from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Dict, Set, Optional
import os, time, random, threading, math, subprocess, tempfile, shutil, json
import requests
from fastapi import HTTPException
from common.utils import chi2_ppf, seed_from_round, gaussian_vectors
from common.tsip import commitment_to_field
app = FastAPI()

def _first_existing_path(candidates: list[str]) -> str:
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]



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
SEED_SECRET = os.getenv("RISERFL_SEED_SECRET", "rise_fed")
CITY_SIZE_M = float(os.getenv("CITY_SIZE_M", "10000"))
DT_SEC = int(os.getenv("DT_SEC", "10"))
TRAJ_POINTS = int(os.getenv("TRAJ_POINTS", "300"))
MAX_STEP_M = float(os.getenv("MAX_STEP_M", "80.0"))

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

class Proof(BaseModel):
    s: float
    m: Optional[int] = None
    dim: Optional[int] = None

class Report(BaseModel):
    round_id: int
    submission_id: str
    idx: List[int] = Field(..., min_length=KPRIME, max_length=KPRIME)
    val: List[int] = Field(..., min_length=KPRIME, max_length=KPRIME)
    proof: Optional[Proof] = None
    zk_step: Optional[Dict[str, object]] = None
    tsip: Optional[Dict[str, object]] = None

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


def validate_tsip_report(r: Report):
    if r.tsip is None:
        raise HTTPException(status_code=400, detail="missing tsip payload")
    tsip = r.tsip
    user_id = str(tsip.get("user_id", "")).strip()
    curr_commitment = str(tsip.get("curr_commitment", "")).strip()
    prev_commitment = str(tsip.get("prev_commitment", "")).strip()
    timestamp = int(tsip.get("timestamp", 0) or 0)
    window_id = int(tsip.get("window_id", 0) or 0)
    if not user_id:
        raise HTTPException(status_code=400, detail="invalid tsip user_id")
    if not curr_commitment:
        raise HTTPException(status_code=400, detail="missing curr_commitment")
    if timestamp <= 0:
        raise HTTPException(status_code=400, detail="invalid tsip timestamp")

    prev_state = tsip_state_by_user.get(user_id)
    if prev_state is None:
        if prev_commitment:
            raise HTTPException(status_code=400, detail="unexpected prev_commitment for first tsip submission")
        return

    expected_prev = str(prev_state["commitment"])
    if prev_commitment != expected_prev:
        raise HTTPException(status_code=400, detail="tsip prev_commitment mismatch")
    prev_timestamp = int(prev_state["timestamp"])
    if timestamp <= prev_timestamp:
        raise HTTPException(status_code=400, detail="tsip timestamp not monotonic")
    if window_id < int(prev_state.get("window_id", 0)):
        raise HTTPException(status_code=400, detail="tsip window reversal")
    max_gap = max(1, TSIP_WINDOW_SEC) * max(1, TSIP_MAX_GAP_WINDOWS)
    if timestamp - prev_timestamp > max_gap:
        raise HTTPException(status_code=400, detail="tsip time gap too large")

    proof_obj = tsip.get("proof")
    public_signals = tsip.get("public_signals")
    if not isinstance(proof_obj, dict):
        raise HTTPException(status_code=400, detail="missing tsip proof")
    if not isinstance(public_signals, list) or len(public_signals) < 3:
        raise HTTPException(status_code=400, detail="invalid tsip public_signals")

    expected_prev_field = str(commitment_to_field(prev_commitment))
    expected_curr_field = str(commitment_to_field(curr_commitment))
    if str(public_signals[0]) != expected_prev_field:
        raise HTTPException(status_code=400, detail="tsip public hash_prev mismatch")
    if str(public_signals[1]) != expected_curr_field:
        raise HTTPException(status_code=400, detail="tsip public hash_curr mismatch")
    ok, err = verify_tsip_proof(proof_obj, public_signals)
    if not ok:
        raise HTTPException(status_code=400, detail=f"invalid tsip proof: {err[:180]}")


def register_tsip_submission(r: Report, channel: str):
    if not TSIP_ENABLE or r.tsip is None:
        return
    tsip = r.tsip
    user_id = str(tsip.get("user_id", "")).strip()
    curr_commitment = str(tsip.get("curr_commitment", "")).strip()
    timestamp = int(tsip.get("timestamp", 0) or 0)
    window_id = int(tsip.get("window_id", 0) or 0)
    key = (int(r.round_id), str(r.submission_id))
    pending = pending_tsip_by_submission.setdefault(
        key,
        {
            "channels": set(),
            "user_id": user_id,
            "curr_commitment": curr_commitment,
            "timestamp": timestamp,
            "window_id": window_id,
        },
    )
    if pending["user_id"] != user_id or pending["curr_commitment"] != curr_commitment:
        raise HTTPException(status_code=400, detail="tsip payload mismatch across A/R")
    channels = pending["channels"]
    channels.add(channel)
    if channels == {"A", "R"}:
        tsip_state_by_user[user_id] = {
            "commitment": curr_commitment,
            "timestamp": timestamp,
            "window_id": window_id,
        }
        pending_tsip_by_submission.pop(key, None)

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
        validate_report(r)
        seenA = seenA_by_round.setdefault(current_round_id, set())
        if r.submission_id in seenA:
            raise HTTPException(status_code=400, detail="duplicate submission_id in A for this round")
        seenA.add(r.submission_id)
        register_tsip_submission(r, "A")
        queueA.append(r)
        qlen = len(queueA)
    return {"ok": True, "queuedA": qlen, "round_id": current_round_id}

@app.post("/ingestR")
def ingestR(r: Report):
    global current_round_id
    with lock:
        # ✅ 强制覆盖 round_id，保证这一轮一致
        r.round_id = current_round_id
        validate_report(r)
        seenR = seenR_by_round.setdefault(current_round_id, set())
        if r.submission_id in seenR:
            raise HTTPException(status_code=400, detail="duplicate submission_id in R for this round")
        seenR.add(r.submission_id)
        register_tsip_submission(r, "R")
        queueR.append(r)
        qlen = len(queueR)
    return {"ok": True, "queuedR": qlen, "round_id": current_round_id}

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
        return {
            "ok": True,
            "queuedA": len(queueA),
            "queuedR": len(queueR),
            "aggA_url": AGG_A_URL,
            "aggR_url": AGG_R_URL,
            "tsip_enable": TSIP_ENABLE,
            "tsip_users": len(tsip_state_by_user),
        }
