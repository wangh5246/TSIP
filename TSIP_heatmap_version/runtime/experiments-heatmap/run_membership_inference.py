#!/usr/bin/env python3
"""
Synthetic membership-inference attack from the TSIP Shuffler view.

Attack goal
-----------
Given only per-uid Shuffler-visible topology metadata, predict whether uid u
participated in target round t.

The synthetic trace deliberately exposes only metadata-style signals:
  - per-uid chain length and recent chain growth,
  - submission-time series summaries with network-delay ambiguity,
  - accept/reject history patterns.

The preferred classifier is sklearn.neural_network.MLPClassifier. If sklearn is
not installed, the script falls back to a small numpy logistic-regression
baseline and marks that downgrade in the output JSON.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - repository experiments use numpy.
    raise SystemExit(
        "numpy is required for this experiment; sklearn is optional."
    ) from exc


FEATURE_NAMES = [
    "chain_len_total",
    "chain_len_norm",
    "accepted_total",
    "rejected_total",
    "accept_rate",
    "reject_rate",
    "recent_count_1",
    "recent_count_2",
    "recent_count_4",
    "recent_accept_rate_4",
    "recent_reject_rate_4",
    "last_seen_age",
    "last_submit_phase",
    "mean_submit_phase",
    "std_submit_phase",
    "phase_entropy_4bin",
    "interarrival_mean",
    "interarrival_std",
    "interarrival_min",
    "interarrival_max",
    "accept_transition_rate",
    "last_accept",
    "tail_accept_streak",
    "tail_reject_streak",
]

FEATURE_GROUPS = {
    "full": FEATURE_NAMES,
    "topology": [
        "chain_len_total",
        "chain_len_norm",
        "recent_count_1",
        "recent_count_2",
        "recent_count_4",
        "last_seen_age",
    ],
    "timing": [
        "last_seen_age",
        "last_submit_phase",
        "mean_submit_phase",
        "std_submit_phase",
        "phase_entropy_4bin",
        "interarrival_mean",
        "interarrival_std",
        "interarrival_min",
        "interarrival_max",
    ],
    "outcomes": [
        "accepted_total",
        "rejected_total",
        "accept_rate",
        "reject_rate",
        "recent_accept_rate_4",
        "recent_reject_rate_4",
        "accept_transition_rate",
        "last_accept",
        "tail_accept_streak",
        "tail_reject_streak",
    ],
}

FEATURE_GROUPS["no_timing"] = [
    name for name in FEATURE_NAMES if name not in set(FEATURE_GROUPS["timing"])
]
FEATURE_GROUPS["no_outcomes"] = [
    name for name in FEATURE_NAMES if name not in set(FEATURE_GROUPS["outcomes"])
]


@dataclass(frozen=True)
class Submission:
    uid: int
    origin_round: int
    visible_time: float
    submit_phase: float
    accepted: int


@dataclass(frozen=True)
class SampleMeta:
    uid: int
    target_round: int


def sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-x))


def stable_logit(p: float) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def tail_streak(values: Sequence[int], target: int) -> int:
    n = 0
    for v in reversed(values):
        if int(v) != target:
            break
        n += 1
    return n


def phase_entropy(phases: np.ndarray) -> float:
    if phases.size == 0:
        return 0.0
    bins = np.minimum(3, np.floor(phases * 4.0).astype(int))
    counts = np.bincount(bins, minlength=4).astype(float)
    probs = counts[counts > 0] / counts.sum()
    return float(-np.sum(probs * np.log(probs)) / math.log(4.0))


def generate_synthetic_trace(
    n_users: int,
    n_rounds: int,
    seed: int,
    participation_rate: float,
    delay_mean: float,
    reject_rate: float,
) -> Tuple[np.ndarray, List[List[Submission]], Dict[str, float]]:
    """
    Generate latent participation and Shuffler-visible submissions.

    Each user has a stable activity propensity, a preferred submission phase,
    and a personal reliability. Network delay blurs the mapping between the
    true origin round and the time at which the Shuffler can see the metadata.
    """
    rng = np.random.default_rng(seed)
    base_logit = stable_logit(participation_rate)

    user_activity_logit = rng.normal(base_logit, 0.8, size=n_users)
    user_rhythm_phase = rng.uniform(0.0, 2.0 * math.pi, size=n_users)
    preferred_phase = rng.beta(2.2, 3.8, size=n_users)
    phase_jitter = rng.uniform(0.045, 0.14, size=n_users)
    user_reject_bias = rng.beta(1.5, 30.0, size=n_users)

    participated = np.zeros((n_users, n_rounds), dtype=np.int8)
    submissions_by_uid: List[List[Submission]] = [[] for _ in range(n_users)]
    prev = rng.random(n_users) < participation_rate

    for r in range(n_rounds):
        rhythm = 0.35 * np.sin((2.0 * math.pi * r / max(6, n_rounds)) + user_rhythm_phase)
        persistence = 0.75 * (prev.astype(float) - 0.5)
        p = sigmoid(user_activity_logit + rhythm + persistence)
        active = rng.random(n_users) < p
        participated[:, r] = active.astype(np.int8)
        prev = active

        active_uids = np.flatnonzero(active)
        if active_uids.size == 0:
            continue

        local_phase = np.clip(
            rng.normal(preferred_phase[active_uids], phase_jitter[active_uids]),
            0.0,
            0.999,
        )
        delay = rng.exponential(delay_mean, size=active_uids.size)
        visible_time = r + local_phase + delay
        per_user_reject = reject_rate + user_reject_bias[active_uids]
        # Late submissions have slightly higher rejection odds in this model.
        per_user_reject += 0.025 * (local_phase > 0.75)
        accepted = (rng.random(active_uids.size) >= np.clip(per_user_reject, 0.0, 0.45)).astype(np.int8)

        for uid, vt, phase, acc in zip(active_uids, visible_time, local_phase, accepted):
            submissions_by_uid[int(uid)].append(
                Submission(
                    uid=int(uid),
                    origin_round=int(r),
                    visible_time=float(vt),
                    submit_phase=float(phase),
                    accepted=int(acc),
                )
            )

    for subs in submissions_by_uid:
        subs.sort(key=lambda s: s.visible_time)

    stats = {
        "participation_rate_observed": float(participated.mean()),
        "avg_visible_submissions_per_user": float(
            np.mean([len(s) for s in submissions_by_uid]) if submissions_by_uid else 0.0
        ),
        "avg_delay_mean": float(delay_mean),
        "base_reject_rate": float(reject_rate),
    }
    return participated, submissions_by_uid, stats


def summarize_history(subs: Sequence[Submission], target_round: int, n_rounds: int) -> List[float]:
    cutoff = float(target_round + 1)
    hist = [s for s in subs if s.visible_time <= cutoff]
    chain_len = len(hist)
    if chain_len == 0:
        return [
            0.0,  # chain_len_total
            0.0,  # chain_len_norm
            0.0,  # accepted_total
            0.0,  # rejected_total
            0.0,  # accept_rate
            0.0,  # reject_rate
            0.0,  # recent_count_1
            0.0,  # recent_count_2
            0.0,  # recent_count_4
            0.0,  # recent_accept_rate_4
            0.0,  # recent_reject_rate_4
            float(n_rounds + 1),  # last_seen_age
            0.5,  # last_submit_phase
            0.5,  # mean_submit_phase
            0.0,  # std_submit_phase
            0.0,  # phase_entropy_4bin
            float(n_rounds + 1),  # interarrival_mean
            0.0,  # interarrival_std
            float(n_rounds + 1),  # interarrival_min
            float(n_rounds + 1),  # interarrival_max
            0.0,  # accept_transition_rate
            0.5,  # last_accept
            0.0,  # tail_accept_streak
            0.0,  # tail_reject_streak
        ]

    times = np.array([s.visible_time for s in hist], dtype=float)
    phases = np.array([s.submit_phase for s in hist], dtype=float)
    accepted = np.array([s.accepted for s in hist], dtype=np.int8)
    accepted_total = int(accepted.sum())
    rejected_total = int(chain_len - accepted_total)

    def recent(start_round: int) -> List[Submission]:
        start = float(max(0, start_round))
        return [s for s in hist if start <= s.visible_time <= cutoff]

    recent1 = recent(target_round)
    recent2 = recent(target_round - 1)
    recent4 = recent(target_round - 3)
    recent4_acc = np.array([s.accepted for s in recent4], dtype=np.int8)

    if times.size >= 2:
        gaps = np.diff(times)
        interarrival_mean = float(gaps.mean())
        interarrival_std = float(gaps.std())
        interarrival_min = float(gaps.min())
        interarrival_max = float(gaps.max())
        transitions = float(np.mean(np.diff(accepted) != 0))
    else:
        interarrival_mean = float(n_rounds + 1)
        interarrival_std = 0.0
        interarrival_min = float(n_rounds + 1)
        interarrival_max = float(n_rounds + 1)
        transitions = 0.0

    recent4_accept_rate = float(recent4_acc.mean()) if recent4_acc.size else 0.0
    recent4_reject_rate = 1.0 - recent4_accept_rate if recent4_acc.size else 0.0

    return [
        float(chain_len),
        float(chain_len / max(1, target_round + 1)),
        float(accepted_total),
        float(rejected_total),
        float(accepted_total / chain_len),
        float(rejected_total / chain_len),
        float(len(recent1)),
        float(len(recent2)),
        float(len(recent4)),
        recent4_accept_rate,
        recent4_reject_rate,
        float(cutoff - times[-1]),
        float(phases[-1]),
        float(phases.mean()),
        float(phases.std()),
        phase_entropy(phases),
        interarrival_mean,
        interarrival_std,
        interarrival_min,
        interarrival_max,
        transitions,
        float(accepted[-1]),
        float(tail_streak(accepted.tolist(), 1)),
        float(tail_streak(accepted.tolist(), 0)),
    ]


def build_dataset(
    participated: np.ndarray,
    submissions_by_uid: Sequence[Sequence[Submission]],
    warmup_rounds: int,
) -> Tuple[np.ndarray, np.ndarray, List[SampleMeta]]:
    n_users, n_rounds = participated.shape
    rows: List[List[float]] = []
    labels: List[int] = []
    metas: List[SampleMeta] = []

    for target_round in range(warmup_rounds, n_rounds):
        for uid in range(n_users):
            rows.append(summarize_history(submissions_by_uid[uid], target_round, n_rounds))
            labels.append(int(participated[uid, target_round]))
            metas.append(SampleMeta(uid=uid, target_round=target_round))

    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=np.int8), metas


def stratified_split(y: np.ndarray, seed: int, test_size: float) -> Tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed + 7919)
    train_parts = []
    test_parts = []
    for label in (0, 1):
        idx = np.flatnonzero(y == label)
        rng.shuffle(idx)
        n_test = max(1, int(round(idx.size * test_size)))
        n_test = min(max(1, n_test), max(1, idx.size - 1))
        test_parts.append(idx[:n_test])
        train_parts.append(idx[n_test:])

    train_idx = np.concatenate(train_parts)
    test_idx = np.concatenate(test_parts)
    rng.shuffle(train_idx)
    rng.shuffle(test_idx)
    return train_idx, test_idx


def auc_manual(y_true: np.ndarray, scores: np.ndarray) -> float:
    y = np.asarray(y_true, dtype=np.int8)
    s = np.asarray(scores, dtype=float)
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(s.size, dtype=float)
    i = 0
    while i < s.size:
        j = i + 1
        while j < s.size and s[order[j]] == s[order[i]]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        ranks[order[i:j]] = avg_rank
        i = j

    pos_rank_sum = float(ranks[y == 1].sum())
    return (pos_rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def fit_sklearn_mlp(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    seed: int,
    hidden_sizes: Tuple[int, ...],
    max_iter: int,
) -> Tuple[np.ndarray, Dict[str, object]]:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    import warnings

    warnings.filterwarnings("ignore", category=ConvergenceWarning)

    clf = make_pipeline(
        StandardScaler(),
        MLPClassifier(
            hidden_layer_sizes=hidden_sizes,
            activation="relu",
            solver="adam",
            alpha=1e-4,
            batch_size=min(128, max(16, x_train.shape[0])),
            learning_rate_init=1e-3,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=25,
            max_iter=max_iter,
            random_state=seed,
        ),
    )
    clf.fit(x_train, y_train)
    scores = clf.predict_proba(x_test)[:, 1]
    mlp = clf.named_steps["mlpclassifier"]
    info = {
        "backend": "sklearn_mlp",
        "hidden_layer_sizes": list(hidden_sizes),
        "max_iter": int(max_iter),
        "n_iter": int(getattr(mlp, "n_iter_", 0)),
        "loss": float(getattr(mlp, "loss_", float("nan"))),
        "fallback": False,
    }
    return scores, info


def fit_numpy_logistic(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    max_iter: int,
    lr: float = 0.05,
    l2: float = 1e-3,
) -> Tuple[np.ndarray, Dict[str, object]]:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std < 1e-8] = 1.0
    z_train = (x_train - mean) / std
    z_test = (x_test - mean) / std
    z_train = np.c_[np.ones(z_train.shape[0]), z_train]
    z_test = np.c_[np.ones(z_test.shape[0]), z_test]

    y = y_train.astype(float)
    w = np.zeros(z_train.shape[1], dtype=float)
    epochs = max(200, max_iter)
    for _ in range(epochs):
        p = sigmoid(z_train @ w)
        grad = z_train.T @ (p - y) / y.size
        grad[1:] += l2 * w[1:]
        w -= lr * grad

    scores = sigmoid(z_test @ w)
    eps = 1e-9
    train_scores = sigmoid(z_train @ w)
    loss = float(
        -np.mean(y * np.log(train_scores + eps) + (1.0 - y) * np.log(1.0 - train_scores + eps))
        + 0.5 * l2 * np.sum(w[1:] ** 2)
    )
    info = {
        "backend": "numpy_logistic",
        "hidden_layer_sizes": [],
        "max_iter": int(epochs),
        "loss": loss,
        "fallback": True,
        "fallback_reason": "sklearn import or MLP training unavailable",
    }
    return scores, info


def train_classifier(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    seed: int,
    hidden_sizes: Tuple[int, ...],
    max_iter: int,
) -> Tuple[np.ndarray, Dict[str, object]]:
    try:
        return fit_sklearn_mlp(x_train, y_train, x_test, seed, hidden_sizes, max_iter)
    except Exception as exc:
        scores, info = fit_numpy_logistic(x_train, y_train, x_test, max_iter=max_iter)
        info["fallback_exception"] = f"{type(exc).__name__}: {exc}"
        return scores, info


def threshold_metrics(y_true: np.ndarray, scores: np.ndarray, threshold: float = 0.5) -> Dict[str, float]:
    pred = scores >= threshold
    y = y_true.astype(bool)
    tp = float(np.sum(pred & y))
    fp = float(np.sum(pred & ~y))
    tn = float(np.sum(~pred & ~y))
    fn = float(np.sum(~pred & y))
    precision = float(tp / max(1.0, tp + fp))
    recall = float(tp / max(1.0, tp + fn))
    f1 = float(2.0 * precision * recall / max(1e-12, precision + recall))
    return {
        "accuracy_at_0_5": float((tp + tn) / max(1.0, tp + fp + tn + fn)),
        "precision_at_0_5": precision,
        "tpr_at_0_5": recall,
        "fpr_at_0_5": float(fp / max(1.0, fp + tn)),
        "f1_at_0_5": f1,
    }


def write_feature_summary(
    out_path: Path,
    x: np.ndarray,
    y: np.ndarray,
    feature_names: Sequence[str],
) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "feature",
                "member_mean",
                "member_std",
                "nonmember_mean",
                "nonmember_std",
                "mean_delta_member_minus_nonmember",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        member = x[y == 1]
        nonmember = x[y == 0]
        for j, name in enumerate(feature_names):
            m_mean = float(member[:, j].mean()) if member.size else 0.0
            n_mean = float(nonmember[:, j].mean()) if nonmember.size else 0.0
            writer.writerow(
                {
                    "feature": name,
                    "member_mean": f"{m_mean:.8f}",
                    "member_std": f"{float(member[:, j].std()) if member.size else 0.0:.8f}",
                    "nonmember_mean": f"{n_mean:.8f}",
                    "nonmember_std": f"{float(nonmember[:, j].std()) if nonmember.size else 0.0:.8f}",
                    "mean_delta_member_minus_nonmember": f"{(m_mean - n_mean):.8f}",
                }
            )


def write_predictions(
    out_path: Path,
    metas: Sequence[SampleMeta],
    y: np.ndarray,
    test_idx: np.ndarray,
    scores: np.ndarray,
) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["uid", "target_round", "label", "score"],
            lineterminator="\n",
        )
        writer.writeheader()
        for idx, score in zip(test_idx, scores):
            meta = metas[int(idx)]
            writer.writerow(
                {
                    "uid": meta.uid,
                    "target_round": meta.target_round,
                    "label": int(y[int(idx)]),
                    "score": f"{float(score):.8f}",
                }
            )


def write_readme(out_path: Path, result: Dict[str, object]) -> None:
    metrics = result["metrics"]
    model = result["model"]
    config = result["config"]
    text = f"""# Membership inference smoke output

This directory is generated by `experiments/run_membership_inference.py`.

## Threat model

The attacker observes Shuffler-visible per-uid topology metadata only: chain
lengths, delayed submission-time summaries, and accept/reject histories. The
label is whether the uid truly participated in target round `t` in the
synthetic trace.

## Current run

- users: {config["users"]}
- rounds: {config["rounds"]}
- seed: {config["seed"]}
- samples: {metrics["samples_total"]} total, {metrics["samples_test"]} test
- classifier: {model["backend"]}
- feature set: {config["feature_set"]}
- AUC: {metrics["auc"]:.6f}
- advantage: {metrics["advantage"]:.6f}
- accuracy@0.5: {metrics["accuracy_at_0_5"]:.6f}
- F1@0.5: {metrics["f1_at_0_5"]:.6f}

Artifacts:

- `metrics.json`: full run configuration and metrics.
- `feature_summary.csv`: feature means split by member/non-member labels.
- `test_predictions.csv`: held-out scores used for AUC.
"""
    out_path.write_text(text, encoding="utf-8")


def parse_hidden_sizes(value: str) -> Tuple[int, ...]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("hidden sizes cannot be empty")
    sizes = tuple(int(p) for p in parts)
    if any(s <= 0 for s in sizes):
        raise argparse.ArgumentTypeError("hidden sizes must be positive integers")
    return sizes


def select_feature_columns(x: np.ndarray, feature_set: str) -> Tuple[np.ndarray, List[str]]:
    selected_names = FEATURE_GROUPS[feature_set]
    name_to_index = {name: i for i, name in enumerate(FEATURE_NAMES)}
    selected_idx = [name_to_index[name] for name in selected_names]
    return x[:, selected_idx], list(selected_names)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a synthetic Shuffler-view membership-inference attack."
    )
    parser.add_argument("--users", type=int, default=500, help="Number of synthetic users.")
    parser.add_argument("--rounds", type=int, default=30, help="Number of synthetic rounds.")
    parser.add_argument("--seed", type=int, default=7, help="RNG seed.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("experiments/membership_inference"),
        help="Directory for metrics and CSV artifacts.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional metrics JSON path. Defaults to OUT_DIR/metrics.json.",
    )
    parser.add_argument(
        "--warmup-rounds",
        type=int,
        default=None,
        help="First target round to score. Defaults to min(5, rounds//5).",
    )
    parser.add_argument(
        "--participation-rate",
        type=float,
        default=0.48,
        help="Mean per-round user participation probability in the synthetic trace.",
    )
    parser.add_argument(
        "--delay-mean",
        type=float,
        default=0.35,
        help="Mean network/shuffler visibility delay measured in rounds.",
    )
    parser.add_argument(
        "--reject-rate",
        type=float,
        default=0.035,
        help="Base false-reject probability for generated submissions.",
    )
    parser.add_argument("--test-size", type=float, default=0.30, help="Held-out test fraction.")
    parser.add_argument(
        "--hidden-sizes",
        type=parse_hidden_sizes,
        default=(32, 16),
        help="Comma-separated MLP hidden layer sizes, e.g. 32,16.",
    )
    parser.add_argument(
        "--feature-set",
        choices=sorted(FEATURE_GROUPS.keys()),
        default="full",
        help="Subset of Shuffler-visible metadata features to expose to the attacker.",
    )
    parser.add_argument("--max-iter", type=int, default=500, help="MLP/logistic max iterations.")
    return parser.parse_args(argv)


def validate_args(args: argparse.Namespace) -> None:
    if args.users < 4:
        raise SystemExit("--users must be >= 4")
    if args.rounds < 4:
        raise SystemExit("--rounds must be >= 4")
    if not 0.01 <= args.participation_rate <= 0.99:
        raise SystemExit("--participation-rate must be in [0.01, 0.99]")
    if args.delay_mean < 0.0:
        raise SystemExit("--delay-mean must be >= 0")
    if not 0.0 <= args.reject_rate <= 0.45:
        raise SystemExit("--reject-rate must be in [0, 0.45]")
    if not 0.05 <= args.test_size <= 0.8:
        raise SystemExit("--test-size must be in [0.05, 0.8]")


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    validate_args(args)

    warmup_rounds = args.warmup_rounds
    if warmup_rounds is None:
        warmup_rounds = min(5, max(1, args.rounds // 5))
    warmup_rounds = max(1, min(int(warmup_rounds), args.rounds - 2))

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = args.json_out or (out_dir / "metrics.json")
    if not json_out.is_absolute():
        json_out = Path.cwd() / json_out
    json_out.parent.mkdir(parents=True, exist_ok=True)

    participated, submissions, trace_stats = generate_synthetic_trace(
        n_users=args.users,
        n_rounds=args.rounds,
        seed=args.seed,
        participation_rate=args.participation_rate,
        delay_mean=args.delay_mean,
        reject_rate=args.reject_rate,
    )
    x_all, y, metas = build_dataset(participated, submissions, warmup_rounds)
    x, feature_names = select_feature_columns(x_all, args.feature_set)
    if len(np.unique(y)) != 2:
        raise SystemExit("Synthetic dataset has only one class; adjust --participation-rate or --seed.")

    train_idx, test_idx = stratified_split(y, args.seed, args.test_size)
    scores, model_info = train_classifier(
        x[train_idx],
        y[train_idx],
        x[test_idx],
        seed=args.seed,
        hidden_sizes=args.hidden_sizes,
        max_iter=args.max_iter,
    )

    y_test = y[test_idx]
    auc = float(auc_manual(y_test, scores))
    advantage = float(2.0 * auc - 1.0)
    metrics: Dict[str, object] = {
        "auc": auc,
        "advantage": advantage,
        "samples_total": int(y.size),
        "samples_train": int(train_idx.size),
        "samples_test": int(test_idx.size),
        "positive_rate_total": float(y.mean()),
        "positive_rate_train": float(y[train_idx].mean()),
        "positive_rate_test": float(y_test.mean()),
    }
    metrics.update(threshold_metrics(y_test, scores))

    result: Dict[str, object] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "config": {
            "users": int(args.users),
            "rounds": int(args.rounds),
            "seed": int(args.seed),
            "warmup_rounds": int(warmup_rounds),
            "participation_rate": float(args.participation_rate),
            "delay_mean": float(args.delay_mean),
            "reject_rate": float(args.reject_rate),
            "test_size": float(args.test_size),
            "feature_set": args.feature_set,
            "synthetic_trace": True,
        },
        "trace_stats": trace_stats,
        "feature_names": feature_names,
        "all_feature_names": FEATURE_NAMES,
        "feature_groups": FEATURE_GROUPS,
        "model": model_info,
        "metrics": metrics,
    }

    json_out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    write_feature_summary(out_dir / "feature_summary.csv", x, y, feature_names)
    write_predictions(out_dir / "test_predictions.csv", metas, y, test_idx, scores)
    write_readme(out_dir / "README.md", result)

    print(
        "membership_inference "
        f"backend={model_info['backend']} "
        f"feature_set={args.feature_set} "
        f"users={args.users} rounds={args.rounds} seed={args.seed} "
        f"samples={y.size} test={test_idx.size} "
        f"auc={auc:.6f} advantage={advantage:.6f} "
        f"json={json_out}"
    )
    if model_info.get("fallback"):
        print(
            "[warn] sklearn MLP unavailable; used numpy logistic baseline",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
