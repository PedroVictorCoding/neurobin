import math
from collections import defaultdict

from django.db.models import Q
from compounds.models import CompoundTargetInteraction


AFFINITY_WEIGHTS = {
    'very_high': 1.0,
    'high': 0.8,
    'medium': 0.5,
    'low': 0.2,
    'very_low': 0.1,
    'unknown': 0.0,
}


def compute_enzymatic_overload(compound_ids: list[int]) -> dict:
    if not compound_ids:
        return {
            'score': 0.0,
            'distinct_enzymes': 0,
            'total_interactions': 0,
            'avg_affinity_per_enzyme': 0.0,
            'quantity_multiplier': 0.0,
            'enzymes': [],
        }

    rows = (
        CompoundTargetInteraction.objects.filter(compound_id__in=compound_ids)
        .filter(
            Q(target__target_type='enzyme') | Q(target__type='enzyme')
        )
        .select_related('target')
        .only('id', 'affinity_level', 'target_id', 'target__name')
    )

    per_enzyme = defaultdict(lambda: {'weight': 0.0, 'interaction_count': 0, 'name': ''})
    total_interactions = 0
    for row in rows:
        total_interactions += 1
        weight = AFFINITY_WEIGHTS.get(row.affinity_level, 0.0)
        bucket = per_enzyme[row.target_id]
        bucket['weight'] += weight
        bucket['interaction_count'] += 1
        if not bucket['name']:
            bucket['name'] = row.target.name

    distinct = len(per_enzyme)
    total_weight = sum(v['weight'] for v in per_enzyme.values())
    avg_per_enzyme = (total_weight / distinct) if distinct else 0.0
    quantity_multiplier = math.log1p(distinct) if distinct else 0.0
    score = avg_per_enzyme * quantity_multiplier

    enzymes = [
        {
            'id': enzyme_id,
            'name': data['name'],
            'weight': data['weight'],
            'interaction_count': data['interaction_count'],
        }
        for enzyme_id, data in per_enzyme.items()
    ]
    enzymes.sort(key=lambda row: row['weight'], reverse=True)

    return {
        'score': score,
        'distinct_enzymes': distinct,
        'total_interactions': total_interactions,
        'avg_affinity_per_enzyme': avg_per_enzyme,
        'quantity_multiplier': quantity_multiplier,
        'enzymes': enzymes[:6],
    }
