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
) -> int:
    """
    Return the cell that a malicious client submits.

    attack_type:
      "random"     - uniform random cell
      "targeted"   - fixed cell 0 (concentrated injection)
      "boundary"   - teleport_jump_cells away from true cell (boundary scan)
    """
    if attack_type == "targeted":
        return 0
    if attack_type == "boundary":
        return (true_cell + teleport_jump_cells) % domain
    # default: "random"
    return rng.randint(0, domain - 1)


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
