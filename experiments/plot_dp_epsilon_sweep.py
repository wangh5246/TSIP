#!/usr/bin/env python3
"""
Plot privacy-utility curves from DP epsilon sweep summary CSV.

Input CSV columns (from run_dp_epsilon_sweep.sh):
epsilon,mode,malicious_rate,avg_malicious_reject_rate,avg_false_reject_rate,
avg_jaccard,std_jaccard,avg_rmse,std_rmse,avg_cells_kept_post,source_summary_csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


MODE_ORDER = ["full", "commit_only", "no_integ", "risefl", "nebula", "ldp", "eiffel"]
MODE_LABEL = {
    "full": "TSIP (Full)",
    "commit_only": "Commit-Only",
    "no_integ": "No-Integrity",
    "risefl": "RiseFL",
    "nebula": "Nebula",
    "ldp": "Pure LDP",
    "eiffel": "EIFFeL-style",
}
MODE_STYLE = {
    "full": ("#d62728", "o"),
    "commit_only": ("#1f77b4", "s"),
    "no_integ": ("#2ca02c", "^"),
    "risefl": ("#9467bd", "D"),
    "nebula": ("#ff7f0e", "P"),
    "ldp": ("#8c564b", "X"),
    "eiffel": ("#17becf", "v"),
}


def _f(x: str) -> float:
    return float(str(x).strip())


def load_rows(path: Path, malicious_rate: float) -> List[Dict]:
    out: List[Dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            try:
                mr = _f(row["malicious_rate"])
            except Exception:
                continue
            if abs(mr - malicious_rate) > 1e-9:
                continue
            out.append(
                {
                    "epsilon": _f(row["epsilon"]),
                    "mode": row["mode"].strip(),
                    "mrr": _f(row["avg_malicious_reject_rate"]),
                    "frr": _f(row["avg_false_reject_rate"]),
                    "jaccard": _f(row["avg_jaccard"]),
                    "std_jaccard": _f(row["std_jaccard"]),
                    "rmse": _f(row["avg_rmse"]),
                    "std_rmse": _f(row["std_rmse"]),
                }
            )
    return out


def plot(rows: List[Dict], out_png: Path, out_pdf: Path, title_suffix: str) -> None:
    if not rows:
        raise SystemExit("No rows loaded for plotting.")

    by_mode: Dict[str, List[Dict]] = {m: [] for m in MODE_ORDER}
    for r in rows:
        if r["mode"] in by_mode:
            by_mode[r["mode"]].append(r)
    for m in by_mode:
        by_mode[m].sort(key=lambda x: x["epsilon"])

    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))
    fig.patch.set_facecolor("white")
    for ax in axes:
        ax.set_facecolor("white")

    # Panel 1: Jaccard
    ax = axes[0]
    for m in MODE_ORDER:
        rs = by_mode[m]
        if not rs:
            continue
        x = [r["epsilon"] for r in rs]
        y = [r["jaccard"] for r in rs]
        ye = [r["std_jaccard"] for r in rs]
        c, mk = MODE_STYLE[m]
        ax.plot(x, y, color=c, marker=mk, linewidth=1.9, markersize=5.5, label=MODE_LABEL[m])
        ax.fill_between(x, [a - b for a, b in zip(y, ye)], [a + b for a, b in zip(y, ye)], color=c, alpha=0.08)
    ax.set_title("Privacy-Utility (Jaccard)")
    ax.set_xlabel("DP Epsilon")
    ax.set_ylabel("Jaccard")
    ax.set_xscale("log")
    ax.grid(True, linestyle="--", alpha=0.35)

    # Panel 2: RMSE
    ax = axes[1]
    for m in MODE_ORDER:
        rs = by_mode[m]
        if not rs:
            continue
        x = [r["epsilon"] for r in rs]
        y = [r["rmse"] for r in rs]
        ye = [r["std_rmse"] for r in rs]
        c, mk = MODE_STYLE[m]
        ax.plot(x, y, color=c, marker=mk, linewidth=1.9, markersize=5.5, label=MODE_LABEL[m])
        ax.fill_between(x, [a - b for a, b in zip(y, ye)], [a + b for a, b in zip(y, ye)], color=c, alpha=0.08)
    ax.set_title("Privacy-Utility (RMSE)")
    ax.set_xlabel("DP Epsilon")
    ax.set_ylabel("RMSE")
    ax.set_xscale("log")
    ax.grid(True, linestyle="--", alpha=0.35)

    # Panel 3: FRR / MRR
    ax = axes[2]
    for m in MODE_ORDER:
        rs = by_mode[m]
        if not rs:
            continue
        x = [r["epsilon"] for r in rs]
        y_frr = [r["frr"] for r in rs]
        y_mrr = [r["mrr"] for r in rs]
        c, mk = MODE_STYLE[m]
        ax.plot(x, y_frr, color=c, marker=mk, linewidth=1.8, markersize=5.2, linestyle="-", label=f"{MODE_LABEL[m]} (FRR)")
        ax.plot(x, y_mrr, color=c, marker=mk, linewidth=1.2, markersize=4.5, linestyle="--", alpha=0.65)
    ax.set_title("Integrity Metrics vs Epsilon")
    ax.set_xlabel("DP Epsilon")
    ax.set_ylabel("Rate")
    ax.set_xscale("log")
    ax.set_ylim(-0.03, 1.05)
    ax.grid(True, linestyle="--", alpha=0.35)

    fig.suptitle(f"DP Epsilon Sweep{title_suffix}", y=1.03, fontsize=13)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.05))

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220, facecolor="white", transparent=False, bbox_inches="tight")
    fig.savefig(out_pdf, facecolor="white", transparent=False, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--summary", required=True, help="Combined summary CSV from run_dp_epsilon_sweep.sh")
    p.add_argument("--malicious-rate", type=float, default=0.1, help="Filter malicious rate")
    p.add_argument("--out-prefix", default="experiments/figures/fig_dp_epsilon_sweep", help="Output prefix")
    p.add_argument("--title-suffix", default=" (system-level)", help="Figure title suffix")
    args = p.parse_args()

    summary = Path(args.summary)
    rows = load_rows(summary, args.malicious_rate)

    out_prefix = Path(args.out_prefix)
    out_png = out_prefix.with_suffix(".png")
    out_pdf = out_prefix.with_suffix(".pdf")
    plot(rows, out_png, out_pdf, args.title_suffix)

    print(f"[ok] summary: {summary}")
    print(f"[ok] rows   : {len(rows)} (malicious_rate={args.malicious_rate})")
    print(f"[ok] png    : {out_png}")
    print(f"[ok] pdf    : {out_pdf}")


if __name__ == "__main__":
    main()
