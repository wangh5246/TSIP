#!/usr/bin/env python3
"""Execute one paired S1 fallback or odometer-sensitivity formal unit."""

from __future__ import annotations

import hashlib
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.settlement import ReceiverFix  # noqa: E402
from script.run_waybill_m1_v6_gate import (  # noqa: E402
    _edge_rows,
    _load_tariff,
    _percentile,
    _records,
    _scale_delta,
    deterministic_outage_edges,
    evaluate_mask,
)
from waybill_formal.core import FormalError, canonical_json  # noqa: E402
from waybill_formal.stage import (  # noqa: E402
    finish_stage,
    load_job_environment,
    load_prepared_manifest,
    prepared_dataset,
)


def burst_outage_edges(
    *,
    dataset: str,
    period_id: str,
    n_intervals: int,
    share: float,
    length_fixes: int,
    seed: int,
) -> list[int]:
    if n_intervals <= 0:
        return []
    burst_edges = max(1, int(length_fixes) - 1)
    target = max(1, int(math.ceil(n_intervals * float(share))))
    candidates: list[tuple[bytes, int]] = []
    for start in range(n_intervals):
        token = f"waybill-s1-burst-v1|{dataset}|{period_id}|{seed}|{length_fixes}|{start}"
        candidates.append((hashlib.sha256(token.encode()).digest(), start))
    selected: set[int] = set()
    for _score, start in sorted(candidates):
        selected.update(range(start, min(n_intervals, start + burst_edges)))
        if len(selected) >= target:
            break
    return sorted(selected)[:target]


def _natural_outage_edges(fixes: list[ReceiverFix]) -> list[int]:
    return [
        index
        for index, fix in enumerate(fixes[:-1])
        if fix.osnma_status != "authenticated"
    ]


def _outage(parameters: dict[str, Any], dataset: str, period_id: str, fixes: list[ReceiverFix]) -> list[int]:
    n_intervals = max(0, len(fixes) - 1)
    scenario = str(parameters["scenario"])
    if scenario == "natural":
        return _natural_outage_edges(fixes)
    if scenario == "independent":
        return deterministic_outage_edges(
            dataset=dataset,
            period_id=period_id,
            n_intervals=n_intervals,
            alpha=float(parameters["alpha"]),
            seed=int(parameters["seed"]),
        )
    if scenario == "burst":
        return burst_outage_edges(
            dataset=dataset,
            period_id=period_id,
            n_intervals=n_intervals,
            share=float(parameters["share"]),
            length_fixes=int(parameters["length_fixes"]),
            seed=int(parameters["seed"]),
        )
    raise FormalError(f"unsupported S1 scenario: {scenario}")


def _write_rows(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def cluster_bootstrap_summary(
    rows: list[dict[str, Any]],
    *,
    metrics: tuple[str, ...],
    percentiles: tuple[int, ...],
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    """Return deterministic cluster-bootstrap percentile confidence intervals."""

    if replicates <= 0:
        raise ValueError("bootstrap replicates must be positive")
    by_cluster: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_cluster.setdefault(str(row["cluster_id"]), []).append(row)
    cluster_ids = sorted(by_cluster)
    if not cluster_ids:
        raise ValueError("cluster bootstrap requires at least one cluster")
    samples: dict[str, dict[int, list[float]]] = {
        metric: {percentile: [] for percentile in percentiles} for metric in metrics
    }
    rng = random.Random(int(seed))
    for _ in range(replicates):
        selected = [rng.choice(cluster_ids) for _ in cluster_ids]
        replicate_rows = [row for cluster in selected for row in by_cluster[cluster]]
        for metric in metrics:
            values = [float(row[metric]) for row in replicate_rows]
            for percentile in percentiles:
                samples[metric][percentile].append(_percentile(values, percentile))
    result: dict[str, Any] = {}
    for metric in metrics:
        values = [float(row[metric]) for row in rows]
        result[metric] = {}
        for percentile in percentiles:
            distribution = samples[metric][percentile]
            result[metric][f"p{percentile}"] = {
                "estimate": _percentile(values, percentile),
                "ci95_lower": _percentile(distribution, 2.5),
                "ci95_upper": _percentile(distribution, 97.5),
            }
    return {
        "cluster_unit": "original vehicle or user",
        "clusters": len(cluster_ids),
        "replicates": int(replicates),
        "confidence_interval": "percentile cluster bootstrap 95%",
        "seed": int(seed),
        "metrics": result,
    }


def _identity_cluster_id(raw: dict[str, Any], *, period_id: str) -> str:
    """Return the preregistered identity cluster or fail closed.

    Falling back to ``period_id`` would silently turn an identity-cluster
    bootstrap into a row/period bootstrap and overstate precision.
    """

    value = raw.get("device_id") or raw.get("vehicle_id")
    if value is None or not str(value).strip():
        raise FormalError(
            f"S1 period {period_id!r} lacks the required device_id/vehicle_id cluster"
        )
    return str(value)


def _fallback_job(
    *,
    parameters: dict[str, Any],
    periods_path: Path,
    attempt_dir: Path,
) -> dict[str, Any]:
    dataset = str(parameters["dataset"])
    tariff, tariff_path = _load_tariff(periods_path)
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in _records(periods_path):
        period_id = str(raw.get("period_id") or raw.get("trip_id"))
        try:
            cluster_id = _identity_cluster_id(raw, period_id=period_id)
            fixes = [ReceiverFix.from_dict(item) for item in raw["fixes"]]
            edges = _edge_rows(fixes, tariff)
            outage = _outage(parameters, dataset, period_id, fixes)
            values = evaluate_mask(
                edges,
                outage_edges=outage,
                r_max_cents_per_m=tariff.max_zone_rate_cents_per_m,
            )
            whole_period_distance = int(values["total_distance_m"])
            with_month_close = whole_period_distance * tariff.max_zone_rate_cents_per_m
            rows.append(
                {
                    "dataset": dataset,
                    "cluster_id": cluster_id,
                    "period_id": period_id,
                    "scenario": parameters["scenario"],
                    "outage_edges": outage,
                    "oracle_position_fee_cents": values["oracle_fee_cents"],
                    "v5_dt_vmax_rmax_fee_cents": values["v5_fee_cents"],
                    "v6_dodo_rmax_fee_cents": values["v6_fee_cents"],
                    "v6_with_month_close_withholding_fee_cents": with_month_close,
                    "v6_without_month_close_fee_cents": 0,
                    "month_close_prevents_withholding_advantage": (
                        with_month_close >= int(values["oracle_fee_cents"])
                    ),
                    **values,
                }
            )
        except (FormalError, KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected.append({"dataset": dataset, "period_id": period_id, "reason": str(exc)})
    if not rows:
        raise FormalError(f"S1 accepted no periods from {periods_path}")
    output_path = attempt_dir / "period-results.jsonl"
    _write_rows(output_path, rows)
    if rejected:
        _write_rows(attempt_dir / "rejected-periods.jsonl", rejected)
    v6_surcharge = [float(row["v6_surcharge_cents"]) for row in rows]
    v5_surcharge = [float(row["v5_surcharge_cents"]) for row in rows]
    bootstrap = cluster_bootstrap_summary(
        rows,
        metrics=("v5_surcharge_cents", "v6_surcharge_cents"),
        percentiles=(50, 95, 99),
        replicates=5_000,
        seed=int(parameters["seed"]),
    )
    summary = {
        "status": "passed"
        if not rejected
        and max(int(row["v6_undercharge_cents"]) for row in rows) == 0
        and max(int(row["max_withholding_advantage_cents"]) for row in rows) == 0
        and sum(int(row["parking_v6_fee_cents"]) for row in rows) == 0
        and all(bool(row["month_close_prevents_withholding_advantage"]) for row in rows)
        else "failed",
        "dataset": dataset,
        "accepted_periods": len(rows),
        "rejected_periods": len(rejected),
        "clusters": len({row["cluster_id"] for row in rows}),
        "v5_surcharge_median_cents": statistics.median(v5_surcharge),
        "v5_surcharge_p95_cents": _percentile(v5_surcharge, 95),
        "v5_surcharge_p99_cents": _percentile(v5_surcharge, 99),
        "v6_surcharge_median_cents": statistics.median(v6_surcharge),
        "v6_surcharge_p95_cents": _percentile(v6_surcharge, 95),
        "v6_surcharge_p99_cents": _percentile(v6_surcharge, 99),
        "max_v6_undercharge_cents": max(int(row["v6_undercharge_cents"]) for row in rows),
        "max_withholding_advantage_cents": max(
            int(row["max_withholding_advantage_cents"]) for row in rows
        ),
        "parking_v6_fee_cents": sum(int(row["parking_v6_fee_cents"]) for row in rows),
        "without_month_close_withheld_fee_cents": 0,
        "with_month_close_withholding_fee_cents": sum(
            int(row["v6_with_month_close_withholding_fee_cents"]) for row in rows
        ),
        "bootstrap": bootstrap,
        "rejected_period_policy": "fail-closed",
        "tariff_path": str(tariff_path),
        "claim_boundary": "experimental integer currency; not an official taxpayer bill",
        "output": output_path.name,
    }
    return summary


def _sensitivity_job(
    *,
    parameters: dict[str, Any],
    periods_path: Path,
    attempt_dir: Path,
) -> dict[str, Any]:
    dataset = str(parameters["dataset"])
    error = float(parameters["odometer_error"])
    tariff, tariff_path = _load_tariff(periods_path)
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in _records(periods_path):
        period_id = str(raw.get("period_id") or raw.get("trip_id"))
        try:
            cluster_id = _identity_cluster_id(raw, period_id=period_id)
            fixes = [ReceiverFix.from_dict(item) for item in raw["fixes"]]
            edges = _edge_rows(fixes, tariff)
            if parameters["context"] == "natural":
                outage = _natural_outage_edges(fixes)
            else:
                outage = deterministic_outage_edges(
                    dataset=dataset,
                    period_id=period_id,
                    n_intervals=len(edges),
                    alpha=0.10,
                    seed=int(parameters["seed"]),
                )
            true_fee = sum(
                int(edge["delta_odo_m"]) * int(edge["zone_rate_cents_per_m"])
                for edge in edges
            )
            observed_fee = 0
            epsilon_m = 0
            outage_premium = 0
            for edge in edges:
                delta = int(edge["delta_odo_m"])
                observed = _scale_delta(delta, error)
                epsilon_m += abs(observed - delta)
                rate = (
                    tariff.max_zone_rate_cents_per_m
                    if int(edge["edge"]) in outage
                    else int(edge["zone_rate_cents_per_m"])
                )
                observed_fee += observed * rate
                if int(edge["edge"]) in outage:
                    outage_premium += delta * (
                        tariff.max_zone_rate_cents_per_m
                        - int(edge["zone_rate_cents_per_m"])
                    )
            revenue_lower = true_fee - tariff.max_zone_rate_cents_per_m * epsilon_m
            fairness_upper = (
                true_fee + outage_premium + tariff.max_zone_rate_cents_per_m * epsilon_m
            )
            rows.append(
                {
                    "dataset": dataset,
                    "cluster_id": cluster_id,
                    "period_id": period_id,
                    "odometer_error": error,
                    "context": parameters["context"],
                    "true_fee_cents": true_fee,
                    "observed_fee_cents": observed_fee,
                    "epsilon_odometer_m": epsilon_m,
                    "revenue_lower_bound_cents": revenue_lower,
                    "fairness_upper_bound_cents": fairness_upper,
                    "revenue_sound": observed_fee >= revenue_lower,
                    "honest_user_fair": observed_fee <= fairness_upper,
                }
            )
        except (FormalError, KeyError, TypeError, ValueError, OverflowError) as exc:
            rejected.append({"dataset": dataset, "period_id": period_id, "reason": str(exc)})
    if not rows:
        raise FormalError(f"S1 sensitivity accepted no periods from {periods_path}")
    output_path = attempt_dir / "sensitivity-results.jsonl"
    _write_rows(output_path, rows)
    if rejected:
        _write_rows(attempt_dir / "rejected-periods.jsonl", rejected)
    passed = not rejected and all(
        row["revenue_sound"] and row["honest_user_fair"] for row in rows
    )
    bootstrap = cluster_bootstrap_summary(
        rows,
        metrics=("observed_fee_cents", "epsilon_odometer_m"),
        percentiles=(50, 95, 99),
        replicates=5_000,
        seed=int(parameters["seed"]),
    )
    return {
        "status": "passed" if passed else "failed",
        "dataset": dataset,
        "accepted_periods": len(rows),
        "rejected_periods": len(rejected),
        "clusters": len({row["cluster_id"] for row in rows}),
        "odometer_error": error,
        "context": parameters["context"],
        "tariff_path": str(tariff_path),
        "bootstrap": bootstrap,
        "output": output_path.name,
    }


def main() -> int:
    job, attempt_dir, run_root = load_job_environment()
    if job.get("stage") != "S1":
        raise FormalError("S1 runner received a non-S1 job")
    manifest = load_prepared_manifest(run_root)
    dataset = prepared_dataset(manifest, str(job["parameters"]["dataset"]))
    periods_path = Path(dataset["periods_path"])
    if not periods_path.is_file():
        raise FormalError(f"prepared period corpus missing: {periods_path}")
    if job["kind"] == "paired-fallback":
        payload = _fallback_job(
            parameters=dict(job["parameters"]),
            periods_path=periods_path,
            attempt_dir=attempt_dir,
        )
    elif job["kind"] == "odometer-sensitivity":
        payload = _sensitivity_job(
            parameters=dict(job["parameters"]),
            periods_path=periods_path,
            attempt_dir=attempt_dir,
        )
    else:
        raise FormalError(f"unsupported S1 job kind: {job['kind']}")
    finish_stage(job=job, attempt_dir=attempt_dir, payload=payload)
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
