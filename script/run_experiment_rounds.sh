#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

ROUNDS="${ROUNDS:-10}"
BUILD_SERVICES="${BUILD_SERVICES:-1}"
TAU="${TAU:-3}"
TAU2="${TAU2:-3}"
CLIENT_TRAJ_SOURCE="${CLIENT_TRAJ_SOURCE:-synthetic}"
GEO_TRAJ_PATH="${GEO_TRAJ_PATH:-/app/experiments/geolife_tsip_ready_50u.jsonl}"
GEO_MAX_USERS="${GEO_MAX_USERS:-50}"
CLIENT_TOTAL="${CLIENT_TOTAL:-200}"
TSIP_USER_SCOPE="${TSIP_USER_SCOPE:-round}"
TSIP_AUTO_RESET_ON_EMPTY="${TSIP_AUTO_RESET_ON_EMPTY:-0}"
TSIP_MAX_GAP_WINDOWS="${TSIP_MAX_GAP_WINDOWS:-}"
TSIP_VERIFY_MODE="${TSIP_VERIFY_MODE:-}"
TSIP_CIRCUIT_PROFILE="${TSIP_CIRCUIT_PROFILE:-k6}"
TELEPORT_JUMP_M="${TELEPORT_JUMP_M:-5000}"
ATTACK_TYPE="${ATTACK_TYPE:-teleport}"
RESET_TSIP_RUNTIME="${RESET_TSIP_RUNTIME:-1}"
SHUFFLER_COMMITTEE_ENABLE="${SHUFFLER_COMMITTEE_ENABLE:-0}"
SYNC_CLIENT_RUNTIME_CODE="${SYNC_CLIENT_RUNTIME_CODE:-1}"
ZK_STEP_PROVER="${ZK_STEP_PROVER:-}"
TSIP_PROVER="${TSIP_PROVER:-}"
RAPIDSNARK_BIN="${RAPIDSNARK_BIN:-}"

# Real trajectory sources often have larger inter-point gaps than synthetic.
# If caller does not set TSIP_MAX_GAP_WINDOWS explicitly, use a safer default.
if [[ -z "${TSIP_MAX_GAP_WINDOWS}" ]]; then
  if [[ "$CLIENT_TRAJ_SOURCE" == "geolife" || "$CLIENT_TRAJ_SOURCE" == "tdrive" ]]; then
    TSIP_MAX_GAP_WINDOWS=12
  else
    TSIP_MAX_GAP_WINDOWS=2
  fi
fi
export TSIP_MAX_GAP_WINDOWS
if [[ -z "${WARMUP_ROUNDS:-}" ]]; then
  WARMUP_ROUNDS="${TSIP_ADWC_WINDOW_K:-6}"
fi

if ! [[ "$ROUNDS" =~ ^[0-9]+$ ]] || [[ "$ROUNDS" -le 0 ]]; then
  echo "error: ROUNDS must be a positive integer" >&2
  exit 1
fi
if ! [[ "$WARMUP_ROUNDS" =~ ^[0-9]+$ ]]; then
  echo "error: WARMUP_ROUNDS must be a non-negative integer" >&2
  exit 1
fi

mkdir -p experiments
TS="$(date +%Y%m%d_%H%M%S)"
OUT_CSV="experiments/round_metrics_${TS}.csv"
TMP_DIR="$(mktemp -d /tmp/risefl_exp.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "== Batch experiment =="
echo "rounds=${ROUNDS} tau=${TAU} tau2=${TAU2} build_services=${BUILD_SERVICES}"
echo "client_traj_source=${CLIENT_TRAJ_SOURCE} client_total=${CLIENT_TOTAL} tsip_user_scope=${TSIP_USER_SCOPE} warmup_rounds=${WARMUP_ROUNDS}"
echo "committee_enable=${SHUFFLER_COMMITTEE_ENABLE} attack_type=${ATTACK_TYPE} teleport_jump_m=${TELEPORT_JUMP_M}"
echo "tsip_verify_mode=${TSIP_VERIFY_MODE:-full}"
echo "tsip_max_gap_windows=${TSIP_MAX_GAP_WINDOWS}"
if [[ "$CLIENT_TRAJ_SOURCE" == "geolife" || "$CLIENT_TRAJ_SOURCE" == "tdrive" ]]; then
  echo "geo_traj_path=${GEO_TRAJ_PATH}"
  echo "geo_max_users=${GEO_MAX_USERS}"
fi

if [[ "${SHUFFLER_COMMITTEE_ENABLE}" == "1" ]]; then
  COMPOSE_PROFILE_ARGS=(--profile committee)
  START_SERVICES=(shuffler shuffler2 shuffler3 aggregator_a aggregator_r decoder client_sim)
  RESET_SERVICES=(shuffler shuffler2 shuffler3 client_sim)
else
  COMPOSE_PROFILE_ARGS=()
  START_SERVICES=(shuffler aggregator_a aggregator_r decoder client_sim)
  RESET_SERVICES=(shuffler client_sim)
fi

sync_client_runtime_code() {
  if [[ "${SYNC_CLIENT_RUNTIME_CODE}" != "1" ]]; then
    return
  fi
  local cid tsip_dir
  local shuffler_synced=()
  _safe_cp() {
    local src="$1"
    local dst="$2"
    if ! docker cp "$src" "$dst" >/dev/null 2>&1; then
      echo "[WARN] skip docker cp (likely bind-mounted): ${src} -> ${dst}" >&2
    fi
  }
  cid="$(docker compose ps -q client_sim 2>/dev/null || true)"
  tsip_dir="tsip_main_v3_${TSIP_CIRCUIT_PROFILE}"
  if [[ -z "$cid" ]]; then
    return
  fi
  _safe_cp "${ROOT_DIR}/client/sim/client.py" "${cid}:/app/client.py"
  _safe_cp "${ROOT_DIR}/common/tsip.py" "${cid}:/app/common/tsip.py"
  _safe_cp "${ROOT_DIR}/common/ea.py" "${cid}:/app/common/ea.py"
  docker compose exec -T client_sim sh -lc "mkdir -p /app/zk/poseidon2_bench/poseidon2_bench_js /app/zk/${tsip_dir}/${tsip_dir}_js /app/zk/tsip_step/tsip_step_js" >/dev/null || true

  # sync poseidon location-hash artifacts used by TSIP_LOC_HASH_MODE=poseidon2
  if [[ -f "${ROOT_DIR}/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm" ]]; then
    _safe_cp "${ROOT_DIR}/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm" "${cid}:/app/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm"
  fi
  if [[ -f "${ROOT_DIR}/zk/poseidon2_bench/poseidon2_bench_js/witness_calculator.js" ]]; then
    _safe_cp "${ROOT_DIR}/zk/poseidon2_bench/poseidon2_bench_js/witness_calculator.js" "${cid}:/app/zk/poseidon2_bench/poseidon2_bench_js/witness_calculator.js"
  fi
  if [[ -f "${ROOT_DIR}/zk/poseidon2_bench/poseidon2_bench_js/generate_witness.js" ]]; then
    _safe_cp "${ROOT_DIR}/zk/poseidon2_bench/poseidon2_bench_js/generate_witness.js" "${cid}:/app/zk/poseidon2_bench/poseidon2_bench_js/generate_witness.js"
  fi

  # sync TSIP/step proving artifacts used by client runtime
  if [[ -f "${ROOT_DIR}/zk/${tsip_dir}/${tsip_dir}_js/${tsip_dir}.wasm" ]]; then
    _safe_cp "${ROOT_DIR}/zk/${tsip_dir}/${tsip_dir}_js/${tsip_dir}.wasm" "${cid}:/app/zk/${tsip_dir}/${tsip_dir}_js/${tsip_dir}.wasm"
  fi
  if [[ -f "${ROOT_DIR}/zk/${tsip_dir}/${tsip_dir}_final.zkey" ]]; then
    _safe_cp "${ROOT_DIR}/zk/${tsip_dir}/${tsip_dir}_final.zkey" "${cid}:/app/zk/${tsip_dir}/${tsip_dir}_final.zkey"
  fi
  if [[ -f "${ROOT_DIR}/zk/tsip_step/tsip_step_js/tsip_step.wasm" ]]; then
    _safe_cp "${ROOT_DIR}/zk/tsip_step/tsip_step_js/tsip_step.wasm" "${cid}:/app/zk/tsip_step/tsip_step_js/tsip_step.wasm"
  fi
  if [[ -f "${ROOT_DIR}/zk/tsip_step/tsip_step_final.zkey" ]]; then
    _safe_cp "${ROOT_DIR}/zk/tsip_step/tsip_step_final.zkey" "${cid}:/app/zk/tsip_step/tsip_step_final.zkey"
  fi

  # If rapidsnark is explicitly requested, ensure binary exists in client_sim.
  if [[ "${ZK_STEP_PROVER}" == "rapidsnark" || "${TSIP_PROVER}" == "rapidsnark" ]]; then
    if [[ -f "/tmp/rapidsnark" ]]; then
      _safe_cp "/tmp/rapidsnark" "${cid}:/usr/local/bin/rapidsnark"
      docker compose exec -T client_sim sh -lc 'chmod +x /usr/local/bin/rapidsnark' >/dev/null || true
    elif docker compose exec -T client_sim sh -lc 'test -x /usr/local/bin/rapidsnark' >/dev/null 2>&1; then
      :
    else
      echo "[WARN] rapidsnark requested but not found in host (/tmp/rapidsnark) or client_sim (/usr/local/bin/rapidsnark)" >&2
    fi
  fi

  # Sync verifier keys to shuffler services as well. Client may use host-mounted
  # zkey while shuffler still has stale image vkey, which causes "invalid tsip proof".
  for svc in shuffler shuffler2 shuffler3; do
    local sid
    sid="$(docker compose ps -q "$svc" 2>/dev/null || true)"
    if [[ -z "$sid" ]]; then
      continue
    fi
    _safe_cp "${ROOT_DIR}/services/shuffler/app.py" "${sid}:/app/app.py"
    _safe_cp "${ROOT_DIR}/common/ea.py" "${sid}:/app/common/ea.py"
    docker compose exec -T "$svc" sh -lc "mkdir -p /app/common /app/zk/${tsip_dir} /app/zk/tsip_step" >/dev/null || true
    if [[ -f "${ROOT_DIR}/common/utils.py" ]]; then
      _safe_cp "${ROOT_DIR}/common/utils.py" "${sid}:/app/common/utils.py"
    fi
    if [[ -f "${ROOT_DIR}/common/tsip.py" ]]; then
      _safe_cp "${ROOT_DIR}/common/tsip.py" "${sid}:/app/common/tsip.py"
    fi
    if [[ -f "${ROOT_DIR}/common/committee.py" ]]; then
      _safe_cp "${ROOT_DIR}/common/committee.py" "${sid}:/app/common/committee.py"
    fi
    if [[ -f "${ROOT_DIR}/zk/${tsip_dir}/verification_key.json" ]]; then
      _safe_cp "${ROOT_DIR}/zk/${tsip_dir}/verification_key.json" "${sid}:/app/zk/${tsip_dir}/verification_key.json"
    fi
    if [[ -f "${ROOT_DIR}/zk/tsip_step/verification_key.json" ]]; then
      _safe_cp "${ROOT_DIR}/zk/tsip_step/verification_key.json" "${sid}:/app/zk/tsip_step/verification_key.json"
    fi
    shuffler_synced+=("$svc")
  done

  if [[ "${#shuffler_synced[@]}" -gt 0 ]]; then
    docker compose restart "${shuffler_synced[@]}" >/dev/null || true
    for svc in "${shuffler_synced[@]}"; do
      ready=0
      for _ in $(seq 1 30); do
        if docker compose exec -T "$svc" python -c \
          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3).read()" \
          >/dev/null 2>&1; then
          ready=1
          break
        fi
        sleep 1
      done
      if [[ "$ready" != "1" ]]; then
        echo "error: ${svc} failed to become healthy after runtime sync" >&2
        docker compose logs --tail=120 "$svc" >&2 || true
        return 1
      fi
    done
  fi
}

if [[ "$BUILD_SERVICES" == "1" ]]; then
  echo "bring up services with build..."
  docker compose "${COMPOSE_PROFILE_ARGS[@]}" up -d --build "${START_SERVICES[@]}" >/dev/null
else
  echo "bring up services without build..."
  docker compose "${COMPOSE_PROFILE_ARGS[@]}" up -d "${START_SERVICES[@]}" >/dev/null
fi
sync_client_runtime_code

if [[ "${RESET_TSIP_RUNTIME}" == "1" ]]; then
  if [[ "${SHUFFLER_COMMITTEE_ENABLE}" == "1" ]]; then
    echo "reset tsip runtime state (recreate shuffler/shuffler2/shuffler3/client_sim + clear client state)..."
  else
    echo "reset tsip runtime state (recreate shuffler/client_sim + clear client state)..."
  fi
  docker compose "${COMPOSE_PROFILE_ARGS[@]}" up -d --force-recreate "${RESET_SERVICES[@]}" >/dev/null
  sync_client_runtime_code
  docker compose exec -T client_sim rm -f /tmp/tsip_client_state.json >/dev/null || true
fi

CLIENT_EXTRA_ENV=()
if [[ -n "${ZK_STEP_PROVER}" ]]; then
  CLIENT_EXTRA_ENV+=(-e ZK_STEP_PROVER="$ZK_STEP_PROVER")
fi
if [[ -n "${TSIP_PROVER}" ]]; then
  CLIENT_EXTRA_ENV+=(-e TSIP_PROVER="$TSIP_PROVER")
fi
if [[ -n "${TSIP_VERIFY_MODE}" ]]; then
  CLIENT_EXTRA_ENV+=(-e TSIP_VERIFY_MODE="$TSIP_VERIFY_MODE")
fi
if [[ -n "${RAPIDSNARK_BIN}" ]]; then
  CLIENT_EXTRA_ENV+=(-e RAPIDSNARK_BIN="$RAPIDSNARK_BIN")
fi

echo "round_idx,round_id,total,valid_clients,rejected,malicious_total,malicious_reject_rate,false_reject_rate,received_A,received_R,cells_final,dp_ok,cells_kept_post,dp_error,gradual_drift_offset_avg_m,gradual_drift_offset_max_m,gradual_drift_terminal_offset_avg_m,gradual_drift_terminal_offset_max_m" >"$OUT_CSV"

if [[ "$WARMUP_ROUNDS" -gt 0 ]]; then
  for i in $(seq 1 "$WARMUP_ROUNDS"); do
    echo "---- warmup ${i}/${WARMUP_ROUNDS} ----"
    WARMUP_LOG="${TMP_DIR}/warmup_${i}.log"
    if ! docker compose exec -T \
      -e CLIENT_TRAJ_SOURCE="$CLIENT_TRAJ_SOURCE" \
      -e GEO_TRAJ_PATH="$GEO_TRAJ_PATH" \
      -e GEO_MAX_USERS="$GEO_MAX_USERS" \
      -e CLIENT_TOTAL="$CLIENT_TOTAL" \
      -e TSIP_USER_SCOPE="$TSIP_USER_SCOPE" \
      -e TSIP_AUTO_RESET_ON_EMPTY="$TSIP_AUTO_RESET_ON_EMPTY" \
      -e TELEPORT_JUMP_M="$TELEPORT_JUMP_M" \
      -e ATTACK_TYPE="$ATTACK_TYPE" \
      "${CLIENT_EXTRA_ENV[@]}" \
      client_sim python client.py >"$WARMUP_LOG"; then
      echo "error: warmup round failed" >&2
      tail -n 40 "$WARMUP_LOG" >&2 || true
      exit 1
    fi
    grep 'summary total=' "$WARMUP_LOG" | tail -n 1 || true
    grep 'reject_reasons_top=' "$WARMUP_LOG" | tail -n 1 || true
    grep 'local_tsip_prove_fail_honest_top=' "$WARMUP_LOG" | tail -n 1 || true
    grep 'local_tsip_prove_fail_malicious_top=' "$WARMUP_LOG" | tail -n 1 || true
    grep 'gradual_drift_offset_avg_m=' "$WARMUP_LOG" | tail -n 1 || true
    grep 'gradual_drift_terminal_offset_avg_m=' "$WARMUP_LOG" | tail -n 1 || true
  done
fi

for i in $(seq 1 "$ROUNDS"); do
  echo "---- round ${i}/${ROUNDS} ----"
  CLIENT_LOG="${TMP_DIR}/client_${i}.log"
  if ! docker compose exec -T \
    -e CLIENT_TRAJ_SOURCE="$CLIENT_TRAJ_SOURCE" \
    -e GEO_TRAJ_PATH="$GEO_TRAJ_PATH" \
    -e GEO_MAX_USERS="$GEO_MAX_USERS" \
    -e CLIENT_TOTAL="$CLIENT_TOTAL" \
    -e TSIP_USER_SCOPE="$TSIP_USER_SCOPE" \
    -e TSIP_AUTO_RESET_ON_EMPTY="$TSIP_AUTO_RESET_ON_EMPTY" \
    -e TELEPORT_JUMP_M="$TELEPORT_JUMP_M" \
    -e ATTACK_TYPE="$ATTACK_TYPE" \
    "${CLIENT_EXTRA_ENV[@]}" \
    client_sim python client.py >"$CLIENT_LOG"; then
    echo "error: client round failed in round ${i}" >&2
    tail -n 40 "$CLIENT_LOG" >&2 || true
    exit 1
  fi

  SUMMARY_LINE="$(grep 'summary total=' "$CLIENT_LOG" | tail -n 1 || true)"
  if [[ -z "$SUMMARY_LINE" ]]; then
    echo "error: summary line not found in round ${i}" >&2
    tail -n 20 "$CLIENT_LOG" >&2 || true
    exit 1
  fi
  echo "$SUMMARY_LINE"
  grep 'reject_reasons_top=' "$CLIENT_LOG" | tail -n 1 || true
  grep 'local_tsip_prove_fail_honest_top=' "$CLIENT_LOG" | tail -n 1 || true
  grep 'local_tsip_prove_fail_malicious_top=' "$CLIENT_LOG" | tail -n 1 || true
  DRIFT_LINE="$(grep 'gradual_drift_offset_avg_m=' "$CLIENT_LOG" | tail -n 1 || true)"
  if [[ -n "$DRIFT_LINE" ]]; then
    echo "$DRIFT_LINE"
  fi
  TERMINAL_DRIFT_LINE="$(grep 'gradual_drift_terminal_offset_avg_m=' "$CLIENT_LOG" | tail -n 1 || true)"
  if [[ -n "$TERMINAL_DRIFT_LINE" ]]; then
    echo "$TERMINAL_DRIFT_LINE"
  fi

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
  gradual_drift_offset_avg_m=""
  gradual_drift_offset_max_m=""
  gradual_drift_terminal_offset_avg_m=""
  gradual_drift_terminal_offset_max_m=""
  if [[ -n "$DRIFT_LINE" ]]; then
    gradual_drift_offset_avg_m="$(extract_metric "gradual_drift_offset_avg_m" "$DRIFT_LINE")"
    gradual_drift_offset_max_m="$(extract_metric "gradual_drift_offset_max_m" "$DRIFT_LINE")"
  fi
  if [[ -n "$TERMINAL_DRIFT_LINE" ]]; then
    gradual_drift_terminal_offset_avg_m="$(extract_metric "gradual_drift_terminal_offset_avg_m" "$TERMINAL_DRIFT_LINE")"
    gradual_drift_terminal_offset_max_m="$(extract_metric "gradual_drift_terminal_offset_max_m" "$TERMINAL_DRIFT_LINE")"
  fi

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

  echo "${i},${round_id},${total},${valid_clients},${rejected},${malicious_total},${malicious_reject_rate},${false_reject_rate},${received_A},${received_R},${cells_final},${dp_ok},${cells_kept_post},\"${dp_error}\",${gradual_drift_offset_avg_m},${gradual_drift_offset_max_m},${gradual_drift_terminal_offset_avg_m},${gradual_drift_terminal_offset_max_m}" >>"$OUT_CSV"
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
    if ($15 != "") {
      sum_drift_avg += $15
      n_drift += 1
    }
    if ($16 != "") {
      if ($16 > max_drift) {
        max_drift = $16
      }
    }
    if ($17 != "") {
      sum_terminal_drift_avg += $17
      n_terminal_drift += 1
    }
    if ($18 != "") {
      if ($18 > max_terminal_drift) {
        max_terminal_drift = $18
      }
    }
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
    if (n_drift > 0) {
      printf("gradual_drift_offset_avg_m=%.2f\n", sum_drift_avg/n_drift)
      printf("gradual_drift_offset_max_m=%.2f\n", max_drift)
    }
    if (n_terminal_drift > 0) {
      printf("gradual_drift_terminal_offset_avg_m=%.2f\n", sum_terminal_drift_avg/n_terminal_drift)
      printf("gradual_drift_terminal_offset_max_m=%.2f\n", max_terminal_drift)
    }
  }
' "$OUT_CSV"

echo
echo "saved: $OUT_CSV"
