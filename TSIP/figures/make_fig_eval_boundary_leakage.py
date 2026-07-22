#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
import pandas as pd


ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "TSIP").is_dir() and (parent / "TSIP_heatmap_version").is_dir()
)
HEATMAP_ROOT = ROOT / "TSIP_heatmap_version/runtime/experiments-heatmap"
OUT = Path(__file__).resolve().parent


def load_synthetic_metadata() -> pd.DataFrame:
    base = HEATMAP_ROOT / "membership_inference/synth_500u_30r_delay1p5_ablation"
    groups = {
        "Timing": "timing_seed*",
        "Topology": "topology_seed*",
        "Accept/\nreject": "outcomes_seed*",
        "Full\nmetadata": "full_seed*",
    }
    rows = []
    for label, pattern in groups.items():
        aucs = []
        for metrics in sorted(base.glob(f"{pattern}/metrics.json")):
            with metrics.open() as fh:
                aucs.append(json.load(fh)["metrics"]["auc"])
        rows.append(
            {
                "label": label,
                "mean": float(np.mean(aucs)),
                "std": float(np.std(aucs, ddof=1)),
                "family": "Synthetic",
            }
        )
    return pd.DataFrame(rows)


def load_real_metadata() -> pd.DataFrame:
    path = HEATMAP_ROOT / "full_n1000_rq/rq3/real_metadata_four_real/real_metadata_summary.csv"
    df = pd.read_csv(path)
    df = df[df["task"].eq("session linkability")].copy()
    order = ["T-Drive", "GeoLife", "Porto", "Rome"]
    df["dataset"] = pd.Categorical(df["dataset"], categories=order, ordered=True)
    df = df.sort_values("dataset")
    df["label"] = df["dataset"].astype(str) + "\nlink"
    return pd.DataFrame(
        {
            "label": df["label"],
            "mean": df["auc_mean"],
            "std": df["auc_std"],
            "family": "Real session",
        }
    )


def load_adaptive() -> pd.DataFrame:
    path = ROOT / "experiments-heatmap/joint_adaptive_adversary_summary.csv"
    df = pd.read_csv(path)
    order = [
        ("random_payload_swap", "Payload\nswap"),
        ("random_valid_payload", "Valid\npayload"),
        ("joint_adaptive_grid_search", "Grid\nsearch"),
        ("mode_switch_timing_saturation", "Mode/timing\nsaturation"),
        ("above_boundary_probe", "Above\ncap"),
    ]
    rows = []
    for scenario, label in order:
        r = df[df["scenario"].eq(scenario)].iloc[0]
        rows.append(
            {
                "label": label,
                "rejected": float(r["attack_rejection_rate"]),
                "polluted": float(r["pollution_fraction_of_all_malicious"]),
            }
        )
    return pd.DataFrame(rows)


def load_boundary_scurve() -> tuple[pd.DataFrame, pd.DataFrame]:
    per_step = pd.read_csv(ROOT / "experiments-heatmap/figures/per_step_scurve_points.csv")
    adwc = pd.read_csv(ROOT / "experiments-heatmap/figures/fig_boundary_scurve_7pts_points.csv")
    return per_step, adwc


def load_hotspot_pollution() -> pd.DataFrame:
    path = ROOT / "experiments-heatmap/hotspot_pollution/hotspot_pollution_summary.csv"
    df = pd.read_csv(path)
    order = ["no_integrity", "tsip_only", "external_only", "tsip_external"]
    df["mode"] = pd.Categorical(df["mode"], categories=order, ordered=True)
    return df.sort_values(["mode", "rho"]).copy()


def load_verifier_scaling() -> tuple[pd.DataFrame, pd.DataFrame]:
    snarkjs = pd.read_csv(ROOT / "experiments-heatmap/verifier_bench/20260424_snarkjs_cli/verifier_worker_projection.csv")
    ark = pd.read_csv(ROOT / "experiments-heatmap/verifier_bench/ark_parallel_process_scaling_20260504.csv")
    return snarkjs, ark


def style_axes(ax: plt.Axes) -> None:
    ax.grid(True, color="0.9", linewidth=0.45)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def panel_label(ax: plt.Axes, label: str) -> None:
    ax.text(
        -0.055,
        1.035,
        label,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=7.8,
        fontweight="bold",
        clip_on=False,
    )


def load_ablation_matrix() -> pd.DataFrame:
    rows = [
        ("SHTPC-Full", 1.00, 1.00, 1.00, 1.00, 1.00),
        ("No-ADWC", 1.00, 1.00, 0.00, 1.00, 1.00),
        ("No-Payload-Bind", 1.00, 1.00, 1.00, 1.00, 0.00),
        ("Stateful-Context", 1.00, 1.00, 1.00, 1.00, 0.00),
        ("No-Check", 0.00, 0.00, 0.00, 0.00, 0.00),
    ]
    return pd.DataFrame(rows, columns=["scheme", "A1", "A2a", "A3", "A5", "A6"])


def load_utility_distribution() -> pd.DataFrame:
    files = [
        ("SHTPC-Full", ROOT / "experiments-heatmap/utility_sweep_20260505_141027_with_jaccard.csv"),
        ("No-Integrity", ROOT / "experiments-heatmap/utility_sweep_20260505_144807_with_jaccard.csv"),
    ]
    frames = []
    for label, path in files:
        df = pd.read_csv(path)
        df["label"] = label
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def draw_box_with_points(ax: plt.Axes, data: list[np.ndarray], colors: list[str]) -> None:
    positions = np.arange(1, len(data) + 1)
    bp = ax.boxplot(
        data,
        positions=positions,
        widths=0.48,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "black", "linewidth": 1.0},
        whiskerprops={"linewidth": 0.75, "color": "0.25"},
        capprops={"linewidth": 0.75, "color": "0.25"},
    )
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.64)
        patch.set_edgecolor("0.2")
        patch.set_linewidth(0.7)
    for idx, values in enumerate(data, start=1):
        offsets = np.linspace(-0.12, 0.12, len(values))
        ax.scatter(
            np.full(len(values), idx) + offsets,
            values,
            s=9,
            color=colors[idx - 1],
            edgecolor="black",
            linewidth=0.25,
            zorder=3,
        )


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 8,
            "axes.labelsize": 8,
            "legend.fontsize": 7.5,
            "xtick.labelsize": 7.2,
            "ytick.labelsize": 7.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )

    meta = pd.concat([load_synthetic_metadata(), load_real_metadata()], ignore_index=True)
    adaptive = load_adaptive()

    fig, axes = plt.subplots(1, 2, figsize=(7.16, 1.86))

    ax = axes[0]
    x = np.arange(len(meta))
    colors = ["#4C78A8" if fam == "Synthetic" else "#F58518" for fam in meta["family"]]
    ax.bar(x, meta["mean"], yerr=meta["std"], capsize=2.5, color=colors, edgecolor="black", linewidth=0.35)
    ax.axhline(0.5, color="0.35", linestyle="--", linewidth=0.8)
    ax.text(len(meta) - 0.15, 0.515, "random", ha="right", va="bottom", fontsize=7, color="0.35")
    ax.set_ylim(0.45, 1.03)
    ax.set_ylabel("AUC")
    ax.set_xticks(x)
    ax.set_xticklabels(meta["label"], fontsize=6.2)
    panel_label(ax, "(a)")
    ax.grid(axis="y", color="0.9", linewidth=0.5)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax = axes[1]
    x = np.arange(len(adaptive))
    width = 0.36
    ax.bar(
        x - width / 2,
        adaptive["rejected"],
        width,
        label="Rejected",
        color="#54A24B",
        edgecolor="black",
        linewidth=0.35,
    )
    ax.bar(
        x + width / 2,
        adaptive["polluted"],
        width,
        label="Successful pollution",
        color="#E45756",
        edgecolor="black",
        linewidth=0.35,
    )
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("Fraction")
    ax.set_xticks(x)
    ax.set_xticklabels(adaptive["label"])
    panel_label(ax, "(b)")
    ax.legend(
        loc="lower center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.55, 1.05),
        handlelength=1.1,
    )
    ax.grid(axis="y", color="0.9", linewidth=0.5)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.subplots_adjust(left=0.06, right=0.995, top=0.80, bottom=0.24, wspace=0.24)

    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_boundary_leakage.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(3.45, 3.18))

    ax = axes[0]
    x = np.arange(len(meta))
    colors = ["#4C78A8" if fam == "Synthetic" else "#F58518" for fam in meta["family"]]
    ax.bar(x, meta["mean"], yerr=meta["std"], capsize=2.0, color=colors, edgecolor="black", linewidth=0.3)
    ax.axhline(0.5, color="0.35", linestyle="--", linewidth=0.7)
    ax.set_ylim(0.45, 1.03)
    ax.set_ylabel("AUC")
    ax.set_xticks(x)
    ax.set_xticklabels(meta["label"], fontsize=5.6)
    panel_label(ax, "(a)")
    ax.grid(axis="y", color="0.9", linewidth=0.45)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax = axes[1]
    x = np.arange(len(adaptive))
    width = 0.36
    ax.bar(
        x - width / 2,
        adaptive["rejected"],
        width,
        label="Rejected",
        color="#54A24B",
        edgecolor="black",
        linewidth=0.3,
    )
    ax.bar(
        x + width / 2,
        adaptive["polluted"],
        width,
        label="Polluted",
        color="#E45756",
        edgecolor="black",
        linewidth=0.3,
    )
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("Fraction")
    ax.set_xticks(x)
    ax.set_xticklabels(adaptive["label"], fontsize=6.4)
    panel_label(ax, "(b)")
    ax.legend(
        loc="lower center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.55, 1.08),
        fontsize=6.6,
        handlelength=1.0,
    )
    ax.grid(axis="y", color="0.9", linewidth=0.45)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.subplots_adjust(left=0.15, right=0.995, top=0.91, bottom=0.10, hspace=0.80)

    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_boundary_leakage_column.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    per_step, adwc = load_boundary_scurve()
    fig, axes = plt.subplots(2, 1, figsize=(3.45, 2.95))

    ax = axes[0]
    ax.plot(
        per_step["distance_m"],
        per_step["reject_rate"],
        color="#1f77b4",
        marker="o",
        linewidth=1.2,
        markersize=3.2,
    )
    ax.axvline(1980, color="#b22222", linestyle="--", linewidth=0.9)
    ax.set_ylim(-0.05, 1.08)
    ax.set_ylabel("Reject rate")
    ax.set_xticks([1000, 1500, 1980, 2500, 3000])
    ax.set_xticklabels(["1.0", "1.5", "1.98", "2.5", "3.0"])
    ax.set_xlabel("displacement (km)")
    panel_label(ax, "(a)")
    style_axes(ax)

    ax = axes[1]
    ax.plot(
        adwc["jump_m"],
        adwc["avg_malicious_reject_rate"],
        color="#1f77b4",
        marker="o",
        linewidth=1.2,
        markersize=3.2,
        label="attack reject",
    )
    ax.plot(
        adwc["jump_m"],
        adwc["avg_false_reject_rate"],
        color="#d62728",
        marker="s",
        linewidth=1.0,
        markersize=3.0,
        linestyle="--",
        label="benign FRR",
    )
    ax.axvspan(6534, 6666, color="#f2c94c", alpha=0.22)
    ax.set_ylim(-0.05, 1.08)
    ax.set_ylabel("Rate")
    ax.set_xticks([1000, 3300, 6600, 7200])
    ax.set_xticklabels(["1.0", "3.3", "6.6", "7.2"])
    ax.set_xlabel("anchor jump (km)")
    panel_label(ax, "(b)")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.56, 1.06),
        ncol=2,
        frameon=False,
        fontsize=6.4,
        handlelength=1.4,
    )
    style_axes(ax)

    fig.subplots_adjust(left=0.15, right=0.995, top=0.92, bottom=0.11, hspace=0.90)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_boundary_scurve_column.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    hotspot = load_hotspot_pollution()
    snarkjs, ark = load_verifier_scaling()
    fig, axes = plt.subplots(2, 1, figsize=(3.45, 3.45))

    ax = axes[0]
    styles = {
        "no_integrity": ("No integrity", "#b7410e", "o", "-"),
        "tsip_only": ("SHTPC-only", "#2f6fed", "s", "--"),
        "external_only": ("External-only", "#7a3ff2", "D", "-."),
        "tsip_external": ("SHTPC + external", "#16823a", "^", ":"),
    }
    for mode, (label, color, marker, line_style) in styles.items():
        sub = hotspot[hotspot["mode"].astype(str).eq(mode)]
        ax.errorbar(
            sub["rho"] * 100,
            sub["false_hotspot_at20_mean"],
            yerr=sub["false_hotspot_at20_std"],
            label=label,
            color=color,
            marker=marker,
            linestyle=line_style,
            linewidth=1.1,
            markersize=3.0,
            capsize=1.8,
        )
    ax.set_ylim(-0.05, 1.08)
    ax.set_ylabel("False HS@20")
    ax.set_xticks([1, 2, 5, 10, 20, 30])
    ax.set_xlabel("malicious fraction (%)")
    panel_label(ax, "(a)")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.56, 1.08),
        ncol=2,
        frameon=False,
        fontsize=5.9,
        handlelength=1.3,
        columnspacing=0.8,
    )
    style_axes(ax)

    ax = axes[1]
    for clients, color in [(1000, "#4C78A8"), (5000, "#F58518"), (10000, "#54A24B")]:
        sub = snarkjs[snarkjs["clients"].eq(clients)]
        ax.plot(
            sub["workers"],
            sub["round_verify_latency_s"],
            marker="o",
            linewidth=1.0,
            markersize=3.0,
            color=color,
            linestyle="--",
            label=f"snarkjs {clients//1000}K",
        )
    ax.plot(
        ark["workers"],
        ark["wall_s"],
        marker="s",
        linewidth=1.2,
        markersize=3.0,
        color="#111111",
        label="ark 10K",
    )
    ax.axhline(60, color="#b22222", linestyle=":", linewidth=0.9)
    ax.set_yscale("log")
    ax.set_ylabel("Latency (s)")
    ax.set_xlabel("verifier workers")
    ax.set_xticks([1, 2, 4, 8, 16])
    ax.set_xticklabels(["1", "2", "4", "8", "16"])
    panel_label(ax, "(b)")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.56, 1.08),
        ncol=2,
        frameon=False,
        fontsize=5.9,
        handlelength=1.4,
        columnspacing=0.8,
    )
    style_axes(ax)

    fig.subplots_adjust(left=0.16, right=0.995, top=0.86, bottom=0.10, hspace=0.92)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_pollution_cost_column.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(7.16, 1.68))

    ax = axes[0]
    for mode, (label, color, marker, line_style) in styles.items():
        sub = hotspot[hotspot["mode"].astype(str).eq(mode)]
        ax.errorbar(
            sub["rho"] * 100,
            sub["false_hotspot_at20_mean"],
            yerr=sub["false_hotspot_at20_std"],
            label=label,
            color=color,
            marker=marker,
            linestyle=line_style,
            linewidth=1.0,
            markersize=2.8,
            capsize=1.6,
        )
    ax.set_ylim(-0.05, 1.08)
    ax.set_ylabel("False HS@20")
    ax.set_xlabel("malicious fraction (%)")
    ax.set_xticks([1, 2, 5, 10, 20, 30])
    panel_label(ax, "(a)")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.56, 1.07),
        ncol=2,
        frameon=False,
        fontsize=5.6,
        handlelength=1.2,
        columnspacing=0.7,
    )
    style_axes(ax)

    ax = axes[1]
    for clients, color in [(1000, "#4C78A8"), (5000, "#F58518"), (10000, "#54A24B")]:
        sub = snarkjs[snarkjs["clients"].eq(clients)]
        ax.plot(
            sub["workers"],
            sub["round_verify_latency_s"],
            marker="o",
            linewidth=1.0,
            markersize=2.8,
            color=color,
            linestyle="--",
            label=f"snarkjs {clients//1000}K",
        )
    ax.plot(
        ark["workers"],
        ark["wall_s"],
        marker="s",
        linewidth=1.2,
        markersize=2.8,
        color="#111111",
        label="ark 10K",
    )
    ax.axhline(60, color="#b22222", linestyle=":", linewidth=0.9)
    ax.set_yscale("log")
    ax.set_ylabel("Latency (s)")
    ax.set_xlabel("verifier workers")
    ax.set_xticks([1, 2, 4, 8, 16])
    ax.set_xticklabels(["1", "2", "4", "8", "16"])
    panel_label(ax, "(b)")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.56, 1.07),
        ncol=2,
        frameon=False,
        fontsize=5.6,
        handlelength=1.2,
        columnspacing=0.8,
    )
    style_axes(ax)

    fig.subplots_adjust(left=0.06, right=0.995, top=0.88, bottom=0.28, wspace=0.26)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_pollution_cost_wide.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    ablation = load_ablation_matrix()
    attacks = ["A1", "A2a", "A3", "A5", "A6"]
    matrix = ablation[attacks].to_numpy(dtype=float)
    fig, ax = plt.subplots(1, 1, figsize=(3.45, 2.12))
    im = ax.imshow(
        matrix,
        cmap=ListedColormap(["#f1c2bd", "#4C78A8"]),
        vmin=0,
        vmax=1,
        aspect="auto",
    )
    ax.set_xticks(np.arange(len(attacks)))
    ax.set_xticklabels(attacks)
    ax.set_yticks(np.arange(len(ablation)))
    ax.set_yticklabels(ablation["scheme"], fontsize=6.7)
    ax.set_xlabel("Violation family")
    ax.set_ylabel("Scheme")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            val = matrix[i, j]
            ax.text(
                j,
                i,
                f"{val:.0f}",
                ha="center",
                va="center",
                color="white" if val > 0.5 else "black",
                fontsize=7.0,
                fontweight="bold",
            )
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_ticks([0, 1])
    cbar.set_ticklabels(["0", "1"])
    cbar.set_label("reject", rotation=90, labelpad=2, fontsize=6.7)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.subplots_adjust(left=0.32, right=0.92, top=0.98, bottom=0.18)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_ablation_matrix_column.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)

    util = load_utility_distribution()
    order = ["SHTPC-Full", "No-Integrity"]
    short_labels = ["SHTPC", "No-Check"]
    colors = ["#4C78A8", "#F58518"]
    fig, axes = plt.subplots(2, 2, figsize=(3.45, 3.34))

    ax = axes[0, 0]
    means = util.groupby("label")[["malicious_reject_rate", "false_reject_rate"]].mean().loc[order]
    x = np.arange(len(order))
    width = 0.34
    ax.bar(
        x - width / 2,
        means["malicious_reject_rate"],
        width,
        label="TPR",
        color="#4C78A8",
        edgecolor="black",
        linewidth=0.3,
    )
    ax.bar(
        x + width / 2,
        means["false_reject_rate"],
        width,
        label="pipeline FRR",
        color="#E45756",
        edgecolor="black",
        linewidth=0.3,
    )
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Rate")
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.57, 1.07),
        ncol=2,
        frameon=False,
        fontsize=5.9,
        handlelength=1.0,
    )
    panel_label(ax, "(a)")
    style_axes(ax)

    ax = axes[0, 1]
    data = [util.loc[util["label"].eq(label), "jaccard"].to_numpy() for label in order]
    draw_box_with_points(ax, data, colors)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Jaccard")
    ax.set_xticks([1, 2])
    ax.set_xticklabels(short_labels)
    panel_label(ax, "(b)")
    style_axes(ax)

    ax = axes[1, 0]
    data = [util.loc[util["label"].eq(label), "rmse"].to_numpy() for label in order]
    draw_box_with_points(ax, data, colors)
    ax.set_ylabel("RMSE")
    ax.set_xticks([1, 2])
    ax.set_xticklabels(short_labels)
    panel_label(ax, "(c)")
    style_axes(ax)

    ax = axes[1, 1]
    data = [util.loc[util["label"].eq(label), "cells_kept_post"].to_numpy() for label in order]
    draw_box_with_points(ax, data, colors)
    ax.set_ylabel("Cells kept")
    ax.set_xticks([1, 2])
    ax.set_xticklabels(short_labels)
    panel_label(ax, "(d)")
    style_axes(ax)

    fig.subplots_adjust(left=0.14, right=0.995, top=0.93, bottom=0.09, hspace=0.68, wspace=0.45)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"fig_eval_utility_distribution_column.{suffix}", dpi=300, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
