from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import quote_plus

import requests
from django.utils import timezone

from .models import Compound


REQUEST_TIMEOUT_SECONDS = 10
MAX_PUBMED_RESULTS_PER_QUERY = 5
ENRICHMENT_RETRY_HOURS = 24

logger = logging.getLogger(__name__)


def _clean_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_get_json(url: str) -> dict:
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("Compound enrichment request failed for %s: %s", url, exc)
        return {}

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        return {}

    return payload if isinstance(payload, dict) else {}


def _join_unique(values: list[str], *, limit: int = 3) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return "; ".join(out)


def _fetch_chembl_molecule(chembl_id: str) -> dict:
    chembl_id_clean = _clean_text(chembl_id).upper()
    if not chembl_id_clean:
        return {}

    molecule_url = f"https://www.ebi.ac.uk/chembl/api/data/molecule/{quote_plus(chembl_id_clean)}.json"
    mechanism_url = (
        "https://www.ebi.ac.uk/chembl/api/data/mechanism.json?"
        f"molecule_chembl_id={quote_plus(chembl_id_clean)}&limit=10"
    )

    molecule_payload = _safe_get_json(molecule_url)
    mechanism_payload = _safe_get_json(mechanism_url)

    molecule_properties = molecule_payload.get("molecule_properties") or {}
    molecule_structures = molecule_payload.get("molecule_structures") or {}
    mechanisms = mechanism_payload.get("mechanisms") or []

    mechanism_terms: list[str] = []
    for row in mechanisms:
        mechanism_terms.append(_clean_text((row or {}).get("mechanism_of_action")))
        mechanism_terms.append(_clean_text((row or {}).get("action_type")))

    return {
        "smiles": _clean_text(molecule_structures.get("canonical_smiles")),
        "inchi": _clean_text(molecule_structures.get("standard_inchi")),
        "inchi_key": _clean_text(molecule_structures.get("standard_inchi_key")),
        "iupac_name": _clean_text(molecule_payload.get("pref_name")),
        "molecular_formula": _clean_text(molecule_properties.get("full_molformula")),
        "molecular_weight": _clean_text(molecule_properties.get("full_mwt")),
        "mechanism_of_action_summary": _join_unique(mechanism_terms, limit=4),
    }


def _fetch_pubchem_cid_by_smiles(smiles: str) -> str:
    smiles_clean = _clean_text(smiles)
    if not smiles_clean:
        return ""

    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/"
        f"{quote_plus(smiles_clean)}/cids/JSON"
    )
    payload = _safe_get_json(url)
    cids = (payload.get("IdentifierList") or {}).get("CID") or []
    if not cids:
        return ""
    return _clean_text(cids[0])


def _fetch_pubchem_cid_by_name(name: str) -> str:
    name_clean = _clean_text(name)
    if not name_clean:
        return ""

    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
        f"{quote_plus(name_clean)}/cids/JSON"
    )
    payload = _safe_get_json(url)
    cids = (payload.get("IdentifierList") or {}).get("CID") or []
    if not cids:
        return ""
    return _clean_text(cids[0])


def _fetch_pubchem_by_cid(cid: str) -> dict:
    cid_clean = _clean_text(cid)
    if not cid_clean:
        return {}

    url = (
        "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
        f"{quote_plus(cid_clean)}/property/"
        "Title,MolecularFormula,MolecularWeight,CanonicalSMILES,SMILES,"
        "ConnectivitySMILES,IsomericSMILES,InChI,InChIKey,IUPACName/JSON"
    )
    payload = _safe_get_json(url)
    properties = (payload.get("PropertyTable") or {}).get("Properties") or []
    if not properties:
        return {}

    row = properties[0]
    smiles_value = _clean_text(
        row.get("CanonicalSMILES")
        or row.get("SMILES")
        or row.get("IsomericSMILES")
        or row.get("ConnectivitySMILES")
    )
    return {
        "smiles": smiles_value,
        "inchi": _clean_text(row.get("InChI")),
        "inchi_key": _clean_text(row.get("InChIKey")),
        "iupac_name": _clean_text(row.get("IUPACName")),
        "molecular_formula": _clean_text(row.get("MolecularFormula")),
        "molecular_weight": _clean_text(row.get("MolecularWeight")),
        "name": _clean_text(row.get("Title")),
    }


def _fetch_pubmed_interactions(cid: str, smiles: str) -> list[dict]:
    terms: list[str] = []
    cid_clean = _clean_text(cid)
    smiles_clean = _clean_text(smiles)

    if cid_clean:
        terms.append(f"{cid_clean}[All Fields] AND (interaction OR interactions OR \"drug interaction\")")
    if smiles_clean:
        terms.append(
            f'"{smiles_clean}"[All Fields] AND (interaction OR interactions OR "drug interaction")'
        )

    results: list[dict] = []
    seen_pmids: set[str] = set()

    for term in terms:
        search_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
            "db=pubmed&retmode=json"
            f"&retmax={MAX_PUBMED_RESULTS_PER_QUERY}"
            f"&term={quote_plus(term)}"
        )
        search_payload = _safe_get_json(search_url)
        pmids = ((search_payload.get("esearchresult") or {}).get("idlist") or [])
        if not pmids:
            continue

        summary_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
            "db=pubmed&retmode=json"
            f"&id={quote_plus(','.join(pmids))}"
        )
        summary_payload = _safe_get_json(summary_url)
        summary_rows = summary_payload.get("result") or {}

        for pmid in pmids:
            pmid_text = _clean_text(pmid)
            if not pmid_text or pmid_text in seen_pmids:
                continue
            row = summary_rows.get(pmid_text) or summary_rows.get(str(pmid_text)) or {}
            if not isinstance(row, dict):
                continue

            seen_pmids.add(pmid_text)
            results.append(
                {
                    "pmid": pmid_text,
                    "title": _clean_text(row.get("title")),
                    "pubdate": _clean_text(row.get("pubdate")),
                    "source": _clean_text(row.get("source")),
                    "query": term,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid_text}/",
                }
            )

    return results


def _should_enrich(compound: Compound) -> bool:
    if compound.pk is None:
        return False
    if not compound.missing_enrichment:
        return False

    if compound.enriched_at is None:
        return True
    return timezone.now() - compound.enriched_at >= timedelta(hours=ENRICHMENT_RETRY_HOURS)


def enrich_compound(compound: Compound) -> Compound:
    """
    Fill missing external metadata for a compound.

    Sources:
    - ChEMBL (by ChEMBL ID)
    - PubChem (CID and CID lookup by SMILES/name)
    - PubMed (interaction-focused queries by CID and SMILES)
    """
    if not _should_enrich(compound):
        return compound

    chembl_data = _fetch_chembl_molecule(compound.chembl_id)

    smiles = _clean_text(compound.smiles) or _clean_text(chembl_data.get("smiles"))
    cid = _clean_text(compound.pubchem_cid)
    if not cid and smiles:
        cid = _fetch_pubchem_cid_by_smiles(smiles)
    if not cid:
        cid = _fetch_pubchem_cid_by_name(compound.name)

    pubchem_data = _fetch_pubchem_by_cid(cid)

    update_fields: list[str] = []

    def set_if_empty(field: str, value: str) -> None:
        current = _clean_text(getattr(compound, field))
        incoming = _clean_text(value)
        if current or not incoming:
            return
        setattr(compound, field, incoming)
        update_fields.append(field)

    set_if_empty("smiles", smiles or pubchem_data.get("smiles", ""))
    set_if_empty("pubchem_cid", cid)
    set_if_empty("inchi", chembl_data.get("inchi") or pubchem_data.get("inchi"))
    set_if_empty("inchi_key", chembl_data.get("inchi_key") or pubchem_data.get("inchi_key"))
    set_if_empty("iupac_name", pubchem_data.get("iupac_name") or chembl_data.get("iupac_name"))
    set_if_empty("molecular_formula", chembl_data.get("molecular_formula") or pubchem_data.get("molecular_formula"))
    set_if_empty("molecular_weight", chembl_data.get("molecular_weight") or pubchem_data.get("molecular_weight"))
    set_if_empty(
        "mechanism_of_action_summary",
        chembl_data.get("mechanism_of_action_summary"),
    )

    if not compound.pubmed_interactions:
        interaction_rows = _fetch_pubmed_interactions(
            cid=_clean_text(compound.pubchem_cid) or cid,
            smiles=_clean_text(compound.smiles) or smiles,
        )
        if interaction_rows:
            compound.pubmed_interactions = interaction_rows
            update_fields.append("pubmed_interactions")

    compound.enriched_at = timezone.now()
    update_fields.append("enriched_at")

    if update_fields:
        compound.save(update_fields=sorted(set(update_fields)))

    return compound
