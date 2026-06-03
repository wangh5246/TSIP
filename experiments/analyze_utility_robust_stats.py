#!/usr/bin/env python3
"""Robust utility summaries: median/IQR and user-bootstrap CIs."""

import argparse
import csv
import json
import math
import random
from pathlib import Path

from compute_system_utility import (
    DOMAIN_SIZE,
    _jaccard,
    _rmse,
    _top_k_cells,
    extract_cell_sequence,
    load_dump,
    load_trajectory_jsonl,
)


def percentile(values, q):
    vals = sorted(float(v) for v in values)
    if not vals:
        return 0.0
    pos = (len(vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - pos) + vals[hi] * (pos - lo)


def pearson(pred, gt):
    n = len(pred)
    mp = sum(pred) / n
    mg = sum(gt) / n
    num = sum((p - mp) * (g - mg) for p, g in zip(pred, gt))
    dp = math.sqrt(sum((p - mp) ** 2 for p in pred))
    dg = math.sqrt(sum((g - mg) ** 2 for g in gt))
    return num / (dp * dg) if dp and dg else 0.0


def user_hist(records, sampled_indices, rounds, domain):
    hist = [0.0] * domain
    for idx in sampled_indices:
        seq = extract_cell_sequence(records[idx], domain)
        if not seq:
            continue
        m = len(seq)
        for ridx in range(rounds):
            hist[seq[ridx % m]] += 1.0
    return hist


def bootstrap_ci(records, pred, rounds, domain, reps, seed):
    rng = random.Random(seed)
    n = len(records)
    vals = []
    for _ in range(reps):
        sample = [rng.randrange(n) for _ in range(n)]
        gt = user_hist(records, sample, rounds, domain)
        vals.append(
            {
                "jaccard": _jaccard(pred, gt, top_k=50),
                "rmse": _rmse(pred, gt),
                "pearson": pearson(pred, gt),
            }
        )
    return {
        metric: (percentile([v[metric] for v in vals], 0.025), percentile([v[metric] for v in vals], 0.975))
        for metric in ("jaccard", "rmse", "pearson")
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sweep-csv", required=True)
    p.add_argument("--traj", required=True)
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("--n-users", type=int, default=50)
    p.add_argument("--domain", type=int, default=DOMAIN_SIZE)
    p.add_argument("--bootstrap-reps", type=int, default=1000)
    p.add_argument("--seed", type=int, default=20260504)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    records = load_trajectory_jsonl(args.traj, args.n_users)
    full_gt = user_hist(records, list(range(len(records))), args.rounds, args.domain)

    rows = list(csv.DictReader(open(args.sweep_csv, encoding="utf-8")))
    per_condition = {}
    for row in rows:
        key = (row["mode"], row["malicious_rate"])
        pred = load_dump(row["dump_file"], args.domain)
        per_condition.setdefault(key, []).append(
            {
                "pred": pred,
                "jaccard": _jaccard(pred, full_gt, top_k=50),
                "rmse": _rmse(pred, full_gt),
                "pearson": pearson(pred, full_gt),
                "mrr": float(row.get("malicious_reject_rate") or 0),
                "frr": float(row.get("false_reject_rate") or 0),
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "mode",
        "malicious_rate",
        "n_samples",
        "mrr_median",
        "frr_median",
        "jaccard_median",
        "jaccard_iqr",
        "jaccard_bootstrap_ci",
        "rmse_median",
        "rmse_iqr",
        "rmse_bootstrap_ci",
        "pearson_median",
        "pearson_iqr",
        "pearson_bootstrap_ci",
    ]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for (mode, mal), vals in sorted(per_condition.items()):
            # Bootstrap against the median-RMSE representative prediction.
            rep = sorted(vals, key=lambda v: v["rmse"])[len(vals) // 2]["pred"]
            ci = bootstrap_ci(records, rep, args.rounds, args.domain, args.bootstrap_reps, args.seed)

            def med(metric):
                return percentile([v[metric] for v in vals], 0.5)

            def iqr(metric):
                q1 = percentile([v[metric] for v in vals], 0.25)
                q3 = percentile([v[metric] for v in vals], 0.75)
                return f"{q1:.4f}--{q3:.4f}"

            w.writerow(
                {
                    "mode": mode,
                    "malicious_rate": mal,
                    "n_samples": len(vals),
                    "mrr_median": f"{med('mrr'):.4f}",
                    "frr_median": f"{med('frr'):.4f}",
                    "jaccard_median": f"{med('jaccard'):.4f}",
                    "jaccard_iqr": iqr("jaccard"),
                    "jaccard_bootstrap_ci": f"{ci['jaccard'][0]:.4f}--{ci['jaccard'][1]:.4f}",
                    "rmse_median": f"{med('rmse'):.4f}",
                    "rmse_iqr": iqr("rmse"),
                    "rmse_bootstrap_ci": f"{ci['rmse'][0]:.4f}--{ci['rmse'][1]:.4f}",
                    "pearson_median": f"{med('pearson'):.4f}",
                    "pearson_iqr": iqr("pearson"),
                    "pearson_bootstrap_ci": f"{ci['pearson'][0]:.4f}--{ci['pearson'][1]:.4f}",
                }
            )
    print(f"[out] {out}")


if __name__ == "__main__":
    main()
