"""
RiseFL-style baseline (single-round norm check, no temporal linkage).

This baseline approximates the core idea of RiseFL-like validation:
verify each submitted update independently via an L2/projection bound.
It intentionally does NOT keep cross-round state, so teleport/replay/
identity-swap style trajectory attacks remain undetected.
"""

import random
from typing import Dict, List, Tuple

import numpy as np

from common.utils import chi2_ppf
from .utils import (
    DOMAIN_SIZE,
    GRID_W,
    compute_metrics,
    inject_attack,
    is_malicious_stable,
)


# Approximate communication overhead (proof/stat payload) for a lightweight
# single-round norm-check baseline.
RISEFL_COMM_BYTES_PER_CLIENT = 2_000  # ~= 2 KB


class RiseFLVerifier:
    """
    Simplified RiseFL-style verifier.

    Check rule:
      s = Σ_j <u, a_j>^2  <=  B^2 * chi2_ppf(1-alpha, m)

    where u is a per-round feature vector derived from the submitted cell.
    No previous-round commitment or temporal consistency is checked.
    """

    def __init__(
        self,
        domain: int = DOMAIN_SIZE,
        grid_w: int = GRID_W,
        m: int = 8,
        alpha: float = 0.05,
        norm_bound: float = 2.5,
        seed: int = 0,
    ):
        self.domain = domain
        self.grid_w = max(2, int(grid_w))
        self.m = max(1, int(m))
        self.alpha = float(alpha)
        self.norm_bound = float(norm_bound)
        self.threshold = (self.norm_bound ** 2) * chi2_ppf(1.0 - self.alpha, self.m)

        rng = random.Random(seed)
        # 2D projection vectors to emulate random-projection norm testing.
        self.proj = np.array(
            [[rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0)] for _ in range(self.m)],
            dtype=float,
        )

    def _cell_to_vec(self, cell_id: int) -> np.ndarray:
        x = int(cell_id) % self.grid_w
        y = int(cell_id) // self.grid_w
        denom = float(self.grid_w - 1)
        # Normalize to [0, 1] so all in-range cells are "physically plausible"
        # under a loose bound.
        return np.array([x / denom, y / denom], dtype=float)

    def verify(self, cell_id: int) -> Tuple[bool, str]:
        if not (0 <= int(cell_id) < self.domain):
            return False, f"cell_id {cell_id} out of range [0, {self.domain})"
        u = self._cell_to_vec(int(cell_id))
        dots = self.proj @ u
        s = float(np.dot(dots, dots))
        if s > self.threshold:
            return False, f"projection norm exceeded: s={s:.3f} > {self.threshold:.3f}"
        return True, ""

    def aggregate_with_verification(
        self, submissions: List[Dict]
    ) -> Tuple[np.ndarray, float, float]:
        histogram = np.zeros(self.domain, dtype=float)
        n_mal = sum(1 for s in submissions if s["is_malicious"])
        n_honest = len(submissions) - n_mal
        mal_rejected = 0
        honest_rejected = 0

        for s in submissions:
            ok, _ = self.verify(int(s["cell_id"]))
            if ok:
                histogram[int(s["cell_id"])] += float(s.get("value", 1.0))
            elif s["is_malicious"]:
                mal_rejected += 1
            else:
                honest_rejected += 1

        mrr = mal_rejected / max(n_mal, 1)
        frr = honest_rejected / max(n_honest, 1)
        return histogram, mrr, frr


def run_risefl_experiment(
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    malicious_rate: float = 0.0,
    attack_type: str = "random",
    teleport_jump_cells: int = 72,
    domain: int = DOMAIN_SIZE,
    top_k: int = 100,
    seed: int = 0,
    m: int = 8,
    alpha: float = 0.05,
    norm_bound: float = 2.5,
) -> List[Dict]:
    """
    Simulate RiseFL-style single-round verification for each round.
    """
    n_users = len(user_sequences)
    rng = random.Random(seed)
    mal_flags = [is_malicious_stable(i, malicious_rate) for i in range(n_users)]
    n_mal = sum(mal_flags)

    verifier = RiseFLVerifier(
        domain=domain,
        grid_w=GRID_W,
        m=m,
        alpha=alpha,
        norm_bound=norm_bound,
        seed=seed,
    )
    rows: List[Dict] = []

    for r in range(n_rounds):
        submissions = []
        for i, seq in enumerate(user_sequences):
            true_cell = int(seq[r % len(seq)])
            is_mal = mal_flags[i]
            report_cell = true_cell
            if is_mal:
                report_cell = inject_attack(
                    true_cell=true_cell,
                    attack_type=attack_type,
                    teleport_jump_cells=teleport_jump_cells,
                    domain=domain,
                    rng=rng,
                )
            report_cell = int(report_cell) % domain
            submissions.append(
                {"cell_id": report_cell, "value": 1.0, "is_malicious": is_mal}
            )

        histogram, mrr, frr = verifier.aggregate_with_verification(submissions)
        metrics = compute_metrics(histogram, ground_truth, top_k)
        rows.append(
            {
                "round": r + 1,
                "n_users": n_users,
                "n_malicious": n_mal,
                "malicious_reject_rate": mrr,
                "false_reject_rate": frr,
                "comm_bytes_per_client": RISEFL_COMM_BYTES_PER_CLIENT,
                **metrics,
            }
        )

    return rows

