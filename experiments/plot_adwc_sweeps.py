#!/usr/bin/env python3
"""
Plot ADWC A3 sweep outputs:
  - Drift-rate x K heatmap (TPR)
  - Policy-cap sensitivity curves (TPR@drift and FRR@benign)
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _to_float(v: str, default: float = float("nan")) -> float:
    try:
        return float(v)
    except Exception:
        return default


def plot_drift_heatmap(rows: list[dict], out_path: Path) -> None:
    ks = sorted({int(_to_float(r.get("k", ""))) for r in rows})
    drifts = sorted({round(_to_float(r.get("drift_bias_ratio", "")), 6) for r in rows})
    if not ks or not drifts:
        raise RuntimeError("empty drift sweep data")

    mat = np.full((len(ks), len(drifts)), np.nan, dtype=float)
    k_index = {k: i for i, k in enumerate(ks)}
    d_index = {d: i for i, d in enumerate(drifts)}
    for r in rows:
        k = int(_to_float(r.get("k", "")))
        d = round(_to_float(r.get("drift_bias_ratio", "")), 6)
        tpr = _to_float(r.get("avg_tpr", "nan"))
        if k in k_index and d in d_index:
            mat[k_index[k], d_index[d]] = tpr

    fig, ax = plt.subplots(figsize=(8.4, 3.6))
    # Figure (a): raise lower bound to highlight K-level differences.
    im = ax.imshow(mat, aspect="auto", cmap="viridis", vmin=0.6, vmax=1.0)
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("TPR")

    ax.set_title("ADWC A3 Drift-rate x K (TPR)")
    ax.set_xlabel("Drift bias ratio")
    ax.set_ylabel("Window K")
    ax.set_xticks(range(len(drifts)))
    ax.set_xticklabels([f"{d:.2f}" for d in drifts])
    ax.set_yticks(range(len(ks)))
    ax.set_yticklabels([str(k) for k in ks])

    for i in range(len(ks)):
        for j in range(len(drifts)):
            v = mat[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", color="black", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def plot_policy_sensitivity(rows: list[dict], out_path: Path) -> None:
    profiles = sorted({str(r.get("profile", "")).strip() for r in rows if str(r.get("profile", "")).strip()})
    if not profiles:
        raise RuntimeError("empty policy sweep data")

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.8), sharex=False)
    ax_tpr, ax_frr = axes

    color_map = {"k6": "#1f77b4", "k30": "#d62728"}
    for p in profiles:
        sub = [r for r in rows if str(r.get("profile", "")).strip() == p]
        sub.sort(key=lambda x: _to_float(x.get("policy_cap_m", "")))
        xs = [_to_float(r.get("policy_cap_m", "")) / 1000.0 for r in sub]  # km
        ys_tpr = [_to_float(r.get("tpr_at_drift", "")) for r in sub]
        ys_frr = [_to_float(r.get("benign_frr", "")) for r in sub]
        c = color_map.get(p, None)
        ax_tpr.plot(xs, ys_tpr, marker="o", linewidth=2.0, label=p, color=c)
        ax_frr.plot(xs, ys_frr, marker="s", linewidth=2.0, label=p, color=c)

    ax_tpr.set_title("Policy Cap Sensitivity (TPR)")
    ax_tpr.set_xlabel("policy_cap (km)")
    ax_tpr.set_ylabel("TPR@drift")
    ax_tpr.set_ylim(0.0, 1.05)
    ax_tpr.grid(alpha=0.25)

    ax_frr.set_title("Policy Cap Sensitivity (FRR)")
    ax_frr.set_xlabel("policy_cap (km)")
    ax_frr.set_ylabel("FRR@benign")
    ax_frr.set_ylim(bottom=0.0)
    ax_frr.grid(alpha=0.25)

    # Figure (b): A3 circuit contribution reference line (~2%).
    a3_circuit_frr = 0.02
    ax_frr.axhline(
        y=a3_circuit_frr,
        color="#444444",
        linestyle="--",
        linewidth=1.5,
        label="A3 circuit contribution ≈ 2%",
    )
    ax_frr.text(
        0.02,
        0.96,
        "Remaining FRR ≈ session constraint",
        transform=ax_frr.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        color="#444444",
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.7),
    )

    handles, labels = ax_tpr.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=max(1, len(labels)), frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot ADWC sweep outputs")
    parser.add_argument("--drift-csv", required=True, help="drift_k_sweep.csv path")
    parser.add_argument("--policy-csv", required=True, help="policy_sensitivity.csv path")
    parser.add_argument("--out-dir", default="experiments/adwc_sweeps", help="output directory")
    args = parser.parse_args()

    drift_csv = Path(args.drift_csv).resolve()
    policy_csv = Path(args.policy_csv).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    drift_rows = _read_csv(drift_csv)
    policy_rows = _read_csv(policy_csv)

    drift_png = out_dir / "adwc_drift_k_heatmap.png"
    policy_png = out_dir / "adwc_policy_sensitivity.png"

    plot_drift_heatmap(drift_rows, drift_png)
    plot_policy_sensitivity(policy_rows, policy_png)

    print("saved:", drift_png)
    print("saved:", policy_png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
