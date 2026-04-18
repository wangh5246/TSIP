import math
import os, time, uuid, random, json, subprocess, tempfile, shutil, hashlib
from collections import Counter
import requests
from common.ea import sign_attestation
from common.utils import gaussian_preview, gaussian_vectors, prp, derive_prp_seed_from_share
import common.tsip as _tsip


def _get_tsip_symbol(name: str, default=None):
    value = getattr(_tsip, name, default)
    if value is None:
        raise RuntimeError(
            f"incompatible common/tsip.py, missing symbol: {name}. "
            "Please sync both /app/client.py and /app/common/tsip.py."
        )
    return value


TSIP_LOC_HASH_MODE = _get_tsip_symbol(
    "TSIP_LOC_HASH_MODE", os.getenv("TSIP_LOC_HASH_MODE", "mimc").strip().lower()
)
TSIP_POSEIDON_SNARKJS = _get_tsip_symbol(
    "TSIP_POSEIDON_SNARKJS", os.getenv("TSIP_POSEIDON_SNARKJS", os.getenv("TSIP_SNARKJS", "snarkjs"))
)
TSIP_POSEIDON_WASM = _get_tsip_symbol(
    "TSIP_POSEIDON_WASM", os.getenv("TSIP_POSEIDON_WASM", "/app/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm")
)
commitment_to_field = _get_tsip_symbol("commitment_to_field")
compute_chain_commitment = _get_tsip_symbol("compute_chain_commitment")
compute_location_commitment = _get_tsip_symbol("compute_location_commitment")
tsip_window_id = _get_tsip_symbol("tsip_window_id")
# P4/P5 helpers
compute_payload_digest = _get_tsip_symbol("compute_payload_digest")
compute_secret_commitment = _get_tsip_symbol("compute_secret_commitment")
split_payload_digest_fields = _get_tsip_symbol("split_payload_digest_fields")
compute_payload_commitment_field = _get_tsip_symbol("compute_payload_commitment_field")
user_id_to_field = _get_tsip_symbol("user_id_to_field")
secret_hex_to_field = _get_tsip_symbol("secret_hex_to_field")
compute_secret_commitment_field = _get_tsip_symbol("compute_secret_commitment_field")
default_adwc_window_k = _get_tsip_symbol("default_adwc_window_k")
normalize_mode = _get_tsip_symbol("normalize_mode")
normalize_tier = _get_tsip_symbol("normalize_tier")
mode_id = _get_tsip_symbol("mode_id")
mode_vmax_mps = _get_tsip_symbol("mode_vmax_mps")
mode_vmax_sq = _get_tsip_symbol("mode_vmax_sq")
tier_vmax_sq = _get_tsip_symbol("tier_vmax_sq")
build_modeset_bitmap = _get_tsip_symbol("build_modeset_bitmap")
modeset_bitmap_all = _get_tsip_symbol("modeset_bitmap_all")
modeset_contains_mode = _get_tsip_symbol("modeset_contains_mode")
compute_modeset_commitment_field = _get_tsip_symbol("compute_modeset_commitment_field")
compute_mode_tag_field = _get_tsip_symbol("compute_mode_tag_field")
compute_tier_anchor_cap_sq = _get_tsip_symbol("compute_tier_anchor_cap_sq")
compute_policy_cap_sq = _get_tsip_symbol("compute_policy_cap_sq")
# Feature flags (mirrored from common/tsip.py so client behaviour is consistent)
TSIP_PAYLOAD_BINDING_ENABLE: bool = getattr(_tsip, "TSIP_PAYLOAD_BINDING_ENABLE", False)
TSIP_SECRET_BINDING_ENABLE: bool = getattr(_tsip, "TSIP_SECRET_BINDING_ENABLE", False)

def _first_existing_path(candidates: list[str]) -> str:
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def _first_existing_binary(candidates: list[str], fallback: str) -> str:
    for cmd in candidates:
        if os.path.isabs(cmd):
            if os.path.exists(cmd):
                return cmd
        else:
            if shutil.which(cmd) is not None:
                return cmd
    return fallback


def _binary_exists(cmd: str) -> bool:
    if os.path.isabs(cmd):
        return os.path.exists(cmd)
    return shutil.which(cmd) is not None


def _normalize_prover(name: str, value: str) -> str:
    mode = (value or "auto").strip().lower()
    if mode not in {"auto", "snarkjs", "rapidsnark"}:
        raise RuntimeError(f"invalid {name}: {value}")
    return mode


def _normalize_tsip_verify_mode(name: str, value: str) -> str:
    mode = (value or "full").strip().lower()
    if mode not in {"full"}:
        raise RuntimeError(f"invalid {name}: {value}")
    return mode


def _normalize_tsip_circuit_profile(value: str) -> str:
    p = (value or "k6").strip().lower()
    if p not in {"k6", "k30"}:
        return "k6"
    return p


def _resolve_prover(mode: str, rapidsnark_bin: str) -> str:
    if mode == "auto":
        return "rapidsnark" if _binary_exists(rapidsnark_bin) else "snarkjs"
    return mode


def _is_rapidsnark(prover: str) -> bool:
    return prover == "rapidsnark"


def _is_malicious_client(user_key: str) -> bool:
    if MALICIOUS_RATE <= 0:
        return False
    if MALICIOUS_SCOPE == "stable":
        digest = hashlib.sha256(user_key.encode("utf-8")).digest()
        raw = int.from_bytes(digest[:8], byteorder="big", signed=False)
        return (raw / float(1 << 64)) < MALICIOUS_RATE
    return random.random() < MALICIOUS_RATE


def _stable_u64(*parts) -> int:
    payload = "||".join(str(p) for p in parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def _sample_non_cell(rng: random.Random, domain: int, excluded: int) -> int:
    if domain <= 1:
        return 0
    c = rng.randrange(domain - 1)
    return c + 1 if c >= excluded else c


def _build_sparse_protocol_report(
    rng: random.Random,
    truth_cell: int,
    protocol: str,
    epsilon: float,
) -> tuple[list[int], list[int]]:
    """
    Build a system-compatible sparse report (K+KD unique idx, mostly zero values)
    for protocol-compatibility baseline modes.
    """
    truth = int(truth_cell) % DOMAIN
    send_cell = truth

    if protocol == "nebula":
        # ESA-like sampling: report true cell with p_s, otherwise random dummy.
        p_s = 1.0 - math.exp(-max(0.0, epsilon))
        if rng.random() >= p_s:
            send_cell = rng.randrange(DOMAIN)
    elif protocol == "ldp":
        # GRR: truthful with p, otherwise sample any other cell.
        eps = max(0.0, epsilon)
        exp_e = math.exp(eps)
        p = exp_e / (exp_e + DOMAIN - 1.0)
        if rng.random() >= p:
            send_cell = _sample_non_cell(rng, DOMAIN, truth)
    elif protocol == "eiffel":
        # EIFFeL-style range-only checks do not randomize payload values.
        send_cell = truth
    else:
        # default path should not call this helper.
        send_cell = truth

    idx = [send_cell]
    used = {send_cell}
    while len(idx) < KPRIME:
        c = rng.randrange(DOMAIN)
        if c in used:
            continue
        used.add(c)
        idx.append(c)

    # Sparse one-hot value vector compatible with existing report schema.
    val = [1] + [0] * (KPRIME - 1)
    return idx, val

ROUND_NEW = os.environ.get("SHUFFLER_ROUND_NEW", "http://shuffler:8001/round/new")
SHUFFLER_URL_A = os.environ.get("SHUFFLER_URL_A", "http://localhost:8001/ingestA")
SHUFFLER_URL_R = os.environ.get("SHUFFLER_URL_R", "http://localhost:8001/ingestR")
SHUFFLER_HEALTH = os.environ.get("SHUFFLER_HEALTH", "http://localhost:8001/health")
RANDOMNESS_SEED_URL = os.environ.get("RANDOMNESS_SEED_URL", "http://aggregator_r:8003/risefl/seed")
RANDOMNESS_PREVIEW_URL = os.environ.get("RANDOMNESS_PREVIEW_URL", "http://aggregator_r:8003/risefl/gaussian_preview")

K = int(os.getenv("K", "50"))
KD = int(os.getenv("KD", "50"))
KPRIME = K + KD
DOMAIN = int(os.getenv("DOMAIN", "10000"))

MASK_BITS = int(os.getenv("MASK_BITS", "32"))
MASK = (1 << MASK_BITS) - 1
CITY_SIZE_M = float(os.getenv("CITY_SIZE_M", "10000"))
TSIP_COORD_MAX = int(os.getenv("TSIP_COORD_MAX", "1000000"))
CELL_SIZE_M = float(os.getenv("CELL_SIZE_M", "100"))
GRID_W = int(os.getenv("GRID_W", "100"))
DT_SEC = int(os.getenv("DT_SEC", "10"))
TRAJ_POINTS = int(os.getenv("TRAJ_POINTS", "300"))
T_MAX_SEC = float(os.getenv("T_MAX_SEC", "600"))
QUANT_BITS = int(os.getenv("QUANT_BITS", "4"))
DUMMY_Q = int(os.getenv("DUMMY_Q", "1"))
DEBUG_CLIENT = os.getenv("DEBUG_CLIENT", "0") == "1"
DEBUG_CLIENT_EVERY = int(os.getenv("DEBUG_CLIENT_EVERY", "1"))
DEBUG_TOPK = os.getenv("DEBUG_TOPK", "0") == "1"
DEBUG_TOPK_PATH = os.getenv("DEBUG_TOPK_PATH", "/tmp/topk_dump.jsonl")
DEBUG_QUANT_TEST = os.getenv("DEBUG_QUANT_TEST", "0") == "1"
QUANT_ERR_MAX = float(os.getenv("QUANT_ERR_MAX", "0"))
DEBUG_RANDOMNESS = os.getenv("DEBUG_RANDOMNESS", "0") == "1"
RAND_M = int(os.getenv("RAND_M", "8"))
RAND_DIM = int(os.getenv("RAND_DIM", "4"))
RAND_PREVIEW_N = int(os.getenv("RAND_PREVIEW_N", "3"))
PROOF_ENABLE = os.getenv("PROOF_ENABLE", "0") == "1"
PROOF_M = int(os.getenv("PROOF_M", "8"))
MAX_STEP_M = float(os.getenv("MAX_STEP_M", "80.0"))
PROOF_TELEPORT_TEST = os.getenv("PROOF_TELEPORT_TEST", "0") == "1"
TELEPORT_JUMP_M = float(os.getenv("TELEPORT_JUMP_M", "5000.0"))
TELEPORT_INDEX = int(os.getenv("TELEPORT_INDEX", "10"))
PROOF_S_THRESHOLD = float(os.getenv("PROOF_S_THRESHOLD", "0"))
MALICIOUS_RATE = float(os.getenv("MALICIOUS_RATE", "0"))
MALICIOUS_SCOPE = os.getenv("MALICIOUS_SCOPE", "round").strip().lower()
FIXED_SYNTHETIC_SEEDS = os.getenv("FIXED_SYNTHETIC_SEEDS", "0") == "1"
EXPERIMENT_SEED_BASE = os.getenv("EXPERIMENT_SEED_BASE", "0").strip()
GRADUAL_DRIFT_BIAS_RATIO = float(os.getenv("GRADUAL_DRIFT_BIAS_RATIO", "0.60"))
_GRADUAL_DRIFT_TARGET_X_RAW = os.getenv("GRADUAL_DRIFT_TARGET_X", "").strip()
_GRADUAL_DRIFT_TARGET_Y_RAW = os.getenv("GRADUAL_DRIFT_TARGET_Y", "").strip()
GRADUAL_DRIFT_TARGET_X = float(_GRADUAL_DRIFT_TARGET_X_RAW) if _GRADUAL_DRIFT_TARGET_X_RAW else None
GRADUAL_DRIFT_TARGET_Y = float(_GRADUAL_DRIFT_TARGET_Y_RAW) if _GRADUAL_DRIFT_TARGET_Y_RAW else None
# ATTACK_TYPE controls malicious client behavior:
#   "teleport"          (default) - apply spatial teleport + tamper commitment chain (A1 + A6)
#   "identity_swap"               - malicious client uses a swapped user_id to break chain continuity (A2)
#   "replay"                      - malicious client re-submits a stale prev_loc_commitment (A5)
#   "boundary_teleport"           - move exactly TELEPORT_JUMP_M from prev, NO commitment tamper (A1 boundary scan)
#                                   TSIP accepts iff distance <= v_max*dt; reject_rate forms a step function at threshold
#   "gradual_drift"               - each step stays within v_max*dt, but is biased toward a fixed fake target (A3)
ATTACK_TYPE = os.getenv("ATTACK_TYPE", "teleport").strip().lower()
ZK_STEP_ENABLE = os.getenv("ZK_STEP_ENABLE", "0") == "1"
ZK_STEP_INDEX = int(os.getenv("ZK_STEP_INDEX", str(TELEPORT_INDEX)))
ZK_STEP_FALLBACK_SCAN = os.getenv("ZK_STEP_FALLBACK_SCAN", "1") == "1"
ZK_STEP_HONEST_SOFT_FAIL = os.getenv("ZK_STEP_HONEST_SOFT_FAIL", "1") == "1"
ZK_STEP_SNARKJS = os.getenv("ZK_STEP_SNARKJS", "snarkjs")
NODE_BIN = _first_existing_binary(["node", "nodejs"], "node")
RAPIDSNARK_BIN = os.getenv(
    "RAPIDSNARK_BIN",
    _first_existing_binary(
        [
            "/app/rapidsnark/rapidsnark",
            "/usr/local/bin/rapidsnark",
            "/Users/wanghao/.local/bin/rapidsnark",
            "rapidsnark",
        ],
        "rapidsnark",
    ),
)
ZK_STEP_PROVER = _normalize_prover("ZK_STEP_PROVER", os.getenv("ZK_STEP_PROVER", "rapidsnark"))
ZK_STEP_WASM = os.getenv(
    "ZK_STEP_WASM",
    _first_existing_path(
        [
            "/app/zk/tsip_step/tsip_step_js/tsip_step.wasm",
            "/app/build/tsip_step/tsip_step_js/tsip_step.wasm",
            "/Users/wanghao/Desktop/risefl_mvp/zk/tsip_step/tsip_step_js/tsip_step.wasm",
            "/Users/wanghao/Desktop/risefl_mvp/build/tsip_step/tsip_step_js/tsip_step.wasm",
            "zk/tsip_step/tsip_step_js/tsip_step.wasm",
            "build/tsip_step/tsip_step_js/tsip_step.wasm",
        ]
    ),
)
ZK_STEP_ZKEY = os.getenv(
    "ZK_STEP_ZKEY",
    _first_existing_path(
        [
            "/app/zk/tsip_step/tsip_step_final.zkey",
            "/app/build/tsip_step/tsip_step_final.zkey",
            "/Users/wanghao/Desktop/risefl_mvp/zk/tsip_step/tsip_step_final.zkey",
            "/Users/wanghao/Desktop/risefl_mvp/build/tsip_step/tsip_step_final.zkey",
            "zk/tsip_step/tsip_step_final.zkey",
            "build/tsip_step/tsip_step_final.zkey",
        ]
    ),
)
ZK_STEP_TIMEOUT_SEC = int(os.getenv("ZK_STEP_TIMEOUT_SEC", "20"))
TSIP_ENABLE = os.getenv("TSIP_ENABLE", "0") == "1"
TSIP_VERIFY_MODE = _normalize_tsip_verify_mode("TSIP_VERIFY_MODE", os.getenv("TSIP_VERIFY_MODE", "full"))
if TSIP_ENABLE and TSIP_VERIFY_MODE != "full":
    raise RuntimeError("TSIP_VERIFY_MODE must be 'full' in TSIP v3 mode")
TSIP_WINDOW_SEC = int(os.getenv("TSIP_WINDOW_SEC", "60"))
TSIP_STATE_PATH = os.getenv("TSIP_STATE_PATH", "/tmp/tsip_client_state.json")
TSIP_ADWC_PROFILE = os.getenv("TSIP_ADWC_PROFILE", "k6").strip().lower()
TSIP_ADWC_WINDOW_K: int = int(os.getenv("TSIP_ADWC_WINDOW_K", str(default_adwc_window_k(TSIP_ADWC_PROFILE))))
TSIP_POLICY_CAP_RATIO: float = float(os.getenv("TSIP_POLICY_CAP_RATIO", "0.5"))
TSIP_CIRCUIT_PROFILE = _normalize_tsip_circuit_profile(
    os.getenv("TSIP_CIRCUIT_PROFILE", os.getenv("TSIP_ADWC_PROFILE", "k6"))
)
TSIP_MODE_DEFAULT = normalize_mode(os.getenv("TSIP_MODE_DEFAULT", "vehicle"))
TSIP_TIER_DEFAULT = normalize_tier(os.getenv("TSIP_TIER_DEFAULT", "transit"))
TSIP_ALLOWED_MODES_RAW = os.getenv("TSIP_ALLOWED_MODES", "walk,bike,vehicle,transit").strip()
TSIP_ALLOWED_MODES = [normalize_mode(x.strip()) for x in TSIP_ALLOWED_MODES_RAW.split(",") if x.strip()]
if not TSIP_ALLOWED_MODES:
    TSIP_ALLOWED_MODES = [TSIP_MODE_DEFAULT]
TSIP_FORCE_MODE = normalize_mode(os.getenv("TSIP_FORCE_MODE", "").strip() or TSIP_MODE_DEFAULT)
TSIP_FORCE_TIER = normalize_tier(os.getenv("TSIP_FORCE_TIER", "").strip() or TSIP_TIER_DEFAULT)
TSIP_EA_SIGNING_SK = os.getenv("TSIP_EA_SIGNING_SK", "").strip().lower()
TSIP_EA_KID = os.getenv("TSIP_EA_KID", "ea-dev").strip() or "ea-dev"
TSIP_EA_EXP_SEC = int(os.getenv("TSIP_EA_EXP_SEC", "86400"))
TSIP_AUTO_RESET_ON_EMPTY = os.getenv("TSIP_AUTO_RESET_ON_EMPTY", "0") == "1"
TSIP_SNARKJS = os.getenv("TSIP_SNARKJS", ZK_STEP_SNARKJS)
TSIP_PROVER = _normalize_prover("TSIP_PROVER", os.getenv("TSIP_PROVER", "rapidsnark"))
TSIP_WASM = os.getenv(
    "TSIP_WASM",
    _first_existing_path(
        [
            f"/app/zk/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}_js/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}.wasm",
            f"/Users/wanghao/Desktop/risefl_mvp/zk/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}_js/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}.wasm",
            f"zk/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}_js/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}.wasm",
        ]
    ),
)
TSIP_ZKEY = os.getenv(
    "TSIP_ZKEY",
    _first_existing_path(
        [
            f"/app/zk/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}_final.zkey",
            f"/Users/wanghao/Desktop/risefl_mvp/zk/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}_final.zkey",
            f"zk/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}/tsip_main_v3_{TSIP_CIRCUIT_PROFILE}_final.zkey",
        ]
    ),
)
TSIP_TIMEOUT_SEC = int(os.getenv("TSIP_TIMEOUT_SEC", "20"))
TSIP_RECOVERY_STATE_URL = os.getenv("TSIP_RECOVERY_STATE_URL", "http://shuffler:8001/tsip/state")
REPORT_TIMEOUT_SEC = float(os.getenv("REPORT_TIMEOUT_SEC", "20"))
SEND_INTERVAL_SEC = float(os.getenv("SEND_INTERVAL_SEC", "0.03"))
CLIENT_TOTAL = int(os.getenv("CLIENT_TOTAL", "200"))
TSIP_USER_SCOPE = os.getenv("TSIP_USER_SCOPE", "stable").strip().lower()
TRAJ_SOURCE = os.getenv("CLIENT_TRAJ_SOURCE", "synthetic").strip().lower()
REAL_TRAJ_SOURCES = {"geolife", "tdrive"}
GEO_TRAJ_PATH = os.getenv(
    "GEO_TRAJ_PATH",
    _first_existing_path(
        [
            "/app/experiments/geolife_tsip_ready_50u.jsonl",
            "/Users/wanghao/Desktop/risefl_mvp/experiments/geolife_tsip_ready_50u.jsonl",
            "experiments/geolife_tsip_ready_50u.jsonl",
        ]
    ),
)
GEO_MAX_USERS = int(os.getenv("GEO_MAX_USERS", "50"))
PRP_ENABLE = os.getenv("PRP_ENABLE", "1") == "1"
PRP_ROUNDS = int(os.getenv("PRP_ROUNDS", "8"))
PRP_MIN_DOMAIN = int(os.getenv("PRP_MIN_DOMAIN", "1000000"))
REPORT_PROTOCOL = os.getenv("REPORT_PROTOCOL", "default").strip().lower()
REPORT_EPSILON = float(os.getenv("REPORT_EPSILON", os.getenv("EPSILON", "1.0")))
if REPORT_PROTOCOL not in {"default", "nebula", "ldp", "eiffel"}:
    raise RuntimeError(f"invalid REPORT_PROTOCOL: {REPORT_PROTOCOL}")
CLOVER_SHARE_URL_A = os.getenv("CLOVER_SHARE_URL_A", "http://aggregator_a:8002/clover/key_share")
CLOVER_SHARE_URL_R = os.getenv("CLOVER_SHARE_URL_R", "http://aggregator_r:8003/clover/key_share")
CLOVER_CLIENT_TOKEN_A = os.getenv("CLOVER_CLIENT_TOKEN_A", "")
CLOVER_CLIENT_TOKEN_R = os.getenv("CLOVER_CLIENT_TOKEN_R", "")

QMAX = (1 << QUANT_BITS) - 1  # INT4 => 15


def load_geolife_trajectories() -> list[dict]:
    if TRAJ_SOURCE not in REAL_TRAJ_SOURCES:
        return []
    if not os.path.exists(GEO_TRAJ_PATH):
        raise RuntimeError(f"missing GEO_TRAJ_PATH: {GEO_TRAJ_PATH}")
    records = []
    with open(GEO_TRAJ_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if len(records) >= max(1, GEO_MAX_USERS):
                break
    if not records:
        raise RuntimeError(f"no {TRAJ_SOURCE} records loaded from: {GEO_TRAJ_PATH}")
    return records


def geolife_trajectory_points(record: dict):
    points = []
    step = max(1, int(record.get("source_window_sec", record.get("window_sec", TSIP_WINDOW_SEC))))
    fallback_ts = None
    for idx, window in enumerate(record.get("windows", [])):
        raw_ts = window.get("timestamp")
        if raw_ts is not None:
            ts = int(raw_ts)
            fallback_ts = ts
        else:
            if fallback_ts is None:
                fallback_ts = int(time.time())
            ts = int(fallback_ts + step)
            fallback_ts = ts
        points.append(
            (
                float(window["x_m"]),
                float(window["y_m"]),
                ts,
            )
        )
    return points


def tamper_commitment_hex(commitment: str) -> str:
    if not commitment:
        return "1" * 64
    chars = list(commitment)
    last = chars[-1].lower()
    chars[-1] = "0" if last != "0" else "1"
    return "".join(chars)



def new_round_id() -> int:
    r = requests.post(ROUND_NEW, timeout=5).json()
    if not r.get("ok"):
        raise RuntimeError(f"failed to new round: {r}")
    return int(r["round_id"])

def wait_for_shuffler(timeout_sec=30):
    start = time.time()
    while True:
        try:
            r = requests.get(SHUFFLER_HEALTH, timeout=2)
            if r.status_code == 200:
                payload = r.json()
                print("shuffler is ready:", payload)
                return payload
        except Exception:
            pass

        if time.time() - start > timeout_sec:
            raise RuntimeError("Timeout waiting for shuffler to be ready")

        print("waiting for shuffler...")
        time.sleep(1)


def fetch_tsip_recovery_state(user_id: str) -> dict:
    if not TSIP_RECOVERY_STATE_URL:
        return {"ok": False, "exists": False, "error": "recovery endpoint disabled"}
    try:
        resp = requests.get(TSIP_RECOVERY_STATE_URL, params={"user_id": user_id}, timeout=3)
        if resp.status_code != 200:
            return {"ok": False, "exists": False, "error": f"http {resp.status_code}"}
        data = resp.json()
        if not isinstance(data, dict):
            return {"ok": False, "exists": False, "error": "invalid response"}
        return data
    except Exception as e:
        return {"ok": False, "exists": False, "error": str(e)}


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _boundary_teleport_target(prev_x: float, prev_y: float, jump_m: float, city_size_m: float):
    """Return (curr_x, curr_y) that is EXACTLY jump_m from (prev_x, prev_y) without clamping.

    Tries 4 axis-aligned directions (E/W/N/S) then 4 diagonals (NE/SE/SW/NW).
    Returns None if no direction keeps the endpoint within [0, city_size_m).
    This guarantees a clean boundary scan: the actual displacement equals jump_m,
    so the ZK proof succeeds iff jump_m <= MAX_STEP_M * time_diff.
    """
    D = float(jump_m)
    C = float(city_size_m)
    diag = D / math.sqrt(2.0)

    candidates = [
        # Axis-aligned: E, W, N, S (integer rounding applied below)
        (prev_x + D,    prev_y),
        (prev_x - D,    prev_y),
        (prev_x,        prev_y + D),
        (prev_x,        prev_y - D),
        # Diagonals: NE, SE, SW, NW
        (prev_x + diag, prev_y + diag),
        (prev_x + diag, prev_y - diag),
        (prev_x - diag, prev_y - diag),
        (prev_x - diag, prev_y + diag),
    ]
    for cx, cy in candidates:
        if 0.0 <= cx < C and 0.0 <= cy < C:
            return int(round(cx)), int(round(cy))
    return None  # city too small for this jump (caller should warn)


def _gradual_drift_target(start_x: float, start_y: float, coord_cap: float):
    cap = max(1.0, float(coord_cap))
    if GRADUAL_DRIFT_TARGET_X is not None and GRADUAL_DRIFT_TARGET_Y is not None:
        return (
            float(clamp(GRADUAL_DRIFT_TARGET_X, 0.0, cap - 1e-6)),
            float(clamp(GRADUAL_DRIFT_TARGET_Y, 0.0, cap - 1e-6)),
        )
    corners = [
        (0.0, 0.0),
        (0.0, cap - 1e-6),
        (cap - 1e-6, 0.0),
        (cap - 1e-6, cap - 1e-6),
    ]
    return max(corners, key=lambda p: (p[0] - start_x) ** 2 + (p[1] - start_y) ** 2)


def _gradual_drift_next_point(
    prev_reported_x: float,
    prev_reported_y: float,
    honest_prev_x: float,
    honest_prev_y: float,
    honest_curr_x: float,
    honest_curr_y: float,
    target_x: float,
    target_y: float,
    max_step: float,
    coord_cap: float,
):
    honest_dx = honest_curr_x - honest_prev_x
    honest_dy = honest_curr_y - honest_prev_y
    honest_norm = math.hypot(honest_dx, honest_dy)
    target_dx = target_x - prev_reported_x
    target_dy = target_y - prev_reported_y
    target_norm = math.hypot(target_dx, target_dy)
    bias_dx = 0.0
    bias_dy = 0.0
    if target_norm > 1e-9:
        residual_budget = max(0.0, float(max_step) - honest_norm)
        bias_mag = residual_budget * max(0.0, GRADUAL_DRIFT_BIAS_RATIO)
        bias_dx = (target_dx / target_norm) * bias_mag
        bias_dy = (target_dy / target_norm) * bias_mag
    step_dx = honest_dx + bias_dx
    step_dy = honest_dy + bias_dy
    step_norm = math.hypot(step_dx, step_dy)
    if step_norm > max_step > 0.0:
        scale = max_step / step_norm
        step_dx *= scale
        step_dy *= scale
    cap = max(1.0, float(coord_cap))
    next_x = clamp(prev_reported_x + step_dx, 0.0, cap - 1e-6)
    next_y = clamp(prev_reported_y + step_dy, 0.0, cap - 1e-6)
    return float(next_x), float(next_y)


def apply_gradual_drift(trajectory, coord_cap_hint: float | None = None):
    if len(trajectory) < 2:
        return list(trajectory)
    observed_cap = max(max(float(x), float(y)) for x, y, _ in trajectory) + 1.0
    coord_cap = max(observed_cap, float(coord_cap_hint)) if coord_cap_hint is not None else observed_cap
    first_x, first_y, first_t = trajectory[0]
    target_x, target_y = _gradual_drift_target(float(first_x), float(first_y), coord_cap)
    drifted = [(float(first_x), float(first_y), int(first_t))]
    for idx in range(1, len(trajectory)):
        honest_prev_x, honest_prev_y, honest_prev_t = trajectory[idx - 1]
        honest_curr_x, honest_curr_y, honest_curr_t = trajectory[idx]
        prev_reported_x, prev_reported_y, _ = drifted[-1]
        dt = max(1, int(honest_curr_t - honest_prev_t))
        max_step = float(MAX_STEP_M) * float(dt)
        next_x, next_y = _gradual_drift_next_point(
            prev_reported_x=float(prev_reported_x),
            prev_reported_y=float(prev_reported_y),
            honest_prev_x=float(honest_prev_x),
            honest_prev_y=float(honest_prev_y),
            honest_curr_x=float(honest_curr_x),
            honest_curr_y=float(honest_curr_y),
            target_x=target_x,
            target_y=target_y,
            max_step=max_step,
            coord_cap=coord_cap,
        )
        drifted.append((next_x, next_y, int(honest_curr_t)))
    return drifted

def map_xy_to_cell(x_m: float, y_m: float) -> int:
    """二维平面网格映射：确定性、可复现"""
    cx = int(x_m // CELL_SIZE_M)
    cy = int(y_m // CELL_SIZE_M)
    # 保证不越界
    cx = clamp(cx, 0, GRID_W - 1)
    # GRID_H 由 DOMAIN 推出来
    grid_h = DOMAIN // GRID_W
    cy = clamp(cy, 0, grid_h - 1)
    cell_id = cy * GRID_W + cx
    return int(cell_id)

def gen_synthetic_trajectory(rng: random.Random):
    """
    生成“家→通勤→公司→随机游走”的合成轨迹
    输出: [(x, y, t), ...] 其中 t 单位秒
    """
    # 随机家和公司
    home = (rng.uniform(0, CITY_SIZE_M), rng.uniform(0, CITY_SIZE_M))
    work = (rng.uniform(0, CITY_SIZE_M), rng.uniform(0, CITY_SIZE_M))

    points = []
    t0 = 1700000000  # 任意起始时间戳（合成数据不重要）

    def add_stay(center, n_steps, jitter_m):
        nonlocal t0
        for _ in range(n_steps):
            x = clamp(center[0] + rng.gauss(0, jitter_m), 0, CITY_SIZE_M - 1e-6)
            y = clamp(center[1] + rng.gauss(0, jitter_m), 0, CITY_SIZE_M - 1e-6)
            points.append((x, y, t0))
            t0 += DT_SEC

    def add_move(p0, p1, n_steps, jitter_m):
        nonlocal t0
        for i in range(n_steps):
            a = 0.0 if n_steps <= 1 else i / (n_steps - 1)
            x = (1 - a) * p0[0] + a * p1[0] + rng.gauss(0, jitter_m)
            y = (1 - a) * p0[1] + a * p1[1] + rng.gauss(0, jitter_m)
            x = clamp(x, 0, CITY_SIZE_M - 1e-6)
            y = clamp(y, 0, CITY_SIZE_M - 1e-6)
            points.append((x, y, t0))
            t0 += DT_SEC

    def add_random_walk(start, n_steps, step_sigma_m):
        nonlocal t0
        x, y = start
        for _ in range(n_steps):
            x = clamp(x + rng.gauss(0, step_sigma_m), 0, CITY_SIZE_M - 1e-6)
            y = clamp(y + rng.gauss(0, step_sigma_m), 0, CITY_SIZE_M - 1e-6)
            points.append((x, y, t0))
            t0 += DT_SEC

    # 用 TRAJ_POINTS 划分段落（你可以按需要调整比例）
    n_home = max(10, TRAJ_POINTS // 5)        # 20%
    n_commute = max(10, TRAJ_POINTS // 5)     # 20%
    n_work = max(10, TRAJ_POINTS // 3)        # 33%
    n_walk = TRAJ_POINTS - (n_home + n_commute + n_work)

    add_stay(home, n_home, jitter_m=8.0)              # 家附近停留
    add_move(home, work, n_commute, jitter_m=6.0)     # 通勤
    add_stay(work, n_work, jitter_m=10.0)             # 公司附近停留
    add_random_walk(work, n_walk, step_sigma_m=25.0)  # 公司周边游走

    return points

def compute_cell_dwell(trajectory):
    """
    按相邻时间戳差累加 dwell time（秒）
    cell_visits[cell_id] += dt
    """
    cell_visits = {}
    for i in range(len(trajectory) - 1):
        x, y, t = trajectory[i]
        _, _, t2 = trajectory[i + 1]
        dt = max(0, int(t2 - t))
        if dt == 0:
            continue
        cell = map_xy_to_cell(x, y)
        cell_visits[cell] = cell_visits.get(cell, 0) + dt
    return cell_visits

def quantize_time(sec: float) -> int:
    """全局固定量化：clip 到 [0, T_MAX_SEC] → 映射到 [0, QMAX]"""
    sec = clamp(sec, 0.0, T_MAX_SEC)
    q = int(round(sec / T_MAX_SEC * QMAX))
    return int(clamp(q, 0, QMAX))

def dequantize_time(q: int) -> float:
    """反量化：q ∈ [0, QMAX] → 近似秒数"""
    q = int(clamp(q, 0, QMAX))
    return (q / QMAX) * T_MAX_SEC

def quantization_self_test():
    samples = [0, 1, 5, 10, 42, 123, 599, 600, 900]
    step = (T_MAX_SEC / QMAX) if QMAX > 0 else 0.0
    max_err = (QUANT_ERR_MAX if QUANT_ERR_MAX > 0 else step / 2)
    print("[DEBUG] quant_test T_MAX_SEC=", T_MAX_SEC, "QMAX=", QMAX, "max_err=", max_err)
    for s in samples:
        s_clip = clamp(s, 0.0, T_MAX_SEC)
        q = quantize_time(s)
        d = dequantize_time(q)
        err = abs(d - s_clip)
        print("  dwell=", s, "clip=", s_clip, "q=", q, "deq=", round(d, 3), "err=", round(err, 3))
        if err > max_err:
            raise RuntimeError(f"quantization error too large: err={err} max_err={max_err}")

def fetch_seed(round_id: int) -> int:
    resp = requests.get(RANDOMNESS_SEED_URL, params={"round_id": round_id}, timeout=5)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"failed to fetch seed: {data}")
    return int(data["seed"])

def fetch_key_share(url: str, token: str) -> bytes:
    headers = {}
    if token:
        headers["X-Client-Token"] = token
    resp = requests.get(url, headers=headers, timeout=5)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"failed to fetch key share: {data}")
    share_hex = data.get("share")
    if not share_hex:
        raise RuntimeError(f"missing share from {url}")
    return bytes.fromhex(share_hex)

def randomness_self_test(round_id: int):
    seed = fetch_seed(round_id)
    client_preview = gaussian_preview(seed, RAND_M, RAND_DIM, RAND_PREVIEW_N)
    print("[DEBUG] randomness client preview:", client_preview)

    resp2 = requests.get(
        RANDOMNESS_PREVIEW_URL,
        params={"round_id": round_id, "m": RAND_M, "dim": RAND_DIM, "n": RAND_PREVIEW_N},
        timeout=5,
    )
    data2 = resp2.json()
    if not data2.get("ok"):
        raise RuntimeError(f"failed to fetch server preview: {data2}")
    server_preview = data2.get("preview", [])
    print("[DEBUG] randomness server preview:", server_preview)

    tol = 1e-9
    if len(client_preview) != len(server_preview):
        raise RuntimeError("preview length mismatch")
    for i, (a, b) in enumerate(zip(client_preview, server_preview)):
        if abs(a - b) > tol:
            raise RuntimeError(f"preview mismatch at {i}: client={a} server={b}")

def compute_displacement_vector(trajectory):
    u = []
    for i in range(len(trajectory) - 1):
        x1, y1, _t1 = trajectory[i]
        x2, y2, _t2 = trajectory[i + 1]
        dx = x2 - x1
        dy = y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        u.append(dist / MAX_STEP_M)
    return u

def ensure_zk_step_ready():
    if not ZK_STEP_ENABLE:
        return
    if not _binary_exists(ZK_STEP_SNARKJS):
        raise RuntimeError(f"snarkjs not found: {ZK_STEP_SNARKJS}")
    resolved = _resolve_prover(ZK_STEP_PROVER, RAPIDSNARK_BIN)
    if _is_rapidsnark(resolved) and not _binary_exists(RAPIDSNARK_BIN):
        raise RuntimeError(f"rapidsnark not found: {RAPIDSNARK_BIN}")
    if _is_rapidsnark(resolved) and not _binary_exists(NODE_BIN):
        raise RuntimeError(f"node not found: {NODE_BIN}")
    if not os.path.exists(ZK_STEP_WASM):
        raise RuntimeError(f"missing ZK_STEP_WASM: {ZK_STEP_WASM}")
    if not os.path.exists(ZK_STEP_ZKEY):
        raise RuntimeError(f"missing ZK_STEP_ZKEY: {ZK_STEP_ZKEY}")


def ensure_tsip_ready():
    if not TSIP_ENABLE:
        return
    if TSIP_LOC_HASH_MODE == "poseidon2":
        if not _binary_exists(TSIP_POSEIDON_SNARKJS):
            raise RuntimeError(f"poseidon snarkjs not found: {TSIP_POSEIDON_SNARKJS}")
        if not os.path.exists(TSIP_POSEIDON_WASM):
            raise RuntimeError(f"missing TSIP_POSEIDON_WASM: {TSIP_POSEIDON_WASM}")
    if TSIP_VERIFY_MODE != "full":
        return
    if not _binary_exists(TSIP_SNARKJS):
        raise RuntimeError(f"snarkjs not found: {TSIP_SNARKJS}")
    resolved = _resolve_prover(TSIP_PROVER, RAPIDSNARK_BIN)
    if _is_rapidsnark(resolved) and not _binary_exists(RAPIDSNARK_BIN):
        raise RuntimeError(f"rapidsnark not found: {RAPIDSNARK_BIN}")
    if _is_rapidsnark(resolved) and not _binary_exists(NODE_BIN):
        raise RuntimeError(f"node not found: {NODE_BIN}")
    if not os.path.exists(TSIP_WASM):
        raise RuntimeError(f"missing TSIP_WASM: {TSIP_WASM}")
    if not os.path.exists(TSIP_ZKEY):
        raise RuntimeError(f"missing TSIP_ZKEY: {TSIP_ZKEY}")


def load_tsip_state() -> dict:
    if not TSIP_ENABLE:
        return {}
    if not os.path.exists(TSIP_STATE_PATH):
        return {}
    with open(TSIP_STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def save_tsip_state(state: dict):
    if not TSIP_ENABLE:
        return
    os.makedirs(os.path.dirname(TSIP_STATE_PATH), exist_ok=True)
    with open(TSIP_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=True, sort_keys=True)


def _run_prover_cmd(cmd: list[str], timeout_sec: int, error_hint: str):
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(msg or error_hint)


def _snarkjs_fullprove(
    snarkjs_bin: str,
    input_path: str,
    wasm_path: str,
    zkey_path: str,
    proof_path: str,
    public_path: str,
    timeout_sec: int,
    error_hint: str,
):
    _run_prover_cmd(
        [
            snarkjs_bin,
            "groth16",
            "fullprove",
            input_path,
            wasm_path,
            zkey_path,
            proof_path,
            public_path,
        ],
        timeout_sec=timeout_sec,
        error_hint=error_hint,
    )


def _rapidsnark_prove(
    snarkjs_bin: str,
    rapidsnark_bin: str,
    input_path: str,
    wasm_path: str,
    zkey_path: str,
    proof_path: str,
    public_path: str,
    timeout_sec: int,
    error_hint: str,
):
    witness_path = os.path.join(os.path.dirname(proof_path), "witness.wtns")
    _run_prover_cmd(
        [snarkjs_bin, "wtns", "calculate", wasm_path, input_path, witness_path],
        timeout_sec=timeout_sec,
        error_hint=f"{error_hint}: witness failed",
    )
    _run_prover_cmd(
        [rapidsnark_bin, zkey_path, witness_path, proof_path, public_path],
        timeout_sec=timeout_sec,
        error_hint=f"{error_hint}: rapidsnark prove failed",
    )


def _run_fullprove(
    prover: str,
    snarkjs_bin: str,
    rapidsnark_bin: str,
    input_path: str,
    wasm_path: str,
    zkey_path: str,
    proof_path: str,
    public_path: str,
    timeout_sec: int,
    error_hint: str,
):
    if _is_rapidsnark(prover):
        _rapidsnark_prove(
            snarkjs_bin=snarkjs_bin,
            rapidsnark_bin=rapidsnark_bin,
            input_path=input_path,
            wasm_path=wasm_path,
            zkey_path=zkey_path,
            proof_path=proof_path,
            public_path=public_path,
            timeout_sec=timeout_sec,
            error_hint=error_hint,
        )
        return
    _snarkjs_fullprove(
        snarkjs_bin=snarkjs_bin,
        input_path=input_path,
        wasm_path=wasm_path,
        zkey_path=zkey_path,
        proof_path=proof_path,
        public_path=public_path,
        timeout_sec=timeout_sec,
        error_hint=error_hint,
    )

def build_zk_step_inputs(trajectory, step_index: int | None = None):
    if len(trajectory) < 2:
        return {"dx": 0, "dy": 0, "dt": 1, "vmax": int(round(MAX_STEP_M))}
    if step_index is None:
        step_index = ZK_STEP_INDEX
    idx = max(1, min(int(step_index), len(trajectory) - 1))
    x1, y1, t1 = trajectory[idx - 1]
    x2, y2, t2 = trajectory[idx]
    dx = int(round(abs(x2 - x1)))
    dy = int(round(abs(y2 - y1)))
    dt = max(1, int(round(abs(t2 - t1))))
    vmax = max(1, int(round(MAX_STEP_M)))
    return {"dx": dx, "dy": dy, "dt": dt, "vmax": vmax}


def _zk_step_inputs_feasible(inputs: dict) -> bool:
    dx = int(inputs["dx"])
    dy = int(inputs["dy"])
    dt = int(inputs["dt"])
    vmax = int(inputs["vmax"])
    return (dx * dx + dy * dy) <= (vmax * vmax * dt * dt)


def find_feasible_zk_step_inputs(trajectory):
    if len(trajectory) < 2:
        return build_zk_step_inputs(trajectory)
    anchor = max(1, min(ZK_STEP_INDEX, len(trajectory) - 1))
    best = None
    best_gap = None
    for idx in range(1, len(trajectory)):
        cand = build_zk_step_inputs(trajectory, step_index=idx)
        if not _zk_step_inputs_feasible(cand):
            continue
        gap = abs(idx - anchor)
        if best is None or gap < best_gap:
            best = cand
            best_gap = gap
            if gap == 0:
                break
    return best

def generate_zk_step_proof(inputs: dict):
    with tempfile.TemporaryDirectory(prefix="zk_step_client_") as td:
        input_path = os.path.join(td, "input.json")
        proof_path = os.path.join(td, "proof.json")
        public_path = os.path.join(td, "public.json")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(inputs, f, ensure_ascii=True)

        prover = _resolve_prover(ZK_STEP_PROVER, RAPIDSNARK_BIN)
        _run_fullprove(
            prover=prover,
            snarkjs_bin=ZK_STEP_SNARKJS,
            rapidsnark_bin=RAPIDSNARK_BIN,
            input_path=input_path,
            wasm_path=ZK_STEP_WASM,
            zkey_path=ZK_STEP_ZKEY,
            proof_path=proof_path,
            public_path=public_path,
            timeout_sec=ZK_STEP_TIMEOUT_SEC,
            error_hint="zk_step prove failed",
        )

        with open(proof_path, "r", encoding="utf-8") as f:
            proof = json.load(f)
        with open(public_path, "r", encoding="utf-8") as f:
            public_signals = json.load(f)
    return {"proof": proof, "public_signals": public_signals, "inputs": inputs}


def generate_tsip_proof(inputs: dict):
    with tempfile.TemporaryDirectory(prefix="tsip_main_client_") as td:
        input_path = os.path.join(td, "input.json")
        proof_path = os.path.join(td, "proof.json")
        public_path = os.path.join(td, "public.json")
        str_inputs = {k: str(v) for k, v in inputs.items()}
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(str_inputs, f, ensure_ascii=True)
        prover = _resolve_prover(TSIP_PROVER, RAPIDSNARK_BIN)
        _run_fullprove(
            prover=prover,
            snarkjs_bin=TSIP_SNARKJS,
            rapidsnark_bin=RAPIDSNARK_BIN,
            input_path=input_path,
            wasm_path=TSIP_WASM,
            zkey_path=TSIP_ZKEY,
            proof_path=proof_path,
            public_path=public_path,
            timeout_sec=TSIP_TIMEOUT_SEC,
            error_hint="tsip prove failed",
        )
        with open(proof_path, "r", encoding="utf-8") as f:
            proof = json.load(f)
        with open(public_path, "r", encoding="utf-8") as f:
            public_signals = json.load(f)
    return {"proof": proof, "public_signals": public_signals}


def _summarize_local_proof_error(err: str) -> str:
    msg = str(err or "").strip()
    if not msg:
        return ""
    msg = msg.splitlines()[0].strip()
    return msg[:180]


def _get_or_generate_user_secret(user_id: str, prev_state: dict | None, rng: random.Random) -> str:
    """P5: Return the per-user hidden secret, generating it on first call.

    The secret is stored in the client's tsip_state and never transmitted to
    the server (only its HMAC commitment is).  Generating it from rng seeded
    per-user gives determinism across restart within a session.
    """
    if prev_state is not None:
        s = prev_state.get("user_secret", "")
        if s:
            return str(s)
    # First time: derive a stable 32-byte secret from the user_id hash so
    # it survives state resets (deterministic but unpredictable to others).
    raw = hashlib.sha256(f"tsip_secret_v1:{user_id}".encode()).hexdigest()
    return raw


def _normalize_adwc_history(prev_state: dict | None) -> list[dict]:
    out: list[dict] = []
    if not isinstance(prev_state, dict):
        return out
    raw_hist = prev_state.get("adwc_history", [])
    if isinstance(raw_hist, list):
        for it in raw_hist:
            if not isinstance(it, dict):
                continue
            try:
                out.append(
                    {
                        "idx": int(it["idx"]),
                        "x": int(it["x"]),
                        "y": int(it["y"]),
                        "loc_commitment": str(it["loc_commitment"]),
                    }
                )
            except Exception:
                continue
    if out:
        out.sort(key=lambda x: int(x["idx"]))
        dedup: dict[int, dict] = {}
        for it in out:
            dedup[int(it["idx"])] = it
        out = [dedup[k] for k in sorted(dedup.keys())]
        return out
    if all(k in prev_state for k in ("x", "y", "loc_commitment")):
        accepted_count = max(1, int(prev_state.get("accepted_count", 1)))
        fallback_idx = max(0, accepted_count - 1)
        return [
            {
                "idx": fallback_idx,
                "x": int(prev_state["x"]),
                "y": int(prev_state["y"]),
                "loc_commitment": str(prev_state["loc_commitment"]),
            }
        ]
    return []


def _recover_tsip_state_from_server(
    user_id: str,
    recovery: dict,
    trajectory,
) -> tuple[dict | None, str]:
    """Rebuild local TSIP state from shuffler commitment snapshot when possible.

    Recovery is commitment-level: the client fetches latest chain/adwc history
    from shuffler and tries to map those commitments back to local trajectory
    points. This currently requires a deterministic local trajectory source
    (e.g., GeoLife/T-Drive replay data).
    """
    if not isinstance(recovery, dict):
        return None, "invalid recovery payload"
    if not recovery.get("ok"):
        return None, str(recovery.get("error", "recovery not ok"))
    if not recovery.get("exists"):
        return None, "no remote state"
    if not trajectory:
        return None, "trajectory unavailable"

    target_loc_commitment = str(recovery.get("loc_commitment", "")).strip()
    target_chain_commitment = str(recovery.get("chain_commitment", "")).strip()
    if not target_loc_commitment or not target_chain_commitment:
        return None, "missing loc/chain commitment"

    accepted_count = int(recovery.get("accepted_count", 0) or 0)
    if accepted_count <= 0:
        return None, "invalid accepted_count"
    current_i = int(accepted_count - 1)

    points: list[dict] = []
    for j, p in enumerate(trajectory):
        try:
            x_f, y_f, t_i = p
            x_i = int(round(float(x_f)))
            y_i = int(round(float(y_f)))
            t_i = int(t_i)
            w_i = int(tsip_window_id(t_i, TSIP_WINDOW_SEC))
            loc_i = compute_location_commitment(
                user_id=user_id,
                x=x_i,
                y=y_i,
                timestamp=t_i,
                window_id=w_i,
                prev_commitment="",
            )
            points.append(
                {
                    "traj_idx": int(j),
                    "x": int(x_i),
                    "y": int(y_i),
                    "timestamp": int(t_i),
                    "window_id": int(w_i),
                    "loc_commitment": str(loc_i),
                }
            )
        except Exception:
            continue
    if not points:
        return None, "no trajectory points"

    candidates = [p for p in points if p["loc_commitment"] == target_loc_commitment]
    if not candidates:
        return None, "cannot map remote latest commitment to local trajectory"

    raw_hist = recovery.get("adwc_history", [])
    hist: list[dict] = []
    if isinstance(raw_hist, list):
        for it in raw_hist:
            if not isinstance(it, dict):
                continue
            try:
                hist.append({"idx": int(it["idx"]), "loc_commitment": str(it["loc_commitment"])})
            except Exception:
                continue
    if not hist:
        hist = [{"idx": int(current_i), "loc_commitment": target_loc_commitment}]
    hist.sort(key=lambda z: int(z["idx"]))

    chosen_curr: dict | None = None
    chosen_hist: list[dict] = []
    for cand in candidates:
        offset = int(cand["traj_idx"]) - int(current_i)
        mapped: list[dict] = []
        ok = True
        for it in hist:
            hidx = int(it["idx"])
            tj = max(0, min(len(points) - 1, hidx + offset))
            pp = points[tj]
            if str(pp["loc_commitment"]) != str(it["loc_commitment"]):
                ok = False
                break
            mapped.append(
                {
                    "idx": int(hidx),
                    "x": int(pp["x"]),
                    "y": int(pp["y"]),
                    "loc_commitment": str(pp["loc_commitment"]),
                }
            )
        if ok:
            chosen_curr = cand
            chosen_hist = mapped
            break
    if chosen_curr is None:
        return None, "cannot align adwc_history commitments with local trajectory"

    recovered_secret = _get_or_generate_user_secret(user_id, None, random.Random(0))
    keep = max(2, int(TSIP_ADWC_WINDOW_K) + 1)
    resolved_mode = normalize_mode(str(recovery.get("mode", TSIP_FORCE_MODE)))
    resolved_tier = normalize_tier(str(recovery.get("tier", TSIP_FORCE_TIER)))
    modeset_bitmap = int(build_modeset_bitmap(TSIP_ALLOWED_MODES))
    salt_seed = hashlib.sha256(f"tsip_modeset_salt_v3:{user_id}".encode("utf-8")).hexdigest()
    modeset_salt = int(int(salt_seed, 16) % _tsip.SNARK_FIELD)
    modeset_commitment = str(compute_modeset_commitment_field(modeset_bitmap, modeset_salt))
    mode_tag = str(compute_mode_tag_field(resolved_mode, recovered_secret))
    remote_modeset_commitment = str(recovery.get("modeset_commitment", "")).strip()
    remote_mode_tag = str(recovery.get("mode_tag", "")).strip()
    remote_tier_vmax_sq = int(recovery.get("tier_vmax_sq", 0) or 0)
    recovered_state = {
        "x": int(chosen_curr["x"]),
        "y": int(chosen_curr["y"]),
        "timestamp": int(chosen_curr["timestamp"]),
        "window_id": int(chosen_curr["window_id"]),
        "loc_commitment": str(target_loc_commitment),
        "chain_commitment": str(target_chain_commitment),
        "cursor": int(chosen_curr["traj_idx"]),
        "user_secret": recovered_secret,
        "accepted_count": int(accepted_count),
        "adwc_history": chosen_hist[-keep:],
        "adwc_profile": TSIP_ADWC_PROFILE,
        "adwc_window_k": int(TSIP_ADWC_WINDOW_K),
        "version": "v3",
        "mode": resolved_mode,
        "tier": resolved_tier,
        "tier_vmax_sq": int(remote_tier_vmax_sq if remote_tier_vmax_sq > 0 else tier_vmax_sq(resolved_tier)),
        "modeset_bitmap": int(modeset_bitmap),
        "modeset_salt": int(modeset_salt),
        "modeset_commitment": str(remote_modeset_commitment or modeset_commitment),
        "mode_tag": str(remote_mode_tag or mode_tag),
        "warmup_count": int(recovery.get("warmup_count", 0) or 0),
        "enrollment_epoch": int(recovery.get("enrollment_epoch", 1) or 1),
    }
    return recovered_state, ""


def _select_adwc_anchor(history: list[dict], accepted_count: int, window_k: int) -> tuple[dict, int, int]:
    current_i = max(1, int(accepted_count))
    anchor_i = max(0, current_i - max(1, int(window_k)))
    for it in history:
        if int(it.get("idx", -1)) == anchor_i:
            return it, anchor_i, current_i
    if anchor_i == 0 and history:
        return history[0], 0, current_i
    raise RuntimeError(f"missing ADWC anchor idx={anchor_i}; history_len={len(history)}")


def _next_adwc_history(history: list[dict], k: int, current_i: int, x: int, y: int, loc_commitment: str) -> list[dict]:
    out = list(history)
    out.append({"idx": int(current_i), "x": int(x), "y": int(y), "loc_commitment": str(loc_commitment)})
    out.sort(key=lambda z: int(z["idx"]))
    if len(out) > max(2, int(k) + 1):
        out = out[-(int(k) + 1):]
    return out


def _default_modeset_salt_field(user_id: str) -> int:
    digest = hashlib.sha256(f"tsip_modeset_salt_v3:{user_id}".encode("utf-8")).hexdigest()
    return int(int(digest, 16) % _tsip.SNARK_FIELD)


def _mode_selector_witness(selected_mode: str) -> tuple[int, int, int, int]:
    m = normalize_mode(selected_mode)
    return (
        1 if m == "walk" else 0,
        1 if m == "bike" else 0,
        1 if m == "vehicle" else 0,
        1 if m == "transit" else 0,
    )


def _build_ea_attestation(
    user_id: str,
    declared_tier_vmax_sq: int,
    declared_sc_field: str,
    declared_modeset_commitment: str,
) -> dict:
    base = {
        "uid": str(user_id),
        "tier_vmax_sq": int(declared_tier_vmax_sq),
        "com_sec": str(declared_sc_field),
        "com_modeset": str(declared_modeset_commitment),
        "exp": int(time.time()) + max(30, int(TSIP_EA_EXP_SEC)),
        "kid": str(TSIP_EA_KID),
    }
    if TSIP_EA_SIGNING_SK:
        return sign_attestation(TSIP_EA_SIGNING_SK, base)
    out = dict(base)
    out["sig"] = ""
    return out


def _resolve_user_mode_tier_context(user_id: str, prev_state: dict | None) -> dict:
    prev_mode = normalize_mode((prev_state or {}).get("mode", TSIP_MODE_DEFAULT))
    prev_tier = normalize_tier((prev_state or {}).get("tier", TSIP_TIER_DEFAULT))
    desired_mode = normalize_mode(TSIP_FORCE_MODE or prev_mode or TSIP_MODE_DEFAULT)
    desired_tier = normalize_tier(TSIP_FORCE_TIER or prev_tier or TSIP_TIER_DEFAULT)

    tier_sq = int(tier_vmax_sq(desired_tier))
    if int(mode_vmax_sq(desired_mode)) > tier_sq:
        # Circuit enforces mode_vmax_sq(selected) <= tier_vmax_sq.
        desired_mode = desired_tier

    prev_tier_sq = int((prev_state or {}).get("tier_vmax_sq", tier_vmax_sq(prev_tier)) or 0)
    tier_changed = prev_state is not None and int(prev_tier_sq) != int(tier_sq)

    if prev_state is not None and not tier_changed and "modeset_bitmap" in prev_state and "modeset_salt" in prev_state:
        bitmap = int(prev_state.get("modeset_bitmap", 0) or 0) & 0xF
        salt = int(prev_state.get("modeset_salt", 0) or 0)
    else:
        bitmap = int(build_modeset_bitmap(TSIP_ALLOWED_MODES))
        salt = int(_default_modeset_salt_field(user_id))

    # Ensure selected mode is always part of the committed mode-set.
    if not modeset_contains_mode(bitmap, desired_mode):
        bitmap = int((bitmap | (1 << int(mode_id(desired_mode)))) & 0xF)

    modeset_commitment = str(compute_modeset_commitment_field(bitmap, salt))
    stored_modeset_commitment = str((prev_state or {}).get("modeset_commitment", "")).strip()
    modeset_changed = prev_state is not None and stored_modeset_commitment and (stored_modeset_commitment != modeset_commitment)
    mode_changed = prev_state is not None and normalize_mode((prev_state or {}).get("mode", desired_mode)) != desired_mode

    needs_reenroll = prev_state is None or tier_changed or modeset_changed or mode_changed
    mode_only_reenroll = prev_state is not None and mode_changed and (not tier_changed) and (not modeset_changed)
    return {
        "mode": desired_mode,
        "tier": desired_tier,
        "tier_vmax_sq": int(tier_sq),
        "modeset_bitmap": int(bitmap),
        "modeset_salt": int(salt),
        "modeset_commitment": str(modeset_commitment),
        "mode_changed": bool(mode_changed),
        "tier_changed": bool(tier_changed),
        "modeset_changed": bool(modeset_changed),
        "needs_reenroll": bool(needs_reenroll),
        "mode_only_reenroll": bool(mode_only_reenroll),
    }


def build_tsip_payload(
    user_id: str,
    prev_state: dict | None,
    rng: random.Random,
    malicious: bool,
    trajectory=None,
    idx: list | None = None,
):
    """Build the TSIP payload for one round.

    *idx* is the list of cell indices being reported.  When P4 payload binding
    is enabled the sorted indices are hashed into the chain commitment so the
    proof cannot be detached from the submitted data.
    """
    if not TSIP_ENABLE:
        return None, None, {}

    payload_idx = idx if idx is not None else []
    payload_digest = compute_payload_digest(payload_idx)
    payload_lo, payload_hi = split_payload_digest_fields(payload_digest)
    payload_commitment_field = int(compute_payload_commitment_field(payload_digest))
    user_secret = _get_or_generate_user_secret(user_id, prev_state, rng)
    secret_commitment = compute_secret_commitment(user_id, user_secret)
    secret_field = int(secret_hex_to_field(user_secret))
    user_id_field = int(user_id_to_field(user_id))
    secret_commitment_field = int(compute_secret_commitment_field(user_id, user_secret))

    mode_ctx = _resolve_user_mode_tier_context(user_id=user_id, prev_state=prev_state)
    selected_mode = str(mode_ctx["mode"])
    selected_tier = str(mode_ctx["tier"])
    declared_tier_vmax_sq = int(mode_ctx["tier_vmax_sq"])
    declared_modeset_bitmap = int(mode_ctx["modeset_bitmap"])
    declared_modeset_salt = int(mode_ctx["modeset_salt"])
    declared_modeset_commitment = str(mode_ctx["modeset_commitment"])
    declared_mode_tag = str(compute_mode_tag_field(selected_mode, user_secret))
    mode_s0, mode_s1, mode_s2, mode_s3 = _mode_selector_witness(selected_mode)

    def _build_enrollment_payload(
        curr_x: int,
        curr_y: int,
        curr_t: int,
        curr_window: int,
        next_cursor: int,
        prev_s: dict | None,
    ) -> tuple[dict, dict, dict]:
        curr_loc_commitment = compute_location_commitment(
            user_id=user_id,
            x=curr_x,
            y=curr_y,
            timestamp=curr_t,
            window_id=curr_window,
            prev_commitment="",
        )
        curr_chain_commitment = compute_chain_commitment(
            prev_chain_commitment="",
            location_commitment=curr_loc_commitment,
            timestamp=curr_t,
            window_id=curr_window,
            payload_digest=payload_digest,
            secret_commitment=secret_commitment,
        )
        ea_attestation = _build_ea_attestation(
            user_id=user_id,
            declared_tier_vmax_sq=declared_tier_vmax_sq,
            declared_sc_field=str(secret_commitment_field),
            declared_modeset_commitment=declared_modeset_commitment,
        )
        next_epoch = (int(prev_s.get("enrollment_epoch", 0) or 0) + 1) if prev_s else 1
        payload = {
            "version": "v3",
            "user_id": user_id,
            "timestamp": int(curr_t),
            "window_id": int(curr_window),
            "prev_loc_commitment": "",
            "curr_loc_commitment": str(curr_loc_commitment),
            "prev_chain_commitment": "",
            "curr_chain_commitment": str(curr_chain_commitment),
            "time_diff": 0,
            "step_dt_sq": 0,
            "tier_vmax_sq": int(declared_tier_vmax_sq),
            "tier_anchor_cap_sq": 0,
            "cap_policy_sq": 0,
            "proof": None,
            "public_signals": [],
            "payload_digest": str(payload_digest),
            "secret_commitment": str(secret_commitment),
            "payload_commitment_field": str(payload_commitment_field),
            "secret_commitment_field": str(secret_commitment_field),
            "anchor_loc_commitment": str(curr_loc_commitment),
            "modeset_commitment": str(declared_modeset_commitment),
            "mode_tag": str(declared_mode_tag),
            "ea_attestation": ea_attestation,
        }
        next_state = {
            "version": "v3",
            "x": int(curr_x),
            "y": int(curr_y),
            "timestamp": int(curr_t),
            "window_id": int(curr_window),
            "loc_commitment": str(curr_loc_commitment),
            "chain_commitment": str(curr_chain_commitment),
            "cursor": int(next_cursor),
            "user_secret": str(user_secret),
            "accepted_count": 1,
            "adwc_history": [
                {"idx": 0, "x": int(curr_x), "y": int(curr_y), "loc_commitment": str(curr_loc_commitment)}
            ],
            "adwc_profile": TSIP_ADWC_PROFILE,
            "adwc_window_k": int(TSIP_ADWC_WINDOW_K),
            "warmup_count": 1,
            "enrollment_epoch": int(next_epoch),
            "mode": str(selected_mode),
            "tier": str(selected_tier),
            "tier_vmax_sq": int(declared_tier_vmax_sq),
            "modeset_bitmap": int(declared_modeset_bitmap),
            "modeset_salt": int(declared_modeset_salt),
            "modeset_commitment": str(declared_modeset_commitment),
            "mode_tag": str(declared_mode_tag),
        }
        meta = {
            "proof_error": "",
            "adwc_anchor_idx": 0,
            "adwc_current_idx": 0,
            "re_enroll": bool(prev_s is not None),
            "mode_only_reenroll": bool(mode_ctx["mode_only_reenroll"]),
            "tier_changed": bool(mode_ctx["tier_changed"]),
        }
        return payload, next_state, meta

    def _build_followup_payload(
        prev_s: dict,
        prev_x: int,
        prev_y: int,
        prev_t: int,
        prev_loc_commitment: str,
        prev_chain_commitment: str,
        curr_x: int,
        curr_y: int,
        curr_t: int,
        curr_window: int,
        time_diff: int,
        next_cursor: int,
    ) -> tuple[dict, dict, dict]:
        curr_loc_commitment = compute_location_commitment(
            user_id=user_id,
            x=curr_x,
            y=curr_y,
            timestamp=curr_t,
            window_id=curr_window,
            prev_commitment=prev_chain_commitment,
        )
        curr_chain_commitment = compute_chain_commitment(
            prev_chain_commitment=prev_chain_commitment,
            location_commitment=curr_loc_commitment,
            timestamp=curr_t,
            window_id=curr_window,
            payload_digest=payload_digest,
            secret_commitment=secret_commitment,
        )

        history = _normalize_adwc_history(prev_s)
        accepted_count = max(1, int(prev_s.get("accepted_count", len(history) if history else 1)))
        if not history:
            history = [
                {
                    "idx": max(0, accepted_count - 1),
                    "x": int(prev_x),
                    "y": int(prev_y),
                    "loc_commitment": str(prev_loc_commitment),
                }
            ]
        anchor_state, anchor_i, current_i = _select_adwc_anchor(history, accepted_count, TSIP_ADWC_WINDOW_K)
        anchor_loc_commitment = str(anchor_state["loc_commitment"])

        step_dt = max(1, int(time_diff))
        step_dt_sq = int(step_dt * step_dt)
        tier_anchor_cap_sq = int(
            compute_tier_anchor_cap_sq(declared_tier_vmax_sq, TSIP_ADWC_WINDOW_K, step_dt_sq)
        )
        cap_policy_sq = int(compute_policy_cap_sq(tier_anchor_cap_sq, TSIP_POLICY_CAP_RATIO))

        inputs = {
            "x1": int(prev_x),
            "y1": int(prev_y),
            "x2": int(curr_x),
            "y2": int(curr_y),
            "x_anchor": int(anchor_state["x"]),
            "y_anchor": int(anchor_state["y"]),
            "hash_prev": int(commitment_to_field(prev_loc_commitment)),
            "hash_curr": int(commitment_to_field(curr_loc_commitment)),
            "hash_anchor": int(commitment_to_field(anchor_loc_commitment)),
            "step_dt_sq": int(step_dt_sq),
            "tier_vmax_sq": int(declared_tier_vmax_sq),
            "tier_anchor_cap_sq": int(tier_anchor_cap_sq),
            "cap_policy_sq": int(cap_policy_sq),
            "payload_lo": int(payload_lo),
            "payload_hi": int(payload_hi),
            "payload_commitment": int(payload_commitment_field),
            "secret": int(secret_field),
            "user_id_field": int(user_id_field),
            "secret_commitment": int(secret_commitment_field),
            "modeset_bitmap": int(declared_modeset_bitmap),
            "modeset_salt": int(declared_modeset_salt),
            "mode_s0": int(mode_s0),
            "mode_s1": int(mode_s1),
            "mode_s2": int(mode_s2),
            "mode_s3": int(mode_s3),
            "modeset_commitment": int(declared_modeset_commitment),
            "mode_tag": int(declared_mode_tag),
        }
        proof_data = {"proof": None, "public_signals": [], "error": ""}
        if TSIP_VERIFY_MODE == "full":
            try:
                proof_data = generate_tsip_proof(inputs)
            except Exception as e:
                if DEBUG_CLIENT and not malicious:
                    print("[DEBUG] tsip prove failed (treated as rejected sample):", str(e))
                proof_data = {"proof": None, "public_signals": [], "error": str(e)}

        ea_attestation = _build_ea_attestation(
            user_id=user_id,
            declared_tier_vmax_sq=declared_tier_vmax_sq,
            declared_sc_field=str(secret_commitment_field),
            declared_modeset_commitment=declared_modeset_commitment,
        )
        payload = {
            "version": "v3",
            "user_id": user_id,
            "timestamp": int(curr_t),
            "window_id": int(curr_window),
            "prev_loc_commitment": str(prev_loc_commitment),
            "curr_loc_commitment": str(curr_loc_commitment),
            "prev_chain_commitment": str(prev_chain_commitment),
            "curr_chain_commitment": str(curr_chain_commitment),
            "time_diff": int(step_dt),
            "step_dt_sq": int(step_dt_sq),
            "tier_vmax_sq": int(declared_tier_vmax_sq),
            "tier_anchor_cap_sq": int(tier_anchor_cap_sq),
            "cap_policy_sq": int(cap_policy_sq),
            "proof": proof_data["proof"],
            "public_signals": proof_data["public_signals"],
            "payload_digest": str(payload_digest),
            "secret_commitment": str(secret_commitment),
            "payload_commitment_field": str(payload_commitment_field),
            "secret_commitment_field": str(secret_commitment_field),
            "anchor_loc_commitment": str(anchor_loc_commitment),
            "modeset_commitment": str(declared_modeset_commitment),
            "mode_tag": str(declared_mode_tag),
            "ea_attestation": ea_attestation,
        }
        if malicious and ATTACK_TYPE not in {"boundary_teleport", "gradual_drift"}:
            # Keep local proof generation valid, then tamper wire payload for server-side rejection.
            payload["prev_loc_commitment"] = tamper_commitment_hex(prev_loc_commitment)
            payload["curr_chain_commitment"] = tamper_commitment_hex(curr_chain_commitment)

        next_history = _next_adwc_history(
            history=history,
            k=TSIP_ADWC_WINDOW_K,
            current_i=current_i,
            x=curr_x,
            y=curr_y,
            loc_commitment=curr_loc_commitment,
        )
        next_state = {
            "version": "v3",
            "x": int(curr_x),
            "y": int(curr_y),
            "timestamp": int(curr_t),
            "window_id": int(curr_window),
            "loc_commitment": str(curr_loc_commitment),
            "chain_commitment": str(curr_chain_commitment),
            "cursor": int(next_cursor),
            "user_secret": str(user_secret),
            "accepted_count": int(current_i + 1),
            "adwc_history": next_history,
            "adwc_profile": TSIP_ADWC_PROFILE,
            "adwc_window_k": int(TSIP_ADWC_WINDOW_K),
            "warmup_count": int(prev_s.get("warmup_count", 0) or 0) + 1,
            "enrollment_epoch": int(prev_s.get("enrollment_epoch", 1) or 1),
            "mode": str(selected_mode),
            "tier": str(selected_tier),
            "tier_vmax_sq": int(declared_tier_vmax_sq),
            "modeset_bitmap": int(declared_modeset_bitmap),
            "modeset_salt": int(declared_modeset_salt),
            "modeset_commitment": str(declared_modeset_commitment),
            "mode_tag": str(declared_mode_tag),
        }
        meta = {
            "proof_error": _summarize_local_proof_error(proof_data.get("error", "")),
            "adwc_anchor_idx": int(anchor_i),
            "adwc_current_idx": int(current_i),
            "re_enroll": False,
            "mode_only_reenroll": False,
            "tier_changed": False,
        }
        return payload, next_state, meta

    if trajectory:
        effective_trajectory = (
            apply_gradual_drift(trajectory) if malicious and ATTACK_TYPE == "gradual_drift" else trajectory
        )
        cursor = -1 if prev_state is None else int(prev_state.get("cursor", -1))
        next_idx = min(cursor + 1, len(effective_trajectory) - 1)
        honest_x_f, honest_y_f, _honest_t = trajectory[next_idx]
        curr_x_f, curr_y_f, curr_t = effective_trajectory[next_idx]
        curr_x = int(round(curr_x_f))
        curr_y = int(round(curr_y_f))
        curr_window = tsip_window_id(curr_t, TSIP_WINDOW_SEC)

        if prev_state is None or bool(mode_ctx["needs_reenroll"]):
            payload, next_state, meta = _build_enrollment_payload(
                curr_x=curr_x,
                curr_y=curr_y,
                curr_t=int(curr_t),
                curr_window=int(curr_window),
                next_cursor=int(next_idx),
                prev_s=prev_state,
            )
            if malicious and ATTACK_TYPE == "gradual_drift":
                meta["drift_offset_m"] = round(math.hypot(curr_x_f - honest_x_f, curr_y_f - honest_y_f), 3)
            return payload, next_state, meta

        prev_x = int(prev_state["x"])
        prev_y = int(prev_state["y"])
        prev_t = int(prev_state["timestamp"])
        prev_loc_commitment = str(prev_state["loc_commitment"])
        prev_chain_commitment = str(prev_state["chain_commitment"])
        time_diff = max(1, int(curr_t - prev_t))

        if malicious and ATTACK_TYPE == "boundary_teleport":
            time_diff = max(1, TSIP_WINDOW_SEC)
            curr_t = prev_t + time_diff
            curr_window = tsip_window_id(curr_t, TSIP_WINDOW_SEC)
            target = _boundary_teleport_target(prev_x, prev_y, TELEPORT_JUMP_M, TSIP_COORD_MAX)
            if target is not None:
                curr_x, curr_y = target
            else:
                print(
                    f"[WARN] boundary_teleport: no unclamped direction for jump={TELEPORT_JUMP_M}m "
                    f"from ({prev_x},{prev_y}) coord_max={TSIP_COORD_MAX}m — result may be inaccurate"
                )
                curr_x = int(round(clamp(prev_x + TELEPORT_JUMP_M, 0, TSIP_COORD_MAX - 1)))
                curr_y = prev_y

        payload, next_state, meta = _build_followup_payload(
            prev_s=prev_state,
            prev_x=prev_x,
            prev_y=prev_y,
            prev_t=prev_t,
            prev_loc_commitment=prev_loc_commitment,
            prev_chain_commitment=prev_chain_commitment,
            curr_x=curr_x,
            curr_y=curr_y,
            curr_t=int(curr_t),
            curr_window=int(curr_window),
            time_diff=int(time_diff),
            next_cursor=int(next_idx),
        )
        if malicious and ATTACK_TYPE == "gradual_drift":
            next_state["drift_target_x"] = float(prev_state.get("drift_target_x", next_state.get("x", curr_x)))
            next_state["drift_target_y"] = float(prev_state.get("drift_target_y", next_state.get("y", curr_y)))
            meta["drift_offset_m"] = round(math.hypot(curr_x_f - honest_x_f, curr_y_f - honest_y_f), 3)
        return payload, next_state, meta

    if prev_state is None or bool(mode_ctx["needs_reenroll"]):
        if prev_state is not None:
            curr_x = int(prev_state.get("x", 0) or 0)
            curr_y = int(prev_state.get("y", 0) or 0)
            curr_t = int(prev_state.get("timestamp", int(time.time())) or int(time.time())) + max(1, TSIP_WINDOW_SEC)
        elif malicious and ATTACK_TYPE == "boundary_teleport":
            curr_x = 0
            curr_y = int(CITY_SIZE_M) // 2
            curr_t = int(time.time())
        else:
            curr_x = int(round(rng.uniform(0, CITY_SIZE_M - 1)))
            curr_y = int(round(rng.uniform(0, CITY_SIZE_M - 1)))
            curr_t = int(time.time())
        curr_window = tsip_window_id(curr_t, TSIP_WINDOW_SEC)
        payload, next_state, meta = _build_enrollment_payload(
            curr_x=int(curr_x),
            curr_y=int(curr_y),
            curr_t=int(curr_t),
            curr_window=int(curr_window),
            next_cursor=int(prev_state.get("cursor", -1) if prev_state else -1),
            prev_s=prev_state,
        )
        if malicious and ATTACK_TYPE == "gradual_drift":
            drift_target_x, drift_target_y = _gradual_drift_target(curr_x, curr_y, CITY_SIZE_M)
            next_state["drift_target_x"] = float(drift_target_x)
            next_state["drift_target_y"] = float(drift_target_y)
            meta["drift_offset_m"] = 0.0
        return payload, next_state, meta

    prev_x = int(prev_state["x"])
    prev_y = int(prev_state["y"])
    prev_t = int(prev_state["timestamp"])
    prev_loc_commitment = str(prev_state["loc_commitment"])
    prev_chain_commitment = str(prev_state["chain_commitment"])
    time_diff = max(1, TSIP_WINDOW_SEC)
    curr_t = prev_t + time_diff
    if malicious and ATTACK_TYPE == "boundary_teleport":
        target = _boundary_teleport_target(prev_x, prev_y, TELEPORT_JUMP_M, CITY_SIZE_M)
        if target is not None:
            curr_x, curr_y = target
        else:
            print(
                f"[WARN] boundary_teleport: no unclamped direction for jump={TELEPORT_JUMP_M}m "
                f"from ({prev_x},{prev_y}) city={CITY_SIZE_M}m — result may be inaccurate"
            )
            curr_x = int(round(clamp(prev_x + TELEPORT_JUMP_M, 0, CITY_SIZE_M - 1)))
            curr_y = prev_y
    elif malicious and ATTACK_TYPE == "gradual_drift":
        target_x = float(prev_state.get("drift_target_x", _gradual_drift_target(prev_x, prev_y, CITY_SIZE_M)[0]))
        target_y = float(prev_state.get("drift_target_y", _gradual_drift_target(prev_x, prev_y, CITY_SIZE_M)[1]))
        max_step = float(mode_vmax_mps(selected_mode)) * float(time_diff)
        honest_radius = max(1.0, max_step * 0.8)
        honest_radius = rng.uniform(0.0, honest_radius)
        honest_angle = rng.uniform(0.0, 2.0 * math.pi)
        honest_curr_x = float(clamp(prev_x + math.cos(honest_angle) * honest_radius, 0, CITY_SIZE_M - 1))
        honest_curr_y = float(clamp(prev_y + math.sin(honest_angle) * honest_radius, 0, CITY_SIZE_M - 1))
        curr_x_f, curr_y_f = _gradual_drift_next_point(
            prev_reported_x=float(prev_x),
            prev_reported_y=float(prev_y),
            honest_prev_x=float(prev_x),
            honest_prev_y=float(prev_y),
            honest_curr_x=honest_curr_x,
            honest_curr_y=honest_curr_y,
            target_x=target_x,
            target_y=target_y,
            max_step=max_step,
            coord_cap=float(CITY_SIZE_M),
        )
        curr_x = int(round(curr_x_f))
        curr_y = int(round(curr_y_f))
    else:
        max_step = float(mode_vmax_mps(selected_mode)) * float(time_diff)
        honest_radius = max(1.0, max_step * 0.8)
        radius = rng.uniform(0.0, honest_radius)
        angle = rng.uniform(0.0, 2.0 * math.pi)
        curr_x = int(round(clamp(prev_x + math.cos(angle) * radius, 0, CITY_SIZE_M - 1)))
        curr_y = int(round(clamp(prev_y + math.sin(angle) * radius, 0, CITY_SIZE_M - 1)))
    curr_window = tsip_window_id(curr_t, TSIP_WINDOW_SEC)
    payload, next_state, meta = _build_followup_payload(
        prev_s=prev_state,
        prev_x=prev_x,
        prev_y=prev_y,
        prev_t=prev_t,
        prev_loc_commitment=prev_loc_commitment,
        prev_chain_commitment=prev_chain_commitment,
        curr_x=curr_x,
        curr_y=curr_y,
        curr_t=int(curr_t),
        curr_window=int(curr_window),
        time_diff=int(time_diff),
        next_cursor=int(prev_state.get("cursor", -1) if prev_state else -1),
    )
    if malicious and ATTACK_TYPE == "gradual_drift":
        drift_target = _gradual_drift_target(prev_x, prev_y, CITY_SIZE_M)
        next_state["drift_target_x"] = float(prev_state.get("drift_target_x", drift_target[0]))
        next_state["drift_target_y"] = float(prev_state.get("drift_target_y", drift_target[1]))
        meta["drift_offset_m"] = round(math.hypot(float(curr_x) - honest_curr_x, float(curr_y) - honest_curr_y), 3)
    return payload, next_state, meta

def proof_statistic_S(seed: int, trajectory, label: str, debug: bool = False):
    u = compute_displacement_vector(trajectory)
    m = PROOF_M
    dim = len(u)
    a = gaussian_vectors(seed, m, dim)
    z = []
    for j in range(m):
        s = 0.0
        aj = a[j]
        for i in range(dim):
            s += u[i] * aj[i]
        z.append(s)
    S = sum(v * v for v in z)
    over = sum(1 for v in u if v > 1.0)
    if debug:
        print("[DEBUG] proof", label, "S=", round(S, 6), "m=", m, "dim=", dim, "steps_over_max=", over)
    return S

def apply_teleport(trajectory, jump_m: float, index: int):
    if len(trajectory) < 2:
        return trajectory
    idx = max(1, min(index, len(trajectory) - 1))
    x_prev, y_prev, _t_prev = trajectory[idx - 1]
    target_a = (CITY_SIZE_M - 1e-6, CITY_SIZE_M - 1e-6)
    target_b = (0.0, 0.0)
    da = abs(x_prev - target_a[0]) + abs(y_prev - target_a[1])
    db = abs(x_prev - target_b[0]) + abs(y_prev - target_b[1])
    tx, ty = target_a if da >= db else target_b
    dx = tx - x_prev
    dy = ty - y_prev
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= 1e-9:
        return trajectory
    scale = min(1.0, jump_m / dist) if jump_m > 0 else 0.0
    x_new = clamp(x_prev + dx * scale, 0, CITY_SIZE_M - 1e-6)
    y_new = clamp(y_prev + dy * scale, 0, CITY_SIZE_M - 1e-6)
    out = list(trajectory)
    x_old, y_old, t_old = out[idx]
    out[idx] = (x_new, y_new, t_old)
    return out

def make_idx_and_val(
    user_seed: int,
    report_idx: int = 0,
    round_id: int = 0,
    proof_seed: int = 0,
    prp_seed_a: int = 0,
    prp_seed_r: int = 0,
    malicious: bool = False,
    trajectory_override=None,
):
    """
    返回 idx/val:
      - idx 长度 KPRIME，且全部唯一
      - 前 K 个是真实 Top-k（不足 K 用 0 值 padding）
      - 后 KD 个是 dummy（val 固定 DUMMY_Q）
    """
    # 1) 合成轨迹
    rng = random.Random(user_seed)
    traj = list(trajectory_override) if trajectory_override is not None else gen_synthetic_trajectory(rng)
    attack_meta = {}
    if malicious and ATTACK_TYPE == "gradual_drift":
        honest_traj = list(traj)
        coord_cap_hint = None if trajectory_override is not None else CITY_SIZE_M
        traj = apply_gradual_drift(traj, coord_cap_hint=coord_cap_hint)
        attack_meta["drift_endpoint_m"] = round(
            math.hypot(traj[-1][0] - honest_traj[-1][0], traj[-1][1] - honest_traj[-1][1]),
            3,
        )
    elif malicious and ATTACK_TYPE != "boundary_teleport":
        traj = apply_teleport(traj, TELEPORT_JUMP_M, TELEPORT_INDEX)
    proof = None
    zk_step = None
    if PROOF_ENABLE:
        debug = DEBUG_CLIENT and (report_idx % max(1, DEBUG_CLIENT_EVERY) == 0)
        label = "malicious" if malicious else "normal"
        s_val = proof_statistic_S(proof_seed, traj, label=label, debug=debug)
        proof = {"s": s_val, "m": PROOF_M, "dim": len(traj) - 1}
        if PROOF_S_THRESHOLD > 0 and s_val > PROOF_S_THRESHOLD:
            print("[WARN] proof S over threshold:", s_val, ">", PROOF_S_THRESHOLD)
        if PROOF_TELEPORT_TEST and report_idx == 0 and not malicious:
            traj_tp = apply_teleport(traj, TELEPORT_JUMP_M, TELEPORT_INDEX)
            s_tp = proof_statistic_S(proof_seed, traj_tp, label="teleport", debug=debug)
            if PROOF_S_THRESHOLD > 0 and s_tp <= PROOF_S_THRESHOLD:
                print("[WARN] teleport S not over threshold:", s_tp, "<=", PROOF_S_THRESHOLD)
    if ZK_STEP_ENABLE:
        inputs = build_zk_step_inputs(traj)
        try:
            zk_step = generate_zk_step_proof(inputs)
        except Exception as e:
            if malicious:
                if DEBUG_CLIENT:
                    print("[DEBUG] expected malicious zk prove failure:", str(e))
                zk_step = {"proof": None, "public_signals": None, "inputs": inputs, "error": str(e)}
            else:
                fallback_err = e
                fallback_inputs = None
                if ZK_STEP_FALLBACK_SCAN:
                    fallback_inputs = find_feasible_zk_step_inputs(traj)
                if fallback_inputs is not None and fallback_inputs != inputs:
                    try:
                        zk_step = generate_zk_step_proof(fallback_inputs)
                        if DEBUG_CLIENT:
                            print(
                                "[WARN] honest zk_step fallback used:",
                                "original_inputs=", inputs,
                                "fallback_inputs=", fallback_inputs,
                            )
                    except Exception as e2:
                        fallback_err = e2
                if zk_step is None:
                    if ZK_STEP_HONEST_SOFT_FAIL:
                        if DEBUG_CLIENT:
                            print("[WARN] honest zk_step soft-fail:", str(fallback_err))
                        zk_step = {"proof": None, "public_signals": None, "inputs": inputs, "error": str(fallback_err)}
                    else:
                        raise fallback_err

    # 2) dwell time 统计
    cell_visits = compute_cell_dwell(traj)

    # 3) 取 Top-K（按 dwell 降序）
    items = sorted(cell_visits.items(), key=lambda kv: -kv[1])
    top_items = items[:K]
    assert len(top_items) <= K
    top_idx = [c for c, _ in top_items]
    top_val = [quantize_time(t) for _, t in top_items]

    # 4) 不足 K 的补齐（补随机未访问 cell，val=0）
    if len(top_idx) < K:
        used = set(top_idx)
        # 从剩余 cell 中抽
        candidates = [i for i in range(DOMAIN) if i not in used]
        pad = rng.sample(candidates, K - len(top_idx))
        top_idx += pad
        top_val += [0] * len(pad)

    # 5) dummy 注入：从“未使用 cell”里采样 KD 个，val 固定 DUMMY_Q
    used = set(top_idx)
    candidates = [i for i in range(DOMAIN) if i not in used]
    dummy_idx = rng.sample(candidates, KD)
    dummy_val = [int(clamp(DUMMY_Q, 0, QMAX))] * KD

    idx_plain = top_idx + dummy_idx
    val = top_val + dummy_val

    # Optional protocol-compatibility path used by utility sweep baselines.
    # Keep report shape (idx/val lengths + uniqueness) unchanged for pipeline compatibility.
    if REPORT_PROTOCOL != "default":
        idx_plain, val = _build_sparse_protocol_report(
            rng=rng,
            truth_cell=top_idx[0] if top_idx else idx_plain[0],
            protocol=REPORT_PROTOCOL,
            epsilon=REPORT_EPSILON,
        )

    if PRP_ENABLE:
        idx = [
            prp(prp_seed_a, prp(prp_seed_r, c, DOMAIN, rounds=PRP_ROUNDS), DOMAIN, rounds=PRP_ROUNDS)
            for c in idx_plain
        ]
    else:
        idx = idx_plain

    # 6) 强约束（你 M1 的校验会依赖这个）
    assert len(idx) == KPRIME and len(val) == KPRIME
    assert len(set(idx)) == KPRIME
    assert all(0 <= c < DOMAIN for c in idx)
    assert all(0 <= v <= QMAX for v in val)

    if report_idx % max(1, DEBUG_CLIENT_EVERY) == 0:
        total_dwell = sum(cell_visits.values())
        if DEBUG_CLIENT:
            top_preview = [
                (top_items[i][0], top_items[i][1], top_val[i])
                for i in range(min(5, len(top_items)))
            ]
            print(
                "[DEBUG] seed=", user_seed,
                "points=", len(traj),
                "unique_cells=", len(cell_visits),
                "total_dwell_sec=", total_dwell,
                "top5(cell,dwell,q)=", top_preview,
                "start=", traj[0],
                "end=", traj[-1],
            )
            if DEBUG_TOPK:
                print("[DEBUG] topk(cell_id,dwell_sec)=", top_items)
        if DEBUG_TOPK:
            record = {
                "seed": user_seed,
                "report_idx": report_idx,
                "points": len(traj),
                "unique_cells": len(cell_visits),
                "total_dwell_sec": total_dwell,
                "k": K,
                "topk_size": len(top_items),
                "topk": top_items,
            }
            with open(DEBUG_TOPK_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=True) + "\n")
    return idx, val, proof, zk_step, attack_meta

def validate_unique_idx(idx, val, seed, round_id, submission_id):
    if len(idx) == len(set(idx)):
        return True
    counts = {}
    for x in idx:
        counts[x] = counts.get(x, 0) + 1
    dups = [k for k, v in counts.items() if v > 1]
    print("duplicate idx detected:", dups)
    print(
        "seed=", seed,
        "round_id=", round_id,
        "submission_id=", submission_id,
        "K=", K,
        "KD=", KD,
        "KPRIME=", KPRIME,
        "DOMAIN=", DOMAIN,
        "idx=", idx,
        "val=", val,
    )
    return False

def secret_share_vals(val):
    """
    vA = r
    vR = (v - r) mod 2^32
    """
    valA = []
    valR = []
    for v in val:
        r = random.getrandbits(32)
        a = r & MASK
        b = (int(v) - a) & MASK
        valA.append(a)
        valR.append(b)
    return valA, valR

def post_report(url: str, report: dict):
    try:
        resp = requests.post(url, json=report, timeout=REPORT_TIMEOUT_SEC)
        status = resp.status_code
        try:
            data = resp.json()
        except Exception:
            data = {"ok": False, "error": resp.text}
        ok = (status == 200) and bool(data.get("ok", True))
        return ok, data, status
    except Exception as e:
        return False, {"ok": False, "error": str(e)}, None

def main():
    if DEBUG_QUANT_TEST:
        quantization_self_test()
    shuffler_health = wait_for_shuffler()
    rid = new_round_id()
    print("new round:", rid)
    if DEBUG_RANDOMNESS:
        randomness_self_test(rid)
    ensure_zk_step_ready()
    ensure_tsip_ready()
    if TSIP_USER_SCOPE not in {"stable", "round"}:
        raise RuntimeError(f"invalid TSIP_USER_SCOPE: {TSIP_USER_SCOPE}")
    if ZK_STEP_ENABLE:
        print("[INFO] zk_step prover:", _resolve_prover(ZK_STEP_PROVER, RAPIDSNARK_BIN))
    if TSIP_ENABLE:
        print("[INFO] tsip prover:", _resolve_prover(TSIP_PROVER, RAPIDSNARK_BIN))
        print("[INFO] tsip verify mode:", TSIP_VERIFY_MODE)
        print("[INFO] tsip loc hash mode:", TSIP_LOC_HASH_MODE)
        print("[INFO] tsip user scope:", TSIP_USER_SCOPE)
        print(
            "[INFO] tsip v3 profile:",
            TSIP_ADWC_PROFILE,
            "circuit=",
            TSIP_CIRCUIT_PROFILE,
            "window_k=",
            TSIP_ADWC_WINDOW_K,
            "policy_cap_ratio=",
            TSIP_POLICY_CAP_RATIO,
            "mode_default=",
            TSIP_FORCE_MODE,
            "tier_default=",
            TSIP_FORCE_TIER,
            "allowed_modes=",
            ",".join(TSIP_ALLOWED_MODES),
        )
    if PRP_ENABLE and DOMAIN < PRP_MIN_DOMAIN:
        print("[WARN] PRP domain is small:", DOMAIN, "recommended >=", PRP_MIN_DOMAIN)
    prp_seed_a = 0
    prp_seed_r = 0
    if PRP_ENABLE:
        share_a = fetch_key_share(CLOVER_SHARE_URL_A, CLOVER_CLIENT_TOKEN_A)
        share_r = fetch_key_share(CLOVER_SHARE_URL_R, CLOVER_CLIENT_TOKEN_R)
        prp_seed_a = derive_prp_seed_from_share(rid, share_a, DOMAIN, "A")
        prp_seed_r = derive_prp_seed_from_share(rid, share_r, DOMAIN, "R")
    proof_seed = fetch_seed(rid) if PROOF_ENABLE else 0
    tsip_state = load_tsip_state()
    if TSIP_ENABLE and TSIP_AUTO_RESET_ON_EMPTY and isinstance(shuffler_health, dict):
        if int(shuffler_health.get("tsip_users", -1)) == 0 and tsip_state:
            print("[INFO] reset local tsip_state because shuffler tsip_users=0")
            tsip_state = {}
    dataset_records = load_geolife_trajectories()
    report_total = len(dataset_records) if TRAJ_SOURCE in REAL_TRAJ_SOURCES else max(1, CLIENT_TOTAL)
    if TRAJ_SOURCE in REAL_TRAJ_SOURCES:
        print(
            f"[INFO] trajectory source: {TRAJ_SOURCE}",
            "path=", GEO_TRAJ_PATH,
            "geo_max_users=", GEO_MAX_USERS,
            "loaded_users=", len(dataset_records),
            "report_total=", report_total,
        )
    else:
        print(
            "[INFO] trajectory source: synthetic",
            "client_total=", CLIENT_TOTAL,
            "report_total=", report_total,
            "fixed_synth_seeds=", FIXED_SYNTHETIC_SEEDS,
            "experiment_seed_base=", EXPERIMENT_SEED_BASE,
        )
    if REPORT_PROTOCOL in {"nebula", "ldp"}:
        print("[INFO] report protocol:", REPORT_PROTOCOL, "report_epsilon=", REPORT_EPSILON)
    else:
        print("[INFO] report protocol:", REPORT_PROTOCOL)
    total = 0
    valid_clients = 0
    rejected = 0
    malicious_total = 0
    malicious_rejected = 0
    false_rejects = 0
    reject_reason_counter = Counter()
    local_tsip_prove_fail_honest_counter = Counter()
    local_tsip_prove_fail_malicious_counter = Counter()
    gradual_drift_offsets = []
    gradual_drift_terminal_offsets = {}
    for i in range(report_total):
        round_id = rid
        if TRAJ_SOURCE in REAL_TRAJ_SOURCES:
            record = dataset_records[i]
            if TSIP_USER_SCOPE == "round":
                user_id = f"r{rid}_{TRAJ_SOURCE}_{record['user_id']}"
            else:
                user_id = f"{TRAJ_SOURCE}_{record['user_id']}"
            trajectory = geolife_trajectory_points(record)
        else:
            record = None
            if TSIP_USER_SCOPE == "round":
                user_id = f"r{rid}_user_{i:04d}"
            else:
                user_id = f"user_{i:04d}"
            trajectory = None
        submission_id = f"U{i}_{uuid.uuid4().hex[:8]}"

        if TRAJ_SOURCE not in REAL_TRAJ_SOURCES and FIXED_SYNTHETIC_SEEDS:
            seed = _stable_u64("synthetic", EXPERIMENT_SEED_BASE, user_id)
        else:
            seed = random.getrandbits(64)
        is_malicious = _is_malicious_client(user_id)

        # A2: Identity Swap — malicious client borrows the user_id of a neighbour,
        # breaking that neighbour's commitment chain on the next round.
        effective_user_id = user_id
        if is_malicious and ATTACK_TYPE == "identity_swap" and report_total > 1:
            swap_target = (i + 1) % report_total
            if TRAJ_SOURCE in REAL_TRAJ_SOURCES and swap_target < len(dataset_records):
                swap_rec = dataset_records[swap_target]
                effective_user_id = (
                    f"r{rid}_{TRAJ_SOURCE}_{swap_rec['user_id']}" if TSIP_USER_SCOPE == "round"
                    else f"{TRAJ_SOURCE}_{swap_rec['user_id']}"
                )
            else:
                effective_user_id = (
                    f"r{rid}_user_{swap_target:04d}" if TSIP_USER_SCOPE == "round"
                    else f"user_{swap_target:04d}"
                )

        idx, val, proof, zk_step, attack_meta = make_idx_and_val(
            user_seed=seed,
            report_idx=i,
            round_id=round_id,
            proof_seed=proof_seed,
            prp_seed_a=prp_seed_a,
            prp_seed_r=prp_seed_r,
            malicious=is_malicious,
            trajectory_override=trajectory,
        )
        if not validate_unique_idx(idx, val, seed, round_id, submission_id):
            raise RuntimeError("duplicate idx generated; aborting send")
        valA, valR = secret_share_vals(val)
        tsip_payload = None
        next_tsip_state = None
        tsip_meta = {}
        if TSIP_ENABLE:
            # A5: Replay — malicious client re-submits its *previous* tsip state
            # (stale prev_loc_commitment) instead of the current one.
            if is_malicious and ATTACK_TYPE == "replay" and user_id in tsip_state:
                # Use a deliberately stale state; the shuffler will reject because
                # the stored commitment has already advanced.
                prev_tsip = tsip_state.get(user_id)  # intentionally re-use old state
            else:
                prev_tsip = tsip_state.get(effective_user_id)
            if prev_tsip is None:
                rec = fetch_tsip_recovery_state(effective_user_id)
                if rec.get("ok") and rec.get("exists"):
                    recovered_state, recover_err = _recover_tsip_state_from_server(
                        user_id=effective_user_id,
                        recovery=rec,
                        trajectory=trajectory,
                    )
                    if recovered_state is not None:
                        prev_tsip = recovered_state
                        tsip_state[effective_user_id] = recovered_state
                        print(
                            "[INFO] recovered local tsip_state from shuffler snapshot:",
                            effective_user_id,
                            "accepted_count=",
                            recovered_state.get("accepted_count"),
                            "cursor=",
                            recovered_state.get("cursor"),
                        )
                    else:
                        print(
                            "[WARN] missing local tsip_state and replay recovery failed:",
                            effective_user_id,
                            "accepted_count=",
                            rec.get("accepted_count"),
                            "latest_loc_commitment=",
                            str(rec.get("loc_commitment", ""))[:16] + "...",
                            "reason=",
                            (recover_err or "unknown"),
                        )
            if DEBUG_CLIENT and prev_tsip is not None:
                print(
                    "[DEBUG] tsip prev_loc before submit:",
                    user_id,
                    str(prev_tsip.get("loc_commitment", "")),
                )
            tsip_payload, next_tsip_state, tsip_meta = build_tsip_payload(
                user_id=effective_user_id,
                prev_state=prev_tsip,
                rng=random.Random(seed ^ 0x5A5A5A5A),
                malicious=is_malicious,
                trajectory=trajectory,
                idx=idx,  # P4: pass cell indices for payload binding
            )
            proof_error = str(tsip_meta.get("proof_error", "")).strip()
            if proof_error:
                if is_malicious:
                    local_tsip_prove_fail_malicious_counter[proof_error] += 1
                else:
                    local_tsip_prove_fail_honest_counter[proof_error] += 1
            if is_malicious and ATTACK_TYPE == "gradual_drift":
                drift_offset_m = tsip_meta.get("drift_offset_m")
                if drift_offset_m is not None:
                    drift_offset_m = float(drift_offset_m)
                    gradual_drift_offsets.append(drift_offset_m)
                    gradual_drift_terminal_offsets[effective_user_id] = drift_offset_m
        elif is_malicious and ATTACK_TYPE == "gradual_drift":
            drift_offset_m = attack_meta.get("drift_endpoint_m")
            if drift_offset_m is not None:
                drift_offset_m = float(drift_offset_m)
                gradual_drift_offsets.append(drift_offset_m)
                gradual_drift_terminal_offsets[effective_user_id] = drift_offset_m

        reportA = {
            "round_id": round_id,
            "submission_id": submission_id,
            "idx": idx,
            "val": valA,
        }
        reportR = {
            "round_id": round_id,
            "submission_id": submission_id,
            "idx": idx,
            "val": valR,
        }
        if PROOF_ENABLE:
            reportA["proof"] = proof
            reportR["proof"] = proof
        if ZK_STEP_ENABLE:
            reportA["zk_step"] = zk_step
            reportR["zk_step"] = zk_step
        if TSIP_ENABLE:
            reportA["tsip"] = tsip_payload
            reportR["tsip"] = tsip_payload

        ok_a, data_a, _ = post_report(SHUFFLER_URL_A, reportA)
        ok_r, data_r, _ = post_report(SHUFFLER_URL_R, reportR)
        accepted = ok_a and ok_r

        if i % 20 == 0:
            print("sent", i, "A_ok=", ok_a, "R_ok=", ok_r, "malicious=", is_malicious, "A_resp=", data_a, "R_resp=", data_r)

        total += 1
        if accepted:
            valid_clients += 1
            if TSIP_ENABLE and next_tsip_state is not None:
                # For identity_swap: store under effective_user_id (the swapped ID)
                # so we pollute the victim's TSIP state on the shuffler side.
                # For replay: do NOT update local state so next round re-uses same commitment.
                store_key = effective_user_id
                if not (is_malicious and ATTACK_TYPE == "replay"):
                    tsip_state[store_key] = next_tsip_state
                if DEBUG_CLIENT:
                    print(
                        "[DEBUG] tsip stored_loc after accept:",
                        store_key,
                        str(next_tsip_state.get("loc_commitment", "")),
                    )
        else:
            rejected += 1
            detail_a = ""
            detail_r = ""
            if isinstance(data_a, dict):
                detail_a = str(data_a.get("detail") or data_a.get("error") or "")
            if isinstance(data_r, dict):
                detail_r = str(data_r.get("detail") or data_r.get("error") or "")
            reason = detail_a or detail_r or "unknown"
            reject_reason_counter[reason] += 1
        if is_malicious:
            malicious_total += 1
            if not accepted:
                malicious_rejected += 1
        else:
            if not accepted:
                false_rejects += 1

        time.sleep(SEND_INTERVAL_SEC)
    if TSIP_ENABLE:
        save_tsip_state(tsip_state)
    honest_total = total - malicious_total
    false_rate = (false_rejects / honest_total) if honest_total > 0 else 0.0
    malicious_reject_rate = (malicious_rejected / malicious_total) if malicious_total > 0 else 0.0
    print(
        "summary total=", total,
        "valid_clients=", valid_clients,
        "rejected=", rejected,
        "malicious_total=", malicious_total,
        "malicious_reject_rate=", round(malicious_reject_rate, 4),
        "false_reject_rate=", round(false_rate, 4),
    )
    if rejected > 0:
        print("reject_reasons_top=", reject_reason_counter.most_common(5))
    if local_tsip_prove_fail_honest_counter:
        print("local_tsip_prove_fail_honest_top=", local_tsip_prove_fail_honest_counter.most_common(5))
    if local_tsip_prove_fail_malicious_counter:
        print("local_tsip_prove_fail_malicious_top=", local_tsip_prove_fail_malicious_counter.most_common(5))
    if ATTACK_TYPE == "gradual_drift" and gradual_drift_offsets:
        print(
            "gradual_drift_offset_avg_m=", round(sum(gradual_drift_offsets) / len(gradual_drift_offsets), 2),
            "gradual_drift_offset_max_m=", round(max(gradual_drift_offsets), 2),
        )
    if ATTACK_TYPE == "gradual_drift" and gradual_drift_terminal_offsets:
        terminal_offsets = list(gradual_drift_terminal_offsets.values())
        print(
            "gradual_drift_terminal_offset_avg_m=", round(sum(terminal_offsets) / len(terminal_offsets), 2),
            "gradual_drift_terminal_offset_max_m=", round(max(terminal_offsets), 2),
        )
    time.sleep(5)

if __name__ == "__main__":
    main()
