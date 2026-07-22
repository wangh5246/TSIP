"""
EIFFeL-style baseline (CCS 2022 – Chowdhury et al.)

Protocol summary
----------------
EIFFeL (Ensuring Integrity for Federated Learning) provides a general
framework for verifiable aggregation: clients secret-share their updates
across two non-colluding servers; each server evaluates a constraint circuit
over shares and outputs a "valid / invalid" verdict.  Invalid updates are
dropped before reconstruction.

Constraints supported by EIFFeL: any predicate that can be expressed as an
arithmetic circuit, e.g., L2-norm bounds, range checks, etc.

What EIFFeL does NOT do
-----------------------
  - Cross-round consistency: EIFFeL checks each update *independently*.
    It cannot detect whether a user's reported location is consistent with
    their previous reports (no commitment chain, no temporal state).
  - Spatial trajectory continuity: the circuit checks "norm ≤ B" (or
    "cell ∈ valid range"), not "dist(prev_loc, curr_loc) ≤ v_max × Δt".

Simplified simulation
---------------------
Full EIFFeL requires a two-server MPC protocol (GC + secret sharing) with
O(n × d) communication.  Here we simulate the *verification outcome* only:

  - Each submission is accepted if the cell_id is in [0, domain) AND
    the reported value's L2 norm is ≤ norm_bound.
  - In practice, adversarial clients reporting random-but-valid cell_ids
    will always pass this check → malicious_reject_rate ≈ 0 for teleport
    attacks (as long as the fake cell is in range).

Communication model (from paper, §6)
--------------------------------------
  EIFFeL sends O(n × d) shares (two servers), so per-client comm is O(d).
  For d=10000 cells, this is ~40–80 KB per client per round, vs. ~2 KB for TSIP.

Key differences from TSIP
--------------------------
  | Dimension             | EIFFeL-style    | TSIP                         |
  |-----------------------|-----------------|------------------------------|
  | Integrity check type  | Single-round    | Cross-round ZK + chain       |
  | Can detect teleport?  | ✗ (cell in range) | ✓ (distance proof)         |
  | Can detect replay?    | ✗ (no state)    | ✓ (commitment chain)         |
  | MPC overhead          | O(n × d) comm   | O(K + proof_size) ≈ 2 KB    |
  | ZK proofs             | ✗               | ✓ Groth16                    |
  | Attack detection      | ~0 %            | 100 % (teleport / replay)    |
  | Comm. per client      | ~40–80 KB       | ~2 KB                        |
"""

import random
import numpy as np
from typing import List, Optional, Dict, Tuple

from .utils import (
    DOMAIN_SIZE,
    compute_metrics,
    is_malicious_stable,
    inject_attack,
)

# Communication cost constants (from EIFFeL paper §6, for d=10000, 32-bit values)
EIFFEL_COMM_BYTES_PER_CLIENT = 40_000   # ≈ 40 KB per client per round (conservative)


# ── server-side verifier ───────────────────────────────────────────────────────

class EIFFeL:
    """
    Simplified EIFFeL verifier.

    Checks:
      1. cell_id ∈ [0, domain)       (range check)
      2. value ≤ norm_bound          (L2-norm / magnitude bound)

    Does NOT check cross-round continuity (no state stored between rounds).
    """

    def __init__(self, domain: int = DOMAIN_SIZE, norm_bound: float = 1e9):
        self.domain     = domain
        self.norm_bound = norm_bound

    def verify(self, cell_id: int, value: float = 1.0) -> Tuple[bool, str]:
        """Return (accepted, reason_if_rejected)."""
        if not (0 <= cell_id < self.domain):
            return False, f"cell_id {cell_id} out of range [0, {self.domain})"
        if abs(value) > self.norm_bound:
            return False, f"value {value:.2f} exceeds norm bound {self.norm_bound:.2f}"
        # ❌ Cannot check: dist(prev_loc, curr_loc) ≤ v_max * Δt
        # ❌ Cannot check: curr_chain matches prev_chain (no commitment state)
        return True, ""

    def aggregate_with_verification(
        self,
        submissions: List[Dict],   # [{"cell_id": int, "value": float, "is_malicious": bool}]
    ) -> Tuple[np.ndarray, float, float]:
        """
        Verify all submissions; aggregate accepted ones into a histogram.

        Returns
        -------
        (histogram, malicious_reject_rate, false_reject_rate)
        """
        histogram = np.zeros(self.domain, dtype=float)
        n_mal     = sum(s["is_malicious"] for s in submissions)
        n_honest  = len(submissions) - n_mal

        mal_rejected    = 0
        honest_rejected = 0

        for s in submissions:
            ok, _ = self.verify(s["cell_id"], s.get("value", 1.0))
            if ok:
                histogram[s["cell_id"]] += s.get("value", 1.0)
            else:
                if s["is_malicious"]:
                    mal_rejected += 1
                else:
                    honest_rejected += 1

        mrr = mal_rejected    / max(n_mal,    1)
        frr = honest_rejected / max(n_honest, 1)
        return histogram, mrr, frr


# ── experiment runner ─────────────────────────────────────────────────────────

def run_eiffel_experiment(
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    malicious_rate: float = 0.0,
    attack_type: str = "random",
    teleport_jump_cells: int = 72,
    norm_bound: float = 1e9,
    domain: int = DOMAIN_SIZE,
    top_k: int = 100,
    seed: int = 0,
) -> List[Dict]:
    """
    Simulate EIFFeL-style verification over *n_rounds*.

    Note: EIFFeL itself does not add DP noise; in a full system the aggregate
    would be post-processed with DP.  Here we measure *raw* utility to isolate
    the integrity dimension.  For a fair DP comparison, pass the histogram
    through an additional Laplace mechanism (see run_baselines.py).

    Parameters
    ----------
    norm_bound : EIFFeL's L2 norm constraint.  Set to 1e9 to effectively
                 disable (any cell value passes), simulating pure range check.
    """
    n_users   = len(user_sequences)
    rng       = random.Random(seed)

    mal_flags = [is_malicious_stable(i, malicious_rate) for i in range(n_users)]
    n_mal     = sum(mal_flags)

    verifier  = EIFFeL(domain=domain, norm_bound=norm_bound)
    rows      = []

    for r in range(n_rounds):
        submissions = []

        for i, seq in enumerate(user_sequences):
            true_cell = seq[r % len(seq)]
            is_mal    = mal_flags[i]

            if is_mal:
                # Malicious client reports a fake cell (but still within [0, domain))
                # so EIFFeL's range check will pass
                fake_cell = inject_attack(true_cell, attack_type,
                                          teleport_jump_cells, domain, rng)
                # Keep fake_cell in range to simulate adversary that knows the check
                fake_cell = fake_cell % domain
                submissions.append({"cell_id": fake_cell, "value": 1.0, "is_malicious": True})
            else:
                submissions.append({"cell_id": true_cell, "value": 1.0, "is_malicious": False})

        histogram, mrr, frr = verifier.aggregate_with_verification(submissions)
        metrics = compute_metrics(histogram, ground_truth, top_k)

        rows.append({
            "round":                r + 1,
            "n_users":              n_users,
            "n_malicious":          n_mal,
            "malicious_reject_rate": mrr,
            "false_reject_rate":    frr,
            "comm_bytes_per_client": EIFFEL_COMM_BYTES_PER_CLIENT,
            **metrics,
        })

    return rows
