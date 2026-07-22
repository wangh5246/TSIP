#!/usr/bin/env python3
"""Real-trace Shuffler-metadata leakage tasks for TSIP.

The script uses TSIP-ready heatmap JSONL traces, but the attacker
features are restricted to Shuffler-visible metadata: user/chain activity,
timing slots, inter-arrival summaries, chain length, and accept/reject outcomes.
It never uses raw coordinates, primary cells, payload values, or cell IDs as
features.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from run_membership_inference import (  # noqa: E402
    FEATURE_GROUPS,
    Submission,
    auc_manual,
    build_dataset,
    phase_entropy,
    select_feature_columns,
    stratified_split,
    threshold_metrics,
    train_classifier,
)


@dataclass(frozen=True)
class RealTrace:
    dataset: str
    records: List[Dict[str, object]]
    selected_bins: List[int]
    participated: np.ndarray
    submissions_by_uid: List[List[Submission]]


def read_records(path: Path, max_users: int) -> List[Dict[str, object]]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if len(records) >= max_users:
                break
    if len(records) < 4:
        raise SystemExit(f"need at least 4 users in {path}")
    return records


def timing_bin(window: Dict[str, object], *, mode: str, time_bin_sec: int) -> int:
    if mode in {"timestamp", "auto"} and "timestamp" in window:
        try:
            return int(window["timestamp"]) // max(1, int(time_bin_sec))
        except Exception:
            if mode == "timestamp":
                raise
    return int(window["window_id"])


def select_dense_bins(
    records: Sequence[Dict[str, object]],
    rounds: int,
    *,
    bin_mode: str,
    time_bin_sec: int,
) -> List[int]:
    counts: Dict[int, int] = {}
    for rec in records:
        for window in rec.get("windows", []):
            wid = timing_bin(window, mode=bin_mode, time_bin_sec=time_bin_sec)
            counts[wid] = counts.get(wid, 0) + 1
    if not counts:
        raise SystemExit("trace has no windows")
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    selected = sorted(wid for wid, _ in ranked[: min(rounds, len(ranked))])
    if len(selected) < 6:
        raise SystemExit("not enough selected timing bins for metadata task")
    return selected


def day_phase(timestamp: object) -> float:
    try:
        ts = int(timestamp)
    except Exception:
        return 0.5
    return float((ts % 86400) / 86400.0)


def build_real_trace(
    dataset: str,
    path: Path,
    users: int,
    rounds: int,
    seed: int,
    delay_mean: float,
    reject_rate: float,
    bin_mode: str,
    time_bin_sec: int,
) -> RealTrace:
    rng = np.random.default_rng(seed)
    records = read_records(path, users)
    selected_bins = select_dense_bins(records, rounds, bin_mode=bin_mode, time_bin_sec=time_bin_sec)
    bin_to_round = {wid: i for i, wid in enumerate(selected_bins)}
    participated = np.zeros((len(records), len(selected_bins)), dtype=np.int8)
    submissions_by_uid: List[List[Submission]] = [[] for _ in records]

    for uid, rec in enumerate(records):
        for window in rec.get("windows", []):
            wid = timing_bin(window, mode=bin_mode, time_bin_sec=time_bin_sec)
            if wid not in bin_to_round:
                continue
            r = bin_to_round[wid]
            phase = day_phase(window.get("timestamp"))
            participated[uid, r] = 1
            visible_time = float(r) + float(rng.exponential(delay_mean))
            accepted = int(rng.random() >= reject_rate)
            submissions_by_uid[uid].append(
                Submission(
                    uid=uid,
                    origin_round=r,
                    visible_time=visible_time,
                    submit_phase=phase,
                    accepted=accepted,
                )
            )
    for subs in submissions_by_uid:
        subs.sort(key=lambda s: s.visible_time)

    if len(np.unique(participated)) != 2:
        raise SystemExit(
            f"{dataset} selected bins produce one-class activity labels; "
            "increase --rounds or use another trace"
        )
    return RealTrace(dataset, records, selected_bins, participated, submissions_by_uid)


def fit_and_score(
    x: np.ndarray,
    y: np.ndarray,
    seed: int,
    hidden_sizes: Tuple[int, ...],
    max_iter: int,
    test_size: float,
) -> Tuple[Dict[str, float], Dict[str, object]]:
    if len(np.unique(y)) != 2:
        raise ValueError("need two classes")
    train_idx, test_idx = stratified_split(y, seed, test_size)
    scores, model_info = train_classifier(
        x[train_idx],
        y[train_idx],
        x[test_idx],
        seed=seed,
        hidden_sizes=hidden_sizes,
        max_iter=max_iter,
    )
    y_test = y[test_idx]
    metrics: Dict[str, float] = {
        "auc": float(auc_manual(y_test, scores)),
        "samples_total": float(y.size),
        "samples_test": float(test_idx.size),
        "positive_rate": float(y.mean()),
    }
    metrics.update(threshold_metrics(y_test, scores))
    return metrics, model_info


def run_active_period_task(
    trace: RealTrace,
    feature_set: str,
    warmup_rounds: int,
    seed: int,
    hidden_sizes: Tuple[int, ...],
    max_iter: int,
    test_size: float,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    x_all, y, _ = build_dataset(trace.participated, trace.submissions_by_uid, warmup_rounds)
    x, feature_names = select_feature_columns(x_all, feature_set)
    metrics, model = fit_and_score(x, y, seed, hidden_sizes, max_iter, test_size)
    row = {
        "dataset": trace.dataset,
        "task": "active-period inference",
        "feature_set": feature_set,
        "auc": metrics["auc"],
        "accuracy": metrics["accuracy_at_0_5"],
        "f1": metrics["f1_at_0_5"],
        "positive_rate": metrics["positive_rate"],
        "samples": int(metrics["samples_total"]),
        "users": trace.participated.shape[0],
        "rounds": trace.participated.shape[1],
    }
    return row, {"metrics": metrics, "model": model, "features": feature_names}


def segment_features(active_rounds: Sequence[int], phases: Sequence[float], start: int, end: int) -> np.ndarray:
    idx = np.array([r for r in active_rounds if start <= r < end], dtype=float)
    ph = np.array(
        [p for r, p in zip(active_rounds, phases) if start <= r < end],
        dtype=float,
    )
    length = max(1, end - start)
    if idx.size == 0:
        return np.array([0.0, 0.0, 1.0, 1.0, 0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 0.0])
    norm_idx = (idx - start) / float(length)
    gaps = np.diff(idx) if idx.size >= 2 else np.array([], dtype=float)
    return np.array(
        [
            float(idx.size),
            float(idx.size / length),
            float(norm_idx.min()),
            float(norm_idx.max()),
            float(norm_idx.mean()),
            float(norm_idx.std()),
            float(gaps.mean() / length) if gaps.size else 1.0,
            float(gaps.std() / length) if gaps.size else 0.0,
            float(ph.mean()) if ph.size else 0.5,
            float(ph.std()) if ph.size else 0.0,
            phase_entropy(ph) if ph.size else 0.0,
        ],
        dtype=float,
    )


def user_segment_features(trace: RealTrace) -> List[Tuple[np.ndarray, np.ndarray]]:
    split = trace.participated.shape[1] // 2
    out = []
    for subs in trace.submissions_by_uid:
        active_rounds = [s.origin_round for s in subs]
        phases = [s.submit_phase for s in subs]
        left = segment_features(active_rounds, phases, 0, split)
        right = segment_features(active_rounds, phases, split, trace.participated.shape[1])
        out.append((left, right))
    return out


def pair_features(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.concatenate([np.abs(a - b), (a + b) / 2.0, a * b])


def split_user_ids(
    n_users: int,
    seed: int,
    test_size: float,
) -> Tuple[np.ndarray, np.ndarray]:
    if n_users < 4:
        raise ValueError("session linking needs at least four users")
    rng = np.random.default_rng(seed + 7919)
    users = np.arange(n_users, dtype=int)
    rng.shuffle(users)
    n_test = max(2, int(round(n_users * test_size)))
    n_test = min(n_test, n_users - 2)
    return users[n_test:], users[:n_test]


def build_session_pairs(
    segments: Sequence[Tuple[np.ndarray, np.ndarray]],
    user_ids: Sequence[int],
    seed: int,
) -> Tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    users = [int(uid) for uid in user_ids]
    if len(users) < 2:
        raise ValueError("session-pair partition needs at least two users")
    rows = []
    labels = []
    for uid in users:
        left, right = segments[uid]
        rows.append(pair_features(left, right))
        labels.append(1)
        other = rng.choice([candidate for candidate in users if candidate != uid])
        rows.append(pair_features(left, segments[other][1]))
        labels.append(0)
    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=np.int8)


def run_session_linkability_task(
    trace: RealTrace,
    seed: int,
    hidden_sizes: Tuple[int, ...],
    max_iter: int,
    test_size: float,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    segs = user_segment_features(trace)
    train_users, test_users = split_user_ids(len(segs), seed + 17, test_size)
    x_train, y_train = build_session_pairs(segs, train_users, seed + 1701)
    x_test, y_test = build_session_pairs(segs, test_users, seed + 2701)
    scores, model = train_classifier(
        x_train,
        y_train,
        x_test,
        seed=seed + 17,
        hidden_sizes=hidden_sizes,
        max_iter=max_iter,
    )
    metrics: Dict[str, float] = {
        "auc": float(auc_manual(y_test, scores)),
        "samples_total": float(y_train.size + y_test.size),
        "samples_train": float(y_train.size),
        "samples_test": float(y_test.size),
        "positive_rate": float(np.concatenate([y_train, y_test]).mean()),
    }
    metrics.update(threshold_metrics(y_test, scores))
    row = {
        "dataset": trace.dataset,
        "task": "session linkability",
        "feature_set": "timing+chain",
        "auc": metrics["auc"],
        "accuracy": metrics["accuracy_at_0_5"],
        "f1": metrics["f1_at_0_5"],
        "positive_rate": metrics["positive_rate"],
        "samples": int(metrics["samples_total"]),
        "users": trace.participated.shape[0],
        "rounds": trace.participated.shape[1],
    }
    return row, {
        "metrics": metrics,
        "model": model,
        "split": {
            "type": "user-disjoint",
            "train_users": int(train_users.size),
            "test_users": int(test_users.size),
            "train_samples": int(y_train.size),
            "test_samples": int(y_test.size),
            "test_size": float(test_size),
            "negative_pair_scope": "within-partition",
        },
    }


def mean_std(rows: Sequence[Dict[str, object]], dataset: str, task: str) -> Dict[str, object]:
    subset = [r for r in rows if r["dataset"] == dataset and r["task"] == task]
    if not subset:
        return {}
    out: Dict[str, object] = {
        "dataset": dataset,
        "task": task,
        "feature_set": subset[0]["feature_set"],
        "runs": len(subset),
        "users": subset[0]["users"],
        "rounds": subset[0]["rounds"],
    }
    for key in ("auc", "accuracy", "f1"):
        vals = np.array([float(r[key]) for r in subset], dtype=float)
        out[f"{key}_mean"] = float(vals.mean())
        out[f"{key}_std"] = float(vals.std(ddof=1)) if vals.size > 1 else 0.0
    return out


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_hidden_sizes(value: str) -> Tuple[int, ...]:
    sizes = tuple(int(p) for p in value.split(",") if p.strip())
    if not sizes:
        raise argparse.ArgumentTypeError("hidden sizes cannot be empty")
    return sizes


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--datasets", default="geolife,tdrive")
    p.add_argument(
        "--geolife",
        type=Path,
        default=Path("experiments-heatmap/geolife_tsip_ready_50u.jsonl"),
    )
    p.add_argument(
        "--tdrive",
        type=Path,
        default=Path("experiments-heatmap/tdrive_tsip_ready_50u.jsonl"),
    )
    p.add_argument("--porto", type=Path, default=None)
    p.add_argument("--rome", type=Path, default=None)
    p.add_argument("--synthetic", type=Path, default=None)
    p.add_argument("--users", type=int, default=50)
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--bin-mode", choices=["auto", "timestamp", "window_id"], default="timestamp")
    p.add_argument("--time-bin-sec", type=int, default=3600)
    p.add_argument("--seeds", nargs="+", type=int, default=[7, 11, 19])
    p.add_argument("--feature-set", choices=sorted(FEATURE_GROUPS.keys()), default="full")
    p.add_argument("--delay-mean", type=float, default=0.35)
    p.add_argument("--reject-rate", type=float, default=0.035)
    p.add_argument("--test-size", type=float, default=0.30)
    p.add_argument("--hidden-sizes", type=parse_hidden_sizes, default=(32, 16))
    p.add_argument("--max-iter", type=int, default=500)
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("experiments-heatmap/membership_inference/real_trace_metadata"),
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rows: List[Dict[str, object]] = []
    details: Dict[str, object] = {"runs": []}
    available = {
        "geolife": ("GeoLife", args.geolife),
        "tdrive": ("T-Drive", args.tdrive),
        "porto": ("Porto", args.porto),
        "rome": ("Rome", args.rome),
        "synthetic": ("Synthetic", args.synthetic),
    }
    dataset_keys = [x.strip() for x in args.datasets.split(",") if x.strip()]
    datasets = []
    for key in dataset_keys:
        if key not in available:
            raise SystemExit(f"unknown dataset: {key}")
        label, path = available[key]
        if path is None:
            raise SystemExit(f"dataset {key} requires --{key} PATH")
        datasets.append((label, path))
    for seed in args.seeds:
        for name, path in datasets:
            trace = build_real_trace(
                dataset=name,
                path=path,
                users=args.users,
                rounds=args.rounds,
                seed=seed,
                delay_mean=args.delay_mean,
                reject_rate=args.reject_rate,
                bin_mode=args.bin_mode,
                time_bin_sec=args.time_bin_sec,
            )
            warmup = min(5, max(1, trace.participated.shape[1] // 5))
            active_row, active_detail = run_active_period_task(
                trace,
                args.feature_set,
                warmup,
                seed,
                args.hidden_sizes,
                args.max_iter,
                args.test_size,
            )
            link_row, link_detail = run_session_linkability_task(
                trace,
                seed,
                args.hidden_sizes,
                args.max_iter,
                args.test_size,
            )
            active_row["seed"] = seed
            link_row["seed"] = seed
            rows.extend([active_row, link_row])
            details["runs"].append(
                {
                    "seed": seed,
                    "dataset": name,
                    "bin_mode": args.bin_mode,
                    "time_bin_sec": args.time_bin_sec,
                    "selected_bins": trace.selected_bins,
                    "active": active_detail,
                    "linkability": link_detail,
                }
            )

    summary = [
        mean_std(rows, dataset, task)
        for dataset, _ in datasets
        for task in ("session linkability", "active-period inference")
    ]
    summary = [r for r in summary if r]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "real_metadata_rows.csv", rows)
    write_csv(args.out_dir / "real_metadata_summary.csv", summary)
    (args.out_dir / "real_metadata_details.json").write_text(
        json.dumps(details, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for r in summary:
        print(
            f"{r['dataset']} {r['task']} "
            f"auc={r['auc_mean']:.3f}+/-{r['auc_std']:.3f} "
            f"acc={r['accuracy_mean']:.3f}+/-{r['accuracy_std']:.3f} "
            f"f1={r['f1_mean']:.3f}+/-{r['f1_std']:.3f}"
        )
    print(f"wrote {args.out_dir / 'real_metadata_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
