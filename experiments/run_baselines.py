#!/usr/bin/env python3
"""
run_baselines.py – Unified baseline runner for TSIP paper experiments.

Usage examples
--------------
# Quick smoke test (synthetic, 10 users, 5 rounds)
python experiments/run_baselines.py --mode quick

# Full experiment on GeoLife data
python experiments/run_baselines.py \
    --traj experiments/geolife_tsip_ready_50u.jsonl \
    --rounds 10 --malicious-rates 0.0 0.1 0.2 0.3 0.5 \
    --epsilons 1.0 --baselines nebula ldp eiffel \
    --out experiments/baseline_results.csv

# ε sweep (fix malicious_rate=0.1, vary ε)
python experiments/run_baselines.py \
    --traj experiments/geolife_tsip_ready_50u.jsonl \
    --rounds 10 --malicious-rates 0.1 \
    --epsilons 0.1 0.5 1.0 2.0 5.0 \
    --baselines nebula ldp \
    --out experiments/epsilon_sweep.csv

Outputs
-------
A CSV with columns:
  baseline, epsilon, malicious_rate, round, n_users, n_malicious,
  malicious_reject_rate, false_reject_rate, jaccard, rmse, relative_error
Plus a summary CSV (*_summary.csv) with per-condition averages.

The CSV can be directly fed into the plotting script (plot_baselines.py).
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np

# Ensure experiments/ is on the path when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.baselines.utils import (
    DOMAIN_SIZE,
    load_trajectory_jsonl,
    extract_cell_sequence,
    pick_cell_for_round,
    make_synthetic_users,
    compute_ground_truth,
    ground_truth_from_records,
    summarize_results,
    print_summary,
)
from experiments.baselines.nebula_baseline   import run_nebula_experiment
from experiments.baselines.pure_ldp_baseline import run_ldp_experiment
from experiments.baselines.eiffel_baseline   import run_eiffel_experiment


# ── helpers ───────────────────────────────────────────────────────────────────

def load_data(traj_path: Optional[str], n_users: int, n_rounds: int, seed: int):
    """
    Load user sequences and compute ground truth.

    If *traj_path* is provided, load from JSONL (real data).
    Otherwise, generate synthetic users.

    Returns
    -------
    (user_sequences, ground_truth)
      user_sequences : List[List[int]]   – [user][round] -> cell_id
      ground_truth   : np.ndarray        – shape [DOMAIN_SIZE]
    """
    if traj_path and os.path.exists(traj_path):
        records = load_trajectory_jsonl(traj_path, max_users=n_users)
        n_users = len(records)
        user_sequences = [extract_cell_sequence(r) for r in records]
        print(f"[data] loaded {n_users} users from {traj_path}")
    else:
        if traj_path:
            print(f"[warn] {traj_path} not found; falling back to synthetic data")
        user_sequences = make_synthetic_users(n_users, n_rounds, seed=seed)
        print(f"[data] generated {n_users} synthetic users × {n_rounds} rounds")

    gt = compute_ground_truth(user_sequences, n_rounds)
    print(f"[data] ground truth: {int((gt > 0).sum())} non-zero cells, "
          f"total={gt.sum():.0f}")
    return user_sequences, gt


BASELINE_MAP = {
    "nebula": run_nebula_experiment,
    "ldp":    run_ldp_experiment,
    "eiffel": run_eiffel_experiment,
}

BASELINE_LABELS = {
    "nebula": "Nebula (ESA)",
    "ldp":    "Pure LDP (GRR)",
    "eiffel": "EIFFeL-style",
}


def run_one_condition(
    baseline: str,
    user_sequences: List[List[int]],
    n_rounds: int,
    ground_truth: np.ndarray,
    epsilon: float,
    malicious_rate: float,
    attack_type: str,
    teleport_jump_cells: int,
    seed: int,
) -> List[Dict]:
    """Run a single (baseline × epsilon × malicious_rate) condition."""
    common_kwargs = dict(
        user_sequences     = user_sequences,
        n_rounds           = n_rounds,
        ground_truth       = ground_truth,
        malicious_rate     = malicious_rate,
        attack_type        = attack_type,
        teleport_jump_cells= teleport_jump_cells,
        domain             = DOMAIN_SIZE,
        top_k              = 100,
        seed               = seed,
    )

    if baseline == "nebula":
        rows = run_nebula_experiment(
            epsilon   = epsilon,
            threshold = 3.0,
            **common_kwargs,
        )
    elif baseline == "ldp":
        rows = run_ldp_experiment(
            epsilon = epsilon,
            **common_kwargs,
        )
    elif baseline == "eiffel":
        # EIFFeL does not have its own DP mechanism; epsilon parameter unused
        rows = run_eiffel_experiment(
            norm_bound = 1e9,   # effectively disable norm check (range-only)
            **{k: v for k, v in common_kwargs.items()
               if k not in ("epsilon",)},
        )
    else:
        raise ValueError(f"unknown baseline: {baseline}")

    # Annotate rows with condition metadata
    for row in rows:
        row["baseline"]       = baseline
        row["epsilon"]        = epsilon
        row["malicious_rate"] = malicious_rate
        row["attack_type"]    = attack_type

    return rows


# ── CSV writer ────────────────────────────────────────────────────────────────

FIELDNAMES = [
    "baseline", "epsilon", "malicious_rate", "attack_type",
    "round", "n_users", "n_malicious",
    "malicious_reject_rate", "false_reject_rate",
    "jaccard", "rmse", "relative_error",
]

SUMMARY_FIELDNAMES = [
    "baseline", "epsilon", "malicious_rate", "attack_type",
    "n_rounds", "n_users",
    "avg_malicious_reject_rate", "avg_false_reject_rate",
    "avg_jaccard", "avg_rmse", "avg_relative_error",
    "std_jaccard", "std_rmse",
]


def write_rows(rows: List[Dict], writer: csv.DictWriter):
    for row in rows:
        writer.writerow({f: row.get(f, "") for f in FIELDNAMES})


def write_summary_row(rows: List[Dict], condition: Dict, writer: csv.DictWriter):
    vals = {k: [r[k] for r in rows if k in r] for k in
            ["malicious_reject_rate", "false_reject_rate", "jaccard", "rmse", "relative_error"]}
    writer.writerow({
        "baseline":                  condition["baseline"],
        "epsilon":                   condition["epsilon"],
        "malicious_rate":            condition["malicious_rate"],
        "attack_type":               condition["attack_type"],
        "n_rounds":                  len(rows),
        "n_users":                   rows[0]["n_users"] if rows else 0,
        "avg_malicious_reject_rate": np.mean(vals["malicious_reject_rate"]),
        "avg_false_reject_rate":     np.mean(vals["false_reject_rate"]),
        "avg_jaccard":               np.mean(vals["jaccard"]),
        "avg_rmse":                  np.mean(vals["rmse"]),
        "avg_relative_error":        np.mean(vals["relative_error"]),
        "std_jaccard":               np.std(vals["jaccard"]),
        "std_rmse":                  np.std(vals["rmse"]),
    })


# ── main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Run standalone baseline experiments for TSIP paper."
    )
    p.add_argument("--traj", default=None,
                   help="Path to TSIP-ready JSONL trajectory file (GeoLife / T-Drive)."
                        " If omitted, synthetic data is generated.")
    p.add_argument("--n-users", type=int, default=50,
                   help="Number of users (used for synthetic generation or capping real data).")
    p.add_argument("--rounds", type=int, default=10,
                   help="Number of rounds per condition.")
    p.add_argument("--baselines", nargs="+",
                   choices=list(BASELINE_MAP.keys()) + ["all"],
                   default=["all"],
                   help="Which baselines to run.")
    p.add_argument("--epsilons", nargs="+", type=float, default=[1.0],
                   help="Privacy budget values to sweep.")
    p.add_argument("--malicious-rates", nargs="+", type=float, default=[0.0, 0.1, 0.3],
                   help="Malicious user fractions to sweep.")
    p.add_argument("--attack-type", default="random",
                   choices=["random", "targeted", "boundary"],
                   help="Attack injection strategy for malicious clients.")
    p.add_argument("--teleport-jump-cells", type=int, default=72,
                   help="For 'boundary' attack: how many cells to jump (default 72 ≈ 7200m / 100m).")
    p.add_argument("--out", default="experiments/baseline_results.csv",
                   help="Output CSV path.")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed.")
    p.add_argument("--mode", choices=["quick", "full"], default="full",
                   help="'quick' overrides settings for a fast smoke test.")
    return p.parse_args()


def main():
    args = parse_args()

    # Quick mode overrides
    if args.mode == "quick":
        args.n_users        = 20
        args.rounds         = 3
        args.epsilons       = [1.0]
        args.malicious_rates = [0.0, 0.1]
        args.baselines      = ["nebula", "ldp", "eiffel"]
        print("[quick mode] n_users=20, rounds=3, epsilons=[1.0], mal_rates=[0.0,0.1]")

    baselines = list(BASELINE_MAP.keys()) if "all" in args.baselines else args.baselines

    # Load / generate data
    user_sequences, ground_truth = load_data(
        args.traj, args.n_users, args.rounds, args.seed
    )

    # Build output paths
    out_path     = Path(args.out)
    summary_path = out_path.with_name(out_path.stem + "_summary" + out_path.suffix)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    with (
        open(out_path,     "w", newline="", encoding="utf-8") as fout,
        open(summary_path, "w", newline="", encoding="utf-8") as fsum,
    ):
        writer  = csv.DictWriter(fout, fieldnames=FIELDNAMES)
        swriter = csv.DictWriter(fsum, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        swriter.writeheader()

        total_conditions = len(baselines) * len(args.epsilons) * len(args.malicious_rates)
        done = 0

        for baseline in baselines:
            for epsilon in args.epsilons:
                for mal_rate in args.malicious_rates:
                    done += 1
                    label = BASELINE_LABELS.get(baseline, baseline)
                    print(f"\n[{done}/{total_conditions}] {label} | "
                          f"ε={epsilon} | mal={mal_rate:.0%} | attack={args.attack_type}")

                    rows = run_one_condition(
                        baseline            = baseline,
                        user_sequences      = user_sequences,
                        n_rounds            = args.rounds,
                        ground_truth        = ground_truth,
                        epsilon             = epsilon,
                        malicious_rate      = mal_rate,
                        attack_type         = args.attack_type,
                        teleport_jump_cells = args.teleport_jump_cells,
                        seed                = args.seed,
                    )

                    write_rows(rows, writer)
                    condition = {
                        "baseline":      baseline,
                        "epsilon":       epsilon,
                        "malicious_rate": mal_rate,
                        "attack_type":   args.attack_type,
                    }
                    write_summary_row(rows, condition, swriter)

                    # Print quick summary to console
                    avg_j   = np.mean([r["jaccard"] for r in rows])
                    avg_mrr = np.mean([r["malicious_reject_rate"] for r in rows])
                    print(f"  → avg_jaccard={avg_j:.4f}  avg_mrr={avg_mrr:.4f}")

    elapsed = time.time() - t0
    print(f"\n[done] {done} conditions in {elapsed:.1f}s")
    print(f"  per-round data : {out_path}")
    print(f"  summary table  : {summary_path}")


if __name__ == "__main__":
    main()
