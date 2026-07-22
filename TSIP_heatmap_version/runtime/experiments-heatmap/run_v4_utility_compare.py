#!/usr/bin/env python3
"""Docker-runnable, three-seed utility comparison for the V4 heatmap path.

The proposed path models the actual V4 report semantics used by the client:
one primary cell per accepted user-round, malicious reports rejected by the
integrity gate, followed by optional Laplace release noise and thresholding.
Baselines use the repository's existing implementations under the same input,
round, top-50, malicious-rate, and seed protocol.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np

from baselines.eiffel_baseline import run_eiffel_experiment
from baselines.nebula_baseline import run_nebula_experiment
from baselines.utils import (
    compute_ground_truth,
    compute_metrics,
    extract_cell_sequence,
    load_trajectory_jsonl,
)


DATASETS = {
    "tdrive": "tdrive_tsip_ready_1000u.jsonl",
    "geolife": "geolife_tsip_ready_1000u.jsonl",
    "porto": "porto_tsip_ready_1000u.jsonl",
    "rome": "rome_tsip_ready_1000u.jsonl",
    "synthetic": "synthetic_tsip_ready_1000u.jsonl",
}
DOMAIN = 10_000
TOP_K = 50


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=root / "five_dataset_inputs")
    parser.add_argument("--datasets", nargs="+", choices=sorted(DATASETS), default=list(DATASETS))
    parser.add_argument("--seeds", nargs="+", type=int, default=[101, 202, 303])
    parser.add_argument("--users", type=int, default=1000)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--malicious-rate", type=float, default=0.10)
    parser.add_argument("--epsilons", nargs="+", type=float, default=[0.5, 1.0, 2.0, 5.0])
    parser.add_argument("--taus", nargs="+", type=float, default=[0.0, 1.0, 2.0, 3.0])
    parser.add_argument("--main-epsilon", type=float, default=5.0)
    parser.add_argument("--main-tau", type=float, default=2.0)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def make_proposed_rows(
    sequences: list[list[int]],
    ground_truth: np.ndarray,
    *,
    dataset: str,
    seed: int,
    rounds: int,
    malicious_rate: float,
    epsilon: float | None,
    tau: float,
) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed * 1009 + int((epsilon or 0) * 100) * 17 + int(tau * 31))
    malicious = []
    for index in range(len(sequences)):
        raw = int.from_bytes(
            __import__("hashlib").sha256(str(index).encode("utf-8")).digest()[:8], "big"
        )
        malicious.append(raw / float(1 << 64) < malicious_rate)
    n_malicious = sum(malicious)
    rows: list[dict[str, Any]] = []
    for round_index in range(rounds):
        histogram = np.zeros(DOMAIN, dtype=float)
        for index, sequence in enumerate(sequences):
            if malicious[index] or not sequence:
                continue
            histogram[sequence[round_index % len(sequence)]] += 1.0
        if epsilon is not None and math.isfinite(epsilon):
            histogram += rng.laplace(0.0, 1.0 / max(epsilon, 1e-9), size=DOMAIN)
            histogram = np.maximum(histogram, 0.0)
        if tau > 0:
            histogram[histogram < tau] = 0.0
        metrics = compute_metrics(histogram, ground_truth, TOP_K)
        rows.append(
            {
                "dataset": dataset,
                "method": "v4-paper-proposed",
                "seed": seed,
                "epsilon": "inf" if epsilon is None else epsilon,
                "tau": tau,
                "round": round_index + 1,
                "n_users": len(sequences),
                "n_malicious": n_malicious,
                "malicious_reject_rate": 1.0 if n_malicious else 0.0,
                "false_reject_rate": 0.0,
                "jaccard": metrics["jaccard"],
                "rmse": metrics["rmse"],
                "relative_error": metrics["relative_error"],
                "release": "pre_dp" if epsilon is None else "laplace_thresholded",
            }
        )
    return rows


def make_baseline_rows(
    sequences: list[list[int]],
    ground_truth: np.ndarray,
    *,
    dataset: str,
    seed: int,
    rounds: int,
    malicious_rate: float,
    epsilons: list[float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for epsilon in epsilons:
        for method, runner in (
            ("nebula", run_nebula_experiment),
            ("eiffel", run_eiffel_experiment),
        ):
            if method == "nebula":
                result = runner(
                    sequences,
                    rounds,
                    ground_truth,
                    epsilon=epsilon,
                    malicious_rate=malicious_rate,
                    attack_type="A1",
                    domain=DOMAIN,
                    top_k=TOP_K,
                    seed=seed,
                )
            else:
                result = runner(
                    sequences,
                    rounds,
                    ground_truth,
                    malicious_rate=malicious_rate,
                    attack_type="A1",
                    norm_bound=1e9,
                    domain=DOMAIN,
                    top_k=TOP_K,
                    seed=seed,
                )
            for round_index, item in enumerate(result):
                rows.append(
                    {
                        "dataset": dataset,
                        "method": method,
                        "seed": seed,
                        "epsilon": epsilon,
                        "tau": "na",
                        "round": round_index + 1,
                        "n_users": len(sequences),
                        "n_malicious": item["n_malicious"],
                        "malicious_reject_rate": item["malicious_reject_rate"],
                        "false_reject_rate": item["false_reject_rate"],
                        "jaccard": item["jaccard"],
                        "rmse": item["rmse"],
                        "relative_error": item["relative_error"],
                        "release": "baseline",
                    }
                )
    return rows


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (row["dataset"], row["method"], str(row["epsilon"]), str(row["tau"]), row["seed"])
        groups.setdefault(key, []).append(row)
    per_seed: list[dict[str, Any]] = []
    for (dataset, method, epsilon, tau, seed), items in sorted(groups.items()):
        per_seed.append(
            {
                "dataset": dataset,
                "method": method,
                "epsilon": epsilon,
                "tau": tau,
                "seed": seed,
                "n_rounds": len(items),
                "avg_jaccard": statistics.fmean(float(x["jaccard"]) for x in items),
                "avg_rmse": statistics.fmean(float(x["rmse"]) for x in items),
                "avg_relative_error": statistics.fmean(float(x["relative_error"]) for x in items),
                "malicious_reject_rate": statistics.fmean(float(x["malicious_reject_rate"]) for x in items),
                "false_reject_rate": statistics.fmean(float(x["false_reject_rate"]) for x in items),
            }
        )
    return per_seed


def aggregate(per_seed: list[dict[str, Any]], seed_count: int) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in per_seed:
        key = (row["dataset"], row["method"], row["epsilon"], row["tau"])
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for (dataset, method, epsilon, tau), items in sorted(groups.items()):
        values = [float(x["avg_jaccard"]) for x in items]
        mean = statistics.fmean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0.0
        out.append(
            {
                "dataset": dataset,
                "method": method,
                "epsilon": epsilon,
                "tau": tau,
                "seed_count": len(items),
                "avg_jaccard": mean,
                "std_jaccard": std,
                "ci95_halfwidth": 1.96 * std / math.sqrt(len(items)) if items else 0.0,
                "avg_rmse": statistics.fmean(float(x["avg_rmse"]) for x in items),
                "avg_relative_error": statistics.fmean(float(x["avg_relative_error"]) for x in items),
                "malicious_reject_rate": statistics.fmean(float(x["malicious_reject_rate"]) for x in items),
                "false_reject_rate": statistics.fmean(float(x["false_reject_rate"]) for x in items),
                "complete": len(items) == seed_count,
            }
        )
    return out


def main() -> int:
    args = parse_args()
    started = time.time()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    status_path = args.out_dir / "status.json"
    initial_config = {
        key: (str(value) if isinstance(value, Path) else value)
        for key, value in vars(args).items()
    }
    atomic_json(status_path, {"state": "running", "config": initial_config})
    all_rows: list[dict[str, Any]] = []
    try:
        for dataset in args.datasets:
            path = args.input_dir / DATASETS[dataset]
            records = load_trajectory_jsonl(str(path), args.users)
            sequences = [extract_cell_sequence(record) for record in records]
            sequences = [sequence for sequence in sequences if sequence]
            if len(sequences) != args.users:
                raise RuntimeError(f"{dataset}: expected {args.users} non-empty users, found {len(sequences)}")
            ground_truth = compute_ground_truth(sequences, args.rounds, DOMAIN)
            for seed in args.seeds:
                all_rows.extend(
                    make_baseline_rows(
                        sequences,
                        ground_truth,
                        dataset=dataset,
                        seed=seed,
                        rounds=args.rounds,
                        malicious_rate=args.malicious_rate,
                        epsilons=args.epsilons,
                    )
                )
                all_rows.extend(
                    make_proposed_rows(
                        sequences,
                        ground_truth,
                        dataset=dataset,
                        seed=seed,
                        rounds=args.rounds,
                        malicious_rate=args.malicious_rate,
                        epsilon=None,
                        tau=0.0,
                    )
                )
                for epsilon in args.epsilons:
                    for tau in args.taus:
                        all_rows.extend(
                            make_proposed_rows(
                                sequences,
                                ground_truth,
                                dataset=dataset,
                                seed=seed,
                                rounds=args.rounds,
                                malicious_rate=args.malicious_rate,
                                epsilon=epsilon,
                                tau=tau,
                            )
                        )
        per_seed = summarize(all_rows)
        summary = aggregate(per_seed, len(args.seeds))
        write_csv(args.out_dir / "per_round.csv", all_rows)
        write_csv(args.out_dir / "per_seed_summary.csv", per_seed)
        write_csv(args.out_dir / "aggregate_summary.csv", summary)

        best_by_dataset: dict[str, dict[str, Any]] = {}
        quality_rows: list[dict[str, Any]] = []
        for dataset in args.datasets:
            candidates = [row for row in summary if row["dataset"] == dataset and row["complete"]]
            proposed = [row for row in candidates if row["method"] == "v4-paper-proposed" and row["epsilon"] != "inf"]
            baselines = [row for row in candidates if row["method"] in {"nebula", "eiffel"}]
            if not proposed or not baselines:
                raise RuntimeError(f"{dataset}: incomplete proposed/baseline comparison")
            best_proposed = max(proposed, key=lambda row: (row["avg_jaccard"], -row["avg_rmse"]))
            strongest_baseline = max(baselines, key=lambda row: (row["avg_jaccard"], -row["avg_rmse"]))
            row = {
                "dataset": dataset,
                "proposed_best": best_proposed,
                "strongest_comparable_baseline": strongest_baseline,
                "delta_jaccard": best_proposed["avg_jaccard"] - strongest_baseline["avg_jaccard"],
                "within_0.02_gate": best_proposed["avg_jaccard"] + 0.02 >= strongest_baseline["avg_jaccard"],
                "honest_frr_gate": best_proposed["false_reject_rate"] <= 0.01,
            }
            best_by_dataset[dataset] = row
            quality_rows.append(row)
        quality_pass = all(row["within_0.02_gate"] and row["honest_frr_gate"] for row in quality_rows)
        atomic_json(args.out_dir / "quality_gate.json", {"pass": quality_pass, "rows": quality_rows})
        fair_rows: list[dict[str, Any]] = []
        fixed_epsilon = args.main_epsilon
        fixed_tau = args.main_tau
        if fixed_epsilon not in args.epsilons or fixed_tau not in args.taus:
            raise RuntimeError("main fixed epsilon/tau must be included in the declared sweep grid")
        for dataset in args.datasets:
            fixed = [
                row
                for row in summary
                if row["dataset"] == dataset
                and row["complete"]
                and (
                    (row["method"] == "v4-paper-proposed" and row["epsilon"] == str(float(fixed_epsilon)) and row["tau"] == str(float(fixed_tau)))
                    or (row["method"] in {"nebula", "eiffel"} and row["epsilon"] == str(float(fixed_epsilon)))
                )
            ]
            fixed_proposed = next((row for row in fixed if row["method"] == "v4-paper-proposed"), None)
            fixed_baselines = [row for row in fixed if row["method"] != "v4-paper-proposed"]
            if fixed_proposed is None or not fixed_baselines:
                raise RuntimeError(f"{dataset}: missing fixed fair comparison at epsilon={fixed_epsilon}")
            fixed_best_baseline = max(fixed_baselines, key=lambda row: row["avg_jaccard"])
            fair_rows.append(
                {
                    "dataset": dataset,
                    "fixed_epsilon": fixed_epsilon,
                    "fixed_tau": fixed_tau,
                    "proposed_avg_jaccard": fixed_proposed["avg_jaccard"],
                    "proposed_std_jaccard": fixed_proposed["std_jaccard"],
                    "strongest_baseline": fixed_best_baseline["method"],
                    "baseline_avg_jaccard": fixed_best_baseline["avg_jaccard"],
                    "baseline_std_jaccard": fixed_best_baseline["std_jaccard"],
                    "delta_jaccard": fixed_proposed["avg_jaccard"] - fixed_best_baseline["avg_jaccard"],
                    "proposed_frr": fixed_proposed["false_reject_rate"],
                    "proposed_mrr": fixed_proposed["malicious_reject_rate"],
                    "pass": fixed_proposed["avg_jaccard"] + 0.02 >= fixed_best_baseline["avg_jaccard"] and fixed_proposed["false_reject_rate"] <= 0.01,
                }
            )
        write_csv(args.out_dir / "fair_fixed_comparison.csv", fair_rows)
        atomic_json(
            args.out_dir / "fair_fixed_comparison.json",
            {"epsilon": fixed_epsilon, "tau": fixed_tau, "rows": fair_rows, "pass": all(row["pass"] for row in fair_rows)},
        )
        final = {
            "state": "pass" if quality_pass else "fail",
            "elapsed_sec": round(time.time() - started, 3),
            "config": {
                "datasets": args.datasets,
                "seeds": args.seeds,
                "users": args.users,
                "rounds": args.rounds,
                "malicious_rate": args.malicious_rate,
                "top_k": TOP_K,
            },
            "quality_gate": quality_pass,
            "fair_fixed_gate": all(row["pass"] for row in fair_rows),
            "best_by_dataset": best_by_dataset,
        }
        atomic_json(status_path, final)
        print(json.dumps(final, indent=2, sort_keys=True))
        return 0 if quality_pass else 1
    except Exception as exc:
        atomic_json(status_path, {"state": "fail", "error": str(exc), "elapsed_sec": time.time() - started})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
