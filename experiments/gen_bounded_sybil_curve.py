#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def parse_int_list(raw: str) -> list[int]:
    out: list[int] = []
    for tok in str(raw).replace(",", " ").split():
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok))
    return out


def parse_float_list(raw: str) -> list[float]:
    out: list[float] = []
    for tok in str(raw).replace(",", " ").split():
        tok = tok.strip()
        if not tok:
            continue
        out.append(float(tok))
    return out


def parse_tier_costs(raw: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    items = [x.strip() for x in str(raw).split(",") if x.strip()]
    for item in items:
        if ":" not in item:
            raise RuntimeError(f"invalid tier cost item: {item}")
        tier, cost = item.split(":", 1)
        tier = tier.strip()
        if not tier:
            raise RuntimeError(f"invalid empty tier in: {item}")
        out.append((tier, float(cost.strip())))
    if not out:
        raise RuntimeError("empty tier-cost map")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate A4 bounded-Sybil cost curves for (t,n) sweeps.")
    parser.add_argument("--t-list", default="1 2 3 4 5", help="Threshold list, e.g. '1 2 3'.")
    parser.add_argument("--n-list", default="1 3 5", help="Anchor-pool size list, e.g. '1 3 5'.")
    parser.add_argument(
        "--budget-list",
        default="10 20 30 40 50 80 100 150 200",
        help="Attacker budget list.",
    )
    parser.add_argument(
        "--c-anchor",
        type=float,
        default=1.0,
        help="Per-anchor unit cost C_anchor.",
    )
    parser.add_argument(
        "--tier-costs",
        default="walk:0,bike:1,vehicle:5,transit:3",
        help="Tier VC costs: tier:cost,...",
    )
    parser.add_argument("--out-csv", required=True, help="Output CSV path.")
    parser.add_argument("--out-png", default="", help="Optional output PNG path.")
    args = parser.parse_args()

    t_list = sorted(set(parse_int_list(args.t_list)))
    n_list = sorted(set(parse_int_list(args.n_list)))
    budgets = sorted(set(parse_float_list(args.budget_list)))
    tier_costs = parse_tier_costs(args.tier_costs)
    c_anchor = float(args.c_anchor)

    rows: list[dict[str, object]] = []
    for n in n_list:
        for t in t_list:
            if t <= 0 or t > n:
                continue
            for tier, c_vc in tier_costs:
                unit_cost = float(t * c_anchor + c_vc)
                for b in budgets:
                    ns_max = int(math.floor(float(b) / unit_cost)) if unit_cost > 0 else 0
                    rows.append(
                        {
                            "n": int(n),
                            "t": int(t),
                            "tier": str(tier),
                            "budget": float(b),
                            "c_anchor": float(c_anchor),
                            "c_vc": float(c_vc),
                            "unit_cost": float(unit_cost),
                            "ns_max": int(ns_max),
                        }
                    )

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "n",
                "t",
                "tier",
                "budget",
                "c_anchor",
                "c_vc",
                "unit_cost",
                "ns_max",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"[ok] csv: {out_csv}")

    if not args.out_png:
        return

    try:
        import matplotlib.pyplot as plt
    except Exception:
        print("[warn] matplotlib unavailable; skip png")
        return

    # One subplot per tier, with lines grouped by (t,n).
    tiers = [t for t, _ in tier_costs]
    fig, axes = plt.subplots(len(tiers), 1, figsize=(9, 3.2 * len(tiers)), sharex=True)
    if len(tiers) == 1:
        axes = [axes]

    for ax, tier in zip(axes, tiers):
        tier_rows = [r for r in rows if r["tier"] == tier]
        for n in n_list:
            for t in t_list:
                key_rows = [r for r in tier_rows if int(r["n"]) == n and int(r["t"]) == t]
                if not key_rows:
                    continue
                key_rows.sort(key=lambda x: float(x["budget"]))
                xs = [float(r["budget"]) for r in key_rows]
                ys = [int(r["ns_max"]) for r in key_rows]
                ax.plot(xs, ys, marker="o", linewidth=1.8, markersize=4, label=f"t={t}, n={n}")
        ax.set_title(f"A4 bounded Sybil curve (tier={tier})")
        ax.set_ylabel("Max Sybil Identities")
        ax.grid(alpha=0.25, linestyle="--")
        ax.legend(ncol=3, fontsize=8)

    axes[-1].set_xlabel("Attacker Budget")
    fig.suptitle("N_s <= floor(B / (t*C_anchor + C_vc(tier)))", y=0.995)
    fig.tight_layout()

    out_png = Path(args.out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    print(f"[ok] png: {out_png}")


if __name__ == "__main__":
    main()
