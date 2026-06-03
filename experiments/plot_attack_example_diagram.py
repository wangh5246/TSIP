#!/usr/bin/env python3
"""
Draw an attack-example diagram showing attack flow and TSIP interception flow.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


def add_box(ax, x, y, w, h, text, fc, ec="#333333", lw=1.2, fs=10):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
    )
    ax.add_patch(box)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color="#111111", wrap=True)
    return box


def arrow(ax, x1, y1, x2, y2, color="#333333", lw=1.8, style="-|>", ls="-"):
    ax.annotate(
        "",
        xy=(x2, y2),
        xytext=(x1, y1),
        arrowprops=dict(arrowstyle=style, color=color, lw=lw, linestyle=ls),
    )


def main():
    out_prefix = Path("experiments/figures/fig_attack_example_interception")
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(13, 7))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Swimlane separators
    ax.plot([0.33, 0.33], [0.06, 0.95], color="#CCCCCC", linestyle="--", linewidth=1.2)
    ax.plot([0.66, 0.66], [0.06, 0.95], color="#CCCCCC", linestyle="--", linewidth=1.2)

    ax.text(0.165, 0.965, "Malicious Client", ha="center", va="center", fontsize=13, fontweight="bold")
    ax.text(0.495, 0.965, "Shuffler + TSIP Verifier", ha="center", va="center", fontsize=13, fontweight="bold")
    ax.text(0.825, 0.965, "Aggregators / Decoder", ha="center", va="center", fontsize=13, fontweight="bold")

    # Client lane
    c1 = add_box(
        ax,
        0.05,
        0.80,
        0.22,
        0.11,
        "1) Previous accepted state\n(prev_loc, prev_chain)",
        fc="#E8F0FE",
    )
    c2 = add_box(
        ax,
        0.05,
        0.61,
        0.22,
        0.14,
        "2) Attack action (A1/A5)\nTeleport or replay stale commitment",
        fc="#FDECEA",
        ec="#C62828",
        lw=1.6,
    )
    c3 = add_box(
        ax,
        0.05,
        0.40,
        0.22,
        0.14,
        "3) Submit report\nidx/val + tsip payload + proof",
        fc="#FFF4E5",
    )

    # Shuffler lane
    s1 = add_box(
        ax,
        0.39,
        0.76,
        0.22,
        0.14,
        "4) Load stored state\nand parse submission",
        fc="#E8F0FE",
    )
    s2 = add_box(
        ax,
        0.39,
        0.54,
        0.22,
        0.18,
        "5) TSIP checks\n- prev_loc/prev_chain match\n- ZK distance proof valid\n- monotonic time/window",
        fc="#E3F2FD",
    )
    s3 = add_box(
        ax,
        0.39,
        0.30,
        0.22,
        0.16,
        "6) Interception\nReject (HTTP 400):\ninvalid proof / commitment mismatch",
        fc="#FDECEA",
        ec="#C62828",
        lw=1.8,
    )
    s4 = add_box(
        ax,
        0.39,
        0.10,
        0.22,
        0.13,
        "7) Security bookkeeping\nrejection streak / blacklist update",
        fc="#F3E5F5",
    )

    # Aggregator lane
    a1 = add_box(
        ax,
        0.71,
        0.52,
        0.22,
        0.14,
        "No forwarding to A/R\nfor rejected submission",
        fc="#F5F5F5",
        ec="#757575",
    )
    a2 = add_box(
        ax,
        0.71,
        0.26,
        0.22,
        0.14,
        "Aggregation result excludes\nthis malicious sample",
        fc="#E8F5E9",
        ec="#2E7D32",
        lw=1.5,
    )

    # Main flow arrows
    arrow(ax, 0.16, 0.80, 0.16, 0.75, color="#D32F2F", lw=2.0)
    arrow(ax, 0.16, 0.61, 0.16, 0.54, color="#D32F2F", lw=2.0)
    arrow(ax, 0.27, 0.47, 0.39, 0.82, color="#D32F2F", lw=2.0)   # submit -> shuffler ingest
    arrow(ax, 0.50, 0.76, 0.50, 0.72, color="#1E88E5", lw=2.0)
    arrow(ax, 0.50, 0.54, 0.50, 0.46, color="#1E88E5", lw=2.0)
    arrow(ax, 0.50, 0.30, 0.50, 0.23, color="#8E24AA", lw=2.0)

    # Blocked to aggregators
    arrow(ax, 0.61, 0.38, 0.71, 0.59, color="#616161", lw=2.0, ls="--")
    arrow(ax, 0.61, 0.18, 0.71, 0.33, color="#2E7D32", lw=2.0)
    ax.text(0.67, 0.45, "blocked", color="#616161", fontsize=10, rotation=23, ha="center")

    # Optional honest path for contrast
    ax.plot([0.27, 0.39], [0.86, 0.86], color="#2E7D32", linestyle="--", linewidth=1.8)
    arrow(ax, 0.39, 0.86, 0.71, 0.86, color="#2E7D32", lw=1.8, ls="--")
    ax.text(0.55, 0.885, "honest submission (passes checks)", color="#2E7D32", fontsize=9, ha="center")
    ax.text(0.80, 0.885, "forwarded to A/R", color="#2E7D32", fontsize=9, ha="center")

    # Legend-like notes
    ax.text(0.02, 0.03, "Red: attack path    Blue: verification path    Gray dashed: blocked forwarding",
            fontsize=10, color="#333333")

    fig.suptitle("Attack Example and TSIP Interception Flow", fontsize=16, fontweight="bold", y=0.995)
    fig.savefig(out_prefix.with_suffix(".png"), dpi=240, bbox_inches="tight", facecolor="white")
    fig.savefig(out_prefix.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"[ok] png: {out_prefix.with_suffix('.png')}")
    print(f"[ok] pdf: {out_prefix.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
