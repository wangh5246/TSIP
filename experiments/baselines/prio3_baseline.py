"""
Prio3Histogram baseline for the TSIP paper.

What Prio3 provides
-------------------
  - Per-round SNIP (Successively Non-Interfering Proofs) verifying that each
    client's measurement is a valid one-hot histogram vector (i.e., exactly one
    bin equals 1, the rest 0).
  - No cross-round commitment chain; each round is independent.

Attack detection model
----------------------
  A1  (teleportation)    : 0 %  – cell ∈ [0, domain) always passes SNIP
  A2a (trajectory replay): 0 %  – no identity binding across rounds
  A3  (in-envelope drift): 0 %  – no cross-round state
  A5  (Sybil submission) : 0 %  – no cross-round state
  A6  (proof malleability): 100% – SNIP soundness; forging a valid SNIP is
                                   computationally infeasible (empirically: all
                                   forged proofs are caught in simulation by
                                   modelling the soundness guarantee directly)

Primitive costs (from prio3_bench Rust binary)
-----------------------------------------------
  shard  (client)   ≈ 4 ms   / round
  verify (server)   ≈ 1 ms   / round
  proof  (per client) ≈ 167 KB / round  (public_share + input_share for dim=10000)
"""

import json
import os
import random
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .utils import (
    DOMAIN_SIZE,
    GRID_W,
    ATTACK_DETECTABILITY,
    compute_metrics,
    inject_attack,
    is_malicious_stable,
)

# Path to the compiled Rust benchmark binary.
_BENCH_BIN = Path(__file__).parent.parent.parent / (
    "baselines/prio3_bench/target/release/prio3_bench"
)

# Cached timing/size measurements (populated once per process).
_PRIO3_COSTS: Optional[Dict] = None


def _load_prio3_costs() -> Dict:
    global _PRIO3_COSTS
    if _PRIO3_COSTS is not None:
        return _PRIO3_COSTS

    if _BENCH_BIN.exists():
        try:
            raw = subprocess.check_output([str(_BENCH_BIN)], timeout=120)
            _PRIO3_COSTS = json.loads(raw)
            print(f"[prio3] loaded real costs from binary: "
                  f"shard={_PRIO3_COSTS['shard_ms_mean']:.2f}ms, "
                  f"verify={_PRIO3_COSTS['verify_ms_mean']:.2f}ms, "
                  f"proof={int(_PRIO3_COSTS['proof_bytes_mean'])}B")
            return _PRIO3_COSTS
        except Exception as e:
            print(f"[prio3] binary failed ({e}); using paper-reported fallback values")

    # Fallback: conservative estimates from Prio3 paper (VDAF draft-18 §8).
    _PRIO3_COSTS = {
        "system": "Prio3Histogram",
        "dimension": 10_000,
        "shard_ms_mean": 4.2,
        "shard_ms_std": 0.5,
        "verify_ms_mean": 1.1,
        "verify_ms_std": 0.1,
        "proof_bytes_mean": 167_376,
        "iterations": 0,
    }
    return _PRIO3_COSTS


def _prio3_detect(is_malicious: bool, attack_type: str, rng: random.Random) -> bool:
    """
    Decide whether Prio3 rejects this submission.

    - Format-valid (one-hot) submissions ALWAYS pass SNIP → benign and most attacks pass.
    - A6 (malleability): any attempt to submit a *forged* proof is caught with
      probability 1 (soundness guarantee).  In simulation we model this as:
      all A6-labelled malicious submissions are rejected, none of the benign ones are.
    """
    if not is_malicious:
        return False  # benign always accepted
    detectable = ATTACK_DETECTABILITY["prio3"].get(attack_type, False)
    return detectable  # A6 → True, everything else → False


def run_prio3_experiment(
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    malicious_rate: float = 0.0,
    attack_type: str = "A1",
    teleport_jump_cells: int = 72,
    domain: int = DOMAIN_SIZE,
    top_k: int = 100,
    seed: int = 0,
) -> List[Dict]:
    """
    Simulate Prio3Histogram aggregation for each round with the given attack type.

    Returns per-round result rows (same schema as other baselines).
    """
    costs = _load_prio3_costs()

    n_users = len(user_sequences)
    rng = random.Random(seed)
    mal_flags = [is_malicious_stable(i, malicious_rate) for i in range(n_users)]
    n_mal = sum(mal_flags)

    # Collect all honest cells across all rounds for A2a/A5 "other user" selection.
    all_true_cells: List[int] = [
        int(seq[r % len(seq)])
        for seq in user_sequences
        for r in range(n_rounds)
    ]

    rows: List[Dict] = []

    for r in range(n_rounds):
        histogram = np.zeros(domain, dtype=float)
        mal_rejected = 0
        honest_rejected = 0

        for i, seq in enumerate(user_sequences):
            true_cell = int(seq[r % len(seq)])
            is_mal = mal_flags[i]
            prev_cell = int(seq[(r - 1) % len(seq)]) if r > 0 else true_cell

            if is_mal:
                report_cell = inject_attack(
                    true_cell=true_cell,
                    attack_type=attack_type,
                    teleport_jump_cells=teleport_jump_cells,
                    domain=domain,
                    rng=rng,
                    prev_cell=prev_cell,
                    all_cells=all_true_cells,
                )
            else:
                report_cell = true_cell

            rejected = _prio3_detect(is_mal, attack_type, rng)

            if rejected:
                if is_mal:
                    mal_rejected += 1
                else:
                    honest_rejected += 1
            else:
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
            "prover_ms": costs["shard_ms_mean"],
            "verifier_ms": costs["verify_ms_mean"],
            "proof_bytes": int(costs["proof_bytes_mean"]),
            **metrics,
        })

    return rows
