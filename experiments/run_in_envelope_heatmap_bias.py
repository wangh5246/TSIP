#!/usr/bin/env python3
"""
Offline heatmap-bias experiment for payload-consistent in-envelope poisoning.

The experiment reads TSIP-ready GeoLife / T-Drive JSONL traces, replaces a
fixed fraction of users with malicious users, and compares benign vs attacked
heatmaps under:

  - benign
  - no_integrity: attackers can vote for any target cell
  - tsip_only: attackers must satisfy per-step and ADWC policy-cap envelopes
  - tsip_external: tsip_only plus a simple historical-support plausibility layer

It reports pre-DP and post-DP heatmap bias plus hotspot distortion metrics for
three attacks:

  P1 targeted cold-spot promotion
  P2 hotspot amplification
  P3 corridor smearing / route pollution
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Profile:
    name: str
    k: int
    policy_cap_m: float


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    cell: str


@dataclass
class Dataset:
    name: str
    path: Path
    cell_size_m: float
    grid_w: int
    numeric_cell_id: bool
    records: list[dict]
    traces: list[list[Point]]


PROFILES = {
    "k6": Profile("k6", 6, 3300.0),
    "k30": Profile("k30", 30, 16500.0),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--datasets", default="geolife,tdrive")
    p.add_argument("--geolife", default=str(ROOT / "experiments/geolife_tsip_ready_50u.jsonl"))
    p.add_argument("--tdrive", default=str(ROOT / "experiments/tdrive_tsip_ready_50u.jsonl"))
    p.add_argument("--profiles", default="k6,k30")
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--n-users", type=int, default=50)
    p.add_argument("--malicious-rate", type=float, default=0.10)
    p.add_argument("--epsilon", type=float, default=1.0)
    p.add_argument("--tau", type=float, default=3.0)
    p.add_argument("--tau2", type=float, default=3.0)
    p.add_argument("--dt-sec", type=float, default=60.0)
    p.add_argument("--vmax-mps", type=float, default=110.0)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--seed", type=int, default=20260504)
    p.add_argument("--out-dir", default="")
    return p.parse_args()


def load_dataset(name: str, path: Path, n_users: int) -> Dataset:
    records: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if len(records) >= n_users:
                break
    if not records:
        raise RuntimeError(f"no records loaded from {path}")
    cell_size = float(records[0].get("cell_size_m", 100.0))
    grid_w = int(records[0].get("grid_w", 100))
    first_windows = records[0].get("windows", [])
    numeric_cell_id = bool(first_windows and ":" not in str(first_windows[0].get("cell_id", "")))
    traces: list[list[Point]] = []
    for rec in records:
        pts: list[Point] = []
        for w in rec.get("windows", []):
            pts.append(Point(float(w["x_m"]), float(w["y_m"]), str(w["cell_id"])))
        if pts:
            traces.append(pts)
    if not traces:
        raise RuntimeError(f"records have no windows: {path}")
    return Dataset(
        name=name,
        path=path,
        cell_size_m=cell_size,
        grid_w=grid_w,
        numeric_cell_id=numeric_cell_id,
        records=records[: len(traces)],
        traces=traces,
    )


def point_at(trace: list[Point], round_idx: int) -> Point:
    return trace[round_idx % len(trace)]


def cell_from_xy(dataset: Dataset, x: float, y: float) -> str:
    cx = int(math.floor(x / dataset.cell_size_m))
    cy = int(math.floor(y / dataset.cell_size_m))
    if dataset.numeric_cell_id:
        return str(cy * dataset.grid_w + cx)
    return f"{cx}:{cy}"


def cell_center(cell: str, cell_size_m: float, fallback: Point | None = None) -> tuple[float, float]:
    if ":" not in cell:
        if fallback is not None:
            return fallback.x, fallback.y
        # GeoLife normalized files use integer id = cy * 100 + cx.
        cid = int(cell)
        cx = cid % 100
        cy = cid // 100
    else:
        cx_s, cy_s = cell.split(":", 1)
        cx, cy = int(cx_s), int(cy_s)
    return (cx + 0.5) * cell_size_m, (cy + 0.5) * cell_size_m


def euclid(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_feasible_point(
    prev: Point,
    anchor: Point,
    target_xy: tuple[float, float],
    max_step_m: float,
    policy_cap_m: float,
) -> tuple[float, float]:
    """Project a target onto the intersection of the step and ADWC disks."""
    px, py = prev.x, prev.y
    ax, ay = anchor.x, anchor.y
    tx, ty = target_xy
    best = (px, py)
    best_dist = euclid(best, target_xy)

    # Sample the segment toward the target. This is deterministic and adequate
    # for quantifying reachable pollution area without a geometry dependency.
    for i in range(1, 257):
        frac = i / 256.0
        x = px + (tx - px) * frac
        y = py + (ty - py) * frac
        if math.hypot(x - px, y - py) <= max_step_m + 1e-9 and math.hypot(x - ax, y - ay) <= policy_cap_m + 1e-9:
            d = math.hypot(x - tx, y - ty)
            if d < best_dist:
                best = (x, y)
                best_dist = d
    return best


def build_benign(dataset: Dataset, rounds: int) -> Counter[str]:
    h: Counter[str] = Counter()
    for trace in dataset.traces:
        for r in range(rounds):
            h[point_at(trace, r).cell] += 1
    return h


def top_cells(hist: Counter[str], k: int) -> list[str]:
    return [c for c, _ in sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def rank_map(hist: Counter[str]) -> dict[str, int]:
    return {c: i + 1 for i, (c, _) in enumerate(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))}


def l1_bias(attacked: Counter[str], benign: Counter[str]) -> float:
    keys = set(attacked) | set(benign)
    return sum(abs(attacked.get(k, 0.0) - benign.get(k, 0.0)) for k in keys) / (sum(benign.values()) + 1.0)


def rmse(attacked: Counter[str], benign: Counter[str]) -> float:
    keys = set(attacked) | set(benign)
    if not keys:
        return 0.0
    return math.sqrt(sum((attacked.get(k, 0.0) - benign.get(k, 0.0)) ** 2 for k in keys) / len(keys))


def dp_release(hist: Counter[str], epsilon: float, threshold: float, rng: random.Random) -> Counter[str]:
    if epsilon <= 0:
        raise ValueError("epsilon must be positive")
    scale = 1.0 / epsilon
    released: Counter[str] = Counter()
    for cell, count in hist.items():
        noisy = max(0.0, float(count) + rng.expovariate(1.0 / scale) - rng.expovariate(1.0 / scale))
        if noisy >= threshold:
            released[cell] = noisy
    return released


def choose_p1_target(benign: Counter[str], reachable: Counter[str], top_k: int) -> str:
    benign_top = set(top_cells(benign, top_k))
    candidates = [
        (benign.get(c, 0), -reachable.get(c, 0), c)
        for c in reachable
        if benign.get(c, 0) > 0 and c not in benign_top
    ]
    if not candidates:
        candidates = [(v, 0, c) for c, v in benign.items() if c not in benign_top and v > 0]
    return min(candidates)[2]


def choose_p2_target(benign: Counter[str]) -> str:
    return top_cells(benign, 1)[0]


def malicious_user_indices(n_users: int, malicious_rate: float, seed: int) -> set[int]:
    n_mal = max(1, int(round(n_users * malicious_rate)))
    rng = random.Random(seed)
    return set(rng.sample(range(n_users), min(n_mal, n_users)))


def reachable_counter(dataset: Dataset, mal_users: Iterable[int], profile: Profile, rounds: int, max_step_m: float) -> Counter[str]:
    counts: Counter[str] = Counter()
    for ui in mal_users:
        trace = dataset.traces[ui]
        for r in range(rounds):
            prev = point_at(trace, max(0, r - 1))
            anchor = point_at(trace, max(0, r - profile.k))
            radius = min(max_step_m, profile.policy_cap_m)
            for angle_i in range(32):
                angle = 2.0 * math.pi * angle_i / 32.0
                x = prev.x + math.cos(angle) * radius
                y = prev.y + math.sin(angle) * radius
                if math.hypot(x - anchor.x, y - anchor.y) <= profile.policy_cap_m + 1e-9:
                    counts[cell_from_xy(dataset, x, y)] += 1
    return counts


def corridor_target(dataset: Dataset, round_idx: int, total_rounds: int) -> tuple[float, float]:
    xs = [p.x for trace in dataset.traces for p in trace[: min(len(trace), total_rounds)]]
    ys = [p.y for trace in dataset.traces for p in trace[: min(len(trace), total_rounds)]]
    x0, x1 = min(xs), max(xs)
    y_mid = sorted(ys)[len(ys) // 2]
    frac = round_idx / max(1, total_rounds - 1)
    return x0 + (x1 - x0) * frac, y_mid


def apply_attack(
    dataset: Dataset,
    benign: Counter[str],
    attack: str,
    mode: str,
    profile: Profile,
    mal_users: set[int],
    rounds: int,
    max_step_m: float,
    top_k: int,
    seed: int,
) -> tuple[Counter[str], str, int]:
    if mode == "benign":
        return Counter(benign), "", 0

    reachable = reachable_counter(dataset, mal_users, profile, rounds, max_step_m)
    if attack == "p1_cold_spot":
        target_cell = choose_p1_target(benign, reachable, top_k)
    elif attack == "p2_hotspot":
        target_cell = choose_p2_target(benign)
    else:
        target_cell = "corridor"

    external_support = {
        (ui, point_at(dataset.traces[ui], r).cell)
        for ui in range(len(dataset.traces))
        for r in range(rounds)
    }

    attacked: Counter[str] = Counter()
    accepted_malicious = 0
    rng = random.Random(seed)
    for ui, trace in enumerate(dataset.traces):
        for r in range(rounds):
            real = point_at(trace, r)
            if ui not in mal_users:
                attacked[real.cell] += 1
                continue

            if mode == "no_integrity":
                if attack == "p3_corridor":
                    fake_xy = corridor_target(dataset, r, rounds)
                    fake_cell = cell_from_xy(dataset, fake_xy[0], fake_xy[1])
                else:
                    fake_cell = target_cell
                attacked[fake_cell] += 1
                accepted_malicious += 1
                continue

            prev = point_at(trace, max(0, r - 1))
            anchor = point_at(trace, max(0, r - profile.k))
            if attack == "p3_corridor":
                target_xy = corridor_target(dataset, r, rounds)
            else:
                target_xy = cell_center(target_cell, dataset.cell_size_m, fallback=real)
            fake_xy = nearest_feasible_point(prev, anchor, target_xy, max_step_m, profile.policy_cap_m)
            if attack == "p3_corridor":
                # Add a deterministic small lateral spread so P3 creates a band
                # rather than a single projected line.
                fake_xy = (fake_xy[0], fake_xy[1] + rng.uniform(-dataset.cell_size_m, dataset.cell_size_m))
            fake_cell = cell_from_xy(dataset, fake_xy[0], fake_xy[1])

            if mode == "tsip_external" and (ui, fake_cell) not in external_support:
                attacked[real.cell] += 1
                continue

            attacked[fake_cell] += 1
            accepted_malicious += 1
    return attacked, target_cell, accepted_malicious


def metric_row(
    dataset: str,
    profile: Profile,
    attack: str,
    mode: str,
    target_cell: str,
    accepted_malicious: int,
    malicious_total: int,
    benign: Counter[str],
    attacked: Counter[str],
    stage: str,
    top_k: int,
) -> dict[str, object]:
    benign_top = set(top_cells(benign, top_k))
    attacked_top = set(top_cells(attacked, top_k))
    benign_rank = rank_map(benign)
    attacked_rank = rank_map(attacked)
    target_count_lift = attacked.get(target_cell, 0.0) - benign.get(target_cell, 0.0) if target_cell != "corridor" else 0.0
    target_rank_lift = (
        benign_rank.get(target_cell, len(benign_rank) + 1) - attacked_rank.get(target_cell, len(attacked_rank) + 1)
        if target_cell != "corridor"
        else 0
    )
    top_j = len(benign_top & attacked_top) / top_k if top_k else 0.0
    false_hotspots = len([c for c in attacked_top if c not in benign_top])
    top1_count = attacked.get(top_cells(attacked, 1)[0], 0.0) if attacked else 0.0
    total = sum(attacked.values()) or 1.0
    top5_count = sum(attacked.get(c, 0.0) for c in top_cells(attacked, min(5, top_k)))
    return {
        "dataset": dataset,
        "profile": profile.name,
        "k": profile.k,
        "policy_cap_m": profile.policy_cap_m,
        "attack": attack,
        "mode": mode,
        "stage": stage,
        "target_cell": target_cell,
        "accepted_malicious_rate": accepted_malicious / malicious_total if malicious_total else 0.0,
        "bias_l1": l1_bias(attacked, benign),
        "rmse": rmse(attacked, benign),
        "target_count_lift": target_count_lift,
        "target_rank_lift": target_rank_lift,
        "topk_jaccard": top_j,
        "false_hotspot_at_k": false_hotspots,
        "top1_dominance": top1_count / total,
        "top5_dominance": top5_count / total,
        "benign_active_cells": len(benign),
        "attacked_active_cells": len(attacked),
    }


def write_markdown(summary_csv: Path, out_md: Path) -> None:
    rows = list(csv.DictReader(summary_csv.open(encoding="utf-8")))
    key_rows = [
        r for r in rows
        if r["stage"] == "pre_dp" and r["mode"] in {"no_integrity", "tsip_only", "tsip_external"}
    ]
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# In-envelope Poisoning Heatmap Bias\n\n")
        f.write("Defaults: p=10%, epsilon_total=1.0, dt=60s, grid=100m, rounds=30.\n\n")
        f.write("| dataset | profile | attack | mode | bias_l1 | rmse | target_lift | rank_lift | topk_jaccard | false_hotspot@k |\n")
        f.write("|---|---:|---|---|---:|---:|---:|---:|---:|---:|\n")
        for r in key_rows:
            f.write(
                f"| {r['dataset']} | {r['profile']} | {r['attack']} | {r['mode']} | "
                f"{float(r['bias_l1']):.4f} | {float(r['rmse']):.3f} | "
                f"{float(r['target_count_lift']):.2f} | {float(r['target_rank_lift']):.2f} | "
                f"{float(r['topk_jaccard']):.3f} | {float(r['false_hotspot_at_k']):.2f} |\n"
            )
        f.write("\nPost-DP rows are in the CSV; use them to discuss downstream DP/SVT filtering.\n")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "experiments" / "heatmap_bias"
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    max_step_m = args.vmax_mps * args.dt_sec

    dataset_paths = {
        "geolife": Path(args.geolife),
        "tdrive": Path(args.tdrive),
    }
    datasets = [load_dataset(name, dataset_paths[name], args.n_users) for name in args.datasets.split(",") if name]
    profiles = [PROFILES[name] for name in args.profiles.split(",") if name]
    attacks = ["p1_cold_spot", "p2_hotspot", "p3_corridor"]
    modes = ["benign", "no_integrity", "tsip_only", "tsip_external"]

    rows: list[dict[str, object]] = []
    for ds in datasets:
        benign = build_benign(ds, args.rounds)
        mal_users = malicious_user_indices(len(ds.traces), args.malicious_rate, args.seed)
        malicious_total = len(mal_users) * args.rounds
        for profile in profiles:
            for attack in attacks:
                for mode in modes:
                    attacked, target_cell, accepted = apply_attack(
                        ds, benign, attack, mode, profile, mal_users, args.rounds, max_step_m, args.top_k, args.seed
                    )
                    rows.append(metric_row(ds.name, profile, attack, mode, target_cell, accepted, malicious_total, benign, attacked, "pre_dp", args.top_k))
                    benign_dp = dp_release(benign, args.epsilon, args.tau2, rng)
                    attacked_dp = dp_release(attacked, args.epsilon, args.tau2, rng)
                    rows.append(metric_row(ds.name, profile, attack, mode, target_cell, accepted, malicious_total, benign_dp, attacked_dp, "post_dp", args.top_k))

    out_csv = out_dir / "in_envelope_heatmap_bias.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary_csv = out_dir / "in_envelope_heatmap_bias_summary.csv"
    group_keys = ["dataset", "profile", "attack", "mode", "stage"]
    numeric = [
        "accepted_malicious_rate",
        "bias_l1",
        "rmse",
        "target_count_lift",
        "target_rank_lift",
        "topk_jaccard",
        "false_hotspot_at_k",
        "top1_dominance",
        "top5_dominance",
        "benign_active_cells",
        "attacked_active_cells",
    ]
    with summary_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=group_keys + numeric)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in group_keys + numeric})

    out_md = out_dir / "in_envelope_heatmap_bias.md"
    write_markdown(summary_csv, out_md)
    print(f"[out] rows: {out_csv}")
    print(f"[out] summary: {summary_csv}")
    print(f"[out] markdown: {out_md}")


if __name__ == "__main__":
    main()
