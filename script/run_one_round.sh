#!/usr/bin/env bash
set -euo pipefail

EXPECTED=${EXPECTED:-auto}
TAU=3
TAU2=3
CLIENT_TRAJ_SOURCE="${CLIENT_TRAJ_SOURCE:-synthetic}"
GEO_TRAJ_PATH="${GEO_TRAJ_PATH:-/app/experiments/geolife_tsip_ready_50u.jsonl}"
GEO_MAX_USERS="${GEO_MAX_USERS:-50}"
CLIENT_TOTAL="${CLIENT_TOTAL:-200}"
TSIP_USER_SCOPE="${TSIP_USER_SCOPE:-stable}"
TSIP_AUTO_RESET_ON_EMPTY="${TSIP_AUTO_RESET_ON_EMPTY:-0}"
TSIP_MAX_GAP_WINDOWS="${TSIP_MAX_GAP_WINDOWS:-}"
TSIP_CIRCUIT_PROFILE="${TSIP_CIRCUIT_PROFILE:-k6}"
SYNC_CLIENT_RUNTIME_CODE="${SYNC_CLIENT_RUNTIME_CODE:-1}"
ZK_STEP_PROVER="${ZK_STEP_PROVER:-}"
TSIP_PROVER="${TSIP_PROVER:-}"
RAPIDSNARK_BIN="${RAPIDSNARK_BIN:-}"

if [[ -z "${TSIP_MAX_GAP_WINDOWS}" ]]; then
  if [[ "${CLIENT_TRAJ_SOURCE}" == "geolife" || "${CLIENT_TRAJ_SOURCE}" == "tdrive" ]]; then
    TSIP_MAX_GAP_WINDOWS=12
  else
    TSIP_MAX_GAP_WINDOWS=2
  fi
fi
export TSIP_MAX_GAP_WINDOWS

sync_client_runtime_code() {
  if [[ "${SYNC_CLIENT_RUNTIME_CODE}" != "1" ]]; then
    return
  fi
  local root_dir cid tsip_dir
  _safe_cp() {
    local src="$1"
    local dst="$2"
    if ! docker cp "$src" "$dst" >/dev/null 2>&1; then
      echo "[WARN] skip docker cp (likely bind-mounted): ${src} -> ${dst}" >&2
    fi
  }
  root_dir="$(cd "$(dirname "$0")/.." && pwd)"
  tsip_dir="tsip_main_v3_${TSIP_CIRCUIT_PROFILE}"
  cid="$(docker compose ps -q client_sim 2>/dev/null || true)"
  if [[ -z "$cid" ]]; then
    return
  fi
  _safe_cp "${root_dir}/client/sim/client.py" "${cid}:/app/client.py"
  _safe_cp "${root_dir}/common/tsip.py" "${cid}:/app/common/tsip.py"
  _safe_cp "${root_dir}/common/ea.py" "${cid}:/app/common/ea.py"
  docker compose exec -T client_sim sh -lc "mkdir -p /app/zk/poseidon2_bench/poseidon2_bench_js /app/zk/${tsip_dir}/${tsip_dir}_js /app/zk/tsip_step/tsip_step_js" >/dev/null || true
  if [[ -f "${root_dir}/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm" ]]; then
    _safe_cp "${root_dir}/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm" "${cid}:/app/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm"
  fi
  if [[ -f "${root_dir}/zk/poseidon2_bench/poseidon2_bench_js/witness_calculator.js" ]]; then
    _safe_cp "${root_dir}/zk/poseidon2_bench/poseidon2_bench_js/witness_calculator.js" "${cid}:/app/zk/poseidon2_bench/poseidon2_bench_js/witness_calculator.js"
  fi
  if [[ -f "${root_dir}/zk/poseidon2_bench/poseidon2_bench_js/generate_witness.js" ]]; then
    _safe_cp "${root_dir}/zk/poseidon2_bench/poseidon2_bench_js/generate_witness.js" "${cid}:/app/zk/poseidon2_bench/poseidon2_bench_js/generate_witness.js"
  fi
  if [[ -f "${root_dir}/zk/${tsip_dir}/${tsip_dir}_js/${tsip_dir}.wasm" ]]; then
    _safe_cp "${root_dir}/zk/${tsip_dir}/${tsip_dir}_js/${tsip_dir}.wasm" "${cid}:/app/zk/${tsip_dir}/${tsip_dir}_js/${tsip_dir}.wasm"
  fi
  if [[ -f "${root_dir}/zk/${tsip_dir}/${tsip_dir}_final.zkey" ]]; then
    _safe_cp "${root_dir}/zk/${tsip_dir}/${tsip_dir}_final.zkey" "${cid}:/app/zk/${tsip_dir}/${tsip_dir}_final.zkey"
  fi
  if [[ -f "${root_dir}/zk/tsip_step/tsip_step_js/tsip_step.wasm" ]]; then
    _safe_cp "${root_dir}/zk/tsip_step/tsip_step_js/tsip_step.wasm" "${cid}:/app/zk/tsip_step/tsip_step_js/tsip_step.wasm"
  fi
  if [[ -f "${root_dir}/zk/tsip_step/tsip_step_final.zkey" ]]; then
    _safe_cp "${root_dir}/zk/tsip_step/tsip_step_final.zkey" "${cid}:/app/zk/tsip_step/tsip_step_final.zkey"
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

  # Keep verifier keys in shuffler services aligned with host zk artifacts.
  for svc in shuffler shuffler2 shuffler3; do
    local sid
    sid="$(docker compose ps -q "$svc" 2>/dev/null || true)"
    if [[ -z "$sid" ]]; then
      continue
    fi
    _safe_cp "${root_dir}/common/ea.py" "${sid}:/app/common/ea.py"
    docker compose exec -T "$svc" sh -lc "mkdir -p /app/common /app/zk/${tsip_dir} /app/zk/tsip_step" >/dev/null || true
    if [[ -f "${root_dir}/zk/${tsip_dir}/verification_key.json" ]]; then
      _safe_cp "${root_dir}/zk/${tsip_dir}/verification_key.json" "${sid}:/app/zk/${tsip_dir}/verification_key.json"
    fi
    if [[ -f "${root_dir}/zk/tsip_step/verification_key.json" ]]; then
      _safe_cp "${root_dir}/zk/tsip_step/verification_key.json" "${sid}:/app/zk/tsip_step/verification_key.json"
    fi
  done
}

CLIENT_EXTRA_ENV=()
if [[ -n "${ZK_STEP_PROVER}" ]]; then
  CLIENT_EXTRA_ENV+=(-e ZK_STEP_PROVER="${ZK_STEP_PROVER}")
fi
if [[ -n "${TSIP_PROVER}" ]]; then
  CLIENT_EXTRA_ENV+=(-e TSIP_PROVER="${TSIP_PROVER}")
fi
if [[ -n "${RAPIDSNARK_BIN}" ]]; then
  CLIENT_EXTRA_ENV+=(-e RAPIDSNARK_BIN="${RAPIDSNARK_BIN}")
fi

echo "1) run client"
sync_client_runtime_code
docker compose exec -T \
  -e CLIENT_TRAJ_SOURCE="${CLIENT_TRAJ_SOURCE}" \
  -e GEO_TRAJ_PATH="${GEO_TRAJ_PATH}" \
  -e GEO_MAX_USERS="${GEO_MAX_USERS}" \
  -e CLIENT_TOTAL="${CLIENT_TOTAL}" \
  -e TSIP_USER_SCOPE="${TSIP_USER_SCOPE}" \
  -e TSIP_AUTO_RESET_ON_EMPTY="${TSIP_AUTO_RESET_ON_EMPTY}" \
  "${CLIENT_EXTRA_ENV[@]}" \
  client_sim python client.py

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
RECEIVED_A="$(echo "${STATUS_JSON}" | jq -r '.received_A // 0')"
RECEIVED_R="$(echo "${STATUS_JSON}" | jq -r '.received_R // 0')"
if [[ "${RECEIVED_A}" =~ ^[0-9]+$ && "${RECEIVED_R}" =~ ^[0-9]+$ ]]; then
  if (( RECEIVED_A < RECEIVED_R )); then
    RECEIVED_MIN="${RECEIVED_A}"
  else
    RECEIVED_MIN="${RECEIVED_R}"
  fi
  if [[ "${EXPECTED_RECON}" =~ ^[0-9]+$ ]] && (( EXPECTED_RECON > RECEIVED_MIN )); then
    echo "adjust expected from ${EXPECTED_RECON} to ${RECEIVED_MIN} (min(received_A, received_R))"
    EXPECTED_RECON="${RECEIVED_MIN}"
  fi
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
