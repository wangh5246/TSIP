#!/usr/bin/env python3
"""
Plot boundary attack metrics (MRR/FRR) from boundary scan summary CSV.

Default use case:
  python experiments/plot_boundary_scurve.py \
    --summary experiments/boundary/boundary_scan_20260405_152809.csv \
    --out-prefix experiments/figures/fig_boundary_scurve_30r
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import List


def _parse_jump_list(raw: str) -> List[int]:
    vals = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        vals.append(int(token))
    return vals


def load_rows(summary_csv: Path, target_jumps: List[int], rounds: int) -> List[dict]:
    rows: List[dict] = []
    with summary_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            jump = int(row["jump_m"])
            r = int(float(row["rounds"]))
            if jump not in target_jumps or r != rounds:
                continue
            rows.append(
                {
                    "jump_m": jump,
                    "rounds": r,
                    "mrr": float(row["avg_malicious_reject_rate"]),
                    "frr": float(row["avg_false_reject_rate"]),
                    "valid_clients": float(row["avg_valid_clients"]),
                    "rejected": float(row["avg_rejected"]),
                    "malicious_total": float(row["avg_malicious_total"]),
                }
            )
    rows.sort(key=lambda x: x["jump_m"])
    return rows


def save_points_csv(rows: List[dict], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "jump_m",
                "rounds",
                "avg_malicious_reject_rate",
                "avg_false_reject_rate",
                "avg_valid_clients",
                "avg_rejected",
                "avg_malicious_total",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["jump_m"],
                    row["rounds"],
                    f"{row['mrr']:.4f}",
                    f"{row['frr']:.4f}",
                    f"{row['valid_clients']:.2f}",
                    f"{row['rejected']:.2f}",
                    f"{row['malicious_total']:.2f}",
                ]
            )


def plot(rows: List[dict], out_png: Path, out_pdf: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [r["jump_m"] for r in rows]
    y_mrr = [r["mrr"] for r in rows]
    y_frr = [r["frr"] for r in rows]

    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    ax.plot(x, y_mrr, marker="o", linewidth=2.2, color="#1f77b4", label="MRR (malicious reject rate)")
    ax.plot(x, y_frr, marker="s", linewidth=2.2, linestyle="--", color="#d62728", label="FRR (false reject rate)")

    ax.set_title("Boundary Attack Curves (T-Drive, 30 rounds)")
    ax.set_xlabel("Teleport distance (m)")
    ax.set_ylabel("Rate")
    ax.set_xticks(x)
    ax.set_ylim(bottom=0.0)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(frameon=False, loc="upper left")

    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=220)
    fig.savefig(out_pdf)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot boundary attack S-curve from summary CSV")
    parser.add_argument(
        "--summary",
        default="experiments/boundary/boundary_scan_20260405_152809.csv",
        help="boundary summary CSV path",
    )
    parser.add_argument(
        "--jumps",
        default="1000,3300,5940,6534",
        help="comma-separated jump distances (m)",
    )
    parser.add_argument("--rounds", type=int, default=30, help="only include rows with this rounds value")
    parser.add_argument(
        "--out-prefix",
        default="experiments/figures/fig_boundary_scurve_30r",
        help="output prefix for .png/.pdf/_points.csv",
    )
    args = parser.parse_args()

    summary_csv = Path(args.summary)
    target_jumps = _parse_jump_list(args.jumps)
    out_prefix = Path(args.out_prefix)

    rows = load_rows(summary_csv, target_jumps, args.rounds)
    if not rows:
        raise SystemExit(f"No matching rows found in {summary_csv}")

    points_csv = out_prefix.with_name(out_prefix.name + "_points.csv")
    out_png = out_prefix.with_suffix(".png")
    out_pdf = out_prefix.with_suffix(".pdf")

    save_points_csv(rows, points_csv)
    plot(rows, out_png, out_pdf)

    print(f"[ok] points csv: {points_csv}")
    print(f"[ok] png      : {out_png}")
    print(f"[ok] pdf      : {out_pdf}")


if __name__ == "__main__":
    main()
