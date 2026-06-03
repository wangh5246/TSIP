"""
Shared utilities for TSIP baseline experiments.

Provides:
  - Data loading (GeoLife / T-Drive trajectory JSONL)
  - Synthetic trajectory generation
  - Ground-truth heatmap computation
  - Utility metrics: Jaccard, RMSE, Relative-Error
  - Malicious-injection helpers
"""

import json
import math
import random
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Union

# ── defaults ──────────────────────────────────────────────────────────────────
DOMAIN_SIZE = 10_000   # 100 × 100 grid
GRID_W      = 100
CELL_SIZE_M = 100.0
CITY_SIZE_M = 10_000.0


def _normalize_cell_id(cell_id: Union[int, str], domain: int = DOMAIN_SIZE) -> int:
    """
    Convert a cell_id to an integer index in [0, domain).

    GeoLife uses integer cell_ids directly (already in range).
    T-Drive uses "cell_x:cell_y" strings with large coordinates.
    We map strings to integers via a stable hash.
    """
    if isinstance(cell_id, int):
        return cell_id % domain
    # String format (e.g. T-Drive "950:573")
    parts = str(cell_id).split(":")
    if len(parts) == 2:
        try:
            cx, cy = int(parts[0]), int(parts[1])
            # Use a large-prime hash that preserves locality roughly
            return (cx * 9973 + cy) % domain
        except ValueError:
            pass
    # Fallback: md5 hash
    h = int(hashlib.md5(str(cell_id).encode()).hexdigest(), 16)
    return h % domain

# ── data loading ──────────────────────────────────────────────────────────────

def load_trajectory_jsonl(path: str, max_users: int = 50) -> List[Dict]:
    """Load up to *max_users* user records from a TSIP-ready JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if len(records) >= max_users:
                break
    return records


def extract_cell_sequence(record: Dict, domain: int = DOMAIN_SIZE) -> List[int]:
    """Return ordered list of normalised integer cell_ids from a user's record."""
    return [_normalize_cell_id(w["cell_id"], domain)
            for w in record.get("windows", [])]


def pick_cell_for_round(record: Dict, round_idx: int, domain: int = DOMAIN_SIZE) -> Optional[int]:
    """Pick the cell_id for *round_idx*, cycling if fewer windows than rounds."""
    windows = record.get("windows", [])
    if not windows:
        return None
    return _normalize_cell_id(windows[round_idx % len(windows)]["cell_id"], domain)


# ── synthetic data generation ─────────────────────────────────────────────────

def make_synthetic_users(
    n_users: int,
    n_rounds: int,
    seed: int = 42,
    domain: int = DOMAIN_SIZE,
    hotspot_cells: Optional[List[int]] = None,
    hotspot_weight: float = 0.8,
) -> List[List[int]]:
    """
    Generate synthetic trajectory data.

    Each user walks around a handful of "home cells" with probability
    *hotspot_weight*, or visits a random cell otherwise.
    Returns a list of lists: [user_idx][round_idx] -> cell_id.
    """
    rng = random.Random(seed)
    if hotspot_cells is None:
        # Pick ~10% of domain as popular cells
        n_hot = max(1, domain // 10)
        hotspot_cells = rng.sample(range(domain), n_hot)

    users = []
    for u in range(n_users):
        # Each user has 1-3 "home" cells from the hotspot set
        home = rng.sample(hotspot_cells, min(3, len(hotspot_cells)))
        seq = []
        for _ in range(n_rounds):
            if rng.random() < hotspot_weight:
                seq.append(rng.choice(home))
            else:
                seq.append(rng.randint(0, domain - 1))
        users.append(seq)
    return users


# ── ground-truth heatmap ──────────────────────────────────────────────────────

def compute_ground_truth(
    user_sequences: List[List[int]],
    n_rounds: int,
    domain: int = DOMAIN_SIZE,
) -> np.ndarray:
    """
    Aggregate all users' true cell visits over *n_rounds* into a
    frequency histogram (shape: [domain]).
    """
    gt = np.zeros(domain, dtype=float)
    for seq in user_sequences:
        for r in range(n_rounds):
            cell = seq[r % len(seq)]
            gt[cell] += 1.0
    return gt


def ground_truth_from_records(
    records: List[Dict],
    n_rounds: int,
    domain: int = DOMAIN_SIZE,
) -> np.ndarray:
    """Ground truth from JSONL user records (real data)."""
    seqs = [extract_cell_sequence(r) for r in records]
    return compute_ground_truth(seqs, n_rounds, domain)


# ── malicious injection ───────────────────────────────────────────────────────

def is_malicious_stable(user_idx: int, malicious_rate: float) -> bool:
    """Deterministic per-user malicious assignment (sha256-based, matches client.py)."""
    payload = str(user_idx).encode("utf-8")
    raw = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)
    return (raw / float(1 << 64)) < malicious_rate


def inject_attack(
    true_cell: int,
    attack_type: str,
    teleport_jump_cells: int,
    domain: int,
    rng: random.Random,
    prev_cell: Optional[int] = None,
    all_cells: Optional[List[int]] = None,
) -> int:
    """
    Return the cell that a malicious client submits.

    Legacy names (backward-compatible):
      "random"     - A1-style: uniform random cell
      "targeted"   - fixed cell 0 (concentrated injection)
      "boundary"   - A1-style: teleport_jump_cells away from true cell

    TSIP attack taxonomy names (A1–A6):
      "A1"  - Teleportation: jump >> v_max*Δt (same as "boundary")
      "A2a" - Trajectory replay: submit a different user's true cell
      "A3"  - In-envelope drift: stay within per-step distance but bias the direction
              (submit a cell 1 step away from prev, skewed away from true location)
      "A5"  - Sybil submission: same as A2a in cell-level simulation (different identity replay)
      "A6"  - Payload malleability: submit a randomly displaced cell WITH a claimed-valid
              proof (in simulation: the system either always catches this or never does,
              depending on whether it has a sound proof system; the *submitted cell* is
              any random cell, indistinguishable from A1 at cell level)

    Note: A6 detection is protocol-level (soundness), not cell-level.  Baseline
    implementations decide A6 detection independently of which cell is submitted.
    The cell returned here is used for utility impact computation only.
    """
    # ── TSIP taxonomy aliases ─────────────────────────────────────────────────
    if attack_type == "A1":
        # Teleportation: jump teleport_jump_cells away (same mechanism as "boundary")
        return (true_cell + teleport_jump_cells) % domain

    if attack_type == "A2a":
        # Trajectory replay: submit some other user's cell.
        # If a pool of other cells is provided, pick from it; else use a random cell.
        if all_cells and len(all_cells) > 1:
            candidates = [c for c in all_cells if c != true_cell]
            return rng.choice(candidates) if candidates else rng.randint(0, domain - 1)
        return rng.randint(0, domain - 1)

    if attack_type == "A3":
        # In-envelope drift: move one cell-step from prev_cell toward a biased direction.
        # If no prev_cell, fall back to a small random offset.
        base = prev_cell if prev_cell is not None else true_cell
        offset = rng.choice([-GRID_W, -1, 1, GRID_W])  # adjacent cells
        return (base + offset) % domain

    if attack_type == "A5":
        # Sybil: same as A2a in our cell-level simulation (replaying another identity's loc)
        if all_cells and len(all_cells) > 1:
            candidates = [c for c in all_cells if c != true_cell]
            return rng.choice(candidates) if candidates else rng.randint(0, domain - 1)
        return rng.randint(0, domain - 1)

    if attack_type == "A6":
        # Payload malleability: the attacker claims any cell with a forged proof.
        # The *cell* submitted is random (utility impact); detection is protocol-level.
        return rng.randint(0, domain - 1)

    # ── legacy names ──────────────────────────────────────────────────────────
    if attack_type == "targeted":
        return 0
    if attack_type == "boundary":
        return (true_cell + teleport_jump_cells) % domain
    # default: "random"
    return rng.randint(0, domain - 1)


# Attack types and their detectability per baseline system.
# Value = whether the system can *ever* detect this attack (soundness/cross-round).
# Used by baseline adapters to implement detection simulation.
ATTACK_DETECTABILITY = {
    # system → {attack → detectable (bool)}
    "prio3": {
        "A1": False,   # no cross-round state; SNIP only checks format
        "A2a": False,  # no identity binding across rounds
        "A3": False,   # no cross-round state
        "A5": False,   # no cross-round state
        "A6": True,    # SNIP soundness: forging a valid SNIP is infeasible
        "random": False, "targeted": False, "boundary": False,
    },
    "rofl": {
        "A1": True,    # per-step distance proof catches teleportation
        "A2a": False,  # distance proof validates per-step; replay looks valid
        "A3": False,   # in-envelope movement passes distance proof
        "A5": False,   # no cross-round identity check
        "A6": True,    # Bulletproofs soundness: forging a range proof is infeasible
        "random": True, "targeted": True, "boundary": True,
    },
    "corgi": {
        "A1": False,   # no integrity check at all
        "A2a": False,
        "A3": False,
        "A5": False,
        "A6": False,
        "random": False, "targeted": False, "boundary": False,
    },
}


# ── utility metrics ───────────────────────────────────────────────────────────

def top_k_cells(histogram: np.ndarray, k: int) -> set:
    """Return the set of cell indices with the top-k counts."""
    idx = np.argpartition(histogram, -k)[-k:]
    # keep only cells with count > 0
    return set(int(i) for i in idx if histogram[i] > 0)


def jaccard(pred: np.ndarray, gt: np.ndarray, top_k: int = 100) -> float:
    """
    Jaccard similarity between top-k cells of *pred* and *gt*.
    Returns 1.0 if both are empty.
    """
    k = min(top_k, int((gt > 0).sum()), int((pred > 0).sum()))
    if k == 0:
        return 1.0 if (pred.sum() == 0 and gt.sum() == 0) else 0.0
    set_pred = top_k_cells(pred, k)
    set_gt   = top_k_cells(gt,   k)
    union = set_pred | set_gt
    if not union:
        return 1.0
    return len(set_pred & set_gt) / len(union)


def rmse(pred: np.ndarray, gt: np.ndarray) -> float:
    """Root mean-squared error over all cells."""
    return float(np.sqrt(np.mean((pred - gt) ** 2)))


def relative_error(pred: np.ndarray, gt: np.ndarray, eps: float = 1e-9) -> float:
    """Mean relative absolute error over non-zero ground-truth cells."""
    mask = gt > 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs(pred[mask] - gt[mask]) / (gt[mask] + eps)))


def compute_metrics(
    pred: np.ndarray,
    gt: np.ndarray,
    top_k: int = 100,
) -> Dict[str, float]:
    return {
        "jaccard":        jaccard(pred, gt, top_k),
        "rmse":           rmse(pred, gt),
        "relative_error": relative_error(pred, gt),
    }


# ── experiment result helpers ─────────────────────────────────────────────────

def summarize_results(rows: List[Dict]) -> Dict:
    """Average per-round result rows into a summary dict."""
    if not rows:
        return {}
    keys = [k for k in rows[0] if isinstance(rows[0][k], (int, float))]
    return {k: float(np.mean([r[k] for r in rows])) for k in keys}


def print_summary(label: str, rows: List[Dict]):
    s = summarize_results(rows)
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for k, v in sorted(s.items()):
        print(f"  {k:<35s} {v:.4f}")
