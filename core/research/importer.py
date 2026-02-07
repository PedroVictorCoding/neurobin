from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
import logging
import time
import xml.etree.ElementTree as ET

import requests
from django.utils import timezone
from django.db import close_old_connections

from django.contrib.auth import get_user_model
from .models import ResearchSnippet, SnippetTag, SnippetTagging, ResearchImportJob


logger = logging.getLogger(__name__)

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"


@dataclass
class PubMedArticle:
    pmid: str
    title: str
    abstract: str
    journal: str
    pubdate: str
    doi: str


def _safe_text(node: Optional[ET.Element]) -> str:
    if node is None:
        return ""
    text = "".join(node.itertext()).strip()
    return text


def _join_abstract(abstract_nodes: Iterable[ET.Element]) -> str:
    parts: List[str] = []
    for node in abstract_nodes:
        label = node.attrib.get("Label")
        text = _safe_text(node)
        if not text:
            continue
        if label:
            parts.append(f"{label}: {text}")
        else:
            parts.append(text)
    return "\n".join(parts).strip()


def _parse_pubmed_xml(xml_text: str) -> List[PubMedArticle]:
    root = ET.fromstring(xml_text)
    articles: List[PubMedArticle] = []

    for article in root.findall(".//PubmedArticle"):
        pmid = _safe_text(article.find(".//PMID"))
        title = _safe_text(article.find(".//ArticleTitle"))
        abstract = _join_abstract(article.findall(".//AbstractText"))
        journal = _safe_text(article.find(".//Journal/Title"))

        pubdate = (
            _safe_text(article.find(".//JournalIssue/PubDate/Year"))
            or _safe_text(article.find(".//JournalIssue/PubDate/MedlineDate"))
        )

        doi = ""
        for id_node in article.findall(".//ArticleId"):
            if id_node.attrib.get("IdType") == "doi":
                doi = _safe_text(id_node)
                break

        if not pmid:
            continue

        articles.append(
            PubMedArticle(
                pmid=pmid,
                title=title,
                abstract=abstract,
                journal=journal,
                pubdate=pubdate,
                doi=doi,
            )
        )

    return articles


def _pubmed_get(endpoint: str, params: dict, *, rate_limit: float = 0.25) -> Optional[requests.Response]:
    time.sleep(rate_limit)
    try:
        response = requests.get(f"{PUBMED_BASE}{endpoint}", params=params, timeout=30)
    except requests.RequestException as exc:
        logger.warning("PubMed request failed: %s", exc)
        return None
    if response.status_code != 200:
        logger.warning("PubMed HTTP %s for %s", response.status_code, response.url)
        return None
    return response


def search_pubmed_ids(term: str, *, retmax: int = 20, api_key: Optional[str] = None, email: Optional[str] = None) -> List[str]:
    params = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": min(retmax, 50),
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email

    response = _pubmed_get("esearch.fcgi", params)
    if not response:
        return []
    data = response.json()
    return data.get("esearchresult", {}).get("idlist", []) or []


def fetch_pubmed_articles(ids: List[str], *, api_key: Optional[str] = None, email: Optional[str] = None) -> List[PubMedArticle]:
    if not ids:
        return []

    params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key
    if email:
        params["email"] = email

    response = _pubmed_get("efetch.fcgi", params)
    if not response:
        return []
    return _parse_pubmed_xml(response.text)


def _build_query(compound) -> str:
    names = [compound.name]
    if compound.aliases:
        aliases = [a.strip() for a in compound.aliases.split(",") if a.strip()]
        aliases = [a for a in aliases if len(a) >= 3]
        names.extend(aliases[:4])

    terms = [f"\"{name}\"[Title/Abstract]" for name in names]
    if not terms:
        return compound.name
    return " OR ".join(terms)


def _infer_snippet_type(title: str, abstract: str) -> str:
    text = f"{title} {abstract}".lower()
    if any(k in text for k in ("clinical", "trial", "randomized", "double-blind", "phase i", "phase ii", "phase iii")):
        return "clinical"
    if any(k in text for k in ("safety", "toxic", "toxicity", "adverse", "carcinogen", "mutagen")):
        return "safety"
    if any(k in text for k in ("interaction", "drug-drug", "cyp", "inhibitor", "substrate")):
        return "interaction"
    if any(k in text for k in ("dose", "dosage", "pharmacokinetic", "pk/")):
        return "dosage"
    if any(k in text for k in ("mechanism", "binding", "receptor", "agonist", "antagonist")):
        return "mechanism"
    if any(k in text for k in ("metabolism", "pharmacology", "bioavailability", "absorption")):
        return "pharmacology"
    return "general"


def _select_tags(snippet_type: str, title: str, abstract: str) -> List[SnippetTag]:
    tags = []
    text = f"{title} {abstract}".lower()
    tag_by_name = {t.name: t for t in SnippetTag.objects.all()}

    def add(name: str):
        tag = tag_by_name.get(name)
        if tag and tag not in tags:
            tags.append(tag)

    if snippet_type == "clinical":
        add("clinical-trial")
    if snippet_type == "safety":
        add("safety")
    if snippet_type == "mechanism":
        add("mechanism")
    if snippet_type == "pharmacology":
        add("pharmacology")
    if snippet_type == "interaction":
        add("interactions")
    if snippet_type == "dosage":
        add("dosage")

    if "metabolism" in text or "cyp" in text or "hepatic" in text:
        add("metabolism")
    if "neuro" in text:
        add("neuroscience")
    if "cognitive" in text:
        add("cognitive")
    if "subjective" in text:
        add("subjective")

    return tags


def import_pubmed_for_compound(
    compound,
    *,
    requested_by=None,
    max_results: int = 20,
    query: Optional[str] = None,
    api_key: Optional[str] = None,
    email: Optional[str] = None,
) -> tuple[int, str]:
    query = (query or _build_query(compound)).strip()
    cap = min(max_results, 10)
    ids = search_pubmed_ids(query, retmax=cap, api_key=api_key, email=email)
    if not ids:
        return 0, query

    articles = fetch_pubmed_articles(ids, api_key=api_key, email=email)
    imported = 0
    creator = requested_by
    if creator is None:
        User = get_user_model()
        creator = User.objects.filter(is_superuser=True).order_by("id").first()
    if creator is None:
        raise ValueError("A requesting user (or a superuser) is required to create snippets.")

    existing = ResearchSnippet.objects.filter(compound=compound)
    existing_dois = set(
        d.lower()
        for d in existing.exclude(doi="").values_list("doi", flat=True)
        if d
    )
    existing_titles = set(
        t.strip().lower()
        for t in existing.exclude(title="").values_list("title", flat=True)
        if t
    )

    for article in articles:
        source_url = f"https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/"
        if ResearchSnippet.objects.filter(compound=compound, source_url=source_url).exists():
            continue
        if article.doi and article.doi.lower() in existing_dois:
            continue
        if article.title and article.title.strip().lower() in existing_titles:
            continue

        snippet_type = _infer_snippet_type(article.title, article.abstract)
        content_parts = []
        if article.abstract:
            content_parts.append(f"Abstract:\n{article.abstract}")
        if article.journal or article.pubdate:
            meta = " | ".join([p for p in [article.journal, article.pubdate] if p])
            if meta:
                content_parts.append(f"Source: {meta}")
        if not content_parts:
            content_parts.append("Summary not available from PubMed.")

        snippet = ResearchSnippet.objects.create(
            title=article.title or f"PubMed article {article.pmid}",
            content="\n\n".join(content_parts),
            compound=compound,
            snippet_type=snippet_type,
            visibility="public",
            status="submitted",
            created_by=creator,
            ai_generated=False,
            ai_summary="",
            source_title=article.title or "",
            source_url=source_url,
            doi=article.doi or "",
        )

        tags = _select_tags(snippet_type, article.title, article.abstract)
        for tag in tags:
            SnippetTagging.objects.get_or_create(
                snippet=snippet,
                tag=tag,
                defaults={"tagged_by": requested_by},
            )

        imported += 1

    return imported, query


def process_import_job(job_id: int) -> None:
    close_old_connections()
    job = ResearchImportJob.objects.select_related("compound", "requested_by").filter(id=job_id).first()
    if not job or job.status != "queued":
        return

    job.status = "running"
    job.started_at = timezone.now()
    job.error_message = ""
    job.save(update_fields=["status", "started_at", "error_message"])

    try:
        imported, query = import_pubmed_for_compound(
            job.compound,
            requested_by=job.requested_by,
            max_results=job.max_results,
            query=job.query or None,
        )
        job.imported_count = imported
        job.query = query
        job.status = "completed"
        job.finished_at = timezone.now()
        job.save(update_fields=["imported_count", "query", "status", "finished_at"])
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at"])
    finally:
        close_old_connections()
