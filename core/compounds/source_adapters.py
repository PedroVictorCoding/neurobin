import hashlib
import json
import time

import requests
from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from accounts.private_storage import encrypt_blob
from .models import MetabolicImportReview, MetabolicSourceDiff, MetabolicSourceSnapshot


FDA_CYP_URL = 'https://www.fda.gov/drugs/drug-interactions-labeling/healthcare-professionals-fdas-examples-drugs-interact-cyp-enzymes-and-transporter-systems'
OPENFDA_LABEL_URL = 'https://api.fda.gov/drug/label.json'

COLUMN_CLASSIFICATION = {
    'CYP Strg INH': ('inhibitor', 'strong'), 'CYP Mod INH': ('inhibitor', 'moderate'),
    'CYP WK INH': ('inhibitor', 'weak'), 'CYP Strg IND': ('inducer', 'strong'),
    'CYP Mod IND': ('inducer', 'moderate'), 'CYP WK IND': ('inducer', 'weak'),
    'CYP SENS SUB': ('substrate', 'sensitive'), 'CYP Mod SENS SUB': ('substrate', 'moderate'),
}


def _get(session, url, *, params=None, attempts=4):
    for attempt in range(attempts):
        response = session.get(url, params=params, timeout=45)
        if response.status_code == 429 or response.status_code >= 500:
            if attempt == attempts - 1:
                response.raise_for_status()
            time.sleep(2 ** attempt)
            continue
        response.raise_for_status()
        return response


def fetch_fda_cyp_table(session=None):
    session = session or requests.Session()
    response = _get(session, FDA_CYP_URL)
    soup = BeautifulSoup(response.content, 'html.parser')
    table = next((table for table in soup.find_all('table') if 'CYP Strg INH' in table.get_text(' ', strip=True)), None)
    if table is None:
        raise ValueError('FDA CYP table shape changed; no recognized table found.')
    headers = [cell.get_text(' ', strip=True) for cell in table.find('tr').find_all(['th', 'td'])]
    records = []
    for row_index, row in enumerate(table.find_all('tr')[1:], start=1):
        cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'])]
        if len(cells) != len(headers) or not cells[0]:
            continue
        drug = cells[0]
        for header, value in zip(headers[1:], cells[1:]):
            if not value or header not in COLUMN_CLASSIFICATION:
                continue
            role, strength = COLUMN_CLASSIFICATION[header]
            enzyme = value.split()[0].upper().replace('CYP', '')
            records.append({
                'id': f'fda-table-{row_index}-{header}', 'compound': drug, 'enzyme': f'CYP{enzyme}',
                'role': role, 'strength': strength, 'quoted_classification': value,
                'source_url': FDA_CYP_URL, 'classification_column': header,
            })
    if not records:
        raise ValueError('FDA CYP parser produced zero records.')
    return response.content, records


def fetch_openfda_labels(*, effective_from, api_key='', session=None, max_pages=25):
    session = session or requests.Session()
    results = []
    for page in range(max_pages):
        params = {
            'search': f'effective_time:[{effective_from}+TO+99991231]', 'limit': 1000, 'skip': page * 1000,
        }
        if api_key:
            params['api_key'] = api_key
        response = _get(session, OPENFDA_LABEL_URL, params=params)
        batch = response.json().get('results', [])
        if not batch:
            break
        for label in batch:
            openfda = label.get('openfda') or {}
            results.append({
                'set_id': label.get('set_id'), 'effective_time': label.get('effective_time'),
                'spl_id': label.get('id') or label.get('set_id'),
                'substance_names': openfda.get('substance_name', []),
                'unii': openfda.get('unii', []),
                'drug_interactions': label.get('drug_interactions', []),
                'clinical_pharmacology': label.get('clinical_pharmacology', []),
                'source_url': OPENFDA_LABEL_URL,
            })
        if len(batch) < 1000:
            break
    return json.dumps(results, sort_keys=True).encode(), results


def store_snapshot(*, source, version, url, raw, records):
    checksum = hashlib.sha256(raw).hexdigest()
    existing = MetabolicSourceSnapshot.objects.filter(checksum=checksum).first()
    if existing:
        return existing, None
    previous = MetabolicSourceSnapshot.objects.filter(source=source).order_by('-retrieved_at').first()
    key_version, encrypted = encrypt_blob(raw)
    current_ids = {str(row.get('id') or row.get('set_id')): row for row in records}
    current_hashes = {
        record_id: hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
        for record_id, record in current_ids.items()
    }
    with transaction.atomic():
        snapshot = MetabolicSourceSnapshot.objects.create(
            source=source, source_version=version, source_url=url, checksum=checksum,
            encrypted_payload=encrypted, encryption_key_version=key_version,
            manifest={'record_count': len(records), 'ids': sorted(current_ids),
                      'record_hashes': current_hashes}, retrieved_at=timezone.now(),
        )
        previous_ids = set((previous.manifest or {}).get('ids', [])) if previous else set()
        previous_hashes = (previous.manifest or {}).get('record_hashes', {}) if previous else {}
        current_set = set(current_ids)
        changed = sorted(record_id for record_id in current_set & previous_ids
                         if previous_hashes.get(record_id) != current_hashes[record_id])
        diff = MetabolicSourceDiff.objects.create(
            source=source, previous_snapshot=previous, current_snapshot=snapshot,
            added=sorted(current_set - previous_ids), removed=sorted(previous_ids - current_set), changed=changed,
        )
    return snapshot, diff


def queue_label_reviews(snapshot, records):
    for record in records:
        for name in record.get('substance_names') or ['']:
            MetabolicImportReview.objects.update_or_create(
                source='openfda', source_version=snapshot.source_version,
                source_record_id=f"{record.get('set_id')}:{name}",
                defaults={'raw_name': name, 'raw_identifiers': {'unii': record.get('unii'), 'spl_id': record.get('spl_id')},
                          'candidates': [], 'reason': 'label_text_requires_review', 'raw_payload': record},
            )
