#!/usr/bin/env python3
"""Compute TSIP-harness Jaccard using CORGI's native Octave matrix output."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def load_mapped_sequences(path: Path, n_users: int, rounds: int) -> list[list[int]]:
    seqs: list[list[int]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if len(seqs) >= n_users:
                break
            rec = json.loads(line)
            cells: list[int] = []
            for w in rec.get("windows", []):
                x = float(w.get("x_m", 0.0))
                y = float(w.get("y_m", 0.0))
                bx = min(6, max(0, int(x / 10_000.0 * 7)))
                by = min(6, max(0, int(y / 10_000.0 * 7)))
                cells.append(by * 7 + bx)
            if cells:
                seqs.append([cells[i % len(cells)] for i in range(rounds)])
    return seqs


def top_cells(hist: np.ndarray, k: int) -> set[int]:
    idx = np.argsort(hist)[::-1]
    return {int(i) for i in idx[: min(k, np.count_nonzero(hist))] if hist[i] > 0}


def jaccard(pred: np.ndarray, gt: np.ndarray, top_k: int) -> float:
    k = min(top_k, int(np.count_nonzero(pred)), int(np.count_nonzero(gt)))
    if k == 0:
        return 1.0 if pred.sum() == 0.0 and gt.sum() == 0.0 else 0.0
    a = top_cells(pred, k)
    b = top_cells(gt, k)
    return len(a & b) / len(a | b) if (a | b) else 1.0


def compute(
    z_path: Path,
    traj_path: Path,
    n_users: int,
    rounds: int,
    top_k: int,
    seed: int,
) -> dict[str, float | int]:
    z = np.loadtxt(z_path, delimiter=",")
    if z.shape != (49, 49):
        raise ValueError(f"expected CORGI 49x49 matrix, got {z.shape}")

    seqs = load_mapped_sequences(traj_path, n_users, rounds)
    rng = random.Random(seed)
    gt = np.zeros(49, dtype=float)
    pred = np.zeros(49, dtype=float)
    for seq in seqs:
        for r in range(rounds):
            c = int(seq[r])
            gt[c] += 1.0
            probs = np.maximum(np.asarray(z[c], dtype=float), 0.0)
            probs = probs / probs.sum()
            u = rng.random()
            acc = 0.0
            out = 48
            for idx, p in enumerate(probs):
                acc += float(p)
                if u <= acc:
                    out = idx
                    break
            pred[out] += 1.0

    return {
        "jaccard": jaccard(pred, gt, top_k),
        "gt_hot": int(np.count_nonzero(gt)),
        "pred_hot": int(np.count_nonzero(pred)),
        "n_users": len(seqs),
        "rounds": rounds,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--z", default=str(ROOT / "experiments/external_baselines/corgi_native/z_robust_epsilon1_delta1.csv"))
    p.add_argument("--traj", default=str(ROOT / "experiments/geolife_tsip_ready_50u.jsonl"))
    p.add_argument("--n-users", type=int, default=50)
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("--top-k", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    result = compute(Path(args.z), Path(args.traj), args.n_users, args.rounds, args.top_k, args.seed)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
