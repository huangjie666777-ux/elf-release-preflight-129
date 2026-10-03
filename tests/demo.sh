#!/usr/bin/env bash
# Start the service, build fixtures and show curl reports.
set -euo pipefail
ROOT="${1:-/tmp/precheck-release}"
bash "$(dirname "$0")/make_fixtures.sh" "$ROOT"
setsid nohup .venv/bin/python -m uvicorn app.main:app --port 8123 >/tmp/uvicorn.log 2>&1 &
sleep 2
trap 'pkill -f "uvicorn app.main:app" || true' EXIT

echo '=== health ==='
curl -s localhost:8123/api/health; echo

echo '=== happy tree (libc intentionally absent -> not ok, edges reported) ==='
curl -s -X POST localhost:8123/api/precheck -H 'Content-Type: application/json' \
  -d "{\"root\":\"$ROOT\",\"entry\":\"/bin/app\",\"lib_dirs\":[\"/lib\"]}" \
  | .venv/bin/python -m json.tool

echo '=== missing version LIBFOO_2 (oldlib first) ==='
curl -s -X POST localhost:8123/api/precheck -H 'Content-Type: application/json' \
  -d "{\"root\":\"$ROOT\",\"entry\":\"/bin/app\",\"lib_dirs\":[\"/oldlib\",\"/lib\"]}" \
  | .venv/bin/python -c "import json,sys; r=json.load(sys.stdin); print('ok:', r['ok']); [print(d) for d in r['diagnostics']]"

