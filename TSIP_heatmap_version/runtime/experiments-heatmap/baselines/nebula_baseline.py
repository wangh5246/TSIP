"""
Nebula baseline (USENIX Security 2023 – Shamsabadi et al.)

Protocol summary
----------------
Nebula implements an Encode-Shuffle-Analyze (ESA) pipeline for differentially
private histogram estimation.

  Client (Encode):
    With probability p_s = 1 - exp(-ε):  send true cell    (the "real" report)
    With probability 1 - p_s:            send Uniform[0,D) (a "dummy" report)

  Shuffler:
    Randomly permutes all reports (hides which user sent which).

  Server (Analyze):
    1. Count occurrences of each cell.
    2. Apply threshold τ: zero out cells with count < τ  (suppress noise floor).
    3. Debias: estimated_count[c] ≈ (raw[c] - n·q) / (p_s - q)
       where q = (1 - p_s) / D  is the probability of sending any specific
       dummy cell.

Security model
--------------
  - Privacy guarantee: ε-LDP for each user in the local model, amplified to
    ε_central ≈ O(ε/√n) after shuffling (shuffle amplification lemma).
  - Integrity: NONE.  Nebula has no mechanism to detect or reject malicious
    reports; adversarial clients can inject arbitrary cell values and directly
    corrupt the aggregate.

Key differences from TSIP
--------------------------
  | Dimension            | Nebula          | TSIP                         |
  |----------------------|-----------------|------------------------------|
  | Integrity check      | ✗               | ZK distance proof + chain    |
  | Cross-round linkage  | ✗               | Commitment chain             |
  | DP mechanism         | Sampling (ESA)  | SVT + Laplace on secret sums |
  | Attack detection     | 0 %             | 100 % (teleport / replay)    |
  | Comm. per client     | ~2.7 KB         | ~2 KB                        |
"""

import math
import random
import numpy as np
from typing import List, Optional, Dict

from .utils import (
    DOMAIN_SIZE,
    compute_metrics,
    is_malicious_stable,
    inject_attack,
)

# Communication cost used by the simulation baseline (bytes/client/round).
NEBULA_COMM_BYTES_PER_CLIENT = 2_700  # ~= 2.7 KB


# ── client ────────────────────────────────────────────────────────────────────

class NebulaClient:
    """Encode step: each client applies the sampling mechanism locally."""

    def __init__(self, epsilon: float = 1.0, domain: int = DOMAIN_SIZE, seed: Optional[int] = None):
        self.epsilon = epsilon
        self.domain  = domain
        # Sampling probability (report true value)
        self.p_s = 1.0 - math.exp(-epsilon)
        # Probability of sending any specific dummy cell
        self.q   = (1.0 - self.p_s) / domain
        self._rng = random.Random(seed)

    def encode(self, true_cell: int) -> int:
        """Return the encoded (possibly randomised) cell to transmit."""
        if self._rng.random() < self.p_s:
            return true_cell                          # real report
        return self._rng.randint(0, self.domain - 1)  # dummy


# ── server ────────────────────────────────────────────────────────────────────

class NebulaServer:
    """Analyze step: threshold + debias."""

    def __init__(
        self,
        n_clients: int,
        epsilon: float = 1.0,
        domain: int = DOMAIN_SIZE,
        threshold: float = 3.0,
    ):
        self.n       = n_clients
        self.domain  = domain
        self.tau     = threshold
        p_s          = 1.0 - math.exp(-epsilon)
        self.p_s     = p_s
        self.q       = (1.0 - p_s) / domain

    def aggregate(self, reports: List[int]) -> np.ndarray:
        """
        Count → threshold → debias.

        Returns a non-negative frequency estimate for each cell.
        """
        counts = np.zeros(self.domain, dtype=float)
        for r in reports:
            counts[r] += 1.0

        # Threshold: suppress cells with raw count below τ
        counts[counts < self.tau] = 0.0

        # Debias: subtract expected dummy contribution, rescale
        denom = self.p_s - self.q
        if abs(denom) < 1e-12:
            return np.maximum(counts, 0.0)
        debiased = (counts - self.n * self.q) / denom
        return np.maximum(debiased, 0.0)


# ── experiment runner ─────────────────────────────────────────────────────────

def run_nebula_experiment(
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    epsilon: float = 1.0,
    malicious_rate: float = 0.0,
    attack_type: str = "random",
    teleport_jump_cells: int = 72,
    threshold: float = 3.0,
    domain: int = DOMAIN_SIZE,
    top_k: int = 100,
    seed: int = 0,
) -> List[Dict]:
    """
    Simulate Nebula over *n_rounds* with the given user trajectory sequences.

    Parameters
    ----------
    user_sequences   : [user_idx][round_idx] -> true cell_id
    n_rounds         : number of rounds to simulate
    ground_truth     : pre-computed ground-truth frequency array [domain]
    epsilon          : privacy budget per client
    malicious_rate   : fraction of users that are adversarial
    attack_type      : injection strategy ("random", "targeted", "boundary")
    teleport_jump_cells : for "boundary" attack
    threshold        : Nebula's suppression threshold τ
    domain           : grid domain size
    top_k            : Jaccard computed over top-k cells
    seed             : RNG seed

    Returns
    -------
    List of per-round result dicts.
    """
    n_users = len(user_sequences)
    rng     = random.Random(seed)

    # Identify malicious users (stable assignment)
    mal_flags = [is_malicious_stable(i, malicious_rate) for i in range(n_users)]
    n_mal     = sum(mal_flags)

    server = NebulaServer(n_users, epsilon, domain, threshold)
    rows   = []

    for r in range(n_rounds):
        reports           = []
        mal_rejected      = 0   # Nebula never rejects anyone
        honest_rejected   = 0

        for i, seq in enumerate(user_sequences):
            true_cell = seq[r % len(seq)]
            is_mal    = mal_flags[i]

            if is_mal:
                true_cell = inject_attack(true_cell, attack_type,
                                          teleport_jump_cells, domain, rng)

            client = NebulaClient(epsilon, domain, seed=rng.randint(0, 2**31))
            reports.append(client.encode(true_cell))

        # Shuffle (order randomisation – irrelevant for counting but correct)
        rng.shuffle(reports)

        pred = server.aggregate(reports)
        metrics = compute_metrics(pred, ground_truth, top_k)

        rows.append({
            "round":                r + 1,
            "n_users":              n_users,
            "n_malicious":          n_mal,
            "malicious_reject_rate": 0.0,   # Nebula cannot detect attacks
            "false_reject_rate":    0.0,
            "comm_bytes_per_client": NEBULA_COMM_BYTES_PER_CLIENT,
            **metrics,
        })

    return rows
