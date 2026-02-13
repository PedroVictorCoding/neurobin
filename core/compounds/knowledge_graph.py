from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from research.importer import fetch_pubmed_articles, search_pubmed_ids

from .interaction_engine import canonicalize_mechanism
from .models import (
    Compound,
    CompoundMechanismOfAction,
    CompoundKnowledgeGraphEdge,
    CompoundKnowledgeGraphRun,
    CompoundTargetInteraction,
    Target,
    normalize_compound_lookup_key,
    normalize_target_name,
)


logger = logging.getLogger(__name__)

_ALLOWED_NODE_KINDS = {"compound", "target", "mechanism", "pathway", "gene", "effect", "unknown"}
_ALLOWED_PREDICATES = {
    "inhibits",
    "activates",
    "modulates",
    "binds_to",
    "targets",
    "metabolized_by",
    "increases_effect",
    "decreases_effect",
    "interacts_with",
    "shares_target_with",
    "associated_with",
    "evidence_for",
}
_ALLOWED_EVIDENCE_LEVELS = {"high", "medium", "low", "unknown"}
_INJECTION_RE = re.compile(
    r"(ignore\s+previous|system\s+prompt|developer\s+message|```|<script|javascript:)",
    re.IGNORECASE,
)
_MODEL_LIMITS = {
    # Conservative ceilings based on current model-tier limits.
    "gemini-2.5-flash": {"rpm": 5, "rpd": 20},
    "gemini-2.5-pro": {"rpm": 15, "rpd": 1500},
    "gemini-2-flash": {"rpm": 15, "rpd": 1500},
    "gemini-2-flash-exp": {"rpm": 15, "rpd": 1500},
    "gemini-2-flash-lite": {"rpm": 15, "rpd": 1500},
    "gemini-2-pro-exp": {"rpm": 15, "rpd": 1500},
}
_MODEL_FALLBACK_ORDER = [
    "gemini-2-flash",
    "gemini-2-flash-lite",
    "gemini-2.5-pro",
    "gemini-2-pro-exp",
    "gemini-2-flash-exp",
    "gemini-2.5-flash",
]
_TARGET_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENE_SYMBOL_RE = re.compile(r"^[A-Za-z0-9\-]{2,20}$")
_TARGET_FUZZY_SCORE_THRESHOLD = 0.84
_TARGET_FUZZY_SINGLE_TOKEN_THRESHOLD = 0.90
_MAX_FUZZY_CANDIDATES = 120


@dataclass
class _SanitizedRelation:
    subject_kind: str
    subject_label: str
    predicate: str
    object_kind: str
    object_label: str
    related_compound_name: str
    related_target_name: str
    canonical_mechanism: str
    confidence_score: float
    evidence_level: str
    source_title: str
    source_url: str
    evidence_snippet: str


@dataclass
class _TargetCandidate:
    target: Target
    normalized_name: str
    lookup_key: str
    tokens: set[str]
    trigrams: set[str]
    gene_name_lc: str
    gene_lookup_key: str


def _setting_int(name: str, default: int) -> int:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.getenv(name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _setting_float(name: str, default: float) -> float:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.getenv(name)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _gemini_api_key() -> str:
    return str(getattr(settings, "GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")).strip()


def _gemini_model() -> str:
    return str(getattr(settings, "GEMINI_MODEL", "") or os.getenv("GEMINI_MODEL", "gemini-2-flash")).strip()


def _gemini_model_priority() -> list[str]:
    raw = getattr(settings, "GEMINI_MODEL_PRIORITY", None)
    if raw is None:
        raw = os.getenv("GEMINI_MODEL_PRIORITY", "")

    candidates: list[str] = []
    if isinstance(raw, (list, tuple)):
        candidates.extend(str(item).strip() for item in raw if str(item).strip())
    else:
        text = str(raw or "").strip()
        if text:
            candidates.extend(part.strip() for part in text.split(",") if part.strip())

    configured = _gemini_model()
    if configured:
        candidates.insert(0, configured)
    candidates.extend(_MODEL_FALLBACK_ORDER)

    deduped: list[str] = []
    seen = set()
    for model in candidates:
        key = model.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _normalize_predicate(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")


def _normalize_node_kind(value: str) -> str:
    kind = (value or "").strip().lower()
    if kind not in _ALLOWED_NODE_KINDS:
        return "unknown"
    return kind


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def _safe_text(value: Any, *, limit: int = 255) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _safe_snippet(value: Any, *, limit: int = 600) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _normalize_target_lookup_key(raw: str | None) -> str:
    text = normalize_target_name(raw).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _target_tokens(raw: str | None) -> set[str]:
    text = normalize_target_name(raw).lower().replace("5-ht", "5ht")
    return set(_TARGET_TOKEN_RE.findall(text))


def _char_trigrams(text: str) -> set[str]:
    if not text:
        return set()
    if len(text) <= 3:
        return {text}
    return {text[idx : idx + 3] for idx in range(len(text) - 2)}


def _token_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    shared = len(left & right)
    denom = max(len(left), len(right))
    return (shared / denom) if denom else 0.0


def _trigram_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union_size = len(left | right)
    if union_size <= 0:
        return 0.0
    return len(left & right) / union_size


def _looks_like_gene_symbol(value: str) -> bool:
    return bool(_GENE_SYMBOL_RE.match(value or ""))


def _append_unique_note(existing: str, line: str) -> str:
    base = (existing or "").strip()
    addition = (line or "").strip()
    if not addition:
        return base
    if addition in base:
        return base
    if not base:
        return addition
    return f"{base}\n{addition}"


class _TargetResolver:
    def __init__(self) -> None:
        self._by_id: dict[int, _TargetCandidate] = {}
        self._by_exact_name_lc: dict[str, int] = {}
        self._by_exact_gene_lc: dict[str, int] = {}
        self._by_gene_key: dict[str, set[int]] = {}
        self._by_prefix: dict[str, set[int]] = {}
        self._by_token: dict[str, set[int]] = {}
        self._all_ids: set[int] = set()
        for target in Target.objects.only("id", "name", "gene_name", "target_type", "type"):
            self._index_target(target)

    def _index_target(self, target: Target) -> None:
        normalized_name = normalize_target_name(target.name or "")
        lookup_key = _normalize_target_lookup_key(normalized_name)
        if not normalized_name or not lookup_key:
            return

        gene_name_lc = (target.gene_name or "").strip().lower()
        gene_lookup_key = normalize_compound_lookup_key(target.gene_name or "")
        tokens = _target_tokens(normalized_name)
        trigrams = _char_trigrams(lookup_key)
        candidate = _TargetCandidate(
            target=target,
            normalized_name=normalized_name,
            lookup_key=lookup_key,
            tokens=tokens,
            trigrams=trigrams,
            gene_name_lc=gene_name_lc,
            gene_lookup_key=gene_lookup_key,
        )
        self._by_id[target.id] = candidate
        self._all_ids.add(target.id)
        self._by_exact_name_lc.setdefault(normalized_name.lower(), target.id)
        if gene_name_lc:
            self._by_exact_gene_lc.setdefault(gene_name_lc, target.id)
        if gene_lookup_key:
            self._by_gene_key.setdefault(gene_lookup_key, set()).add(target.id)
        self._by_prefix.setdefault(lookup_key[:4], set()).add(target.id)
        for token in tokens:
            self._by_token.setdefault(token, set()).add(target.id)

    def _target_by_id(self, target_id: int | None) -> Target | None:
        if not target_id:
            return None
        candidate = self._by_id.get(target_id)
        return candidate.target if candidate else None

    def _resolve_exact(self, label: str, *, allowed_ids: set[int] | None = None) -> tuple[Target | None, str]:
        normalized = normalize_target_name(label)
        if not normalized:
            return None, "none"

        name_lc = normalized.lower()
        target_id = self._by_exact_name_lc.get(name_lc)
        if target_id and (allowed_ids is None or target_id in allowed_ids):
            return self._target_by_id(target_id), "exact"

        gene_lc = label.strip().lower()
        target_id = self._by_exact_gene_lc.get(gene_lc)
        if target_id and (allowed_ids is None or target_id in allowed_ids):
            return self._target_by_id(target_id), "exact"

        gene_key = normalize_compound_lookup_key(label)
        if gene_key:
            gene_ids = self._by_gene_key.get(gene_key) or set()
            for target_id in gene_ids:
                if allowed_ids is None or target_id in allowed_ids:
                    return self._target_by_id(target_id), "exact"

        return None, "none"

    def _prefilter_candidate_ids(
        self,
        *,
        lookup_key: str,
        tokens: set[str],
        trigrams: set[str],
        allowed_ids: set[int] | None = None,
    ) -> list[int]:
        if allowed_ids is None:
            candidate_ids: set[int] = set()
            for token in tokens:
                candidate_ids.update(self._by_token.get(token, set()))
            candidate_ids.update(self._by_prefix.get(lookup_key[:4], set()))
            if not candidate_ids:
                candidate_ids = set(self._all_ids)
        else:
            candidate_ids = set(allowed_ids)

        ranked: list[tuple[float, int]] = []
        query_len = max(1, len(lookup_key))
        for target_id in candidate_ids:
            candidate = self._by_id.get(target_id)
            if not candidate:
                continue
            cand_len = max(1, len(candidate.lookup_key))
            length_ratio = query_len / cand_len
            if query_len >= 5 and (length_ratio < 0.45 or length_ratio > 2.35):
                continue

            token_score = _token_overlap_ratio(tokens, candidate.tokens)
            trigram_score = _trigram_similarity(trigrams, candidate.trigrams)
            contains = lookup_key in candidate.lookup_key or candidate.lookup_key in lookup_key
            if token_score <= 0 and trigram_score < 0.18 and not contains:
                continue

            quick_score = (trigram_score * 0.58) + (token_score * 0.32) + (0.10 if contains else 0.0)
            if lookup_key[:3] and candidate.lookup_key.startswith(lookup_key[:3]):
                quick_score += 0.05
            ranked.append((quick_score, target_id))

        ranked.sort(reverse=True, key=lambda item: item[0])
        return [target_id for _, target_id in ranked[:_MAX_FUZZY_CANDIDATES]]

    def _fuzzy_best(
        self,
        *,
        label: str,
        lookup_key: str,
        tokens: set[str],
        trigrams: set[str],
        allowed_ids: set[int] | None = None,
    ) -> tuple[Target | None, float]:
        short_query = len(tokens) <= 1
        threshold = _TARGET_FUZZY_SINGLE_TOKEN_THRESHOLD if short_query else _TARGET_FUZZY_SCORE_THRESHOLD
        if allowed_ids:
            threshold = max(0.72, threshold - 0.10)
        candidates = self._prefilter_candidate_ids(
            lookup_key=lookup_key,
            tokens=tokens,
            trigrams=trigrams,
            allowed_ids=allowed_ids,
        )
        if not candidates:
            return None, 0.0

        normalized_label = normalize_target_name(label)
        best_target: Target | None = None
        best_score = 0.0
        second_best = 0.0
        for target_id in candidates:
            candidate = self._by_id.get(target_id)
            if not candidate:
                continue
            ratio = difflib.SequenceMatcher(None, lookup_key, candidate.lookup_key).ratio()
            word_ratio = difflib.SequenceMatcher(None, normalized_label.lower(), candidate.normalized_name.lower()).ratio()
            token_score = _token_overlap_ratio(tokens, candidate.tokens)
            trigram_score = _trigram_similarity(trigrams, candidate.trigrams)
            contains = lookup_key in candidate.lookup_key or candidate.lookup_key in lookup_key
            score = (
                ratio * 0.50
                + word_ratio * 0.20
                + token_score * 0.15
                + trigram_score * 0.10
                + (0.05 if contains else 0.0)
            )
            if score > best_score:
                second_best = best_score
                best_score = score
                best_target = candidate.target
            elif score > second_best:
                second_best = score

        if best_target is None:
            return None, 0.0
        if best_score < threshold:
            return None, best_score
        if best_score < 0.95 and (best_score - second_best) < 0.02:
            return None, best_score
        return best_target, best_score

    def resolve(self, label: str, *, allowed_ids: set[int] | None = None) -> tuple[Target | None, str]:
        normalized = normalize_target_name(label)
        lookup_key = _normalize_target_lookup_key(normalized)
        if not normalized or not lookup_key:
            return None, "none"

        exact, mode = self._resolve_exact(normalized, allowed_ids=allowed_ids)
        if exact:
            return exact, mode

        tokens = _target_tokens(normalized)
        trigrams = _char_trigrams(lookup_key)
        best, score = self._fuzzy_best(
            label=normalized,
            lookup_key=lookup_key,
            tokens=tokens,
            trigrams=trigrams,
            allowed_ids=allowed_ids,
        )
        if best:
            logger.debug("Fuzzy matched target '%s' -> '%s' (score=%.3f)", label, best.name, score)
            return best, "fuzzy"
        return None, "none"

    def create_target(self, label: str) -> Target | None:
        normalized = normalize_target_name(label)
        if not normalized:
            return None
        normalized = _safe_text(normalized, limit=255)
        if len(normalized) < 3:
            return None

        existing_id = self._by_exact_name_lc.get(normalized.lower())
        if existing_id:
            existing = self._target_by_id(existing_id)
            if existing:
                return existing

        defaults: dict[str, Any] = {"target_type": "unknown", "type": "unknown"}
        if _looks_like_gene_symbol(normalized) and len(normalized) <= 20:
            defaults["gene_name"] = normalized.upper()

        try:
            target = Target.objects.create(name=normalized, **defaults)
        except IntegrityError:
            target = Target.objects.filter(name__iexact=normalized).first()
            if not target:
                return None
        self._index_target(target)
        return target


def _is_safe_public_url(url: str) -> bool:
    if not url:
        return True
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost"}:
        return False
    if host.startswith("127.") or host.startswith("10.") or host.startswith("192.168.") or host.startswith("169.254."):
        return False
    return True


def _build_db_context(compound: Compound) -> dict[str, Any]:
    interactions = list(
        CompoundTargetInteraction.objects.filter(compound=compound)
        .select_related("target")
        .order_by("target__name", "mechanism")
    )
    db_targets = []
    for row in interactions[:40]:
        db_targets.append(
            {
                "target": row.target.name,
                "gene": row.target.gene_name or "",
                "mechanism": row.mechanism,
                "affinity": row.affinity_level,
                "notes": (row.notes or "")[:240],
            }
        )

    related_by_target = (
        CompoundTargetInteraction.objects.filter(target__in=[row.target for row in interactions])
        .exclude(compound=compound)
        .select_related("compound", "target")
        .order_by("compound__name", "target__name")[:80]
    )
    related_compounds = []
    seen_pairs = set()
    for row in related_by_target:
        pair_key = (row.compound_id, row.target_id, row.mechanism)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        related_compounds.append(
            {
                "compound": row.compound.name,
                "target": row.target.name,
                "mechanism": row.mechanism,
            }
        )

    return {
        "compound": {
            "name": compound.name,
            "aliases": [a.strip() for a in (compound.aliases or "").split(",") if a.strip()],
            "smiles": (compound.smiles or "")[:200],
        },
        "known_interactions": db_targets,
        "related_compounds_by_shared_target": related_compounds,
    }


def _fetch_pubmed_context(compound: Compound, *, max_results: int = 5) -> list[dict[str, str]]:
    query_terms = [compound.name]
    if compound.aliases:
        query_terms.extend([a.strip() for a in compound.aliases.split(",") if a.strip()][:3])
    query = " OR ".join(f"\"{term}\"[Title/Abstract]" for term in query_terms if term)
    if not query:
        query = f"\"{compound.name}\"[Title/Abstract]"

    try:
        ids = search_pubmed_ids(query, retmax=max(1, min(max_results, 8)))
        articles = fetch_pubmed_articles(ids[:max_results])
    except Exception as exc:
        logger.warning("PubMed context fetch failed for %s: %s", compound.name, exc)
        return []

    rows: list[dict[str, str]] = []
    for article in articles[:max_results]:
        rows.append(
            {
                "title": _safe_text(article.title, limit=500),
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/",
                "snippet": _safe_snippet(article.abstract, limit=500),
                "doi": _safe_text(article.doi, limit=120),
            }
        )
    return rows


def _build_request_hash(compound: Compound, *, include_internet: bool, max_edges: int) -> str:
    interactions = list(
        CompoundTargetInteraction.objects.filter(compound=compound)
        .select_related("target")
        .order_by("target__name", "mechanism")
        .values_list("target__name", "mechanism", "affinity_level")
    )
    payload = {
        "compound_id": compound.id,
        "name": compound.name,
        "aliases": compound.aliases or "",
        "smiles": compound.smiles or "",
        "interactions": list(interactions),
        "include_internet": bool(include_internet),
        "max_edges": int(max_edges),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _extract_json_payload(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return {}
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _cache_increment(key: str, *, timeout: int) -> int:
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return int(cache.incr(key))
    except Exception:
        current = int(cache.get(key, 0) or 0) + 1
        cache.set(key, current, timeout=timeout)
        return current


def _model_limits(model: str) -> dict[str, int]:
    limits = _MODEL_LIMITS.get(model, {"rpm": 15, "rpd": 1500}).copy()
    default_rpm = int(limits.get("rpm", 15) or 15)
    default_rpd = int(limits.get("rpd", 1500) or 1500)
    limits["rpm"] = _setting_int(f"GEMINI_GRAPH_RPM_{model.upper().replace('-', '_')}", default_rpm)
    limits["rpd"] = _setting_int(f"GEMINI_GRAPH_RPD_{model.upper().replace('-', '_')}", default_rpd)
    limits["rpm"] = max(1, limits["rpm"])
    limits["rpd"] = max(1, limits["rpd"])
    return limits


def _enforce_global_interval(model: str, *, rpm: int) -> None:
    min_interval = _setting_float("GEMINI_GRAPH_MIN_INTERVAL_SECONDS", 4.1)
    model_interval = (60.0 / float(max(1, rpm))) + 0.05
    min_interval = max(min_interval, model_interval)
    if min_interval <= 0:
        return
    key = f"gemini_graph:last_call_ts:{model}"
    now = time.time()
    last = cache.get(key)
    if last is not None:
        try:
            wait_for = float(last) + min_interval - now
        except (TypeError, ValueError):
            wait_for = 0.0
        if wait_for > 0:
            time.sleep(wait_for)
    cache.set(key, time.time(), timeout=120)


def _acquire_model_budget(model: str) -> None:
    limits = _model_limits(model)
    rpm = int(limits["rpm"])
    rpd = int(limits["rpd"])
    now = timezone.now()
    minute_key = f"gemini_graph:{model}:minute:{now.strftime('%Y%m%d%H%M')}"
    day_key = f"gemini_graph:{model}:day:{now.strftime('%Y%m%d')}"

    minute_count = int(cache.get(minute_key, 0) or 0)
    if minute_count >= rpm:
        raise RuntimeError(f"RPM budget reached for model {model}")

    day_count = int(cache.get(day_key, 0) or 0)
    if day_count >= rpd:
        raise RuntimeError(f"RPD budget reached for model {model}")

    _cache_increment(minute_key, timeout=90)
    _cache_increment(day_key, timeout=60 * 60 * 26)


def _build_prompt(
    *,
    db_context: dict[str, Any],
    internet_context: list[dict[str, str]],
    max_edges: int,
) -> str:
    instructions = {
        "task": "Generate mechanistic relationship graph edges centered on the anchor compound.",
        "constraints": [
            "Use only grounded evidence from DB context and provided internet snippets.",
            "Do not invent citations.",
            "Prefer mechanistic predicates.",
            f"Return at most {max_edges} relations.",
        ],
        "output_json": {
            "relations": [
                {
                    "subject": "string",
                    "subject_kind": "compound|target|mechanism|pathway|gene|effect|unknown",
                    "predicate": "inhibits|activates|modulates|binds_to|targets|metabolized_by|increases_effect|decreases_effect|interacts_with|shares_target_with|associated_with|evidence_for",
                    "object": "string",
                    "object_kind": "compound|target|mechanism|pathway|gene|effect|unknown",
                    "related_compound": "string optional",
                    "related_target": "string optional",
                    "mechanism": "free text mechanism term",
                    "confidence": "number 0..1",
                    "evidence_level": "high|medium|low|unknown",
                    "source_title": "string",
                    "source_url": "string",
                    "evidence_snippet": "short string",
                }
            ]
        },
    }
    payload = {
        "instructions": instructions,
        "db_context": db_context,
        "internet_context": internet_context[:8],
    }
    return json.dumps(payload, ensure_ascii=True)


def _call_gemini(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = _gemini_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    timeout = _setting_int("GEMINI_GRAPH_TIMEOUT_SECONDS", 45)
    max_retries = max(1, _setting_int("GEMINI_GRAPH_MAX_RETRIES", 2))
    candidates = _gemini_model_priority()
    last_error = None
    for model in candidates:
        model_limits = _model_limits(model)
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            ],
        }

        for attempt in range(1, max_retries + 1):
            try:
                _acquire_model_budget(model)
                _enforce_global_interval(model, rpm=int(model_limits["rpm"]))
            except RuntimeError as exc:
                last_error = exc
                logger.info("Skipping model %s: %s", model, exc)
                break

            try:
                response = requests.post(
                    endpoint,
                    params={"key": api_key},
                    json=body,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("Gemini request failed (%s, attempt %s/%s): %s", model, attempt, max_retries, exc)
                time.sleep(min(3 * attempt, 8))
                continue

            if response.status_code == 429:
                last_error = RuntimeError(f"Gemini HTTP 429 on model {model}")
                logger.warning("Model %s hit provider rate limit, trying fallback.", model)
                break

            if response.status_code in {500, 502, 503, 504} and attempt < max_retries:
                time.sleep(min(3 * attempt, 8))
                continue

            if response.status_code >= 400:
                last_error = RuntimeError(f"Gemini HTTP {response.status_code}: {response.text[:400]}")
                logger.warning("Model %s returned HTTP %s, trying fallback.", model, response.status_code)
                break

            raw = response.json()
            raw["_model_used"] = model
            response_candidates = raw.get("candidates") or []
            if not response_candidates:
                return {}, raw

            parts = ((response_candidates[0].get("content") or {}).get("parts") or [])
            text = "".join(str(part.get("text", "")) for part in parts)
            return _extract_json_payload(text), raw

    raise RuntimeError(f"Gemini request failed after retries: {last_error}")


def _moderate_relations(
    relations: list[dict[str, Any]],
    *,
    max_edges: int,
) -> tuple[list[_SanitizedRelation], int, list[str]]:
    approved: list[_SanitizedRelation] = []
    rejected = 0
    notes: list[str] = []

    seen = set()
    for row in relations[: max_edges * 3]:
        if not isinstance(row, dict):
            rejected += 1
            notes.append("Dropped non-object relation.")
            continue

        subject = _safe_text(row.get("subject"), limit=255)
        obj = _safe_text(row.get("object"), limit=255)
        predicate = _normalize_predicate(_safe_text(row.get("predicate"), limit=100))
        snippet = _safe_snippet(row.get("evidence_snippet"), limit=600)
        source_url = _safe_text(row.get("source_url"), limit=500)

        if not subject or not obj or not predicate:
            rejected += 1
            notes.append("Dropped relation missing subject/object/predicate.")
            continue
        if predicate not in _ALLOWED_PREDICATES:
            rejected += 1
            notes.append(f"Dropped unsupported predicate: {predicate}")
            continue
        if _INJECTION_RE.search(subject) or _INJECTION_RE.search(obj) or _INJECTION_RE.search(snippet):
            rejected += 1
            notes.append("Dropped relation due to prompt-injection markers.")
            continue
        if not _is_safe_public_url(source_url):
            rejected += 1
            notes.append("Dropped relation with unsafe source URL.")
            continue

        subject_kind = _normalize_node_kind(str(row.get("subject_kind", "")))
        object_kind = _normalize_node_kind(str(row.get("object_kind", "")))
        evidence_level = str(row.get("evidence_level", "unknown")).strip().lower()
        if evidence_level not in _ALLOWED_EVIDENCE_LEVELS:
            evidence_level = "unknown"

        mechanism = canonicalize_mechanism(
            action_type=row.get("mechanism"),
            mechanism_of_action=predicate,
            notes=snippet,
        )
        normalized = _SanitizedRelation(
            subject_kind=subject_kind,
            subject_label=subject,
            predicate=predicate,
            object_kind=object_kind,
            object_label=obj,
            related_compound_name=_safe_text(row.get("related_compound"), limit=255),
            related_target_name=_safe_text(row.get("related_target"), limit=255),
            canonical_mechanism=mechanism,
            confidence_score=_clamp_confidence(row.get("confidence")),
            evidence_level=evidence_level,
            source_title=_safe_text(row.get("source_title"), limit=500),
            source_url=source_url,
            evidence_snippet=snippet,
        )
        dedupe_key = (
            normalized.subject_label.lower(),
            normalized.predicate,
            normalized.object_label.lower(),
            normalized.source_url.lower(),
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        approved.append(normalized)
        if len(approved) >= max_edges:
            break

    return approved, rejected, notes


def _compound_lookup() -> dict[str, Compound]:
    lookup: dict[str, Compound] = {}
    for compound in Compound.objects.all().only("id", "name", "aliases"):
        keys = {normalize_compound_lookup_key(compound.name)}
        aliases = [a.strip() for a in (compound.aliases or "").split(",") if a.strip()]
        keys.update(normalize_compound_lookup_key(alias) for alias in aliases)
        for key in keys:
            if key and key not in lookup:
                lookup[key] = compound
    return lookup


def _target_label_candidates(relation: _SanitizedRelation) -> list[tuple[str, bool]]:
    candidates: list[tuple[str, bool]] = []
    if relation.related_target_name:
        candidates.append((relation.related_target_name, True))
    if relation.subject_kind in {"target", "gene"}:
        candidates.append((relation.subject_label, True))
    if relation.object_kind in {"target", "gene"}:
        candidates.append((relation.object_label, True))
    if not candidates:
        candidates.append((relation.object_label, False))
        candidates.append((relation.subject_label, False))

    deduped: list[tuple[str, bool]] = []
    seen = set()
    for label, allow_create in candidates:
        cleaned = _safe_text(label, limit=255)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append((cleaned, allow_create))
    return deduped


def _resolve_entities(
    relation: _SanitizedRelation,
    *,
    compound_by_key: dict[str, Compound],
    target_resolver: _TargetResolver,
    existing_target_ids: set[int],
    create_missing_target: bool,
) -> tuple[Compound | None, Target | None, str]:
    related_compound = None
    if relation.related_compound_name:
        key = normalize_compound_lookup_key(relation.related_compound_name)
        related_compound = compound_by_key.get(key)
    if related_compound is None:
        for label in (relation.subject_label, relation.object_label):
            key = normalize_compound_lookup_key(label)
            candidate = compound_by_key.get(key)
            if candidate:
                related_compound = candidate
                break

    related_target = None
    target_match_mode = "none"
    target_labels = _target_label_candidates(relation)
    if existing_target_ids:
        for label, _ in target_labels:
            candidate, mode = target_resolver.resolve(label, allowed_ids=existing_target_ids)
            if candidate:
                related_target = candidate
                target_match_mode = f"compound_{mode}"
                break
    if related_target is None:
        for label, _ in target_labels:
            candidate, mode = target_resolver.resolve(label)
            if candidate:
                related_target = candidate
                target_match_mode = mode
                break
    if related_target is None and create_missing_target:
        for label, allow_create in target_labels:
            if not allow_create:
                continue
            candidate = target_resolver.create_target(label)
            if candidate:
                related_target = candidate
                target_match_mode = "created"
                break

    return related_compound, related_target, target_match_mode


def _resolve_relation_mechanism(relation: _SanitizedRelation, *, existing_mechanisms: set[str]) -> str:
    if relation.canonical_mechanism and relation.canonical_mechanism != "unknown":
        return relation.canonical_mechanism

    inferred = canonicalize_mechanism(
        action_type=relation.predicate,
        mechanism_of_action=f"{relation.subject_label} {relation.object_label}",
        notes=relation.evidence_snippet,
    )
    if inferred != "unknown":
        return inferred

    if not existing_mechanisms:
        return "unknown"

    text_blob = " ".join(
        [
            relation.predicate,
            relation.subject_label,
            relation.object_label,
            relation.evidence_snippet,
        ]
    ).lower()
    for mechanism in sorted(existing_mechanisms):
        mechanism_label = mechanism.replace("_", " ")
        if mechanism_label in text_blob:
            return mechanism
    return "unknown"


def _db_validation_status(
    anchor_compound: Compound,
    mechanism: str,
    *,
    related_compound: Compound | None,
    related_target: Target | None,
) -> str:
    if related_target:
        known = list(
            CompoundTargetInteraction.objects.filter(compound=anchor_compound, target=related_target)
            .values_list("mechanism", flat=True)
        )
        if known:
            if mechanism in known or mechanism == "unknown":
                return "confirmed"
            return "conflicting"
        return "novel"

    if related_compound and related_compound.id != anchor_compound.id:
        shared = CompoundTargetInteraction.objects.filter(
            compound=anchor_compound,
            target__compound_interactions__compound=related_compound,
        ).exists()
        return "confirmed" if shared else "unresolved"

    return "unresolved"


def _upsert_compound_target_relationship(
    *,
    anchor_compound: Compound,
    related_target: Target | None,
    mechanism: str,
    relation: _SanitizedRelation,
    run_id: int,
) -> tuple[bool, bool]:
    if not related_target or not mechanism or mechanism == "unknown":
        return False, False

    note_line = _safe_text(
        f"[KG run {run_id}] {relation.source_title or relation.source_url} :: {relation.evidence_snippet}",
        limit=700,
    )
    defaults = {
        "affinity_level": "unknown",
        "notes": note_line,
        "source": "KnowledgeGraph",
    }
    interaction, created = CompoundTargetInteraction.objects.get_or_create(
        compound=anchor_compound,
        target=related_target,
        mechanism=mechanism,
        defaults=defaults,
    )
    updated = False
    if not created:
        updates: list[str] = []
        new_notes = _append_unique_note(interaction.notes, note_line)
        if new_notes != interaction.notes:
            interaction.notes = new_notes
            updates.append("notes")
        if not interaction.source:
            interaction.source = "KnowledgeGraph"
            updates.append("source")
        if updates:
            interaction.save(update_fields=updates)
            updated = True

    target_type = related_target.target_type if related_target.target_type in {"receptor", "enzyme", "ion_channel", "transporter", "protein", "other"} else ""
    mechanism_obj = CompoundMechanismOfAction.objects.filter(
        target_name=related_target,
        target_interaction=mechanism,
    ).first()
    if mechanism_obj is None:
        try:
            mechanism_obj = CompoundMechanismOfAction.objects.create(
                target_name=related_target,
                target_interaction=mechanism,
                target_type=target_type,
                description=_safe_text(
                    f"Auto-derived from moderated knowledge graph evidence for {anchor_compound.name}.",
                    limit=500,
                ),
            )
        except IntegrityError:
            mechanism_obj = CompoundMechanismOfAction.objects.filter(
                target_name=related_target,
                target_interaction=mechanism,
            ).first()
            if mechanism_obj is None:
                return created, updated
    anchor_compound.mechanism_of_action.add(mechanism_obj)
    return created, updated


def _edge_hash(compound_id: int, relation: _SanitizedRelation) -> str:
    payload = "|".join(
        [
            str(compound_id),
            relation.subject_label.lower(),
            relation.predicate,
            relation.object_label.lower(),
            relation.source_url.lower(),
            relation.canonical_mechanism,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_latest_graph_run(compound: Compound) -> CompoundKnowledgeGraphRun | None:
    return (
        CompoundKnowledgeGraphRun.objects.filter(compound=compound, status__in=["completed", "skipped"])
        .order_by("-created_at")
        .first()
    )


def generate_compound_knowledge_graph(
    *,
    compound: Compound,
    requested_by=None,
    include_internet: bool = True,
    max_edges: int = 25,
    force: bool = False,
) -> tuple[CompoundKnowledgeGraphRun, bool]:
    max_allowed = _setting_int("GEMINI_GRAPH_MAX_EDGES", 30)
    max_edges = max(1, min(int(max_edges), max_allowed))
    request_hash = _build_request_hash(compound, include_internet=include_internet, max_edges=max_edges)

    cooldown_seconds = _setting_int("GEMINI_GRAPH_COOLDOWN_SECONDS", 6 * 60 * 60)
    cooldown_since = timezone.now() - timezone.timedelta(seconds=max(0, cooldown_seconds))
    if not force:
        cached = (
            CompoundKnowledgeGraphRun.objects.filter(
                compound=compound,
                request_hash=request_hash,
                status="completed",
                created_at__gte=cooldown_since,
            )
            .order_by("-created_at")
            .first()
        )
        if cached:
            return cached, True

    run = CompoundKnowledgeGraphRun.objects.create(
        compound=compound,
        requested_by=requested_by,
        status="running",
        model_name=_gemini_model(),
        request_hash=request_hash,
        include_internet=bool(include_internet),
        max_edges=max_edges,
        started_at=timezone.now(),
    )

    try:
        db_context = _build_db_context(compound)
        internet_context = _fetch_pubmed_context(compound, max_results=5) if include_internet else []
        prompt = _build_prompt(
            db_context=db_context,
            internet_context=internet_context,
            max_edges=max_edges,
        )
        parsed_payload, raw_response = _call_gemini(prompt)
        used_model = str((raw_response or {}).get("_model_used", "")).strip()
        if used_model and used_model != run.model_name:
            run.model_name = used_model
            run.save(update_fields=["model_name"])
        relations = parsed_payload.get("relations") or []
        if not isinstance(relations, list):
            relations = []

        approved, rejected_count, moderation_notes = _moderate_relations(relations, max_edges=max_edges)

        compound_by_key = _compound_lookup()
        target_resolver = _TargetResolver()
        apply_relationships = bool(_setting_int("GEMINI_GRAPH_APPLY_RELATIONSHIPS", 1))
        existing_interactions = list(
            CompoundTargetInteraction.objects.filter(compound=compound)
            .select_related("target")
            .only("id", "target_id", "mechanism")
        )
        existing_target_ids = {row.target_id for row in existing_interactions}
        existing_mechanisms = {row.mechanism for row in existing_interactions if row.mechanism}
        stats = {
            "target_fuzzy_matches": 0,
            "targets_created": 0,
            "interactions_created": 0,
            "interactions_updated": 0,
        }
        validated = 0

        with transaction.atomic():
            for relation in approved:
                related_compound, related_target, target_match_mode = _resolve_entities(
                    relation,
                    compound_by_key=compound_by_key,
                    target_resolver=target_resolver,
                    existing_target_ids=existing_target_ids,
                    create_missing_target=apply_relationships,
                )
                if "fuzzy" in target_match_mode:
                    stats["target_fuzzy_matches"] += 1
                if target_match_mode == "created" and related_target:
                    existing_target_ids.add(related_target.id)
                    stats["targets_created"] += 1

                canonical_mechanism = _resolve_relation_mechanism(
                    relation,
                    existing_mechanisms=existing_mechanisms,
                )
                relation.canonical_mechanism = canonical_mechanism
                db_status = _db_validation_status(
                    compound,
                    canonical_mechanism,
                    related_compound=related_compound,
                    related_target=related_target,
                )
                if db_status == "confirmed":
                    validated += 1

                CompoundKnowledgeGraphEdge.objects.create(
                    run=run,
                    compound=compound,
                    subject_kind=relation.subject_kind,
                    subject_label=relation.subject_label,
                    predicate=relation.predicate,
                    object_kind=relation.object_kind,
                    object_label=relation.object_label,
                    related_compound=related_compound if related_compound and related_compound.id != compound.id else None,
                    related_target=related_target,
                    canonical_mechanism=canonical_mechanism,
                    confidence_score=relation.confidence_score,
                    evidence_level=relation.evidence_level,
                    source_title=relation.source_title,
                    source_url=relation.source_url,
                    evidence_snippet=relation.evidence_snippet,
                    db_validation_status=db_status,
                    moderation_status="approved",
                    moderation_reason="",
                    edge_hash=_edge_hash(compound.id, relation),
                )

                if apply_relationships:
                    created, updated = _upsert_compound_target_relationship(
                        anchor_compound=compound,
                        related_target=related_target,
                        mechanism=canonical_mechanism,
                        relation=relation,
                        run_id=run.id,
                    )
                    if created:
                        stats["interactions_created"] += 1
                        if related_target:
                            existing_target_ids.add(related_target.id)
                        existing_mechanisms.add(canonical_mechanism)
                    elif updated:
                        stats["interactions_updated"] += 1

        status = "completed"
        if not approved and rejected_count > 0:
            status = "blocked"

        if apply_relationships:
            moderation_notes.append(
                (
                    "Relationship sync: "
                    f"targets_created={stats['targets_created']} "
                    f"target_fuzzy_matches={stats['target_fuzzy_matches']} "
                    f"interactions_created={stats['interactions_created']} "
                    f"interactions_updated={stats['interactions_updated']}"
                )
            )

        run.status = status
        run.edges_created = len(approved)
        run.edges_rejected = rejected_count
        run.edges_validated = validated
        run.raw_response = raw_response if isinstance(raw_response, dict) else {"raw": str(raw_response)[:4000]}
        run.parsed_output = parsed_payload if isinstance(parsed_payload, dict) else {}
        run.moderation_notes = "\n".join(moderation_notes[:50])
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "model_name",
                "edges_created",
                "edges_rejected",
                "edges_validated",
                "raw_response",
                "parsed_output",
                "moderation_notes",
                "finished_at",
            ]
        )
        return run, False
    except Exception as exc:
        logger.exception("Knowledge graph generation failed for %s", compound.name)
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        return run, False
