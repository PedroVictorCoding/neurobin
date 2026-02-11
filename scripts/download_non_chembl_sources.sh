#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${ROOT_DIR}/data/import_sources"
INCLUDE_DRUGBANK=0
EXTRACT_ZIPS=1

DRUGBANK_URL="${DRUGBANK_URL:-}"
DRUGBANK_USER="${DRUGBANK_USER:-}"
DRUGBANK_PASSWORD="${DRUGBANK_PASSWORD:-}"

SHOW_HELP=0

usage() {
  cat <<'EOF'
Usage:
  scripts/download_non_chembl_sources.sh [options]

Options:
  --output-dir PATH       Destination root (default: data/import_sources)
  --include-drugbank      Attempt DrugBank download (license/account required)
  --drugbank-url URL      DrugBank download URL (or use DRUGBANK_URL env var)
  --drugbank-user USER    Optional HTTP auth user (or DRUGBANK_USER env var)
  --drugbank-password PW  Optional HTTP auth password (or DRUGBANK_PASSWORD env var)
  --no-extract            Do not auto-extract downloaded .zip files
  -h, --help              Show this help

Examples:
  scripts/download_non_chembl_sources.sh
  scripts/download_non_chembl_sources.sh --include-drugbank --drugbank-url "https://..."
  DRUGBANK_URL="https://..." DRUGBANK_USER="..." DRUGBANK_PASSWORD="..." scripts/download_non_chembl_sources.sh --include-drugbank
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --include-drugbank)
      INCLUDE_DRUGBANK=1
      shift
      ;;
    --drugbank-url)
      DRUGBANK_URL="$2"
      shift 2
      ;;
    --drugbank-user)
      DRUGBANK_USER="$2"
      shift 2
      ;;
    --drugbank-password)
      DRUGBANK_PASSWORD="$2"
      shift 2
      ;;
    --no-extract)
      EXTRACT_ZIPS=0
      shift
      ;;
    -h|--help)
      SHOW_HELP=1
      shift
      ;;
    *)
      echo "[!] Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ "$SHOW_HELP" == "1" ]]; then
  usage
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[x] curl is required but not installed." >&2
  exit 1
fi

mkdir -p \
  "${OUTPUT_DIR}/iuphar" \
  "${OUTPUT_DIR}/bindingdb" \
  "${OUTPUT_DIR}/dgidb" \
  "${OUTPUT_DIR}/pharmgkb" \
  "${OUTPUT_DIR}/drugbank"

if [[ "$EXTRACT_ZIPS" == "1" ]] && ! command -v unzip >/dev/null 2>&1; then
  echo "[!] unzip not found. Zip files will not be extracted."
  EXTRACT_ZIPS=0
fi

SUCCESS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

download_to_file() {
  local url="$1"
  local dest="$2"
  local tmp="${dest}.tmp"

  echo "[→] Downloading: ${url}"
  if curl -fL \
    --retry 4 \
    --retry-delay 2 \
    --connect-timeout 20 \
    --max-time 1800 \
    "${url}" \
    -o "${tmp}"; then
    mv "${tmp}" "${dest}"
    echo "[✓] Saved: ${dest}"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    return 0
  fi

  rm -f "${tmp}"
  echo "[x] Failed: ${url}"
  return 1
}

download_to_file_with_auth() {
  local url="$1"
  local dest="$2"
  local tmp="${dest}.tmp"

  echo "[→] Downloading (auth): ${url}"
  if [[ -n "${DRUGBANK_USER}" && -n "${DRUGBANK_PASSWORD}" ]]; then
    if curl -fL \
      --retry 4 \
      --retry-delay 2 \
      --connect-timeout 20 \
      --max-time 1800 \
      -u "${DRUGBANK_USER}:${DRUGBANK_PASSWORD}" \
      "${url}" \
      -o "${tmp}"; then
      mv "${tmp}" "${dest}"
      echo "[✓] Saved: ${dest}"
      SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
      return 0
    fi
  else
    if curl -fL \
      --retry 4 \
      --retry-delay 2 \
      --connect-timeout 20 \
      --max-time 1800 \
      "${url}" \
      -o "${tmp}"; then
      mv "${tmp}" "${dest}"
      echo "[✓] Saved: ${dest}"
      SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
      return 0
    fi
  fi

  rm -f "${tmp}"
  echo "[x] Failed: ${url}"
  return 1
}

extract_zip_if_needed() {
  local file="$1"
  local dest_dir="$2"
  if [[ "$EXTRACT_ZIPS" != "1" ]]; then
    return 0
  fi
  if [[ "${file##*.}" != "zip" ]]; then
    return 0
  fi
  echo "[→] Extracting: ${file}"
  unzip -o -q "${file}" -d "${dest_dir}"
  echo "[✓] Extracted into: ${dest_dir}"
}

download_first_success() {
  local dest="$1"
  shift
  local url
  for url in "$@"; do
    if download_to_file "${url}" "${dest}"; then
      return 0
    fi
  done
  FAIL_COUNT=$((FAIL_COUNT + 1))
  return 1
}

echo "[i] Output directory: ${OUTPUT_DIR}"
echo "[i] Starting non-ChEMBL source downloads..."

# IUPHAR (Guide to Pharmacology)
IUPHAR_DIR="${OUTPUT_DIR}/iuphar"
download_first_success \
  "${IUPHAR_DIR}/interactions.tsv" \
  "https://www.guidetopharmacology.org/DATA/interactions.tsv" \
  "https://www.guidetopharmacology.org/DATA/interactions.csv" || true

# BindingDB
BINDINGDB_DIR="${OUTPUT_DIR}/bindingdb"
BINDINGDB_ZIP="${BINDINGDB_DIR}/BindingDB_All.tsv.zip"
if download_first_success \
  "${BINDINGDB_ZIP}" \
  "https://www.bindingdb.org/rwd/bind/downloads/BindingDB_All.tsv.zip" \
  "https://www.bindingdb.org/bind/downloads/BindingDB_All.tsv.zip"; then
  extract_zip_if_needed "${BINDINGDB_ZIP}" "${BINDINGDB_DIR}"
fi

# DGIdb
DGIDB_DIR="${OUTPUT_DIR}/dgidb"
download_first_success \
  "${DGIDB_DIR}/interactions.tsv" \
  "https://www.dgidb.org/data/latest/interactions.tsv" \
  "https://www.dgidb.org/downloads" || true

# PharmGKB
PHARMGKB_DIR="${OUTPUT_DIR}/pharmgkb"
download_first_success \
  "${PHARMGKB_DIR}/clinical_annotations.json" \
  "https://api.pharmgkb.org/v1/data/clinicalAnnotation" \
  "https://api.pharmgkb.org/v1/data/variantAnnotation" || true

# DrugBank (license/account required)
if [[ "$INCLUDE_DRUGBANK" == "1" ]]; then
  if [[ -z "${DRUGBANK_URL}" ]]; then
    echo "[x] DrugBank requested but no URL provided."
    echo "    Set --drugbank-url or DRUGBANK_URL."
    FAIL_COUNT=$((FAIL_COUNT + 1))
  else
    DRUGBANK_DIR="${OUTPUT_DIR}/drugbank"
    DRUGBANK_FILE="${DRUGBANK_DIR}/drugbank_download.zip"
    if download_to_file_with_auth "${DRUGBANK_URL}" "${DRUGBANK_FILE}"; then
      extract_zip_if_needed "${DRUGBANK_FILE}" "${DRUGBANK_DIR}"
    else
      FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
  fi
else
  echo "[i] Skipping DrugBank (use --include-drugbank to enable)."
  SKIP_COUNT=$((SKIP_COUNT + 1))
fi

echo
echo "[i] Download summary:"
echo "    successful: ${SUCCESS_COUNT}"
echo "    failed groups: ${FAIL_COUNT}"
echo "    skipped groups: ${SKIP_COUNT}"
echo "    output: ${OUTPUT_DIR}"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  exit 1
fi

exit 0
