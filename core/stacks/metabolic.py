"""Evidence-aware metabolic interaction screening and PBPK hand-off."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from compounds.models import MetabolicInteractionEvidence


EVIDENCE_PRIORITY = {
    'label_clinical': 5, 'curated_human': 4, 'experimental': 3,
    'consensus': 2, 'predicted': 1,
}
PERPETRATOR_ROLES = {'inhibitor', 'inducer', 'time_dependent_inhibitor'}


def _evidence_dict(row: MetabolicInteractionEvidence) -> dict[str, Any]:
    return {
        'id': row.id, 'compound_id': row.compound_id, 'compound': row.compound.name,
        'enzyme': row.enzyme.upper(), 'role': row.role, 'strength': row.strength,
        'evidence_tier': row.evidence_tier, 'source': row.source,
        'source_url': row.source_url, 'route': row.route,
        'narrow_therapeutic_index': row.narrow_therapeutic_index,
        'ki_nm': row.ki_nm, 'ic50_nm': row.ic50_nm,
        'fraction_metabolized': row.fraction_metabolized,
        'half_life_minutes': row.half_life_minutes,
    }


def assess_metabolic_interaction(items, *, predicted_compounds=None, clinical_profile=None) -> dict[str, Any]:
    """Return categorical evidence tiers; never synthesize exposure or AUC values."""
    items = list(items)
    item_by_compound = {item.compound_id: item for item in items}
    compound_ids = list(item_by_compound)
    rows = list(
        MetabolicInteractionEvidence.objects.filter(
            compound_id__in=compound_ids, superseded_at__isnull=True,
        ).select_related('compound').order_by('-retrieved_at')
    )
    best: dict[tuple[str, int, str], MetabolicInteractionEvidence] = {}
    for row in rows:
        key = (row.enzyme.upper(), row.compound_id, row.role)
        current = best.get(key)
        if current is None or EVIDENCE_PRIORITY.get(row.evidence_tier, 0) > EVIDENCE_PRIORITY.get(current.evidence_tier, 0):
            best[key] = row
    by_enzyme: dict[str, list[MetabolicInteractionEvidence]] = defaultdict(list)
    for row in best.values():
        by_enzyme[row.enzyme.upper()].append(row)

    findings = []
    for enzyme, enzyme_rows in by_enzyme.items():
        role_evidence: dict[int, list[MetabolicInteractionEvidence]] = defaultdict(list)
        for row in enzyme_rows:
            role_evidence[row.compound_id].append(row)
        conflicted_compounds = set()
        for compound_id, compound_rows in role_evidence.items():
            perpetrator_rows = [row for row in compound_rows if row.role in PERPETRATOR_ROLES]
            if len({row.role for row in perpetrator_rows}) > 1:
                top_priority = max(EVIDENCE_PRIORITY.get(row.evidence_tier, 0) for row in perpetrator_rows)
                top_roles = {row.role for row in perpetrator_rows if EVIDENCE_PRIORITY.get(row.evidence_tier, 0) == top_priority}
                if len(top_roles) > 1:
                    conflicted_compounds.add(compound_id)
                    findings.append({
                        'tier': 'unknown', 'enzyme': enzyme, 'mechanism': 'contradictory_roles',
                        'compound_id': compound_id, 'confidence': 'low', 'completeness': 0.0,
                        'missing_parameters': ['resolved_mechanism_context'],
                        'rationale': 'Equal-priority evidence assigns contradictory perpetrator roles.',
                        'sources': sorted({row.source for row in perpetrator_rows}), 'auc_ratio': None,
                    })
        substrates = [row for row in enzyme_rows if row.role == 'substrate']
        perpetrators = [
            row for row in enzyme_rows
            if row.role in PERPETRATOR_ROLES and row.compound_id not in conflicted_compounds
        ]
        for perpetrator in perpetrators:
            for substrate in substrates:
                if perpetrator.compound_id == substrate.compound_id:
                    continue
                documented = min(
                    EVIDENCE_PRIORITY.get(perpetrator.evidence_tier, 0),
                    EVIDENCE_PRIORITY.get(substrate.evidence_tier, 0),
                ) >= EVIDENCE_PRIORITY['curated_human']
                severe_pair = (
                    perpetrator.strength == 'strong'
                    and (substrate.strength == 'sensitive' or substrate.narrow_therapeutic_index)
                )
                tier = 'high' if documented and severe_pair else 'moderate'
                if perpetrator.route and substrate.route and perpetrator.route != substrate.route:
                    tier = 'moderate'
                missing = []
                if perpetrator.ki_nm is None and perpetrator.ic50_nm is None:
                    missing.append('perpetrator_ki_or_ic50')
                if substrate.fraction_metabolized is None:
                    missing.append('substrate_fraction_metabolized')
                if perpetrator.half_life_minutes is None:
                    missing.append('perpetrator_half_life')
                for row in (perpetrator, substrate):
                    item = item_by_compound[row.compound_id]
                    if item.dosage_amount is None:
                        missing.append(f'compound_{row.compound_id}_dose')
                    if not row.route:
                        missing.append(f'compound_{row.compound_id}_route')
                completeness = max(0.0, 1.0 - (len(set(missing)) / 7.0))
                findings.append({
                    'tier': tier, 'enzyme': enzyme,
                    'mechanism': f'{perpetrator.role}_to_substrate',
                    'perpetrator': _evidence_dict(perpetrator),
                    'victim': _evidence_dict(substrate),
                    'confidence': 'high' if documented else 'medium',
                    'completeness': round(completeness, 3),
                    'missing_parameters': sorted(set(missing)),
                    'rationale': (
                        f'{perpetrator.compound.name} is classified as a {perpetrator.strength} '
                        f'{perpetrator.role} and {substrate.compound.name} as a '
                        f'{substrate.strength} substrate of {enzyme}.'
                    ),
                    'auc_ratio': None,
                    'sources': sorted({perpetrator.source, substrate.source}),
                })

    # Prediction overlap is retained only as an explicitly non-clinical hypothesis.
    predicted_compounds = predicted_compounds or []
    predicted_by_enzyme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for compound in predicted_compounds:
        for enzyme, probability in (compound.get('cyp_endpoints') or {}).items():
            if isinstance(probability, (int, float)) and probability >= 0.5:
                predicted_by_enzyme[enzyme.upper()].append({
                    'compound_id': compound.get('compound_id'), 'name': compound.get('name'),
                    'probability': probability,
                })
    documented_enzymes = {finding['enzyme'] for finding in findings}
    for enzyme, contributors in predicted_by_enzyme.items():
        if len(contributors) >= 2 and enzyme not in documented_enzymes:
            findings.append({
                'tier': 'hypothesis', 'enzyme': enzyme, 'mechanism': 'prediction_overlap',
                'contributors': contributors, 'confidence': 'low', 'completeness': 0.0,
                'missing_parameters': ['roles', 'clinical_evidence', 'exposure_parameters'],
                'rationale': 'Multiple predictions share this endpoint; roles and clinical relevance are unknown.',
                'auc_ratio': None,
            })

    rank = {'high': 4, 'moderate': 3, 'hypothesis': 2, 'unknown': 1}
    findings.sort(key=lambda row: (-rank[row['tier']], -row['completeness'], row['enzyme']))
    tier = findings[0]['tier'] if findings else 'unknown'
    profile_context = _patient_context(clinical_profile)
    return {
        'model_version': 'metabolic-interaction-v4', 'tier': tier,
        'finding_count': len(findings), 'findings': findings,
        'patient_context': profile_context,
        'disclaimer': 'Research screening only; not a clinical interaction, exposure, or dosing determination.',
    }


def _patient_context(profile) -> dict[str, Any]:
    if profile is None or profile.verified_at is None:
        return {'applied': False, 'reason': 'No verified clinical profile.'}
    modifiers = []
    if profile.egfr is not None:
        modifiers.append({'factor': 'egfr', 'value': float(profile.egfr), 'applied_to_score': False})
    if profile.child_pugh_class:
        modifiers.append({'factor': 'child_pugh', 'value': profile.child_pugh_class, 'applied_to_score': False})
    if profile.smoking_status:
        modifiers.append({'factor': 'smoking', 'value': profile.smoking_status, 'applied_to_score': False})
    return {'applied': bool(modifiers), 'profile_revision': profile.revision, 'modifiers': modifiers,
            'note': 'Context is reported but not numerically applied without a traceable compound-specific rule.'}


def build_pbpk_export(stack, assessment, *, clinical_profile=None) -> dict[str, Any]:
    missing = []
    processes = []
    for finding in assessment.get('findings', []):
        if finding.get('tier') == 'hypothesis':
            continue
        missing.extend(finding.get('missing_parameters', []))
        processes.append({
            'enzyme': finding['enzyme'], 'mechanism': finding['mechanism'],
            'perpetrator': finding['perpetrator'], 'victim': finding['victim'],
        })
    if not processes:
        missing.append('supported_perpetrator_victim_pair')
    if clinical_profile is None or clinical_profile.verified_at is None:
        missing.append('verified_clinical_profile')
    status = 'needs_data' if missing else 'eligible'
    return {
        'schema': 'neurobin-osp-export-v1', 'status': status,
        'missing_parameters': sorted(set(missing)),
        'stack': {'id': stack.id, 'name': stack.name, 'items': [
            {'compound_id': item.compound_id, 'name': item.compound.name,
             'dose': str(item.dosage_amount) if item.dosage_amount is not None else None,
             'unit': item.dosage_unit, 'scheduled_at': item.intake_time.isoformat() if item.intake_time else None}
            for item in stack.items.select_related('compound').all()
        ]},
        'processes': processes,
        'patient_profile_revision': getattr(clinical_profile, 'revision', None),
        'provenance': {'assessment_model': assessment.get('model_version')},
        'result_policy': 'No simulated AUC or exposure is produced by Neurobin.',
    }
