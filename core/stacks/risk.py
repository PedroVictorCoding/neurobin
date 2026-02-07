import hashlib
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from compounds.models import CompoundADMETPrediction, CompoundMolPropPrediction

from .models import Stack, StackItem, StackRiskAssessment


TOX_ENDPOINTS = ("DILI", "AMES", "ClinTox", "Carcinogens_Lagunin")
ABS_ENDPOINTS = ("Bioavailability_Ma", "HIA_Hou")
BBB_ENDPOINTS = ("BBB_Martins",)
RISK_CURVE_GAMMA = 2.2


def _as_prob(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        if 0.0 <= v <= 1.0:
            return v
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "positive"):
            return 1.0
        if v in ("false", "no", "negative"):
            return 0.0
        try:
            n = float(value)
        except ValueError:
            return None
        if 0.0 <= n <= 1.0:
            return n
    return None


def _apply_risk_curve(value: float | None, gamma: float = RISK_CURVE_GAMMA) -> float | None:
    if value is None:
        return None
    v = max(0.0, min(1.0, float(value)))
    return float(pow(v, gamma))


def _risk_level(score: float | None, predicted_count: int) -> str:
    if predicted_count <= 0 or score is None:
        return "unknown"
    if score >= 0.7:
        return "high"
    if score >= 0.5:
        return "moderate"
    return "low"


def _stack_input_hash(
    compound_ids: list[int],
    admet_rows: dict[int, CompoundADMETPrediction],
    molprop_rows: dict[int, CompoundMolPropPrediction],
) -> str:
    parts: list[str] = []
    for compound_id in sorted(set(compound_ids)):
        admet = admet_rows.get(compound_id)
        molprop = molprop_rows.get(compound_id)
        if admet:
            parts.append(f"{compound_id}:admet:{admet.smiles_sha256}:{admet.model_version or ''}")
        else:
            parts.append(f"{compound_id}:admet:none")
        if molprop:
            parts.append(f"{compound_id}:molprop:{molprop.smiles_sha256}:{molprop.model_version or ''}")
        else:
            parts.append(f"{compound_id}:molprop:none")
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _extract_molprop_uncertainty(molprop: CompoundMolPropPrediction | None) -> float | None:
    if not molprop or not isinstance(molprop.uncertainty, dict):
        return None
    vals = []
    for v in molprop.uncertainty.values():
        n = _as_prob(v)
        if n is not None:
            vals.append(n)
    if vals:
        return float(sum(vals) / len(vals))
    return None


def _get_endpoint_probs(admet_pred: dict, molprop_pred: dict, key: str) -> list[float]:
    vals = []
    a = _as_prob(admet_pred.get(key))
    if a is not None:
        vals.append(a)
    m = _as_prob(molprop_pred.get(key))
    if m is not None:
        vals.append(m)
    return vals


def _best_or_avg(values: list[float], mode: str = "max") -> float | None:
    if not values:
        return None
    if mode == "avg":
        return float(sum(values) / len(values))
    return float(max(values))


def _summarize_compound(
    compound,
    admet: CompoundADMETPrediction | None,
    molprop: CompoundMolPropPrediction | None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "compound_id": compound.id,
        "name": compound.name,
        "slug": getattr(compound, "slug", ""),
        "has_prediction": bool((admet and admet.predictions) or (molprop and molprop.predictions)),
        "has_molprop": bool(molprop and molprop.predictions),
    }

    admet_preds = admet.predictions if (admet and isinstance(admet.predictions, dict)) else {}
    molprop_preds = molprop.predictions if (molprop and isinstance(molprop.predictions, dict)) else {}
    if not admet_preds and not molprop_preds:
        return out

    tox_vals = []
    tox_flags = []
    for k in TOX_ENDPOINTS:
        vals = _get_endpoint_probs(admet_preds, molprop_preds, k)
        v = _best_or_avg(vals, mode="max")
        if v is None:
            continue
        tox_vals.append(v)
        if v >= 0.7:
            tox_flags.append({"endpoint": k, "score": v})
    tox_score = max(tox_vals) if tox_vals else None

    cyp_vals = []
    cyp_flags = []
    for src in (admet_preds, molprop_preds):
        for k, raw in src.items():
            key = str(k)
            if not key.upper().startswith("CYP"):
                continue
            v = _as_prob(raw)
            if v is None:
                continue
            cyp_vals.append(v)
            if v >= 0.7:
                cyp_flags.append({"endpoint": key, "score": v})
    cyp_score = max(cyp_vals) if cyp_vals else None

    bbb = _best_or_avg(_get_endpoint_probs(admet_preds, molprop_preds, "BBB_Martins"), mode="avg")
    bio = _best_or_avg(_get_endpoint_probs(admet_preds, molprop_preds, "Bioavailability_Ma"), mode="avg")
    hia = _best_or_avg(_get_endpoint_probs(admet_preds, molprop_preds, "HIA_Hou"), mode="avg")
    uncertainty = _extract_molprop_uncertainty(molprop)
    certainty = (1.0 - uncertainty) if uncertainty is not None else None

    # Stack "risk" is primarily toxicity + interaction likelihood.
    # MolProp certainty modulates confidence (not raw risk severity).
    compound_risk_raw = None
    if tox_score is not None or cyp_score is not None:
        base_risk = max(tox_score or 0.0, (cyp_score or 0.0) * 0.85)
        if certainty is not None:
            # increase/decrease confidence gently with certainty
            compound_risk_raw = max(0.0, min(1.0, base_risk * (0.9 + 0.2 * certainty)))
        else:
            compound_risk_raw = base_risk
    compound_risk = _apply_risk_curve(compound_risk_raw)

    out.update(
        {
            "tox_score": tox_score,
            "tox_flags": sorted(tox_flags, key=lambda x: -x["score"])[:4],
            "cyp_score": cyp_score,
            "cyp_flags": sorted(cyp_flags, key=lambda x: -x["score"])[:6],
            "bbb": bbb,
            "bioavailability": bio,
            "hia": hia,
            "compound_risk": compound_risk,
            "compound_risk_raw": compound_risk_raw,
            "uncertainty": uncertainty,
            "certainty": certainty,
        }
    )
    return out


@dataclass(frozen=True)
class StackRiskResult:
    assessment: StackRiskAssessment
    computed: bool


def get_or_compute_stack_risk(stack: Stack, items: list[StackItem] | None = None) -> StackRiskResult:
    """
    Computes and caches a stack-level risk assessment based on cached ADMET-AI predictions
    for the stack's compounds.
    """
    if items is None:
        items = list(stack.items.all().select_related("compound"))

    compound_ids = [i.compound_id for i in items]
    admet_qs = CompoundADMETPrediction.objects.filter(compound_id__in=compound_ids)
    molprop_qs = CompoundMolPropPrediction.objects.filter(compound_id__in=compound_ids)
    admet_map: dict[int, CompoundADMETPrediction] = {p.compound_id: p for p in admet_qs}
    molprop_map: dict[int, CompoundMolPropPrediction] = {p.compound_id: p for p in molprop_qs}

    input_hash = _stack_input_hash(compound_ids, admet_map, molprop_map)
    existing = getattr(stack, "risk_assessment", None)
    if existing and existing.input_hash == input_hash:
        # Backward-compatible: older cached assessments may not include newer fields like details.compounds.
        details = existing.details
        if isinstance(details, dict) and "compounds" in details:
            return StackRiskResult(assessment=existing, computed=False)

    per_compound = []
    predicted_count = 0
    molprop_count = 0
    for item in items:
        admet = admet_map.get(item.compound_id)
        molprop = molprop_map.get(item.compound_id)
        if admet and admet.predictions:
            predicted_count += 1
        if molprop and molprop.predictions:
            molprop_count += 1
        per_compound.append(_summarize_compound(item.compound, admet, molprop))

    # Overall stack risk = max compound risk (heuristic).
    risks = [c.get("compound_risk") for c in per_compound if isinstance(c.get("compound_risk"), (int, float))]
    risk_score = float(max(risks)) if risks else None
    level = _risk_level(risk_score, predicted_count)

    top = sorted(
        [c for c in per_compound if isinstance(c.get("compound_risk"), (int, float))],
        key=lambda c: -float(c.get("compound_risk") or 0.0),
    )[:5]

    compounds_sorted = sorted(
        per_compound,
        key=lambda c: (
            1 if c.get("compound_risk") is None else 0,
            -float(c.get("compound_risk") or 0.0),
            str(c.get("name") or ""),
        ),
    )

    details: dict[str, Any] = {
        "coverage": {
            "compound_count": len(set(compound_ids)),
            "predicted_count": predicted_count,
            "molprop_count": molprop_count,
        },
        "summary": {
            "risk_curve_gamma": RISK_CURVE_GAMMA,
            "tox_max": max(
                [c.get("tox_score") for c in per_compound if isinstance(c.get("tox_score"), (int, float))] or [None]
            ),
            "cyp_max": max(
                [c.get("cyp_score") for c in per_compound if isinstance(c.get("cyp_score"), (int, float))] or [None]
            ),
            "bbb_high_count": sum(1 for c in per_compound if isinstance(c.get("bbb"), (int, float)) and float(c["bbb"]) >= 0.7),
            "low_bioavailability_count": sum(
                1 for c in per_compound if isinstance(c.get("bioavailability"), (int, float)) and float(c["bioavailability"]) <= 0.3
            ),
            "mean_certainty": (
                sum(float(c["certainty"]) for c in per_compound if isinstance(c.get("certainty"), (int, float)))
                / max(1, sum(1 for c in per_compound if isinstance(c.get("certainty"), (int, float))))
            )
            if any(isinstance(c.get("certainty"), (int, float)) for c in per_compound)
            else None,
        },
        "top_compounds": top,
        "compounds": compounds_sorted,
    }

    with transaction.atomic():
        assessment, _created = StackRiskAssessment.objects.update_or_create(
            stack=stack,
            defaults={
                "input_hash": input_hash,
                "compound_count": len(set(compound_ids)),
                "predicted_count": predicted_count,
                "risk_score": risk_score,
                "risk_level": level,
                "details": details,
            },
        )

    return StackRiskResult(assessment=assessment, computed=True)
