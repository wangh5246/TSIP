from fastapi import FastAPI, Header
from pydantic import BaseModel, Field
from typing import List, Dict, Set, Optional
import os, time, random, threading, math, subprocess, tempfile, shutil, json, hashlib
import requests
from fastapi import HTTPException
from common.ea import parse_kid_pubkeys, verify_attestation
from common.utils import chi2_ppf, seed_from_round, gaussian_vectors
from common.tsip import (
    commitment_to_field,
    compute_chain_commitment,
    compute_policy_cap_sq,
    compute_payload_digest,
    compute_payload_commitment_field,
    compute_tier_anchor_cap_sq,
    default_adwc_window_k,
)
from common.v4_bindings import (
    PAPER_PUBLIC_SIGNAL_ORDER,
    canonical_digest_field,
    report_context,
)
from common.proof_payload import (
    DOMAIN_BLOB,
    DOMAIN_CHANNEL_A,
    DOMAIN_CHANNEL_R,
    DOMAIN_PAYLOAD,
    fingerprint_challenge,
    package_digest_field,
    poseidon_chain,
)
from common.state_accountability import AccountableStateStore, StateTransitionError
app = FastAPI()

def _first_existing_path(candidates: list[str]) -> str:
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def _normalize_tsip_verify_mode(name: str, value: str) -> str:
    mode = (value or "full").strip().lower()
    if mode not in {"full"}:
        raise RuntimeError(f"invalid {name}: {value}")
    return mode


def _normalize_tsip_circuit_profile(value: str) -> str:
    p = (value or "k6").strip().lower()
    if p != "k6":
        raise RuntimeError("TSIP V4-paper source supports only the k6 circuit profile")
    return p



K = int(os.getenv("K", "50"))
KD = int(os.getenv("KD", "50"))
KPRIME = K + KD
DOMAIN = int(os.getenv("DOMAIN", "10000"))

MASK_BITS = int(os.getenv("MASK_BITS", "32"))
MASK = (1 << MASK_BITS) - 1

PROOF_ENABLE = os.getenv("PROOF_ENABLE", "0") == "1"
PROOF_M = int(os.getenv("PROOF_M", "8"))
PROOF_ALPHA = float(os.getenv("PROOF_ALPHA", "0.05"))
PROOF_B = float(os.getenv("PROOF_B", "0"))
PROOF_DIM = int(os.getenv("PROOF_DIM", "0"))
PROOF_B_SCALE = float(os.getenv("PROOF_B_SCALE", "1.0"))
PROOF_CALIBRATE = os.getenv("PROOF_CALIBRATE", "0") == "1"
PROOF_CALIBRATION_SAMPLES = int(os.getenv("PROOF_CALIBRATION_SAMPLES", "200"))
ZK_STEP_ENABLE = os.getenv("ZK_STEP_ENABLE", "0") == "1"
ZK_STEP_SNARKJS = os.getenv("ZK_STEP_SNARKJS", "snarkjs")
ZK_STEP_VKEY = os.getenv(
    "ZK_STEP_VKEY",
    _first_existing_path(
        [
            "/app/zk/tsip_step/verification_key.json",
            "zk/tsip_step/verification_key.json",
        ]
    ),
)
ZK_STEP_VERIFY_TIMEOUT_SEC = int(os.getenv("ZK_STEP_VERIFY_TIMEOUT_SEC", "30"))
TSIP_ENABLE = os.getenv("TSIP_ENABLE", "0") == "1"
TSIP_VERIFY_MODE = _normalize_tsip_verify_mode("TSIP_VERIFY_MODE", os.getenv("TSIP_VERIFY_MODE", "full"))
TSIP_SNARKJS = os.getenv("TSIP_SNARKJS", "snarkjs")
TSIP_CIRCUIT_PROFILE = _normalize_tsip_circuit_profile(
    os.getenv("TSIP_CIRCUIT_PROFILE", os.getenv("TSIP_ADWC_PROFILE", "k6"))
)
TSIP_VKEY = os.getenv(
    "TSIP_VKEY",
    _first_existing_path(
        [
            "/app/v4/zk/v4_paper_k6/verification_key.json",
            "zk/v4_paper_k6/verification_key.json",
        ]
    ),
)
TSIP_VERIFY_TIMEOUT_SEC = int(os.getenv("TSIP_VERIFY_TIMEOUT_SEC", "30"))
TSIP_WINDOW_SEC = int(os.getenv("TSIP_WINDOW_SEC", "60"))
TSIP_MAX_GAP_WINDOWS = int(os.getenv("TSIP_MAX_GAP_WINDOWS", "2"))
TSIP_BLACKLIST_THRESHOLD = int(os.getenv("TSIP_BLACKLIST_THRESHOLD", "3"))
TSIP_DEBUG = os.getenv("TSIP_DEBUG", "0") == "1"
TSIP_BOOTSTRAP_POLICY = os.getenv("TSIP_BOOTSTRAP_POLICY", "legacy_accept").strip().lower()
# A session gap never clears the accepted predecessor. Re-enrollment stays
# fail-closed until this prototype has a verified reset-credential interface.
# In particular, no environment variable may turn a bare enrollment payload
# into a state reset.
TSIP_ALLOW_REENROLL = False
TSIP_STATE_ACCOUNTABILITY_ENABLE = os.getenv("TSIP_STATE_ACCOUNTABILITY_ENABLE", "0") == "1"
SHUFFLER_STATE_DB_PATH = os.getenv("SHUFFLER_STATE_DB_PATH", "/data/shtpc_state.sqlite3")
SHUFFLER_STATE_SIGNING_KEY = os.getenv("SHUFFLER_STATE_SIGNING_KEY", "").strip()
SHUFFLER_STATE_SERVICE_ID = os.getenv("SHUFFLER_STATE_SERVICE_ID", "shuffler-1").strip() or "shuffler-1"
SHUFFLER_CHECKPOINT_INTERVAL = int(os.getenv("SHUFFLER_CHECKPOINT_INTERVAL", "100"))
SHUFFLER_STATE_MERKLE_DEPTH = int(os.getenv("SHUFFLER_STATE_MERKLE_DEPTH", "32"))

# ── C6: Anchor-Distance Window Continuity (ADWC) ────────────────────────────
TSIP_ADWC_PROFILE = os.getenv("TSIP_ADWC_PROFILE", "k6").strip().lower()
TSIP_ADWC_WINDOW_K: int = int(os.getenv("TSIP_ADWC_WINDOW_K", str(default_adwc_window_k(TSIP_ADWC_PROFILE))))
TSIP_POLICY_CAP_RATIO: float = float(os.getenv("TSIP_POLICY_CAP_RATIO", "0.5"))
# ── P1: Enrollment Warmup ───────────────────────────────────────────────────
# New users' submissions are held from aggregation for this many accepted
# rounds while the commitment chain is being established.
# Fixed rule: N_warm = max(K, 2) for an initial enrollment.
TSIP_WARMUP_ROUNDS: int = max(int(TSIP_ADWC_WINDOW_K), 2)
if TSIP_ENABLE and TSIP_VERIFY_MODE != "full":
    raise RuntimeError("TSIP_VERIFY_MODE must be 'full' in TSIP v4-paper mode")
if TSIP_POLICY_CAP_RATIO <= 0:
    raise RuntimeError("TSIP_POLICY_CAP_RATIO must be > 0")

# ── Operator-attested enrollment (EA) ────────────────────────────────────────
TSIP_EA_REQUIRE = os.getenv("TSIP_EA_REQUIRE", "1") == "1"
TSIP_EA_PUBKEYS_RAW = os.getenv("TSIP_EA_PUBKEYS", "")
TSIP_EA_PUBKEYS = parse_kid_pubkeys(TSIP_EA_PUBKEYS_RAW)
TSIP_EA_ALLOW_EXPIRED_SEC = int(os.getenv("TSIP_EA_ALLOW_EXPIRED_SEC", "0"))
if TSIP_ENABLE and TSIP_EA_REQUIRE and not TSIP_EA_PUBKEYS:
    raise RuntimeError("TSIP_EA_REQUIRE=1 but TSIP_EA_PUBKEYS is empty")

# ── P3: Server Trust Model ──────────────────────────────────────────────────
# Minimum number of *distinct* aggregator replicas that must accept a report
# before it counts toward the final tally.  With the current 2-aggregator
# design, setting this to 2 prevents a single compromised aggregator from
# poisoning the output; however full collusion still degrades privacy to DP-
# only (the aggregated output is still DP-protected).
# NOTE: Enforced only at the shuffler level via committee signatures;
# inter-aggregator cross-validation or TEE/MPC is left as future work.
TSIP_MIN_AGGREGATORS: int = int(os.getenv("TSIP_MIN_AGGREGATORS", "1"))

TSIP_VERIFY_DP_ENABLE = os.getenv("TSIP_VERIFY_DP_ENABLE", "0") == "1"
TSIP_VERIFY_EPSILON = float(os.getenv("TSIP_VERIFY_EPSILON", "0.2"))
TSIP_VERIFY_NOISY_THRESHOLD = float(os.getenv("TSIP_VERIFY_NOISY_THRESHOLD", "0.5"))
SEED_SECRET = os.getenv("RISERFL_SEED_SECRET", "rise_fed")
TSIP_VERIFY_DP_SEED = os.getenv("TSIP_VERIFY_DP_SEED", SEED_SECRET)
CITY_SIZE_M = float(os.getenv("CITY_SIZE_M", "10000"))
DT_SEC = int(os.getenv("DT_SEC", "10"))
TRAJ_POINTS = int(os.getenv("TRAJ_POINTS", "300"))
MAX_STEP_M = float(os.getenv("MAX_STEP_M", "80.0"))
SHUFFLER_COMMITTEE_ENABLE = os.getenv("SHUFFLER_COMMITTEE_ENABLE", "0") == "1"
SHUFFLER_COMMITTEE_ID = os.getenv("SHUFFLER_COMMITTEE_ID", "s1").strip() or "s1"
SHUFFLER_COMMITTEE_SIGN_SECRET = os.getenv("SHUFFLER_COMMITTEE_SIGN_SECRET", "").strip()
SHUFFLER_COMMITTEE_THRESHOLD = int(os.getenv("SHUFFLER_COMMITTEE_THRESHOLD", "1"))
SHUFFLER_COMMITTEE_PEERS = [x.strip().rstrip("/") for x in os.getenv("SHUFFLER_COMMITTEE_PEERS", "").split(",") if x.strip()]
SHUFFLER_COMMITTEE_TIMEOUT_SEC = float(os.getenv("SHUFFLER_COMMITTEE_TIMEOUT_SEC", "3"))
SHUFFLER_COMMITTEE_ATTEST_PATH = os.getenv("SHUFFLER_COMMITTEE_ATTEST_PATH", "/committee/attest").strip() or "/committee/attest"
SHUFFLER_COMMITTEE_TOKEN = os.getenv("SHUFFLER_COMMITTEE_TOKEN", "").strip()

AGG_A_URL = os.environ.get("AGG_A_URL", "http://localhost:8002/forward")
AGG_R_URL = os.environ.get("AGG_R_URL", "http://localhost:8003/forward")
FLUSH_SECONDS = float(os.environ.get("FLUSH_SECONDS", "2"))
current_round_id = 999999  # 默认值，第一次也能用
round_lock = threading.Lock()

# 按 round 记录 submission_id，A/R 分开（同一 submission_id 允许在 A/R 各出现一次）
seenA_by_round: Dict[int, Set[str]] = {}
seenR_by_round: Dict[int, Set[str]] = {}
proof_threshold_by_round: Dict[int, float] = {}
tsip_state_by_user: Dict[str, Dict[str, object]] = {}
pending_tsip_by_submission: Dict[tuple[int, str], Dict[str, object]] = {}
pending_route_reports_by_submission: Dict[tuple[int, str], Dict[str, object]] = {}
tsip_reject_streak_by_user: Dict[str, int] = {}
tsip_blacklist_by_user: Dict[str, Dict[str, object]] = {}
tsip_rejected_submission_keys: Set[tuple[int, str]] = set()
tsip_verify_dp_decision_by_submission: Dict[tuple[int, str], Dict[str, object]] = {}
tsip_verify_dp_usage_by_round: Dict[int, Dict[str, float]] = {}
tsip_bootstrap_held_by_round: Dict[int, int] = {}
tsip_proof_attempted_submission_keys: Set[tuple[int, str]] = set()
tsip_proof_verified_submission_keys: Set[tuple[int, str]] = set()
tsip_proof_failed_submission_keys: Set[tuple[int, str]] = set()
tsip_state_receipt_by_submission: Dict[tuple[int, str], Dict[str, object]] = {}
state_accountability_store: Optional[AccountableStateStore] = None

# P5: secret commitment registered at enrollment; verified on subsequent rounds
tsip_secret_commitment_by_user: Dict[str, str] = {}
tsip_secret_commitment_field_by_user: Dict[str, str] = {}

class Proof(BaseModel):
    s: float
    m: Optional[int] = None
    dim: Optional[int] = None


class CommitteeSignature(BaseModel):
    shuffler_id: str
    signature: str


class Report(BaseModel):
    round_id: int
    submission_id: str
    idx: List[int] = Field(..., min_length=KPRIME, max_length=KPRIME)
    val: List[int] = Field(..., min_length=KPRIME, max_length=KPRIME)
    proof: Optional[Proof] = None
    zk_step: Optional[Dict[str, object]] = None
    tsip: Optional[Dict[str, object]] = None
    committee_sigs: Optional[List[CommitteeSignature]] = None


class CommitteeAttestRequest(BaseModel):
    channel: str
    report: Report

queueA: List[Report] = []
queueR: List[Report] = []
lock = threading.Lock()

#通用校验函数
def proof_threshold_static(dim: int) -> float:
    if PROOF_M <= 0:
        raise HTTPException(status_code=400, detail="invalid PROOF_M")
    if not (0.0 < PROOF_ALPHA < 1.0):
        raise HTTPException(status_code=400, detail="invalid PROOF_ALPHA")
    if PROOF_B > 0:
        b = PROOF_B
    else:
        if dim <= 0:
            raise HTTPException(status_code=400, detail="invalid proof dim")
        b = math.sqrt(dim) * (PROOF_B_SCALE if PROOF_B_SCALE > 0 else 1.0)
    return (b * b) * chi2_ppf(1.0 - PROOF_ALPHA, PROOF_M)

def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x

def gen_synthetic_trajectory(rng: random.Random):
    home = (rng.uniform(0, CITY_SIZE_M), rng.uniform(0, CITY_SIZE_M))
    work = (rng.uniform(0, CITY_SIZE_M), rng.uniform(0, CITY_SIZE_M))

    points = []
    t0 = 1700000000

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

    n_home = max(10, TRAJ_POINTS // 5)
    n_commute = max(10, TRAJ_POINTS // 5)
    n_work = max(10, TRAJ_POINTS // 3)
    n_walk = TRAJ_POINTS - (n_home + n_commute + n_work)

    add_stay(home, n_home, jitter_m=8.0)
    add_move(home, work, n_commute, jitter_m=6.0)
    add_stay(work, n_work, jitter_m=10.0)
    add_random_walk(work, n_walk, step_sigma_m=25.0)

    return points

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

def calibrate_threshold(round_id: int, dim: int) -> float:
    if PROOF_CALIBRATION_SAMPLES <= 0:
        raise HTTPException(status_code=400, detail="invalid PROOF_CALIBRATION_SAMPLES")
    seed = seed_from_round(round_id, SEED_SECRET)
    a = gaussian_vectors(seed, PROOF_M, dim)
    rng = random.Random(int(round_id) ^ 0x9E3779B9)

    s_vals = []
    for _ in range(PROOF_CALIBRATION_SAMPLES):
        traj = gen_synthetic_trajectory(rng)
        u = compute_displacement_vector(traj)
        s = 0.0
        for j in range(PROOF_M):
            aj = a[j]
            dot = 0.0
            for i in range(dim):
                dot += u[i] * aj[i]
            s += dot * dot
        s_vals.append(s)

    s_vals.sort()
    idx = int(math.ceil((1.0 - PROOF_ALPHA) * len(s_vals))) - 1
    idx = max(0, min(len(s_vals) - 1, idx))
    s_q = s_vals[idx]
    chi_q = chi2_ppf(1.0 - PROOF_ALPHA, PROOF_M)
    b2 = (s_q / chi_q) if chi_q > 0 else 0.0
    return b2 * chi_q

def proof_threshold(round_id: int, dim: int) -> float:
    if PROOF_CALIBRATE:
        cached = proof_threshold_by_round.get(round_id)
        if cached is not None:
            return cached
        threshold = calibrate_threshold(round_id, dim)
        proof_threshold_by_round[round_id] = threshold
        return threshold
    return proof_threshold_static(dim)

def verify_zk_step_proof(proof: dict, public_signals: list) -> tuple[bool, str]:
    if shutil.which(ZK_STEP_SNARKJS) is None:
        return False, f"snarkjs not found: {ZK_STEP_SNARKJS}"
    if not os.path.exists(ZK_STEP_VKEY):
        return False, f"missing verification key: {ZK_STEP_VKEY}"

    with tempfile.TemporaryDirectory(prefix="zk_step_verify_") as td:
        proof_path = os.path.join(td, "proof.json")
        public_path = os.path.join(td, "public.json")
        with open(proof_path, "w", encoding="utf-8") as f:
            json.dump(proof, f, ensure_ascii=True)
        with open(public_path, "w", encoding="utf-8") as f:
            json.dump(public_signals, f, ensure_ascii=True)
        cmd = [
            ZK_STEP_SNARKJS,
            "groth16",
            "verify",
            ZK_STEP_VKEY,
            public_path,
            proof_path,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=ZK_STEP_VERIFY_TIMEOUT_SEC,
            check=False,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            return False, out or "groth16 verify failed"
        if "OK!" not in out:
            return False, out or "groth16 verify not OK"
    return True, ""


def verify_tsip_proof(proof: dict, public_signals: list) -> tuple[bool, str]:
    if shutil.which(TSIP_SNARKJS) is None:
        return False, f"snarkjs not found: {TSIP_SNARKJS}"
    if not os.path.exists(TSIP_VKEY):
        return False, f"missing verification key: {TSIP_VKEY}"

    with tempfile.TemporaryDirectory(prefix="tsip_verify_") as td:
        proof_path = os.path.join(td, "proof.json")
        public_path = os.path.join(td, "public.json")
        with open(proof_path, "w", encoding="utf-8") as f:
            json.dump(proof, f, ensure_ascii=True)
        with open(public_path, "w", encoding="utf-8") as f:
            json.dump(public_signals, f, ensure_ascii=True)
        cmd = [
            TSIP_SNARKJS,
            "groth16",
            "verify",
            TSIP_VKEY,
            public_path,
            proof_path,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TSIP_VERIFY_TIMEOUT_SEC,
            check=False,
        )
        out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode != 0:
            return False, out or "groth16 verify failed"
        if "OK!" not in out:
            return False, out or "groth16 verify not OK"
    return True, ""


def _stable_uniform_minus_half_to_half(material: str) -> float:
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    raw = int.from_bytes(digest[:8], byteorder="big", signed=False)
    # Map to (0, 1) then shift to (-0.5, 0.5)
    u01 = (raw + 0.5) / float(1 << 64)
    if u01 <= 0.0:
        u01 = 1e-12
    elif u01 >= 1.0:
        u01 = 1.0 - 1e-12
    return u01 - 0.5


def _stable_laplace_noise(scale: float, material: str) -> float:
    if scale <= 0:
        return 0.0
    u = _stable_uniform_minus_half_to_half(material)
    return -scale * (1.0 if u >= 0 else -1.0) * math.log(1.0 - 2.0 * abs(u))


def _is_tsip_verify_runtime_error(err: str) -> bool:
    e = (err or "").lower()
    if not e:
        return False
    return (
        ("snarkjs not found" in e)
        or ("missing verification key" in e)
        or ("timed out" in e)
        or ("timeout" in e)
    )


def _tsip_verify_dp_decision(r: Report, verify_ok: bool) -> tuple[bool, Dict[str, object]]:
    if not TSIP_VERIFY_DP_ENABLE:
        return verify_ok, {"dp_enabled": False}
    if TSIP_VERIFY_EPSILON <= 0:
        raise HTTPException(status_code=400, detail="invalid TSIP_VERIFY_EPSILON")
    if not (0.0 <= TSIP_VERIFY_NOISY_THRESHOLD <= 1.0):
        raise HTTPException(status_code=400, detail="invalid TSIP_VERIFY_NOISY_THRESHOLD")

    key = (int(r.round_id), str(r.submission_id))
    cached = tsip_verify_dp_decision_by_submission.get(key)
    if cached is not None:
        return bool(cached["accept"]), cached

    user_id = _tsip_user_id(r)
    score = 1.0 if verify_ok else 0.0
    scale = 1.0 / TSIP_VERIFY_EPSILON
    material = (
        f"{TSIP_VERIFY_DP_SEED}|round={r.round_id}|submission={r.submission_id}"
        f"|user={user_id}|score={int(score)}"
    )
    noise = _stable_laplace_noise(scale, material)
    noisy_score = score + noise
    accept = noisy_score > TSIP_VERIFY_NOISY_THRESHOLD

    usage = tsip_verify_dp_usage_by_round.setdefault(
        int(r.round_id),
        {
            "calls": 0.0,
            "spent": 0.0,
            "deterministic_accept": 0.0,
            "deterministic_reject": 0.0,
            "noisy_accept": 0.0,
            "noisy_reject": 0.0,
        },
    )
    usage["calls"] += 1.0
    usage["spent"] += TSIP_VERIFY_EPSILON
    if verify_ok:
        usage["deterministic_accept"] += 1.0
    else:
        usage["deterministic_reject"] += 1.0
    if accept:
        usage["noisy_accept"] += 1.0
    else:
        usage["noisy_reject"] += 1.0

    out = {
        "dp_enabled": True,
        "epsilon_verify": TSIP_VERIFY_EPSILON,
        "score": score,
        "noise": noise,
        "noisy_score": noisy_score,
        "threshold": TSIP_VERIFY_NOISY_THRESHOLD,
        "accept": accept,
    }
    tsip_verify_dp_decision_by_submission[key] = out
    return accept, out


def _tsip_expected_chain(
    prev_chain: str,
    curr_loc: str,
    timestamp: int,
    window_id: int,
    payload_digest: str,
    secret_commitment: str,
) -> str:
    """Compute the expected TSIP V4-paper chain commitment."""
    return compute_chain_commitment(
        prev_chain_commitment=prev_chain,
        location_commitment=curr_loc,
        timestamp=timestamp,
        window_id=window_id,
        payload_digest=payload_digest,
        secret_commitment=secret_commitment,
    )


def _is_enrollment_payload(tsip: dict) -> bool:
    prev_loc_commitment = str(tsip.get("prev_loc_commitment", "")).strip()
    prev_chain_commitment = str(tsip.get("prev_chain_commitment", "")).strip()
    return (not prev_loc_commitment) and (not prev_chain_commitment)


def _validate_ea_attestation(
    tsip: dict,
    user_id: str,
    declared_tier_vmax_sq: int,
    declared_sc_field: str,
    declared_modeset_commitment: str,
) -> dict:
    att = tsip.get("ea_attestation")
    if not isinstance(att, dict):
        raise HTTPException(status_code=400, detail="missing tsip ea_attestation")
    if TSIP_EA_REQUIRE:
        ok, err = verify_attestation(
            attestation=att,
            pubkeys_by_kid=TSIP_EA_PUBKEYS,
            now_ts=(int(time.time()) - int(TSIP_EA_ALLOW_EXPIRED_SEC)),
        )
        if not ok:
            raise HTTPException(status_code=400, detail=f"invalid ea_attestation: {err[:180]}")

    uid = str(att.get("uid", "")).strip()
    if uid != user_id:
        raise HTTPException(status_code=400, detail="ea_attestation uid mismatch")
    try:
        att_tier = int(att.get("tier_vmax_sq", 0) or 0)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid ea_attestation tier_vmax_sq")
    if att_tier != int(declared_tier_vmax_sq):
        raise HTTPException(status_code=400, detail="ea_attestation tier_vmax_sq mismatch")

    att_sec = str(att.get("com_sec", "")).strip()
    if att_sec != str(declared_sc_field):
        raise HTTPException(status_code=400, detail="ea_attestation com_sec mismatch")
    att_modeset = str(att.get("com_modeset", "")).strip()
    if att_modeset != str(declared_modeset_commitment):
        raise HTTPException(status_code=400, detail="ea_attestation com_modeset mismatch")
    return att


def _normalize_adwc_history(prev_state: dict) -> list[dict]:
    out: list[dict] = []
    if not isinstance(prev_state, dict) or not prev_state:
        return out
    raw = prev_state.get("adwc_history", [])
    if isinstance(raw, list):
        for it in raw:
            if not isinstance(it, dict):
                continue
            try:
                out.append({"idx": int(it["idx"]), "loc_commitment": str(it["loc_commitment"])})
            except Exception:
                continue
    if out:
        out.sort(key=lambda z: int(z["idx"]))
        dedup: Dict[int, dict] = {}
        for it in out:
            dedup[int(it["idx"])] = it
        out = [dedup[k] for k in sorted(dedup.keys())]
        return out
    loc = str(prev_state.get("loc_commitment", "")).strip()
    if not loc:
        return out
    accepted_count = max(1, int(prev_state.get("accepted_count", 1)))
    return [{"idx": max(0, accepted_count - 1), "loc_commitment": loc}]


def _expected_anchor_from_state(prev_state: dict) -> tuple[str, int, int]:
    history = _normalize_adwc_history(prev_state)
    accepted_count = max(1, int(prev_state.get("accepted_count", len(history) if history else 1)))
    current_i = accepted_count
    anchor_i = max(0, current_i - max(1, int(TSIP_ADWC_WINDOW_K)))
    for it in history:
        if int(it.get("idx", -1)) == anchor_i:
            return str(it.get("loc_commitment", "")), anchor_i, current_i
    if anchor_i == 0 and history:
        return str(history[0].get("loc_commitment", "")), 0, current_i
    raise HTTPException(
        status_code=400,
        detail=f"tsip missing anchor state idx={anchor_i} history_len={len(history)} (require keep >=K+1)",
    )


def _next_adwc_history(prev_state: dict, curr_loc_commitment: str) -> tuple[list[dict], int]:
    history = _normalize_adwc_history(prev_state)
    accepted_count = int(prev_state.get("accepted_count", len(history)))
    if accepted_count < 0:
        accepted_count = 0
    current_i = accepted_count
    history.append({"idx": int(current_i), "loc_commitment": str(curr_loc_commitment)})
    history.sort(key=lambda z: int(z["idx"]))
    keep = max(2, int(TSIP_ADWC_WINDOW_K) + 1)
    if len(history) > keep:
        history = history[-keep:]
    return history, int(current_i + 1)


def _state_accountability() -> Optional[AccountableStateStore]:
    global state_accountability_store
    if not TSIP_STATE_ACCOUNTABILITY_ENABLE:
        return None
    if state_accountability_store is None:
        state_accountability_store = AccountableStateStore(
            db_path=SHUFFLER_STATE_DB_PATH,
            signing_key_b64=SHUFFLER_STATE_SIGNING_KEY,
            service_id=SHUFFLER_STATE_SERVICE_ID,
            checkpoint_interval=SHUFFLER_CHECKPOINT_INTERVAL,
            merkle_depth=SHUFFLER_STATE_MERKLE_DEPTH,
        )
    return state_accountability_store


def _restore_accountable_state(user_id: str) -> Optional[dict]:
    if not user_id:
        return None
    current = tsip_state_by_user.get(user_id)
    if current is not None:
        return current
    store = _state_accountability()
    if store is None:
        return None
    snapshot = store.latest_state_snapshot(user_id)
    if not snapshot:
        return None
    restored = snapshot.get("state")
    if not isinstance(restored, dict):
        return None
    tsip_state_by_user[user_id] = restored
    tsip_secret_commitment_by_user[user_id] = str(snapshot.get("secret_commitment", ""))
    tsip_secret_commitment_field_by_user[user_id] = str(snapshot.get("secret_commitment_field", ""))
    return restored


def _commit_accountable_state(
    *,
    user_id: str,
    state: dict,
    previous_state: dict,
    is_enrollment: bool,
    report_digest: str,
    timing_token_digest: str,
    secret_commitment: str,
    secret_commitment_field: str,
) -> Optional[dict]:
    store = _state_accountability()
    if store is None:
        return None
    try:
        commit = store.commit(
            user_id=user_id,
            epoch=int(state["enrollment_epoch"]),
            state_round=int(state["accepted_count"]),
            previous_commitment="" if is_enrollment else str(previous_state["chain_commitment"]),
            current_commitment=str(state["chain_commitment"]),
            report_digest=report_digest,
            timing_token_digest=timing_token_digest,
            state_snapshot={
                "state": state,
                "secret_commitment": secret_commitment,
                "secret_commitment_field": secret_commitment_field,
            },
            reset=bool(is_enrollment),
        )
    except (StateTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"accountable state transition rejected: {exc}") from exc
    return {
        "receipt": commit.receipt,
        "inclusion_proof": commit.inclusion_proof,
        "checkpoint": commit.checkpoint,
    }


def _validate_v4_route_binding(
    r: Report,
    channel: str,
    tsip: dict,
    public_signals: list | None,
) -> None:
    route = str(channel or "").strip().upper()
    if route not in {"A", "R"}:
        raise HTTPException(status_code=400, detail="invalid v4 route channel")

    user_id = str(tsip.get("user_id", "")).strip()
    prev_state = _restore_accountable_state(user_id)
    if _is_enrollment_payload(tsip):
        epoch = int((prev_state or {}).get("enrollment_epoch", 0) or 0) + 1
    else:
        epoch = int((prev_state or {}).get("enrollment_epoch", 1) or 1)
    expected_context = report_context(
        user_id=user_id,
        round_id=int(r.round_id),
        submission_id=str(r.submission_id),
        epoch=epoch,
    )
    if tsip.get("context") != expected_context:
        raise HTTPException(status_code=400, detail="tsip report context mismatch")

    expected_context_field = int(canonical_digest_field(expected_context))
    declared_context_field = int(tsip.get("context_commitment", 0) or 0)
    if declared_context_field != expected_context_field:
        raise HTTPException(status_code=400, detail="tsip context_commitment mismatch")

    primary_commitment = int(tsip.get("primary_commitment", 0) or 0)
    share_a = int(tsip.get("share_content_commitment_a", 0) or 0)
    share_r = int(tsip.get("share_content_commitment_r", 0) or 0)
    payload_commitment = int(tsip.get("payload_commitment_v2", 0) or 0)
    declared_blob_hash = int(tsip.get("blob_hash", 0) or 0)
    package_digest_a = int(tsip.get("package_digest_a", 0) or 0)
    package_digest_r = int(tsip.get("package_digest_r", 0) or 0)
    alpha = int(tsip.get("fingerprint_challenge", 0) or 0)
    fingerprint_a = int(tsip.get("fingerprint_a", 0) or 0)
    fingerprint_r = int(tsip.get("fingerprint_r", 0) or 0)
    contribution_bit = int(tsip.get("contribution_bit", -1))
    if contribution_bit not in {0, 1}:
        raise HTTPException(status_code=400, detail="invalid contribution_bit")
    if min(
        primary_commitment,
        share_a,
        share_r,
        payload_commitment,
        declared_blob_hash,
        package_digest_a,
        package_digest_r,
        alpha,
    ) <= 0:
        raise HTTPException(status_code=400, detail="missing v4 route binding field")

    package_digest = int(
        package_digest_field(
            channel=route,
            context=expected_context,
            idx=[int(item) for item in r.idx],
            val=[int(item) for item in r.val],
            dimension=DOMAIN,
            mask_bits=MASK_BITS,
            expected_length=KPRIME,
        )
    )
    declared_package_digest = package_digest_a if route == "A" else package_digest_r
    if package_digest != declared_package_digest:
        raise HTTPException(status_code=400, detail=f"tsip {route} package digest mismatch")

    expected_alpha = int(
        fingerprint_challenge(
            context_commitment=expected_context_field,
            primary_commitment=primary_commitment,
            package_digest_a=package_digest_a,
            package_digest_r=package_digest_r,
        )
    )
    if alpha != expected_alpha:
        raise HTTPException(status_code=400, detail="tsip fingerprint challenge mismatch")

    route_domain = DOMAIN_CHANNEL_A if route == "A" else DOMAIN_CHANNEL_R
    route_fingerprint = fingerprint_a if route == "A" else fingerprint_r
    expected_share = int(
        poseidon_chain(
            route_domain,
            primary_commitment,
            expected_context_field,
            declared_package_digest,
            route_fingerprint,
        )
    )
    declared_share = share_a if route == "A" else share_r
    if expected_share != declared_share:
        raise HTTPException(
            status_code=400,
            detail=f"tsip {route} share-content commitment mismatch (C21+)",
        )

    expected_payload = int(
        poseidon_chain(
            DOMAIN_PAYLOAD,
            expected_context_field,
            primary_commitment,
            share_a,
            share_r,
            contribution_bit,
        )
    )
    if payload_commitment != expected_payload:
        raise HTTPException(status_code=400, detail="tsip payload_commitment_v2 mismatch (C21+)")
    expected_blob_hash = int(
        poseidon_chain(
            DOMAIN_BLOB,
            expected_context_field,
            package_digest_a,
            package_digest_r,
            payload_commitment,
        )
    )
    if declared_blob_hash != expected_blob_hash:
        raise HTTPException(status_code=400, detail="tsip transport digest mismatch (C21+)")

    if public_signals is None:
        return
    if len(public_signals) != len(PAPER_PUBLIC_SIGNAL_ORDER):
        raise HTTPException(
            status_code=400,
            detail=f"invalid tsip public_signals: expected {len(PAPER_PUBLIC_SIGNAL_ORDER)}",
        )
    expected_binding_signals = {
        7: primary_commitment,
        8: payload_commitment,
        9: share_a,
        10: share_r,
        11: expected_context_field,
        12: declared_blob_hash,
        13: package_digest_a,
        14: package_digest_r,
        15: alpha,
    }
    for signal_idx, expected in expected_binding_signals.items():
        if str(public_signals[signal_idx]) != str(expected):
            name = PAPER_PUBLIC_SIGNAL_ORDER[signal_idx]
            raise HTTPException(status_code=400, detail=f"tsip {name} public signal mismatch")


def validate_tsip_report(r: Report, channel: str):
    if r.tsip is None:
        raise HTTPException(status_code=400, detail="missing tsip payload")
    tsip = r.tsip
    version = str(tsip.get("version", "")).strip().lower()
    if version != "v4-paper":
        raise HTTPException(status_code=400, detail="tsip version must be v4-paper")

    user_id = str(tsip.get("user_id", "")).strip()
    prev_loc_commitment = str(tsip.get("prev_loc_commitment", "")).strip()
    curr_loc_commitment = str(tsip.get("curr_loc_commitment", "")).strip()
    prev_chain_commitment = str(tsip.get("prev_chain_commitment", "")).strip()
    curr_chain_commitment = str(tsip.get("curr_chain_commitment", "")).strip()
    timestamp = int(tsip.get("timestamp", 0) or 0)
    window_id = int(tsip.get("window_id", 0) or 0)

    # ── P4/P5 fields ─────────────────────────────────────────────────────────
    payload_digest = str(tsip.get("payload_digest", "")).strip()
    if not payload_digest:
        raise HTTPException(status_code=400, detail="missing tsip payload_digest")
    expected_payload_digest = compute_payload_digest(r.idx)
    if payload_digest != expected_payload_digest:
        raise HTTPException(status_code=400, detail="tsip payload_digest mismatch with idx")
    secret_commitment_recv = str(tsip.get("secret_commitment", "")).strip()
    if not secret_commitment_recv:
        raise HTTPException(status_code=400, detail="missing tsip secret_commitment")
    declared_sc_field = str(tsip.get("secret_commitment_field", "")).strip()
    if not declared_sc_field:
        raise HTTPException(status_code=400, detail="missing tsip secret_commitment_field")
    declared_modeset_commitment = str(tsip.get("modeset_commitment", "")).strip()
    if not declared_modeset_commitment:
        raise HTTPException(status_code=400, detail="missing tsip modeset_commitment")
    declared_mode_tag = str(tsip.get("mode_tag", "")).strip()
    if not declared_mode_tag:
        raise HTTPException(status_code=400, detail="missing tsip mode_tag")
    try:
        declared_tier_vmax_sq = int(tsip.get("tier_vmax_sq", 0) or 0)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid tsip tier_vmax_sq")
    if declared_tier_vmax_sq <= 0:
        raise HTTPException(status_code=400, detail="invalid tsip tier_vmax_sq")

    if not user_id:
        raise HTTPException(status_code=400, detail="invalid tsip user_id")
    if not curr_loc_commitment or not curr_chain_commitment:
        raise HTTPException(status_code=400, detail="missing tsip commitments")
    if timestamp <= 0:
        raise HTTPException(status_code=400, detail="invalid tsip timestamp")

    _validate_ea_attestation(
        tsip=tsip,
        user_id=user_id,
        declared_tier_vmax_sq=declared_tier_vmax_sq,
        declared_sc_field=declared_sc_field,
        declared_modeset_commitment=declared_modeset_commitment,
    )

    is_enroll = _is_enrollment_payload(tsip)
    prev_state = _restore_accountable_state(user_id)
    if prev_state is None and not is_enroll:
        raise HTTPException(status_code=400, detail="missing enrollment for tsip follow-up")
    route_public_signals = None if is_enroll else tsip.get("public_signals")
    if route_public_signals is not None and not isinstance(route_public_signals, list):
        raise HTTPException(status_code=400, detail="invalid tsip public_signals")
    _validate_v4_route_binding(r, channel, tsip, route_public_signals)

    if is_enroll:
        if prev_state is not None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "tsip re-enrollment is disabled: an authenticated reset "
                    "credential verifier is not implemented"
                ),
            )

        expected_chain = _tsip_expected_chain(
            "",
            curr_loc_commitment,
            timestamp,
            window_id,
            payload_digest,
            secret_commitment_recv,
        )
        if curr_chain_commitment != expected_chain:
            raise HTTPException(status_code=400, detail="invalid tsip enrollment chain commitment")
        return

    # ── Subsequent submission ───────────────────────────────────────────────
    expected_prev_loc = str(prev_state["loc_commitment"])
    expected_prev_chain = str(prev_state["chain_commitment"])
    if TSIP_DEBUG:
        print(
            "[TSIP_DEBUG] stored_prev_loc=",
            expected_prev_loc,
            "received_prev_loc=",
            prev_loc_commitment,
            "user_id=",
            user_id,
            "submission_id=",
            r.submission_id,
            "round_id=",
            r.round_id,
            flush=True,
        )
    if prev_loc_commitment != expected_prev_loc:
        raise HTTPException(status_code=400, detail="tsip prev_loc_commitment mismatch")
    if prev_chain_commitment != expected_prev_chain:
        raise HTTPException(status_code=400, detail="tsip prev_chain_commitment mismatch")
    prev_timestamp = int(prev_state["timestamp"])
    if timestamp <= prev_timestamp:
        raise HTTPException(status_code=400, detail="tsip timestamp not monotonic")
    if window_id < int(prev_state.get("window_id", 0)):
        raise HTTPException(status_code=400, detail="tsip window reversal")
    max_gap = max(1, TSIP_WINDOW_SEC) * max(1, TSIP_MAX_GAP_WINDOWS)
    if timestamp - prev_timestamp > max_gap:
        raise HTTPException(status_code=400, detail="tsip time gap too large")

    # ── P5: secret commitment continuity ─────────────────────────────────────
    stored_sc = tsip_secret_commitment_by_user.get(user_id, "")
    stored_sc_field = tsip_secret_commitment_field_by_user.get(user_id, "")
    if stored_sc and secret_commitment_recv != stored_sc:
        raise HTTPException(status_code=400, detail="tsip secret_commitment mismatch (P5)")
    if stored_sc_field and declared_sc_field != stored_sc_field:
        raise HTTPException(status_code=400, detail="tsip secret_commitment_field mismatch (P5)")
    if not stored_sc:
        tsip_secret_commitment_by_user[user_id] = secret_commitment_recv
    if not stored_sc_field:
        tsip_secret_commitment_field_by_user[user_id] = declared_sc_field

    # ── C6: Anchor-distance window continuity anchor binding ────────────────
    anchor_loc_commitment = str(tsip.get("anchor_loc_commitment", "")).strip()
    if not anchor_loc_commitment:
        raise HTTPException(status_code=400, detail="missing tsip anchor_loc_commitment (C6)")
    expected_anchor_loc, anchor_i, current_i = _expected_anchor_from_state(prev_state)
    if anchor_loc_commitment != expected_anchor_loc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"tsip anchor_loc_commitment mismatch (C6): "
                f"expected_idx={anchor_i} expected={expected_anchor_loc[:20]}... "
                f"got={anchor_loc_commitment[:20]}..."
            ),
        )

    expected_chain = _tsip_expected_chain(
        prev_chain_commitment, curr_loc_commitment, timestamp, window_id,
        payload_digest, secret_commitment_recv,
    )
    if curr_chain_commitment != expected_chain:
        raise HTTPException(status_code=400, detail="invalid tsip chain commitment")

    proof_obj = tsip.get("proof")
    public_signals = tsip.get("public_signals")
    if not isinstance(proof_obj, dict):
        raise HTTPException(status_code=400, detail="missing tsip proof")
    if not isinstance(public_signals, list) or len(public_signals) != len(PAPER_PUBLIC_SIGNAL_ORDER):
        raise HTTPException(status_code=400, detail="invalid tsip public_signals")

    expected_prev_field = str(commitment_to_field(prev_loc_commitment))
    expected_curr_field = str(commitment_to_field(curr_loc_commitment))
    if str(public_signals[0]) != expected_prev_field:
        raise HTTPException(status_code=400, detail="tsip public hash_prev mismatch")
    if str(public_signals[1]) != expected_curr_field:
        raise HTTPException(status_code=400, detail="tsip public hash_curr mismatch")

    expected_anchor_field = str(commitment_to_field(anchor_loc_commitment))
    if str(public_signals[2]) != expected_anchor_field:
        raise HTTPException(status_code=400, detail="tsip anchor hash public signal mismatch (C6)")

    step_dt = max(1, int(timestamp - prev_timestamp))
    expected_step_dt_sq = int(step_dt * step_dt)
    declared_step_dt_sq = int(tsip.get("step_dt_sq", 0) or 0)
    if declared_step_dt_sq != expected_step_dt_sq:
        raise HTTPException(
            status_code=400,
            detail=f"tsip step_dt_sq mismatch: declared={declared_step_dt_sq} expected={expected_step_dt_sq}",
        )
    if str(public_signals[3]) != str(declared_step_dt_sq):
        raise HTTPException(status_code=400, detail="tsip step_dt_sq public signal mismatch")

    stored_tier = int(prev_state.get("tier_vmax_sq", 0) or 0)
    if declared_tier_vmax_sq != stored_tier:
        raise HTTPException(status_code=400, detail="tsip tier_vmax_sq changed without re-enrollment")
    if str(public_signals[4]) != str(declared_tier_vmax_sq):
        raise HTTPException(status_code=400, detail="tsip tier_vmax_sq public signal mismatch")

    declared_tier_anchor_cap_sq = int(tsip.get("tier_anchor_cap_sq", 0) or 0)
    expected_tier_anchor_cap_sq = int(
        compute_tier_anchor_cap_sq(declared_tier_vmax_sq, TSIP_ADWC_WINDOW_K, declared_step_dt_sq)
    )
    if declared_tier_anchor_cap_sq != expected_tier_anchor_cap_sq:
        raise HTTPException(
            status_code=400,
            detail=(
                f"tsip tier_anchor_cap_sq mismatch: "
                f"declared={declared_tier_anchor_cap_sq} expected={expected_tier_anchor_cap_sq}"
            ),
        )
    if str(public_signals[5]) != str(declared_tier_anchor_cap_sq):
        raise HTTPException(status_code=400, detail="tsip tier_anchor_cap_sq public signal mismatch")

    declared_cap_policy_sq = int(tsip.get("cap_policy_sq", 0) or 0)
    expected_cap_policy_sq = int(compute_policy_cap_sq(declared_tier_anchor_cap_sq, TSIP_POLICY_CAP_RATIO))
    if declared_cap_policy_sq != expected_cap_policy_sq:
        raise HTTPException(
            status_code=400,
            detail=(
                f"tsip cap_policy_sq mismatch: "
                f"declared={declared_cap_policy_sq} expected={expected_cap_policy_sq}"
            ),
        )
    if declared_cap_policy_sq > declared_tier_anchor_cap_sq:
        raise HTTPException(status_code=400, detail="tsip cap_policy_sq exceeds tier_anchor_cap_sq")
    if str(public_signals[6]) != str(declared_cap_policy_sq):
        raise HTTPException(status_code=400, detail="tsip cap_policy_sq public signal mismatch (C6)")

    if str(public_signals[16]) != declared_sc_field:
        raise HTTPException(status_code=400, detail="tsip secret_commitment public signal mismatch (P5)")

    stored_modeset = str(prev_state.get("modeset_commitment", "")).strip()
    if stored_modeset and declared_modeset_commitment != stored_modeset:
        raise HTTPException(status_code=400, detail="tsip modeset_commitment changed without re-enrollment")
    if str(public_signals[17]) != declared_modeset_commitment:
        raise HTTPException(status_code=400, detail="tsip modeset_commitment public signal mismatch")

    stored_mode_tag = str(prev_state.get("mode_tag", "")).strip()
    if stored_mode_tag and declared_mode_tag != stored_mode_tag:
        raise HTTPException(status_code=400, detail="tsip mode_tag changed without re-enrollment")
    if str(public_signals[18]) != declared_mode_tag:
        raise HTTPException(status_code=400, detail="tsip mode_tag public signal mismatch")

    proof_key = (int(r.round_id), str(r.submission_id))
    tsip_proof_attempted_submission_keys.add(proof_key)
    ok, err = verify_tsip_proof(proof_obj, public_signals)
    if ok:
        tsip_proof_verified_submission_keys.add(proof_key)
        tsip_proof_failed_submission_keys.discard(proof_key)
    else:
        tsip_proof_failed_submission_keys.add(proof_key)
    if (not ok) and _is_tsip_verify_runtime_error(err):
        raise HTTPException(status_code=400, detail=f"tsip verifier runtime error: {err[:180]}")
    accept, dp_meta = _tsip_verify_dp_decision(r, ok)
    if TSIP_DEBUG and dp_meta.get("dp_enabled"):
        print(
            "[TSIP_DEBUG] verify_dp score=",
            dp_meta.get("score"),
            "noise=",
            dp_meta.get("noise"),
            "noisy_score=",
            dp_meta.get("noisy_score"),
            "threshold=",
            dp_meta.get("threshold"),
            "accept=",
            dp_meta.get("accept"),
            "round_id=",
            r.round_id,
            "submission_id=",
            r.submission_id,
            flush=True,
        )
    if not accept:
        if ok:
            raise HTTPException(status_code=400, detail="tsip proof rejected by noisy verifier")
        raise HTTPException(status_code=400, detail=f"invalid tsip proof: {err[:180]}")
    if TSIP_DEBUG:
        print(
            "[TSIP_DEBUG] verified_curr_loc=",
            curr_loc_commitment,
            "user_id=",
            user_id,
            "submission_id=",
            r.submission_id,
            "round_id=",
            r.round_id,
            flush=True,
        )


def _tsip_user_id(r: Report) -> str:
    if r.tsip is None:
        return ""
    return str(r.tsip.get("user_id", "")).strip()


def _is_bootstrap_submission(r: Report) -> bool:
    if not TSIP_ENABLE or r.tsip is None:
        return False
    user_id = _tsip_user_id(r)
    if not user_id:
        return False
    return tsip_state_by_user.get(user_id) is None


def _is_warmup_submission(r: Report) -> bool:
    """P1: Return True when the user is still within the warmup period.

    During warmup the chain is being established (depth < TSIP_WARMUP_ROUNDS).
    Submissions are validated and stored but NOT forwarded to aggregators,
    preventing a fresh account with a fully-fabricated first position from
    immediately influencing the aggregate.  This is the enrollment-trust
    assumption mitigation described in the paper.
    """
    if TSIP_WARMUP_ROUNDS <= 0:
        return False
    if not TSIP_ENABLE or r.tsip is None:
        return False
    user_id = _tsip_user_id(r)
    if not user_id:
        return False
    st = tsip_state_by_user.get(user_id)
    if st is None:
        # First enrollment submission is warmup-held.
        return True
    if _is_enrollment_payload(r.tsip):
        # Existing-state enrollment is rejected before this point; only the
        # initial enrollment may be held for warmup.
        return False
    count = int(st.get("warmup_count", st.get("accepted_count", 0) or 0))
    return count < TSIP_WARMUP_ROUNDS


def _committee_channel(channel: str) -> str:
    c = (channel or "").strip().upper()
    if c not in {"A", "R"}:
        raise HTTPException(status_code=400, detail="invalid committee channel")
    return c


def _sign_submission_lazy(**kwargs) -> str:
    try:
        from common.committee import sign_submission
    except ModuleNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"committee helpers unavailable: {e}") from e
    return sign_submission(**kwargs)


def _self_committee_signature(channel: str, r: Report) -> dict:
    if not SHUFFLER_COMMITTEE_SIGN_SECRET:
        raise HTTPException(status_code=500, detail="missing SHUFFLER_COMMITTEE_SIGN_SECRET")
    sig = _sign_submission_lazy(
        secret=SHUFFLER_COMMITTEE_SIGN_SECRET,
        channel=channel,
        round_id=int(r.round_id),
        submission_id=str(r.submission_id),
        idx=r.idx,
        val=r.val,
    )
    return {"shuffler_id": SHUFFLER_COMMITTEE_ID, "signature": sig}


def _collect_committee_signatures(channel: str, r: Report) -> List[dict]:
    c = _committee_channel(channel)
    sigs: List[dict] = [_self_committee_signature(c, r)]
    if not SHUFFLER_COMMITTEE_PEERS:
        return sigs

    req = {"channel": c, "report": r.model_dump(mode="json", exclude={"committee_sigs"})}
    headers = {}
    if SHUFFLER_COMMITTEE_TOKEN:
        headers["X-Committee-Token"] = SHUFFLER_COMMITTEE_TOKEN
    for peer in SHUFFLER_COMMITTEE_PEERS:
        url = f"{peer}{SHUFFLER_COMMITTEE_ATTEST_PATH}"
        try:
            resp = requests.post(url, json=req, headers=headers, timeout=SHUFFLER_COMMITTEE_TIMEOUT_SEC)
            if resp.status_code != 200:
                continue
            data = resp.json()
            sid = str(data.get("shuffler_id", "")).strip()
            sig = str(data.get("signature", "")).strip()
            if sid and sig:
                sigs.append({"shuffler_id": sid, "signature": sig})
        except Exception:
            continue

    unique: Dict[str, str] = {}
    for s in sigs:
        sid = str(s.get("shuffler_id", "")).strip()
        sig = str(s.get("signature", "")).strip()
        if sid and sid not in unique and sig:
            unique[sid] = sig
    return [{"shuffler_id": sid, "signature": sig} for sid, sig in unique.items()]


def _apply_committee_gate(channel: str, r: Report):
    if not SHUFFLER_COMMITTEE_ENABLE:
        return
    if SHUFFLER_COMMITTEE_THRESHOLD <= 0:
        raise HTTPException(status_code=400, detail="invalid SHUFFLER_COMMITTEE_THRESHOLD")
    sigs = _collect_committee_signatures(channel, r)
    if len(sigs) < SHUFFLER_COMMITTEE_THRESHOLD:
        raise HTTPException(
            status_code=400,
            detail=f"committee signatures not enough: got {len(sigs)} need {SHUFFLER_COMMITTEE_THRESHOLD}",
        )
    r.committee_sigs = [CommitteeSignature(**s) for s in sigs]


def ensure_tsip_not_blacklisted(r: Report):
    if not TSIP_ENABLE or r.tsip is None:
        return
    user_id = _tsip_user_id(r)
    if not user_id:
        return
    if user_id in tsip_blacklist_by_user:
        raise HTTPException(status_code=403, detail="tsip user blacklisted")


def register_tsip_rejection(r: Report, detail: str):
    if not TSIP_ENABLE or r.tsip is None or TSIP_BLACKLIST_THRESHOLD <= 0:
        return
    user_id = _tsip_user_id(r)
    if not user_id:
        return
    key = (int(r.round_id), str(r.submission_id))
    if key in tsip_rejected_submission_keys:
        return
    tsip_rejected_submission_keys.add(key)
    pending_tsip_by_submission.pop(key, None)
    pending_route_reports_by_submission.pop(key, None)
    tsip_verify_dp_decision_by_submission.pop(key, None)
    streak = tsip_reject_streak_by_user.get(user_id, 0) + 1
    tsip_reject_streak_by_user[user_id] = streak
    if streak >= TSIP_BLACKLIST_THRESHOLD:
        tsip_blacklist_by_user[user_id] = {
            "streak": streak,
            "detail": str(detail)[:180],
            "round_id": int(r.round_id),
            "submission_id": str(r.submission_id),
            "timestamp": int(time.time()),
        }


def clear_tsip_rejection_streak(user_id: str):
    if not user_id:
        return
    tsip_reject_streak_by_user.pop(user_id, None)


def register_tsip_submission(r: Report, channel: str) -> bool:
    if not TSIP_ENABLE or r.tsip is None:
        return True
    tsip = r.tsip
    user_id = str(tsip.get("user_id", "")).strip()
    curr_loc_commitment = str(tsip.get("curr_loc_commitment", "")).strip()
    curr_chain_commitment = str(tsip.get("curr_chain_commitment", "")).strip()
    timestamp = int(tsip.get("timestamp", 0) or 0)
    window_id = int(tsip.get("window_id", 0) or 0)
    is_enroll = _is_enrollment_payload(tsip)
    tier_vmax_sq = int(tsip.get("tier_vmax_sq", 0) or 0)
    modeset_commitment = str(tsip.get("modeset_commitment", "")).strip()
    mode_tag = str(tsip.get("mode_tag", "")).strip()
    secret_commitment = str(tsip.get("secret_commitment", "")).strip()
    secret_commitment_field = str(tsip.get("secret_commitment_field", "")).strip()
    binding_fingerprint = json.dumps(
        {
            "blob_hash": tsip.get("blob_hash"),
            "context": tsip.get("context"),
            "context_commitment": tsip.get("context_commitment"),
            "payload_commitment_v2": tsip.get("payload_commitment_v2"),
            "contribution_bit": tsip.get("contribution_bit"),
            "fingerprint_a": tsip.get("fingerprint_a"),
            "fingerprint_challenge": tsip.get("fingerprint_challenge"),
            "fingerprint_r": tsip.get("fingerprint_r"),
            "package_digest_a": tsip.get("package_digest_a"),
            "package_digest_r": tsip.get("package_digest_r"),
            "primary_commitment": tsip.get("primary_commitment"),
            "public_signals": tsip.get("public_signals"),
            "share_content_commitment_a": tsip.get("share_content_commitment_a"),
            "share_content_commitment_r": tsip.get("share_content_commitment_r"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    key = (int(r.round_id), str(r.submission_id))
    pending = pending_tsip_by_submission.setdefault(
        key,
        {
            "channels": set(),
            "user_id": user_id,
            "curr_loc_commitment": curr_loc_commitment,
            "curr_chain_commitment": curr_chain_commitment,
            "timestamp": timestamp,
            "window_id": window_id,
            "is_enroll": bool(is_enroll),
            "tier_vmax_sq": int(tier_vmax_sq),
            "modeset_commitment": modeset_commitment,
            "mode_tag": mode_tag,
            "secret_commitment": secret_commitment,
            "secret_commitment_field": secret_commitment_field,
            "binding_fingerprint": binding_fingerprint,
        },
    )
    if (
        pending["user_id"] != user_id
        or pending["curr_loc_commitment"] != curr_loc_commitment
        or pending["curr_chain_commitment"] != curr_chain_commitment
        or bool(pending["is_enroll"]) != bool(is_enroll)
        or int(pending["tier_vmax_sq"]) != int(tier_vmax_sq)
        or str(pending["modeset_commitment"]) != str(modeset_commitment)
        or str(pending["mode_tag"]) != str(mode_tag)
        or str(pending["binding_fingerprint"]) != str(binding_fingerprint)
    ):
        raise HTTPException(status_code=400, detail="tsip payload mismatch across A/R")
    channels = pending["channels"]
    channels.add(channel)
    if channels == {"A", "R"}:
        prev_state = tsip_state_by_user.get(user_id, {})
        if bool(is_enroll):
            epoch = int(prev_state.get("enrollment_epoch", 0) or 0) + 1
            next_state = {
                "loc_commitment": curr_loc_commitment,
                "chain_commitment": curr_chain_commitment,
                "timestamp": timestamp,
                "window_id": window_id,
                "accepted_count": 1,
                "adwc_history": [{"idx": 0, "loc_commitment": str(curr_loc_commitment)}],
                "warmup_count": 1,
                "enrollment_epoch": int(epoch),
                "tier_vmax_sq": int(tier_vmax_sq),
                "modeset_commitment": str(modeset_commitment),
                "mode_tag": str(mode_tag),
            }
        else:
            adwc_history, next_count = _next_adwc_history(prev_state, curr_loc_commitment)
            prev_warm = int(prev_state.get("warmup_count", 0) or 0)
            next_state = {
                "loc_commitment": curr_loc_commitment,
                "chain_commitment": curr_chain_commitment,
                "timestamp": timestamp,
                "window_id": window_id,
                "accepted_count": int(next_count),
                "adwc_history": adwc_history,
                "warmup_count": int(prev_warm + 1),
                "enrollment_epoch": int(prev_state.get("enrollment_epoch", 1) or 1),
                "tier_vmax_sq": int(tier_vmax_sq),
                "modeset_commitment": str(modeset_commitment),
                "mode_tag": str(mode_tag),
            }
        state_digest = hashlib.sha256(
            json.dumps(
                {
                    "binding": binding_fingerprint,
                    "round_id": int(r.round_id),
                    "submission_id": str(r.submission_id),
                    "user_id": user_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        timing_token_digest = hashlib.sha256(
            json.dumps(
                {
                    "timestamp": timestamp,
                    "window_id": window_id,
                    "user_id": user_id,
                    "epoch": int(next_state["enrollment_epoch"]),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        accountability = _commit_accountable_state(
            user_id=user_id,
            state=next_state,
            previous_state=prev_state,
            is_enrollment=bool(is_enroll),
            report_digest=state_digest,
            timing_token_digest=timing_token_digest,
            secret_commitment=str(secret_commitment),
            secret_commitment_field=str(secret_commitment_field),
        )
        tsip_state_by_user[user_id] = next_state
        tsip_secret_commitment_by_user[user_id] = str(secret_commitment)
        tsip_secret_commitment_field_by_user[user_id] = str(secret_commitment_field)
        if accountability is not None:
            tsip_state_receipt_by_submission[key] = accountability
        clear_tsip_rejection_streak(user_id)
        pending_tsip_by_submission.pop(key, None)
        tsip_verify_dp_decision_by_submission.pop(key, None)
        return True
    return False


def queue_tsip_pair_if_ready(
    r: Report,
    channel: str,
    pair_ready: bool,
    bootstrap_hold: bool,
    warmup_hold: bool,
) -> None:
    key = (int(r.round_id), str(r.submission_id))
    pending = pending_route_reports_by_submission.setdefault(
        key,
        {"reports": {}, "bootstrap_hold": False, "warmup_hold": False},
    )
    reports = pending["reports"]
    reports[str(channel)] = r.model_copy(deep=True)
    pending["bootstrap_hold"] = bool(pending["bootstrap_hold"] or bootstrap_hold)
    pending["warmup_hold"] = bool(pending["warmup_hold"] or warmup_hold)
    if not pair_ready:
        return
    if set(reports) != {"A", "R"}:
        raise HTTPException(status_code=500, detail="tsip pair marked ready without both routes")
    held = bool(
        (TSIP_BOOTSTRAP_POLICY == "enroll_only" and pending["bootstrap_hold"])
        or pending["warmup_hold"]
    )
    if held:
        rid = int(current_round_id)
        tsip_bootstrap_held_by_round[rid] = tsip_bootstrap_held_by_round.get(rid, 0) + 1
    else:
        queueA.append(reports["A"])
        queueR.append(reports["R"])
    pending_route_reports_by_submission.pop(key, None)

def validate_report(r: Report, channel: str):
    rejection_key = (int(r.round_id), str(r.submission_id))
    if TSIP_ENABLE and rejection_key in tsip_rejected_submission_keys:
        raise HTTPException(status_code=400, detail="paired TSIP route previously rejected")
    if len(r.idx) != KPRIME or len(r.val) != KPRIME:
        raise HTTPException(status_code=400, detail="bad length")

    if not r.submission_id:
        raise HTTPException(status_code=400, detail="empty submission_id")

    # idx 范围
    for c in r.idx:
        if not (0 <= int(c) < DOMAIN):
            raise HTTPException(status_code=400, detail=f"idx out of range: {c}")

    # idx 必须唯一（贡献界限）
    if len(set(r.idx)) != KPRIME:
        raise HTTPException(status_code=400, detail="duplicate idx in one report")

    # val 必须是 0..MASK 的 32-bit share
    for v in r.val:
        iv = int(v)
        if iv < 0 or iv > MASK:
            raise HTTPException(status_code=400, detail=f"val out of range: {iv}")

    if PROOF_ENABLE:
        if r.proof is None:
            raise HTTPException(status_code=400, detail="missing proof")
        if r.proof.m is not None and int(r.proof.m) != PROOF_M:
            raise HTTPException(status_code=400, detail="proof m mismatch")
        s = float(r.proof.s)
        if not math.isfinite(s) or s < 0:
            raise HTTPException(status_code=400, detail="invalid proof s")
        if PROOF_DIM > 0 and r.proof.dim is not None and int(r.proof.dim) != PROOF_DIM:
            raise HTTPException(status_code=400, detail="proof dim mismatch")
        dim = int(r.proof.dim or PROOF_DIM)
        threshold = proof_threshold(int(r.round_id), dim)
        if s > threshold:
            raise HTTPException(status_code=400, detail="proof S over threshold")
    if ZK_STEP_ENABLE:
        if r.zk_step is None:
            raise HTTPException(status_code=400, detail="missing zk_step")
        proof_obj = r.zk_step.get("proof")
        public_signals = r.zk_step.get("public_signals")
        if not isinstance(proof_obj, dict):
            raise HTTPException(status_code=400, detail="invalid zk_step proof")
        if not isinstance(public_signals, list):
            raise HTTPException(status_code=400, detail="invalid zk_step public_signals")
        ok, err = verify_zk_step_proof(proof_obj, public_signals)
        if not ok:
            raise HTTPException(status_code=400, detail=f"invalid zk_step proof: {err[:180]}")
    if TSIP_ENABLE:
        validate_tsip_report(r, channel)


if TSIP_BOOTSTRAP_POLICY not in {"legacy_accept", "enroll_only"}:
    raise RuntimeError(f"invalid TSIP_BOOTSTRAP_POLICY: {TSIP_BOOTSTRAP_POLICY}")


@app.post("/committee/attest")
def committee_attest(
    req: CommitteeAttestRequest,
    x_committee_token: str | None = Header(default=None, alias="X-Committee-Token"),
):
    if not SHUFFLER_COMMITTEE_ENABLE:
        raise HTTPException(status_code=403, detail="committee mode disabled")
    if SHUFFLER_COMMITTEE_TOKEN and x_committee_token != SHUFFLER_COMMITTEE_TOKEN:
        raise HTTPException(status_code=403, detail="invalid committee token")
    r = req.report
    channel = _committee_channel(req.channel)
    with lock:
        ensure_tsip_not_blacklisted(r)
        try:
            validate_report(r, channel)
        except HTTPException as e:
            register_tsip_rejection(r, str(e.detail))
            raise
        register_tsip_submission(r, channel)
        sig = _self_committee_signature(channel, r)
    return {"ok": True, "shuffler_id": sig["shuffler_id"], "signature": sig["signature"]}


@app.post("/round/new")
def round_new():
    global current_round_id
    with round_lock:
        # 用毫秒时间戳 + 随机，避免重复
        current_round_id = int(time.time() * 1000) % 2_000_000_000
        # 也可以简单点：current_round_id += 1
        rid = current_round_id
    if PROOF_ENABLE and PROOF_CALIBRATE:
        try:
            dim = PROOF_DIM if PROOF_DIM > 0 else max(1, TRAJ_POINTS - 1)
            proof_threshold_by_round[rid] = calibrate_threshold(rid, dim)
        except Exception:
            pass
    return {"ok": True, "round_id": rid}

@app.get("/round")
def round_get():
    with round_lock:
        return {"ok": True, "round_id": current_round_id}
@app.post("/ingestA")
def ingestA(r: Report):
    global current_round_id
    with lock:
        # ✅ 强制覆盖 round_id，保证这一轮一致
        r.round_id = current_round_id
        ensure_tsip_not_blacklisted(r)
        try:
            validate_report(r, "A")
        except HTTPException as e:
            register_tsip_rejection(r, str(e.detail))
            raise
        seenA = seenA_by_round.setdefault(current_round_id, set())
        if r.submission_id in seenA:
            raise HTTPException(status_code=400, detail="duplicate submission_id in A for this round")
        bootstrap_hold = _is_bootstrap_submission(r)
        # P1: check warmup hold *before* registering (count not yet incremented)
        warmup_hold = _is_warmup_submission(r)
        _apply_committee_gate("A", r)
        seenA.add(r.submission_id)
        pair_ready = register_tsip_submission(r, "A")
        queue_tsip_pair_if_ready(r, "A", pair_ready, bootstrap_hold, warmup_hold)
        qlen = len(queueA)
    return {
        "ok": True,
        "queuedA": qlen,
        "round_id": current_round_id,
        "bootstrap_held": bool(TSIP_BOOTSTRAP_POLICY == "enroll_only" and bootstrap_hold),
        "warmup_held": bool(warmup_hold),
        "pair_ready": bool(pair_ready),
    }

@app.post("/ingestR")
def ingestR(r: Report):
    global current_round_id
    with lock:
        # ✅ 强制覆盖 round_id，保证这一轮一致
        r.round_id = current_round_id
        ensure_tsip_not_blacklisted(r)
        try:
            validate_report(r, "R")
        except HTTPException as e:
            register_tsip_rejection(r, str(e.detail))
            raise
        seenR = seenR_by_round.setdefault(current_round_id, set())
        if r.submission_id in seenR:
            raise HTTPException(status_code=400, detail="duplicate submission_id in R for this round")
        bootstrap_hold = _is_bootstrap_submission(r)
        # P1: check warmup hold *before* registering (count not yet incremented)
        warmup_hold = _is_warmup_submission(r)
        _apply_committee_gate("R", r)
        seenR.add(r.submission_id)
        pair_ready = register_tsip_submission(r, "R")
        queue_tsip_pair_if_ready(r, "R", pair_ready, bootstrap_hold, warmup_hold)
        qlen = len(queueR)
    return {
        "ok": True,
        "queuedR": qlen,
        "round_id": current_round_id,
        "bootstrap_held": bool(TSIP_BOOTSTRAP_POLICY == "enroll_only" and bootstrap_hold),
        "warmup_held": bool(warmup_hold),
        "pair_ready": bool(pair_ready),
        "state_accountability": tsip_state_receipt_by_submission.get(
            (int(r.round_id), str(r.submission_id))
        ),
    }

def flush_one(url: str, batch: List[Report]):
    payload = {"reports": [b.model_dump() for b in batch]}
    requests.post(url, json=payload, timeout=5)

def flusher_loop():
    while True:
        time.sleep(FLUSH_SECONDS)
        with lock:
            batchA = queueA[:]
            batchR = queueR[:]
            queueA.clear()
            queueR.clear()

        if batchA:
            random.shuffle(batchA)
            try:
                flush_one(AGG_A_URL, batchA)
            except Exception:
                pass

        if batchR:
            random.shuffle(batchR)
            try:
                flush_one(AGG_R_URL, batchR)
            except Exception:
                pass

@app.on_event("startup")
def startup():
    t = threading.Thread(target=flusher_loop, daemon=True)
    t.start()


@app.get("/tsip/state")
def tsip_state(user_id: str):
    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="missing user_id")
    with lock:
        st = _restore_accountable_state(uid)
        if not st:
            return {"ok": True, "exists": False, "user_id": uid}
        hist = _normalize_adwc_history(st)
        response = {
            "ok": True,
            "exists": True,
            "user_id": uid,
            "accepted_count": int(st.get("accepted_count", len(hist))),
            "warmup_count": int(st.get("warmup_count", 0) or 0),
            "enrollment_epoch": int(st.get("enrollment_epoch", 0) or 0),
            "loc_commitment": str(st.get("loc_commitment", "")),
            "chain_commitment": str(st.get("chain_commitment", "")),
            "timestamp": int(st.get("timestamp", 0) or 0),
            "window_id": int(st.get("window_id", 0) or 0),
            "tier_vmax_sq": int(st.get("tier_vmax_sq", 0) or 0),
            "modeset_commitment": str(st.get("modeset_commitment", "")),
            "mode_tag": str(st.get("mode_tag", "")),
            "adwc_history": hist,
            "adwc_window_k": int(TSIP_ADWC_WINDOW_K),
            "policy_cap_ratio": float(TSIP_POLICY_CAP_RATIO),
        }
        store = _state_accountability()
        if store is not None:
            response["state_accountability"] = {
                "latest_receipt": store.latest_receipt(uid, int(st.get("enrollment_epoch", 0) or 0)),
                "status": store.status(),
            }
        return response


@app.get("/tsip/checkpoint")
def tsip_checkpoint():
    with lock:
        store = _state_accountability()
        if store is None:
            raise HTTPException(status_code=404, detail="state accountability disabled")
        return {"ok": True, "checkpoint": store.latest_checkpoint(), "status": store.status()}


@app.get("/health")
def health():
    with lock:
        current_proof_attempts = sum(1 for rid, _ in tsip_proof_attempted_submission_keys if rid == int(current_round_id))
        current_proof_verified = sum(1 for rid, _ in tsip_proof_verified_submission_keys if rid == int(current_round_id))
        current_proof_failed = sum(1 for rid, _ in tsip_proof_failed_submission_keys if rid == int(current_round_id))
        usage = tsip_verify_dp_usage_by_round.get(
            int(current_round_id),
            {
                "calls": 0.0,
                "spent": 0.0,
                "deterministic_accept": 0.0,
                "deterministic_reject": 0.0,
                "noisy_accept": 0.0,
                "noisy_reject": 0.0,
            },
        )
        return {
            "ok": True,
            "queuedA": len(queueA),
            "queuedR": len(queueR),
            "aggA_url": AGG_A_URL,
            "aggR_url": AGG_R_URL,
            "tsip_enable": TSIP_ENABLE,
            "tsip_verify_mode": TSIP_VERIFY_MODE,
            "tsip_circuit_profile": TSIP_CIRCUIT_PROFILE,
            "tsip_users": len(tsip_state_by_user),
            "tsip_adwc_profile": TSIP_ADWC_PROFILE,
            "tsip_adwc_window_k": TSIP_ADWC_WINDOW_K,
            "tsip_policy_cap_ratio": TSIP_POLICY_CAP_RATIO,
            "tsip_blacklisted_users": len(tsip_blacklist_by_user),
            "tsip_blacklist_threshold": TSIP_BLACKLIST_THRESHOLD,
            "tsip_verify_dp_enable": TSIP_VERIFY_DP_ENABLE,
            "tsip_verify_epsilon": TSIP_VERIFY_EPSILON,
            "tsip_verify_noisy_threshold": TSIP_VERIFY_NOISY_THRESHOLD,
            "tsip_verify_calls": int(usage["calls"]),
            "tsip_verify_spent": usage["spent"],
            "tsip_proof_attempts_current_round": current_proof_attempts,
            "tsip_proof_verified_current_round": current_proof_verified,
            "tsip_proof_failed_current_round": current_proof_failed,
            "tsip_proof_attempts_total": len(tsip_proof_attempted_submission_keys),
            "tsip_proof_verified_total": len(tsip_proof_verified_submission_keys),
            "tsip_proof_failed_total": len(tsip_proof_failed_submission_keys),
            "tsip_ea_require": TSIP_EA_REQUIRE,
            "tsip_ea_kids": sorted(TSIP_EA_PUBKEYS.keys()),
            "committee_enable": SHUFFLER_COMMITTEE_ENABLE,
            "committee_id": SHUFFLER_COMMITTEE_ID,
            "committee_threshold": SHUFFLER_COMMITTEE_THRESHOLD,
            "committee_peer_count": len(SHUFFLER_COMMITTEE_PEERS),
            "tsip_bootstrap_policy": TSIP_BOOTSTRAP_POLICY,
            "tsip_allow_reenroll": TSIP_ALLOW_REENROLL,
            "tsip_bootstrap_held_current_round": tsip_bootstrap_held_by_round.get(int(current_round_id), 0),
            "tsip_state_accountability_enable": TSIP_STATE_ACCOUNTABILITY_ENABLE,
            "tsip_state_accountability": (
                _state_accountability().status() if TSIP_STATE_ACCOUNTABILITY_ENABLE else {"enabled": False}
            ),
        }
