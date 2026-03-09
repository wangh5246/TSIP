#!/usr/bin/env bash
set -euo pipefail

RECONSTRUCT_URL="${RECONSTRUCT_URL:-http://localhost:8002/reconstruct_latest?expected=0}"
DP_URL="${DP_URL:-http://localhost:8002/dump_latest_dp?epsilon=1.0&tau=3&tau2=3}"
DECODE_AUDIT_URL="${DECODE_AUDIT_URL:-http://localhost:8010/authorize_decode}"
DECODE_URL="${DECODE_URL:-http://localhost:8010/decode_tokens}"
AUDIT_CALLER_TOKEN="${AUDIT_CALLER_TOKEN:-audit_caller_v1}"
TOKENS_N="${TOKENS_N:-3}"

echo "1) reconstruct_latest"
curl -s -X POST "$RECONSTRUCT_URL" | jq .

echo "2) dump_latest_dp"
DP_JSON="$(curl -s "$DP_URL")"
echo "$DP_JSON" | jq .

ERR_MSG="$(echo "$DP_JSON" | jq -r '.error // empty')"
if [[ -n "$ERR_MSG" ]]; then
  echo "error: $ERR_MSG" 1>&2
  exit 1
fi

ROUND_ID="$(echo "$DP_JSON" | jq -r '.round_id')"
TOKENS_JSON="$(echo "$DP_JSON" | jq -c --argjson n "$TOKENS_N" '(.top_tokens // .top_cells // [])[:$n] | map(.[0])')"
TOKENS_LEN="$(echo "$TOKENS_JSON" | jq 'length')"

if [[ "$TOKENS_LEN" -eq 0 ]]; then
  echo "no tokens available to decode"
  exit 0
fi

AUDIT_JSON="$(curl -s -X POST "$DECODE_AUDIT_URL" \
  -H "X-Audit-Caller: ${AUDIT_CALLER_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{\"round_id\":${ROUND_ID},\"tokens\":${TOKENS_JSON}}")"

SIG="$(echo "$AUDIT_JSON" | jq -r '.signature // empty')"
ISSUED_AT="$(echo "$AUDIT_JSON" | jq -r '.issued_at // empty')"
TTL="$(echo "$AUDIT_JSON" | jq -r '.ttl_seconds // empty')"

if [[ -z "$SIG" || -z "$ISSUED_AT" || -z "$TTL" ]]; then
  echo "failed to get audit signature" 1>&2
  exit 1
fi

echo "3) decode_tokens with signature"
curl -s -X POST "$DECODE_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"round_id\":${ROUND_ID},\"tokens\":${TOKENS_JSON},\"signature\":\"${SIG}\",\"issued_at\":${ISSUED_AT},\"ttl_seconds\":${TTL}}" | jq .

echo "4) decode_tokens without signature (should fail)"
curl -s -X POST "$DECODE_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"round_id\":${ROUND_ID},\"tokens\":${TOKENS_JSON}}" | jq .
