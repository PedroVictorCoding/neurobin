#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${CLINICAL_DOCUMENT_ROOT:?CLINICAL_DOCUMENT_ROOT is required}"
: "${BACKUP_OUTPUT_DIR:?BACKUP_OUTPUT_DIR is required}"
: "${AGE_RECIPIENT:?AGE_RECIPIENT is required}"

case "$CLINICAL_DOCUMENT_ROOT" in /|"$HOME"|"$HOME/"|"") echo "Refusing broad clinical document root" >&2; exit 2;; esac
case "$BACKUP_OUTPUT_DIR" in /|"$HOME"|"$HOME/"|"") echo "Refusing broad backup directory" >&2; exit 2;; esac

mkdir -p -- "$BACKUP_OUTPUT_DIR"
chmod 700 -- "$BACKUP_OUTPUT_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump --dbname="$DATABASE_URL" --format=custom | age -r "$AGE_RECIPIENT" -o "$BACKUP_OUTPUT_DIR/database-$timestamp.dump.age"
tar -C "$(dirname "$CLINICAL_DOCUMENT_ROOT")" -cf - "$(basename "$CLINICAL_DOCUMENT_ROOT")" | age -r "$AGE_RECIPIENT" -o "$BACKUP_OUTPUT_DIR/clinical-files-$timestamp.tar.age"
sha256sum "$BACKUP_OUTPUT_DIR"/*"$timestamp"*.age > "$BACKUP_OUTPUT_DIR/manifest-$timestamp.sha256"
chmod 600 -- "$BACKUP_OUTPUT_DIR"/*"$timestamp"*
