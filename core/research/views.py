import base64
import io
import ipaddress
import json
import re
from html import unescape
from urllib.parse import urlencode, urljoin, urlparse

import requests
from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg
from django.db import transaction
from django.utils import timezone

from .models import (
    ResearchSnippet, 
    SnippetReview, 
    SnippetTag, 
    SnippetTagging,
    SnippetComment,
    ResearchSettings,
    UserRole
)
from .forms import (
    ResearchSnippetForm, 
    SnippetReviewForm, 
    SnippetSearchForm,
    AIAnalysisForm,
    ResearchSettingsForm,
    BulkSnippetActionForm
)
from compounds.models import Compound
from .importer import fetch_pubmed_articles, search_pubmed_ids


_GRAPH_CONTEXT_STOPWORDS = {
    "with", "from", "that", "this", "these", "those", "were", "been", "have", "has",
    "into", "their", "there", "than", "then", "when", "where", "which", "while", "study",
    "studies", "effect", "effects", "using", "used", "between", "among", "after", "before",
    "human", "rats", "mice", "male", "female", "data", "results", "analysis", "compound",
    "compounds", "metenolone", "primobolan", "acetate", "steroid", "steroids", "research",
}
_GRAPH_CONTEXT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{3,}")
_GRAPH_NODE_KIND_ALLOWED = {
    "compound", "target", "mechanism", "pathway", "effect", "enzyme", "tissue", "clinical", "concept",
}
_TRIPLE_LINE_RE = re.compile(r"^\s*(.+?)\s*--\s*([A-Za-z_][A-Za-z0-9_\-\s]{1,80})\s*-->\s*(.+?)\s*$")
_PDF_HREF_RE = re.compile(r"""href=["']([^"'#\s>]+?\.pdf(?:\?[^"']*)?)["']""", re.IGNORECASE)
_CITATION_PDF_META_RE = re.compile(
    r"""<meta[^>]+name=["']citation_pdf_url["'][^>]+content=["']([^"']+)["']""",
    re.IGNORECASE,
)


def _compact_text(value, max_len=500):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len]


def _node_id_from_label(label):
    return re.sub(r"[^a-z0-9]+", "_", str(label or "").strip().lower()).strip("_")


def _normalize_relation(value):
    relation = _compact_text(value, 80).lower()
    relation = re.sub(r"[^a-z0-9_]+", "_", relation).strip("_")
    return relation or "associated_with"


def _infer_snippet_type_from_text(title, abstract):
    text = f"{title or ''} {abstract or ''}".lower()
    if any(k in text for k in ("clinical", "trial", "phase i", "phase ii", "phase iii", "double-blind")):
        return "clinical"
    if any(k in text for k in ("safety", "toxic", "toxicity", "adverse", "pathological")):
        return "safety"
    if any(k in text for k in ("interaction", "cyp", "inhibitor", "substrate", "combination")):
        return "interaction"
    if any(k in text for k in ("mechanism", "receptor", "agonist", "antagonist", "binding")):
        return "mechanism"
    if any(k in text for k in ("metabolism", "pharmacology", "bioavailability", "pharmacokinetic")):
        return "pharmacology"
    if any(k in text for k in ("dose", "dosage")):
        return "dosage"
    return "general"


def _build_compound_search_query(compound_name, query):
    base = f"\"{compound_name}\"[Title/Abstract]"
    user_query = (query or "").strip()
    if not user_query or user_query.lower() == compound_name.lower():
        return base
    if compound_name.lower() in user_query.lower():
        return user_query
    return f"({base}) AND ({user_query})"


def _article_payload(article):
    pmid = _compact_text(article.pmid, 32)
    source_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else ""
    return {
        "pmid": pmid,
        "title": _compact_text(article.title, 320),
        "abstract": _compact_text(article.abstract, 4000),
        "journal": _compact_text(article.journal, 220),
        "pubdate": _compact_text(article.pubdate, 64),
        "doi": _compact_text(article.doi, 120),
        "source_url": source_url,
    }


def _extract_graph_text(query, papers):
    chunks = [_compact_text(query, 400)]
    for row in papers[:10]:
        chunks.append(_compact_text(row.get("title", ""), 260))
        chunks.append(_compact_text(row.get("abstract", ""), 500))
    return " ".join([chunk for chunk in chunks if chunk])


def _fallback_graph_context(compound_name, query, papers):
    counts = {}
    for token in _GRAPH_CONTEXT_TOKEN_RE.findall(_extract_graph_text(query, papers).lower()):
        if token in _GRAPH_CONTEXT_STOPWORDS or token.isdigit():
            continue
        counts[token] = counts.get(token, 0) + 1

    ranked = sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    terms = [term.replace("-", " ") for term, _ in ranked[:10]]

    nodes = [{"id": "compound", "label": compound_name, "kind": "compound"}]
    edges = []
    for term in terms:
        node_id = re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")
        if not node_id:
            continue
        nodes.append({"id": node_id, "label": term.title(), "kind": "concept"})
        edges.append({"source": "compound", "target": node_id, "relation": "associated_with"})

    return {
        "source": "fallback",
        "nodes": nodes,
        "edges": edges,
        "subsearch_terms": [node["label"] for node in nodes[1:]],
    }


def _parse_gemini_json_text(raw_text):
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _parse_triple_lines(raw_text):
    triples = []
    for raw_line in str(raw_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _TRIPLE_LINE_RE.match(line)
        if not match:
            continue
        source = _compact_text(match.group(1), 120)
        relation = _normalize_relation(match.group(2))
        target = _compact_text(match.group(3), 120)
        if source and target:
            triples.append({"source": source, "relation": relation, "target": target})
    return triples


def _is_safe_public_url(raw_url):
    parsed = urlparse(str(raw_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return False

    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        return True

    if (
        host_ip.is_private
        or host_ip.is_loopback
        or host_ip.is_link_local
        or host_ip.is_reserved
        or host_ip.is_multicast
        or host_ip.is_unspecified
    ):
        return False
    return True


def _extract_pdf_url_from_html(base_url, html_text):
    html = str(html_text or "")
    candidates = []

    meta_match = _CITATION_PDF_META_RE.search(html)
    if meta_match:
        candidates.append(meta_match.group(1))

    for href in _PDF_HREF_RE.findall(html):
        candidates.append(href)
        if len(candidates) >= 20:
            break

    for candidate in candidates:
        resolved = urljoin(base_url, unescape(str(candidate or "").strip()))
        if _is_safe_public_url(resolved):
            return resolved
    return ""


def _fetch_binary_url(url, timeout_seconds, max_bytes):
    response = requests.get(
        url,
        timeout=timeout_seconds,
        allow_redirects=True,
        stream=True,
        headers={
            "User-Agent": "NeurobinResearch/1.0 (+compound-explorer)",
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
        },
    )
    response.raise_for_status()

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("PDF is too large to analyze.")
        chunks.append(chunk)

    return response.url, b"".join(chunks), str(response.headers.get("Content-Type", "") or "")


def _resolve_pdf_from_research_url(raw_url):
    target_url = str(raw_url or "").strip()
    if not target_url:
        raise ValueError("A paper URL is required.")
    if not _is_safe_public_url(target_url):
        raise ValueError("URL is not allowed. Use a public http(s) paper URL.")

    timeout_seconds = int(getattr(settings, "RESEARCH_REMOTE_FETCH_TIMEOUT_SECONDS", 25) or 25)
    max_pdf_bytes = int(getattr(settings, "RESEARCH_MAX_REMOTE_PDF_BYTES", 12 * 1024 * 1024) or (12 * 1024 * 1024))

    response = requests.get(
        target_url,
        timeout=timeout_seconds,
        allow_redirects=True,
        headers={
            "User-Agent": "NeurobinResearch/1.0 (+compound-explorer)",
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
        },
    )
    response.raise_for_status()

    resolved_url = str(response.url or target_url)
    content_type = str(response.headers.get("Content-Type", "") or "").lower()
    is_pdf = "application/pdf" in content_type or resolved_url.lower().split("?")[0].endswith(".pdf")

    if is_pdf:
        pdf_bytes = response.content or b""
        if len(pdf_bytes) > max_pdf_bytes:
            raise ValueError("PDF is too large to analyze.")
        return {
            "resolved_url": resolved_url,
            "pdf_url": resolved_url,
            "pdf_bytes": pdf_bytes,
        }

    pdf_url = _extract_pdf_url_from_html(resolved_url, response.text)
    if not pdf_url:
        raise ValueError("Could not find a PDF on that page. Please provide a direct PDF URL.")

    final_pdf_url, pdf_bytes, pdf_content_type = _fetch_binary_url(
        pdf_url,
        timeout_seconds=timeout_seconds,
        max_bytes=max_pdf_bytes,
    )
    if "pdf" not in pdf_content_type.lower() and not final_pdf_url.lower().split("?")[0].endswith(".pdf"):
        raise ValueError("Resolved link did not return a PDF document.")
    return {
        "resolved_url": resolved_url,
        "pdf_url": final_pdf_url,
        "pdf_bytes": pdf_bytes,
    }


def _extract_pdf_text_excerpt(pdf_bytes, max_chars=18000):
    if not pdf_bytes:
        return ""
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return ""

    chunks = []
    total_chars = 0
    for page in reader.pages[:10]:
        try:
            page_text = _compact_text(page.extract_text() or "", 4000)
        except Exception:
            page_text = ""
        if not page_text:
            continue
        chunks.append(page_text)
        total_chars += len(page_text)
        if total_chars >= max_chars:
            break

    return _compact_text("\n".join(chunks), max_chars)


def _sanitize_graph_payload(compound_name, payload):
    raw_nodes = (payload.get("nodes") or []) if isinstance(payload, dict) else []
    raw_edges = (payload.get("edges") or []) if isinstance(payload, dict) else []
    raw_terms = (payload.get("subsearch_terms") or []) if isinstance(payload, dict) else []
    raw_triples = (payload.get("triples") or []) if isinstance(payload, dict) else []

    nodes = []
    node_ids = set()
    label_to_id = {}

    def ensure_node(label, kind="concept", preferred_id=""):
        normalized_label = _compact_text(label, 100)
        if not normalized_label:
            return ""
        if normalized_label.lower() == compound_name.lower():
            normalized_label = compound_name
            kind = "compound"
            preferred_id = "compound"

        if preferred_id:
            node_id = _node_id_from_label(preferred_id)
        else:
            node_id = _node_id_from_label(normalized_label)
        if not node_id:
            return ""
        if node_id in node_ids:
            return node_id

        safe_kind = _compact_text(kind, 24).lower()
        if safe_kind not in _GRAPH_NODE_KIND_ALLOWED:
            safe_kind = "concept"
        node_ids.add(node_id)
        label_to_id[normalized_label.lower()] = node_id
        nodes.append({"id": node_id, "label": normalized_label, "kind": safe_kind})
        return node_id

    ensure_node(compound_name, kind="compound", preferred_id="compound")

    for row in raw_nodes[:30]:
        if not isinstance(row, dict):
            continue
        ensure_node(
            row.get("label"),
            kind=row.get("kind") or "concept",
            preferred_id=row.get("id") or "",
        )

    edge_rows = []
    for row in raw_edges[:50]:
        if isinstance(row, dict):
            edge_rows.append({
                "source": row.get("source"),
                "target": row.get("target"),
                "relation": row.get("relation") or row.get("predicate") or "associated_with",
            })

    if isinstance(raw_triples, list):
        for row in raw_triples[:50]:
            if isinstance(row, dict):
                edge_rows.append({
                    "source": row.get("source") or row.get("subject"),
                    "target": row.get("target") or row.get("object"),
                    "relation": row.get("relation") or row.get("predicate") or "associated_with",
                })
            elif isinstance(row, str):
                for triple in _parse_triple_lines(row):
                    edge_rows.append(triple)
    elif isinstance(raw_triples, str):
        edge_rows.extend(_parse_triple_lines(raw_triples))

    edges = []
    edge_ids = set()
    for row in edge_rows:
        source_raw = _compact_text(row.get("source"), 100)
        target_raw = _compact_text(row.get("target"), 100)
        if not source_raw or not target_raw:
            continue

        source_id = ""
        target_id = ""
        source_candidate = _node_id_from_label(source_raw)
        target_candidate = _node_id_from_label(target_raw)
        if source_candidate in node_ids:
            source_id = source_candidate
        else:
            source_id = label_to_id.get(source_raw.lower(), "")
        if target_candidate in node_ids:
            target_id = target_candidate
        else:
            target_id = label_to_id.get(target_raw.lower(), "")

        if not source_id:
            source_id = ensure_node(source_raw, kind="concept")
        if not target_id:
            target_id = ensure_node(target_raw, kind="concept")

        if not source_id or not target_id or source_id == target_id:
            continue

        relation = _normalize_relation(row.get("relation"))
        edge_key = f"{source_id}|{relation}|{target_id}"
        if edge_key in edge_ids:
            continue
        edge_ids.add(edge_key)
        edges.append({"source": source_id, "target": target_id, "relation": relation})

    if not edges:
        for node in nodes:
            if node["id"] == "compound":
                continue
            edge_key = f"compound|associated_with|{node['id']}"
            if edge_key in edge_ids:
                continue
            edge_ids.add(edge_key)
            edges.append({"source": "compound", "target": node["id"], "relation": "associated_with"})

    # Degree-weighted term suggestions for subsearch.
    degree = {}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    subsearch_terms = []
    if isinstance(raw_terms, list):
        for row in raw_terms:
            term = _compact_text(row, 80)
            if term:
                subsearch_terms.append(term)
    if not subsearch_terms:
        ranked_nodes = sorted(
            [row for row in nodes if row["id"] != "compound"],
            key=lambda row: (-degree.get(row["id"], 0), row["label"].lower()),
        )
        subsearch_terms = [row["label"] for row in ranked_nodes[:10]]

    return {
        "source": "gemini",
        "nodes": nodes,
        "edges": edges,
        "subsearch_terms": subsearch_terms,
    }


def _generate_gemini_graph_context(compound_name, query, papers):
    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None

    model_name = str(getattr(settings, "GEMINI_MODEL", "gemini-2-flash") or "gemini-2-flash").strip()
    timeout_seconds = int(getattr(settings, "GEMINI_GRAPH_TIMEOUT_SECONDS", 45) or 45)
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    compact_papers = []
    for row in papers[:8]:
        compact_papers.append({
            "title": _compact_text(row.get("title", ""), 220),
            "abstract": _compact_text(row.get("abstract", ""), 700),
        })

    prompt = (
        "Return strict JSON only for a causal implication graph subsearch.\n"
        "Schema: {\"nodes\":[{\"id\":\"...\",\"label\":\"...\",\"kind\":\"concept\"}],"
        "\"edges\":[{\"source\":\"...\",\"target\":\"...\",\"relation\":\"modulates\"}],"
        "\"triples\":[{\"source\":\"EDARAVONE\",\"predicate\":\"modulates\",\"target\":\"oxidative stress\"}],"
        "\"subsearch_terms\":[\"...\"]}\n"
        "Rules:\n"
        "1) Include root node id='compound' with the exact compound name label.\n"
        "2) Prefer implication relations such as modulates, contributes_to, mitigates, treats, activates, inhibits, exhibits.\n"
        "3) Return up to 18 nodes and up to 30 edges.\n"
        "4) relation/predicate must be lowercase snake_case.\n"
        "5) Include disease/phenotype/mechanism implications when supported by titles/abstracts.\n"
        "6) Also include concise subsearch_terms for follow-up queries.\n"
        "Example triple style: EDARAVONE --modulates--> oxidative stress.\n"
        f"Compound: {compound_name}\n"
        f"Current search: {query}\n"
        f"Papers: {json.dumps(compact_papers)}"
    )

    try:
        response = requests.post(
            endpoint,
            params={"key": api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2},
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        raw_text = "\n".join([str(part.get("text") or "") for part in parts if isinstance(part, dict)])
        parsed = _parse_gemini_json_text(raw_text)
        if not isinstance(parsed, dict):
            triples = _parse_triple_lines(raw_text)
            if not triples:
                return None
            parsed = {"triples": triples, "subsearch_terms": [row["target"] for row in triples[:10]]}
        return _sanitize_graph_payload(compound_name, parsed)
    except Exception:
        return None


def _generate_gemini_pdf_graph_context(compound_name, query, paper_title, paper_url, pdf_url, pdf_bytes, pdf_text):
    api_key = str(getattr(settings, "GEMINI_API_KEY", "") or "").strip()
    if not api_key:
        return None

    model_name = str(
        getattr(settings, "GEMINI_PDF_MODEL", "gemini-2.0-flash-lite")
        or "gemini-2.0-flash-lite"
    ).strip()
    timeout_seconds = int(getattr(settings, "GEMINI_GRAPH_TIMEOUT_SECONDS", 45) or 45)
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    prompt = (
        "Return strict JSON only for a causal implication graph subsearch.\n"
        "Schema: {\"nodes\":[{\"id\":\"...\",\"label\":\"...\",\"kind\":\"concept\"}],"
        "\"edges\":[{\"source\":\"...\",\"target\":\"...\",\"relation\":\"modulates\"}],"
        "\"triples\":[{\"source\":\"EDARAVONE\",\"predicate\":\"modulates\",\"target\":\"oxidative stress\"}],"
        "\"subsearch_terms\":[\"...\"]}\n"
        "Rules:\n"
        "1) Include root node id='compound' with the exact compound name label.\n"
        "2) Extract implication relations supported by the paper content.\n"
        "3) Prefer relations: modulates, contributes_to, mitigates, treats, activates, inhibits, exhibits, provides, intervenes_in.\n"
        "4) relation/predicate must be lowercase snake_case.\n"
        "5) Return up to 20 nodes and up to 32 edges.\n"
        "6) Include concise subsearch_terms suitable for follow-up query expansion.\n"
        f"Compound: {compound_name}\n"
        f"Current search: {query}\n"
        f"Paper title: {paper_title}\n"
        f"Paper URL: {paper_url}\n"
        f"PDF URL: {pdf_url}\n"
    )

    parts = [{"text": prompt}]
    if pdf_bytes:
        parts.append(
            {
                "inlineData": {
                    "mimeType": "application/pdf",
                    "data": base64.b64encode(pdf_bytes).decode("ascii"),
                }
            }
        )
    if pdf_text:
        parts.append({"text": f"Extracted text excerpt:\n{_compact_text(pdf_text, 18000)}"})

    try:
        response = requests.post(
            endpoint,
            params={"key": api_key},
            json={
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0.1},
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        raw_text = "\n".join([str(part.get("text") or "") for part in parts if isinstance(part, dict)])
        parsed = _parse_gemini_json_text(raw_text)
        if not isinstance(parsed, dict):
            triples = _parse_triple_lines(raw_text)
            if not triples:
                return None
            parsed = {"triples": triples, "subsearch_terms": [row["target"] for row in triples[:10]]}
        sanitized = _sanitize_graph_payload(compound_name, parsed)
        sanitized["source"] = "gemini_pdf"
        return sanitized
    except Exception:
        return None


def _push_recent_snippet(request, snippet):
    recent = request.session.get("recent_snippets", [])
    if not isinstance(recent, list):
        recent = []
    recent = [row for row in recent if row.get("id") != snippet.id]
    recent.insert(
        0,
        {
            "id": snippet.id,
            "title": snippet.title,
            "compound_slug": snippet.compound.slug,
            "compound_name": snippet.compound.name,
        },
    )
    request.session["recent_snippets"] = recent[:8]


def snippet_list(request):
    """
    Display paginated list of research snippets with filtering.
    """
    form = SnippetSearchForm(request.GET)
    snippets = ResearchSnippet.objects.select_related('compound', 'created_by').prefetch_related('tags', 'reviews')
    
    # Apply user visibility permissions
    if request.user.is_authenticated:
        if request.user.is_staff:
            # Staff can see all snippets
            pass
        else:
            # Regular users see public snippets + their own drafts
            snippets = snippets.filter(
                Q(visibility='public') |
                Q(created_by=request.user, visibility='draft')
            )
    else:
        # Anonymous users only see public snippets
        snippets = snippets.filter(visibility='public')
    
    # Apply search filters
    if form.is_valid():
        query = form.cleaned_data.get('query')
        compound = form.cleaned_data.get('compound')
        snippet_type = form.cleaned_data.get('snippet_type')
        status = form.cleaned_data.get('status')
        tags = form.cleaned_data.get('tags')
        created_by = form.cleaned_data.get('created_by')
        ai_generated = form.cleaned_data.get('ai_generated')
        sort_by = form.cleaned_data.get('sort_by', '-created_at')
        
        if query:
            snippets = snippets.filter(
                Q(title__icontains=query) |
                Q(content__icontains=query) |
                Q(source_title__icontains=query)
            )
        
        if compound:
            snippets = snippets.filter(compound=compound)
        
        if snippet_type:
            snippets = snippets.filter(snippet_type=snippet_type)
        
        if status:
            snippets = snippets.filter(status=status)
        
        if tags:
            snippets = snippets.filter(tags__in=tags).distinct()
        
        if created_by:
            snippets = snippets.filter(created_by=created_by)
        
        if ai_generated == 'true':
            snippets = snippets.filter(ai_generated=True)
        elif ai_generated == 'false':
            snippets = snippets.filter(ai_generated=False)
        
        snippets = snippets.order_by(sort_by)
    
    # Pagination
    paginator = Paginator(snippets, 12)  # 12 snippets per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get research settings for display options
    settings = ResearchSettings.objects.first()
    
    context = {
        'snippets': page_obj,
        'form': form,
        'settings': settings,
        'total_count': snippets.count(),
    }
    
    return render(request, 'research/snippet_list.html', context)


def snippet_detail(request, pk):
    """
    Display detailed view of a research snippet with review options.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if not snippet.visibility == 'public' and not snippet.visibility == 'public_review':
        if not request.user.is_authenticated or (snippet.created_by != request.user and not request.user.is_staff):
            return HttpResponseForbidden("You don't have permission to view this snippet.")
    
    # Increment view count
    snippet.view_count += 1
    snippet.save(update_fields=['view_count'])
    _push_recent_snippet(request, snippet)
    
    # Get user's existing review if any
    user_review = None
    if request.user.is_authenticated:
        try:
            user_review = SnippetReview.objects.get(snippet=snippet, reviewer=request.user)
        except SnippetReview.DoesNotExist:
            pass
    
    # Get review stats
    review_stats = snippet.reviews.aggregate(
        total_reviews=Count('id'),
        positive_reviews=Count('id', filter=Q(vote_type='validate')),
        negative_reviews=Count('id', filter=Q(vote_type='reject'))
    )
    
    # Calculate approval percentage
    approval_percentage = 0
    if review_stats['total_reviews'] > 0:
        approval_percentage = round((review_stats['positive_reviews'] / review_stats['total_reviews']) * 100)
    
    # Get all reviews with comments for display
    reviews_with_comments = snippet.reviews.select_related('reviewer').filter(
        comment__isnull=False, comment__gt=''
    ).order_by('-created_at')
    
    # Check if user can review
    can_review = (
        request.user.is_authenticated and 
        snippet.created_by != request.user and 
        not user_review and
        snippet.visibility in ['public', 'public_review']
    )
    
    context = {
        'snippet': snippet,
        'user_review': user_review,
        'review_stats': review_stats,
        'approval_percentage': approval_percentage,
        'reviews_with_comments': reviews_with_comments,
        'can_review': can_review,
        'review_form': SnippetReviewForm() if can_review else None,
    }
    
    return render(request, 'research/snippet_detail.html', context)


@login_required
def create_snippet(request):
    """
    Create a new research snippet.
    """
    # Check if public submissions are enabled
    settings = ResearchSettings.objects.first()
    if settings and not settings.public_submissions_enabled and not request.user.is_staff:
        messages.error(request, "Public research submissions are currently disabled.")
        return redirect('research:snippet_list')
    
    if request.method == 'POST':
        form = ResearchSnippetForm(request.POST)
        if form.is_valid():
            snippet = form.save(commit=False)
            snippet.created_by = request.user
            
            # Set visibility based on whether it's saved as draft
            if request.POST.get('save_draft') or form.cleaned_data.get('save_as_draft'):
                snippet.visibility = 'draft'
                snippet.status = 'draft'
            else:
                snippet.visibility = 'public'
                snippet.status = 'submitted'
            
            snippet.save()
            form.save_m2m()  # Save many-to-many relationships
            
            messages.success(request, "Research snippet created successfully!")
            return redirect('research:snippet_detail', pk=snippet.pk)
    else:
        form = ResearchSnippetForm()
        
        # Pre-fill compound if provided in URL
        compound_id = request.GET.get('compound')
        if compound_id:
            try:
                compound = Compound.objects.get(pk=compound_id)
                form.initial['compound'] = compound
            except Compound.DoesNotExist:
                pass
    
    context = {
        'form': form,
        'title': 'Create Research Snippet',
        'settings': settings,
    }
    
    # Add selected compound to context for back button
    compound_id = request.GET.get('compound')
    if compound_id:
        try:
            context['selected_compound'] = Compound.objects.get(pk=compound_id)
        except Compound.DoesNotExist:
            pass
    elif request.method == 'POST' and form.is_valid():
        context['selected_compound'] = form.cleaned_data['compound']
    
    return render(request, 'research/snippet_form.html', context)


@login_required
def edit_snippet(request, pk):
    """
    Edit an existing research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You don't have permission to edit this snippet.")
    
    if request.method == 'POST':
        form = ResearchSnippetForm(request.POST, instance=snippet)
        if form.is_valid():
            form.save()
            messages.success(request, "Research snippet updated successfully!")
            return redirect('research:snippet_detail', pk=snippet.pk)
    else:
        form = ResearchSnippetForm(instance=snippet)
    
    context = {
        'form': form,
        'snippet': snippet,
        'title': 'Edit Research Snippet',
        'selected_compound': snippet.compound,  # Always available for edit
    }
    
    return render(request, 'research/snippet_form.html', context)


@login_required
@require_POST
def submit_review(request, pk):
    """
    Submit or update a review/vote for a research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by == request.user:
        return JsonResponse({'error': 'Cannot review your own snippet'}, status=400)
    
    if snippet.visibility not in ['public', 'public_review']:
        return JsonResponse({'error': 'Cannot review private snippets'}, status=400)
    
    # Check if user already reviewed
    existing_review = SnippetReview.objects.filter(snippet=snippet, reviewer=request.user).first()
    
    try:
        data = json.loads(request.body)
        vote_type = data.get('vote_type')
        comment = data.get('comment', '').strip()
        
        if vote_type not in ['validate', 'reject']:
            return JsonResponse({'error': 'Invalid vote type'}, status=400)
        
        if existing_review:
            # Update existing review
            existing_review.vote_type = vote_type
            existing_review.comment = comment
            existing_review.save()
            review = existing_review
            action = 'updated'
        else:
            # Create new review
            review = SnippetReview.objects.create(
                snippet=snippet,
                reviewer=request.user,
                vote_type=vote_type,
                comment=comment
            )
            action = 'created'
        
        # Update snippet status
        snippet.update_status()
        
        # Get updated stats
        stats = snippet.reviews.aggregate(
            total=Count('id'),
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        return JsonResponse({
            'success': True,
            'review_id': review.id,
            'action': action,
            'new_status': snippet.status,
            'stats': stats,
            'confidence_level': snippet.confidence_level,
            'confidence_color': snippet.confidence_color
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def delete_snippet(request, pk):
    """
    Delete a research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You don't have permission to delete this snippet.")
    
    if request.method == 'POST':
        snippet.delete()
        messages.success(request, "Research snippet deleted successfully!")
        return redirect('research:snippet_list')
    
    context = {
        'snippet': snippet,
    }
    
    return render(request, 'research/snippet_confirm_delete.html', context)


def compound_snippets(request, slug):
    """
    Display all research snippets for a specific compound.
    """
    compound = get_object_or_404(Compound, slug=slug)
    
    snippets = ResearchSnippet.objects.filter(compound=compound).select_related('created_by').prefetch_related('tags', 'reviews', 'comments')
    
    # Apply visibility filters
    if request.user.is_authenticated:
        if not request.user.is_staff:
            snippets = snippets.filter(
                Q(visibility__in=['public', 'public_review']) |
                Q(created_by=request.user)
            )
    else:
        snippets = snippets.filter(visibility__in=['public', 'public_review'])
    
    # Annotate with review stats
    snippets = snippets.annotate(
        positive_reviews=Count('reviews', filter=Q(reviews__vote_type='validate')),
        negative_reviews=Count('reviews', filter=Q(reviews__vote_type='reject')),
        total_reviews=Count('reviews')
    )
    
    # Get user's reviews for each snippet
    user_reviews = {}
    if request.user.is_authenticated:
        from .models import SnippetReview
        user_review_qs = SnippetReview.objects.filter(
            snippet__in=snippets,
            reviewer=request.user
        ).values('snippet_id', 'vote_type')
        user_reviews = {r['snippet_id']: r['vote_type'] for r in user_review_qs}
    
    # Add user review vote to each snippet
    for snippet in snippets:
        snippet.user_review_vote = user_reviews.get(snippet.id)
    
    # Group by snippet type
    snippet_groups = {}
    for snippet in snippets:
        snippet_type = snippet.get_snippet_type_display()
        if snippet_type not in snippet_groups:
            snippet_groups[snippet_type] = []
        snippet_groups[snippet_type].append(snippet)
    
    context = {
        'compound': compound,
        'snippet_groups': snippet_groups,
        'total_count': snippets.count(),
        'user_reviews': user_reviews,
    }
    
    return render(request, 'research/compound_snippets.html', context)


def compound_research_explorer(request, slug):
    """
    Compound-scoped research explorer with PubMed search + snippet save workflow.
    """
    compound = get_object_or_404(Compound, slug=slug)

    search_input = (request.GET.get("q") or "").strip()
    max_results_raw = request.GET.get("max_results", "12")
    try:
        max_results = int(max_results_raw)
    except (TypeError, ValueError):
        max_results = 12
    max_results = max(1, min(max_results, 25))

    query = _build_compound_search_query(compound.name, search_input)
    paper_results = []
    search_error = ""

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip().lower()
        if action == "save_paper_snippet":
            if not request.user.is_authenticated:
                return redirect("login")

            paper_title = _compact_text(request.POST.get("paper_title"), 300)
            paper_abstract = _compact_text(request.POST.get("paper_abstract"), 6000)
            paper_pmid = _compact_text(request.POST.get("paper_pmid"), 32)
            paper_doi = _compact_text(request.POST.get("paper_doi"), 100)
            paper_journal = _compact_text(request.POST.get("paper_journal"), 300)
            paper_pubdate = _compact_text(request.POST.get("paper_pubdate"), 64)
            user_note = _compact_text(request.POST.get("user_note"), 3000)
            source_url = f"https://pubmed.ncbi.nlm.nih.gov/{paper_pmid}/" if paper_pmid else ""

            if not paper_title:
                messages.error(request, "Paper title is required to create a snippet.")
            else:
                existing = None
                if source_url:
                    existing = ResearchSnippet.objects.filter(
                        compound=compound,
                        source_url=source_url,
                    ).first()

                if existing:
                    messages.info(request, "A snippet for this paper already exists.")
                else:
                    snippet_body = []
                    if paper_abstract:
                        snippet_body.append(f"Abstract:\n{paper_abstract}")
                    source_meta = " | ".join([row for row in [paper_journal, paper_pubdate] if row])
                    if source_meta:
                        snippet_body.append(f"Source: {source_meta}")
                    if user_note:
                        snippet_body.append(f"User Notes:\n{user_note}")
                    if not snippet_body:
                        snippet_body.append("No abstract or notes provided.")

                    snippet = ResearchSnippet.objects.create(
                        title=paper_title,
                        content="\n\n".join(snippet_body),
                        compound=compound,
                        snippet_type=_infer_snippet_type_from_text(paper_title, paper_abstract),
                        visibility="public",
                        status="submitted",
                        source_title=paper_title,
                        source_url=source_url,
                        doi=paper_doi,
                        created_by=request.user,
                        ai_generated=False,
                    )
                    messages.success(request, f"Saved '{snippet.title}' to research snippets.")

            params = {}
            if search_input:
                params["q"] = search_input
            params["max_results"] = str(max_results)
            return redirect(f"{request.path}?{urlencode(params)}")

    try:
        pubmed_ids = search_pubmed_ids(query, retmax=max_results)
        papers = fetch_pubmed_articles(pubmed_ids)
        paper_results = [_article_payload(row) for row in papers]
    except Exception as exc:
        search_error = str(exc)

    saved_research_count = 0
    if request.user.is_authenticated:
        saved_research_count = ResearchSnippet.objects.filter(
            compound=compound,
            created_by=request.user,
        ).count()

    context = {
        "compound": compound,
        "search_input": search_input,
        "query": query,
        "paper_results": paper_results,
        "paper_count": len(paper_results),
        "saved_research_count": saved_research_count,
        "max_results": max_results,
        "search_error": search_error,
        "graph_seed_papers": [
            {"title": row.get("title", ""), "abstract": row.get("abstract", "")}
            for row in paper_results[:10]
        ],
    }
    return render(request, "research/compound_explorer.html", context)


@require_POST
def compound_explorer_graph_context(request, slug):
    """
    Build context graph nodes for subsearch; uses Gemini when configured, otherwise fallback.
    """
    compound = get_object_or_404(Compound, slug=slug)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    query = _compact_text(payload.get("query"), 400)
    papers = payload.get("papers")
    if not isinstance(papers, list):
        papers = []

    safe_papers = []
    for row in papers[:10]:
        if not isinstance(row, dict):
            continue
        safe_papers.append({
            "title": _compact_text(row.get("title"), 260),
            "abstract": _compact_text(row.get("abstract"), 1200),
        })

    graph_payload = None
    # Restrict paid/API-backed calls to authenticated users, while keeping fallback available.
    if request.user.is_authenticated:
        graph_payload = _generate_gemini_graph_context(compound.name, query, safe_papers)

    if not graph_payload:
        graph_payload = _fallback_graph_context(compound.name, query, safe_papers)

    return JsonResponse(graph_payload, status=200)


@require_POST
def compound_explorer_url_graph_context(request, slug):
    """
    Build graph context from a user-confirmed paper URL by resolving/fetching its PDF first.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Login is required for URL/PDF context analysis."}, status=403)

    compound = get_object_or_404(Compound, slug=slug)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid JSON payload"}, status=400)

    raw_url = _compact_text(payload.get("url"), 1200)
    query = _compact_text(payload.get("query"), 400)
    paper_title = _compact_text(payload.get("paper_title"), 240)
    if not raw_url:
        return JsonResponse({"error": "URL is required."}, status=400)
    if not _is_safe_public_url(raw_url):
        return JsonResponse({"error": "Only public http(s) URLs are allowed."}, status=400)

    try:
        resolved = _resolve_pdf_from_research_url(raw_url)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except requests.RequestException as exc:
        return JsonResponse({"error": f"Could not load URL: {exc}"}, status=400)

    pdf_text = _extract_pdf_text_excerpt(resolved.get("pdf_bytes", b""))
    graph_payload = _generate_gemini_pdf_graph_context(
        compound_name=compound.name,
        query=query,
        paper_title=paper_title,
        paper_url=resolved.get("resolved_url", raw_url),
        pdf_url=resolved.get("pdf_url", raw_url),
        pdf_bytes=resolved.get("pdf_bytes", b""),
        pdf_text=pdf_text,
    )
    if not graph_payload:
        fallback_papers = []
        if pdf_text:
            fallback_papers.append({
                "title": paper_title or resolved.get("pdf_url", raw_url),
                "abstract": pdf_text,
            })
        graph_payload = _fallback_graph_context(compound.name, query or paper_title, fallback_papers)
        graph_payload["source"] = "fallback_pdf"

    graph_payload["resolved_url"] = resolved.get("resolved_url", raw_url)
    graph_payload["pdf_url"] = resolved.get("pdf_url", raw_url)
    return JsonResponse(graph_payload, status=200)


@login_required
def ai_analysis(request):
    """
    AI-powered research analysis and summarization.
    """
    settings = ResearchSettings.objects.first()
    if settings and not settings.ai_summaries_enabled:
        messages.error(request, "AI analysis features are currently disabled.")
        return redirect('research:snippet_list')
    
    if request.method == 'POST':
        form = AIAnalysisForm(request.POST)
        if form.is_valid():
            # This is where you'd integrate with your AI service
            # For now, we'll return a placeholder response
            content = form.cleaned_data['content']
            analysis_type = form.cleaned_data['analysis_type']
            target_compound = form.cleaned_data.get('target_compound')
            
            # Placeholder AI response
            ai_result = {
                'summary': f"AI analysis of {len(content)} characters of content...",
                'confidence': 0.85,
                'suggested_tags': ['Dopaminergic', 'Clinical Study'],
                'compound_detected': target_compound.name if target_compound else 'Auto-detection needed',
            }
            
            context = {
                'form': form,
                'ai_result': ai_result,
                'original_content': content,
            }
            
            return render(request, 'research/ai_analysis.html', context)
    else:
        form = AIAnalysisForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'research/ai_analysis.html', context)


@staff_member_required
def manage_settings(request):
    """
    Admin view for managing research system settings.
    """
    settings, created = ResearchSettings.objects.get_or_create(
        defaults={
            'public_submissions_enabled': True,
            'require_review_flair': True,
            'ai_summaries_enabled': True,
        }
    )
    
    if request.method == 'POST':
        form = ResearchSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings updated successfully!")
            return redirect('research:manage_settings')
    else:
        form = ResearchSettingsForm(instance=settings)
    
    # Get system statistics
    stats = {
        'total_snippets': ResearchSnippet.objects.count(),
        'verified_snippets': ResearchSnippet.objects.filter(status='verified').count(),
        'pending_review': ResearchSnippet.objects.filter(status='needs_review').count(),
        'total_reviews': SnippetReview.objects.count(),
        'active_contributors': ResearchSnippet.objects.values('created_by').distinct().count(),
    }
    
    context = {
        'form': form,
        'settings': settings,
        'stats': stats,
    }
    
    return render(request, 'research/manage_settings.html', context)


@staff_member_required
def moderation_queue(request):
    """
    Admin view for moderating research snippets.
    """
    # Get snippets that need attention
    flagged_snippets = ResearchSnippet.objects.filter(status='flagged').select_related('created_by', 'compound')
    pending_snippets = ResearchSnippet.objects.filter(status='needs_review').select_related('created_by', 'compound')
    
    context = {
        'flagged_snippets': flagged_snippets,
        'pending_snippets': pending_snippets,
    }
    
    return render(request, 'research/moderation_queue.html', context)


@staff_member_required
@require_POST
def moderate_snippet(request, pk):
    """
    Moderate a specific snippet (approve, reject, etc.).
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    try:
        data = json.loads(request.body)
        action = data.get('action')
        
        if action == 'approve':
            snippet.status = 'verified'
        elif action == 'reject':
            snippet.status = 'rejected'
        elif action == 'flag':
            snippet.status = 'flagged'
        elif action == 'reset':
            snippet.status = 'needs_review'
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)
        
        snippet.save()
        
        return JsonResponse({
            'success': True,
            'new_status': snippet.status,
            'message': f'Snippet {action}ed successfully'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# API endpoints for AJAX functionality

@require_POST
def toggle_snippet_visibility(request, pk):
    """
    Toggle snippet visibility (for snippet owners).
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=403)
    
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    if snippet.created_by != request.user and not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        new_visibility = data.get('visibility')
        
        if new_visibility not in ['private', 'public', 'public_review']:
            return JsonResponse({'error': 'Invalid visibility option'}, status=400)
        
        snippet.visibility = new_visibility
        
        # Update status based on new visibility
        if new_visibility == 'private':
            snippet.status = 'draft'
        elif new_visibility == 'public':
            snippet.status = 'submitted'
        else:  # public_review
            snippet.status = 'needs_review'
        
        snippet.save()
        
        return JsonResponse({
            'success': True,
            'new_visibility': snippet.visibility,
            'new_status': snippet.status
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def quick_vote_snippet(request, pk):
    """
    Handle quick vote (approve/reject) for a snippet from compound page.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    # Check permissions
    if snippet.created_by == request.user:
        return JsonResponse({'error': 'Cannot vote on your own snippet'}, status=400)
    
    # Check if user already voted
    existing_review = SnippetReview.objects.filter(snippet=snippet, reviewer=request.user).first()
    if existing_review:
        return JsonResponse({'error': 'You have already voted on this snippet'}, status=400)
    
    try:
        data = json.loads(request.body)
        vote_type = data.get('vote_type')
        
        if vote_type not in ['validate', 'reject']:
            return JsonResponse({'error': 'Invalid vote type'}, status=400)
        
        # Create review without comment (quick vote)
        review = SnippetReview.objects.create(
            snippet=snippet,
            reviewer=request.user,
            vote_type=vote_type,
            comment=''
        )
        
        # Update snippet status
        snippet.update_status()
        
        # Get updated stats
        stats = snippet.reviews.aggregate(
            total=Count('id'),
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        return JsonResponse({
            'success': True,
            'vote_type': vote_type,
            'stats': stats
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def add_snippet_comment(request, pk):
    """
    Add a comment to a research snippet.
    """
    snippet = get_object_or_404(ResearchSnippet, pk=pk)
    
    try:
        data = json.loads(request.body)
        content = data.get('content', '').strip()
        
        if not content or len(content) < 5:
            return JsonResponse({'error': 'Comment must be at least 5 characters long'}, status=400)
        
        # Create comment
        comment = SnippetComment.objects.create(
            snippet=snippet,
            author=request.user,
            content=content
        )
        
        return JsonResponse({
            'success': True,
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'author': comment.author.username,
                'created_at': comment.created_at.strftime('%b %d, %Y at %I:%M %p')
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# REST Framework ViewSets
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Q
from .serializers import (
    ResearchSnippetSerializer,
    SnippetReviewSerializer,
    SnippetTagSerializer,
    SnippetTaggingSerializer,
    UserRoleSerializer,
    ResearchSettingsSerializer,
    SnippetCommentSerializer
)


class ResearchSnippetViewSet(viewsets.ModelViewSet):
    serializer_class = ResearchSnippetSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'id'

    def get_queryset(self):
        queryset = ResearchSnippet.objects.select_related('compound', 'created_by').prefetch_related('tags', 'reviews', 'comments')
        
        # Apply visibility permissions
        if self.request.user.is_authenticated:
            if self.request.user.is_staff:
                # Staff can see all snippets
                pass
            else:
                # Regular users see public snippets + their own drafts
                queryset = queryset.filter(
                    Q(visibility='public') |
                    Q(created_by=self.request.user, visibility='draft')
                )
        else:
            # Anonymous users only see public snippets
            queryset = queryset.filter(visibility='public')
            
        # Filter by compound if specified
        compound_id = self.request.query_params.get('compound', None)
        if compound_id:
            queryset = queryset.filter(compound_id=compound_id)
            
        # Filter by status if specified
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def increment_view(self, request, id=None):
        """Increment view count for snippet"""
        snippet = self.get_object()
        snippet.view_count += 1
        snippet.save()
        return Response({'view_count': snippet.view_count})

    @action(detail=True, methods=['get'])
    def analytics(self, request, id=None):
        """Get analytics data for snippet"""
        snippet = self.get_object()
        reviews = snippet.reviews.aggregate(
            positive=Count('id', filter=Q(vote_type='validate')),
            negative=Count('id', filter=Q(vote_type='reject'))
        )
        
        analytics_data = {
            'view_count': snippet.view_count,
            'positive_reviews': reviews['positive'] or 0,
            'negative_reviews': reviews['negative'] or 0,
            'confidence_level': snippet.confidence_level,
            'comment_count': snippet.comments.count(),
        }
        
        return Response(analytics_data)


class SnippetReviewViewSet(viewsets.ModelViewSet):
    queryset = SnippetReview.objects.all()
    serializer_class = SnippetReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = SnippetReview.objects.select_related('snippet', 'reviewer')
        snippet_id = self.request.query_params.get('snippet', None)
        if snippet_id:
            queryset = queryset.filter(snippet_id=snippet_id)
        return queryset.order_by('-created_at')


class SnippetTagViewSet(viewsets.ModelViewSet):
    queryset = SnippetTag.objects.all()
    serializer_class = SnippetTagSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class SnippetTaggingViewSet(viewsets.ModelViewSet):
    queryset = SnippetTagging.objects.all()
    serializer_class = SnippetTaggingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = SnippetTagging.objects.select_related('snippet', 'tag', 'tagged_by')
        snippet_id = self.request.query_params.get('snippet', None)
        if snippet_id:
            queryset = queryset.filter(snippet_id=snippet_id)
        return queryset.order_by('-created_at')


class UserRoleViewSet(viewsets.ModelViewSet):
    queryset = UserRole.objects.all()
    serializer_class = UserRoleSerializer
    permission_classes = [permissions.IsAdminUser]


class ResearchSettingsViewSet(viewsets.ModelViewSet):
    queryset = ResearchSettings.objects.all()
    serializer_class = ResearchSettingsSerializer
    permission_classes = [permissions.IsAdminUser]


class SnippetCommentViewSet(viewsets.ModelViewSet):
    queryset = SnippetComment.objects.all()
    serializer_class = SnippetCommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = SnippetComment.objects.select_related('snippet', 'author')
        snippet_id = self.request.query_params.get('snippet', None)
        if snippet_id:
            queryset = queryset.filter(snippet_id=snippet_id)
        return queryset.order_by('-created_at')
