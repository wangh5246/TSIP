#!/usr/bin/env python3
"""Run the independent WayBill M3 certified-E3 experiment.

The runner accepts canonical instance JSON/JSONL directly.  For regression and
dataset runs it can also adapt the repository's period JSONL plus adjacent
``tariff_block.json`` files into exact integer-coordinate instances at
100/50/25/10 metre grids.  Fine-grid feasible witnesses are lifted into their
same-rate containing coarse cells without moving their integer payload points;
the coarse strict checker must accept every such incumbent.  The runner emits
one bound receipt per line and deterministic JSON/CSV summaries; it does not
call the legacy E3 harness.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.e3_certification import (  # noqa: E402
    MODEL_ID,
    RECEIPT_SCHEMA,
    E3Instance,
    E3Profile,
    Point,
    Rectangle,
    TariffCell,
    TrueFix,
    canonical_json,
    certify_instance,
    implementation_code_hash,
    sha256_json,
)


DEFAULT_INPUTS = (
    ROOT_DIR / "data" / "e1_mechanism_ablation" / "geolife" / "geolife_medium_identity.jsonl",
    ROOT_DIR / "experiments" / "e1_rome_real_tariff_ratio_fix" / "periods_60s.jsonl",
    ROOT_DIR / "data" / "e1_mechanism_ablation" / "porto" / "periods_60s.jsonl",
    ROOT_DIR / "data" / "e1_mechanism_ablation" / "tdrive" / "periods_300s.jsonl",
)
DEFAULT_OUTPUT_DIR = ROOT_DIR / "experiments" / "m3_certified_e3"
COORDINATE_SCALE_PER_M = 1_000  # exact integer millimetres


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run certified E3 LB/UB/gap analysis.")
    parser.add_argument(
        "--instances",
        nargs="+",
        type=Path,
        default=None,
        help="Canonical E3 instance JSON or JSONL files. When set, legacy --inputs are ignored.",
    )
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(DEFAULT_INPUTS))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--buckets-m", default="100,50,25,10")
    parser.add_argument("--relay-radius-m", type=int, default=200)
    parser.add_argument("--cadence-sec", type=int, default=120)
    parser.add_argument("--max-dt-sec", type=int, default=600)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument("--limit-per-input", type=int, default=1)
    parser.add_argument(
        "--rome-stratified",
        action="store_true",
        help=(
            "Select deterministic low/median/high neighbourhood-heterogeneity Rome records, "
            "with short/medium/long span tie-breaking."
        ),
    )
    parser.add_argument(
        "--max-fixes",
        type=int,
        default=0,
        help="Explicit prefix size for smoke runs; 0 retains the full frozen period.",
    )
    parser.add_argument("--timeout-sec", type=float, default=None)
    parser.add_argument("--oracle-max-fixes", type=int, default=5)
    parser.add_argument("--oracle-max-paths", type=int, default=1_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _validate_args(args)
    if args.instances:
        instances = list(_load_canonical_instances(args.instances))
        source_manifest: dict[str, Any] = {
            "mode": "canonical",
            "inputs": [str(path) for path in args.instances],
        }
    else:
        buckets_m = _parse_positive_ints(args.buckets_m)
        instances = list(
            _load_legacy_instances(
                args.inputs,
                buckets_m=buckets_m,
                relay_radius_m=int(args.relay_radius_m),
                cadence_sec=int(args.cadence_sec),
                max_dt_sec=int(args.max_dt_sec),
                tier_vmax_mps=int(args.tier_vmax_mps),
                limit_per_input=int(args.limit_per_input),
                max_fixes=int(args.max_fixes),
                stratify_rome=bool(args.rome_stratified),
            )
        )
        source_manifest = {
            "mode": "legacy_adapter",
            "inputs": [str(path) for path in args.inputs],
            "buckets_m": buckets_m,
            "coordinate_scale_per_m": COORDINATE_SCALE_PER_M,
            "rome_stratified": bool(args.rome_stratified),
            "rome_stratum_note": (
                "Rome candidate-neighbourhood heterogeneity has only the levels present in the fixed corpus; "
                "labels are deterministic quantile representatives, not fabricated tariff levels."
            ),
            "adapter_rule": (
                "subdivide each bound base tariff cell; child rate inherits its parent; "
                "bucket size changes the candidate grid but never odometer tolerance"
            ),
            "coarse_warm_start_rule": (
                "when a fine claimed cell is wholly contained by a same-rate coarse cell, "
                "retain the exact claimed point and rebind only its cell id; accept it only "
                "after the coarse instance strict checker passes"
            ),
        }

    receipts = _certify_instances(instances, args)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    receipts_path = args.output_dir / "bound_receipts.jsonl"
    summary_json_path = args.output_dir / "summary.json"
    summary_csv_path = args.output_dir / "summary.csv"
    receipts_path.write_text(
        "".join(canonical_json(receipt) + "\n" for receipt in receipts),
        encoding="utf-8",
    )
    oracle_gate = _run_small_oracle_gate()
    rows = _instance_summary_rows(receipts)
    gates = _gate_summary(rows, oracle_gate)
    _write_summary_csv(rows, summary_csv_path)
    summary = {
        "schema": "waybill.e3.run-summary/v1",
        "model_id": MODEL_ID,
        "source": source_manifest,
        "arguments": _json_arguments(args),
        "environment": _environment_manifest(),
        "core_code_hash": implementation_code_hash(),
        "runner_code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "attempted": len(receipts),
        "status_counts": dict(sorted(Counter(str(item.get("status", "unknown")) for item in receipts).items())),
        "main_representative_rule": "coarsest configured bucket for each fixed dataset/period stratum",
        "gap_rules": {
            "main_max_relative_gap_ppm": 10_000,
            "other_max_relative_gap_ppm": 50_000,
            "timeout_passes": False,
        },
        "legacy_rome_review": _legacy_rome_review(),
        "small_oracle_gate": oracle_gate,
        "gates": gates,
        "m3_status": gates["m3_status"],
        "hard_gate_passed": gates["hard_gate_passed"],
        "instance_results": rows,
        "aggregate_rows": _aggregate_rows(rows),
        "outputs": {
            "receipts_jsonl": str(receipts_path),
            "summary_csv": str(summary_csv_path),
        },
    }
    summary["summary_hash"] = sha256_json(summary)
    summary_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "attempted": len(receipts),
                "status_counts": summary["status_counts"],
                "m3_status": gates["m3_status"],
                "hard_gate_passed": gates["hard_gate_passed"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if gates["hard_gate_passed"] else 1


def _certify_instances(
    instances: list[E3Instance], args: argparse.Namespace
) -> list[dict[str, Any]]:
    """Certify fine grids first and expose their checked paths as coarse incumbents."""

    receipts: list[dict[str, Any] | None] = [None] * len(instances)
    completed_by_path: dict[str, list[tuple[E3Instance, Mapping[str, Any]]]] = defaultdict(list)

    def order_key(index: int) -> tuple[str, int, str]:
        instance = instances[index]
        bucket = instance.bucket_size_units
        # Unknown bucket geometry cannot prove a nested-grid lift, so it runs
        # after all explicit grids and receives no such incumbent.
        bucket_order = int(bucket) if isinstance(bucket, int) else 1 << 120
        return (_immutable_path_key(instance), bucket_order, str(instance.instance_id))

    for index in sorted(range(len(instances)), key=order_key):
        instance = instances[index]
        path_key = _immutable_path_key(instance)
        incumbents = _nested_grid_incumbents(
            target=instance,
            completed=completed_by_path[path_key],
        )
        try:
            receipt = certify_instance(
                instance,
                run_oracle=len(instance.fixes) <= int(args.oracle_max_fixes),
                oracle_max_paths=int(args.oracle_max_paths),
                timeout_sec=args.timeout_sec,
                feasible_incumbents=incumbents,
            )
        except Exception as exc:  # retain failed attempts in the experiment ledger
            receipt = _failed_receipt(instance, exc)
        receipts[index] = receipt
        if receipt.get("status") == "certified":
            completed_by_path[path_key].append((instance, receipt))

    if any(receipt is None for receipt in receipts):
        raise AssertionError("internal certification ledger is incomplete")
    return [receipt for receipt in receipts if receipt is not None]


def _immutable_path_key(instance: E3Instance) -> str:
    """Bind the fields that must agree before cross-grid witness reuse."""

    return sha256_json(
        {
            "dataset": str(instance.dataset),
            "profile": instance.profile.to_dict(),
            "fixes": [
                {
                    "device_id": str(fix.device_id),
                    "period_id": str(fix.period_id),
                    "fix_seq": int(fix.fix_seq),
                    "auth_time_sec": int(fix.auth_time_sec),
                    "odometer_m": int(fix.odometer_m),
                    "true_point": fix.true_point.to_dict(),
                }
                for fix in instance.fixes
            ],
        }
    )


def _nested_grid_incumbents(
    *,
    target: E3Instance,
    completed: Iterable[tuple[E3Instance, Mapping[str, Any]]],
) -> tuple[tuple[str, tuple[tuple[str, Point], ...]], ...]:
    """Lift strictly checked fine paths into same-rate containing coarse cells."""

    target_bucket = target.bucket_size_units
    if not isinstance(target_bucket, int):
        return ()
    incumbents: list[tuple[str, tuple[tuple[str, Point], ...]]] = []
    for source, receipt in completed:
        source_bucket = source.bucket_size_units
        if (
            not isinstance(source_bucket, int)
            or source_bucket >= target_bucket
            or target_bucket % source_bucket != 0
            or receipt.get("status") != "certified"
        ):
            continue
        witness = receipt.get("lower_bound", {}).get("witness")
        if not isinstance(witness, Mapping):
            continue
        raw_fixes = witness.get("fixes")
        if not isinstance(raw_fixes, list) or len(raw_fixes) != len(target.fixes):
            continue
        path: list[tuple[str, Point]] = []
        valid_lift = True
        for raw_fix in raw_fixes:
            if not isinstance(raw_fix, Mapping):
                valid_lift = False
                break
            source_cell = source.cell_map.get(str(raw_fix.get("claimed_cell_id", "")))
            raw_point = raw_fix.get("claimed_point")
            if source_cell is None or not isinstance(raw_point, Mapping):
                valid_lift = False
                break
            point = Point.from_dict(raw_point)
            containing = [
                cell
                for cell in target.tariff_cells
                if int(cell.rate_cents_per_m) == int(source_cell.rate_cents_per_m)
                and _rectangle_contains_rectangle(cell.rectangle, source_cell.rectangle)
                and cell.rectangle.contains(point)
            ]
            if not containing:
                valid_lift = False
                break
            target_cell = min(containing, key=lambda item: str(item.cell_id))
            path.append((str(target_cell.cell_id), point))
        if not valid_lift:
            continue
        source_label = (
            f"nested-grid-lift:{source.instance_id}:"
            f"{source.instance_hash}"
        )
        incumbents.append((source_label, tuple(path)))
    return tuple(incumbents)


def _rectangle_contains_rectangle(outer: Rectangle, inner: Rectangle) -> bool:
    return (
        int(outer.x_min) <= int(inner.x_min)
        and int(inner.x_max) <= int(outer.x_max)
        and int(outer.y_min) <= int(inner.y_min)
        and int(inner.y_max) <= int(outer.y_max)
    )


def _failed_receipt(instance: E3Instance, exc: Exception) -> dict[str, Any]:
    error_text = str(exc).lower()
    soundness_markers = (
        "bound direction",
        "relaxation direction",
        "containment proof",
        "outside the certified interval",
        "failed strict checking",
    )
    failure_class = (
        "soundness-failure"
        if isinstance(exc, AssertionError)
        or any(marker in error_text for marker in soundness_markers)
        else "execution-failure"
    )
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "failed",
        "instance": {
            "instance_id": str(instance.instance_id),
            "dataset": str(instance.dataset),
            "instance_hash": instance.instance_hash,
            "bucket_size_units": instance.bucket_size_units,
        },
        "bindings": {
            "model_id": MODEL_ID,
            "profile_hash": instance.profile_hash,
            "tariff_hash": instance.tariff_hash,
            "data_hash": instance.data_hash,
            "code_hash": implementation_code_hash(),
        },
        "error_type": type(exc).__name__,
        "error": str(exc),
        "failure_class": failure_class,
    }
    receipt["receipt_hash"] = sha256_json(receipt)
    return receipt


def _legacy_rome_review() -> dict[str, Any]:
    """Keep the legacy bucket sensitivity distinct from certified bounds."""

    return {
        "classification": "legacy_bucket_sensitivity_not_certified_bound",
        "reported_legacy_p95_change": {
            "from": "0.464",
            "to": "0.295",
            "copied_into_certified_results": False,
        },
        "distance_projection_regression": {
            "period_id": "rome:60:67-1-s1:p0",
            "immutable_odometer_delta_m": 648,
            "legacy_projected_delta_m": 361,
            "strict_checker_result": "rejected",
            "violation_code": "ODO_BINDING",
            "test": (
                "tests/test_e3_certification.py::"
                "test_old_rome_648_to_361_projection_is_rejected_without_bucket_tolerance"
            ),
        },
        "conclusion": (
            "The legacy 0.464-to-0.295 P95 sensitivity used bucket-expanded distance "
            "semantics and is not an LB, UB, or certified gap. Under the frozen V6 SSOT, "
            "the 648m-to-361m odometer projection is rejected by ODO_BINDING, so the old "
            "numbers cannot be directly reproduced or compared as V6 certified results."
        ),
    }


def _validate_args(args: argparse.Namespace) -> None:
    if int(args.relay_radius_m) < 0:
        raise ValueError("--relay-radius-m must be non-negative")
    for option in ("cadence_sec", "max_dt_sec", "tier_vmax_mps", "oracle_max_paths"):
        if int(getattr(args, option)) <= 0:
            raise ValueError(f"--{option.replace('_', '-')} must be positive")
    if int(args.limit_per_input) < 0 or int(args.max_fixes) < 0 or int(args.oracle_max_fixes) < 0:
        raise ValueError("--limit-per-input, --max-fixes, and --oracle-max-fixes must be non-negative")
    if args.timeout_sec is not None and float(args.timeout_sec) <= 0:
        raise ValueError("--timeout-sec must be positive")


def _json_arguments(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "instances": None if args.instances is None else [str(path) for path in args.instances],
        "inputs": [str(path) for path in args.inputs],
        "output_dir": str(args.output_dir),
        "buckets_m": str(args.buckets_m),
        "relay_radius_m": int(args.relay_radius_m),
        "cadence_sec": int(args.cadence_sec),
        "max_dt_sec": int(args.max_dt_sec),
        "tier_vmax_mps": int(args.tier_vmax_mps),
        "limit_per_input": int(args.limit_per_input),
        "rome_stratified": bool(args.rome_stratified),
        "max_fixes": int(args.max_fixes),
        "timeout_sec": args.timeout_sec,
        "oracle_max_fixes": int(args.oracle_max_fixes),
        "oracle_max_paths": int(args.oracle_max_paths),
    }


def _parse_positive_ints(raw: str) -> list[int]:
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if not values or any(value <= 0 for value in values):
        raise ValueError("integer list must contain positive values")
    if len(set(values)) != len(values):
        raise ValueError("integer list must not contain duplicates")
    return values


def _environment_manifest() -> dict[str, Any]:
    return {
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "implementation": platform.python_implementation(),
            "version": sys.version,
        },
        "hardware": {
            "machine": platform.machine(),
            "processor": platform.processor() or "not-reported-by-platform",
            "logical_cpu_count": os.cpu_count(),
        },
        "platform": platform.platform(),
        "execution": {
            "command": [str(Path(sys.executable).resolve()), *sys.argv],
            "parallelism": "single process; no worker pool",
            "solver_backend": (
                "pure-Python deterministic integer layered search with exact small-oracle "
                "enumeration and R_rect/R_ind relaxations"
            ),
            "thread_setting": "no configurable solver threads; Python runner executes serially",
        },
    }


def _load_canonical_instances(paths: Iterable[Path]) -> Iterator[E3Instance]:
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        text = path.read_text(encoding="utf-8")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            payloads = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payloads = decoded if isinstance(decoded, list) else [decoded]
        for payload in payloads:
            yield E3Instance.from_dict(payload)


def _load_legacy_instances(
    paths: Iterable[Path],
    *,
    buckets_m: list[int],
    relay_radius_m: int,
    cadence_sec: int,
    max_dt_sec: int,
    tier_vmax_mps: int,
    limit_per_input: int,
    max_fixes: int,
    stratify_rome: bool,
) -> Iterator[E3Instance]:
    for path in paths:
        if not path.exists():
            continue
        tariff_payload = _load_tariff_payload(path)
        records = list(_iter_jsonl(path))
        rome_is_stratified = stratify_rome and _dataset_name(path) == "rome"
        if rome_is_stratified:
            records = _select_rome_strata(
                path=path,
                records=records,
                tariff_payload=tariff_payload,
                relay_radius_m=relay_radius_m,
                cadence_sec=cadence_sec,
                max_dt_sec=max_dt_sec,
                tier_vmax_mps=tier_vmax_mps,
            )
        emitted = 0
        for record in records:
            raw_fixes = list(record.get("fixes", []))
            if max_fixes > 0:
                raw_fixes = raw_fixes[:max_fixes]
            if len(raw_fixes) < 2:
                continue
            for bucket_m in buckets_m:
                try:
                    yield _legacy_record_to_instance(
                        path=path,
                        record=record,
                        raw_fixes=raw_fixes,
                        tariff_payload=tariff_payload,
                        bucket_m=bucket_m,
                        relay_radius_m=relay_radius_m,
                        cadence_sec=cadence_sec,
                        max_dt_sec=max_dt_sec,
                        tier_vmax_mps=tier_vmax_mps,
                    )
                except ValueError:
                    # The same period can be outside a bounded tariff block at a
                    # particular adapter grid.  It is omitted rather than
                    # silently changing the frozen path or tariff.
                    continue
            emitted += 1
            # A stratified Rome run is a fixed three-record corpus regardless
            # of the per-input representative limit used for other datasets.
            effective_limit = len(records) if rome_is_stratified else limit_per_input
            if effective_limit > 0 and emitted >= effective_limit:
                break


def _select_rome_strata(
    *,
    path: Path,
    records: list[dict[str, Any]],
    tariff_payload: Mapping[str, Any],
    relay_radius_m: int,
    cadence_sec: int,
    max_dt_sec: int,
    tier_vmax_mps: int,
) -> list[dict[str, Any]]:
    """Pick fixed low/median/high attack-neighbourhood representatives.

    The old Rome corpus has a constant true-path rate, so heterogeneity is
    measured over cells reachable by the frozen relay radius, not invented from
    the legacy 0.464/0.295 sensitivity numbers.
    """

    metrics: list[tuple[dict[str, Any], int, int, int, int, str]] = []
    for record in records:
        raw_fixes = list(record.get("fixes", []))
        if len(raw_fixes) < 2:
            continue
        try:
            instance = _legacy_record_to_instance(
                path=path,
                record=record,
                raw_fixes=raw_fixes,
                tariff_payload=tariff_payload,
                bucket_m=100,
                relay_radius_m=relay_radius_m,
                cadence_sec=cadence_sec,
                max_dt_sec=max_dt_sec,
                tier_vmax_mps=tier_vmax_mps,
            )
        except ValueError:
            continue
        candidate_rates: set[int] = set()
        radius_sq = int(instance.profile.relay_radius_units) ** 2
        for fix in instance.fixes:
            for cell in instance.tariff_cells:
                if _point_rectangle_distance_sq(fix.true_point, cell.rectangle) <= radius_sq:
                    candidate_rates.add(int(cell.rate_cents_per_m))
        if not candidate_rates:
            continue
        span_sec = int(raw_fixes[-1]["auth_gnss_time"]) - int(raw_fixes[0]["auth_gnss_time"])
        distance_m = int(raw_fixes[-1]["odometer_reading_m"]) - int(raw_fixes[0]["odometer_reading_m"])
        metrics.append(
            (
                record,
                max(candidate_rates) - min(candidate_rates),
                len(candidate_rates),
                span_sec,
                distance_m,
                str(record.get("period_id", record.get("trip_id", ""))),
            )
        )
    if not metrics:
        return records[:3]
    ordered = sorted(metrics, key=lambda item: (item[1], item[2], item[3], item[4], item[5]))
    selections = (
        (ordered[0], "low-heterogeneity-short"),
        (ordered[len(ordered) // 2], "median-heterogeneity-medium"),
        (ordered[-1], "high-heterogeneity-long"),
    )
    selected: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    for metric, label in selections:
        record = dict(metric[0])
        period_id = str(record.get("period_id", record.get("trip_id", "")))
        if period_id in seen_periods:
            continue
        record["_m3_stratum"] = label
        record["_m3_neighbourhood_rate_spread"] = int(metric[1])
        record["_m3_neighbourhood_rate_levels"] = int(metric[2])
        record["_m3_span_sec"] = int(metric[3])
        seen_periods.add(period_id)
        selected.append(record)
    return selected


def _load_tariff_payload(input_path: Path) -> dict[str, Any]:
    candidates = (
        input_path.parent / "tariff_block.json",
        input_path.parent.parent / "tariff_block.json",
    )
    for candidate in candidates:
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            payload["_source_path"] = str(candidate)
            return payload
    raise FileNotFoundError(f"missing tariff_block.json adjacent to {input_path}")


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _legacy_record_to_instance(
    *,
    path: Path,
    record: Mapping[str, Any],
    raw_fixes: list[Mapping[str, Any]],
    tariff_payload: Mapping[str, Any],
    bucket_m: int,
    relay_radius_m: int,
    cadence_sec: int,
    max_dt_sec: int,
    tier_vmax_mps: int,
) -> E3Instance:
    tariff = tariff_payload.get("tariff", tariff_payload)
    base_cell_size_m = int(tariff_payload.get("block", {}).get("cell_size_m", 100))
    if base_cell_size_m % int(bucket_m):
        raise ValueError("bucket must exactly divide the source tariff cell size")
    grid_w = int(tariff["grid_w"])
    cell_zones = {int(key): int(value) for key, value in tariff["cell_zones"].items()}
    zone_rates = {int(key): int(value) for key, value in tariff["zone_rates_cents_per_m"].items()}
    block = tariff_payload.get("block", {})
    global_x_min = int(block.get("global_cell_x_min", 0))
    global_y_min = int(block.get("global_cell_y_min", 0))
    true_points = [
        _legacy_true_point(
            raw,
            global_x_min=global_x_min,
            global_y_min=global_y_min,
            base_cell_size_m=base_cell_size_m,
        )
        for raw in raw_fixes
    ]
    cells = _subdivide_tariff(
        cell_zones=cell_zones,
        zone_rates=zone_rates,
        grid_w=grid_w,
        global_x_min=global_x_min,
        global_y_min=global_y_min,
        base_cell_size_m=base_cell_size_m,
        bucket_m=int(bucket_m),
        true_points=true_points,
        relay_radius_units=int(relay_radius_m) * COORDINATE_SCALE_PER_M,
    )
    cell_map = {cell.cell_id: cell for cell in cells}
    true_fixes: list[TrueFix] = []
    for index, (raw, true_point) in enumerate(zip(raw_fixes, true_points)):
        fine_x = math.floor(int(true_point.x) / (int(bucket_m) * COORDINATE_SCALE_PER_M))
        fine_y = math.floor(int(true_point.y) / (int(bucket_m) * COORDINATE_SCALE_PER_M))
        true_cell_id = _child_cell_id(bucket_m, fine_x, fine_y)
        if true_cell_id not in cell_map or not cell_map[true_cell_id].rectangle.contains(true_point):
            raise ValueError(f"fix {index} lies outside the bound tariff cells")
        true_fixes.append(
            TrueFix(
                device_id=str(raw.get("device_id", record.get("device_id", "unknown"))),
                period_id=str(raw.get("period_id", record.get("period_id", record.get("trip_id", "unknown")))),
                fix_seq=int(raw["fix_seq"]),
                auth_time_sec=int(raw["auth_gnss_time"]),
                odometer_m=int(raw["odometer_reading_m"]),
                true_point=true_point,
                true_cell_id=true_cell_id,
            )
        )
    dataset = str(record.get("dataset") or _dataset_name(path))
    period_id = str(record.get("period_id") or record.get("trip_id") or true_fixes[0].period_id)
    stratum = str(record.get("_m3_stratum", ""))
    stratum_suffix = f":stratum-{stratum}" if stratum else ""
    profile = E3Profile(
        profile_id=f"waybill-v6-fixed-odo-{dataset}",
        cadence_sec=int(cadence_sec),
        max_dt_sec=int(max_dt_sec),
        tier_vmax_mps=int(tier_vmax_mps),
        relay_radius_units=int(relay_radius_m) * COORDINATE_SCALE_PER_M,
        r_max_cents_per_m=max(cell.rate_cents_per_m for cell in cells),
        coordinate_scale_per_m=COORDINATE_SCALE_PER_M,
    )
    return E3Instance(
        instance_id=f"{dataset}:{period_id}:bucket-{bucket_m}m{stratum_suffix}",
        dataset=dataset,
        profile=profile,
        tariff_cells=tuple(cells),
        fixes=tuple(true_fixes),
        bucket_size_units=int(bucket_m) * COORDINATE_SCALE_PER_M,
    )


def _subdivide_tariff(
    *,
    cell_zones: Mapping[int, int],
    zone_rates: Mapping[int, int],
    grid_w: int,
    global_x_min: int,
    global_y_min: int,
    base_cell_size_m: int,
    bucket_m: int,
    true_points: list[Point],
    relay_radius_units: int,
) -> list[TariffCell]:
    factor = int(base_cell_size_m) // int(bucket_m)
    bucket_units = int(bucket_m) * COORDINATE_SCALE_PER_M
    cells: dict[str, TariffCell] = {}
    base_units = int(base_cell_size_m) * COORDINATE_SCALE_PER_M
    radius_sq = int(relay_radius_units) ** 2
    maximum_bound_rate = max(int(zone_rates[int(zone)]) for zone in cell_zones.values())
    selected_indices: set[int] = set()
    maximum_rate_index: int | None = None
    for local_index, zone_id in sorted(cell_zones.items()):
        local_x = int(local_index) % int(grid_w)
        local_y = int(local_index) // int(grid_w)
        base_global_x = int(global_x_min) + local_x
        base_global_y = int(global_y_min) + local_y
        rate = int(zone_rates[int(zone_id)])
        if rate == maximum_bound_rate and maximum_rate_index is None:
            maximum_rate_index = int(local_index)
        base_rectangle = Rectangle(
            x_min=base_global_x * base_units,
            y_min=base_global_y * base_units,
            x_max=(base_global_x + 1) * base_units,
            y_max=(base_global_y + 1) * base_units,
        )
        if any(_point_rectangle_distance_sq(point, base_rectangle) <= radius_sq for point in true_points):
            selected_indices.add(int(local_index))
    # Preserve the canonical r_max binding even when its representative cell is
    # outside every attack disk.  Such a cell cannot enter a candidate layer.
    if maximum_rate_index is not None:
        selected_indices.add(maximum_rate_index)

    for local_index in sorted(selected_indices):
        zone_id = int(cell_zones[local_index])
        local_x = int(local_index) % int(grid_w)
        local_y = int(local_index) // int(grid_w)
        base_global_x = int(global_x_min) + local_x
        base_global_y = int(global_y_min) + local_y
        rate = int(zone_rates[zone_id])
        for sub_y in range(factor):
            for sub_x in range(factor):
                fine_x = base_global_x * factor + sub_x
                fine_y = base_global_y * factor + sub_y
                cell_id = _child_cell_id(bucket_m, fine_x, fine_y)
                cells[cell_id] = TariffCell(
                    cell_id=cell_id,
                    rectangle=Rectangle(
                        x_min=fine_x * bucket_units,
                        y_min=fine_y * bucket_units,
                        x_max=(fine_x + 1) * bucket_units,
                        y_max=(fine_y + 1) * bucket_units,
                    ),
                    rate_cents_per_m=rate,
                )
    return [cells[cell_id] for cell_id in sorted(cells)]


def _point_rectangle_distance_sq(point: Point, rectangle: Rectangle) -> int:
    dx = max(int(rectangle.x_min) - int(point.x), 0, int(point.x) - int(rectangle.x_max))
    dy = max(int(rectangle.y_min) - int(point.y), 0, int(point.y) - int(rectangle.y_max))
    return dx * dx + dy * dy


def _child_cell_id(bucket_m: int, fine_x: int, fine_y: int) -> str:
    return f"b{int(bucket_m)}:{int(fine_x)}:{int(fine_y)}"


def _legacy_true_point(
    raw: Mapping[str, Any],
    *,
    global_x_min: int,
    global_y_min: int,
    base_cell_size_m: int,
) -> Point:
    if "x_m" in raw and "y_m" in raw:
        return Point(_metres_to_units(raw["x_m"]), _metres_to_units(raw["y_m"]))
    local_x = int(raw["cell_x"])
    local_y = int(raw["cell_y"])
    global_x = int(global_x_min) + local_x
    global_y = int(global_y_min) + local_y
    half = int(base_cell_size_m) * COORDINATE_SCALE_PER_M // 2
    return Point(
        global_x * int(base_cell_size_m) * COORDINATE_SCALE_PER_M + half,
        global_y * int(base_cell_size_m) * COORDINATE_SCALE_PER_M + half,
    )


def _metres_to_units(value: Any) -> int:
    scaled = Decimal(str(value)) * Decimal(COORDINATE_SCALE_PER_M)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _dataset_name(path: Path) -> str:
    lowered = str(path).lower()
    for name in ("geolife", "rome", "porto", "tdrive"):
        if name in lowered:
            return name
    return path.stem


def _run_small_oracle_gate() -> dict[str, Any]:
    cells = (
        TariffCell("low", Rectangle(-3, -1, -1, 1), 1),
        TariffCell("true-0", Rectangle(-1, -1, 1, 1), 10),
        TariffCell("true-1", Rectangle(9, -1, 11, 1), 10),
    )
    instance = E3Instance(
        instance_id="m3-small-oracle-gate-v1",
        dataset="gate",
        profile=E3Profile(
            cadence_sec=60,
            max_dt_sec=1_000,
            tier_vmax_mps=1,
            relay_radius_units=2,
            r_max_cents_per_m=10,
            coordinate_scale_per_m=1,
        ),
        tariff_cells=cells,
        fixes=(
            TrueFix("gate-device", "gate-period", 0, 0, 0, Point(0, 0), "true-0"),
            TrueFix("gate-device", "gate-period", 1, 10, 10, Point(10, 0), "true-1"),
        ),
        bucket_size_units=2,
    )
    try:
        receipt = certify_instance(instance, run_oracle=True, oracle_max_paths=10_000)
        oracle = receipt.get("oracle") or {}
        optimum = oracle.get("optimum_underpayment_cents")
        bracketed = (
            oracle.get("complete") is True
            and isinstance(optimum, int)
            and int(receipt["LB_cents"]) <= optimum <= int(receipt["UB_cents"])
        )
        original_domain = oracle.get("domain") == "F_continuous_integer"
        noncenter_regression = int(receipt["LB_cents"]) < int(optimum) == int(receipt["UB_cents"])
        lb_checker = bool(receipt["lower_bound"]["checker"]["accepted"])
        ub_direction = bool(
            receipt["upper_bound"]["independent_cross_check"]["direction_ok"]
        )
        passed = (
            bracketed
            and original_domain
            and noncenter_regression
            and lb_checker
            and ub_direction
            and not bool(receipt.get("timeout"))
        )
        return {
            "required": True,
            "passed": passed,
            "complete": bool(oracle.get("complete")),
            "LB_cents": int(receipt["LB_cents"]),
            "OPT_cents": optimum,
            "UB_cents": int(receipt["UB_cents"]),
            "lb_le_opt_le_ub": bracketed,
            "oracle_domain": oracle.get("domain"),
            "original_domain_exact": original_domain,
            "noncenter_better_than_center_regression": noncenter_regression,
            "lb_checker_passed": lb_checker,
            "ub_direction_passed": ub_direction,
            "timeout": bool(receipt.get("timeout")),
            "receipt_hash": str(receipt["receipt_hash"]),
        }
    except Exception as exc:
        return {
            "required": True,
            "passed": False,
            "complete": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _instance_summary_rows(receipts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    materialized = list(receipts)
    maximum_bucket_by_period: dict[str, int] = {}
    for receipt in materialized:
        instance = receipt.get("instance", {})
        bucket = instance.get("bucket_size_units")
        if isinstance(bucket, int):
            group = _instance_group_id(str(instance.get("instance_id", "")))
            maximum_bucket_by_period[group] = max(maximum_bucket_by_period.get(group, bucket), bucket)

    rows: list[dict[str, Any]] = []
    for receipt in materialized:
        instance = receipt.get("instance", {})
        instance_id = str(instance.get("instance_id", "unknown"))
        dataset = str(instance.get("dataset", "unknown"))
        bucket_units = instance.get("bucket_size_units")
        group = _instance_group_id(instance_id)
        main_representative = (
            isinstance(bucket_units, int)
            and bucket_units == maximum_bucket_by_period.get(group)
        )
        threshold_ppm = 10_000 if main_representative else 50_000
        certified = receipt.get("status") == "certified"
        checker_passed = bool(
            certified and receipt.get("lower_bound", {}).get("checker", {}).get("accepted")
        )
        lb = receipt.get("LB_cents")
        ub = receipt.get("UB_cents")
        lb_le_ub = isinstance(lb, int) and isinstance(ub, int) and lb <= ub
        rect_le_ind = bool(
            certified
            and receipt.get("upper_bound", {})
            .get("independent_cross_check", {})
            .get("direction_ok")
        )
        ub_direction_passed = lb_le_ub and rect_le_ind
        relative_gap_ppm = receipt.get("relative_gap_ppm")
        gap_passed = isinstance(relative_gap_ppm, int) and relative_gap_ppm <= threshold_ppm
        timeout = bool(receipt.get("timeout"))
        oracle = receipt.get("oracle")
        oracle_status = "not_run" if oracle is None else "complete" if oracle.get("complete") else "incomplete"
        hard_gate_passed = (
            certified
            and checker_passed
            and ub_direction_passed
            and gap_passed
            and not timeout
        )
        if not certified:
            resolution = "failed_execution"
        elif not checker_passed or not ub_direction_passed:
            resolution = "failed_soundness"
        elif timeout:
            resolution = "unresolved_timeout"
        elif not gap_passed:
            resolution = "unresolved_gap"
        else:
            resolution = "gate_passed"
        stratum = next(
            (part.removeprefix("stratum-") for part in instance_id.split(":") if part.startswith("stratum-")),
            "representative",
        )
        rows.append(
            {
                "instance_id": instance_id,
                "dataset": dataset,
                "stratum": stratum,
                "bucket_size_units": bucket_units,
                "bucket_m": (
                    int(bucket_units) // COORDINATE_SCALE_PER_M
                    if isinstance(bucket_units, int) and bucket_units >= COORDINATE_SCALE_PER_M
                    else ""
                ),
                "status": str(receipt.get("status", "unknown")),
                "resolution": resolution,
                "main_representative": main_representative,
                "H_cents": receipt.get("H_cents", ""),
                "LB_cents": lb if isinstance(lb, int) else "",
                "UB_cents": ub if isinstance(ub, int) else "",
                "gap_cents": receipt.get("gap_cents", ""),
                "relative_gap_ppm": relative_gap_ppm if isinstance(relative_gap_ppm, int) else "",
                "gap_threshold_ppm": threshold_ppm,
                "gap_passed": gap_passed,
                "timeout": timeout,
                "lb_checker_passed": checker_passed,
                "lower_selected_source": str(
                    receipt.get("lower_bound", {}).get("selected_source", "")
                ),
                "lb_le_ub": lb_le_ub,
                "rect_le_ind": rect_le_ind,
                "ub_direction_passed": ub_direction_passed,
                "oracle_status": oracle_status,
                "upper_relaxation": str(
                    receipt.get("upper_bound", {}).get("relaxation_id", "")
                ),
                "hard_gate_passed": hard_gate_passed,
                "receipt_hash": str(receipt.get("receipt_hash", "")),
                "error": str(receipt.get("error", "")),
            }
        )
    return sorted(rows, key=lambda row: (str(row["dataset"]), str(row["instance_id"]), int(row["bucket_size_units"] or 0)))


def _instance_group_id(instance_id: str) -> str:
    return ":".join(part for part in instance_id.split(":") if not part.startswith("bucket-"))


def _gate_summary(rows: list[dict[str, Any]], oracle_gate: Mapping[str, Any]) -> dict[str, Any]:
    all_instances_certified = bool(rows) and all(row["status"] == "certified" for row in rows)
    all_lb_checkers_passed = bool(rows) and all(bool(row["lb_checker_passed"]) for row in rows)
    all_ub_directions_passed = bool(rows) and all(bool(row["ub_direction_passed"]) for row in rows)
    all_gap_thresholds_passed = bool(rows) and all(bool(row["gap_passed"]) for row in rows)
    no_timeouts = bool(rows) and not any(bool(row["timeout"]) for row in rows)
    small_oracle_passed = oracle_gate.get("passed") is True
    soundness_passed = small_oracle_passed and all_lb_checkers_passed and all_ub_directions_passed
    hard_gate_passed = (
        all_instances_certified
        and soundness_passed
        and all_gap_thresholds_passed
        and no_timeouts
    )
    if hard_gate_passed:
        m3_status = "verified"
    elif not all_instances_certified or not soundness_passed:
        m3_status = "failed"
    else:
        m3_status = "unresolved"
    return {
        "small_oracle_passed": small_oracle_passed,
        "all_instances_certified": all_instances_certified,
        "all_lb_checkers_passed": all_lb_checkers_passed,
        "all_ub_directions_passed": all_ub_directions_passed,
        "all_gap_thresholds_passed": all_gap_thresholds_passed,
        "no_timeouts": no_timeouts,
        "hard_gate_passed": hard_gate_passed,
        "m3_status": m3_status,
    }


def _aggregate_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, Any], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["dataset"]), row["bucket_size_units"])].append(row)
    aggregates: list[dict[str, Any]] = []
    for (dataset, bucket), items in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or -1)):
        aggregates.append(
            {
                "dataset": dataset,
                "bucket_size_units": bucket,
                "attempted": len(items),
                "gate_passed": sum(bool(item["hard_gate_passed"]) for item in items),
                "failed_or_unresolved": sum(not bool(item["hard_gate_passed"]) for item in items),
                "gap_cents_sum": sum(int(item["gap_cents"] or 0) for item in items),
                "timeout_count": sum(bool(item["timeout"]) for item in items),
            }
        )
    return aggregates


def _write_summary_csv(rows: list[dict[str, Any]], path: Path) -> None:
    fields = (
        "instance_id",
        "dataset",
        "stratum",
        "bucket_size_units",
        "bucket_m",
        "status",
        "resolution",
        "main_representative",
        "H_cents",
        "LB_cents",
        "UB_cents",
        "gap_cents",
        "relative_gap_ppm",
        "gap_threshold_ppm",
        "gap_passed",
        "timeout",
        "lb_checker_passed",
        "lower_selected_source",
        "lb_le_ub",
        "rect_le_ind",
        "ub_direction_passed",
        "oracle_status",
        "upper_relaxation",
        "hard_gate_passed",
        "receipt_hash",
        "error",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
