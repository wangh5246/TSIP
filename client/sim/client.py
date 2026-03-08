import os, time, uuid, random, json, subprocess, tempfile, shutil
import requests
from common.utils import gaussian_preview, gaussian_vectors, prp, derive_prp_seed_from_share

def _first_existing_path(candidates: list[str]) -> str:
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]

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
ZK_STEP_ENABLE = os.getenv("ZK_STEP_ENABLE", "0") == "1"
ZK_STEP_INDEX = int(os.getenv("ZK_STEP_INDEX", str(TELEPORT_INDEX)))
ZK_STEP_SNARKJS = os.getenv("ZK_STEP_SNARKJS", "snarkjs")
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
PRP_ENABLE = os.getenv("PRP_ENABLE", "1") == "1"
PRP_ROUNDS = int(os.getenv("PRP_ROUNDS", "8"))
PRP_MIN_DOMAIN = int(os.getenv("PRP_MIN_DOMAIN", "1000000"))
CLOVER_SHARE_URL_A = os.getenv("CLOVER_SHARE_URL_A", "http://aggregator_a:8002/clover/key_share")
CLOVER_SHARE_URL_R = os.getenv("CLOVER_SHARE_URL_R", "http://aggregator_r:8003/clover/key_share")
CLOVER_CLIENT_TOKEN_A = os.getenv("CLOVER_CLIENT_TOKEN_A", "")
CLOVER_CLIENT_TOKEN_R = os.getenv("CLOVER_CLIENT_TOKEN_R", "")

QMAX = (1 << QUANT_BITS) - 1  # INT4 => 15



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
                print("shuffler is ready:", r.json())
                return
        except Exception:
            pass

        if time.time() - start > timeout_sec:
            raise RuntimeError("Timeout waiting for shuffler to be ready")

        print("waiting for shuffler...")
        time.sleep(1)

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

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
    if shutil.which(ZK_STEP_SNARKJS) is None:
        raise RuntimeError(f"snarkjs not found: {ZK_STEP_SNARKJS}")
    if not os.path.exists(ZK_STEP_WASM):
        raise RuntimeError(f"missing ZK_STEP_WASM: {ZK_STEP_WASM}")
    if not os.path.exists(ZK_STEP_ZKEY):
        raise RuntimeError(f"missing ZK_STEP_ZKEY: {ZK_STEP_ZKEY}")

def build_zk_step_inputs(trajectory):
    if len(trajectory) < 2:
        return {"dx": 0, "dy": 0, "dt": 1, "vmax": int(round(MAX_STEP_M))}
    idx = max(1, min(ZK_STEP_INDEX, len(trajectory) - 1))
    x1, y1, t1 = trajectory[idx - 1]
    x2, y2, t2 = trajectory[idx]
    dx = int(round(abs(x2 - x1)))
    dy = int(round(abs(y2 - y1)))
    dt = max(1, int(round(abs(t2 - t1))))
    vmax = max(1, int(round(MAX_STEP_M)))
    return {"dx": dx, "dy": dy, "dt": dt, "vmax": vmax}

def generate_zk_step_proof(inputs: dict):
    with tempfile.TemporaryDirectory(prefix="zk_step_client_") as td:
        input_path = os.path.join(td, "input.json")
        proof_path = os.path.join(td, "proof.json")
        public_path = os.path.join(td, "public.json")

        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(inputs, f, ensure_ascii=True)

        cmd = [
            ZK_STEP_SNARKJS,
            "groth16",
            "fullprove",
            input_path,
            ZK_STEP_WASM,
            ZK_STEP_ZKEY,
            proof_path,
            public_path,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=ZK_STEP_TIMEOUT_SEC,
            check=False,
        )
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(msg or "snarkjs fullprove failed")

        with open(proof_path, "r", encoding="utf-8") as f:
            proof = json.load(f)
        with open(public_path, "r", encoding="utf-8") as f:
            public_signals = json.load(f)
    return {"proof": proof, "public_signals": public_signals, "inputs": inputs}

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
):
    """
    返回 idx/val:
      - idx 长度 KPRIME，且全部唯一
      - 前 K 个是真实 Top-k（不足 K 用 0 值 padding）
      - 后 KD 个是 dummy（val 固定 DUMMY_Q）
    """
    # 1) 合成轨迹
    rng = random.Random(user_seed)
    traj = gen_synthetic_trajectory(rng)
    if malicious:
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
                raise

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
    return idx, val, proof, zk_step

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
        resp = requests.post(url, json=report, timeout=5)
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
    wait_for_shuffler()
    rid = new_round_id()
    print("new round:", rid)
    if DEBUG_RANDOMNESS:
        randomness_self_test(rid)
    ensure_zk_step_ready()
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
    total = 0
    valid_clients = 0
    rejected = 0
    malicious_total = 0
    malicious_rejected = 0
    false_rejects = 0
    for i in range(200):
        round_id = rid
        submission_id = f"U{i}_{uuid.uuid4().hex[:8]}"

        seed = random.getrandbits(64)
        is_malicious = (MALICIOUS_RATE > 0 and random.random() < MALICIOUS_RATE)
        idx, val, proof, zk_step = make_idx_and_val(
            user_seed=seed,
            report_idx=i,
            round_id=round_id,
            proof_seed=proof_seed,
            prp_seed_a=prp_seed_a,
            prp_seed_r=prp_seed_r,
            malicious=is_malicious,
        )
        if not validate_unique_idx(idx, val, seed, round_id, submission_id):
            raise RuntimeError("duplicate idx generated; aborting send")
        valA, valR = secret_share_vals(val)

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

        ok_a, data_a, _ = post_report(SHUFFLER_URL_A, reportA)
        ok_r, data_r, _ = post_report(SHUFFLER_URL_R, reportR)
        accepted = ok_a and ok_r

        if i % 20 == 0:
            print("sent", i, "A_ok=", ok_a, "R_ok=", ok_r, "malicious=", is_malicious, "A_resp=", data_a, "R_resp=", data_r)

        total += 1
        if accepted:
            valid_clients += 1
        else:
            rejected += 1
        if is_malicious:
            malicious_total += 1
            if not accepted:
                malicious_rejected += 1
        else:
            if not accepted:
                false_rejects += 1

        time.sleep(0.01)
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
    time.sleep(5)

if __name__ == "__main__":
    main()
