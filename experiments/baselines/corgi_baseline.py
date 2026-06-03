"""
CORGI / Geo-Indistinguishability baseline for the TSIP paper.

What CORGI provides
-------------------
  - Planar Laplace mechanism (geo-indistinguishability, Andrés et al. 2013):
    each client adds isotropic Laplace noise to their (x, y) coordinates before
    reporting; the server aggregates without any integrity check.
  - No proof system, no commitment chain, no cross-round state.
  - Privacy guarantee: ε-geo-indistinguishability (distinguishing a user's true
    location from any other location within distance d requires exp(ε·d) advantage).

Attack detection model
----------------------
  All attacks: 0 %  – no integrity mechanism whatsoever.
  A malicious client can submit any cell; the server cannot distinguish it from
  a legitimately noisy report.

Utility model
-------------
  Noise is added by the client (LDP-style), not post-hoc by the server.
  We simulate this by adding planar Laplace noise to each reported cell
  coordinate before snapping back to the grid.

Primitive costs
---------------
  No ZK proof system → prover_ms = 0,  verifier_ms = 0,  proof_bytes = 0.
  Client-side noise addition is O(1): negligible (<0.001 ms).
"""

import random
import math
from typing import Dict, List

import numpy as np

from .utils import (
    DOMAIN_SIZE,
    GRID_W,
    CELL_SIZE_M,
    ATTACK_DETECTABILITY,
    compute_metrics,
    inject_attack,
    is_malicious_stable,
)


def _planar_laplace_noise(epsilon: float, sensitivity_m: float = CELL_SIZE_M) -> tuple:
    """
    Sample displacement (Δx, Δy) in grid cells from the planar Laplace distribution
    with privacy budget ε (geo-indistinguishability at cell resolution).

    The planar Laplace distribution has radial density  f(r) = ε²r/(2) · exp(-εr)
    where r is in metres.  We sample in polar coordinates:
      θ  ~ Uniform[0, 2π)
      r  ~ Gamma(2, 1/ε)  (the radial part of the bivariate Laplace)
    then convert to grid-cell displacement.
    """
    if epsilon <= 0:
        return 0.0, 0.0
    scale = sensitivity_m / epsilon          # metres per unit
    r = np.random.gamma(2, scale)             # radial distance in metres
    theta = random.uniform(0, 2 * math.pi)
    dx_m = r * math.cos(theta)
    dy_m = r * math.sin(theta)
    # Convert to grid cells (round to nearest integer cell)
    dx_cells = dx_m / CELL_SIZE_M
    dy_cells = dy_m / CELL_SIZE_M
    return dx_cells, dy_cells


def _apply_noise(cell: int, epsilon: float, domain: int = DOMAIN_SIZE) -> int:
    """Apply planar Laplace noise to *cell* and return the noisy cell index."""
    cx = cell % GRID_W
    cy = cell // GRID_W
    dx, dy = _planar_laplace_noise(epsilon)
    noisy_cx = int(np.clip(round(cx + dx), 0, GRID_W - 1))
    noisy_cy = int(np.clip(round(cy + dy), 0, GRID_W - 1))
    return noisy_cy * GRID_W + noisy_cx


def run_corgi_experiment(
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    malicious_rate: float = 0.0,
    attack_type: str = "A1",
    teleport_jump_cells: int = 72,
    domain: int = DOMAIN_SIZE,
    top_k: int = 100,
    seed: int = 0,
    epsilon: float = 1.0,
) -> List[Dict]:
    """
    Simulate CORGI geo-indistinguishability aggregation for each round.

    Honest clients add planar Laplace noise with budget ε.
    Malicious clients submit injected cells (no noise added on their side —
    they control their own client and bypass the LDP mechanism).
    CORGI has no server-side integrity check, so all submissions are accepted.
    """
    n_users = len(user_sequences)
    rng_attack = random.Random(seed)
    np.random.seed(seed)
    mal_flags = [is_malicious_stable(i, malicious_rate) for i in range(n_users)]
    n_mal = sum(mal_flags)

    all_true_cells: List[int] = [
        int(seq[r % len(seq)])
        for seq in user_sequences
        for r in range(n_rounds)
    ]

    rows: List[Dict] = []

    for r in range(n_rounds):
        histogram = np.zeros(domain, dtype=float)
        # CORGI never rejects anything.
        mal_rejected = 0
        honest_rejected = 0

        for i, seq in enumerate(user_sequences):
            true_cell = int(seq[r % len(seq)])
            is_mal = mal_flags[i]
            prev_cell = int(seq[(r - 1) % len(seq)]) if r > 0 else true_cell

            if is_mal:
                # Malicious client bypasses LDP and submits injected cell.
                report_cell = inject_attack(
                    true_cell=true_cell,
                    attack_type=attack_type,
                    teleport_jump_cells=teleport_jump_cells,
                    domain=domain,
                    rng=rng_attack,
                    prev_cell=prev_cell,
                    all_cells=all_true_cells,
                )
            else:
                # Honest client applies planar Laplace noise.
                report_cell = _apply_noise(true_cell, epsilon, domain)

            # CORGI accepts all reports.
            histogram[int(report_cell) % domain] += 1.0

        mrr = mal_rejected / max(n_mal, 1)
        frr = honest_rejected / max(n_users - n_mal, 1)
        metrics = compute_metrics(histogram, ground_truth, top_k)

        rows.append({
            "round": r + 1,
            "n_users": n_users,
            "n_malicious": n_mal,
            "malicious_reject_rate": mrr,
            "false_reject_rate": frr,
            "prover_ms": 0.0,
            "verifier_ms": 0.0,
            "proof_bytes": 0,
            **metrics,
        })

    return rows
