#!/usr/bin/env python3
"""Generate focused evaluation figures from existing experiment receipts."""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import numpy as np
import pandas as pd


ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "TSIP").is_dir() and (parent / "experiments-heatmap").is_dir()
)
OUT = Path(__file__).resolve().parent
ADWC_RECEIPT = (
    ROOT
    / "experiments-heatmap/adwc_sweeps/20260417_225953/drift_k_sweep.csv"
)
HOTSPOT_RECEIPT = (
    ROOT
    / "experiments-heatmap/hotspot_pollution/hotspot_pollution_summary.csv"
)

EXPECTED_BIASES = [0.2, 0.4, 0.6, 0.8, 1.0]
EXPECTED_PROFILES = ["k6", "k30"]
EXPECTED_RHOS = [0.01, 0.02, 0.05, 0.10, 0.20, 0.30]
EXPECTED_MODES = [
    "no_integrity",
    "tsip_only",
    "external_only",
    "tsip_external",
]


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 8,
            "axes.labelsize": 8,
            "legend.fontsize": 6.7,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.2,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def export(fig: plt.Figure, stem: str) -> None:
    for suffix in ("pdf", "png"):
        fig.savefig(
            OUT / f"{stem}.{suffix}",
            dpi=300,
            bbox_inches="tight",
            pad_inches=0.02,
        )
    plt.close(fig)


def load_adwc() -> pd.DataFrame:
    frame = pd.read_csv(ADWC_RECEIPT)
    required = {"profile", "k", "drift_bias_ratio", "malicious_rate", "avg_tpr"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"ADWC receipt is missing columns: {missing}")
    if sorted(frame["profile"].unique().tolist()) != sorted(EXPECTED_PROFILES):
        raise ValueError("ADWC receipt does not contain the expected profiles")
    if sorted(frame["drift_bias_ratio"].unique().tolist()) != EXPECTED_BIASES:
        raise ValueError("ADWC receipt does not contain the expected drift biases")
    if not np.allclose(frame["malicious_rate"], 0.10):
        raise ValueError("ADWC figure requires a fixed 10% malicious rate")
    values = frame["avg_tpr"].to_numpy(dtype=float)
    if not np.isfinite(values).all() or ((values < 0.0) | (values > 1.0)).any():
        raise ValueError("ADWC TPR values must be finite and within [0, 1]")
    return frame


def make_adwc_figure() -> None:
    frame = load_adwc()
    matrix = np.vstack(
        [
            frame[frame["profile"].eq(profile)]
            .sort_values("drift_bias_ratio")["avg_tpr"]
            .to_numpy(dtype=float)
            for profile in EXPECTED_PROFILES
        ]
    )

    fig, ax = plt.subplots(figsize=(3.45, 1.34))
    image = ax.imshow(
        matrix,
        cmap="viridis",
        norm=Normalize(vmin=0.75, vmax=1.0),
        aspect="auto",
    )
    ax.set_xticks(np.arange(len(EXPECTED_BIASES)))
    ax.set_xticklabels([f"{value:.1f}" for value in EXPECTED_BIASES])
    ax.set_yticks([0, 1])
    ax.set_yticklabels([r"$K=6$", r"$K=30$"])
    ax.set_xlabel("drift-bias ratio")
    ax.set_ylabel("ADWC profile")
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            value = matrix[row, col]
            ax.text(
                col,
                row,
                f"{value:.2f}",
                ha="center",
                va="center",
                color="black" if value > 0.92 else "white",
                fontsize=7.0,
            )
    cbar = fig.colorbar(image, ax=ax, fraction=0.047, pad=0.025)
    cbar.set_label("TPR")
    cbar.set_ticks([0.8, 0.9, 1.0])
    for spine in ax.spines.values():
        spine.set_linewidth(0.55)
    fig.subplots_adjust(left=0.18, right=0.93, top=0.98, bottom=0.29)
    export(fig, "fig_eval_adwc_sensitivity_column")


def load_hotspot() -> pd.DataFrame:
    frame = pd.read_csv(HOTSPOT_RECEIPT)
    required = {
        "mode",
        "rho",
        "n_seeds",
        "false_hotspot_at20_mean",
        "false_hotspot_at20_std",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"hotspot receipt is missing columns: {missing}")
    if sorted(frame["mode"].unique().tolist()) != sorted(EXPECTED_MODES):
        raise ValueError("hotspot receipt does not contain the expected modes")
    if sorted(frame["rho"].unique().tolist()) != EXPECTED_RHOS:
        raise ValueError("hotspot receipt does not contain the expected ratios")
    if not frame["n_seeds"].eq(5).all():
        raise ValueError("hotspot figure requires five seeds per point")
    values = frame[["false_hotspot_at20_mean", "false_hotspot_at20_std"]].to_numpy(
        dtype=float
    )
    if not np.isfinite(values).all() or ((values < 0.0) | (values > 1.0)).any():
        raise ValueError("hotspot metrics must be finite and within [0, 1]")
    return frame


def make_hotspot_figure() -> None:
    frame = load_hotspot()
    styles = {
        "no_integrity": ("No integrity", "#b7410e", "o", "-"),
        "tsip_only": ("SHTPC-only", "#2f6fed", "s", "--"),
        "external_only": ("External-only", "#7a3ff2", "D", "-."),
        "tsip_external": ("SHTPC + external", "#16823a", "^", ":"),
    }
    fig, ax = plt.subplots(figsize=(3.45, 1.72))
    for mode in EXPECTED_MODES:
        label, color, marker, line_style = styles[mode]
        subset = frame[frame["mode"].eq(mode)].sort_values("rho")
        ax.errorbar(
            subset["rho"] * 100,
            subset["false_hotspot_at20_mean"],
            yerr=subset["false_hotspot_at20_std"],
            label=label,
            color=color,
            marker=marker,
            linestyle=line_style,
            linewidth=1.05,
            markersize=3.1,
            capsize=1.7,
        )
    ax.set_ylim(-0.05, 1.08)
    ax.set_xticks([1, 2, 5, 10, 20, 30])
    ax.set_xlabel("malicious fraction (%)")
    ax.set_ylabel("False HS@20")
    ax.grid(True, color="0.9", linewidth=0.45)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.53, 1.01),
        ncol=2,
        frameon=False,
        handlelength=1.5,
        columnspacing=0.8,
    )
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.subplots_adjust(left=0.15, right=0.995, top=0.77, bottom=0.24)
    export(fig, "fig_eval_hotspot_pollution_column")


def main() -> None:
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1784764800")
    configure_style()
    make_adwc_figure()
    make_hotspot_figure()


if __name__ == "__main__":
    main()
