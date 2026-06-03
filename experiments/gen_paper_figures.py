#!/usr/bin/env python3
"""
Generate publication-quality figures for the TSIP paper.

Produces:
  figures/fig_ratio.{pdf,png}   — fig:ratio  (MRR + Jaccard vs adversarial ratio)
  figures/fig_utility.{pdf,png} — fig:utility (Jaccard + RMSE comparison, all modes)

Run from repo root:
  python experiments/gen_paper_figures.py
"""

from __future__ import annotations
import csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── Data source ────────────────────────────────────────────────────────────────
SUMMARY_CSV = Path("server_file/utility_sweep/utility_sweep_20260412_151427_with_jaccard_summary.csv")
OUT_DIR = Path("figures")

# ── Styling ────────────────────────────────────────────────────────────────────
MODE_ORDER   = ["full", "commit_only", "no_integ", "risefl", "nebula", "ldp", "eiffel"]
MODE_LABEL   = {
    "full":        "TSIP (Full)",
    "commit_only": "Commit-Only",
    "no_integ":    "No-Integrity",
    "risefl":      "RiseFL",
    "nebula":      "Nebula",
    "ldp":         "Pure LDP",
    "eiffel":      "EIFFeL-style",
}
# colour-blind–friendly palette (Okabe–Ito + IBM)
MODE_STYLE = {
    "full":        ("#E63946", "o",  2.2,  True),   # red, filled circle
    "commit_only": ("#457B9D", "s",  1.8,  False),  # steel blue, square
    "no_integ":    ("#2DC653", "^",  1.8,  False),  # green, triangle
    "risefl":      ("#9B5DE5", "D",  1.6,  False),  # purple, diamond
    "nebula":      ("#F4A261", "P",  1.8,  False),  # orange, plus
    "ldp":         ("#8B4513", "X",  1.8,  False),  # brown, x
    "eiffel":      ("#00B4D8", "v",  1.8,  False),  # cyan, down-triangle
}

COLUMNS = [
    "mode", "malicious_rate",
    "avg_mrr",  # avg malicious reject rate (TPR for A1 teleport)
    "avg_frr",  # avg false reject rate
    "avg_jaccard", "std_jaccard",
    "avg_rmse",    "std_rmse",
    "avg_cells",
]

plt.rcParams.update({
    "font.family":       "serif",
    "font.size":         9,
    "axes.labelsize":    9,
    "axes.titlesize":    9.5,
    "legend.fontsize":   7.8,
    "xtick.labelsize":   8,
    "ytick.labelsize":   8,
    "axes.linewidth":    0.8,
    "grid.linewidth":    0.5,
    "lines.linewidth":   1.7,
    "lines.markersize":  5,
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
    "savefig.facecolor": "white",
})


# ── Load ───────────────────────────────────────────────────────────────────────
def load(path: Path) -> dict[str, list[dict]]:
    by_mode: dict[str, list[dict]] = {m: [] for m in MODE_ORDER}
    with path.open(newline="") as f:
        for row in csv.reader(f):
            if not row or row[0].strip().lower() == "mode":
                continue
            if len(row) < len(COLUMNS):
                continue
            d = dict(zip(COLUMNS, row))
            m = d["mode"].strip()
            if m not in by_mode:
                continue
            by_mode[m].append({
                "x":   float(d["malicious_rate"]) * 100,
                "mrr": float(d["avg_mrr"]),
                "frr": float(d["avg_frr"]),
                "jac": float(d["avg_jaccard"]),
                "jac_std": float(d["std_jaccard"]),
                "rmse":    float(d["avg_rmse"]),
                "rmse_std":float(d["std_rmse"]),
            })
    for m in by_mode:
        by_mode[m].sort(key=lambda r: r["x"])
    return by_mode


# ── Figure 1: fig:ratio  (MRR vs adversarial ratio) ───────────────────────────
def make_fig_ratio(by_mode: dict, out_prefix: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.55))
    fig.subplots_adjust(wspace=0.38, left=0.09, right=0.98, top=0.88, bottom=0.27)

    titles = ["(a) Attack Detection (TPR)", "(b) Utility (Jaccard)"]
    for i, (ax, title) in enumerate(zip(axes, titles)):
        for m in MODE_ORDER:
            ms = by_mode[m]
            if not ms:
                continue
            x = [r["x"] for r in ms]
            y = [r["mrr"] if i == 0 else r["jac"] for r in ms]
            ye = [0] * len(ms) if i == 0 else [r["jac_std"] for r in ms]
            c, mk, lw, emph = MODE_STYLE[m]
            lw_use = lw if emph else lw * 0.85
            ls = "-" if emph else "--"
            ax.plot(x, y, color=c, marker=mk, linewidth=lw_use,
                    linestyle=ls, label=MODE_LABEL[m], zorder=3 if emph else 2)
            if i == 1 and any(e > 0 for e in ye):
                ax.fill_between(x,
                                [a - b for a, b in zip(y, ye)],
                                [a + b for a, b in zip(y, ye)],
                                color=c, alpha=0.10, zorder=1)
        ax.set_title(title, pad=4)
        ax.set_xlabel("Adversarial Ratio (%)")
        if i == 0:
            ax.set_ylabel("True Positive Rate")
            ax.set_ylim(-0.06, 1.08)
            ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
        else:
            ax.set_ylabel("Jaccard Similarity")
            jvals = [r["jac"] for m in MODE_ORDER for r in by_mode[m]]
            if jvals:
                lo, hi = min(jvals), max(jvals)
                pad = max(0.005, (hi - lo) * 0.5)
                ax.set_ylim(max(0, lo - pad), min(1.0, hi + pad))
        ax.set_xticks([0, 10, 20, 30, 50])
        ax.grid(True, linestyle="--", alpha=0.4, linewidth=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # shared legend below
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4,
               frameon=False, bbox_to_anchor=(0.5, -0.02),
               columnspacing=1.0, handlelength=1.8)

    for sfx in (".pdf", ".png"):
        p = out_prefix.with_suffix(sfx)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[fig:ratio]   → {out_prefix}.pdf / .png")


# ── Figure 2: fig:utility  (3-panel: MRR / Jaccard / RMSE) ───────────────────
def make_fig_utility(by_mode: dict, out_prefix: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(9.4, 2.7))
    fig.subplots_adjust(wspace=0.40, left=0.07, right=0.99, top=0.88, bottom=0.26)

    panel_cfg = [
        ("mrr",  None,      "Attack Detection (TPR)",      "True Positive Rate"),
        ("jac",  "jac_std", "Utility — Jaccard Similarity","Jaccard"),
        ("rmse", "rmse_std","Utility — RMSE",              "RMSE"),
    ]
    for ax, (key, err_key, title, ylabel) in zip(axes, panel_cfg):
        for m in MODE_ORDER:
            ms = by_mode[m]
            if not ms:
                continue
            x  = [r["x"]    for r in ms]
            y  = [r[key]     for r in ms]
            ye = [r[err_key] for r in ms] if err_key else None
            c, mk, lw, emph = MODE_STYLE[m]
            lw_use = lw if emph else lw * 0.85
            ls = "-" if emph else "--"
            ax.plot(x, y, color=c, marker=mk, linewidth=lw_use,
                    linestyle=ls, label=MODE_LABEL[m], zorder=3 if emph else 2)
            if ye and any(e > 0 for e in ye):
                ax.fill_between(x,
                                [a - b for a, b in zip(y, ye)],
                                [a + b for a, b in zip(y, ye)],
                                color=c, alpha=0.10, zorder=1)
        ax.set_title(title, pad=4)
        ax.set_xlabel("Adversarial Ratio (%)")
        ax.set_ylabel(ylabel)
        if key == "mrr":
            ax.set_ylim(-0.06, 1.08)
            ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
        ax.set_xticks([0, 10, 20, 30, 50])
        ax.grid(True, linestyle="--", alpha=0.4, linewidth=0.5)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4,
               frameon=False, bbox_to_anchor=(0.5, -0.02),
               columnspacing=1.0, handlelength=1.8)

    for sfx in (".pdf", ".png"):
        p = out_prefix.with_suffix(sfx)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[fig:utility] → {out_prefix}.pdf / .png")


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    by_mode = load(SUMMARY_CSV)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    make_fig_ratio(by_mode,   OUT_DIR / "fig_ratio")
    make_fig_utility(by_mode, OUT_DIR / "fig_utility")
    print("Done. Figures saved to:", OUT_DIR.resolve())


if __name__ == "__main__":
    main()
