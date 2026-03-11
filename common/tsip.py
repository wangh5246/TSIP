from __future__ import annotations


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
COMMIT_X_COEFF = 1315423911
COMMIT_Y_COEFF = 2654435761
COMMIT_CONST = 97531
CHAIN_PREV_COEFF = 65537
CHAIN_LOC_COEFF = 11400714819323198485
CHAIN_TIME_COEFF = 8191
CHAIN_WINDOW_COEFF = 131071
CHAIN_CONST = 424242


def tsip_window_id(timestamp: int, window_sec: int) -> int:
    window = max(1, int(window_sec))
    return int(timestamp) // window


def compute_location_commitment(user_id: str, x: int, y: int, timestamp: int, window_id: int, prev_commitment: str = "") -> str:
    del user_id, timestamp, window_id, prev_commitment
    value = (int(x) * COMMIT_X_COEFF + int(y) * COMMIT_Y_COEFF + COMMIT_CONST) % SNARK_FIELD
    return f"{value:064x}"


def compute_chain_commitment(
    prev_chain_commitment: str,
    location_commitment: str,
    timestamp: int,
    window_id: int,
) -> str:
    prev_field = commitment_to_field(prev_chain_commitment)
    loc_field = commitment_to_field(location_commitment)
    value = (
        prev_field * CHAIN_PREV_COEFF
        + loc_field * CHAIN_LOC_COEFF
        + int(timestamp) * CHAIN_TIME_COEFF
        + int(window_id) * CHAIN_WINDOW_COEFF
        + CHAIN_CONST
    ) % SNARK_FIELD
    return f"{value:064x}"


def commitment_to_field(commitment_hex: str) -> int:
    if not commitment_hex:
        return 0
    return int(commitment_hex, 16) % SNARK_FIELD


def compute_max_dist_sq(vmax: float, time_diff: int) -> int:
    vmax_i = max(1, int(round(float(vmax))))
    dt_i = max(1, int(time_diff))
    return int(vmax_i * vmax_i * dt_i * dt_i)
