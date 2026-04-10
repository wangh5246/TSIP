from fastapi import FastAPI, Header
from pydantic import BaseModel, Field
from typing import List, Dict, Set, Optional
import os, time, random, threading, math, subprocess, tempfile, shutil, json, hashlib
import requests
from fastapi import HTTPException
from common.utils import chi2_ppf, seed_from_round, gaussian_vectors
from common.tsip import commitment_to_field, compute_chain_commitment
app = FastAPI()

def _first_existing_path(candidates: list[str]) -> str:
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def _normalize_tsip_verify_mode(name: str, value: str) -> str:
    mode = (value or "full").strip().lower()
    if mode not in {"full", "commitment_only"}:
        raise RuntimeError(f"invalid {name}: {value}")
    return mode



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
            "/Users/wanghao/Desktop/risefl_mvp/zk/tsip_step/verification_key.json",
            "zk/tsip_step/verification_key.json",
        ]
    ),
)
ZK_STEP_VERIFY_TIMEOUT_SEC = int(os.getenv("ZK_STEP_VERIFY_TIMEOUT_SEC", "30"))
TSIP_ENABLE = os.getenv("TSIP_ENABLE", "0") == "1"
TSIP_VERIFY_MODE = _normalize_tsip_verify_mode("TSIP_VERIFY_MODE", os.getenv("TSIP_VERIFY_MODE", "full"))
TSIP_SNARKJS = os.getenv("TSIP_SNARKJS", "snarkjs")
TSIP_VKEY = os.getenv(
    "TSIP_VKEY",
    _first_existing_path(
        [
            "/app/zk/tsip_main/verification_key.json",
            "/Users/wanghao/Desktop/risefl_mvp/zk/tsip_main/verification_key.json",
            "zk/tsip_main/verification_key.json",
        ]
    ),
)
TSIP_VERIFY_TIMEOUT_SEC = int(os.getenv("TSIP_VERIFY_TIMEOUT_SEC", "30"))
TSIP_WINDOW_SEC = int(os.getenv("TSIP_WINDOW_SEC", "60"))
TSIP_MAX_GAP_WINDOWS = int(os.getenv("TSIP_MAX_GAP_WINDOWS", "2"))
TSIP_BLACKLIST_THRESHOLD = int(os.getenv("TSIP_BLACKLIST_THRESHOLD", "3"))
TSIP_DEBUG = os.getenv("TSIP_DEBUG", "0") == "1"
TSIP_BOOTSTRAP_POLICY = os.getenv("TSIP_BOOTSTRAP_POLICY", "legacy_accept").strip().lower()
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
tsip_reject_streak_by_user: Dict[str, int] = {}
tsip_blacklist_by_user: Dict[str, Dict[str, object]] = {}
tsip_rejected_submission_keys: Set[tuple[int, str]] = set()
tsip_verify_dp_decision_by_submission: Dict[tuple[int, str], Dict[str, object]] = {}
tsip_verify_dp_usage_by_round: Dict[int, Dict[str, float]] = {}
tsip_bootstrap_held_by_round: Dict[int, int] = {}

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


def validate_tsip_report(r: Report):
    if r.tsip is None:
        raise HTTPException(status_code=400, detail="missing tsip payload")
    tsip = r.tsip
    user_id = str(tsip.get("user_id", "")).strip()
    prev_loc_commitment = str(tsip.get("prev_loc_commitment", "")).strip()
    curr_loc_commitment = str(tsip.get("curr_loc_commitment", "")).strip()
    prev_chain_commitment = str(tsip.get("prev_chain_commitment", "")).strip()
    curr_chain_commitment = str(tsip.get("curr_chain_commitment", "")).strip()
    timestamp = int(tsip.get("timestamp", 0) or 0)
    window_id = int(tsip.get("window_id", 0) or 0)
    if not user_id:
        raise HTTPException(status_code=400, detail="invalid tsip user_id")
    if not curr_loc_commitment or not curr_chain_commitment:
        raise HTTPException(status_code=400, detail="missing tsip commitments")
    if timestamp <= 0:
        raise HTTPException(status_code=400, detail="invalid tsip timestamp")

    prev_state = tsip_state_by_user.get(user_id)
    if prev_state is None:
        if prev_loc_commitment or prev_chain_commitment:
            raise HTTPException(status_code=400, detail="unexpected previous tsip commitment for first submission")
        expected_chain = compute_chain_commitment("", curr_loc_commitment, timestamp, window_id)
        if curr_chain_commitment != expected_chain:
            raise HTTPException(status_code=400, detail="invalid initial tsip chain commitment")
        return

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

    expected_chain = compute_chain_commitment(prev_chain_commitment, curr_loc_commitment, timestamp, window_id)
    if curr_chain_commitment != expected_chain:
        raise HTTPException(status_code=400, detail="invalid tsip chain commitment")
    if TSIP_VERIFY_MODE == "commitment_only":
        if TSIP_DEBUG:
            print(
                "[TSIP_DEBUG] commitment_only accepted_curr_loc=",
                curr_loc_commitment,
                "user_id=",
                user_id,
                "submission_id=",
                r.submission_id,
                "round_id=",
                r.round_id,
                flush=True,
            )
        return

    proof_obj = tsip.get("proof")
    public_signals = tsip.get("public_signals")
    if not isinstance(proof_obj, dict):
        raise HTTPException(status_code=400, detail="missing tsip proof")
    if not isinstance(public_signals, list) or len(public_signals) < 3:
        raise HTTPException(status_code=400, detail="invalid tsip public_signals")

    expected_prev_field = str(commitment_to_field(prev_loc_commitment))
    expected_curr_field = str(commitment_to_field(curr_loc_commitment))
    if str(public_signals[0]) != expected_prev_field:
        raise HTTPException(status_code=400, detail="tsip public hash_prev mismatch")
    if str(public_signals[1]) != expected_curr_field:
        raise HTTPException(status_code=400, detail="tsip public hash_curr mismatch")
    ok, err = verify_tsip_proof(proof_obj, public_signals)
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


def register_tsip_submission(r: Report, channel: str):
    if not TSIP_ENABLE or r.tsip is None:
        return
    tsip = r.tsip
    user_id = str(tsip.get("user_id", "")).strip()
    curr_loc_commitment = str(tsip.get("curr_loc_commitment", "")).strip()
    curr_chain_commitment = str(tsip.get("curr_chain_commitment", "")).strip()
    timestamp = int(tsip.get("timestamp", 0) or 0)
    window_id = int(tsip.get("window_id", 0) or 0)
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
        },
    )
    if (
        pending["user_id"] != user_id
        or pending["curr_loc_commitment"] != curr_loc_commitment
        or pending["curr_chain_commitment"] != curr_chain_commitment
    ):
        raise HTTPException(status_code=400, detail="tsip payload mismatch across A/R")
    channels = pending["channels"]
    channels.add(channel)
    if channels == {"A", "R"}:
        tsip_state_by_user[user_id] = {
            "loc_commitment": curr_loc_commitment,
            "chain_commitment": curr_chain_commitment,
            "timestamp": timestamp,
            "window_id": window_id,
        }
        clear_tsip_rejection_streak(user_id)
        pending_tsip_by_submission.pop(key, None)
        tsip_verify_dp_decision_by_submission.pop(key, None)

def validate_report(r: Report):
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
        validate_tsip_report(r)


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
            validate_report(r)
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
            validate_report(r)
        except HTTPException as e:
            register_tsip_rejection(r, str(e.detail))
            raise
        seenA = seenA_by_round.setdefault(current_round_id, set())
        if r.submission_id in seenA:
            raise HTTPException(status_code=400, detail="duplicate submission_id in A for this round")
        bootstrap_hold = _is_bootstrap_submission(r)
        _apply_committee_gate("A", r)
        seenA.add(r.submission_id)
        register_tsip_submission(r, "A")
        if TSIP_BOOTSTRAP_POLICY == "enroll_only" and bootstrap_hold:
            rid = int(current_round_id)
            tsip_bootstrap_held_by_round[rid] = tsip_bootstrap_held_by_round.get(rid, 0) + 1
        else:
            queueA.append(r)
        qlen = len(queueA)
    return {
        "ok": True,
        "queuedA": qlen,
        "round_id": current_round_id,
        "bootstrap_held": bool(TSIP_BOOTSTRAP_POLICY == "enroll_only" and bootstrap_hold),
    }

@app.post("/ingestR")
def ingestR(r: Report):
    global current_round_id
    with lock:
        # ✅ 强制覆盖 round_id，保证这一轮一致
        r.round_id = current_round_id
        ensure_tsip_not_blacklisted(r)
        try:
            validate_report(r)
        except HTTPException as e:
            register_tsip_rejection(r, str(e.detail))
            raise
        seenR = seenR_by_round.setdefault(current_round_id, set())
        if r.submission_id in seenR:
            raise HTTPException(status_code=400, detail="duplicate submission_id in R for this round")
        bootstrap_hold = _is_bootstrap_submission(r)
        _apply_committee_gate("R", r)
        seenR.add(r.submission_id)
        register_tsip_submission(r, "R")
        if TSIP_BOOTSTRAP_POLICY == "enroll_only" and bootstrap_hold:
            rid = int(current_round_id)
            tsip_bootstrap_held_by_round[rid] = tsip_bootstrap_held_by_round.get(rid, 0) + 1
        else:
            queueR.append(r)
        qlen = len(queueR)
    return {
        "ok": True,
        "queuedR": qlen,
        "round_id": current_round_id,
        "bootstrap_held": bool(TSIP_BOOTSTRAP_POLICY == "enroll_only" and bootstrap_hold),
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

@app.get("/health")
def health():
    with lock:
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
            "tsip_users": len(tsip_state_by_user),
            "tsip_blacklisted_users": len(tsip_blacklist_by_user),
            "tsip_blacklist_threshold": TSIP_BLACKLIST_THRESHOLD,
            "tsip_verify_dp_enable": TSIP_VERIFY_DP_ENABLE,
            "tsip_verify_epsilon": TSIP_VERIFY_EPSILON,
            "tsip_verify_noisy_threshold": TSIP_VERIFY_NOISY_THRESHOLD,
            "tsip_verify_calls": int(usage["calls"]),
            "tsip_verify_spent": usage["spent"],
            "committee_enable": SHUFFLER_COMMITTEE_ENABLE,
            "committee_id": SHUFFLER_COMMITTEE_ID,
            "committee_threshold": SHUFFLER_COMMITTEE_THRESHOLD,
            "committee_peer_count": len(SHUFFLER_COMMITTEE_PEERS),
            "tsip_bootstrap_policy": TSIP_BOOTSTRAP_POLICY,
            "tsip_bootstrap_held_current_round": tsip_bootstrap_held_by_round.get(int(current_round_id), 0),
        }
