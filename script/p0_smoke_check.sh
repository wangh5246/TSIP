#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BUILD_SERVICES="${BUILD_SERVICES:-1}"

echo "== P0 smoke check =="
echo "1) ensure services are up"
if [[ "$BUILD_SERVICES" == "1" ]]; then
  docker compose up -d --build shuffler aggregator_a aggregator_r decoder client_sim >/dev/null
else
  docker compose up -d shuffler aggregator_a aggregator_r decoder client_sim >/dev/null
fi

echo "2) generate one round reports"
docker compose exec -T client_sim python client.py >/tmp/p0_client_run.log
tail -n 5 /tmp/p0_client_run.log

echo "3) fetch latest status"
STATUS_JSON="$(curl -s http://localhost:8002/status_latest)"
echo "$STATUS_JSON" | jq .

RID="$(echo "$STATUS_JSON" | jq -r '.round_id')"
RA="$(echo "$STATUS_JSON" | jq -r '.received_A')"
RR="$(echo "$STATUS_JSON" | jq -r '.received_R')"
if [[ -z "$RID" || "$RID" == "null" ]]; then
  echo "error: no latest round id" >&2
  exit 1
fi
if (( RA < RR )); then
  EXPECTED="$RA"
else
  EXPECTED="$RR"
fi

echo "4) secure reconstruct_latest expected=$EXPECTED"
RECON_JSON="$(curl -s -X POST "http://localhost:8010/secure/reconstruct_latest?expected=${EXPECTED}")"
echo "$RECON_JSON" | jq .
if [[ "$(echo "$RECON_JSON" | jq -r '.ok // false')" != "true" ]]; then
  echo "error: secure/reconstruct_latest failed" >&2
  exit 1
fi

echo "5) reset privacy budget"
RESET_JSON="$(curl -s -X POST "http://localhost:8002/privacy_budget_reset?round_id=${RID}")"
echo "$RESET_JSON" | jq .

echo "6) dp/latest first call should pass"
DP1="$(curl -s "http://localhost:8002/dp/latest")"
echo "$DP1" | jq '{mode, round_id, cells_kept_post, dp_decode_enabled, error}'
if [[ -n "$(echo "$DP1" | jq -r '.error // empty')" ]]; then
  echo "error: dp/latest first call returned error" >&2
  exit 1
fi

echo "7) dp/latest second call should hit budget gate"
DP2="$(curl -s "http://localhost:8002/dp/latest")"
echo "$DP2" | jq .
ERR2="$(echo "$DP2" | jq -r '.error // empty')"
if [[ "$ERR2" != "privacy budget exhausted" ]]; then
  echo "error: expected privacy budget exhausted, got: $ERR2" >&2
  exit 1
fi

echo "8) privacy_budget_status should show exhausted"
PBS="$(curl -s "http://localhost:8002/privacy_budget_status?round_id=${RID}")"
echo "$PBS" | jq .
EXH="$(echo "$PBS" | jq -r '.exhausted // false')"
if [[ "$EXH" != "true" ]]; then
  echo "error: expected exhausted=true" >&2
  exit 1
fi

echo "9) secure status latest"
SSTAT="$(curl -s "http://localhost:8010/secure/status_latest")"
echo "$SSTAT" | jq '{ok, round_id, cells_in_final_map}'
if [[ "$(echo "$SSTAT" | jq -r '.ok // false')" != "true" ]]; then
  echo "error: secure/status_latest failed" >&2
  exit 1
fi

echo "P0 smoke check passed"
