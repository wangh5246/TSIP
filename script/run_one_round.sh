#!/usr/bin/env bash
set -e

EXPECTED=${EXPECTED:-auto}
TAU=3
TAU2=3

echo "1) run client"
docker compose exec client_sim python client.py

echo "2) status"
STATUS_JSON="$(curl -s http://localhost:8002/status_latest)"
echo "${STATUS_JSON}" | jq .

if [[ -z "${EXPECTED}" || "${EXPECTED}" == "0" || "${EXPECTED}" == "auto" ]]; then
  RECEIVED_A="$(echo "${STATUS_JSON}" | jq -r '.received_A // 0')"
  RECEIVED_R="$(echo "${STATUS_JSON}" | jq -r '.received_R // 0')"
  if [[ "${RECEIVED_A}" =~ ^[0-9]+$ && "${RECEIVED_R}" =~ ^[0-9]+$ ]]; then
    if (( RECEIVED_A < RECEIVED_R )); then
      EXPECTED_RECON="${RECEIVED_A}"
    else
      EXPECTED_RECON="${RECEIVED_R}"
    fi
  else
    EXPECTED_RECON=0
  fi
else
  EXPECTED_RECON="${EXPECTED}"
fi
echo "reconstruct expected=${EXPECTED_RECON}"

echo "3) reconstruct"
curl -s -X POST "http://localhost:8010/secure/reconstruct_latest?expected=${EXPECTED_RECON}" | jq .

echo "4) secure status"
curl -s "http://localhost:8010/secure/status_latest" | jq .

echo "5) dp latest (Nebula-like)"
curl -s "http://localhost:8002/dp/latest?tau=${TAU}&tau2=${TAU2}" | jq .

echo "6) privacy budget status"
curl -s "http://localhost:8002/privacy_budget_status" | jq .
