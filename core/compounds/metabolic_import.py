import csv
import hashlib
import io
import json
from urllib.parse import urlparse

import requests
from django.db import transaction
from django.utils import timezone

from .models import Compound, MetabolicImportReview, MetabolicInteractionEvidence


ROLE_ALIASES = {
    'substrate': 'substrate', 'sensitive substrate': 'substrate',
    'inhibitor': 'inhibitor', 'reversible inhibitor': 'inhibitor',
    'inducer': 'inducer', 'time-dependent inhibitor': 'time_dependent_inhibitor',
    'time dependent inhibitor': 'time_dependent_inhibitor',
}


def _load_source(location):
    if urlparse(location).scheme in {'http', 'https'}:
        response = requests.get(location, timeout=30)
        response.raise_for_status()
        return response.content, response.headers.get('content-type', '')
    with open(location, 'rb') as handle:
        return handle.read(), ''


def _rows(raw, content_type, location):
    text = raw.decode('utf-8-sig')
    if 'json' in content_type or location.lower().endswith('.json'):
        payload = json.loads(text)
        return payload if isinstance(payload, list) else payload.get('results', payload.get('records', []))
    return list(csv.DictReader(io.StringIO(text)))


def _match_compound(row):
    inchi_key = (row.get('inchi_key') or row.get('inchikey') or '').strip()
    if inchi_key:
        matches = list(Compound.objects.filter(inchi_key__iexact=inchi_key)[:2])
        if len(matches) == 1:
            return matches[0], []
    pubchem = str(row.get('pubchem_cid') or '').strip()
    if pubchem:
        matches = list(Compound.objects.filter(pubchem_cid=pubchem)[:2])
        if len(matches) == 1:
            return matches[0], []
    name = (row.get('compound') or row.get('drug_name') or row.get('name') or '').strip()
    matches = list(Compound.objects.filter(name__iexact=name)[:5])
    if len(matches) == 1:
        return matches[0], []
    alias_matches = list(Compound.objects.filter(aliases__icontains=name)[:5]) if name else []
    if len(alias_matches) == 1:
        return alias_matches[0], []
    return None, [{'id': item.id, 'name': item.name} for item in (matches or alias_matches)]


def import_metabolic_source(*, source, source_version, location, evidence_tier, dry_run=False):
    raw, content_type = _load_source(location)
    checksum = hashlib.sha256(raw).hexdigest()
    records = _rows(raw, content_type, location)
    stats = {'seen': len(records), 'created': 0, 'updated': 0, 'review': 0, 'unchanged': 0, 'checksum': checksum}
    retrieved_at = timezone.now()
    for index, row in enumerate(records):
        source_record_id = str(row.get('source_record_id') or row.get('id') or index)
        compound, candidates = _match_compound(row)
        if not compound:
            stats['review'] += 1
            if not dry_run:
                MetabolicImportReview.objects.update_or_create(
                    source=source, source_version=source_version, source_record_id=source_record_id,
                    defaults={'raw_name': row.get('compound') or row.get('drug_name') or row.get('name') or '',
                              'raw_identifiers': {'inchi_key': row.get('inchi_key'), 'pubchem_cid': row.get('pubchem_cid')},
                              'candidates': candidates, 'reason': 'ambiguous_or_unmatched'},
                )
            continue
        role_raw = str(row.get('role') or row.get('classification') or '').strip().lower()
        role = ROLE_ALIASES.get(role_raw)
        if not role:
            stats['review'] += 1
            continue
        nti_raw = row.get('narrow_therapeutic_index', False)
        nti = nti_raw if isinstance(nti_raw, bool) else str(nti_raw).strip().lower() in {'1', 'true', 'yes'}
        defaults = {
            'compound': compound, 'enzyme': str(row.get('enzyme') or '').upper().replace(' ', ''),
            'role': role, 'strength': str(row.get('strength') or ('sensitive' if 'sensitive' in role_raw else 'unknown')).lower(),
            'evidence_tier': evidence_tier, 'narrow_therapeutic_index': nti,
            'source_url': row.get('source_url') or (location if urlparse(location).scheme else ''),
            'source_checksum': checksum, 'quoted_classification': row.get('quoted_classification') or role_raw,
            'route': row.get('route') or '', 'retrieved_at': retrieved_at, 'raw_payload': row,
        }
        existing = MetabolicInteractionEvidence.objects.filter(
            source=source, source_record_id=source_record_id, source_version=source_version,
        ).first()
        if dry_run:
            stats['updated' if existing else 'created'] += 1
            continue
        with transaction.atomic():
            MetabolicInteractionEvidence.objects.filter(
                source=source, source_record_id=source_record_id, superseded_at__isnull=True,
            ).exclude(source_version=source_version).update(superseded_at=retrieved_at)
            _obj, created = MetabolicInteractionEvidence.objects.update_or_create(
                source=source, source_record_id=source_record_id, source_version=source_version,
                defaults=defaults,
            )
            stats['created' if created else 'updated'] += 1
    return stats
