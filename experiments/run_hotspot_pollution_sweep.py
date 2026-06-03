#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = 10_000
GRID_W = 100
CELL_SIZE_M = 100.0

MODE_LABELS = {
    "no_integrity": "No integrity",
    "tsip_only": "TSIP-only",
    "tsip_external": "TSIP + external layer",
}


def parse_float_list(raw: str) -> list[float]:
    return [float(x) for x in str(raw).replace(",", " ").split() if x.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(x) for x in str(raw).replace(",", " ").split() if x.strip()]


def load_records(path: Path, n_base_users: int) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if len(records) >= n_base_users:
                break
    if not records:
        raise RuntimeError(f"no trajectory records loaded from {path}")
    return records


def cell_seq(record: dict) -> list[int]:
    seq: list[int] = []
    for w in record.get("windows", []):
        try:
            seq.append(int(w.get("cell_id")) % DOMAIN)
        except (TypeError, ValueError):
            continue
    return seq


def user_cell(seqs: list[list[int]], user_idx: int, round_idx: int) -> int:
    seq = seqs[user_idx % len(seqs)]
    if not seq:
        return 0
    # Dephase repeated virtual users so the 50-user real trace can support
    # percentage sweeps with finer granularity than one physical record.
    offset = (user_idx // len(seqs)) * 17
    return int(seq[(round_idx + offset) % len(seq)])


def top_k(hist: list[float], k: int) -> list[int]:
    items = [(i, v) for i, v in enumerate(hist) if v > 0.0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [i for i, _ in items[:k]]


def rank_of(hist: list[float], cell: int) -> int:
    target_v = hist[cell]
    if target_v <= 0:
        return DOMAIN + 1
    better = sum(1 for v in hist if v > target_v)
    ties_before = sum(1 for i, v in enumerate(hist) if v == target_v and i < cell)
    return better + ties_before + 1


def jaccard(a: set[int], b: set[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def laplace(rng: random.Random, scale: float) -> float:
    if scale <= 0:
        return 0.0
    u = rng.random() - 0.5
    return -scale * math.copysign(math.log(1.0 - 2.0 * abs(u)), u)


def release(hist: list[float], epsilon: float, tau: float, tau2: float, rng: random.Random) -> list[float]:
    scale = 1.0 / max(epsilon, 1e-12)
    out = [0.0] * len(hist)
    for i, v in enumerate(hist):
        if v < tau:
            continue
        noisy = max(0.0, v + laplace(rng, scale))
        if noisy >= tau2:
            out[i] = noisy
    return out


def cell_xy(cell: int) -> tuple[int, int]:
    return int(cell) % GRID_W, int(cell) // GRID_W


def reachable(src: int, dst: int, radius_m: float) -> bool:
    sx, sy = cell_xy(src)
    dx, dy = cell_xy(dst)
    dist_m = math.hypot(float(sx - dx), float(sy - dy)) * CELL_SIZE_M
    return dist_m <= radius_m


def reachable_lattice_cells(radius_m: float) -> int:
    r_cells = radius_m / CELL_SIZE_M
    r2 = r_cells * r_cells
    total = 0
    # Interior-anchor lattice count. This intentionally matches the paper's
    # reach-bound calculation, not edge-clipped city geometry.
    lim = int(math.ceil(r_cells))
    for y in range(-lim, lim + 1):
        for x in range(-lim, lim + 1):
            if x * x + y * y <= r2 + 1e-12:
                total += 1
    return total


def choose_target(benign_hist: list[float], desired_rank: int, top_exclude: int) -> int:
    ranked = top_k(benign_hist, DOMAIN)
    excluded = set(ranked[:top_exclude])
    if desired_rank <= len(ranked):
        candidate = ranked[desired_rank - 1]
        if candidate not in excluded:
            return candidate
    for candidate in ranked:
        if candidate not in excluded:
            return candidate
    for candidate in range(DOMAIN):
        if candidate not in excluded:
            return candidate
    raise RuntimeError("could not choose target cell")


def build_benign_hist(seqs: list[list[int]], n_users: int, rounds: int) -> list[float]:
    hist = [0.0] * DOMAIN
    for r in range(rounds):
        for u in range(n_users):
            hist[user_cell(seqs, u, r)] += 1.0
    return hist


def selected_malicious_users(n_users: int, rho: float, seed: int) -> set[int]:
    n_mal = int(round(n_users * rho))
    rng = random.Random(seed)
    return set(rng.sample(range(n_users), min(n_users, max(0, n_mal))))


def simulate_condition(
    *,
    seqs: list[list[int]],
    n_users: int,
    rounds: int,
    rho: float,
    seed: int,
    target_cell: int,
    benign_release: list[float],
    mode: str,
    radius_m: float,
    external_malicious_pass: float,
    external_benign_frr: float,
    epsilon: float,
    tau: float,
    tau2: float,
) -> dict:
    mode_salt = sum((i + 1) * ord(ch) for i, ch in enumerate(mode))
    rng = random.Random(seed * 1009 + mode_salt)
    malicious = selected_malicious_users(n_users, rho, seed)
    hist = [0.0] * DOMAIN
    accepted_malicious_to_target = 0
    malicious_total = 0
    benign_false_rejects = 0
    benign_total = 0

    for r in range(rounds):
        for u in range(n_users):
            true_cell = user_cell(seqs, u, r)
            if u not in malicious:
                benign_total += 1
                if mode == "tsip_external" and rng.random() < external_benign_frr:
                    benign_false_rejects += 1
                    continue
                hist[true_cell] += 1.0
                continue

            malicious_total += 1
            if mode == "no_integrity":
                hist[target_cell] += 1.0
                accepted_malicious_to_target += 1
            elif mode == "tsip_only":
                if reachable(true_cell, target_cell, radius_m):
                    hist[target_cell] += 1.0
                    accepted_malicious_to_target += 1
                else:
                    hist[true_cell] += 1.0
            elif mode == "tsip_external":
                if rng.random() <= external_malicious_pass and reachable(true_cell, target_cell, radius_m):
                    hist[target_cell] += 1.0
                    accepted_malicious_to_target += 1
                else:
                    # External controls or reach checks prevent target pollution.
                    hist[true_cell] += 1.0
            else:
                raise RuntimeError(f"unknown mode: {mode}")

    attacked_release = release(
        hist,
        epsilon=epsilon,
        tau=tau,
        tau2=tau2,
        rng=random.Random(seed * 9176 + len(mode) * 37),
    )

    benign_top20 = set(top_k(benign_release, 20))
    attacked_top20 = set(top_k(attacked_release, 20))
    benign_rank = rank_of(benign_release, target_cell)
    attacked_rank = rank_of(attacked_release, target_cell)
    benign_rank_at20 = min(benign_rank, 21)
    attacked_rank_at20 = min(attacked_rank, 21)
    return {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "rho": rho,
        "seed": seed,
        "target_cell": target_cell,
        "target_rank_benign": benign_rank,
        "target_rank_attacked": attacked_rank,
        "target_rank_lift": max(0, benign_rank_at20 - attacked_rank_at20),
        "false_hotspot_at20": int(target_cell in attacked_top20 and target_cell not in benign_top20),
        "top20_jaccard": jaccard(attacked_top20, benign_top20),
        "accepted_malicious_to_target": accepted_malicious_to_target,
        "malicious_reports": malicious_total,
        "target_pollution_rate": accepted_malicious_to_target / malicious_total if malicious_total else 0.0,
        "false_reject_rate": benign_false_rejects / benign_total if benign_total else 0.0,
    }


def mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def std(vals: list[float]) -> float:
    if not vals:
        return 0.0
    m = mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))


def summarize(rows: list[dict]) -> list[dict]:
    buckets: dict[tuple[str, float], list[dict]] = defaultdict(list)
    for row in rows:
        buckets[(row["mode"], float(row["rho"]))].append(row)
    out: list[dict] = []
    for (mode, rho), rs in sorted(buckets.items(), key=lambda x: (x[0][0], x[0][1])):
        out.append(
            {
                "mode": mode,
                "mode_label": MODE_LABELS[mode],
                "rho": rho,
                "n_seeds": len({r["seed"] for r in rs}),
                "target_rank_lift_mean": mean([float(r["target_rank_lift"]) for r in rs]),
                "target_rank_lift_std": std([float(r["target_rank_lift"]) for r in rs]),
                "false_hotspot_at20_mean": mean([float(r["false_hotspot_at20"]) for r in rs]),
                "false_hotspot_at20_std": std([float(r["false_hotspot_at20"]) for r in rs]),
                "top20_jaccard_mean": mean([float(r["top20_jaccard"]) for r in rs]),
                "top20_jaccard_std": std([float(r["top20_jaccard"]) for r in rs]),
                "target_pollution_rate_mean": mean([float(r["target_pollution_rate"]) for r in rs]),
                "false_reject_rate_mean": mean([float(r["false_reject_rate"]) for r in rs]),
                "target_rank_attacked_mean": mean([float(r["target_rank_attacked"]) for r in rs]),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def plot_summary(summary_rows: list[dict], out_path: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib")
    import matplotlib.pyplot as plt

    # Color improves screen readability; line styles and markers keep the plot
    # readable under black-and-white reproduction.
    colors = {
        "no_integrity": "#c2410c",
        "tsip_only": "#2563eb",
        "tsip_external": "#15803d",
    }
    markers = {
        "no_integrity": "o",
        "tsip_only": "s",
        "tsip_external": "^",
    }
    linestyles = {
        "no_integrity": "-",
        "tsip_only": "--",
        "tsip_external": ":",
    }
    fig, ax = plt.subplots(1, 1, figsize=(4.4, 3.55))
    mode_order = ["no_integrity", "tsip_only", "tsip_external"]

    for mode in mode_order:
        rs = [r for r in summary_rows if r["mode"] == mode]
        rs.sort(key=lambda r: float(r["rho"]))
        xs = [100.0 * float(r["rho"]) for r in rs]
        ys = [float(r["false_hotspot_at20_mean"]) for r in rs]
        es = [float(r["false_hotspot_at20_std"]) for r in rs]
        ax.errorbar(
            xs,
            ys,
            yerr=es,
            color=colors[mode],
            marker=markers[mode],
            linestyle=linestyles[mode],
            linewidth=2.2,
            markersize=6.0,
            markerfacecolor="white",
            markeredgewidth=1.3,
            capsize=3,
            label=MODE_LABELS[mode],
        )
    ax.set_xlabel("Malicious fraction $\\rho$ (%)")
    ax.set_ylabel("FalseHotspot@20")
    ax.set_ylim(-0.05, 1.05)
    ax.set_xticks([1, 2, 5, 10, 20, 30])
    ax.grid(True, linestyle="--", alpha=0.32)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.24),
        ncol=3,
        fontsize=7.5,
        frameon=False,
        handlelength=2.2,
        columnspacing=0.9,
    )
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220)
    fig.savefig(out_path.with_suffix(".pdf"))


def main() -> None:
    p = argparse.ArgumentParser(description="Sweep malicious hotspot pollution under TSIP reach bounds.")
    p.add_argument("--traj", default=str(ROOT / "experiments/geolife_tsip_ready_50u.jsonl"))
    p.add_argument("--n-base-users", type=int, default=50)
    p.add_argument("--n-users", type=int, default=100)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--rhos", default="0.01 0.02 0.05 0.10 0.20 0.30")
    p.add_argument("--seeds", default="1 2 3 4 5")
    p.add_argument("--epsilon", type=float, default=1.0)
    p.add_argument("--tau", type=float, default=3.0)
    p.add_argument("--tau2", type=float, default=3.0)
    p.add_argument("--k-window", type=int, default=6)
    p.add_argument("--tier-anchor-cap-m", type=float, default=6600.0)
    p.add_argument("--cap-ratio", type=float, default=0.5)
    p.add_argument(
        "--target-cell",
        type=int,
        default=3153,
        help="Target false hotspot cell. Default is outside the benign Top-20 but reachable by a small user subset.",
    )
    p.add_argument("--target-rank", type=int, default=40)
    p.add_argument("--external-malicious-pass", type=float, default=0.25)
    p.add_argument("--external-benign-frr", type=float, default=0.01)
    p.add_argument("--out-dir", default=str(ROOT / "experiments/hotspot_pollution"))
    args = p.parse_args()

    records = load_records(Path(args.traj), args.n_base_users)
    seqs = [cell_seq(r) for r in records]
    seqs = [s for s in seqs if s]
    benign_hist = build_benign_hist(seqs, args.n_users, args.rounds)
    target_cell = int(args.target_cell) % DOMAIN if args.target_cell >= 0 else choose_target(
        benign_hist,
        desired_rank=args.target_rank,
        top_exclude=20,
    )
    benign_release = release(
        benign_hist,
        epsilon=args.epsilon,
        tau=args.tau,
        tau2=args.tau2,
        rng=random.Random(20260504),
    )
    radius_m = float(args.tier_anchor_cap_m) * float(args.cap_ratio)
    reach_cells = reachable_lattice_cells(radius_m)
    reach_fraction = reach_cells / DOMAIN

    rows: list[dict] = []
    for seed in parse_int_list(args.seeds):
        for rho in parse_float_list(args.rhos):
            for mode in ("no_integrity", "tsip_only", "tsip_external"):
                row = simulate_condition(
                    seqs=seqs,
                    n_users=args.n_users,
                    rounds=args.rounds,
                    rho=rho,
                    seed=seed,
                    target_cell=target_cell,
                    benign_release=benign_release,
                    mode=mode,
                    radius_m=radius_m,
                    external_malicious_pass=args.external_malicious_pass,
                    external_benign_frr=args.external_benign_frr,
                    epsilon=args.epsilon,
                    tau=args.tau,
                    tau2=args.tau2,
                )
                row.update(
                    {
                        "n_users": args.n_users,
                        "rounds": args.rounds,
                        "epsilon": args.epsilon,
                        "tau": args.tau,
                        "tau2": args.tau2,
                        "k_window": args.k_window,
                        "cap_ratio": args.cap_ratio,
                        "cap_policy_m": radius_m,
                        "reach_cells": reach_cells,
                        "reach_fraction": reach_fraction,
                    }
                )
                rows.append(row)

    summary_rows = summarize(rows)
    out_dir = Path(args.out_dir)
    per_seed_csv = out_dir / "hotspot_pollution_per_seed.csv"
    summary_csv = out_dir / "hotspot_pollution_summary.csv"
    fig_path = out_dir / "fig_hotspot_pollution.png"
    write_csv(per_seed_csv, rows)
    write_csv(summary_csv, summary_rows)
    plot_summary(summary_rows, fig_path)

    benign_top20 = set(top_k(benign_release, 20))
    meta = {
        "traj": str(Path(args.traj).resolve()),
        "n_base_users": args.n_base_users,
        "n_users": args.n_users,
        "rounds": args.rounds,
        "rhos": parse_float_list(args.rhos),
        "seeds": parse_int_list(args.seeds),
        "epsilon": args.epsilon,
        "tau": args.tau,
        "tau2": args.tau2,
        "k_window": args.k_window,
        "cap_ratio": args.cap_ratio,
        "cap_policy_m": radius_m,
        "reach_cells": reach_cells,
        "reach_fraction": reach_fraction,
        "target_cell": target_cell,
        "target_rank_benign_release": rank_of(benign_release, target_cell),
        "target_in_benign_top20": target_cell in benign_top20,
        "external_malicious_pass": args.external_malicious_pass,
        "external_benign_frr": args.external_benign_frr,
        "mode_counts": dict(Counter(r["mode"] for r in rows)),
    }
    (out_dir / "hotspot_pollution_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[out] per-seed: {per_seed_csv}")
    print(f"[out] summary : {summary_csv}")
    print(f"[out] figure  : {fig_path}")
    print(
        "[meta] target_cell={target_cell} benign_rank={rank} reach={reach:.2%} cap_policy_m={cap:.1f}".format(
            target_cell=target_cell,
            rank=meta["target_rank_benign_release"],
            reach=reach_fraction,
            cap=radius_m,
        )
    )


if __name__ == "__main__":
    main()
