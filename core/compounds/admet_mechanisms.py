from __future__ import annotations

import re
from typing import Any, Iterable


_KNOWN = {
    # Nuclear receptor (Tox21-like) endpoints
    "NR-AR": ("Androgen receptor (AR)", "NR"),
    "NR-AR-LBD": ("Androgen receptor LBD (AR)", "NR"),
    "NR-ER": ("Estrogen receptor (ER / ESR1)", "NR"),
    "NR-ER-LBD": ("Estrogen receptor LBD (ESR1)", "NR"),
    "NR-PR": ("Progesterone receptor (PGR)", "NR"),
    "NR-AhR": ("Aryl hydrocarbon receptor (AHR)", "NR"),
    "NR-Aromatase": ("Aromatase (CYP19A1)", "NR"),
    "NR-PPAR-gamma": ("PPAR-γ (PPARG)", "NR"),
    # Stress response endpoints
    "SR-ARE": ("Antioxidant response (NRF2)", "SR"),
    "SR-ATAD5": ("DNA damage response (ATAD5)", "SR"),
    "SR-HSE": ("Heat shock response (HSF1)", "SR"),
    "SR-MMP": ("Mitochondrial membrane potential (MMP)", "SR"),
    "SR-p53": ("p53 response (TP53)", "SR"),
}

_ENDPOINT_SIGNATURES = {
    "NR-AR": ["androgen receptor", " ar "],
    "NR-AR-LBD": ["androgen receptor", " ar "],
    "NR-ER": ["estrogen receptor", " esr1 ", " er "],
    "NR-ER-LBD": ["estrogen receptor", " esr1 ", " er "],
    "NR-PR": ["progesterone receptor", " pgr ", " pr "],
    "NR-AhR": ["aryl hydrocarbon receptor", " ahr "],
    "NR-Aromatase": ["aromatase", " cyp19"],
    "NR-PPAR-gamma": ["ppar", "pparg"],
}


def _to_prob(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        if v != v:  # NaN
            return None
        return v
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "yes", "positive"):
            return 1.0
        if s in ("false", "no", "negative"):
            return 0.0
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _pretty_endpoint(key: str) -> str:
    # e.g. NR-PPAR-gamma -> PPAR gamma
    out = key
    if out.startswith("NR-"):
        out = out[3:]
    elif out.startswith("SR-"):
        out = out[3:]
    out = out.replace("_", " ").replace("-", " ")
    out = re.sub(r"\bdrugbank\s+approved\s+percentile\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\bdrugbank\s+approved\b", "", out, flags=re.IGNORECASE)
    out = " ".join([w for w in out.split(" ") if w])
    return out


def extract_predicted_mechanisms(predictions: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Returns mechanistic endpoints from ADMET-AI predictions (NR-* and SR-*),
    sorted by score descending.
    """
    if not isinstance(predictions, dict) or not predictions:
        return []

    out: list[dict[str, Any]] = []
    for key, raw in predictions.items():
        key_s = str(key)
        if not (key_s.startswith("NR-") or key_s.startswith("SR-")):
            continue
        score = _to_prob(raw)
        if score is None:
            continue

        label, kind = _KNOWN.get(key_s, (f"{_pretty_endpoint(key_s)} (predicted)", "NR" if key_s.startswith("NR-") else "SR"))
        out.append(
            {
                "endpoint": key_s,
                "label": label,
                "kind": "Nuclear Receptor" if kind == "NR" else "Stress Response",
                "score": score,
            }
        )

    out.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return out


def _extract_cyp_endpoints(predictions: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(predictions, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, raw in predictions.items():
        key_s = str(key)
        if not key_s.upper().startswith("CYP"):
            continue
        score = _to_prob(raw)
        if score is None:
            continue
        out.append(
            {
                "endpoint": key_s,
                "label": f"{key_s.replace('_', ' ')} interaction",
                "kind": "Metabolism (CYP)",
                "score": score,
            }
        )
    out.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return out


def _extract_transporter_endpoints(predictions: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(predictions, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, raw in predictions.items():
        key_s = str(key)
        if not re.search(r"(pgp|p-gp|bcrp|oatp|oct|oat|mate|mrp)", key_s, flags=re.IGNORECASE):
            continue
        score = _to_prob(raw)
        if score is None:
            continue
        out.append(
            {
                "endpoint": key_s,
                "label": f"{_pretty_endpoint(key_s)} transporter interaction",
                "kind": "Transporters",
                "score": score,
            }
        )
    out.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    return out


def _confidence_tier(score: float, kind: str, expected_status: str, *, agrees_with_secondary: bool = False) -> str:
    if score >= 0.9:
        tier = 2
    elif score >= 0.75:
        tier = 1
    else:
        tier = 0

    # Assay-activity endpoints are informative but not direct pharmacology proof.
    if kind in ("Nuclear Receptor", "Stress Response"):
        tier = max(0, tier - 1)
    if expected_status == "expected":
        tier = min(2, tier + 1)
    elif expected_status == "unexpected":
        tier = max(0, tier - 1)
    if agrees_with_secondary:
        tier = min(2, tier + 1)

    return ("low", "medium", "high")[tier]


def _interpretation(kind: str) -> str:
    if kind == "Nuclear Receptor":
        return "Assay activity signal; may reflect pathway engagement or assay cross-reactivity."
    if kind == "Stress Response":
        return "Cellular stress-response assay signal; indicates biological stress potential."
    if kind == "Metabolism (CYP)":
        return "Predicted metabolism interaction likelihood (substrate/inhibitor context is endpoint-dependent)."
    if kind == "Transporters":
        return "Predicted transporter interaction likelihood (distribution/absorption impact possible)."
    return "Predictive signal; needs validation against curated evidence."


def _normal_text(value: str) -> str:
    s = f" {value.lower()} "
    return re.sub(r"\s+", " ", s)


def _expected_status(endpoint: str, kind: str, known_targets: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not known_targets:
        return "unknown", []

    signatures = _ENDPOINT_SIGNATURES.get(endpoint, [])
    if kind == "Metabolism (CYP)":
        cyp_match = re.search(r"(CYP\d[A-Z]?\d*)", endpoint, flags=re.IGNORECASE)
        if cyp_match:
            signatures = signatures + [cyp_match.group(1).lower()]
    if kind == "Transporters":
        signatures = signatures + ["pgp", "abcb1", "bcrp", "oatp", "oct", "oat", "mate", "mrp"]

    if not signatures:
        return "unknown", []

    matched: list[dict[str, Any]] = []
    for target in known_targets:
        hay = _normal_text(target.get("name", ""))
        if any(sig.lower() in hay for sig in signatures):
            matched.append(target)

    if matched:
        return "expected", matched
    return "unexpected", []


def _extract_known_targets(target_interactions: Iterable[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for interaction in target_interactions or []:
        target = getattr(interaction, "target", None)
        if not target:
            continue
        source = (getattr(interaction, "source", "") or "").strip()
        chembl_id = (getattr(target, "chembl_id", "") or "").strip()
        chembl_url = f"https://www.ebi.ac.uk/chembl/target_report_card/{chembl_id}/" if chembl_id else ""

        pubmed_url = ""
        if "pubmed" in source.lower():
            match = re.search(r"(\d{7,8})", source)
            if match:
                pubmed_url = f"https://pubmed.ncbi.nlm.nih.gov/{match.group(1)}/"
            else:
                pubmed_url = "https://pubmed.ncbi.nlm.nih.gov/"

        out.append(
            {
                "name": getattr(target, "name", ""),
                "mechanism": getattr(interaction, "get_mechanism_display", lambda: "")(),
                "source": source,
                "chembl_url": chembl_url,
                "pubmed_url": pubmed_url,
            }
        )
    return out


def _find_secondary_score(secondary_predictions: dict[str, Any] | None, endpoint: str) -> float | None:
    if not isinstance(secondary_predictions, dict) or not secondary_predictions:
        return None
    if endpoint in secondary_predictions:
        return _to_prob(secondary_predictions.get(endpoint))

    # Fallback: permissive normalized key match.
    norm = re.sub(r"[^a-z0-9]+", "", endpoint.lower())
    for key, val in secondary_predictions.items():
        if re.sub(r"[^a-z0-9]+", "", str(key).lower()) == norm:
            return _to_prob(val)
    return None


def build_predicted_mechanism_context(
    predictions: dict[str, Any] | None,
    *,
    target_interactions: Iterable[Any] | None = None,
    secondary_predictions: dict[str, Any] | None = None,
    secondary_label: str = "MolProp",
) -> dict[str, Any]:
    known_targets = _extract_known_targets(target_interactions or [])
    mechanisms = (
        extract_predicted_mechanisms(predictions)
        + _extract_cyp_endpoints(predictions)
        + _extract_transporter_endpoints(predictions)
    )

    enriched: list[dict[str, Any]] = []
    for m in mechanisms:
        expected_status, refs = _expected_status(m.get("endpoint", ""), m.get("kind", ""), known_targets)
        primary_score = float(m.get("score") or 0.0)
        secondary_score = _find_secondary_score(secondary_predictions, m.get("endpoint", ""))
        agrees = (
            secondary_score is not None
            and abs(float(secondary_score) - primary_score) <= 0.2
        )
        confidence = _confidence_tier(
            primary_score,
            m.get("kind", ""),
            expected_status,
            agrees_with_secondary=agrees,
        )
        enriched.append(
            {
                **m,
                "interpretation": _interpretation(m.get("kind", "")),
                "expected_status": expected_status,
                "confidence": confidence,
                "known_refs": refs[:3],
                "secondary_score": secondary_score,
                "secondary_label": secondary_label,
                "cross_model_agreement": agrees,
            }
        )

    enriched.sort(key=lambda x: (x.get("kind", ""), -float(x.get("score") or 0.0)))

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in enriched:
        by_kind.setdefault(row.get("kind", "Other"), []).append(row)

    top_likely = [r for r in enriched if r["expected_status"] == "expected" and r["confidence"] in ("medium", "high")][:4]
    uncertain = [r for r in enriched if r["confidence"] == "low"][:4]
    possible_false = [r for r in enriched if r["expected_status"] == "unexpected" and float(r.get("score") or 0.0) >= 0.75][:4]

    contradiction_notes = []
    if possible_false:
        contradiction_notes.append(
            "Some high assay signals do not match curated targets; these may represent off-target activity or assay cross-reactivity."
        )
    if not known_targets:
        contradiction_notes.append(
            "No curated target interactions are present yet, so expected/unexpected tagging is limited."
        )

    references = known_targets[:10]

    return {
        "mechanisms": enriched,
        "groups": by_kind,
        "summary": {
            "top_likely": top_likely,
            "uncertain": uncertain,
            "possible_false": possible_false,
            "notes": contradiction_notes,
            "cross_model_agree_count": sum(1 for r in enriched if r.get("cross_model_agreement")),
            "cross_model_total": sum(1 for r in enriched if r.get("secondary_score") is not None),
        },
        "references": references,
    }
