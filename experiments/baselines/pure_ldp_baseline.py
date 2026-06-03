"""
Pure LDP baseline – Generalised Randomised Response (GRR)

Protocol summary
----------------
Each client applies ε-LDP locally using Generalised Randomised Response and
sends a single perturbed cell value directly to the server.  There is no
shuffle step, so noise must be added at the local level, resulting in O(d/n)
variance (vs. O(d/n²) for shuffle-based protocols at the same ε).

  Client:
    With probability p = exp(ε) / (exp(ε) + d - 1):  send true cell
    With probability q = 1 / (exp(ε) + d - 1):        send any other cell

  Server:
    Unbiased frequency estimation:
      f̂[c] = (count[c]/n - q) / (p - q)
    Clamp to [0, ∞).

Security model
--------------
  - Privacy: ε-LDP (local, without shuffling).
  - Integrity: NONE.  Malicious clients send arbitrary cell values that are
    indistinguishable (to the server) from legitimate LDP responses.
  - Utility: worst among all baselines; noise variance ∝ 1/(p-q)² ≈ exp(-2ε)·d²/n.

Key differences from TSIP
--------------------------
  | Dimension            | Pure LDP        | TSIP                         |
  |----------------------|-----------------|------------------------------|
  | Integrity check      | ✗               | ZK distance proof + chain    |
  | Shuffle step         | ✗               | ✓ (Shuffler service)         |
  | Privacy guarantee    | ε-LDP local     | ε-CDP (shuffle-amplified)    |
  | Utility at small ε   | Very poor       | Good (amplification helps)   |
  | Attack detection     | 0 %             | 100 % (teleport / replay)    |
  | Comm. per client     | ~0.01 KB        | ~2 KB                        |
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
PURE_LDP_COMM_BYTES_PER_CLIENT = 10  # ~= 0.01 KB


# ── client ────────────────────────────────────────────────────────────────────

class PureLDPClient:
    """Generalised Randomised Response (GRR) encoder."""

    def __init__(self, epsilon: float = 1.0, domain: int = DOMAIN_SIZE, seed: Optional[int] = None):
        self.domain  = domain
        exp_e        = math.exp(epsilon)
        self.p       = exp_e / (exp_e + domain - 1.0)   # prob of true value
        self.q       = 1.0   / (exp_e + domain - 1.0)   # prob of each other value
        self._rng    = random.Random(seed)

    def randomize(self, true_cell: int) -> int:
        """Return the perturbed cell value."""
        r = self._rng.random()
        if r < self.p:
            return true_cell
        # Sample uniformly from all cells *except* true_cell
        # Fast path: reject-sample (expected ~1 iteration since p≈q for large d)
        while True:
            c = self._rng.randint(0, self.domain - 1)
            if c != true_cell:
                return c


# ── server ────────────────────────────────────────────────────────────────────

class PureLDPServer:
    """Unbiased frequency estimator for GRR."""

    def __init__(self, n_clients: int, epsilon: float = 1.0, domain: int = DOMAIN_SIZE):
        self.n      = n_clients
        self.domain = domain
        exp_e       = math.exp(epsilon)
        self.p      = exp_e / (exp_e + domain - 1.0)
        self.q      = 1.0   / (exp_e + domain - 1.0)

    def aggregate(self, responses: List[int]) -> np.ndarray:
        """Count responses, then apply the unbiased GRR estimator."""
        counts = np.zeros(self.domain, dtype=float)
        for r in responses:
            counts[r] += 1.0
        # Unbiased estimate: f̂[c] = (count[c]/n - q) / (p - q)
        denom    = self.p - self.q
        estimated = (counts / self.n - self.q) / denom
        # Scale back to count space and clamp
        return np.maximum(estimated * self.n, 0.0)


# ── experiment runner ─────────────────────────────────────────────────────────

def run_ldp_experiment(
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    epsilon: float = 1.0,
    malicious_rate: float = 0.0,
    attack_type: str = "random",
    teleport_jump_cells: int = 72,
    domain: int = DOMAIN_SIZE,
    top_k: int = 100,
    seed: int = 0,
) -> List[Dict]:
    """
    Simulate Pure-LDP (GRR) over *n_rounds*.

    Parameters mirror run_nebula_experiment; see nebula_baseline.py for details.
    """
    n_users  = len(user_sequences)
    rng      = random.Random(seed)

    mal_flags = [is_malicious_stable(i, malicious_rate) for i in range(n_users)]
    n_mal     = sum(mal_flags)

    server = PureLDPServer(n_users, epsilon, domain)
    rows   = []

    for r in range(n_rounds):
        responses = []

        for i, seq in enumerate(user_sequences):
            true_cell = seq[r % len(seq)]
            is_mal    = mal_flags[i]

            if is_mal:
                true_cell = inject_attack(true_cell, attack_type,
                                          teleport_jump_cells, domain, rng)

            client = PureLDPClient(epsilon, domain, seed=rng.randint(0, 2**31))
            responses.append(client.randomize(true_cell))

        pred    = server.aggregate(responses)
        metrics = compute_metrics(pred, ground_truth, top_k)

        rows.append({
            "round":                r + 1,
            "n_users":              n_users,
            "n_malicious":          n_mal,
            "malicious_reject_rate": 0.0,   # LDP server cannot detect attacks
            "false_reject_rate":    0.0,
            "comm_bytes_per_client": PURE_LDP_COMM_BYTES_PER_CLIENT,
            **metrics,
        })

    return rows
