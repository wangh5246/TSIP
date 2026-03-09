#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

ROUNDS="${ROUNDS:-10}"
BUILD_SERVICES="${BUILD_SERVICES:-1}"
TAU="${TAU:-3}"
TAU2="${TAU2:-3}"

if ! [[ "$ROUNDS" =~ ^[0-9]+$ ]] || [[ "$ROUNDS" -le 0 ]]; then
  echo "error: ROUNDS must be a positive integer" >&2
  exit 1
fi

mkdir -p experiments
TS="$(date +%Y%m%d_%H%M%S)"
OUT_CSV="experiments/round_metrics_${TS}.csv"
TMP_DIR="$(mktemp -d /tmp/risefl_exp.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "== Batch experiment =="
echo "rounds=${ROUNDS} tau=${TAU} tau2=${TAU2} build_services=${BUILD_SERVICES}"

if [[ "$BUILD_SERVICES" == "1" ]]; then
  echo "bring up services with build..."
  docker compose up -d --build shuffler aggregator_a aggregator_r decoder client_sim >/dev/null
else
  echo "bring up services without build..."
  docker compose up -d shuffler aggregator_a aggregator_r decoder client_sim >/dev/null
fi

echo "round_idx,round_id,total,valid_clients,rejected,malicious_total,malicious_reject_rate,false_reject_rate,received_A,received_R,cells_final,dp_ok,cells_kept_post,dp_error" >"$OUT_CSV"

for i in $(seq 1 "$ROUNDS"); do
  echo "---- round ${i}/${ROUNDS} ----"
  CLIENT_LOG="${TMP_DIR}/client_${i}.log"
  docker compose exec -T client_sim python client.py >"$CLIENT_LOG"

  SUMMARY_LINE="$(grep 'summary total=' "$CLIENT_LOG" | tail -n 1 || true)"
  if [[ -z "$SUMMARY_LINE" ]]; then
    echo "error: summary line not found in round ${i}" >&2
    tail -n 20 "$CLIENT_LOG" >&2 || true
    exit 1
  fi
  echo "$SUMMARY_LINE"

  extract_metric() {
    local key="$1"
    local line="$2"
    echo "$line" | awk -v k="${key}" '{
      for (i=1; i<=NF; i++) {
        if ($i == k "=") {
          print $(i+1)
          exit
        }
        if (index($i, k "=") == 1 && length($i) > length(k) + 1) {
          v = $i
          sub(k "=", "", v)
          print v
          exit
        }
      }
    }'
  }

  total="$(extract_metric "total" "$SUMMARY_LINE")"
  valid_clients="$(extract_metric "valid_clients" "$SUMMARY_LINE")"
  rejected="$(extract_metric "rejected" "$SUMMARY_LINE")"
  malicious_total="$(extract_metric "malicious_total" "$SUMMARY_LINE")"
  malicious_reject_rate="$(extract_metric "malicious_reject_rate" "$SUMMARY_LINE")"
  false_reject_rate="$(extract_metric "false_reject_rate" "$SUMMARY_LINE")"

  STATUS_JSON="$(curl -s "http://localhost:8002/status_latest")"
  round_id="$(echo "$STATUS_JSON" | jq -r '.round_id // 0')"
  received_A="$(echo "$STATUS_JSON" | jq -r '.received_A // 0')"
  received_R="$(echo "$STATUS_JSON" | jq -r '.received_R // 0')"
  if [[ "$received_A" =~ ^[0-9]+$ && "$received_R" =~ ^[0-9]+$ ]]; then
    if (( received_A < received_R )); then
      expected="$received_A"
    else
      expected="$received_R"
    fi
  else
    expected=0
  fi

  RECON_JSON="$(curl -s -X POST "http://localhost:8010/secure/reconstruct_latest?expected=${expected}")"
  recon_ok="$(echo "$RECON_JSON" | jq -r '.ok // false')"
  if [[ "$recon_ok" != "true" ]]; then
    echo "error: secure reconstruct failed in round ${i}" >&2
    echo "$RECON_JSON" | jq . >&2
    exit 1
  fi
  cells_final="$(echo "$RECON_JSON" | jq -r '.cells_in_final_map // 0')"

  curl -s -X POST "http://localhost:8002/privacy_budget_reset?round_id=${round_id}" >/dev/null
  DP_JSON="$(curl -s "http://localhost:8002/dp/latest?tau=${TAU}&tau2=${TAU2}")"
  dp_error="$(echo "$DP_JSON" | jq -r '.error // ""')"
  if [[ -z "$dp_error" ]]; then
    dp_ok="true"
  else
    dp_ok="false"
  fi
  cells_kept_post="$(echo "$DP_JSON" | jq -r '.cells_kept_post // 0')"

  echo "${i},${round_id},${total},${valid_clients},${rejected},${malicious_total},${malicious_reject_rate},${false_reject_rate},${received_A},${received_R},${cells_final},${dp_ok},${cells_kept_post},\"${dp_error}\"" >>"$OUT_CSV"
done

echo
echo "== Summary =="
awk -F',' '
  NR==1 {next}
  {
    n += 1
    sum_valid += $4
    sum_rej += $5
    sum_mal += $6
    sum_mrr += $7
    sum_frr += $8
    sum_cells += $11
    sum_dp += $13
  }
  END {
    if (n == 0) {
      print "no data"
      exit 1
    }
    printf("rounds=%d\n", n)
    printf("avg_valid_clients=%.2f\n", sum_valid/n)
    printf("avg_rejected=%.2f\n", sum_rej/n)
    printf("avg_malicious_total=%.2f\n", sum_mal/n)
    printf("avg_malicious_reject_rate=%.4f\n", sum_mrr/n)
    printf("avg_false_reject_rate=%.4f\n", sum_frr/n)
    printf("avg_cells_final=%.2f\n", sum_cells/n)
    printf("avg_dp_cells_kept_post=%.2f\n", sum_dp/n)
  }
' "$OUT_CSV"

echo
echo "saved: $OUT_CSV"
