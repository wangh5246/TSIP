#!/usr/bin/env python3
"""Run one S4 route/linkability attack with identity-disjoint metric training."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.eval_harness import HarnessParams, compute_bill, total_odometer_distance  # noqa: E402
from common.settlement import ReceiverFix, TariffTable  # noqa: E402
from waybill_formal.core import FormalError, canonical_json  # noqa: E402
from waybill_formal.s4_eligibility import (  # noqa: E402
    group_periods_by_identity,
    window_start_indices,
)
from waybill_formal.stage import (  # noqa: E402
    finish_stage,
    load_job_environment,
    load_prepared_manifest,
    prepared_dataset,
)


def _load_tariff(path: Path) -> TariffTable:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("tariff", payload)
    return TariffTable(
        tariff_version=int(raw["tariff_version"]),
        grid_w=int(raw["grid_w"]),
        cell_zones={int(key): int(value) for key, value in raw["cell_zones"].items()},
        zone_rates_cents_per_m={
            int(key): int(value) for key, value in raw["zone_rates_cents_per_m"].items()
        },
    )


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _hash_score(seed: int, *parts: str) -> float:
    digest = hashlib.sha256(f"{seed}|{'|'.join(parts)}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _opened_cells(cells: list[int], opening: float, seed: int, period_id: str) -> list[int]:
    count = int(math.ceil(len(cells) * opening))
    ranked = sorted(
        ((_hash_score(seed, period_id, str(index)), index) for index in range(len(cells)))
    )
    return sorted(cells[index] for _score, index in ranked[:count])


def _period_observation(
    raw: dict[str, Any],
    tariff: TariffTable,
    *,
    view: str,
    opening: float,
    seed: int,
) -> dict[str, Any]:
    fixes = [ReceiverFix.from_dict(item) for item in raw["fixes"]]
    cadence = int(raw.get("cadence_sec", 60))
    params = HarnessParams(cadence_sec=cadence)
    bill = compute_bill(fixes, tariff, params)
    distance = int(total_odometer_distance(fixes))
    fee = int(bill["total_fee_cents"])
    fallback = int(bill["fallback_intervals"])
    cells = [tariff.cell_index(fix.cell_x, fix.cell_y) for fix in fixes]
    observation: dict[str, Any] = {
        "period_duration_sec": int(fixes[-1].auth_gnss_time - fixes[0].auth_gnss_time),
        "interval_count": max(0, len(fixes) - 1),
    }
    if view in {"O0", "O1"}:
        observation["total_fee_cents"] = fee
        observation["total_distance_m"] = distance
    if view in {"O1", "O2", "O3"}:
        observation["fallback_indicator"] = int(fallback > 0)
        observation["fallback_intervals"] = fallback
    if view in {"O2", "O3"}:
        observation["distance_bucket_100m"] = distance // 100
        observation["amount_bucket_500c"] = fee // 500
    if view == "O3":
        observation["opened_cells"] = _opened_cells(
            cells,
            opening,
            seed,
            str(raw.get("period_id") or raw.get("trip_id")),
        )
    return observation


def _observation_fields(view: str) -> list[str]:
    if view not in {"O0", "O1", "O2", "O3"}:
        raise FormalError(f"unsupported S4 observation view: {view}")
    fields = ["interval_count", "period_duration_sec"]
    if view in {"O0", "O1"}:
        fields.extend(["total_distance_m", "total_fee_cents"])
    if view in {"O1", "O2", "O3"}:
        fields.extend(["fallback_indicator", "fallback_intervals"])
    if view in {"O2", "O3"}:
        fields.extend(["amount_bucket_500c", "distance_bucket_100m"])
    if view == "O3":
        fields.append("opened_cells")
    return sorted(fields)


def _numeric_vector(observations: list[dict[str, Any]], *, view: str) -> list[float]:
    fields = [field for field in _observation_fields(view) if field != "opened_cells"]
    vector: list[float] = []
    for field in fields:
        values = [float(row[field]) for row in observations if field in row]
        vector.extend(
            [
                statistics.mean(values) if values else 0.0,
                statistics.pstdev(values) if len(values) > 1 else 0.0,
            ]
        )
    return vector


def _sequence_rows(
    periods_path: Path,
    tariff: TariffTable,
    *,
    view: str,
    opening: float,
    horizon: int,
    seed: int,
    temporal_gap_periods: int = 1,
) -> list[dict[str, Any]]:
    if horizon < 1:
        raise FormalError("S4 horizon must be positive")
    if temporal_gap_periods < 1:
        raise FormalError("S4 temporal gap must be at least one period")
    try:
        by_identity = group_periods_by_identity(_records(periods_path))
    except ValueError as exc:
        raise FormalError(str(exc)) from exc
    sequences: list[dict[str, Any]] = []
    for identity, rows in sorted(by_identity.items()):
        rows.sort(
            key=lambda row: (
                int(row["fixes"][0]["auth_gnss_time"]),
                str(row.get("period_id") or row.get("trip_id")),
            )
        )
        starts = window_start_indices(
            len(rows), horizon=horizon, temporal_gap_periods=temporal_gap_periods
        )
        if len(starts) < 2:
            continue
        for start in starts:
            selected = rows[start : start + horizon]
            observations = [
                _period_observation(row, tariff, view=view, opening=opening, seed=seed)
                for row in selected
            ]
            opened = [
                int(cell)
                for observation in observations
                for cell in observation.get("opened_cells", [])
            ]
            sequences.append(
                {
                    "sequence_id": f"{identity}:{start}:{horizon}",
                    "identity": identity,
                    "vector": _numeric_vector(observations, view=view),
                    "opened_cells": sorted(set(opened)),
                    "period_ids": [
                        str(row.get("period_id") or row.get("trip_id")) for row in selected
                    ],
                    "window_start_index": start,
                    "window_end_index": start + horizon,
                    "temporal_gap_periods": temporal_gap_periods,
                }
            )
    return sequences


def _split_identities(
    identities: list[str],
    seed: int,
    *,
    target_train_fraction: float = 0.7,
    minimum_train_identities: int = 2,
    minimum_test_identities: int = 2,
) -> tuple[set[str], set[str]]:
    ranked = sorted(identities, key=lambda identity: _hash_score(seed, "split", identity))
    if len(ranked) < minimum_train_identities + minimum_test_identities:
        raise FormalError("S4 requires at least four identities for a disjoint train/test split")
    # Keep the protocol's deterministic target while guaranteeing the declared
    # minimum train/test identity counts for the smallest valid split.
    cut = max(
        minimum_train_identities,
        min(
            len(ranked) - minimum_test_identities,
            int(round(target_train_fraction * len(ranked))),
        ),
    )
    return set(ranked[:cut]), set(ranked[cut:])


def _distance(left: list[float], right: list[float], weights: list[float] | None = None) -> float:
    if len(left) != len(right):
        raise FormalError("S4 feature length mismatch")
    active = weights or [1.0] * len(left)
    return math.sqrt(
        sum(weight * (a - b) ** 2 for a, b, weight in zip(left, right, active))
    )


def _learn_weights(rows: list[dict[str, Any]]) -> list[float]:
    if not rows:
        raise FormalError("S4 supervised linker has no training sequences")
    dimension = len(rows[0]["vector"])
    by_identity: dict[str, list[list[float]]] = defaultdict(list)
    for row in rows:
        by_identity[row["identity"]].append(row["vector"])
    weights: list[float] = []
    for index in range(dimension):
        within: list[float] = []
        means: list[float] = []
        for vectors in by_identity.values():
            values = [vector[index] for vector in vectors]
            means.append(statistics.mean(values))
            if len(values) > 1:
                within.append(statistics.pvariance(values))
        between = statistics.pvariance(means) if len(means) > 1 else 0.0
        within_mean = statistics.mean(within) if within else 0.0
        weights.append((between + 1e-9) / (within_mean + 1e-9))
    scale = statistics.mean(weights) or 1.0
    return [min(1000.0, weight / scale) for weight in weights]


def _cell_jaccard(left: list[int], right: list[int]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _score(
    query: dict[str, Any],
    gallery: dict[str, Any],
    *,
    attacker: str,
    seed: int,
    weights: list[float] | None,
) -> float:
    if attacker == "random-majority":
        return _hash_score(seed, query["sequence_id"], gallery["sequence_id"])
    numeric = -_distance(query["vector"], gallery["vector"], weights)
    if attacker == "nearest-route":
        return numeric + 10.0 * _cell_jaccard(query["opened_cells"], gallery["opened_cells"])
    if attacker == "supervised-linker":
        return numeric + 20.0 * _cell_jaccard(query["opened_cells"], gallery["opened_cells"])
    raise FormalError(f"unsupported S4 attacker: {attacker}")


def _auc(positive: list[float], negative: list[float]) -> float:
    if not positive or not negative:
        raise FormalError("S4 AUC requires positive and negative pairs")
    wins = 0.0
    for pos in positive:
        for neg in negative:
            wins += 1.0 if pos > neg else 0.5 if pos == neg else 0.0
    return wins / (len(positive) * len(negative))


def identity_cluster_bootstrap(
    rows: list[dict[str, Any]], *, replicates: int, seed: int
) -> dict[str, Any]:
    """Bootstrap macro attack metrics over original test identities."""

    if replicates <= 0:
        raise ValueError("S4 bootstrap replicates must be positive")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["true_identity"])].append(row)
    identities = sorted(grouped)
    if not identities:
        raise ValueError("S4 bootstrap requires at least one test identity")
    identity_metrics = {
        identity: {
            "top1_accuracy": statistics.fmean(
                float(row["correct_top1"]) for row in grouped[identity]
            ),
            "top5_accuracy": statistics.fmean(
                float(row["correct_top5"]) for row in grouped[identity]
            ),
            "linkability_auc": statistics.fmean(
                float(row["query_auc"]) for row in grouped[identity]
            ),
        }
        for identity in identities
    }
    metrics = ("top1_accuracy", "top5_accuracy", "linkability_auc")
    distributions: dict[str, list[float]] = {metric: [] for metric in metrics}
    rng = random.Random(int(seed))
    for _ in range(replicates):
        selected = [rng.choice(identities) for _ in identities]
        for metric in metrics:
            distributions[metric].append(
                statistics.fmean(identity_metrics[identity][metric] for identity in selected)
            )
    return {
        "cluster_unit": "original vehicle or user",
        "clusters": len(identities),
        "replicates": int(replicates),
        "confidence_interval": "percentile identity-cluster bootstrap 95%",
        "metrics": {
            metric: {
                "macro_estimate": statistics.fmean(
                    identity_metrics[identity][metric] for identity in identities
                ),
                "ci95_lower": _percentile(distributions[metric], 2.5),
                "ci95_upper": _percentile(distributions[metric], 97.5),
            }
            for metric in metrics
        },
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * float(percentile) / 100.0
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def main() -> int:
    job, attempt_dir, run_root = load_job_environment()
    if job.get("stage") != "S4" or job.get("kind") != "privacy-attack":
        raise FormalError("S4 runner received an unsupported job")
    parameters = dict(job["parameters"])
    manifest = load_prepared_manifest(run_root)
    eligibility = manifest.get("s4_eligibility")
    expected_eligibility_sha256 = parameters.get("s4_eligibility_matrix_sha256")
    if expected_eligibility_sha256 is not None:
        if not isinstance(eligibility, dict) or (
            eligibility.get("matrix_sha256") != expected_eligibility_sha256
        ):
            raise FormalError(
                "S4 job eligibility matrix does not match the sealed prepared manifest"
            )
        matching_rows = [
            row
            for row in eligibility.get("rows", [])
            if isinstance(row, dict)
            and row.get("dataset") == parameters["dataset"]
            and int(row.get("horizon", 0)) == int(parameters["horizon"])
        ]
        if len(matching_rows) != 1 or matching_rows[0].get("status") != "eligible":
            raise FormalError("S4 plan scheduled a dataset/horizon that is not evaluable")
    dataset = prepared_dataset(manifest, str(parameters["dataset"]))
    periods_path = Path(dataset["periods_path"])
    tariff_path = Path(dataset["tariff_path"])
    tariff = _load_tariff(tariff_path)
    sequences = _sequence_rows(
        periods_path,
        tariff,
        view=str(parameters["view"]),
        opening=float(parameters["opening"]),
        horizon=int(parameters["horizon"]),
        seed=int(parameters["seed"]),
        temporal_gap_periods=int(parameters.get("temporal_gap_periods", 1)),
    )
    identities = sorted({row["identity"] for row in sequences})
    minimum_sequence_identities = int(parameters.get("minimum_sequence_identities", 4))
    if len(identities) < minimum_sequence_identities:
        raise FormalError("S4 requires at least four identities for a disjoint train/test split")
    split_policy = parameters.get("split_policy", {})
    train_ids, test_ids = _split_identities(
        identities,
        int(parameters["seed"]),
        target_train_fraction=float(split_policy.get("target_train_fraction", 0.7)),
        minimum_train_identities=int(split_policy.get("minimum_train_identities", 2)),
        minimum_test_identities=int(split_policy.get("minimum_test_identities", 2)),
    )
    train = [row for row in sequences if row["identity"] in train_ids]
    test_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sequences:
        if row["identity"] in test_ids:
            test_by_identity[row["identity"]].append(row)
    gallery = [sorted(rows, key=lambda row: row["sequence_id"])[0] for rows in test_by_identity.values()]
    queries = [
        row
        for rows in test_by_identity.values()
        for row in sorted(rows, key=lambda row: row["sequence_id"])[1:]
    ]
    if len(gallery) < 2 or not queries:
        raise FormalError("S4 test identities need one gallery and at least one query sequence each")
    gallery_by_identity = {row["identity"]: row for row in gallery}
    overlap_checks: list[dict[str, Any]] = []
    for query in queries:
        gallery_row = gallery_by_identity[query["identity"]]
        overlap = sorted(set(gallery_row["period_ids"]) & set(query["period_ids"]))
        if overlap:
            raise FormalError("S4 gallery/query windows share periods")
        actual_gap = int(query["window_start_index"]) - int(gallery_row["window_end_index"])
        if actual_gap < int(parameters.get("temporal_gap_periods", 1)):
            raise FormalError("S4 gallery/query temporal gap is below the frozen minimum")
        overlap_checks.append(
            {
                "identity": query["identity"],
                "gallery_sequence_id": gallery_row["sequence_id"],
                "query_sequence_id": query["sequence_id"],
                "shared_periods": overlap,
                "temporal_gap_periods": actual_gap,
            }
        )
    attacker = str(parameters["attacker"])
    weights = _learn_weights(train) if attacker == "supervised-linker" else None
    top1 = 0
    top5 = 0
    positive: list[float] = []
    negative: list[float] = []
    rows: list[dict[str, Any]] = []
    for query in queries:
        scored = [
            (
                _score(
                    query,
                    candidate,
                    attacker=attacker,
                    seed=int(parameters["seed"]),
                    weights=weights,
                ),
                candidate,
            )
            for candidate in gallery
        ]
        ranked = sorted(scored, key=lambda item: (-item[0], item[1]["sequence_id"]))
        predictions = [candidate["identity"] for _score_value, candidate in ranked]
        top1 += int(predictions[0] == query["identity"])
        top5 += int(query["identity"] in predictions[:5])
        for score_value, candidate in scored:
            if candidate["identity"] == query["identity"]:
                positive.append(score_value)
            else:
                negative.append(score_value)
        positive_score = next(
            score_value
            for score_value, candidate in scored
            if candidate["identity"] == query["identity"]
        )
        query_negative = [
            score_value
            for score_value, candidate in scored
            if candidate["identity"] != query["identity"]
        ]
        rows.append(
            {
                "query_id": query["sequence_id"],
                "true_identity": query["identity"],
                "top1_identity": predictions[0],
                "top5_identities": predictions[:5],
                "correct_top1": predictions[0] == query["identity"],
                "correct_top5": query["identity"] in predictions[:5],
                "query_auc": _auc([positive_score], query_negative),
            }
        )
    output_path = attempt_dir / "query-results.jsonl"
    with output_path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    observation_fields = _observation_fields(str(parameters["view"]))
    exact_fields = {"total_fee_cents", "total_distance_m"}
    if str(parameters["view"]) in {"O2", "O3"} and exact_fields & set(observation_fields):
        raise FormalError("bucketed S4 views must not contain exact fee or distance")
    schema_sha256 = hashlib.sha256(canonical_json(observation_fields).encode()).hexdigest()
    bootstrap = identity_cluster_bootstrap(
        rows,
        replicates=int(parameters.get("bootstrap_replicates", 5_000)),
        seed=int(parameters["seed"]),
    )
    result = {
        "status": "passed",
        "dataset": parameters["dataset"],
        "view": parameters["view"],
        "opening": parameters["opening"],
        "horizon": parameters["horizon"],
        "attacker": attacker,
        "seed": parameters["seed"],
        "split": parameters["split"],
        "train_identities": len(train_ids),
        "test_identities": len(test_ids),
        "gallery_sequences": len(gallery),
        "query_sequences": len(queries),
        "temporal_gap_periods": int(parameters.get("temporal_gap_periods", 1)),
        "gallery_query_shared_periods": 0,
        "overlap_checks": overlap_checks,
        "top1_accuracy": top1 / len(queries),
        "top5_accuracy": top5 / len(queries),
        "linkability_auc": _auc(positive, negative),
        "cluster_bootstrap": bootstrap,
        "observation_manifest": {
            "fields": observation_fields,
            "schema_sha256": schema_sha256,
            "mutually_exclusive_exact_and_bucketed": not bool(
                exact_fields & set(observation_fields)
            )
            if str(parameters["view"]) in {"O2", "O3"}
            else True,
            "source": "derived from the current WayBill period/public-statement implementation",
        },
        "learned_weights": weights,
        "output": output_path.name,
        "claim_rule": "attack success triggers claim downgrade; there is no privacy pass threshold",
    }
    finish_stage(job=job, attempt_dir=attempt_dir, payload=result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
