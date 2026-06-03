#!/usr/bin/env python3
"""
External proof-of-location / behavioral-layer sensitivity study.

This is an offline deployment-layer experiment. It does not implement carrier
IMSI, TEE, secure elements, or a real attestation service. Instead it asks:
if an external layer can provide enrollment-location gating and/or transparent
behavioral scoring, how much extra robustness does TSIP gain against smooth
false-genesis cold-spot promotion attacks?

The four reported configurations are:
  - no_integrity: no TSIP and no external layer.
  - tsip_only: TSIP envelope/payload binding is present, but a smooth
    false-genesis trajectory is assumed to be internally valid.
  - external_only: PoL/behavior gates are present, but no TSIP proof.
  - tsip_external: TSIP plus the external layer.

For this specific false-genesis/A2b-style study, TSIP-only and no_integrity
accept the smooth malicious trace; external_only and tsip_external differ only
in the explanatory security claim, not in the simulated detector outcome.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


DOMAIN_SIZE = 10_000
GRID_W = 100
CELL_SIZE_M = 100.0


@dataclass(frozen=True)
class Window:
    x: float
    y: float
    cell_id: int
    timestamp: int


@dataclass
class UserTrace:
    user_id: str
    windows: list[Window]


def stable_is_malicious(user_idx: int, malicious_rate: float, seed: int) -> bool:
    payload = f"{seed}:{user_idx}".encode("utf-8")
    raw = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)
    return (raw / float(1 << 64)) < malicious_rate


def cell_from_xy(x: float, y: float) -> int:
    cx = max(0, min(GRID_W - 1, int(x // CELL_SIZE_M)))
    cy = max(0, min(GRID_W - 1, int(y // CELL_SIZE_M)))
    return cy * GRID_W + cx


def xy_from_cell(cell_id: int) -> tuple[float, float]:
    cy, cx = divmod(int(cell_id), GRID_W)
    return (cx + 0.5) * CELL_SIZE_M, (cy + 0.5) * CELL_SIZE_M


def euclidean(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def load_traces(path: Path, n_users: int) -> list[UserTrace]:
    traces: list[UserTrace] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            windows = []
            for w in row.get("windows", []):
                if "x_m" not in w or "y_m" not in w:
                    continue
                x = float(w["x_m"])
                y = float(w["y_m"])
                windows.append(
                    Window(
                        x=x,
                        y=y,
                        cell_id=cell_from_xy(x, y),
                        timestamp=int(w.get("timestamp", w.get("window_id", len(windows)))),
                    )
                )
            if windows:
                traces.append(UserTrace(str(row.get("user_id", len(traces))), windows))
            if len(traces) >= n_users:
                break
    return traces


def prefix_windows(trace: UserTrace, offset: int, rounds: int) -> list[Window]:
    wins = trace.windows
    if not wins:
        return []
    return [wins[(offset + r) % len(wins)] for r in range(rounds)]


def choose_cold_target(
    traces: list[UserTrace],
    malicious_flags: list[bool],
    rounds: int,
    offset: int,
    seed: int,
) -> int:
    gt = Counter()
    for t in traces:
        for w in prefix_windows(t, offset, rounds):
            gt[w.cell_id] += 1

    malicious_starts = [
        (traces[i].windows[0].x, traces[i].windows[0].y)
        for i, is_mal in enumerate(malicious_flags)
        if is_mal
    ]
    if not malicious_starts:
        malicious_starts = [(t.windows[0].x, t.windows[0].y) for t in traces]

    rng = random.Random(seed)
    cold = [c for c in range(DOMAIN_SIZE) if gt[c] == 0]
    candidates = rng.sample(cold, min(1000, len(cold))) if len(cold) > 1000 else cold

    def score(cell: int) -> tuple[float, float]:
        xy = xy_from_cell(cell)
        avg_dist = sum(euclidean(xy, s) for s in malicious_starts) / len(malicious_starts)
        edge_penalty = min(xy[0], xy[1], GRID_W * CELL_SIZE_M - xy[0], GRID_W * CELL_SIZE_M - xy[1])
        return avg_dist, edge_penalty

    return max(candidates, key=score)


def move_toward(src: tuple[float, float], dst: tuple[float, float], max_step_m: float) -> tuple[float, float]:
    d = euclidean(src, dst)
    if d <= max_step_m or d == 0:
        return dst
    ratio = max_step_m / d
    return src[0] + (dst[0] - src[0]) * ratio, src[1] + (dst[1] - src[1]) * ratio


def make_attack_trace(
    real_trace: UserTrace,
    target_cell: int,
    rounds: int,
    verified_genesis: bool,
    max_step_m: float,
) -> list[Window]:
    target_xy = xy_from_cell(target_cell)
    if verified_genesis:
        x, y = real_trace.windows[0].x, real_trace.windows[0].y
        out = []
        for r in range(rounds):
            if r > 0:
                x, y = move_toward((x, y), target_xy, max_step_m)
            out.append(Window(x=x, y=y, cell_id=cell_from_xy(x, y), timestamp=r))
        return out

    # No enrollment PoL: the adversary can choose a fake c0 already at target.
    x, y = target_xy
    return [Window(x=x, y=y, cell_id=target_cell, timestamp=r) for r in range(rounds)]


def step_lengths(windows: list[Window]) -> list[float]:
    return [
        euclidean((a.x, a.y), (b.x, b.y))
        for a, b in zip(windows, windows[1:])
    ]


def headings(windows: list[Window]) -> list[float]:
    hs = []
    for a, b in zip(windows, windows[1:]):
        hs.append(math.atan2(b.y - a.y, b.x - a.x))
    return hs


def heading_changes(windows: list[Window]) -> list[float]:
    hs = headings(windows)
    changes = []
    for a, b in zip(hs, hs[1:]):
        d = abs((b - a + math.pi) % (2 * math.pi) - math.pi)
        changes.append(d)
    return changes


def entropy(cells: Iterable[int]) -> float:
    c = Counter(cells)
    n = sum(c.values())
    if n == 0:
        return 0.0
    return -sum((v / n) * math.log((v / n) + 1e-12) for v in c.values())


def hist(values: list[float], bins: list[float]) -> np.ndarray:
    arr = np.histogram(values, bins=bins)[0].astype(float)
    s = arr.sum()
    return arr / s if s > 0 else arr


def kl(p: np.ndarray, q: np.ndarray) -> float:
    eps = 1e-9
    pp = p + eps
    qq = q + eps
    return float(np.sum(pp * np.log(pp / qq)))


def feature_profile(windows: list[Window]) -> dict[str, object]:
    xs = [w.x for w in windows]
    ys = [w.y for w in windows]
    cells = [w.cell_id for w in windows]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    dcent = sum(euclidean((w.x, w.y), (cx, cy)) for w in windows) / len(windows)
    return {
        "step_hist": hist(step_lengths(windows), [0, 25, 75, 150, 300, 600, 1200, 1e9]),
        "heading_hist": hist(heading_changes(windows), [0, 0.1, 0.4, 0.8, 1.6, 3.2]),
        "dist_centroid": dcent,
        "entropy": entropy(cells),
        "active_bins": len(set((w.timestamp // 3600) % 24 for w in windows)),
    }


def profile_distance(profile: dict[str, object], baseline: dict[str, object]) -> float:
    return (
        1.00 * kl(profile["step_hist"], baseline["step_hist"])
        + 0.60 * kl(profile["heading_hist"], baseline["heading_hist"])
        + 0.004 * abs(float(profile["dist_centroid"]) - float(baseline["dist_centroid"]))
        + 0.25 * abs(float(profile["entropy"]) - float(baseline["entropy"]))
        + 0.05 * abs(float(profile["active_bins"]) - float(baseline["active_bins"]))
    )


def build_behavior_model(
    traces: list[UserTrace],
    train_windows: int,
    eval_window: int,
    fpr_targets: list[float],
) -> tuple[dict[int, dict[str, object]], dict[float, float], list[float]]:
    baselines: dict[int, dict[str, object]] = {}
    benign_scores: list[float] = []

    for i, trace in enumerate(traces):
        if len(trace.windows) < train_windows + eval_window:
            base = trace.windows[: max(eval_window, min(len(trace.windows), train_windows))]
            val = base
        else:
            base = trace.windows[:train_windows]
            val = trace.windows[train_windows : train_windows + eval_window]
        baselines[i] = feature_profile(base)
        benign_scores.append(profile_distance(feature_profile(val), baselines[i]))

    thresholds = {}
    for fpr in fpr_targets:
        q = max(0.0, min(1.0, 1.0 - fpr))
        thresholds[fpr] = float(np.quantile(benign_scores, q))
    return baselines, thresholds, benign_scores


def behavior_flags(
    user_idx: int,
    windows: list[Window],
    baseline: dict[str, object],
    threshold: float,
    eval_window: int,
    consecutive_m: int,
) -> list[bool]:
    flags = []
    recent = deque(maxlen=consecutive_m)
    for r in range(len(windows)):
        lo = max(0, r - eval_window + 1)
        segment = windows[lo : r + 1]
        if len(segment) < max(3, min(eval_window, 3)):
            score_flag = False
        else:
            score_flag = profile_distance(feature_profile(segment), baseline) > threshold
        recent.append(score_flag)
        flags.append(len(recent) == consecutive_m and all(recent))
    return flags


def top_rank(histogram: Counter, cell: int) -> int:
    count = histogram.get(cell, 0)
    better = sum(1 for _, v in histogram.items() if v > count)
    return better + 1


def l1_bias(pred: Counter, gt: Counter) -> float:
    keys = set(pred) | set(gt)
    return float(sum(abs(pred.get(k, 0.0) - gt.get(k, 0.0)) for k in keys))


def run_condition(
    name: str,
    traces: list[UserTrace],
    malicious_flags: list[bool],
    target_cell: int,
    rounds: int,
    offset: int,
    verified_genesis: bool,
    use_behavior: bool,
    baselines: dict[int, dict[str, object]],
    behavior_threshold: float,
    behavior_window: int,
    consecutive_m: int,
    max_step_m: float,
) -> dict[str, object]:
    gt = Counter()
    pred = Counter()
    accepted_malicious = 0
    total_malicious = 0
    target_seen_round = None
    attack_flags = 0
    benign_flags = 0
    total_benign = 0
    total_attack_windows = 0

    attack_cache: dict[int, list[Window]] = {}
    flag_cache: dict[int, list[bool]] = {}

    for i, trace in enumerate(traces):
        if malicious_flags[i]:
            attack_cache[i] = make_attack_trace(trace, target_cell, rounds, verified_genesis, max_step_m)
            if use_behavior:
                flag_cache[i] = behavior_flags(
                    i, attack_cache[i], baselines[i], behavior_threshold, behavior_window, consecutive_m
                )
            else:
                flag_cache[i] = [False] * rounds

    for r in range(rounds):
        round_pred = Counter()
        for i, trace in enumerate(traces):
            real_w = prefix_windows(trace, offset, rounds)[r]
            gt[real_w.cell_id] += 1
            if malicious_flags[i]:
                total_malicious += 1
                total_attack_windows += 1
                attack_w = attack_cache[i][r]
                if flag_cache[i][r]:
                    attack_flags += 1
                    continue
                accepted_malicious += 1
                round_pred[attack_w.cell_id] += 1
                if attack_w.cell_id == target_cell and target_seen_round is None:
                    target_seen_round = r + 1
            else:
                total_benign += 1
                if use_behavior:
                    benign_seq = prefix_windows(trace, offset, rounds)
                    benign_flag = behavior_flags(
                        i, benign_seq, baselines[i], behavior_threshold, behavior_window, consecutive_m
                    )[r]
                    if benign_flag:
                        benign_flags += 1
                        continue
                round_pred[real_w.cell_id] += 1
        pred.update(round_pred)

    gt_rank = top_rank(gt, target_cell)
    pred_rank = top_rank(pred, target_cell)
    gt_count = gt.get(target_cell, 0)
    pred_count = pred.get(target_cell, 0)
    base_bias = l1_bias(gt, gt)
    bias = l1_bias(pred, gt)

    return {
        "config": name,
        "target_cell": target_cell,
        "target_gt_count": gt_count,
        "target_pred_count": pred_count,
        "target_count_lift": pred_count - gt_count,
        "target_gt_rank": gt_rank,
        "target_pred_rank": pred_rank,
        "target_rank_lift": gt_rank - pred_rank,
        "time_to_target_rounds": target_seen_round if target_seen_round is not None else "",
        "accepted_malicious_reports": accepted_malicious,
        "total_malicious_reports": total_malicious,
        "accepted_malicious_mass": accepted_malicious / total_malicious if total_malicious else 0.0,
        "behavioral_tpr": attack_flags / total_attack_windows if total_attack_windows else 0.0,
        "benign_frr": benign_flags / total_benign if total_benign else 0.0,
        "bias_l1": bias,
        "base_bias_l1": base_bias,
    }


def write_summary(rows: list[dict[str, object]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, object]], out: Path, fpr: float, threshold: float) -> None:
    by_name = {r["config"]: r for r in rows}
    tsip = by_name["tsip_only"]
    combined = by_name["tsip_external"]
    mass_reduction = 1.0 - (
        float(combined["accepted_malicious_reports"]) / max(1.0, float(tsip["accepted_malicious_reports"]))
    )
    bias_reduction = 1.0 - (float(combined["bias_l1"]) / max(1e-9, float(tsip["bias_l1"])))

    lines = [
        "# External Layer Sensitivity Study",
        "",
        f"- Behavioral threshold calibrated at benign FPR target `{fpr:.0%}`: `{threshold:.6f}`.",
        f"- Attack mass reduction vs TSIP-only: `{mass_reduction:.4f}`.",
        f"- Heatmap L1 bias reduction vs TSIP-only: `{bias_reduction:.4f}`.",
        "",
        "| config | time-to-target | TargetCountLift | TargetRankLift | accepted malicious mass | Behavioral TPR | Benign FRR | Bias_L1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['config']} | {r['time_to_target_rounds']} | "
            f"{float(r['target_count_lift']):.0f} | {float(r['target_rank_lift']):.0f} | "
            f"{float(r['accepted_malicious_mass']):.4f} | {float(r['behavioral_tpr']):.4f} | "
            f"{float(r['benign_frr']):.4f} | {float(r['bias_l1']):.0f} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot(rows: list[dict[str, object]], out: Path) -> None:
    import matplotlib.pyplot as plt

    labels = [str(r["config"]).replace("_", "\n") for r in rows]
    mass = [float(r["accepted_malicious_mass"]) for r in rows]
    bias = [float(r["bias_l1"]) for r in rows]
    lift = [float(r["target_count_lift"]) for r in rows]

    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.2))
    axes[0].bar(labels, mass, color=["#777777", "#4C78A8", "#72B7B2", "#54A24B"])
    axes[0].set_title("Accepted malicious mass")
    axes[0].set_ylim(0, 1.05)
    axes[0].set_ylabel("fraction")

    axes[1].bar(labels, lift, color=["#777777", "#4C78A8", "#72B7B2", "#54A24B"])
    axes[1].set_title("TargetCountLift")
    axes[1].set_ylabel("reports")

    axes[2].bar(labels, bias, color=["#777777", "#4C78A8", "#72B7B2", "#54A24B"])
    axes[2].set_title("Bias_L1")
    axes[2].set_ylabel("L1 distance")

    for ax in axes:
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="x", labelsize=8)

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--traj", type=Path, default=Path("experiments/geolife_tsip_ready_50u.jsonl"))
    p.add_argument("--n-users", type=int, default=50)
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--malicious-rate", type=float, default=0.20)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--offset", type=int, default=32)
    p.add_argument("--train-windows", type=int, default=20)
    p.add_argument("--behavior-window", type=int, default=8)
    p.add_argument("--behavior-fpr", type=float, default=0.05, choices=[0.01, 0.05])
    p.add_argument("--consecutive-m", type=int, default=2)
    p.add_argument("--max-step-m", type=float, default=150.0)
    p.add_argument("--out-dir", type=Path, default=Path("experiments/external_layer"))
    p.add_argument("--tag", default="")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    traces = load_traces(args.traj, args.n_users)
    if not traces:
        raise SystemExit(f"no traces loaded from {args.traj}")

    malicious_flags = [
        stable_is_malicious(i, args.malicious_rate, args.seed)
        for i in range(len(traces))
    ]
    if not any(malicious_flags):
        malicious_flags[0] = True

    target_cell = choose_cold_target(traces, malicious_flags, args.rounds, args.offset, args.seed)
    baselines, thresholds, benign_scores = build_behavior_model(
        traces,
        train_windows=args.train_windows,
        eval_window=args.behavior_window,
        fpr_targets=[0.01, 0.05],
    )
    threshold = thresholds[args.behavior_fpr]

    configs = [
        ("no_integrity", False, False),
        ("tsip_only", False, False),
        ("external_only", True, True),
        ("tsip_external", True, True),
    ]
    rows = [
        run_condition(
            name=name,
            traces=traces,
            malicious_flags=malicious_flags,
            target_cell=target_cell,
            rounds=args.rounds,
            offset=args.offset,
            verified_genesis=verified_genesis,
            use_behavior=use_behavior,
            baselines=baselines,
            behavior_threshold=threshold,
            behavior_window=args.behavior_window,
            consecutive_m=args.consecutive_m,
            max_step_m=args.max_step_m,
        )
        for name, verified_genesis, use_behavior in configs
    ]

    suffix = args.tag or f"seed{args.seed}_fpr{int(args.behavior_fpr * 100)}"
    summary_csv = args.out_dir / f"external_layer_summary_{suffix}.csv"
    report_md = args.out_dir / f"external_layer_report_{suffix}.md"
    figure_png = args.out_dir / f"external_layer_sensitivity_{suffix}.png"

    write_summary(rows, summary_csv)
    write_markdown(rows, report_md, args.behavior_fpr, threshold)
    plot(rows, figure_png)

    print(f"[data] users={len(traces)} malicious={sum(malicious_flags)} target_cell={target_cell}")
    print(f"[behavior] threshold={threshold:.6f} benign_score_mean={np.mean(benign_scores):.6f}")
    print(f"[out] summary={summary_csv}")
    print(f"[out] report={report_md}")
    print(f"[out] figure={figure_png}")
    for r in rows:
        print(
            f"{r['config']:<14} accepted_mass={float(r['accepted_malicious_mass']):.3f} "
            f"tpr={float(r['behavioral_tpr']):.3f} frr={float(r['benign_frr']):.3f} "
            f"count_lift={float(r['target_count_lift']):.0f} "
            f"rank_lift={float(r['target_rank_lift']):.0f} bias_l1={float(r['bias_l1']):.0f}"
        )


if __name__ == "__main__":
    main()
