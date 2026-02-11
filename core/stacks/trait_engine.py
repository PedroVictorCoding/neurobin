from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from django.db import OperationalError, ProgrammingError
from django.db.models import Count, Q

from compounds.models import (
    Compound,
    CompoundTargetContextConsensus,
    CompoundTargetInteraction,
    CompoundTargetInteractionEvidence,
    CompoundToCompoundTargetInteraction,
)

from .models import MechanismTraitRule, StackDangerousPairRule, StackTrait


CONFIDENCE_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
EVIDENCE_CONF_MULT = {"unknown": 0.35, "low": 0.5, "medium": 0.75, "high": 1.0}
CONSENSUS_CONF_MULT = {"low": 0.6, "medium": 0.8, "high": 1.0}
PAIR_CONF_MULT = {"low": 0.6, "medium": 0.85, "high": 1.0}
PAIR_PENALTY_BY_TYPE = {
    "synergistic": -0.3,
    "antagonistic": 1.1,
    "competitive": 0.8,
    "competitive_metabolism": 1.6,
    "enzyme_inhibition": 1.4,
    "enzyme_induction": 1.1,
    "receptor_competition": 0.9,
    "additive": 0.2,
    "unknown": 0.5,
}
HARD_BLOCK_INTERACTION_TYPES = {"competitive_metabolism"}
ANDROGENIC_NAME_HINTS = {
    "testosterone",
    "methenolone",
    "metenolone",
    "nandrolone",
    "trenbolone",
    "boldenone",
    "oxandrolone",
    "oxymetholone",
    "stanozolol",
    "drostanolone",
    "mesterolone",
    "fluoxymesterone",
    "dihydrotestosterone",
}
HEURISTIC_NAME_CONF_LEVEL = "low"
LEGACY_FALLBACK_CONF_LEVEL = "low"
MECHANISM_POLARITY = {
    "agonist": 1,
    "partial_agonist": 1,
    "inverse_agonist": -1,
    "pam": 1,
    "nam": -1,
    "inhibitor": -1,
    "inducer": 1,
    "activator": 1,
    "binder": 0,
    "substrate": 0,
    "modulator": 0,
    "blocker": -1,
    "opener": 1,
    "antagonist": -1,
    "unknown": 0,
}

DISCLAIMER = (
    "Evidence-weighted hypothesis only. This output is not medical advice and should not be "
    "used as diagnosis or treatment guidance."
)

GROUPING_PRESETS: dict[str, dict[str, Any]] = {
    # Anabolism
    "anabolism_ar": {
        "label": "Anabolism: AR axis",
        "trait_slug": "anabolism",
        "target_keywords": [
            "androgen receptor",
            "nr3c4",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "modulator",
            "activator",
            "binder",
        ],
        "good_affinity_nm": 150.0,
        "category_names": [
            "Anabolism",
            "Anabolism - AR Axis",
        ],
    },
    "anabolism_igf1": {
        "label": "Anabolism: IGF-1 axis",
        "trait_slug": "anabolism",
        "target_keywords": [
            "igf-1 receptor",
            "igf1 receptor",
            "igf1r",
            "insulin-like growth factor 1 receptor",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "activator",
            "modulator",
            "binder",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Anabolism",
            "Anabolism - IGF1 Axis",
        ],
    },
    "anabolism_gh": {
        "label": "Anabolism: GH axis",
        "trait_slug": "anabolism",
        "target_keywords": [
            "growth hormone receptor",
            "gh receptor",
            "ghr",
            "growth hormone secretagogue receptor",
            "ghrelin receptor",
            "ghrh receptor",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "activator",
            "modulator",
            "binder",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Anabolism",
            "Anabolism - GH Axis",
        ],
    },
    # Longevity
    "longevity_ampk": {
        "label": "Longevity: AMPK activation",
        "trait_slug": "longevity",
        "target_keywords": [
            "ampk",
            "prkaa",
        ],
        "mechanisms": [
            "activator",
            "agonist",
            "modulator",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Longevity",
            "Longevity - AMPK",
        ],
    },
    "longevity_sirtuin": {
        "label": "Longevity: Sirtuin axis",
        "trait_slug": "longevity",
        "target_keywords": [
            "sirt1",
            "sirtuin",
        ],
        "mechanisms": [
            "activator",
            "agonist",
            "modulator",
        ],
        "good_affinity_nm": 400.0,
        "category_names": [
            "Longevity",
            "Longevity - Sirtuin",
        ],
    },
    "longevity_mtor_brake": {
        "label": "Longevity: mTOR brake",
        "trait_slug": "longevity",
        "target_keywords": [
            "mtor",
            "mechanistic target of rapamycin",
        ],
        "mechanisms": [
            "inhibitor",
            "antagonist",
            "nam",
            "blocker",
            "modulator",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Longevity",
            "Longevity - mTOR Brake",
        ],
    },
    # Sleep
    "sleep_gaba": {
        "label": "Sleep: GABAergic tone",
        "trait_slug": "sleep",
        "target_keywords": [
            "gaba",
            "gabra",
            "gabrb",
        ],
        "mechanisms": [
            "agonist",
            "pam",
            "modulator",
            "activator",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Sleep",
            "Sleep - GABA",
        ],
    },
    "sleep_orexin": {
        "label": "Sleep: Orexin antagonism",
        "trait_slug": "sleep",
        "target_keywords": [
            "orexin",
            "hcrtr",
            "hypocretin receptor",
        ],
        "mechanisms": [
            "antagonist",
            "inhibitor",
            "blocker",
            "nam",
        ],
        "good_affinity_nm": 200.0,
        "category_names": [
            "Sleep",
            "Sleep - Orexin",
        ],
    },
    "sleep_melatonin": {
        "label": "Sleep: Melatonin axis",
        "trait_slug": "sleep",
        "target_keywords": [
            "melatonin receptor",
            "mt1",
            "mt2",
            "mtnr1a",
            "mtnr1b",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "modulator",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Sleep",
            "Sleep - Melatonin",
        ],
    },
    # Cognition
    "cognition_cholinergic": {
        "label": "Cognition: Cholinergic support",
        "trait_slug": "cognition",
        "target_keywords": [
            "nicotinic acetylcholine",
            "muscarinic",
            "acetylcholinesterase",
            "chrm",
            "chrn",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "pam",
            "modulator",
            "inhibitor",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Cognition",
            "Cognition - Cholinergic",
        ],
    },
    "cognition_glutamatergic": {
        "label": "Cognition: Glutamatergic tuning",
        "trait_slug": "cognition",
        "target_keywords": [
            "nmda",
            "grin",
            "ampa",
            "gria",
            "metabotropic glutamate",
            "grm",
        ],
        "mechanisms": [
            "modulator",
            "pam",
            "agonist",
            "partial_agonist",
        ],
        "good_affinity_nm": 350.0,
        "category_names": [
            "Cognition",
            "Cognition - Glutamatergic",
        ],
    },
    "cognition_dopaminergic": {
        "label": "Cognition: Dopaminergic drive",
        "trait_slug": "cognition",
        "target_keywords": [
            "dopamine",
            "drd",
            "dat",
            "slc6a3",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "modulator",
            "inhibitor",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Cognition",
            "Cognition - Dopaminergic",
        ],
    },
    # Anti-inflammatory
    "anti_inflammatory_cox": {
        "label": "Anti-inflammatory: COX axis",
        "trait_slug": "anti_inflammatory",
        "target_keywords": [
            "cox",
            "ptgs1",
            "ptgs2",
            "cyclooxygenase",
        ],
        "mechanisms": [
            "inhibitor",
            "antagonist",
            "blocker",
            "nam",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Anti-inflammatory",
            "Anti-inflammatory - COX",
        ],
    },
    "anti_inflammatory_nfkb": {
        "label": "Anti-inflammatory: NF-kB axis",
        "trait_slug": "anti_inflammatory",
        "target_keywords": [
            "nf-kb",
            "nfkb",
            "ikk",
            "rela",
        ],
        "mechanisms": [
            "inhibitor",
            "antagonist",
            "modulator",
            "nam",
        ],
        "good_affinity_nm": 400.0,
        "category_names": [
            "Anti-inflammatory",
            "Anti-inflammatory - NF-kB",
        ],
    },
    "anti_inflammatory_cytokine": {
        "label": "Anti-inflammatory: Cytokine brake",
        "trait_slug": "anti_inflammatory",
        "target_keywords": [
            "tnf",
            "interleukin",
            "il-",
            "il6",
            "il1",
        ],
        "mechanisms": [
            "inhibitor",
            "antagonist",
            "blocker",
            "modulator",
        ],
        "good_affinity_nm": 500.0,
        "category_names": [
            "Anti-inflammatory",
            "Anti-inflammatory - Cytokine",
        ],
    },
    # Metabolic health
    "metabolic_health_glp1": {
        "label": "Metabolic Health: GLP-1 axis",
        "trait_slug": "metabolic_health",
        "target_keywords": [
            "glp-1 receptor",
            "glp1 receptor",
            "glp1r",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "activator",
            "modulator",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Metabolic Health",
            "Metabolic Health - GLP1",
        ],
    },
    "metabolic_health_ppar": {
        "label": "Metabolic Health: PPAR axis",
        "trait_slug": "metabolic_health",
        "target_keywords": [
            "ppar",
            "ppara",
            "ppard",
            "pparg",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "activator",
            "modulator",
        ],
        "good_affinity_nm": 350.0,
        "category_names": [
            "Metabolic Health",
            "Metabolic Health - PPAR",
        ],
    },
    "metabolic_health_insulin_sensitivity": {
        "label": "Metabolic Health: Insulin sensitivity",
        "trait_slug": "metabolic_health",
        "target_keywords": [
            "insulin receptor",
            "insr",
            "akt",
            "pi3k",
        ],
        "mechanisms": [
            "agonist",
            "activator",
            "modulator",
            "pam",
        ],
        "good_affinity_nm": 450.0,
        "category_names": [
            "Metabolic Health",
            "Metabolic Health - Insulin Sensitivity",
        ],
    },
    # Anxiety relief
    "anxiety_gaba": {
        "label": "Anxiety: GABAergic",
        "trait_slug": "anxiety_relief",
        "target_keywords": [
            "gaba",
            "gabra",
            "gabrb",
        ],
        "mechanisms": [
            "agonist",
            "pam",
            "modulator",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Anxiety Relief",
            "Anxiety Relief - GABA",
        ],
    },
    "anxiety_5ht1a": {
        "label": "Anxiety: 5-HT1A axis",
        "trait_slug": "anxiety_relief",
        "target_keywords": [
            "5-ht1a",
            "htr1a",
            "serotonin 1a",
        ],
        "mechanisms": [
            "agonist",
            "partial_agonist",
            "modulator",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Anxiety Relief",
            "Anxiety Relief - 5HT1A",
        ],
    },
    "anxiety_beta_blockade": {
        "label": "Anxiety: Beta-adrenergic blockade",
        "trait_slug": "anxiety_relief",
        "target_keywords": [
            "beta-adrenergic",
            "adrb",
            "adrenoceptor beta",
        ],
        "mechanisms": [
            "antagonist",
            "blocker",
            "inhibitor",
            "nam",
        ],
        "good_affinity_nm": 350.0,
        "category_names": [
            "Anxiety Relief",
            "Anxiety Relief - Beta Blockade",
        ],
    },
    # Oncoprotection hypothesis
    "oncoprotection_pi3k_mtor": {
        "label": "Oncoprotection: PI3K/mTOR brake",
        "trait_slug": "oncoprotection_hypothesis",
        "target_keywords": [
            "pi3k",
            "akt",
            "mtor",
        ],
        "mechanisms": [
            "inhibitor",
            "antagonist",
            "blocker",
            "modulator",
        ],
        "good_affinity_nm": 250.0,
        "category_names": [
            "Oncoprotection Hypothesis",
            "Oncoprotection - PI3K mTOR",
        ],
    },
    "oncoprotection_aromatase": {
        "label": "Oncoprotection: Aromatase control",
        "trait_slug": "oncoprotection_hypothesis",
        "target_keywords": [
            "aromatase",
            "cyp19a1",
        ],
        "mechanisms": [
            "inhibitor",
            "antagonist",
            "blocker",
        ],
        "good_affinity_nm": 300.0,
        "category_names": [
            "Oncoprotection Hypothesis",
            "Oncoprotection - Aromatase",
        ],
    },
    "oncoprotection_nrf2": {
        "label": "Oncoprotection: NRF2 antioxidant axis",
        "trait_slug": "oncoprotection_hypothesis",
        "target_keywords": [
            "nrf2",
            "nfe2l2",
            "keap1",
        ],
        "mechanisms": [
            "activator",
            "modulator",
            "pam",
        ],
        "good_affinity_nm": 500.0,
        "category_names": [
            "Oncoprotection Hypothesis",
            "Oncoprotection - NRF2",
        ],
    },
}

FOCUS_GROUP_ALIASES = {
    "ar": "anabolism_ar",
    "androgen": "anabolism_ar",
    "androgen_receptor": "anabolism_ar",
    "igf1": "anabolism_igf1",
    "igf-1": "anabolism_igf1",
    "insulin_like_growth_factor_1": "anabolism_igf1",
    "gh": "anabolism_gh",
    "growth_hormone": "anabolism_gh",
    "ampk": "longevity_ampk",
    "sirtuin": "longevity_sirtuin",
    "mtor_brake": "longevity_mtor_brake",
    "sleep_gaba": "sleep_gaba",
    "orexin": "sleep_orexin",
    "melatonin": "sleep_melatonin",
    "cholinergic": "cognition_cholinergic",
    "glutamatergic": "cognition_glutamatergic",
    "dopaminergic": "cognition_dopaminergic",
    "cox": "anti_inflammatory_cox",
    "nfkb": "anti_inflammatory_nfkb",
    "cytokine": "anti_inflammatory_cytokine",
    "glp1": "metabolic_health_glp1",
    "ppar": "metabolic_health_ppar",
    "insulin_sensitivity": "metabolic_health_insulin_sensitivity",
    "anxiety_gaba": "anxiety_gaba",
    "5ht1a": "anxiety_5ht1a",
    "beta_blockade": "anxiety_beta_blockade",
    "oncoprotection_pi3k": "oncoprotection_pi3k_mtor",
    "oncoprotection_aromatase": "oncoprotection_aromatase",
    "oncoprotection_nrf2": "oncoprotection_nrf2",
}


@dataclass(frozen=True)
class TraitSpec:
    slug: str
    label: str
    trait_type: str
    min_score: float
    max_score: float
    default_weight: float
    is_hypothesis: bool
    display_order: int


@dataclass(frozen=True)
class RuleSpec:
    rule_id: int | None
    mechanism: str
    trait_slug: str
    delta: float
    base_confidence: float
    target_name_contains: str
    species: str
    assay_type: str
    route: str
    source: str
    notes: str
    priority: int


DEFAULT_TRAITS: list[dict[str, Any]] = [
    {
        "slug": "longevity",
        "label": "Longevity",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.0,
        "is_hypothesis": False,
        "display_order": 10,
    },
    {
        "slug": "anabolism",
        "label": "Anabolism",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.0,
        "is_hypothesis": False,
        "display_order": 20,
    },
    {
        "slug": "cognition",
        "label": "Cognition",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.0,
        "is_hypothesis": False,
        "display_order": 30,
    },
    {
        "slug": "sleep",
        "label": "Sleep",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 0.9,
        "is_hypothesis": False,
        "display_order": 40,
    },
    {
        "slug": "anti_inflammatory",
        "label": "Anti-Inflammatory",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 0.9,
        "is_hypothesis": False,
        "display_order": 50,
    },
    {
        "slug": "metabolic_health",
        "label": "Metabolic Health",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.0,
        "is_hypothesis": False,
        "display_order": 60,
    },
    {
        "slug": "oncoprotection_hypothesis",
        "label": "Oncoprotection Hypothesis",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 0.8,
        "is_hypothesis": True,
        "display_order": 70,
    },
    {
        "slug": "anxiety_relief",
        "label": "Anxiety Relief",
        "trait_type": "benefit",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 0.9,
        "is_hypothesis": False,
        "display_order": 80,
    },
    {
        "slug": "cancer_risk",
        "label": "Cancer Risk",
        "trait_type": "risk",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.2,
        "is_hypothesis": False,
        "display_order": 90,
    },
    {
        "slug": "cardio_risk",
        "label": "Cardiovascular Risk",
        "trait_type": "risk",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.2,
        "is_hypothesis": False,
        "display_order": 100,
    },
    {
        "slug": "dependence_risk",
        "label": "Dependence Risk",
        "trait_type": "risk",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 1.1,
        "is_hypothesis": False,
        "display_order": 110,
    },
    {
        "slug": "sedation_risk",
        "label": "Sedation Risk",
        "trait_type": "risk",
        "min_score": -5.0,
        "max_score": 5.0,
        "default_weight": 0.8,
        "is_hypothesis": False,
        "display_order": 120,
    },
]

DEFAULT_RULES: list[dict[str, Any]] = [
    # AMPK/energy metabolism
    {"mechanism": "activator", "trait_slug": "longevity", "delta": 1.2, "target_name_contains": "ampk", "priority": 10},
    {
        "mechanism": "activator",
        "trait_slug": "metabolic_health",
        "delta": 1.5,
        "target_name_contains": "ampk",
        "priority": 10,
    },
    {
        "mechanism": "activator",
        "trait_slug": "oncoprotection_hypothesis",
        "delta": 0.6,
        "target_name_contains": "ampk",
        "priority": 20,
    },
    # AR axis
    {
        "mechanism": "agonist",
        "trait_slug": "anabolism",
        "delta": 1.8,
        "target_name_contains": "androgen receptor",
        "priority": 10,
    },
    {
        "mechanism": "agonist",
        "trait_slug": "cardio_risk",
        "delta": 1.0,
        "target_name_contains": "androgen receptor",
        "priority": 10,
    },
    {
        "mechanism": "agonist",
        "trait_slug": "cancer_risk",
        "delta": 0.9,
        "target_name_contains": "androgen receptor",
        "priority": 10,
    },
    # GABA axis
    {"mechanism": "agonist", "trait_slug": "anxiety_relief", "delta": 1.2, "target_name_contains": "gaba", "priority": 10},
    {"mechanism": "agonist", "trait_slug": "sleep", "delta": 1.0, "target_name_contains": "gaba", "priority": 10},
    {
        "mechanism": "agonist",
        "trait_slug": "dependence_risk",
        "delta": 1.1,
        "target_name_contains": "gaba",
        "priority": 10,
    },
    {
        "mechanism": "agonist",
        "trait_slug": "sedation_risk",
        "delta": 1.3,
        "target_name_contains": "gaba",
        "priority": 10,
    },
    # Anti-inflammatory patterns
    {"mechanism": "inhibitor", "trait_slug": "anti_inflammatory", "delta": 0.6, "target_name_contains": "cox", "priority": 20},
    {"mechanism": "inhibitor", "trait_slug": "anti_inflammatory", "delta": 0.5, "target_name_contains": "nf-kb", "priority": 20},
    # General fallback rules
    {"mechanism": "activator", "trait_slug": "metabolic_health", "delta": 0.3, "priority": 200},
    {"mechanism": "agonist", "trait_slug": "cognition", "delta": 0.2, "priority": 200},
    {"mechanism": "inhibitor", "trait_slug": "anti_inflammatory", "delta": 0.2, "priority": 220},
    {"mechanism": "inducer", "trait_slug": "cardio_risk", "delta": 0.2, "priority": 240},
    {"mechanism": "modulator", "trait_slug": "cognition", "delta": 0.2, "priority": 240},
]


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _norm_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _compound_text_blob(compound: Compound) -> str:
    return " ".join(
        [
            _norm_text(compound.name),
            _norm_text(getattr(compound, "aliases", "")),
        ]
    ).strip()


def _normalize_focus_group_slug(raw: str | None) -> str:
    slug = _norm_text(raw).replace(" ", "_")
    slug = FOCUS_GROUP_ALIASES.get(slug, slug)
    return slug if slug in GROUPING_PRESETS else ""


def parse_focus_groups(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [part for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(part) for part in raw]
    else:
        values = [str(raw)]

    out = []
    seen = set()
    for value in values:
        slug = _normalize_focus_group_slug(value)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def grouping_preset_options() -> list[dict[str, Any]]:
    return [
        {
            "slug": slug,
            "label": config["label"],
            "trait_slug": config.get("trait_slug", ""),
            "mechanisms": list(config.get("mechanisms", [])),
            "target_keywords": list(config.get("target_keywords", [])),
            "category_names": list(config.get("category_names", [])),
            "good_affinity_nm": config.get("good_affinity_nm"),
        }
        for slug, config in GROUPING_PRESETS.items()
    ]


def _affinity_signal_multiplier(value_nm: float | None, good_affinity_nm: float | None) -> float:
    if value_nm is None:
        return 0.85
    if value_nm <= 0:
        return 0.8
    if not good_affinity_nm:
        good_affinity_nm = 250.0
    if value_nm <= good_affinity_nm:
        return 1.4
    if value_nm <= good_affinity_nm * 5.0:
        return 1.0
    if value_nm <= good_affinity_nm * 20.0:
        return 0.7
    return 0.45


def _evidence_matches_grouping(evidence: CompoundTargetInteractionEvidence, config: dict[str, Any]) -> bool:
    mechanisms = set(config.get("mechanisms") or [])
    if mechanisms and evidence.canonical_mechanism not in mechanisms:
        return False
    target_name = _norm_text(getattr(evidence.target, "name", ""))
    target_keywords = config.get("target_keywords") or []
    if target_keywords and not any(keyword in target_name for keyword in target_keywords):
        return False
    return True


def _context_match_factor(evidence: CompoundTargetInteractionEvidence, desired_context: dict[str, str]) -> float:
    if not desired_context:
        return 1.0

    factor = 1.0
    for field_name, desired_value in desired_context.items():
        desired = _norm_text(desired_value)
        if not desired:
            continue
        actual = _norm_text(getattr(evidence, field_name, ""))
        if not actual:
            factor *= 0.85
        elif desired == actual:
            factor *= 1.0
        elif desired in actual or actual in desired:
            factor *= 0.9
        else:
            factor *= 0.6
    return factor


def _confidence_rank(value: str | None) -> int:
    return CONFIDENCE_RANK.get(_norm_text(value), 0)


def _confidence_band(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _mechanism_polarity(mechanism: str | None) -> int:
    return int(MECHANISM_POLARITY.get(_norm_text(mechanism), 0))


def _bayesian_confidence(
    support_mass: float,
    uncertainty_mass: float,
    *,
    prior_alpha: float = 0.75,
    prior_beta: float = 2.25,
) -> float:
    support = max(0.0, float(support_mass or 0.0))
    uncertainty = max(0.0, float(uncertainty_mass or 0.0))
    alpha = max(0.001, float(prior_alpha)) + support
    beta = max(0.001, float(prior_beta)) + uncertainty
    return _clip(alpha / max(0.001, alpha + beta), 0.0, 1.0)


def _normalize_goals(goals: dict[str, Any] | None) -> dict[str, float]:
    normalized: dict[str, float] = {}
    if not goals:
        return normalized
    for slug, weight in goals.items():
        try:
            numeric = float(weight)
        except (TypeError, ValueError):
            continue
        if numeric == 0.0:
            continue
        normalized[str(slug).strip()] = numeric
    return normalized


def _load_trait_specs() -> dict[str, TraitSpec]:
    try:
        db_traits = list(StackTrait.objects.filter(is_active=True).order_by("display_order", "id"))
    except (OperationalError, ProgrammingError):
        db_traits = []
    if db_traits:
        return {
            trait.slug: TraitSpec(
                slug=trait.slug,
                label=trait.label,
                trait_type=trait.trait_type,
                min_score=float(trait.min_score),
                max_score=float(trait.max_score),
                default_weight=float(trait.default_weight),
                is_hypothesis=bool(trait.is_hypothesis),
                display_order=int(trait.display_order),
            )
            for trait in db_traits
        }
    return {
        row["slug"]: TraitSpec(
            slug=row["slug"],
            label=row["label"],
            trait_type=row["trait_type"],
            min_score=float(row["min_score"]),
            max_score=float(row["max_score"]),
            default_weight=float(row["default_weight"]),
            is_hypothesis=bool(row["is_hypothesis"]),
            display_order=int(row["display_order"]),
        )
        for row in DEFAULT_TRAITS
    }


def _load_rule_specs(known_traits: set[str]) -> dict[str, list[RuleSpec]]:
    try:
        db_rules = list(
            MechanismTraitRule.objects.filter(is_active=True, trait__is_active=True)
            .select_related("trait")
            .order_by("priority", "id")
        )
    except (OperationalError, ProgrammingError):
        db_rules = []
    if db_rules:
        grouped: dict[str, list[RuleSpec]] = defaultdict(list)
        for rule in db_rules:
            trait_slug = rule.trait.slug
            if trait_slug not in known_traits:
                continue
            grouped[rule.mechanism].append(
                RuleSpec(
                    rule_id=rule.id,
                    mechanism=rule.mechanism,
                    trait_slug=trait_slug,
                    delta=float(rule.delta),
                    base_confidence=float(rule.base_confidence),
                    target_name_contains=_norm_text(rule.target_name_contains),
                    species=_norm_text(rule.species),
                    assay_type=_norm_text(rule.assay_type),
                    route=_norm_text(rule.route),
                    source=rule.source or "",
                    notes=rule.notes or "",
                    priority=int(rule.priority),
                )
            )
        return grouped

    grouped = defaultdict(list)
    for idx, row in enumerate(DEFAULT_RULES, start=1):
        trait_slug = row["trait_slug"]
        if trait_slug not in known_traits:
            continue
        grouped[row["mechanism"]].append(
            RuleSpec(
                rule_id=None,
                mechanism=row["mechanism"],
                trait_slug=trait_slug,
                delta=float(row["delta"]),
                base_confidence=float(row.get("base_confidence", 0.7)),
                target_name_contains=_norm_text(row.get("target_name_contains", "")),
                species=_norm_text(row.get("species", "")),
                assay_type=_norm_text(row.get("assay_type", "")),
                route=_norm_text(row.get("route", "")),
                source=row.get("source", "default"),
                notes=row.get("notes", ""),
                priority=int(row.get("priority", 1000 + idx)),
            )
        )
    for mechanism in grouped:
        grouped[mechanism].sort(key=lambda item: (item.priority, item.trait_slug))
    return grouped


def _trait_entry(spec: TraitSpec, score: float, confidence: float) -> dict[str, Any]:
    span = max(0.01, float(spec.max_score) - float(spec.min_score))
    bar_percent = _clip(((float(score) - float(spec.min_score)) / span) * 100.0, 0.0, 100.0)
    return {
        "slug": spec.slug,
        "label": spec.label,
        "trait_type": spec.trait_type,
        "score": round(float(score), 3),
        "confidence": round(float(confidence), 3),
        "min_score": spec.min_score,
        "max_score": spec.max_score,
        "bar_percent": round(float(bar_percent), 2),
        "is_hypothesis": spec.is_hypothesis,
    }


class TraitEngine:
    def __init__(self, *, desired_context: dict[str, str] | None = None, min_evidence_confidence: str = "low"):
        self.desired_context = {
            str(k): str(v)
            for k, v in (desired_context or {}).items()
            if str(v).strip()
        }
        self.min_evidence_confidence = _norm_text(min_evidence_confidence) or "low"
        self.min_rank = _confidence_rank(self.min_evidence_confidence)
        self.traits = _load_trait_specs()
        self.rules_by_mechanism = _load_rule_specs(set(self.traits.keys()))
        self._compound_cache: dict[int, dict[str, Any]] = {}

    def _compound_consensus_map(self, compound_id: int) -> dict[tuple[int, str], CompoundTargetContextConsensus]:
        rows = CompoundTargetContextConsensus.objects.filter(compound_id=compound_id).only(
            "target_id",
            "context_key",
            "consensus_confidence",
            "has_conflict",
        )
        return {(row.target_id, row.context_key): row for row in rows}

    def _rule_matches(self, rule: RuleSpec, evidence: CompoundTargetInteractionEvidence) -> bool:
        target_name = _norm_text(getattr(evidence.target, "name", ""))
        if rule.target_name_contains and rule.target_name_contains not in target_name:
            return False
        if rule.species:
            ev_species = _norm_text(evidence.species)
            if ev_species and ev_species != rule.species:
                return False
        if rule.assay_type:
            ev_assay = _norm_text(evidence.assay_type)
            if ev_assay and ev_assay != rule.assay_type:
                return False
        if rule.route:
            ev_route = _norm_text(evidence.route)
            if ev_route and ev_route != rule.route:
                return False
        return True

    def _apply_legacy_interaction_fallback(
        self,
        *,
        compound: Compound,
        trait_score_map: dict[str, float],
        trait_weight_map: dict[str, float],
        provenance_map: dict[str, list[dict[str, Any]]],
        group_signal_score: dict[str, float],
        group_hits: dict[str, list[dict[str, Any]]],
        evidence_level_counts: dict[str, int],
        mechanism_counts: dict[str, int],
        target_mechanisms: dict[int, set[str]],
        target_polarities: dict[int, set[int]],
        target_sources: dict[int, set[str]],
        target_names: dict[int, str],
        target_row_count: dict[int, int],
    ) -> tuple[int, float, float]:
        if self.min_rank > _confidence_rank(LEGACY_FALLBACK_CONF_LEVEL):
            return 0, 0.0, 0.0

        legacy_rows = (
            CompoundTargetInteraction.objects.filter(compound=compound)
            .exclude(mechanism="unknown")
            .select_related("target")
            .order_by("id")
        )
        if not legacy_rows:
            return 0, 0.0, 0.0

        matched_rows = 0
        support_mass = 0.0
        uncertainty_mass = 0.0
        evidence_conf = EVIDENCE_CONF_MULT.get(LEGACY_FALLBACK_CONF_LEVEL, 0.5)
        evidence_weight = 1.6
        context_factor = 0.9
        consensus_factor = 0.9
        quality_mass = evidence_weight * evidence_conf * context_factor * consensus_factor

        for row in legacy_rows:
            mechanism = _norm_text(row.mechanism) or "unknown"
            if mechanism == "unknown":
                continue
            rules = self.rules_by_mechanism.get(mechanism, [])
            if not rules:
                continue
            target_name = _norm_text(getattr(row.target, "name", ""))
            for rule in rules:
                if rule.target_name_contains and rule.target_name_contains not in target_name:
                    continue
                if rule.species or rule.assay_type or rule.route:
                    continue

                trait_spec = self.traits.get(rule.trait_slug)
                if trait_spec is None:
                    continue
                contribution = (
                    float(rule.delta)
                    * evidence_weight
                    * evidence_conf
                    * consensus_factor
                    * context_factor
                    * max(0.0, min(1.0, float(rule.base_confidence)))
                )
                if contribution == 0:
                    continue
                matched_rows += 1
                trait_score_map[rule.trait_slug] += contribution
                trait_weight_map[rule.trait_slug] += abs(
                    evidence_weight * evidence_conf * consensus_factor * max(0.2, float(rule.base_confidence))
                )
                provenance_map[rule.trait_slug].append(
                    {
                        "target": getattr(row.target, "name", ""),
                        "mechanism": mechanism,
                        "source": "legacy_compound_target_interaction",
                        "evidence_level": LEGACY_FALLBACK_CONF_LEVEL,
                        "evidence_weight": round(evidence_weight, 3),
                        "context_key": "legacy::unknown_context",
                        "context_match_factor": round(context_factor, 3),
                        "contribution": round(contribution, 4),
                        "rule_id": rule.rule_id,
                        "rule_priority": rule.priority,
                        "rule_source": rule.source,
                    }
                )

            for group_slug, config in GROUPING_PRESETS.items():
                mechanisms = set(config.get("mechanisms") or [])
                target_keywords = config.get("target_keywords") or []
                if mechanisms and mechanism not in mechanisms:
                    continue
                if target_keywords and not any(keyword in target_name for keyword in target_keywords):
                    continue
                affinity_mult = _affinity_signal_multiplier(
                    None,
                    float(config.get("good_affinity_nm")) if config.get("good_affinity_nm") else None,
                )
                signal = max(0.05, evidence_weight * evidence_conf * context_factor * affinity_mult)
                group_signal_score[group_slug] += signal
                group_hits[group_slug].append(
                    {
                        "target": getattr(row.target, "name", ""),
                        "mechanism": mechanism,
                        "source": "legacy_compound_target_interaction",
                        "evidence_level": LEGACY_FALLBACK_CONF_LEVEL,
                        "affinity_value_nm": None,
                        "signal": round(signal, 4),
                    }
                )

            evidence_level_counts[LEGACY_FALLBACK_CONF_LEVEL] += 1
            mechanism_counts[mechanism] += 1
            target_id = int(getattr(row, "target_id", 0) or 0)
            if target_id > 0:
                target_row_count[target_id] += 1
                target_names[target_id] = getattr(row.target, "name", "")
                target_mechanisms[target_id].add(mechanism)
                target_sources[target_id].add("legacy_compound_target_interaction")
                polarity = _mechanism_polarity(mechanism)
                if polarity != 0:
                    target_polarities[target_id].add(polarity)

            support_mass += quality_mass
            uncertainty_mass += max(0.0, evidence_weight * (1.0 - evidence_conf) * context_factor)

        return matched_rows, support_mass, uncertainty_mass

    def _apply_androgenic_name_heuristic(
        self,
        *,
        compound: Compound,
        trait_score_map: dict[str, float],
        trait_weight_map: dict[str, float],
        provenance_map: dict[str, list[dict[str, Any]]],
        group_signal_score: dict[str, float],
        group_hits: dict[str, list[dict[str, Any]]],
        evidence_level_counts: dict[str, int],
        mechanism_counts: dict[str, int],
    ) -> tuple[bool, float, float]:
        if self.min_rank > _confidence_rank(HEURISTIC_NAME_CONF_LEVEL):
            return False, 0.0, 0.0

        text_blob = _compound_text_blob(compound)
        name_hits = sorted([hint for hint in ANDROGENIC_NAME_HINTS if hint in text_blob])
        if not name_hits:
            return False, 0.0, 0.0

        heuristic_contribs = {
            "anabolism": 0.55,
            "cardio_risk": 0.18,
            "cancer_risk": 0.16,
        }
        evidence_conf = EVIDENCE_CONF_MULT.get(HEURISTIC_NAME_CONF_LEVEL, 0.5)
        evidence_weight = 1.2
        confidence_mass = evidence_weight * evidence_conf
        for trait_slug, delta in heuristic_contribs.items():
            if trait_slug not in self.traits:
                continue
            trait_score_map[trait_slug] += float(delta)
            trait_weight_map[trait_slug] += confidence_mass * 0.75
            provenance_map[trait_slug].append(
                {
                    "target": "androgenic scaffold heuristic",
                    "mechanism": "heuristic_androgenic_name",
                    "source": "name_heuristic.androgenic_scaffold",
                    "evidence_level": HEURISTIC_NAME_CONF_LEVEL,
                    "evidence_weight": round(evidence_weight, 3),
                    "context_key": "heuristic::name",
                    "context_match_factor": 1.0,
                    "contribution": round(float(delta), 4),
                    "rule_id": None,
                    "rule_priority": 9999,
                    "rule_source": "name_heuristic",
                }
            )

        if "anabolism_ar" in group_signal_score:
            signal = 0.75
            group_signal_score["anabolism_ar"] += signal
            group_hits["anabolism_ar"].append(
                {
                    "target": "androgenic scaffold heuristic",
                    "mechanism": "heuristic_androgenic_name",
                    "source": "name_heuristic.androgenic_scaffold",
                    "evidence_level": HEURISTIC_NAME_CONF_LEVEL,
                    "affinity_value_nm": None,
                    "signal": round(signal, 4),
                    "name_hits": name_hits[:4],
                }
            )

        evidence_level_counts[HEURISTIC_NAME_CONF_LEVEL] += 1
        mechanism_counts["heuristic_androgenic_name"] += 1
        support_mass = confidence_mass * 0.8
        uncertainty_mass = max(0.0, evidence_weight * (1.0 - evidence_conf))
        return True, support_mass, uncertainty_mass

    def score_compound(self, compound: Compound) -> dict[str, Any]:
        cached = self._compound_cache.get(compound.id)
        if cached is not None:
            return cached

        trait_score_map = {slug: 0.0 for slug in self.traits.keys()}
        trait_weight_map = {slug: 0.0 for slug in self.traits.keys()}
        provenance_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        group_signal_score: dict[str, float] = {slug: 0.0 for slug in GROUPING_PRESETS.keys()}
        group_hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
        evidence_level_counts: dict[str, int] = defaultdict(int)
        mechanism_counts: dict[str, int] = defaultdict(int)
        support_mass = 0.0
        uncertainty_mass = 0.0
        conflict_rows = 0
        target_mechanisms: dict[int, set[str]] = defaultdict(set)
        target_polarities: dict[int, set[int]] = defaultdict(set)
        target_sources: dict[int, set[str]] = defaultdict(set)
        target_names: dict[int, str] = {}
        target_row_count: dict[int, int] = defaultdict(int)
        target_conflict_mass: dict[int, float] = defaultdict(float)
        category_names = {
            _norm_text(name)
            for name in compound.categories.values_list("name", flat=True)
            if _norm_text(name)
        }
        for group_slug, config in GROUPING_PRESETS.items():
            group_categories = {_norm_text(row) for row in (config.get("category_names") or [])}
            if group_categories and category_names.intersection(group_categories):
                group_signal_score[group_slug] += 0.6

        evidence_rows = (
            CompoundTargetInteractionEvidence.objects.filter(compound=compound)
            .exclude(canonical_mechanism="unknown")
            .select_related("target")
            .order_by("id")
        )
        consensus_map = self._compound_consensus_map(compound.id)
        matched_evidence = 0
        route_hits = 0
        route_total = 0

        for evidence in evidence_rows:
            if _confidence_rank(evidence.evidence_level) < self.min_rank:
                continue

            mechanism = evidence.canonical_mechanism
            evidence_level = _norm_text(evidence.evidence_level) or "unknown"
            context_factor = _context_match_factor(evidence, self.desired_context)
            evidence_conf = EVIDENCE_CONF_MULT.get(evidence_level, 0.35)
            evidence_weight = max(0.05, float(evidence.evidence_weight or 0.0))
            consensus = consensus_map.get((evidence.target_id, evidence.context_key))
            consensus_factor = 0.7
            conflict_factor = 1.0
            if consensus:
                consensus_factor = CONSENSUS_CONF_MULT.get(_norm_text(consensus.consensus_confidence), 0.6)
                if consensus.has_conflict:
                    conflict_factor = 0.85
                    conflict_rows += 1

            quality_mass = evidence_weight * evidence_conf * context_factor * consensus_factor
            support_mass += quality_mass * conflict_factor
            uncertainty_mass += max(0.0, evidence_weight * (1.0 - evidence_conf) * context_factor)
            uncertainty_mass += (1.0 - conflict_factor) * quality_mass
            evidence_level_counts[evidence_level] += 1
            mechanism_counts[mechanism] += 1
            target_row_count[evidence.target_id] += 1
            target_name = getattr(evidence.target, "name", "")
            target_names[evidence.target_id] = target_name
            target_mechanisms[evidence.target_id].add(mechanism)
            if evidence.source:
                target_sources[evidence.target_id].add(evidence.source)
            polarity = _mechanism_polarity(mechanism)
            if polarity != 0:
                target_polarities[evidence.target_id].add(polarity)
            if consensus and consensus.has_conflict:
                target_conflict_mass[evidence.target_id] += quality_mass

            rules = self.rules_by_mechanism.get(evidence.canonical_mechanism, [])
            if not rules:
                continue
            matched_evidence += 1
            if self.desired_context.get("route"):
                route_total += 1
                if _norm_text(evidence.route) == _norm_text(self.desired_context.get("route")):
                    route_hits += 1

            for rule in rules:
                if not self._rule_matches(rule, evidence):
                    continue
                trait_spec = self.traits.get(rule.trait_slug)
                if trait_spec is None:
                    continue

                contribution = (
                    float(rule.delta)
                    * evidence_weight
                    * evidence_conf
                    * consensus_factor
                    * conflict_factor
                    * context_factor
                    * max(0.0, min(1.0, float(rule.base_confidence)))
                )
                if contribution == 0:
                    continue

                trait_score_map[rule.trait_slug] += contribution
                trait_weight_map[rule.trait_slug] += abs(
                    evidence_weight * evidence_conf * consensus_factor * max(0.2, float(rule.base_confidence))
                )
                provenance_map[rule.trait_slug].append(
                    {
                        "target": getattr(evidence.target, "name", ""),
                        "mechanism": evidence.canonical_mechanism,
                        "source": evidence.source,
                        "evidence_level": evidence.evidence_level,
                        "evidence_weight": round(evidence_weight, 3),
                        "context_key": evidence.context_key,
                        "context_match_factor": round(context_factor, 3),
                        "contribution": round(contribution, 4),
                        "rule_id": rule.rule_id,
                        "rule_priority": rule.priority,
                        "rule_source": rule.source,
                    }
                )

            for group_slug, config in GROUPING_PRESETS.items():
                if not _evidence_matches_grouping(evidence, config):
                    continue
                affinity_mult = _affinity_signal_multiplier(
                    float(evidence.affinity_value_nm) if evidence.affinity_value_nm is not None else None,
                    float(config.get("good_affinity_nm")) if config.get("good_affinity_nm") else None,
                )
                signal = max(0.05, evidence_weight * evidence_conf * context_factor * affinity_mult)
                group_signal_score[group_slug] += signal
                group_hits[group_slug].append(
                    {
                        "target": getattr(evidence.target, "name", ""),
                        "mechanism": evidence.canonical_mechanism,
                        "source": evidence.source,
                        "evidence_level": evidence.evidence_level,
                        "affinity_value_nm": evidence.affinity_value_nm,
                        "signal": round(signal, 4),
                    }
                )

        if matched_evidence <= 0:
            legacy_rows, legacy_support_mass, legacy_uncertainty_mass = self._apply_legacy_interaction_fallback(
                compound=compound,
                trait_score_map=trait_score_map,
                trait_weight_map=trait_weight_map,
                provenance_map=provenance_map,
                group_signal_score=group_signal_score,
                group_hits=group_hits,
                evidence_level_counts=evidence_level_counts,
                mechanism_counts=mechanism_counts,
                target_mechanisms=target_mechanisms,
                target_polarities=target_polarities,
                target_sources=target_sources,
                target_names=target_names,
                target_row_count=target_row_count,
            )
            matched_evidence += legacy_rows
            support_mass += legacy_support_mass
            uncertainty_mass += legacy_uncertainty_mass

        if matched_evidence <= 0:
            heuristic_applied, heuristic_support_mass, heuristic_uncertainty_mass = self._apply_androgenic_name_heuristic(
                compound=compound,
                trait_score_map=trait_score_map,
                trait_weight_map=trait_weight_map,
                provenance_map=provenance_map,
                group_signal_score=group_signal_score,
                group_hits=group_hits,
                evidence_level_counts=evidence_level_counts,
                mechanism_counts=mechanism_counts,
            )
            if heuristic_applied:
                matched_evidence += 1
                support_mass += heuristic_support_mass
                uncertainty_mass += heuristic_uncertainty_mass

        traits = []
        trait_map: dict[str, dict[str, Any]] = {}
        non_zero_conf = []
        for slug, spec in sorted(self.traits.items(), key=lambda item: item[1].display_order):
            bounded_score = _clip(trait_score_map.get(slug, 0.0), spec.min_score, spec.max_score)
            confidence = _clip(trait_weight_map.get(slug, 0.0) / 3.0, 0.0, 1.0)
            if confidence > 0:
                non_zero_conf.append(confidence)
            entry = _trait_entry(spec, bounded_score, confidence)
            top_contribs = sorted(
                provenance_map.get(slug, []),
                key=lambda row: abs(float(row.get("contribution") or 0.0)),
                reverse=True,
            )[:5]
            if top_contribs:
                entry["top_contributions"] = top_contribs
            traits.append(entry)
            trait_map[slug] = entry

        overall_conf = float(sum(non_zero_conf) / len(non_zero_conf)) if non_zero_conf else 0.0
        route_support = float(route_hits / route_total) if route_total else None
        group_signals = []
        for group_slug, score in group_signal_score.items():
            if score <= 0:
                continue
            config = GROUPING_PRESETS[group_slug]
            hits = sorted(
                group_hits.get(group_slug, []),
                key=lambda row: abs(float(row.get("signal") or 0.0)),
                reverse=True,
            )[:4]
            group_signals.append(
                {
                    "slug": group_slug,
                    "label": config["label"],
                    "trait_slug": config.get("trait_slug", ""),
                    "score": round(float(score), 3),
                    "hit_count": len(group_hits.get(group_slug, [])),
                    "top_hits": hits,
                    "category_names": list(config.get("category_names") or []),
                }
            )
        group_signals.sort(key=lambda row: row["score"], reverse=True)

        contradiction_rows = []
        for target_id, polarities in target_polarities.items():
            if len(polarities) < 2:
                continue
            row_count = int(target_row_count.get(target_id) or 0)
            conflict_mass = float(target_conflict_mass.get(target_id) or 0.0)
            contradiction_rows.append(
                {
                    "target_id": target_id,
                    "target": target_names.get(target_id, ""),
                    "row_count": row_count,
                    "mechanisms": sorted(target_mechanisms.get(target_id) or []),
                    "sources": sorted(target_sources.get(target_id) or [])[:5],
                    "has_consensus_conflict": bool(conflict_mass > 0),
                    "conflict_score": round(conflict_mass + (0.45 * row_count), 3),
                }
            )
        contradiction_rows.sort(key=lambda row: row["conflict_score"], reverse=True)

        rows_scored = int(sum(evidence_level_counts.values()))
        target_count = int(len(target_row_count))
        conflict_ratio = float(conflict_rows / max(1, rows_scored))
        contradiction_targets = int(len(contradiction_rows))
        contradiction_ratio = float(contradiction_targets / max(1, target_count))
        contradiction_index = _clip((0.6 * conflict_ratio) + (0.4 * contradiction_ratio), 0.0, 1.0)
        posterior_confidence = _bayesian_confidence(
            support_mass=support_mass,
            uncertainty_mass=uncertainty_mass + (0.35 * conflict_rows),
        )
        evidence_profile = {
            "rows_scored": rows_scored,
            "target_count": target_count,
            "support_mass": round(float(support_mass), 3),
            "uncertainty_mass": round(float(uncertainty_mass), 3),
            "posterior_confidence": round(float(posterior_confidence), 3),
            "bayes_band": _confidence_band(posterior_confidence),
            "conflict_rows": int(conflict_rows),
            "conflict_ratio": round(float(conflict_ratio), 3),
            "contradiction_targets": contradiction_targets,
            "contradiction_ratio": round(float(contradiction_ratio), 3),
            "contradiction_index": round(float(contradiction_index), 3),
            "evidence_level_breakdown": dict(sorted(evidence_level_counts.items())),
            "mechanism_breakdown": dict(sorted(mechanism_counts.items())),
        }
        contradiction_radar = {
            "target_count": contradiction_targets,
            "rows": contradiction_rows[:8],
        }

        result = {
            "compound_id": compound.id,
            "compound_name": compound.name,
            "compound_slug": compound.slug,
            "overall_confidence": round(overall_conf, 3),
            "matched_evidence_rows": matched_evidence,
            "route_support": round(route_support, 3) if route_support is not None else None,
            "traits": traits,
            "trait_map": trait_map,
            "group_signals": group_signals,
            "group_signal_map": {row["slug"]: row for row in group_signals},
            "provenance": {slug: rows[:12] for slug, rows in provenance_map.items()},
            "evidence_profile": evidence_profile,
            "contradiction_radar": contradiction_radar,
        }
        self._compound_cache[compound.id] = result
        return result

    def aggregate_stack_traits(self, sheets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        aggregate: dict[str, dict[str, Any]] = {}
        for slug, spec in self.traits.items():
            raw_total = 0.0
            conf_total = 0.0
            contributors = []
            for sheet in sheets:
                entry = (sheet.get("trait_map") or {}).get(slug)
                if not entry:
                    continue
                score = float(entry.get("score") or 0.0)
                confidence = float(entry.get("confidence") or 0.0)
                weighted = score * (0.5 + 0.5 * confidence)
                raw_total += weighted
                conf_total += confidence
                if score != 0:
                    contributors.append(
                        {
                            "compound_id": sheet["compound_id"],
                            "compound_name": sheet["compound_name"],
                            "score": round(score, 3),
                            "confidence": round(confidence, 3),
                        }
                    )
            bounded = _clip(raw_total, spec.min_score, spec.max_score)
            avg_conf = _clip(conf_total / max(1, len(sheets)), 0.0, 1.0)
            aggregate[slug] = {
                **_trait_entry(spec, bounded, avg_conf),
                "contributors": sorted(contributors, key=lambda row: abs(row["score"]), reverse=True)[:6],
            }
        return aggregate


def _build_max_trait_constraints(constraints: dict[str, Any] | None) -> dict[str, float]:
    data = constraints or {}
    max_traits = dict(data.get("max_traits") or {})
    legacy_map = {
        "max_cardio_risk": "cardio_risk",
        "max_cancer_risk": "cancer_risk",
        "max_dependence_risk": "dependence_risk",
        "max_sedation_risk": "sedation_risk",
    }
    for key, trait_slug in legacy_map.items():
        if key in data and trait_slug not in max_traits:
            max_traits[trait_slug] = data[key]

    out = {}
    for slug, value in max_traits.items():
        try:
            out[str(slug)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _load_candidate_compounds(
    *,
    goals: dict[str, float],
    rules_by_mechanism: dict[str, list[RuleSpec]],
    explicit_ids: list[int] | None,
    focus_groups: list[str] | None,
    limit: int,
) -> list[Compound]:
    if explicit_ids:
        return list(Compound.objects.filter(id__in=explicit_ids).order_by("name"))

    goal_traits = {slug for slug, weight in goals.items() if weight != 0}
    goal_mechanisms = set()
    if goal_traits:
        for mechanism, rules in rules_by_mechanism.items():
            for rule in rules:
                if rule.trait_slug in goal_traits:
                    goal_mechanisms.add(mechanism)
                    break

    evidence_qs = CompoundTargetInteractionEvidence.objects.exclude(canonical_mechanism="unknown")
    if goal_mechanisms:
        evidence_qs = evidence_qs.filter(canonical_mechanism__in=goal_mechanisms)
    normalized_focus_groups = [slug for slug in (focus_groups or []) if slug in GROUPING_PRESETS]
    category_matched_ids: list[int] = []
    if normalized_focus_groups:
        focus_mechanisms = set()
        keyword_filters = Q()
        focus_category_names = set()
        for slug in normalized_focus_groups:
            config = GROUPING_PRESETS[slug]
            focus_mechanisms.update(config.get("mechanisms") or [])
            for keyword in config.get("target_keywords") or []:
                keyword_filters |= Q(target__name__icontains=keyword)
            for category_name in config.get("category_names") or []:
                cleaned = (category_name or "").strip()
                if cleaned:
                    focus_category_names.add(cleaned)
        if focus_mechanisms:
            evidence_qs = evidence_qs.filter(canonical_mechanism__in=focus_mechanisms)
        if keyword_filters:
            evidence_qs = evidence_qs.filter(keyword_filters)
        if focus_category_names:
            category_matched_ids = list(
                Compound.objects.filter(categories__name__in=focus_category_names)
                .distinct()
                .values_list("id", flat=True)[:limit]
            )

    ids = list(
        evidence_qs.values("compound_id")
        .annotate(evidence_count=Count("id"))
        .order_by("-evidence_count")
        .values_list("compound_id", flat=True)[:limit]
    )
    if not ids:
        ids = list(
            CompoundTargetInteractionEvidence.objects.exclude(canonical_mechanism="unknown")
            .values("compound_id")
            .annotate(evidence_count=Count("id"))
            .order_by("-evidence_count")
            .values_list("compound_id", flat=True)[:limit]
        )
    if category_matched_ids:
        merged_ids = list(ids)
        seen = set(merged_ids)
        for compound_id in category_matched_ids:
            if compound_id in seen:
                continue
            merged_ids.append(compound_id)
            seen.add(compound_id)
            if len(merged_ids) >= limit:
                break
        ids = merged_ids

    order_map = {compound_id: idx for idx, compound_id in enumerate(ids)}
    compounds = list(Compound.objects.filter(id__in=ids))
    compounds.sort(key=lambda row: order_map.get(row.id, 10**9))
    return compounds


def _pair_tuple(a_id: int, b_id: int) -> tuple[int, int]:
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def _pair_safety_and_penalty(
    *,
    compound_ids: list[int],
    constraints: dict[str, Any],
) -> dict[str, Any]:
    if len(compound_ids) < 2:
        return {"blocked": False, "hard_blocks": [], "penalty": 0.0, "warnings": []}

    no_cyp3a4_conflicts = bool(constraints.get("no_cyp3a4_conflicts", False))
    pairs = {_pair_tuple(a_id, b_id) for a_id, b_id in combinations(compound_ids, 2)}

    try:
        curated_rows = StackDangerousPairRule.objects.filter(
            is_active=True,
            compound_a_id__in=compound_ids,
            compound_b_id__in=compound_ids,
        ).select_related("compound_a", "compound_b")
    except (OperationalError, ProgrammingError):
        curated_rows = []
    curated_map = {(_pair_tuple(row.compound_a_id, row.compound_b_id)): row for row in curated_rows}

    interaction_rows = (
        CompoundToCompoundTargetInteraction.objects.filter(
            compound_a_id__in=compound_ids,
            compound_b_id__in=compound_ids,
        )
        .select_related("target", "compound_a", "compound_b")
        .order_by("id")
    )

    blocked = []
    warnings = []
    penalty = 0.0

    for pair in pairs:
        curated = curated_map.get(pair)
        if curated:
            blocked.append(
                {
                    "pair": [curated.compound_a_id, curated.compound_b_id],
                    "reason": curated.reason,
                    "severity": curated.severity,
                    "source": curated.source or "curated_rule",
                }
            )

    for row in interaction_rows:
        pair = _pair_tuple(row.compound_a_id, row.compound_b_id)
        if pair not in pairs:
            continue
        confidence_mult = PAIR_CONF_MULT.get(_norm_text(row.confidence), 0.7)
        type_penalty = PAIR_PENALTY_BY_TYPE.get(row.interaction_type, PAIR_PENALTY_BY_TYPE["unknown"])
        penalty += float(type_penalty) * confidence_mult
        if row.interaction_type in HARD_BLOCK_INTERACTION_TYPES and _norm_text(row.confidence) == "high":
            blocked.append(
                {
                    "pair": [pair[0], pair[1]],
                    "reason": (
                        f"High-confidence {row.interaction_type} via {row.target.name} "
                        "was treated as a hard safety block."
                    ),
                    "severity": "high",
                    "source": "compound_pair_interaction",
                }
            )
        if no_cyp3a4_conflicts and "cyp3a4" in _norm_text(row.target.name):
            if row.interaction_type in {"enzyme_inhibition", "competitive_metabolism", "enzyme_induction"}:
                blocked.append(
                    {
                        "pair": [pair[0], pair[1]],
                        "reason": f"CYP3A4 conflict ({row.interaction_type})",
                        "severity": "high",
                        "source": "constraint.no_cyp3a4_conflicts",
                    }
                )
        if row.interaction_type in {"antagonistic", "competitive", "receptor_competition"}:
            warnings.append(
                {
                    "pair": [pair[0], pair[1]],
                    "interaction_type": row.interaction_type,
                    "target": row.target.name,
                    "confidence": row.confidence,
                }
            )

    return {
        "blocked": bool(blocked),
        "hard_blocks": blocked,
        "penalty": round(float(max(0.0, penalty)), 4),
        "warnings": warnings[:20],
    }


def _aggregate_stack_evidence(sheets: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    total_rows = 0
    total_targets = 0
    total_support_mass = 0.0
    total_uncertainty_mass = 0.0
    total_conflict_rows = 0
    posterior_values: list[float] = []
    contradiction_target_rows: dict[str, dict[str, Any]] = {}

    for sheet in sheets:
        profile = sheet.get("evidence_profile") or {}
        total_rows += int(profile.get("rows_scored") or 0)
        total_targets += int(profile.get("target_count") or 0)
        total_support_mass += float(profile.get("support_mass") or 0.0)
        total_uncertainty_mass += float(profile.get("uncertainty_mass") or 0.0)
        total_conflict_rows += int(profile.get("conflict_rows") or 0)
        posterior = profile.get("posterior_confidence")
        if posterior is not None:
            try:
                posterior_values.append(float(posterior))
            except (TypeError, ValueError):
                pass

        for radar_row in (sheet.get("contradiction_radar") or {}).get("rows") or []:
            target_id = radar_row.get("target_id")
            target_label = str(radar_row.get("target") or "")
            target_key = str(target_id) if target_id is not None else target_label
            if not target_key:
                continue
            existing = contradiction_target_rows.get(target_key)
            if not existing:
                contradiction_target_rows[target_key] = {
                    "target_id": target_id,
                    "target": target_label,
                    "row_count": int(radar_row.get("row_count") or 0),
                    "mechanisms": set(radar_row.get("mechanisms") or []),
                    "sources": set(radar_row.get("sources") or []),
                    "compound_names": {sheet.get("compound_name") or ""},
                    "conflict_score": float(radar_row.get("conflict_score") or 0.0),
                }
                continue
            existing["row_count"] += int(radar_row.get("row_count") or 0)
            existing["mechanisms"].update(radar_row.get("mechanisms") or [])
            existing["sources"].update(radar_row.get("sources") or [])
            existing["compound_names"].add(sheet.get("compound_name") or "")
            existing["conflict_score"] += float(radar_row.get("conflict_score") or 0.0)

    contradiction_rows = []
    for row in contradiction_target_rows.values():
        contradiction_rows.append(
            {
                "target_id": row.get("target_id"),
                "target": row.get("target") or "",
                "row_count": int(row.get("row_count") or 0),
                "mechanisms": sorted([m for m in row.get("mechanisms", set()) if m]),
                "sources": sorted([s for s in row.get("sources", set()) if s])[:6],
                "compound_names": sorted([c for c in row.get("compound_names", set()) if c])[:6],
                "conflict_score": round(float(row.get("conflict_score") or 0.0), 3),
            }
        )
    contradiction_rows.sort(key=lambda row: row["conflict_score"], reverse=True)

    conflict_ratio = float(total_conflict_rows / max(1, total_rows))
    contradiction_targets = len(contradiction_rows)
    contradiction_ratio = float(contradiction_targets / max(1, total_targets))
    contradiction_index = _clip((0.6 * conflict_ratio) + (0.4 * contradiction_ratio), 0.0, 1.0)
    posterior_confidence = _bayesian_confidence(
        support_mass=total_support_mass,
        uncertainty_mass=total_uncertainty_mass + (0.35 * total_conflict_rows),
    )
    avg_posterior = float(sum(posterior_values) / max(1, len(posterior_values))) if posterior_values else 0.0

    evidence_profile = {
        "rows_scored": int(total_rows),
        "target_count": int(total_targets),
        "support_mass": round(float(total_support_mass), 3),
        "uncertainty_mass": round(float(total_uncertainty_mass), 3),
        "posterior_confidence": round(float(posterior_confidence), 3),
        "avg_compound_posterior": round(float(avg_posterior), 3),
        "bayes_band": _confidence_band(posterior_confidence),
        "conflict_rows": int(total_conflict_rows),
        "conflict_ratio": round(float(conflict_ratio), 3),
        "contradiction_targets": int(contradiction_targets),
        "contradiction_ratio": round(float(contradiction_ratio), 3),
        "contradiction_index": round(float(contradiction_index), 3),
    }
    contradiction_radar = {
        "target_count": int(contradiction_targets),
        "rows": contradiction_rows[:10],
    }
    return evidence_profile, contradiction_radar


def _evaluate_stack_state(
    *,
    compound_ids: list[int],
    goals: dict[str, float],
    constraints: dict[str, Any],
    trait_engine: TraitEngine,
    compound_sheets: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    sheets = [compound_sheets[cid] for cid in compound_ids]
    stack_traits = trait_engine.aggregate_stack_traits(sheets)
    goal_score = 0.0
    for goal_slug, weight in goals.items():
        entry = stack_traits.get(goal_slug)
        if not entry:
            continue
        goal_score += float(weight) * (float(entry["score"]) / 5.0)

    max_traits = _build_max_trait_constraints(constraints)
    risk_penalty = 0.0
    risk_overflows = []
    for trait_slug, max_allowed in max_traits.items():
        entry = stack_traits.get(trait_slug)
        if not entry:
            continue
        score = float(entry["score"])
        if score > max_allowed:
            overflow = score - max_allowed
            penalty = overflow * 2.5
            risk_penalty += penalty
            risk_overflows.append(
                {
                    "trait": trait_slug,
                    "score": round(score, 3),
                    "max_allowed": round(max_allowed, 3),
                    "overflow": round(overflow, 3),
                    "penalty": round(penalty, 3),
                }
            )

    route_penalty = 0.0
    required_route = _norm_text(constraints.get("required_route"))
    if required_route:
        for sheet in sheets:
            route_support = sheet.get("route_support")
            if route_support is None:
                route_penalty += 0.2
            elif float(route_support) < 0.5:
                route_penalty += (0.5 - float(route_support)) * 1.2

    pair_eval = _pair_safety_and_penalty(compound_ids=compound_ids, constraints=constraints)
    evidence_profile, contradiction_radar = _aggregate_stack_evidence(sheets)
    total_score = goal_score - risk_penalty - route_penalty - float(pair_eval["penalty"])

    sorted_traits = sorted(
        stack_traits.values(),
        key=lambda row: float(row.get("score") or 0.0),
        reverse=True,
    )
    perks = [row for row in sorted_traits if float(row["score"]) > 0.35][:5]
    flaws = [row for row in reversed(sorted_traits) if float(row["score"]) < -0.35][:5]
    risks = [
        row
        for row in sorted_traits
        if row["trait_type"] == "risk" and float(row["score"]) > 0.35
    ][:5]

    return {
        "compound_ids": compound_ids,
        "blocked": bool(pair_eval["blocked"]),
        "hard_blocks": pair_eval["hard_blocks"],
        "warnings": pair_eval["warnings"],
        "goal_score": round(goal_score, 4),
        "risk_penalty": round(risk_penalty, 4),
        "route_penalty": round(route_penalty, 4),
        "interaction_penalty": round(float(pair_eval["penalty"]), 4),
        "total_score": round(float(total_score), 4),
        "risk_overflows": risk_overflows,
        "traits": list(stack_traits.values()),
        "perks": perks,
        "flaws": flaws,
        "active_risks": risks,
        "evidence_profile": evidence_profile,
        "contradiction_radar": contradiction_radar,
    }


def _build_compound_distribution(
    *,
    candidate_ids: list[int],
    base_compound_ids: list[int],
    goals: dict[str, float],
    constraints: dict[str, Any],
    focus_groups: list[str],
    trait_engine: TraitEngine,
    compound_sheets: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    points = []
    for compound_id in candidate_ids:
        sheet = compound_sheets.get(compound_id)
        if not sheet:
            continue
        evaluation = _evaluate_stack_state(
            compound_ids=sorted({*base_compound_ids, compound_id}),
            goals=goals,
            constraints=constraints,
            trait_engine=trait_engine,
            compound_sheets=compound_sheets,
        )
        if evaluation["blocked"]:
            continue
        signal_map = sheet.get("group_signal_map") or {}
        max_focus_signal = max(
            [float((signal_map.get(group_slug) or {}).get("score") or 0.0) for group_slug in focus_groups] or [0.0]
        )
        risk_load = (
            float(evaluation["risk_penalty"])
            + float(evaluation["interaction_penalty"])
            + float(evaluation["route_penalty"])
        )
        point = {
            "compound_id": compound_id,
            "compound_name": sheet["compound_name"],
            "compound_slug": sheet["compound_slug"],
            "goal_score": round(float(evaluation["goal_score"]), 4),
            "risk_load": round(float(risk_load), 4),
            "net_score": round(float(evaluation["total_score"]), 4),
            "overall_confidence": round(float(sheet.get("overall_confidence") or 0.0), 3),
            "posterior_confidence": (sheet.get("evidence_profile") or {}).get("posterior_confidence"),
            "contradiction_index": (sheet.get("evidence_profile") or {}).get("contradiction_index"),
            "focus_signal": round(float(max_focus_signal), 3),
            "group_tags": [row.get("slug") for row in (sheet.get("group_signals") or [])[:3]],
        }
        if point["net_score"] >= 0.5:
            point["score_band"] = "strong"
        elif point["net_score"] >= 0.0:
            point["score_band"] = "moderate"
        else:
            point["score_band"] = "weak"
        points.append(point)

    points.sort(key=lambda row: row["net_score"], reverse=True)
    return {
        "mode": "compound_cloud",
        "x_axis": "goal_score",
        "y_axis": "risk_load",
        "point_count": len(points),
        "points": points,
    }


def recommend_stack_builds(
    *,
    goals: dict[str, Any] | None,
    constraints: dict[str, Any] | None = None,
    candidate_compound_ids: list[int] | None = None,
    base_compound_ids: list[int] | None = None,
    max_stack_size: int = 4,
    beam_width: int = 12,
    top_k: int = 5,
    min_evidence_confidence: str = "medium",
    desired_context: dict[str, str] | None = None,
    candidate_limit: int = 220,
    output_mode: str = "ranked",
    include_distribution: bool | None = None,
) -> dict[str, Any]:
    normalized_goals = _normalize_goals(goals)
    constraints = dict(constraints or {})
    output_mode = _norm_text(output_mode) or "ranked"
    if output_mode not in {"ranked", "hybrid", "cloud"}:
        raise ValueError("output_mode must be one of: ranked, hybrid, cloud.")
    if include_distribution is None:
        include_distribution = output_mode in {"hybrid", "cloud"}
    else:
        include_distribution = bool(include_distribution)
    focus_groups = parse_focus_groups(constraints.get("focus_groups"))
    min_group_score = constraints.get("min_group_score")
    try:
        min_group_score = float(min_group_score) if min_group_score is not None else 0.0
    except (TypeError, ValueError):
        min_group_score = 0.0
    min_group_score = max(0.0, min(float(min_group_score), 10.0))
    base_compound_ids = sorted({int(compound_id) for compound_id in (base_compound_ids or [])})
    trait_engine = TraitEngine(
        desired_context=desired_context,
        min_evidence_confidence=min_evidence_confidence,
    )

    compounds = _load_candidate_compounds(
        goals=normalized_goals,
        rules_by_mechanism=trait_engine.rules_by_mechanism,
        explicit_ids=candidate_compound_ids,
        focus_groups=focus_groups,
        limit=max(20, int(candidate_limit)),
    )

    excluded_ids = {int(v) for v in (constraints.get("exclude_compound_ids") or []) if str(v).isdigit()}
    excluded_ids.update(base_compound_ids)
    confidence_floor = EVIDENCE_CONF_MULT.get(_norm_text(min_evidence_confidence), 0.5)

    compound_sheets: dict[int, dict[str, Any]] = {}
    candidate_sheet_count = 0
    candidate_only_ids: list[int] = []
    if base_compound_ids:
        base_compounds = list(Compound.objects.filter(id__in=base_compound_ids).order_by("name"))
        for compound in base_compounds:
            compound_sheets[compound.id] = trait_engine.score_compound(compound)
    for compound in compounds:
        if compound.id in excluded_ids:
            continue
        sheet = trait_engine.score_compound(compound)
        matched_rows = int(sheet.get("matched_evidence_rows") or 0)
        allow_label_only = False
        max_focus_signal = 0.0
        if focus_groups:
            signal_map = sheet.get("group_signal_map") or {}
            max_focus_signal = max(
                [float((signal_map.get(group_slug) or {}).get("score") or 0.0) for group_slug in focus_groups] or [0.0]
            )
            if max_focus_signal < min_group_score:
                continue
            if matched_rows <= 0:
                allow_label_only = True
        elif matched_rows <= 0:
            continue
        effective_floor = max(0.2, confidence_floor * 0.35)
        if not allow_label_only and float(sheet["overall_confidence"]) + 0.05 < effective_floor:
            continue
        compound_sheets[compound.id] = sheet
        candidate_sheet_count += 1
        candidate_only_ids.append(compound.id)

    if candidate_sheet_count <= 0:
        base_compounds = list(Compound.objects.filter(id__in=base_compound_ids).order_by("name"))
        base_sheets = {compound.id: trait_engine.score_compound(compound) for compound in base_compounds}
        baseline = None
        if base_compounds:
            baseline_eval = _evaluate_stack_state(
                compound_ids=[compound.id for compound in base_compounds],
                goals=normalized_goals,
                constraints=constraints,
                trait_engine=trait_engine,
                compound_sheets=base_sheets,
            )
            baseline = {
                "compound_ids": [compound.id for compound in base_compounds],
                "compounds": [
                    {
                        "id": compound.id,
                        "name": compound.name,
                        "slug": compound.slug,
                        "overall_confidence": base_sheets[compound.id]["overall_confidence"],
                    }
                    for compound in base_compounds
                ],
                "score": baseline_eval["total_score"],
                "character_sheet": {
                    "traits": baseline_eval["traits"],
                    "perks": baseline_eval["perks"],
                    "flaws": baseline_eval["flaws"],
                    "active_risks": baseline_eval["active_risks"],
                    "evidence_profile": baseline_eval["evidence_profile"],
                    "contradiction_radar": baseline_eval["contradiction_radar"],
                },
                "evidence_profile": baseline_eval["evidence_profile"],
                "contradiction_radar": baseline_eval["contradiction_radar"],
            }
        return {
            "disclaimer": DISCLAIMER,
            "recommendations": [],
            "baseline": baseline,
            "distribution": {
                "mode": "compound_cloud",
                "x_axis": "goal_score",
                "y_axis": "risk_load",
                "point_count": 0,
                "points": [],
            } if include_distribution else None,
            "meta": {
                "candidate_count": 0,
                "base_compound_count": len(base_compound_ids),
                "goal_traits": list(normalized_goals.keys()),
                "focus_groups": focus_groups,
                "min_group_score": min_group_score,
                "output_mode": output_mode,
                "distribution_included": bool(include_distribution),
                "reason": "No candidate compounds met the confidence/group thresholds.",
            },
        }

    max_stack_size = max(1, min(int(max_stack_size), 8))
    beam_width = max(2, min(int(beam_width), 64))
    top_k = max(1, min(int(top_k), 20))

    candidate_ids = list(candidate_only_ids)
    pre_scored = []
    for compound_id in candidate_ids:
        sheet = compound_sheets[compound_id]
        score = 0.0
        for goal_slug, weight in normalized_goals.items():
            entry = (sheet.get("trait_map") or {}).get(goal_slug)
            if entry:
                score += float(weight) * (float(entry["score"]) / 5.0)
        pre_scored.append((compound_id, score, float(sheet.get("overall_confidence") or 0.0)))
    pre_scored.sort(key=lambda row: (row[1], row[2]), reverse=True)
    candidate_ids = [row[0] for row in pre_scored]

    states = [tuple()]
    seen_states = {tuple()}
    viable_states: list[tuple[tuple[int, ...], dict[str, Any]]] = []

    for _depth in range(max_stack_size):
        expanded: list[tuple[tuple[int, ...], dict[str, Any]]] = []
        for state in states:
            start_index = 0
            if state:
                try:
                    start_index = candidate_ids.index(state[-1]) + 1
                except ValueError:
                    start_index = 0
            for idx in range(start_index, len(candidate_ids)):
                candidate_id = candidate_ids[idx]
                if candidate_id in state:
                    continue
                new_state = tuple(sorted((*state, candidate_id)))
                if new_state in seen_states:
                    continue
                seen_states.add(new_state)

                full_compound_ids = sorted({*base_compound_ids, *new_state})
                evaluation = _evaluate_stack_state(
                    compound_ids=full_compound_ids,
                    goals=normalized_goals,
                    constraints=constraints,
                    trait_engine=trait_engine,
                    compound_sheets=compound_sheets,
                )
                if evaluation["blocked"]:
                    continue
                expanded.append((new_state, evaluation))
                viable_states.append((new_state, evaluation))

        if not expanded:
            break
        expanded.sort(key=lambda row: row[1]["total_score"], reverse=True)
        states = [row[0] for row in expanded[:beam_width]]

    viable_states.sort(key=lambda row: row[1]["total_score"], reverse=True)
    recommendations = []
    for rank, (state, evaluation) in enumerate(viable_states[:top_k], start=1):
        compounds_payload = []
        full_compounds_payload = []
        full_ids = sorted({*base_compound_ids, *state})
        for compound_id in full_ids:
            if compound_id in state:
                continue
            if compound_id in compound_sheets:
                sheet = compound_sheets[compound_id]
            else:
                compound = Compound.objects.filter(id=compound_id).first()
                if not compound:
                    continue
                sheet = trait_engine.score_compound(compound)
                compound_sheets[compound_id] = sheet
            full_compounds_payload.append(
                {
                    "id": compound_id,
                    "name": sheet["compound_name"],
                    "slug": sheet["compound_slug"],
                    "overall_confidence": sheet["overall_confidence"],
                    "is_base": True,
                    "traits": sheet["traits"],
                    "group_signals": sheet.get("group_signals") or [],
                }
            )
        for compound_id in state:
            sheet = compound_sheets[compound_id]
            row = {
                "id": compound_id,
                "name": sheet["compound_name"],
                "slug": sheet["compound_slug"],
                "overall_confidence": sheet["overall_confidence"],
                "is_base": False,
                "traits": sheet["traits"],
                "group_signals": sheet.get("group_signals") or [],
            }
            compounds_payload.append(row)
            full_compounds_payload.append(
                {
                    **row,
                }
            )
        recommendations.append(
            {
                "rank": rank,
                "score": evaluation["total_score"],
                "goal_score": evaluation["goal_score"],
                "risk_penalty": evaluation["risk_penalty"],
                "interaction_penalty": evaluation["interaction_penalty"],
                "route_penalty": evaluation["route_penalty"],
                "compound_count": len(full_ids),
                "base_compound_count": len(base_compound_ids),
                "added_compound_count": len(state),
                "base_compound_ids": list(base_compound_ids),
                "compound_ids": full_ids,
                "compounds": compounds_payload,
                "full_stack_compounds": full_compounds_payload,
                "character_sheet": {
                    "traits": evaluation["traits"],
                    "perks": evaluation["perks"],
                    "flaws": evaluation["flaws"],
                    "active_risks": evaluation["active_risks"],
                    "evidence_profile": evaluation["evidence_profile"],
                    "contradiction_radar": evaluation["contradiction_radar"],
                },
                "evidence_profile": evaluation["evidence_profile"],
                "contradiction_radar": evaluation["contradiction_radar"],
                "warnings": evaluation["warnings"],
                "risk_overflows": evaluation["risk_overflows"],
            }
        )

    advisories = []
    if constraints.get("budget_limit") is not None:
        advisories.append(
            "budget_limit was accepted but not scored because compound pricing data is not modeled yet."
        )
    if output_mode == "cloud":
        advisories.append("output_mode=cloud still includes ranked combinations for compatibility.")

    distribution = None
    if include_distribution:
        distribution = _build_compound_distribution(
            candidate_ids=candidate_ids,
            base_compound_ids=base_compound_ids,
            goals=normalized_goals,
            constraints=constraints,
            focus_groups=focus_groups,
            trait_engine=trait_engine,
            compound_sheets=compound_sheets,
        )

    return {
        "disclaimer": DISCLAIMER,
        "recommendations": recommendations,
        "distribution": distribution,
        "advisories": advisories,
        "meta": {
            "candidate_count": len(candidate_ids),
            "base_compound_count": len(base_compound_ids),
            "goal_traits": list(normalized_goals.keys()),
            "max_stack_size": max_stack_size,
            "beam_width": beam_width,
            "top_k": top_k,
            "min_evidence_confidence": min_evidence_confidence,
            "output_mode": output_mode,
            "distribution_included": bool(include_distribution),
            "constraints_applied": {
                "max_traits": _build_max_trait_constraints(constraints),
                "no_cyp3a4_conflicts": bool(constraints.get("no_cyp3a4_conflicts", False)),
                "required_route": constraints.get("required_route") or "",
                "budget_limit": constraints.get("budget_limit"),
                "focus_groups": focus_groups,
                "min_group_score": min_group_score,
            },
            "available_focus_groups": grouping_preset_options(),
        },
    }


def analyze_stack_character_sheet(
    *,
    compound_ids: list[int],
    goals: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    min_evidence_confidence: str = "low",
    desired_context: dict[str, str] | None = None,
) -> dict[str, Any]:
    goals = _normalize_goals(goals)
    constraints = dict(constraints or {})
    compounds = list(Compound.objects.filter(id__in=compound_ids).order_by("name"))
    trait_engine = TraitEngine(
        desired_context=desired_context,
        min_evidence_confidence=min_evidence_confidence,
    )
    sheets = {compound.id: trait_engine.score_compound(compound) for compound in compounds}
    evaluation = _evaluate_stack_state(
        compound_ids=[compound.id for compound in compounds],
        goals=goals,
        constraints=constraints,
        trait_engine=trait_engine,
        compound_sheets=sheets,
    )
    payload_compounds = []
    for compound in compounds:
        payload_compounds.append(
            {
                "id": compound.id,
                "name": compound.name,
                "slug": compound.slug,
                "overall_confidence": sheets[compound.id]["overall_confidence"],
                "traits": sheets[compound.id]["traits"],
                "group_signals": sheets[compound.id].get("group_signals") or [],
                "evidence_profile": sheets[compound.id].get("evidence_profile") or {},
                "contradiction_radar": sheets[compound.id].get("contradiction_radar") or {},
            }
        )
    return {
        "disclaimer": DISCLAIMER,
        "compounds": payload_compounds,
        "character_sheet": {
            "traits": evaluation["traits"],
            "perks": evaluation["perks"],
            "flaws": evaluation["flaws"],
            "active_risks": evaluation["active_risks"],
            "evidence_profile": evaluation["evidence_profile"],
            "contradiction_radar": evaluation["contradiction_radar"],
        },
        "score": evaluation["total_score"],
        "goal_score": evaluation["goal_score"],
        "risk_penalty": evaluation["risk_penalty"],
        "interaction_penalty": evaluation["interaction_penalty"],
        "route_penalty": evaluation["route_penalty"],
        "warnings": evaluation["warnings"],
        "hard_blocks": evaluation["hard_blocks"],
        "evidence_profile": evaluation["evidence_profile"],
        "contradiction_radar": evaluation["contradiction_radar"],
    }
