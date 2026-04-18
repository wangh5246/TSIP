from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import tempfile
from functools import lru_cache


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
MIMC_ROUNDS = 32
TSIP_LOC_HASH_MODE = os.getenv("TSIP_LOC_HASH_MODE", "poseidon2").strip().lower()

# ── Feature flags (read by both client and shuffler) ─────────────────────────
# P4: bind the submitted cell-index payload into the chain commitment.
# When enabled, curr_chain = MiMC(prev_chain, curr_loc, t, w, payload_digest)
# so a valid chain cannot be re-used with a swapped payload.
TSIP_PAYLOAD_BINDING_ENABLE: bool = os.getenv("TSIP_PAYLOAD_BINDING_ENABLE", "0") == "1"

# P5: bind a per-user hidden secret into the chain commitment.
# When enabled, curr_chain = MiMC(..., secret_commitment)
# so an attacker who knows the victim's coordinates but not their secret
# cannot forge a valid chain continuation.
TSIP_SECRET_BINDING_ENABLE: bool = os.getenv("TSIP_SECRET_BINDING_ENABLE", "0") == "1"
TSIP_POSEIDON_SNARKJS = os.getenv("TSIP_POSEIDON_SNARKJS", os.getenv("TSIP_SNARKJS", "snarkjs"))
TSIP_POSEIDON_WASM = os.getenv(
    "TSIP_POSEIDON_WASM",
    next(
        (
            p
            for p in [
                "/app/build/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
                "/app/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
                "/Users/wanghao/Desktop/risefl_mvp/build/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
                "/Users/wanghao/Desktop/risefl_mvp/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
                "build/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
                "zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
            ]
            if os.path.exists(p)
        ),
        "build/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm",
    ),
)
TSIP_POSEIDON_TIMEOUT_SEC = int(os.getenv("TSIP_POSEIDON_TIMEOUT_SEC", "20"))

# ── ADWC (Anchor-Distance Window Continuity) defaults ───────────────────────
ADWC_PROFILE_DEFAULTS: dict[str, dict[str, int]] = {
    "k6": {"k": 6, "policy_cap_m": 3300},
    "k30": {"k": 30, "policy_cap_m": 16500},
}

# ── TSIP v3 mobility-mode defaults ───────────────────────────────────────────
MOBILITY_MODE_ORDER: tuple[str, str, str, str] = ("walk", "bike", "vehicle", "transit")
MOBILITY_MODE_VMAX_MPS: dict[str, int] = {
    "walk": 3,
    "bike": 10,
    "vehicle": 33,
    "transit": 40,
}
MOBILITY_MODE_TO_ID: dict[str, int] = {
    "walk": 0,
    "bike": 1,
    "vehicle": 2,
    "transit": 3,
}
DEFAULT_MODE: str = os.getenv("TSIP_MODE_DEFAULT", "vehicle").strip().lower()
DEFAULT_TIER: str = os.getenv("TSIP_TIER_DEFAULT", "transit").strip().lower()
TSIP_POLICY_CAP_RATIO: float = float(os.getenv("TSIP_POLICY_CAP_RATIO", "0.5"))


def tsip_window_id(timestamp: int, window_sec: int) -> int:
    window = max(1, int(window_sec))
    return int(timestamp) // window


def _field(v: int) -> int:
    return int(v) % SNARK_FIELD


def _value_to_field(v) -> int:
    if isinstance(v, int):
        return int(v) % SNARK_FIELD
    s = str(v or "").strip().lower()
    if not s:
        return 0
    if s.startswith("0x"):
        return int(s, 16) % SNARK_FIELD
    if all(ch in "0123456789abcdef" for ch in s) and any(ch in "abcdef" for ch in s):
        return int(s, 16) % SNARK_FIELD
    return int(s) % SNARK_FIELD


def _mimc7(x: int, key: int = 0, rounds: int = MIMC_ROUNDS) -> int:
    state = _field(x)
    key_f = _field(key)
    for i in range(rounds):
        c = i + 1
        t = _field(state + key_f + c)
        t2 = _field(t * t)
        t4 = _field(t2 * t2)
        t6 = _field(t4 * t2)
        state = _field(t6 * t)
    return _field(state + key_f)


def _mimc_hash_inputs(inputs: list[int]) -> int:
    state = 0
    for v in inputs:
        state = _mimc7(_field(state + int(v)))
    return _field(state)


def _run_poseidon_cmd(cmd: list[str], timeout_sec: int):
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(msg or f"command failed: {' '.join(cmd)}")


@lru_cache(maxsize=200000)
def _poseidon2_hash(x: int, y: int) -> int:
    if not os.path.exists(TSIP_POSEIDON_WASM):
        raise RuntimeError(f"missing TSIP_POSEIDON_WASM: {TSIP_POSEIDON_WASM}")
    with tempfile.TemporaryDirectory(prefix="tsip_poseidon2_") as td:
        input_path = os.path.join(td, "input.json")
        witness_path = os.path.join(td, "witness.wtns")
        witness_json_path = os.path.join(td, "witness.json")
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump({"a": str(int(x)), "b": str(int(y))}, f, ensure_ascii=True)
        _run_poseidon_cmd(
            [
                TSIP_POSEIDON_SNARKJS,
                "wtns",
                "calculate",
                TSIP_POSEIDON_WASM,
                input_path,
                witness_path,
            ],
            timeout_sec=TSIP_POSEIDON_TIMEOUT_SEC,
        )
        _run_poseidon_cmd(
            [
                TSIP_POSEIDON_SNARKJS,
                "wtns",
                "export",
                "json",
                witness_path,
                witness_json_path,
            ],
            timeout_sec=TSIP_POSEIDON_TIMEOUT_SEC,
        )
        with open(witness_json_path, "r", encoding="utf-8") as f:
            witness = json.load(f)
        if not isinstance(witness, list) or len(witness) < 2:
            raise RuntimeError("invalid poseidon witness output")
        return int(witness[1])


def compute_location_commitment(user_id: str, x: int, y: int, timestamp: int, window_id: int, prev_commitment: str = "") -> str:
    del user_id, timestamp, window_id, prev_commitment
    if TSIP_LOC_HASH_MODE == "mimc":
        value = _mimc_hash_inputs([int(x), int(y)])
    elif TSIP_LOC_HASH_MODE == "poseidon2":
        value = _poseidon2_hash(int(x), int(y))
    else:
        raise RuntimeError(f"invalid TSIP_LOC_HASH_MODE: {TSIP_LOC_HASH_MODE}")
    return f"{value:064x}"


def compute_chain_commitment(
    prev_chain_commitment: str,
    location_commitment: str,
    timestamp: int,
    window_id: int,
    payload_digest: str = "",
    secret_commitment: str = "",
) -> str:
    """Hash the trajectory chain link.

    When *payload_digest* is non-empty (P4 payload binding enabled) its field
    value is appended to the MiMC inputs so the chain is tied to the submitted
    cell-index payload.  When *secret_commitment* is non-empty (P5 secret
    binding enabled) the user's hidden-secret commitment is appended so the
    chain cannot be forged without knowing the user's secret.  Both default to
    empty string for full backward compatibility with the original 4-input hash.
    """
    prev_field = commitment_to_field(prev_chain_commitment)
    loc_field = commitment_to_field(location_commitment)
    inputs = [prev_field, loc_field, int(timestamp), int(window_id)]
    if payload_digest:
        # P4: bind sorted cell-index digest into chain
        inputs.append(commitment_to_field(payload_digest))
    if secret_commitment:
        # P5: bind per-user secret commitment into chain
        inputs.append(commitment_to_field(secret_commitment))
    value = _mimc_hash_inputs(inputs)
    return f"{value:064x}"


def commitment_to_field(commitment_hex: str) -> int:
    if not commitment_hex:
        return 0
    return int(commitment_hex, 16) % SNARK_FIELD


def compute_max_dist_sq(vmax: float, time_diff: int) -> int:
    vmax_i = max(1, int(round(float(vmax))))
    dt_i = max(1, int(time_diff))
    return int(vmax_i * vmax_i * dt_i * dt_i)


def normalize_adwc_profile(profile: str) -> str:
    p = str(profile or "k6").strip().lower()
    if p in ADWC_PROFILE_DEFAULTS:
        return p
    return "k6"


def default_adwc_window_k(profile: str) -> int:
    p = normalize_adwc_profile(profile)
    return int(ADWC_PROFILE_DEFAULTS[p]["k"])


def default_adwc_policy_cap_m(profile: str) -> int:
    p = normalize_adwc_profile(profile)
    return int(ADWC_PROFILE_DEFAULTS[p]["policy_cap_m"])


def normalize_mode(mode: str) -> str:
    m = str(mode or DEFAULT_MODE).strip().lower()
    if m in MOBILITY_MODE_TO_ID:
        return m
    return "vehicle"


def normalize_tier(tier: str) -> str:
    t = str(tier or DEFAULT_TIER).strip().lower()
    if t in MOBILITY_MODE_TO_ID:
        return t
    return "transit"


def mode_id(mode: str) -> int:
    return int(MOBILITY_MODE_TO_ID[normalize_mode(mode)])


def mode_vmax_mps(mode: str) -> int:
    return int(MOBILITY_MODE_VMAX_MPS[normalize_mode(mode)])


def mode_vmax_sq(mode: str) -> int:
    v = mode_vmax_mps(mode)
    return int(v * v)


def mode_vmax_sq_by_id(mode_idx: int) -> int:
    idx = int(mode_idx)
    if idx < 0 or idx >= len(MOBILITY_MODE_ORDER):
        raise ValueError(f"invalid mode id: {mode_idx}")
    return mode_vmax_sq(MOBILITY_MODE_ORDER[idx])


def tier_vmax_sq(tier: str) -> int:
    t = normalize_tier(tier)
    v = int(MOBILITY_MODE_VMAX_MPS[t])
    return int(v * v)


def build_modeset_bitmap(modes: list[str]) -> int:
    bm = 0
    for m in modes:
        bm |= (1 << mode_id(m))
    return int(bm & 0xF)


def modeset_bitmap_all() -> int:
    return build_modeset_bitmap(list(MOBILITY_MODE_ORDER))


def modeset_contains_mode(bitmap: int, mode: str) -> bool:
    idx = mode_id(mode)
    bm = int(bitmap) & 0xF
    return bool((bm >> idx) & 1)


def compute_modeset_commitment_field(bitmap: int, modeset_salt) -> int:
    bm = int(bitmap) & 0xF
    salt_f = _value_to_field(modeset_salt)
    return int(_poseidon2_hash(bm, salt_f))


def compute_mode_tag_field(mode: str, secret_hex: str) -> int:
    mid = mode_id(mode)
    sec = secret_hex_to_field(secret_hex)
    return int(_poseidon2_hash(mid, sec))


def compute_tier_anchor_cap_sq(tier_vmax_sq_value: int, window_k: int, step_dt_sq: int) -> int:
    k = max(1, int(window_k))
    tier_sq = max(1, int(tier_vmax_sq_value))
    dt_sq = max(1, int(step_dt_sq))
    return int(k * k * tier_sq * dt_sq)


def compute_policy_cap_sq(tier_anchor_cap_sq: int, ratio: float | None = None) -> int:
    r = TSIP_POLICY_CAP_RATIO if ratio is None else float(ratio)
    if r <= 0:
        raise ValueError("policy cap ratio must be > 0")
    cap = int(float(tier_anchor_cap_sq) * r)
    if cap <= 0:
        cap = 1
    if cap > int(tier_anchor_cap_sq):
        cap = int(tier_anchor_cap_sq)
    return int(cap)


def mode_anchor_cap_sq(mode: str, window_k: int, step_dt_sq: int) -> int:
    return compute_tier_anchor_cap_sq(mode_vmax_sq(mode), window_k, step_dt_sq)


def compute_adwc_physics_cap_sq(vmax: float, window_k: int, window_sec: int) -> int:
    k = max(1, int(window_k))
    vmax_i = max(1, int(round(float(vmax))))
    dt_i = max(1, int(round(float(window_sec))))
    cap_m = k * vmax_i * dt_i
    return int(cap_m * cap_m)


def compute_adwc_policy_cap_sq(policy_cap_m: float) -> int:
    cap_i = max(1, int(round(float(policy_cap_m))))
    return int(cap_i * cap_i)


# ── P4: Proof-Payload Binding ──────────────────────────────────────────────
def compute_payload_digest(idx: list) -> str:
    """SHA-256 of the sorted cell indices.

    Binding this digest into the chain commitment (P4) ensures an attacker
    cannot generate a valid ZK proof for location L then swap the submitted
    cell indices for a different set without breaking the chain verification.

    Only the *indices* (not values) are bound: the secret shares are random-
    looking and cannot be manipulated independently of the indices anyway.
    """
    canonical = json.dumps(sorted(int(x) for x in idx), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def split_payload_digest_fields(payload_digest_hex: str) -> tuple[int, int]:
    s = str(payload_digest_hex or "").strip().lower()
    if len(s) != 64:
        raise ValueError("payload_digest must be 64 hex chars")
    lo = int(s[:32], 16) % SNARK_FIELD
    hi = int(s[32:], 16) % SNARK_FIELD
    return int(lo), int(hi)


def compute_payload_commitment_field(payload_digest_hex: str) -> int:
    lo, hi = split_payload_digest_fields(payload_digest_hex)
    return int(_poseidon2_hash(lo, hi))


# ── P5: Per-User Hidden Secret Binding ────────────────────────────────────
def compute_secret_commitment(user_id: str, secret: str) -> str:
    """HMAC-SHA256(key=secret, msg=user_id) → 64-hex commitment.

    The secret is generated on the client at first registration and never
    shared with any server.  Binding this commitment into the chain
    (P5) means an attacker who knows the victim's coordinates (for an
    identity-swap attack) still cannot forge a valid chain continuation
    without also knowing the victim's secret.

    For the ZK-circuit-level guarantee (v2), see circuits/tsip_main_v2.circom
    which proves knowledge of *secret* inside the proof instead.
    """
    mac = hmac.new(secret.encode("utf-8"), user_id.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def user_id_to_field(user_id: str) -> int:
    h = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()
    return int(int(h, 16) % SNARK_FIELD)


def secret_hex_to_field(secret_hex: str) -> int:
    s = str(secret_hex or "").strip().lower()
    if not s:
        return 0
    return int(int(s, 16) % SNARK_FIELD)


def compute_secret_commitment_field(user_id: str, secret_hex: str) -> int:
    secret_f = secret_hex_to_field(secret_hex)
    user_f = user_id_to_field(user_id)
    return int(_poseidon2_hash(secret_f, user_f))


# ── Legacy helper (unused in TSIP v3 ADWC main path) ───────────────────────
def sliding_window_max_dist_sq(vmax: float, window_rounds: int, round_sec: int) -> int:
    """Legacy cumulative-distance bound helper.

    TSIP v3 mainline uses ADWC anchor-distance constraints in-circuit
    (`circuits/tsip_main_v3_{k6,k30}.circom`) instead of cumulative-sum semantics.
    This helper is kept only for backward-compatible tooling.
    """
    k = max(1, int(window_rounds))
    vmax_i = max(1, int(round(float(vmax))))
    dt_i = max(1, int(round_sec))
    max_dist = k * vmax_i * dt_i
    return max_dist * max_dist
