#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/core${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -x "venv/bin/python" ]]; then
  echo "venv not found at ./venv. Create it and install deps first."
  exit 1
fi

export DJANGO_ENV="${DJANGO_ENV:-development}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings}"

if [[ "${RUN_DEPLOY_CHECK:-0}" == "1" ]]; then
  venv/bin/python core/manage.py check --deploy --fail-level WARNING
fi

if command -v redis-cli >/dev/null 2>&1; then
  if ! redis-cli ping >/dev/null 2>&1; then
    echo "Redis is not responding on localhost:6379."
    echo "Start Redis before running this script."
  fi
else
  echo "redis-cli not found. Ensure Redis is running on localhost:6379."
fi

if [[ "${RUN_MIGRATIONS:-0}" == "1" ]]; then
  venv/bin/python core/manage.py migrate
fi

if [[ "${COLLECTSTATIC:-0}" == "1" ]]; then
  venv/bin/python core/manage.py collectstatic --noinput
fi

cleanup() {
  if [[ -n "${CELERY_PID:-}" ]]; then
    kill "$CELERY_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

if [[ "${START_CELERY_WORKER:-0}" == "1" ]]; then
  venv/bin/celery -A core.celery worker -l info &
  CELERY_PID=$!
  echo "Celery worker started (pid=$CELERY_PID)"
else
  echo "Skipping embedded Celery worker (START_CELERY_WORKER=0)."
fi

WEB_BIND="${WEB_BIND:-0.0.0.0:9000}"
venv/bin/python core/manage.py runserver "$WEB_BIND" --insecure
