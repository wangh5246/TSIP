#!/usr/bin/env bash
# =============================================================================
# run_utility_sweep.sh
#
# Utility sweep for TSIP paper – Experiment 2 (Privacy-Utility Tradeoff).
#
# What it does
# ------------
# For each (MODE × MALICIOUS_RATE) condition:
#   1. Reset services & client TSIP state
#   2. Run WARMUP_ROUNDS warmup rounds (not measured)
#   3. Run ROUNDS measured rounds; after each round:
#        a. Capture dump_latest_dp JSON → experiments/utility_dumps/
#        b. Append round stats to a CSV
# After all conditions:
#   4. Call compute_system_utility.py to compute Jaccard/RMSE vs ground truth
#
# Modes (TSIP_MODE env var):
#   full        – Full TSIP (TSIP_ENABLE=1, TSIP_VERIFY_MODE=full)
#   commit_only – Commitment chain only (TSIP_ENABLE=1, TSIP_VERIFY_MODE=commitment_only)
#   no_integ    – No integrity (TSIP_ENABLE=0)
#
# Usage
# -----
#   # Quick local test (1 condition, 2 rounds):
#   ROUNDS=2 MALICIOUS_RATES="0.0 0.1" TSIP_MODES="full" \
#   bash experiments/run_utility_sweep.sh
#
#   # Full sweep (server):
#   ROUNDS=10 MALICIOUS_RATES="0.0 0.1 0.2 0.3 0.5" \
#   TSIP_MODES="full commit_only no_integ" \
#   bash experiments/run_utility_sweep.sh
#
# Important: set PRP_ENABLE=0 (default here) so dump_latest_dp returns
# original cell_ids that can be compared directly to ground truth.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# ── configurable parameters ───────────────────────────────────────────────────
ROUNDS="${ROUNDS:-10}"
WARMUP_ROUNDS="${WARMUP_ROUNDS:-1}"
CLIENT_TOTAL="${CLIENT_TOTAL:-50}"
# Use GeoLife by default: T-Drive coordinates are outside the 10km×10km grid
# and get clamped to grid corners, making utility measurement unreliable.
CLIENT_TRAJ_SOURCE="${CLIENT_TRAJ_SOURCE:-geolife}"
GEO_TRAJ_PATH="${GEO_TRAJ_PATH:-/app/experiments/geolife_tsip_ready_50u.jsonl}"
GEO_MAX_USERS="${GEO_MAX_USERS:-50}"
ATTACK_TYPE="${ATTACK_TYPE:-boundary_teleport}"
TELEPORT_JUMP_M="${TELEPORT_JUMP_M:-7200}"
TSIP_USER_SCOPE="${TSIP_USER_SCOPE:-stable}"
MALICIOUS_SCOPE="${MALICIOUS_SCOPE:-stable}"
TAU="${TAU:-3}"
TAU2="${TAU2:-3}"
EPSILON="${EPSILON:-1.0}"
BUILD_SERVICES="${BUILD_SERVICES:-0}"
TSIP_PROVER="${TSIP_PROVER:-}"
ZK_STEP_PROVER="${ZK_STEP_PROVER:-}"
RAPIDSNARK_BIN="${RAPIDSNARK_BIN:-}"

# TSIP_MODES: space-separated list of: full commit_only no_integ
TSIP_MODES="${TSIP_MODES:-full commit_only no_integ}"
# MALICIOUS_RATES: space-separated float list
MALICIOUS_RATES="${MALICIOUS_RATES:-0.0 0.1 0.2 0.3 0.5}"

# ── output paths ──────────────────────────────────────────────────────────────
TS="$(date +%Y%m%d_%H%M%S)"
DUMP_DIR="${ROOT_DIR}/experiments/utility_dumps/${TS}"
OUT_CSV="${ROOT_DIR}/experiments/utility_sweep_${TS}.csv"
mkdir -p "${DUMP_DIR}"

echo "============================================================"
echo "  TSIP Utility Sweep – ${TS}"
echo "  modes   : ${TSIP_MODES}"
echo "  mal rates: ${MALICIOUS_RATES}"
echo "  rounds  : ${ROUNDS} (+${WARMUP_ROUNDS} warmup)"
echo "  dataset : ${CLIENT_TRAJ_SOURCE}"
echo "  dump dir: ${DUMP_DIR}"
echo "============================================================"

# Write CSV header
echo "mode,malicious_rate,round_idx,round_id,total,valid_clients,rejected,\
malicious_total,malicious_reject_rate,false_reject_rate,\
dump_file,cells_kept_pre,cells_kept_post" > "${OUT_CSV}"

# ── helpers ───────────────────────────────────────────────────────────────────

extract_metric() {
    local key="$1"
    local line="$2"
    echo "$line" | awk -v k="${key}" '{
        for (i=1; i<=NF; i++) {
            if ($i == k"=") { print $(i+1); exit }
            if (index($i, k"=") == 1 && length($i) > length(k)+1) {
                v=$i; sub(k"=","",v); print v; exit
            }
        }
    }'
}

reset_services() {
    local mode="$1"
    local mal_rate="$2"
    echo "  [reset] mode=${mode} mal_rate=${mal_rate}"

    # ── Export shuffler env vars BEFORE force-recreate so docker-compose
    #    picks them up from the shell environment.
    #    Key: always disable ZK_STEP and PROOF (not used in utility sweep).
    export SHUFFLER_ZK_STEP_ENABLE=0
    export SHUFFLER_PROOF_ENABLE=0
    export SHUFFLER_TSIP_ENABLE=0
    export TSIP_VERIFY_MODE=full

    case "$mode" in
        full)
            export SHUFFLER_TSIP_ENABLE=1
            export TSIP_VERIFY_MODE=full
            ;;
        commit_only)
            export SHUFFLER_TSIP_ENABLE=1
            export TSIP_VERIFY_MODE=commitment_only
            ;;
        no_integ)
            export SHUFFLER_TSIP_ENABLE=0
            ;;
    esac

    # Force-recreate shuffler (picks up new env vars above) and client_sim
    docker compose up -d --force-recreate shuffler client_sim >/dev/null 2>&1

    # Sync latest source code into containers (handles bind-mount and image modes)
    local SHUFFLER_CID CLIENT_CID
    SHUFFLER_CID="$(docker compose ps -q shuffler 2>/dev/null || true)"
    CLIENT_CID="$(docker compose ps -q client_sim 2>/dev/null || true)"

    if [[ -n "$SHUFFLER_CID" ]]; then
        docker cp "${ROOT_DIR}/services/shuffler/app.py" "${SHUFFLER_CID}:/app/app.py" 2>/dev/null || true
        docker cp "${ROOT_DIR}/common/tsip.py"           "${SHUFFLER_CID}:/app/common/tsip.py" 2>/dev/null || true
        docker cp "${ROOT_DIR}/common/utils.py"          "${SHUFFLER_CID}:/app/common/utils.py" 2>/dev/null || true
        docker compose restart shuffler >/dev/null 2>&1
        echo -n "  [wait] shuffler health "
        for _ in $(seq 1 40); do
            if docker compose exec -T shuffler python -c \
               "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=3).read()" \
               >/dev/null 2>&1; then echo " OK"; break; fi
            echo -n "."
            sleep 1
        done
    fi

    if [[ -n "$CLIENT_CID" ]]; then
        docker cp "${ROOT_DIR}/client/sim/client.py" "${CLIENT_CID}:/app/client.py" 2>/dev/null || true
        docker cp "${ROOT_DIR}/common/tsip.py"       "${CLIENT_CID}:/app/common/tsip.py" 2>/dev/null || true
        docker compose exec -T client_sim rm -f /tmp/tsip_client_state.json >/dev/null 2>&1 || true
    fi
}

mode_to_env() {
    local mode="$1"
    case "$mode" in
        full)
            echo "SHUFFLER_TSIP_ENABLE=1 CLIENT_TSIP_ENABLE=1 TSIP_VERIFY_MODE=full"
            ;;
        commit_only)
            echo "SHUFFLER_TSIP_ENABLE=1 CLIENT_TSIP_ENABLE=1 TSIP_VERIFY_MODE=commitment_only"
            ;;
        no_integ)
            echo "SHUFFLER_TSIP_ENABLE=0 CLIENT_TSIP_ENABLE=0 TSIP_VERIFY_MODE=full"
            ;;
        *)
            echo "SHUFFLER_TSIP_ENABLE=0 CLIENT_TSIP_ENABLE=0 TSIP_VERIFY_MODE=full"
            ;;
    esac
}

run_one_round() {
    # Usage: run_one_round <mode> <mal_rate> <round_idx> <is_warmup>
    local mode="$1"
    local mal_rate="$2"
    local ridx="$3"
    local is_warmup="${4:-0}"

    # Build env array for docker compose exec
    local ENV_VARS=()
    ENV_VARS+=(-e CLIENT_TRAJ_SOURCE="${CLIENT_TRAJ_SOURCE}")
    ENV_VARS+=(-e GEO_TRAJ_PATH="${GEO_TRAJ_PATH}")
    ENV_VARS+=(-e GEO_MAX_USERS="${GEO_MAX_USERS}")
    ENV_VARS+=(-e CLIENT_TOTAL="${CLIENT_TOTAL}")
    ENV_VARS+=(-e TSIP_USER_SCOPE="${TSIP_USER_SCOPE}")
    ENV_VARS+=(-e MALICIOUS_SCOPE="${MALICIOUS_SCOPE}")
    ENV_VARS+=(-e MALICIOUS_RATE="${mal_rate}")
    ENV_VARS+=(-e ATTACK_TYPE="${ATTACK_TYPE}")
    ENV_VARS+=(-e TELEPORT_JUMP_M="${TELEPORT_JUMP_M}")
    ENV_VARS+=(-e PRP_ENABLE=0)          # ← key: raw cell_ids for utility comparison

    # TSIP mode env
    case "$mode" in
        full)
            ENV_VARS+=(-e TSIP_ENABLE=1)
            ENV_VARS+=(-e TSIP_VERIFY_MODE=full)
            ;;
        commit_only)
            ENV_VARS+=(-e TSIP_ENABLE=1)
            ENV_VARS+=(-e TSIP_VERIFY_MODE=commitment_only)
            ;;
        no_integ)
            ENV_VARS+=(-e TSIP_ENABLE=0)
            ;;
    esac

    [[ -n "${TSIP_PROVER}"    ]] && ENV_VARS+=(-e TSIP_PROVER="${TSIP_PROVER}")
    [[ -n "${ZK_STEP_PROVER}" ]] && ENV_VARS+=(-e ZK_STEP_PROVER="${ZK_STEP_PROVER}")
    [[ -n "${RAPIDSNARK_BIN}" ]] && ENV_VARS+=(-e RAPIDSNARK_BIN="${RAPIDSNARK_BIN}")

    local LOG_FILE
    LOG_FILE="$(mktemp /tmp/risefl_util_XXXXXX.log)"
    docker compose exec -T "${ENV_VARS[@]}" client_sim python client.py > "${LOG_FILE}" 2>&1
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "  [error] round ${ridx} client failed (rc=${rc})" >&2
        tail -20 "${LOG_FILE}" >&2
        rm -f "${LOG_FILE}"
        return 1
    fi

    local SUMMARY_LINE
    SUMMARY_LINE="$(grep 'summary total=' "${LOG_FILE}" | tail -n1 || true)"
    if [[ -z "$SUMMARY_LINE" ]]; then
        echo "  [error] no summary line in round ${ridx}" >&2
        tail -10 "${LOG_FILE}" >&2
        rm -f "${LOG_FILE}"
        return 1
    fi
    rm -f "${LOG_FILE}"

    if [[ "$is_warmup" == "1" ]]; then
        echo "    [warmup ${ridx}] ${SUMMARY_LINE}"
        return 0
    fi

    echo "    [round ${ridx}] ${SUMMARY_LINE}"

    # ── grab round stats ──────────────────────────────────────────────────────
    local total valid_clients rejected malicious_total malicious_reject_rate false_reject_rate
    total="$(extract_metric "total" "$SUMMARY_LINE")"
    valid_clients="$(extract_metric "valid_clients" "$SUMMARY_LINE")"
    rejected="$(extract_metric "rejected" "$SUMMARY_LINE")"
    malicious_total="$(extract_metric "malicious_total" "$SUMMARY_LINE")"
    malicious_reject_rate="$(extract_metric "malicious_reject_rate" "$SUMMARY_LINE")"
    false_reject_rate="$(extract_metric "false_reject_rate" "$SUMMARY_LINE")"

    # ── wait for shuffler flush (FLUSH_SECONDS=2 default) ────────────────────
    sleep 3

    # ── get round_id from aggregator ──────────────────────────────────────────
    local STATUS_JSON round_id received_A received_R expected
    STATUS_JSON="$(curl -s "http://localhost:8002/status_latest")"
    round_id="$(echo "$STATUS_JSON" | jq -r '.round_id // 0')"
    received_A="$(echo "$STATUS_JSON" | jq -r '.received_A // 0')"
    received_R="$(echo "$STATUS_JSON" | jq -r '.received_R // 0')"
    if [[ "$received_A" =~ ^[0-9]+$ && "$received_R" =~ ^[0-9]+$ ]]; then
        expected=$((received_A < received_R ? received_A : received_R))
    else
        expected=0
    fi

    # ── reconstruct ───────────────────────────────────────────────────────────
    local RECON_JSON recon_ok
    RECON_JSON="$(curl -s -X POST "http://localhost:8010/secure/reconstruct_latest?expected=${expected}")"
    recon_ok="$(echo "$RECON_JSON" | jq -r '.ok // false')"
    if [[ "$recon_ok" != "true" ]]; then
        echo "  [warn] reconstruct failed in round ${ridx}: $(echo "$RECON_JSON" | jq -c .)" >&2
    fi

    # ── reset privacy budget ──────────────────────────────────────────────────
    curl -s -X POST "http://localhost:8002/privacy_budget_reset?round_id=${round_id}" >/dev/null

    # ── dump DP output ────────────────────────────────────────────────────────
    local DUMP_FILE="${DUMP_DIR}/${mode}_mal${mal_rate}_r${ridx}.json"
    curl -s "http://localhost:8002/dump_latest_dp?epsilon=${EPSILON}&tau=${TAU}&tau2=${TAU2}" \
        > "${DUMP_FILE}"

    # Check dump succeeded
    local dump_ok
    dump_ok="$(jq -r '.ok // true' "${DUMP_FILE}" 2>/dev/null || echo "false")"
    if echo "${DUMP_FILE}" | xargs jq -e '.error' >/dev/null 2>&1; then
        echo "  [warn] dump error: $(jq -r '.error' "${DUMP_FILE}")" >&2
    fi

    local cells_kept_pre cells_kept_post
    cells_kept_pre="$(jq -r '.cells_kept_pre // 0' "${DUMP_FILE}" 2>/dev/null || echo 0)"
    cells_kept_post="$(jq -r '.cells_kept_post // 0' "${DUMP_FILE}" 2>/dev/null || echo 0)"

    echo "${mode},${mal_rate},${ridx},${round_id},${total},${valid_clients},\
${rejected},${malicious_total},${malicious_reject_rate},${false_reject_rate},\
${DUMP_FILE},${cells_kept_pre},${cells_kept_post}" >> "${OUT_CSV}"

    echo "    [dump]  cells_kept_post=${cells_kept_post} → ${DUMP_FILE##*/}"
}

# ── main sweep loop ───────────────────────────────────────────────────────────
TOTAL_CONDITIONS=0
for _m in $TSIP_MODES; do for _r in $MALICIOUS_RATES; do
    TOTAL_CONDITIONS=$((TOTAL_CONDITIONS + 1))
done; done

DONE=0
for mode in $TSIP_MODES; do
    for mal_rate in $MALICIOUS_RATES; do
        DONE=$((DONE + 1))
        echo ""
        echo "── [${DONE}/${TOTAL_CONDITIONS}] mode=${mode}  mal_rate=${mal_rate} ──"

        reset_services "$mode" "$mal_rate"

        # Warmup rounds
        for i in $(seq 1 "$WARMUP_ROUNDS"); do
            run_one_round "$mode" "$mal_rate" "$i" 1
        done

        # Measured rounds
        for i in $(seq 1 "$ROUNDS"); do
            run_one_round "$mode" "$mal_rate" "$i" 0
        done
    done
done

echo ""
echo "============================================================"
echo "  Sweep done. Computing utility metrics …"
echo "============================================================"

# ── compute Jaccard / RMSE via Python ─────────────────────────────────────────
LOCAL_TRAJ_PATH="${ROOT_DIR}/experiments/${CLIENT_TRAJ_SOURCE}_tsip_ready_50u.jsonl"
if [[ ! -f "${LOCAL_TRAJ_PATH}" ]]; then
    LOCAL_TRAJ_PATH="${ROOT_DIR}/experiments/geolife_tsip_ready_50u.jsonl"
fi

python3 "${ROOT_DIR}/experiments/compute_system_utility.py" \
    --sweep-csv    "${OUT_CSV}" \
    --traj         "${LOCAL_TRAJ_PATH}" \
    --dump-dir     "${DUMP_DIR}" \
    --rounds       "${ROUNDS}" \
    --n-users      "${CLIENT_TOTAL}" \
    --out          "${OUT_CSV%.csv}_with_jaccard.csv"

echo ""
echo "Results:"
echo "  Raw sweep CSV    : ${OUT_CSV}"
echo "  With Jaccard CSV : ${OUT_CSV%.csv}_with_jaccard.csv"
echo "  Dump JSON dir    : ${DUMP_DIR}"
