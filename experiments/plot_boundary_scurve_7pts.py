#!/usr/bin/env python3
"""
Build and plot 7-point boundary curve with mixed-precision sources:

- 1000/3300/5940/6534 from 30-round boundary summary (3 repeats).
- 6600 from available 30-round round_metrics repeats (currently 2 repeats).
- 6666/7200 from 10-round clean logs summary.

Outputs:
  - <out_prefix>_points.csv
  - <out_prefix>.png
  - <out_prefix>.pdf
"""

from __future__ import annotations

import argparse
import csv
import glob
import re
from pathlib import Path
from statistics import mean
from typing import Dict, List


TARGET_JUMPS = [1000, 3300, 5940, 6534, 6600, 6666, 7200]


def _read_summary_csv(path: Path) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            jump = int(row["jump_m"])
            if jump not in TARGET_JUMPS:
                continue
            out[jump] = {
                "jump_m": jump,
                "mrr": float(row["avg_malicious_reject_rate"]),
                "frr": float(row["avg_false_reject_rate"]),
                "rounds": int(float(row["rounds"])),
                "repeats": int(float(row["repeats"])),
                "tier": "30r-summary",
                "source": str(path),
            }
    return out


def _read_round_metrics_for_jump(jump: int) -> dict | None:
    pattern = (
        "experiments/boundary/"
        f"boundary_scan_20260405_152809_jump_{jump}_rep_*_round_metrics_*.csv"
    )
    files = sorted(glob.glob(pattern))
    if not files:
        return None

    rep_mrr: List[float] = []
    rep_frr: List[float] = []
    rep_rounds: List[int] = []
    for fp in files:
        with open(fp, "r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        rep_mrr.append(mean(float(r["malicious_reject_rate"]) for r in rows))
        rep_frr.append(mean(float(r["false_reject_rate"]) for r in rows))
        rep_rounds.append(len(rows))

    if not rep_mrr:
        return None

    rounds = int(round(mean(rep_rounds)))
    return {
        "jump_m": jump,
        "mrr": mean(rep_mrr),
        "frr": mean(rep_frr),
        "rounds": rounds,
        "repeats": len(rep_mrr),
        "tier": "30r-metrics",
        "source": ";".join(files),
    }


def _read_from_clean_log(log_path: Path, jump: int) -> dict:
    txt = log_path.read_text(encoding="utf-8", errors="ignore")
    rounds_match = re.search(r"(?m)^rounds=(\d+)", txt)
    mrr_match = re.search(r"(?m)^avg_malicious_reject_rate=([0-9.]+)", txt)
    frr_match = re.search(r"(?m)^avg_false_reject_rate=([0-9.]+)", txt)
    if not (rounds_match and mrr_match and frr_match):
        raise ValueError(f"Cannot parse summary metrics from {log_path}")
    return {
        "jump_m": jump,
        "mrr": float(mrr_match.group(1)),
        "frr": float(frr_match.group(1)),
        "rounds": int(rounds_match.group(1)),
        "repeats": 1,
        "tier": "10r-log",
        "source": str(log_path),
    }


def _collect_rows(summary_csv: Path) -> List[dict]:
    rows_map: Dict[int, dict] = _read_summary_csv(summary_csv)

    # Fill 6600 by 30-round metrics if missing in summary.
    if 6600 not in rows_map:
        row_6600 = _read_round_metrics_for_jump(6600)
        if row_6600:
            rows_map[6600] = row_6600

    # Fill missing higher points from clean logs.
    fallback_logs = {
        6666: Path("experiments/tdrive_boundary_clean_6666m.log"),
        7200: Path("experiments/tdrive_boundary_clean_7200m.log"),
    }
    # Optional 6600 fallback from clean log if metrics are unavailable.
    if 6600 not in rows_map:
        fallback_logs[6600] = Path("experiments/tdrive_boundary_clean_6600m.log")

    for jump, logp in fallback_logs.items():
        if jump in rows_map:
            continue
        if logp.exists():
            rows_map[jump] = _read_from_clean_log(logp, jump)

    rows: List[dict] = []
    for jump in TARGET_JUMPS:
        if jump in rows_map:
            rows.append(rows_map[jump])
    return rows


def _save_points_csv(rows: List[dict], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "jump_m",
                "avg_malicious_reject_rate",
                "avg_false_reject_rate",
                "rounds",
                "repeats",
                "data_tier",
                "source",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["jump_m"],
                    f"{r['mrr']:.4f}",
                    f"{r['frr']:.4f}",
                    r["rounds"],
                    r["repeats"],
                    r["tier"],
                    r["source"],
                ]
            )


def _plot(rows: List[dict], out_png: Path, out_pdf: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mtick

    # Enforce pure white canvas regardless of external matplotlib style config.
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.facecolor"] = "white"
    plt.rcParams["savefig.facecolor"] = "white"
    plt.rcParams["savefig.edgecolor"] = "white"

    x = [r["jump_m"] for r in rows]
    y_mrr = [r["mrr"] for r in rows]
    y_frr = [r["frr"] for r in rows]

    fig, ax = plt.subplots(figsize=(7.9, 5.1))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Left axis: MRR
    line_mrr, = ax.plot(
        x, y_mrr,
        marker="s",
        markersize=7,
        linewidth=2.0,
        color="#e25521",
        label="T-Drive — malicious reject rate",
        zorder=4,
    )

    # Right axis: FRR
    ax2 = ax.twinx()
    line_frr, = ax2.plot(
        x, y_frr,
        marker="^",
        markersize=6,
        linewidth=1.8,
        linestyle=":",
        color="#e57a4b",
        label="T-Drive — false reject rate (right axis)",
        zorder=4,
    )

    # Transition zone + threshold line (keep compatible with old figure style)
    trans = ax.axvspan(6500, 6665, color="#d9c437", alpha=0.20, label="Detection transition zone", zorder=1)
    ax.axvline(6600, color="#b38d00", linestyle="--", linewidth=1.4, zorder=2)

    # Keep 6534 tick hidden (use arrow label). Show 6600 on axis and hide 6666 label.
    tick_labels = []
    for v in x:
        if v in (6534, 6666):
            tick_labels.append("")
        else:
            tick_labels.append(str(v))
    ax.set_xticks(x)
    ax.set_xticklabels(tick_labels, rotation=30, ha="right")

    # Arrow labels to avoid overlap near threshold points.
    y6534 = y_mrr[x.index(6534)]
    ax.annotate(
        "6534 m",
        xy=(6534, y6534),
        xytext=(6260, 0.18),
        textcoords="data",
        fontsize=9,
        color="#2f2f2f",
        bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="none", alpha=0.95),
        arrowprops=dict(
            arrowstyle="->",
            color="#2f2f2f",
            lw=1.0,
            connectionstyle="arc3,rad=-0.18",
        ),
    )
    ax.set_title("TSIP Boundary Detection: S-Curve\n(T-Drive)")
    ax.set_xlabel("Teleport distance (m)")
    ax.set_ylabel("Malicious Reject Rate")
    ax2.set_ylabel("False Reject Rate (right axis)", color="#e25521")

    ax.set_ylim(-0.04, 1.08)
    ax2.set_ylim(-0.01, max(0.12, max(y_frr) + 0.01))

    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0, decimals=0))
    ax.grid(alpha=0.35, linestyle="--")

    # Combined legend order to match old-style explanation.
    handles = [line_mrr, line_frr, trans]
    labels = [h.get_label() for h in handles]
    ax.legend(handles, labels, frameon=True, framealpha=0.9, loc="upper left", bbox_to_anchor=(0.01, 0.72))
    fig.tight_layout()

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220, facecolor="white", transparent=False)
    fig.savefig(out_pdf, facecolor="white", transparent=False)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        default="experiments/boundary/boundary_scan_20260405_152809.csv",
        help="30-round boundary summary CSV",
    )
    parser.add_argument(
        "--out-prefix",
        default="experiments/figures/fig_boundary_scurve_7pts",
        help="output file prefix",
    )
    args = parser.parse_args()

    summary_csv = Path(args.summary)
    out_prefix = Path(args.out_prefix)

    rows = _collect_rows(summary_csv)
    missing = [j for j in TARGET_JUMPS if j not in {r["jump_m"] for r in rows}]
    if missing:
        raise SystemExit(f"Missing jumps in assembled data: {missing}")

    out_csv = out_prefix.with_name(out_prefix.name + "_points.csv")
    out_png = out_prefix.with_suffix(".png")
    out_pdf = out_prefix.with_suffix(".pdf")

    _save_points_csv(rows, out_csv)
    _plot(rows, out_png, out_pdf)

    print(f"[ok] points csv: {out_csv}")
    print(f"[ok] png      : {out_png}")
    print(f"[ok] pdf      : {out_pdf}")


if __name__ == "__main__":
    main()
