#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

print_service_cfg() {
  local svc="$1"
  local pattern="$2"
  echo "== ${svc} =="
  if ! docker compose ps --services --status running | grep -q "^${svc}$"; then
    echo "(not running)"
    echo
    return
  fi
  docker compose exec -T "$svc" env | grep -E "$pattern" | sort || true
  echo
}

print_service_cfg "shuffler" "^(PROOF_|ZK_STEP_|MAX_STEP_M|FLUSH_SECONDS)"
print_service_cfg "aggregator_a" "^(DP_|DECODE_|K=|KD=|DOMAIN=|MASK_BITS=)"
print_service_cfg "client_sim" "^(PROOF_|ZK_STEP_|MAX_STEP_M|REPORT_TIMEOUT_SEC|SEND_INTERVAL_SEC|MALICIOUS_RATE)"
