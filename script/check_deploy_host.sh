#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

fail=0

check_cmd() {
  local cmd="$1"
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "ok: found $cmd"
  else
    echo "missing: $cmd" >&2
    fail=1
  fi
}

echo "== host preflight =="
echo "root=$ROOT_DIR"
echo "os=$(uname -s) arch=$(uname -m)"

check_cmd docker
check_cmd curl

if command -v jq >/dev/null 2>&1; then
  echo "ok: found jq"
else
  echo "warn: jq not found, JSON inspection will be less convenient"
fi

if [[ -f ".env" ]]; then
  echo "ok: found .env"
else
  echo "missing: .env (copy from .env.example first)" >&2
  fail=1
fi

if docker compose version >/dev/null 2>&1; then
  echo "ok: docker compose available"
else
  echo "missing: docker compose plugin" >&2
  fail=1
fi

if docker info >/dev/null 2>&1; then
  echo "ok: docker daemon reachable"
else
  echo "missing: docker daemon not reachable" >&2
  fail=1
fi

for path in \
  "zk/tsip_step/verification_key.json" \
  "zk/tsip_step/tsip_step_final.zkey" \
  "zk/tsip_step/tsip_step_js/tsip_step.wasm"
do
  if [[ -f "$path" ]]; then
    echo "ok: found $path"
  else
    echo "missing: $path" >&2
    fail=1
  fi
done

echo "== port plan =="
echo "8001 -> shuffler"
echo "8002 -> aggregator_a"
echo "8003 -> aggregator_r"
echo "8010 -> decoder"

if [[ "$fail" -ne 0 ]]; then
  echo "host preflight failed" >&2
  exit 1
fi

echo "host preflight passed"
