# Metabolic Assessment Hardening Runbook

The feature must remain disabled until every readiness check and the pharmacist
validation gate passes.

## Host preparation

1. Mount a LUKS/provider-encrypted volume at `/var/lib/neurobin`.
2. Create `/var/lib/neurobin/private-clinical` owned by the application user with mode `0700`.
3. Install and enable `clamav-daemon`; grant the application user access to its Unix socket.
4. Generate a 32-byte AES key, encode it with URL-safe base64, and configure a versioned keyring.
5. Run Celery worker and beat services. Uploads fail closed if the scan cannot be queued.
6. Keep nginx and Django media aliases pointed only at ordinary `MEDIA_ROOT`; never alias the private root.

## Pre-merge and staging gate

1. Run `scripts/backup_clinical_release.sh` with an age recipient and verify its checksums.
2. Restore the database and private archive into an isolated staging host and open an encrypted document through the authenticated endpoint.
3. Apply migrations and run Django checks plus the blocking CI suites.
4. Run `sync_official_metabolic_sources --source fda`, review the source diff, and resolve ambiguous matches.
5. Run `validate_metabolic_reference_set --dataset-version <version>` and archive its JSON report.
6. Require sensitivity ≥0.95, specificity ≥0.90, zero prediction promotions, and named pharmacist approval.
7. Enable `METABOLIC_ASSESSMENT_ENABLED=True` with a staff allowlist only.
8. Verify `/api/accounts/clinical-profile/readiness/` returns HTTP 200 before staff validation.

## Key rotation and retention

Add the new key to `CLINICAL_DOCUMENT_KEYS`, set it active, restart workers, and retain old keys until all documents encrypted with them have been purged or re-encrypted. The daily beat task purges originals 30 days after extraction; audit and confirmed structured provenance remain.

## Rollback

Disable the feature flag first. Stop workers, restore the encrypted database and file snapshots, restore the previous keyring, apply the previous release, and rerun the authenticated download and isolation checks. Never copy decrypted clinical files into `MEDIA_ROOT`.
