#!/usr/bin/env python3
"""
compute_system_utility.py
=========================
Post-processes dump_latest_dp JSON files produced by run_utility_sweep.sh
and computes Jaccard / RMSE / Relative-Error against the ground-truth heatmap.

Inputs
------
  --sweep-csv   : CSV output of run_utility_sweep.sh (one row per round)
  --traj        : TSIP-ready JSONL trajectory file (GeoLife or T-Drive)
  --dump-dir    : Directory containing dump_latest_dp JSON files
  --rounds      : Number of measured rounds per condition
  --n-users     : Number of users

Outputs
-------
  --out  : CSV with columns:
             mode, malicious_rate, round_idx,
             malicious_reject_rate, false_reject_rate,
             jaccard, rmse, relative_error,
             cells_kept_post, dump_file

  Also prints a per-condition summary table to stdout.

Notes
-----
  - dump_latest_dp with PRP_ENABLE=0 returns original (unshuffled) cell_ids
    in the top_tokens field → directly comparable to ground truth.
  - We use top_tokens (not top_cells) because decode may be disabled.
  - Ground truth is computed as the average frequency histogram across
    all users × all rounds (i.e., each user contributes 1 count per round
    to their true cell).
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from experiments.baselines.utils import (
    DOMAIN_SIZE,
    load_trajectory_jsonl,
    extract_cell_sequence,
    compute_ground_truth,
    compute_metrics,
    summarize_results,
)

FIELDNAMES = [
    "mode", "malicious_rate", "round_idx",
    "malicious_reject_rate", "false_reject_rate",
    "jaccard", "rmse", "relative_error",
    "cells_kept_post", "dump_file",
]

SUMMARY_FIELDNAMES = [
    "mode", "malicious_rate",
    "avg_malicious_reject_rate", "avg_false_reject_rate",
    "avg_jaccard", "std_jaccard",
    "avg_rmse",    "std_rmse",
    "avg_cells_kept_post",
]


# ── dump JSON loading ─────────────────────────────────────────────────────────

def load_dump(dump_file: str, domain: int = DOMAIN_SIZE) -> np.ndarray:
    """
    Parse a dump_latest_dp JSON and return a frequency histogram.

    Uses top_tokens (raw PRP-off tokens = original cell_ids when PRP_ENABLE=0).
    Falls back to top_cells if top_tokens is absent.
    """
    hist = np.zeros(domain, dtype=float)
    try:
        with open(dump_file, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  [warn] cannot load {dump_file}: {e}", file=sys.stderr)
        return hist

    # top_tokens = [(token_int, noisy_count), ...]
    # When PRP_ENABLE=0, token_int == original cell_id
    items = data.get("top_tokens") or data.get("top_cells") or []
    for entry in items:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        cell_id, count = entry[0], entry[1]
        try:
            cid = int(cell_id) % domain
            cnt = max(0.0, float(count))
            hist[cid] += cnt
        except (TypeError, ValueError):
            pass

    return hist


# ── ground truth ──────────────────────────────────────────────────────────────

def build_ground_truth(traj_path: str, n_users: int, n_rounds: int,
                       domain: int = DOMAIN_SIZE) -> np.ndarray:
    """
    Load real trajectory data and compute the expected frequency histogram.

    Uses the integer cell_id field from each JSONL window directly, which is
    consistent with what the client sends when PRP_ENABLE=0.
    For GeoLife the field is an integer in [0, 9999].
    For T-Drive the field is a string "x:y" which we hash into [0, domain).
    """
    records = load_trajectory_jsonl(traj_path, max_users=n_users)
    # Use extract_cell_sequence which applies _normalize_cell_id (handles both
    # integer GeoLife cell_ids and string T-Drive cell_ids consistently)
    seqs    = [extract_cell_sequence(r, domain) for r in records]
    gt      = compute_ground_truth(seqs, n_rounds, domain)
    print(f"[gt] {len(records)} users, {int((gt > 0).sum())} hot cells, "
          f"total visits = {gt.sum():.0f}")
    return gt


# ── sweep CSV parsing ─────────────────────────────────────────────────────────

def load_sweep_csv(path: str):
    """Load the raw sweep CSV produced by run_utility_sweep.sh."""
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


# ── main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sweep-csv",  required=True)
    p.add_argument("--traj",       required=True, help="TSIP-ready JSONL file")
    p.add_argument("--dump-dir",   required=True)
    p.add_argument("--rounds",     type=int, default=10)
    p.add_argument("--n-users",    type=int, default=50)
    p.add_argument("--domain",     type=int, default=DOMAIN_SIZE)
    p.add_argument("--top-k",      type=int, default=50,
                   help="Jaccard computed over top-k cells (max 50, limited by dump)")
    p.add_argument("--out",        required=True)
    return p.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("  compute_system_utility.py")
    print("=" * 60)

    # Ground truth
    gt = build_ground_truth(args.traj, args.n_users, args.rounds, args.domain)

    # Load sweep CSV
    sweep_rows = load_sweep_csv(args.sweep_csv)
    print(f"[sweep] {len(sweep_rows)} rows loaded from {args.sweep_csv}")

    out_path     = Path(args.out)
    summary_path = out_path.with_name(out_path.stem + "_summary" + out_path.suffix)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Per-condition accumulator for summary
    per_condition = defaultdict(list)

    with (
        open(out_path,     "w", newline="", encoding="utf-8") as fout,
        open(summary_path, "w", newline="", encoding="utf-8") as fsum,
    ):
        writer  = csv.DictWriter(fout, fieldnames=FIELDNAMES)
        swriter = csv.DictWriter(fsum, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        swriter.writeheader()

        for row in sweep_rows:
            mode        = row.get("mode", "")
            mal_rate    = row.get("malicious_rate", "")
            round_idx   = row.get("round_idx", "")
            dump_file   = row.get("dump_file", "")
            mrr         = float(row.get("malicious_reject_rate", 0) or 0)
            frr         = float(row.get("false_reject_rate",     0) or 0)
            kept_post   = int(row.get("cells_kept_post", 0) or 0)

            # Load predicted histogram from dump
            pred    = load_dump(dump_file, args.domain)
            metrics = compute_metrics(pred, gt, top_k=args.top_k)

            out_row = {
                "mode":                  mode,
                "malicious_rate":        mal_rate,
                "round_idx":             round_idx,
                "malicious_reject_rate": mrr,
                "false_reject_rate":     frr,
                "jaccard":               metrics["jaccard"],
                "rmse":                  metrics["rmse"],
                "relative_error":        metrics["relative_error"],
                "cells_kept_post":       kept_post,
                "dump_file":             Path(dump_file).name,
            }
            writer.writerow(out_row)

            key = (mode, mal_rate)
            per_condition[key].append(out_row)

        # Write summary rows
        print("\n[summary]")
        print(f"  {'Mode':<14} {'MalRate':>8} {'MRR':>6} {'Jaccard':>8} {'±':>6} {'RMSE':>8}")
        print(f"  {'-'*14} {'-'*8} {'-'*6} {'-'*8} {'-'*6} {'-'*8}")

        for (mode, mal_rate), cond_rows in sorted(per_condition.items()):
            vals = {k: [r[k] for r in cond_rows]
                    for k in ["malicious_reject_rate","false_reject_rate",
                               "jaccard","rmse","relative_error","cells_kept_post"]}
            summary_row = {
                "mode":                      mode,
                "malicious_rate":            mal_rate,
                "avg_malicious_reject_rate": np.mean(vals["malicious_reject_rate"]),
                "avg_false_reject_rate":     np.mean(vals["false_reject_rate"]),
                "avg_jaccard":               np.mean(vals["jaccard"]),
                "std_jaccard":               np.std(vals["jaccard"]),
                "avg_rmse":                  np.mean(vals["rmse"]),
                "std_rmse":                  np.std(vals["rmse"]),
                "avg_cells_kept_post":       np.mean(vals["cells_kept_post"]),
            }
            swriter.writerow(summary_row)
            print(f"  {mode:<14} {float(mal_rate):>8.0%}  "
                  f"{summary_row['avg_malicious_reject_rate']:>5.2f}  "
                  f"{summary_row['avg_jaccard']:>8.4f}  "
                  f"±{summary_row['std_jaccard']:.4f}  "
                  f"{summary_row['avg_rmse']:>8.2f}")

    print(f"\n[out] per-round : {out_path}")
    print(f"[out] summary   : {summary_path}")


if __name__ == "__main__":
    main()
