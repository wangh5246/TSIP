#!/usr/bin/env python3
"""
Plot utility sweep results for all modes (7 baselines) from summary CSV.

Default input:
  server_file/utility_sweep/utility_sweep_20260412_151427_with_jaccard_summary.csv

Output:
  experiments/figures/fig_utility_allmodes_20260412_151427.{png,pdf}
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


COLUMNS = [
    "mode",
    "malicious_rate",
    "avg_malicious_reject_rate",
    "avg_false_reject_rate",
    "avg_jaccard",
    "std_jaccard",
    "avg_rmse",
    "std_rmse",
    "avg_cells_kept_post",
]

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
    return float(x.strip())


def load_summary(path: Path) -> List[Dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        return []

    has_header = rows[0] and rows[0][0].strip().lower() == "mode"
    data_rows = rows[1:] if has_header else rows

    out = []
    for r in data_rows:
        if len(r) < len(COLUMNS):
            continue
        row = dict(zip(COLUMNS, r[: len(COLUMNS)]))
        out.append(
            {
                "mode": row["mode"].strip(),
                "malicious_rate": _f(row["malicious_rate"]),
                "mrr": _f(row["avg_malicious_reject_rate"]),
                "frr": _f(row["avg_false_reject_rate"]),
                "jaccard": _f(row["avg_jaccard"]),
                "std_jaccard": _f(row["std_jaccard"]),
                "rmse": _f(row["avg_rmse"]),
                "std_rmse": _f(row["std_rmse"]),
            }
        )
    return out


def plot(rows: List[Dict], out_png: Path, out_pdf: Path, title_suffix: str = "") -> None:
    if not rows:
        raise SystemExit("No rows loaded from summary CSV.")

    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["savefig.facecolor"] = "white"
    plt.rcParams["savefig.edgecolor"] = "white"

    by_mode: Dict[str, List[Dict]] = {m: [] for m in MODE_ORDER}
    for r in rows:
        if r["mode"] in by_mode:
            by_mode[r["mode"]].append(r)

    for m in by_mode:
        by_mode[m].sort(key=lambda x: x["malicious_rate"])

    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))

    # Panel 1: MRR
    ax = axes[0]
    for m in MODE_ORDER:
        ms = by_mode[m]
        if not ms:
            continue
        x = [r["malicious_rate"] * 100 for r in ms]
        y = [r["mrr"] for r in ms]
        c, mk = MODE_STYLE[m]
        ax.plot(x, y, color=c, marker=mk, linewidth=1.9, markersize=5.5, label=MODE_LABEL[m])
    ax.set_title("MRR vs Malicious Rate")
    ax.set_xlabel("Malicious Rate (%)")
    ax.set_ylabel("MRR")
    ax.set_ylim(-0.03, 1.05)
    ax.grid(True, linestyle="--", alpha=0.35)

    # Panel 2: Jaccard
    ax = axes[1]
    for m in MODE_ORDER:
        ms = by_mode[m]
        if not ms:
            continue
        x = [r["malicious_rate"] * 100 for r in ms]
        y = [r["jaccard"] for r in ms]
        ye = [r["std_jaccard"] for r in ms]
        c, mk = MODE_STYLE[m]
        ax.plot(x, y, color=c, marker=mk, linewidth=1.9, markersize=5.5, label=MODE_LABEL[m])
        ax.fill_between(x, [a - b for a, b in zip(y, ye)], [a + b for a, b in zip(y, ye)], color=c, alpha=0.08)
    ax.set_title("Jaccard vs Malicious Rate")
    ax.set_xlabel("Malicious Rate (%)")
    ax.set_ylabel("Jaccard")
    jvals = [r["jaccard"] for r in rows]
    jmin, jmax = min(jvals), max(jvals)
    pad = max(0.004, (jmax - jmin) * 0.35)
    ax.set_ylim(max(0.0, jmin - pad), min(1.0, jmax + pad))
    ax.grid(True, linestyle="--", alpha=0.35)

    # Panel 3: RMSE
    ax = axes[2]
    for m in MODE_ORDER:
        ms = by_mode[m]
        if not ms:
            continue
        x = [r["malicious_rate"] * 100 for r in ms]
        y = [r["rmse"] for r in ms]
        ye = [r["std_rmse"] for r in ms]
        c, mk = MODE_STYLE[m]
        ax.plot(x, y, color=c, marker=mk, linewidth=1.9, markersize=5.5, label=MODE_LABEL[m])
        ax.fill_between(x, [a - b for a, b in zip(y, ye)], [a + b for a, b in zip(y, ye)], color=c, alpha=0.08)
    ax.set_title("RMSE vs Malicious Rate")
    ax.set_xlabel("Malicious Rate (%)")
    ax.set_ylabel("RMSE")
    rvals = [r["rmse"] for r in rows]
    rmin, rmax = min(rvals), max(rvals)
    rpad = max(0.08, (rmax - rmin) * 0.15)
    ax.set_ylim(rmin - rpad, rmax + rpad)
    ax.grid(True, linestyle="--", alpha=0.35)

    fig.suptitle(f"Utility Sweep Across 7 Modes{title_suffix}", y=1.03, fontsize=13)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.04))

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220, facecolor="white", transparent=False, bbox_inches="tight")
    fig.savefig(out_pdf, facecolor="white", transparent=False, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        default="server_file/utility_sweep/utility_sweep_20260412_151427_with_jaccard_summary.csv",
        help="summary CSV path (header or headerless)",
    )
    parser.add_argument(
        "--out-prefix",
        default="experiments/figures/fig_utility_allmodes_20260412_151427",
        help="output figure path prefix",
    )
    parser.add_argument(
        "--title-suffix",
        default=" (GeoLife, 10 rounds + 1 warmup)",
        help="title suffix text",
    )
    args = parser.parse_args()

    summary = Path(args.summary)
    out_prefix = Path(args.out_prefix)
    rows = load_summary(summary)

    out_png = out_prefix.with_suffix(".png")
    out_pdf = out_prefix.with_suffix(".pdf")
    plot(rows, out_png, out_pdf, args.title_suffix)

    print(f"[ok] summary: {summary}")
    print(f"[ok] png    : {out_png}")
    print(f"[ok] pdf    : {out_pdf}")


if __name__ == "__main__":
    main()

