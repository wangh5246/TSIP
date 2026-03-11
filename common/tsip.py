from __future__ import annotations


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
MIMC_ROUNDS = 32


def tsip_window_id(timestamp: int, window_sec: int) -> int:
    window = max(1, int(window_sec))
    return int(timestamp) // window


def _field(v: int) -> int:
    return int(v) % SNARK_FIELD


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


def compute_location_commitment(user_id: str, x: int, y: int, timestamp: int, window_id: int, prev_commitment: str = "") -> str:
    del user_id, timestamp, window_id, prev_commitment
    value = _mimc_hash_inputs([int(x), int(y)])
    return f"{value:064x}"


def compute_chain_commitment(
    prev_chain_commitment: str,
    location_commitment: str,
    timestamp: int,
    window_id: int,
) -> str:
    prev_field = commitment_to_field(prev_chain_commitment)
    loc_field = commitment_to_field(location_commitment)
    value = _mimc_hash_inputs([prev_field, loc_field, int(timestamp), int(window_id)])
    return f"{value:064x}"


def commitment_to_field(commitment_hex: str) -> int:
    if not commitment_hex:
        return 0
    return int(commitment_hex, 16) % SNARK_FIELD


def compute_max_dist_sq(vmax: float, time_diff: int) -> int:
    vmax_i = max(1, int(round(float(vmax))))
    dt_i = max(1, int(time_diff))
    return int(vmax_i * vmax_i * dt_i * dt_i)
