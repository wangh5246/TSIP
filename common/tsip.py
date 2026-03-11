from __future__ import annotations


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
COMMIT_X_COEFF = 1315423911
COMMIT_Y_COEFF = 2654435761
COMMIT_CONST = 97531


def tsip_window_id(timestamp: int, window_sec: int) -> int:
    window = max(1, int(window_sec))
    return int(timestamp) // window


def compute_location_commitment(
    user_id: str,
    x: int,
    y: int,
    timestamp: int,
    window_id: int,
    prev_commitment: str = "",
) -> str:
    del user_id, timestamp, window_id, prev_commitment
    value = (int(x) * COMMIT_X_COEFF + int(y) * COMMIT_Y_COEFF + COMMIT_CONST) % SNARK_FIELD
    return f"{value:064x}"


def commitment_to_field(commitment_hex: str) -> int:
    if not commitment_hex:
        return 0
    return int(commitment_hex, 16) % SNARK_FIELD


def compute_max_dist_sq(vmax: float, time_diff: int) -> int:
    vmax_i = max(1, int(round(float(vmax))))
    dt_i = max(1, int(time_diff))
    return int(vmax_i * vmax_i * dt_i * dt_i)
