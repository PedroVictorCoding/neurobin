# Metabolic Interaction Assessment v4

Neurobin's v4 assessment is a research-screening system. It is not clinical
decision support and does not recommend doses or calculate exposure/AUC.

## Evidence model

Active records are ordered by evidence tier: FDA/label clinical, curated human,
experimental, consensus, then predicted. Records retain their source version,
checksum, URL, retrieved date, quoted classification, and raw payload. Older
versions are superseded rather than deleted. Ambiguous compound matches enter
`MetabolicImportReview`.

Import a normalized JSON or CSV source with:

```bash
python manage.py import_metabolic_source \
  --source fda --source-version 2026-01 --input /data/fda-cyp.json --dry-run
```

ClinPGx is disabled unless `--enable-clinpgx` is supplied after its data terms
have been reviewed.

## Result tiers

- **High:** clinical/curated strong perpetrator plus sensitive or narrow-index substrate.
- **Moderate:** supported perpetrator–victim mechanism with incomplete quantitative context.
- **Hypothesis:** prediction overlap without supported roles.
- **Unknown:** missing or contradictory evidence.

Missing Ki/IC50, fraction metabolized, dose, route, or half-life is reported as
missing. It is never replaced with a population default. Prediction overlap is
retained in the deprecated compatibility field but does not affect the legacy
risk score.

## Private patient context and PBPK

Clinical profiles and report documents are accessible only through authenticated
owner endpoints under `/api/accounts/`. Extracted report values remain drafts
until explicitly confirmed, and confirmation invalidates profile verification.
Public/shared stack payloads never contain clinical-profile values.

`GET /api/stacks/stack/{id}/pbpk_export/` returns an OSP-oriented eligibility
bundle. `needs_data` includes every missing parameter. Neurobin does not execute
PK-Sim or accept simulation results in v4.
