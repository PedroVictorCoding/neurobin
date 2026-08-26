import hashlib
import math
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from compounds.models import CompoundADMETPrediction, CompoundMolPropPrediction, MetabolicInteractionEvidence

from .models import Stack, StackItem, StackRiskAssessment


TOX_ENDPOINTS = ("DILI", "AMES", "ClinTox", "Carcinogens_Lagunin")
ABS_ENDPOINTS = ("Bioavailability_Ma", "HIA_Hou")
BBB_ENDPOINTS = ("BBB_Martins",)
RISK_CURVE_GAMMA = 2.2
STACK_RISK_SCORE_VERSION = "stack-risk-log-v4"
ENZYME_SIGNAL_THRESHOLD = 0.5
ENZYME_OVERLOAD_MODERATE_THRESHOLD = 0.6
ENZYME_OVERLOAD_HIGH_THRESHOLD = 0.8
ENZYME_RISK_WEIGHT = 0.75
STACK_RISK_LOG_SCALE = 9.0
STACK_RISK_PEAK_WEIGHT = 0.65
STACK_RISK_MEAN_WEIGHT = 0.20
STACK_RISK_ELEVATED_WEIGHT = 0.15
STACK_RISK_ELEVATED_THRESHOLD = 0.5
STACK_RISK_MODERATE_THRESHOLD = 0.38
STACK_RISK_HIGH_THRESHOLD = 0.78


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


def _aggregate_stack_risk(compound_risks: list[float]) -> tuple[float | None, dict[str, float]]:
    valid = [max(0.0, min(1.0, float(risk))) for risk in compound_risks]
    if not valid:
        return None, {}

    peak_risk = max(valid)
    mean_risk = float(sum(valid) / len(valid))
    elevated_support = float(
        sum(risk for risk in valid if risk >= STACK_RISK_ELEVATED_THRESHOLD) / len(valid)
    )
    aggregate_signal = max(
        0.0,
        min(
            1.0,
            (peak_risk * STACK_RISK_PEAK_WEIGHT)
            + (mean_risk * STACK_RISK_MEAN_WEIGHT)
            + (elevated_support * STACK_RISK_ELEVATED_WEIGHT),
        ),
    )
    return _logarithmic_risk_dampening(aggregate_signal), {
        "peak_risk": peak_risk,
        "mean_risk": mean_risk,
        "elevated_support": elevated_support,
        "aggregate_signal": aggregate_signal,
    }


def _risk_level(score: float | None, predicted_count: int) -> str:
    if predicted_count <= 0 or score is None:
        return "unknown"
    if score >= STACK_RISK_HIGH_THRESHOLD:
        return "high"
    if score >= STACK_RISK_MODERATE_THRESHOLD:
        return "moderate"
    return "low"


def _logarithmic_risk_dampening(value: float | None, scale: float = STACK_RISK_LOG_SCALE) -> float | None:
    if value is None:
        return None
    v = max(0.0, min(1.0, float(value)))
    if v <= 0.0 or scale <= 0:
        return v
    if v >= 1.0:
        return 1.0

    denominator = math.log1p(scale)
    if denominator <= 0.0:
        return v

    dampened = 1.0 - (math.log1p(scale * (1.0 - v)) / denominator)
    return max(0.0, min(1.0, float(dampened)))


def _stack_input_hash(
    compound_ids: list[int],
    admet_rows: dict[int, CompoundADMETPrediction],
    molprop_rows: dict[int, CompoundMolPropPrediction],
    *,
    items: list[StackItem] | None = None,
    profile_revision: int | None = None,
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
    for item in sorted(items or [], key=lambda row: row.id):
        parts.append(
            f"item:{item.id}:{item.dosage_amount}:{item.dosage_unit}:"
            f"{item.intake_time}:{item.recurrence_interval}:{item.recurrence_unit}"
        )
    for evidence in MetabolicInteractionEvidence.objects.filter(
        compound_id__in=compound_ids, superseded_at__isnull=True,
    ).order_by('id').values_list('id', 'source_checksum', 'source_version'):
        parts.append(f"evidence:{evidence[0]}:{evidence[1]}:{evidence[2]}")
    parts.append(f"profile:{profile_revision or 'none'}")
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


def _merged_endpoint_probs(admet_pred: dict, molprop_pred: dict) -> dict[str, float]:
    """
    Merge endpoint probabilities by averaging shared numeric endpoints.
    """
    merged: dict[str, float] = {}
    all_keys = set(admet_pred.keys()) | set(molprop_pred.keys())
    for key in all_keys:
        vals: list[float] = []
        a = _as_prob(admet_pred.get(key))
        if a is not None:
            vals.append(a)
        m = _as_prob(molprop_pred.get(key))
        if m is not None:
            vals.append(m)
        if vals:
            merged[str(key)] = float(sum(vals) / len(vals))
    return merged


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

    merged_probs = _merged_endpoint_probs(admet_preds, molprop_preds)

    tox_vals = []
    tox_flags = []
    for k in TOX_ENDPOINTS:
        v = merged_probs.get(k)
        if v is None:
            continue
        tox_vals.append(v)
        if v >= 0.7:
            tox_flags.append({"endpoint": k, "score": v})
    tox_score = max(tox_vals) if tox_vals else None

    cyp_vals = []
    cyp_flags = []
    for key, v in merged_probs.items():
        if not str(key).upper().startswith("CYP"):
            continue
        cyp_vals.append(v)
        if v >= 0.7:
            cyp_flags.append({"endpoint": key, "score": v})
    cyp_score = max(cyp_vals) if cyp_vals else None

    bbb = merged_probs.get("BBB_Martins")
    bio = merged_probs.get("Bioavailability_Ma")
    hia = merged_probs.get("HIA_Hou")
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
            "cyp_endpoints": {
                str(key).upper(): value
                for key, value in merged_probs.items()
                if str(key).upper().startswith("CYP")
            },
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


def _assess_enzymatic_overload(compounds: list[dict[str, Any]]) -> dict[str, Any]:
    """Estimate shared CYP pathway pressure across predicted compounds.

    This is a screening signal, not a pharmacokinetic simulation. It combines
    independent model probabilities with pathway breadth and only reports an
    overload when at least two compounds contribute to the same CYP endpoint.
    """
    pathways: dict[str, list[dict[str, Any]]] = {}
    for compound in compounds:
        endpoints = compound.get("cyp_endpoints")
        if not isinstance(endpoints, dict):
            continue
        for enzyme, value in endpoints.items():
            probability = _as_prob(value)
            if probability is None or probability < ENZYME_SIGNAL_THRESHOLD:
                continue
            pathways.setdefault(str(enzyme).upper(), []).append(
                {
                    "compound_id": compound.get("compound_id"),
                    "name": compound.get("name"),
                    "score": probability,
                }
            )

    rows: list[dict[str, Any]] = []
    for enzyme, contributors in pathways.items():
        if len(contributors) < 2:
            continue
        combined_probability = 1.0
        for contributor in contributors:
            combined_probability *= 1.0 - float(contributor["score"])
        combined_probability = 1.0 - combined_probability
        breadth = min(1.0, (len(contributors) - 1) / 3.0)
        overload_score = min(1.0, (combined_probability * 0.75) + (breadth * 0.25))
        level = (
            "high"
            if overload_score >= ENZYME_OVERLOAD_HIGH_THRESHOLD
            else "moderate"
            if overload_score >= ENZYME_OVERLOAD_MODERATE_THRESHOLD
            else "low"
        )
        rows.append(
            {
                "enzyme": enzyme,
                "score": overload_score,
                "level": level,
                "compound_count": len(contributors),
                "contributors": sorted(contributors, key=lambda row: -float(row["score"])),
            }
        )

    rows.sort(key=lambda row: (-float(row["score"]), row["enzyme"]))
    overall_score = float(rows[0]["score"]) if rows else None
    return {
        "score": overall_score,
        "level": rows[0]["level"] if rows else "none",
        "pathway_count": len(rows),
        "pathways": rows,
        "signal_threshold": ENZYME_SIGNAL_THRESHOLD,
        "disclaimer": "Screening signal from predicted CYP endpoints; not a clinical interaction or dose model.",
    }


@dataclass(frozen=True)
class StackRiskResult:
    assessment: StackRiskAssessment
    computed: bool


def get_or_compute_stack_risk(stack: Stack, items: list[StackItem] | None = None) -> StackRiskResult:
    """
    Compute and cache stack-level risk assessment from cached prediction data.
    """
    if items is None:
        items = list(stack.items.all().select_related("compound"))

    compound_ids = [i.compound_id for i in items]
    admet_qs = CompoundADMETPrediction.objects.filter(compound_id__in=compound_ids)
    molprop_qs = CompoundMolPropPrediction.objects.filter(compound_id__in=compound_ids)
    admet_map: dict[int, CompoundADMETPrediction] = {p.compound_id: p for p in admet_qs}
    molprop_map: dict[int, CompoundMolPropPrediction] = {p.compound_id: p for p in molprop_qs}

    input_hash = _stack_input_hash(
        compound_ids, admet_map, molprop_map, items=items,
    )
    existing = getattr(stack, "risk_assessment", None)
    if existing and existing.input_hash == input_hash:
        # Older cached assessments may miss newer structure or use an outdated scoring model.
        details = existing.details
        summary = details.get("summary") if isinstance(details, dict) else None
        if (
            isinstance(details, dict)
            and "compounds" in details
            and isinstance(summary, dict)
            and summary.get("score_model_version") == STACK_RISK_SCORE_VERSION
        ):
            return StackRiskResult(assessment=existing, computed=False)

    per_compound = []
    predicted_count = 0
    molprop_count = 0
    for item in items:
        admet = admet_map.get(item.compound_id)
        molprop = molprop_map.get(item.compound_id)
        if (admet and admet.predictions) or (molprop and molprop.predictions):
            predicted_count += 1
        if molprop and molprop.predictions:
            molprop_count += 1
        per_compound.append(_summarize_compound(item.compound, admet, molprop))

    # Overall stack risk uses a conservative weighted blend, then log-dampens the high end.
    risks = [c.get("compound_risk") for c in per_compound if isinstance(c.get("compound_risk"), (int, float))]
    risk_score, stack_risk_components = _aggregate_stack_risk(risks)
    enzymatic_overload = _assess_enzymatic_overload(per_compound)
    # v4 deliberately does not let prediction overlap inflate clinical-looking risk.
    from .metabolic import assess_metabolic_interaction
    metabolic_interaction = assess_metabolic_interaction(
        items, predicted_compounds=per_compound, clinical_profile=None,
    )
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
            "score_model_version": STACK_RISK_SCORE_VERSION,
            "risk_curve_gamma": RISK_CURVE_GAMMA,
            "stack_log_scale": STACK_RISK_LOG_SCALE,
            "stack_peak_weight": STACK_RISK_PEAK_WEIGHT,
            "stack_mean_weight": STACK_RISK_MEAN_WEIGHT,
            "stack_elevated_weight": STACK_RISK_ELEVATED_WEIGHT,
            "stack_elevated_threshold": STACK_RISK_ELEVATED_THRESHOLD,
            "stack_peak_risk": stack_risk_components.get("peak_risk"),
            "stack_mean_risk": stack_risk_components.get("mean_risk"),
            "stack_elevated_support": stack_risk_components.get("elevated_support"),
            "stack_aggregate_signal": stack_risk_components.get("aggregate_signal"),
            "moderate_threshold": STACK_RISK_MODERATE_THRESHOLD,
            "high_threshold": STACK_RISK_HIGH_THRESHOLD,
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
        "enzymatic_overload": {**enzymatic_overload, "deprecated": True, "affects_risk_score": False},
        "metabolic_interaction_potential": metabolic_interaction,
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
