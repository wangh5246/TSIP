#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.osm_vectors import tariff_at_granularity, tariff_from_geojson  # noqa: E402
from common.eval_harness import HarnessParams  # noqa: E402
from common.trajectory_preprocess import (  # noqa: E402
    CELL_SIZE_M,
    CITY_BBOX,
    DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M,
    LEGAL_CADENCES,
    MAX_DT_SEC,
    N_PERIOD_FIXES,
    PERIOD_MAX_SEC,
    REBASE_ANCHOR,
    TRIP_GAP_SEC,
    build_local_tariff_table,
    build_period_records,
    build_resampled_fixes,
    choose_density_peak_block,
    clean_raw_points,
    global_cell_center_latlon,
    iter_geolife_driving_raw_points,
    iter_porto_raw_points,
    iter_rome_raw_points,
    iter_tdrive_raw_points,
    rebase_points_to_2026,
    receiver_fixes_from_period,
    segment_native_trips,
)
from script.prove_settlement_period_v5 import TREE_DEPTH, build_raw_witness_input_for_fixes  # noqa: E402


DATASET_DIR = ROOT_DIR / "dataset"
FIELDS = [
    "dataset",
    "cadence_sec",
    "grid_side",
    "n_devices",
    "n_raw_points",
    "n_native_trips",
    "n_resampled_fixes",
    "n_runs",
    "max_run_len",
    "p95_run_len",
    "n_runs_ge_25",
    "n_candidate_25_windows",
    "n_candidate_25_windows_span_ok",
    "n_candidate_25_windows_positive_odo",
    "n_periods",
    "n_periods_with_outage",
    "max_intra_period_dt",
    "n_witness_input_ok",
    "grid_cells",
    "tariff_leaf_count",
    "tariff_leaf_capacity",
    "tariff_leaf_capacity_ok",
    "tariff_nonzero_rate_cells",
    "tariff_nonzero_rate_cells_fit_leaf_capacity",
    "tariff_cells_used",
    "tariff_cells_capacity",
    "block_global_cell_x_min",
    "block_global_cell_y_min",
    "block_lat_min",
    "block_lat_max",
    "block_lon_min",
    "block_lon_max",
    "block_center_lat",
    "block_center_lon",
    "top_placement_cells",
    "rebase_sample_device_id",
    "rebase_sample_n_dts",
    "rebase_sample_dt_match",
    "rebase_sample_max_abs_dt_delta",
    "rebase_devices_with_dt_mismatch",
    "first_period_id",
    "first_period_device_id",
    "first_period_trip_id",
    "first_period_span_sec",
    "first_period_original_span_sec",
    "first_period_max_dt_sec",
    "first_period_max_original_dt_sec",
    "first_period_rebase_dt_match",
    "first_period_start_original_unix",
    "first_period_end_original_unix",
    "top_reject_reasons",
    "status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Tier-1 period yield as a function of grid side.")
    parser.add_argument("--dataset", choices=["tdrive", "geolife", "porto", "rome", "all"], default="tdrive")
    parser.add_argument("--grid-sides", nargs="+", type=int, default=[6, 16, 32])
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "data" / "processed" / "grid_yield_diagnostic.csv")
    parser.add_argument("--granularity", choices=["coarse", "medium", "fine"], default="medium")
    parser.add_argument("--cell-size-m", type=int, default=CELL_SIZE_M)
    parser.add_argument("--circuit-grid-w", type=int, default=100)
    parser.add_argument("--trip-gap-sec", type=int, default=TRIP_GAP_SEC)
    parser.add_argument("--max-dt-sec", type=int, default=MAX_DT_SEC)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument("--outage-bridge-max-odo-m", type=int, default=DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M)
    parser.add_argument("--max-raw-points", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = ["tdrive", "geolife", "porto", "rome"] if args.dataset == "all" else [args.dataset]
    rows: list[dict[str, Any]] = []
    for dataset in selected:
        rows.extend(_diagnose_dataset(dataset, args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))
    return 0


def _diagnose_dataset(dataset: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    city = "beijing" if dataset in {"tdrive", "geolife"} else dataset
    geometry = _load_geometry(city, args.granularity, args.cell_size_m)
    raw, _stage0_rejects = clean_raw_points(dataset, _limit(_iter_raw(dataset), args.max_raw_points), city_bbox=CITY_BBOX[city])
    rebased = rebase_points_to_2026(raw, anchor=REBASE_ANCHOR)
    rebase_stats = _rebase_diff_stats(rebased)
    native, _stage2_rejects = segment_native_trips(dataset, rebased, gap_sec=args.trip_gap_sec)
    out: list[dict[str, Any]] = []
    for grid_side in args.grid_sides:
        block = choose_density_peak_block(
            native or rebased,
            origin_lat=geometry.origin_lat,
            origin_lon=geometry.origin_lon,
            width=int(grid_side),
            cell_size_m=args.cell_size_m,
            moving_only=True,
        )
        tariff = build_local_tariff_table(block, geometry, circuit_grid_w=args.circuit_grid_w)
        tariff_capacity_stats = _tariff_capacity_stats(tariff, grid_side=int(grid_side))
        for cadence_sec in LEGAL_CADENCES[dataset]:
            fixes, fix_rejects = build_resampled_fixes(
                dataset,
                native,
                cadence_sec=cadence_sec,
                block=block,
                tariff=tariff,
                tier_vmax_mps=args.tier_vmax_mps,
                max_dt_sec=args.max_dt_sec,
                outage_bridge_max_odo_m=args.outage_bridge_max_odo_m,
            )
            periods, period_rejects = build_period_records(dataset, fixes, cadence_sec=cadence_sec, tariff=tariff)
            run_stats = _run_stats(fixes)
            witness_ok = _witness_smoke_count(
                periods,
                tariff,
                cadence_sec=cadence_sec,
                max_dt_sec=args.max_dt_sec,
                tier_vmax_mps=args.tier_vmax_mps,
            )
            block_stats = _block_location_stats(block)
            placement_stats = _placement_stats(native or rebased, block, moving_only=True)
            period_stats = _first_period_introspection(periods, fixes)
            reject_counts: Counter[str] = Counter()
            for row in [*fix_rejects, *period_rejects]:
                reject_counts[str(row.reason)] += int(row.count)
            out.append(
                {
                    "dataset": dataset,
                    "cadence_sec": int(cadence_sec),
                    "grid_side": int(grid_side),
                    "n_devices": len({row["device_id"] for row in raw}),
                    "n_raw_points": len(raw),
                    "n_native_trips": len({row["trip_id"] for row in native}),
                    "n_resampled_fixes": len(fixes),
                    **run_stats,
                    "n_periods": len(periods),
                    "n_periods_with_outage": sum(1 for period in periods if int(period["n_outage_intervals"]) > 0),
                    "max_intra_period_dt": max([int(period["max_intra_period_dt"]) for period in periods] or [0]),
                    "n_witness_input_ok": witness_ok,
                    **tariff_capacity_stats,
                    "tariff_cells_used": len({int(fix["cell_idx"]) for fix in fixes}),
                    "tariff_cells_capacity": int(grid_side) * int(grid_side),
                    "block_global_cell_x_min": int(block.global_cell_x_min),
                    "block_global_cell_y_min": int(block.global_cell_y_min),
                    **block_stats,
                    **placement_stats,
                    **rebase_stats,
                    **period_stats,
                    "top_reject_reasons": " ".join(f"{k}:{v}" for k, v in reject_counts.most_common(5)),
                    "status": "ok" if periods else "empty",
                }
            )
    return out


def _tariff_capacity_stats(tariff, *, grid_side: int) -> dict[str, Any]:
    leaf_capacity = 1 << int(TREE_DEPTH)
    leaf_count = len(tariff.cell_zones)
    nonzero_cells = sum(
        1
        for zone_id in tariff.cell_zones.values()
        if int(tariff.rate_for_zone(int(zone_id))) > 0
    )
    return {
        "grid_cells": int(grid_side) * int(grid_side),
        "tariff_leaf_count": int(leaf_count),
        "tariff_leaf_capacity": int(leaf_capacity),
        "tariff_leaf_capacity_ok": str(int(leaf_count) <= int(leaf_capacity)),
        "tariff_nonzero_rate_cells": int(nonzero_cells),
        "tariff_nonzero_rate_cells_fit_leaf_capacity": str(int(nonzero_cells) <= int(leaf_capacity)),
    }


def _witness_smoke_count(
    periods: list[dict[str, Any]],
    tariff,
    *,
    cadence_sec: int,
    max_dt_sec: int,
    tier_vmax_mps: int,
    limit: int = 10,
) -> int:
    count = 0
    params = HarnessParams(cadence_sec=cadence_sec, max_dt_sec=max_dt_sec, tier_vmax_mps=tier_vmax_mps)
    for period in periods[: max(0, int(limit))]:
        try:
            build_raw_witness_input_for_fixes(receiver_fixes_from_period(period), tariff, params=params)
        except Exception:
            continue
        count += 1
    return count


def _block_location_stats(block) -> dict[str, Any]:
    lat_min, lon_min = global_cell_center_latlon(
        int(block.global_cell_x_min),
        int(block.global_cell_y_min),
        origin_lat=block.origin_lat,
        origin_lon=block.origin_lon,
        cell_size_m=block.cell_size_m,
    )
    lat_max, lon_max = global_cell_center_latlon(
        int(block.global_cell_x_min) + int(block.width) - 1,
        int(block.global_cell_y_min) + int(block.width) - 1,
        origin_lat=block.origin_lat,
        origin_lon=block.origin_lon,
        cell_size_m=block.cell_size_m,
    )
    center_lat, center_lon = global_cell_center_latlon(
        int(block.global_cell_x_min) + int(block.width) // 2,
        int(block.global_cell_y_min) + int(block.width) // 2,
        origin_lat=block.origin_lat,
        origin_lon=block.origin_lon,
        cell_size_m=block.cell_size_m,
    )
    return {
        "block_lat_min": round(min(lat_min, lat_max), 6),
        "block_lat_max": round(max(lat_min, lat_max), 6),
        "block_lon_min": round(min(lon_min, lon_max), 6),
        "block_lon_max": round(max(lon_min, lon_max), 6),
        "block_center_lat": round(center_lat, 6),
        "block_center_lon": round(center_lon, 6),
    }


def _placement_stats(rows: list[dict[str, Any]], block, *, moving_only: bool) -> dict[str, str]:
    visits: set[tuple[str, int, int]] = set()
    placement_rows = [
        row
        for row in rows
        if not moving_only or int(row.get("native_step_distance_m", 1)) > 0
    ]
    if not placement_rows:
        placement_rows = rows
    for row in placement_rows:
        from common.trajectory_preprocess import project_xy_m

        x_m, y_m = project_xy_m(float(row["lat"]), float(row["lon"]), block.origin_lat, block.origin_lon)
        visits.add((str(row["device_id"]), int(x_m // int(block.cell_size_m)), int(y_m // int(block.cell_size_m))))
    counts = Counter((gx, gy) for _device, gx, gy in visits)
    top = " ".join(f"{gx}:{gy}:{count}" for (gx, gy), count in counts.most_common(5))
    return {"top_placement_cells": top}


def _rebase_diff_stats(rebased_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rebased_rows:
        if "t_unix_original" in row:
            grouped[str(row["device_id"])].append(row)

    sample_device = ""
    sample_n_dts = 0
    sample_match = ""
    sample_max_abs_delta = ""
    devices_with_mismatch = 0
    for device_id, rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        rows.sort(key=lambda row: int(row["t_unix"]))
        deltas = []
        for prev, cur in zip(rows, rows[1:]):
            rebased_dt = int(cur["t_unix"]) - int(prev["t_unix"])
            original_dt = int(cur["t_unix_original"]) - int(prev["t_unix_original"])
            deltas.append(rebased_dt - original_dt)
        if any(delta != 0 for delta in deltas):
            devices_with_mismatch += 1
        if not sample_device:
            sample_device = device_id
            sample_n_dts = len(deltas)
            sample_match = str(all(delta == 0 for delta in deltas))
            sample_max_abs_delta = max([abs(delta) for delta in deltas] or [0])

    return {
        "rebase_sample_device_id": sample_device,
        "rebase_sample_n_dts": sample_n_dts,
        "rebase_sample_dt_match": sample_match,
        "rebase_sample_max_abs_dt_delta": sample_max_abs_delta,
        "rebase_devices_with_dt_mismatch": devices_with_mismatch,
    }


def _first_period_introspection(periods: list[dict[str, Any]], fixes: list[dict[str, Any]]) -> dict[str, Any]:
    empty = {
        "first_period_id": "",
        "first_period_device_id": "",
        "first_period_trip_id": "",
        "first_period_span_sec": "",
        "first_period_original_span_sec": "",
        "first_period_max_dt_sec": "",
        "first_period_max_original_dt_sec": "",
        "first_period_rebase_dt_match": "",
        "first_period_start_original_unix": "",
        "first_period_end_original_unix": "",
    }
    if not periods:
        return empty
    period = periods[0]
    segment_rows = [
        row
        for row in fixes
        if str(row.get("device_id")) == str(period["device_id"])
        and str(row.get("trip_id")) == str(period["trip_id"])
        and str(row.get("tariff_segment_id")) == str(period["tariff_segment_id"])
        and int(period["period_start_time"]) <= int(row["t_unix"]) <= int(period["period_end_time"])
    ]
    segment_rows.sort(key=lambda row: int(row["t_unix"]))
    chunk = segment_rows[:N_PERIOD_FIXES]
    rebased_dts = [int(cur["t_unix"]) - int(prev["t_unix"]) for prev, cur in zip(chunk, chunk[1:])]
    original_dts = [
        int(cur["t_unix_original"]) - int(prev["t_unix_original"])
        for prev, cur in zip(chunk, chunk[1:])
        if "t_unix_original" in prev and "t_unix_original" in cur
    ]
    out = dict(empty)
    out.update(
        {
            "first_period_id": str(period["period_id"]),
            "first_period_device_id": str(period["device_id"]),
            "first_period_trip_id": str(period["trip_id"]),
            "first_period_span_sec": int(period["period_span_sec"]),
            "first_period_max_dt_sec": max(rebased_dts or [0]),
        }
    )
    if len(chunk) == N_PERIOD_FIXES and len(original_dts) == N_PERIOD_FIXES - 1:
        out.update(
            {
                "first_period_original_span_sec": int(chunk[-1]["t_unix_original"]) - int(chunk[0]["t_unix_original"]),
                "first_period_max_original_dt_sec": max(original_dts or [0]),
                "first_period_rebase_dt_match": str(rebased_dts == original_dts),
                "first_period_start_original_unix": int(chunk[0]["t_unix_original"]),
                "first_period_end_original_unix": int(chunk[-1]["t_unix_original"]),
            }
        )
    return out


def _run_stats(fixes: list[dict[str, Any]]) -> dict[str, int]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fix in fixes:
        grouped[(str(fix["device_id"]), str(fix["trip_id"]), str(fix["tariff_segment_id"]))].append(fix)
    run_lengths: list[int] = []
    candidate_windows = 0
    span_ok = 0
    positive_odo = 0
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["t_unix"]))
        run_lengths.append(len(rows))
        for start in range(0, max(0, len(rows) - N_PERIOD_FIXES + 1), N_PERIOD_FIXES):
            chunk = rows[start : start + N_PERIOD_FIXES]
            candidate_windows += 1
            if int(chunk[-1]["t_unix"]) - int(chunk[0]["t_unix"]) <= PERIOD_MAX_SEC:
                span_ok += 1
                if int(chunk[-1]["odometer_reading_m"]) - int(chunk[0]["odometer_reading_m"]) > 0:
                    positive_odo += 1
    return {
        "n_runs": len(run_lengths),
        "max_run_len": max(run_lengths or [0]),
        "p95_run_len": _percentile_int(run_lengths, 0.95),
        "n_runs_ge_25": sum(1 for value in run_lengths if value >= N_PERIOD_FIXES),
        "n_candidate_25_windows": candidate_windows,
        "n_candidate_25_windows_span_ok": span_ok,
        "n_candidate_25_windows_positive_odo": positive_odo,
    }


def _percentile_int(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * float(q)))))
    return int(ordered[idx])


def _iter_raw(dataset: str):
    if dataset == "tdrive":
        return iter_tdrive_raw_points(DATASET_DIR / "T-Drive")
    if dataset == "geolife":
        return iter_geolife_driving_raw_points(DATASET_DIR / "Geolife Trajectories 1.3" / "Data")
    if dataset == "porto":
        return iter_porto_raw_points(DATASET_DIR / "porto" / "train.csv")
    if dataset == "rome":
        return iter_rome_raw_points(DATASET_DIR / "Rome.txt")
    raise ValueError(dataset)


def _load_geometry(city: str, granularity: str, cell_size_m: int):
    fallback = tariff_at_granularity(city, granularity, grid_w=16, cell_size_m=cell_size_m)
    overlay = DATASET_DIR / "osm" / "zones" / f"{city}_{granularity}.geojson"
    if not overlay.exists():
        return fallback
    return tariff_from_geojson(
        overlay,
        city=city,
        granularity=granularity,
        origin_lat=fallback.origin_lat,
        origin_lon=fallback.origin_lon,
        grid_w=16,
        cell_size_m=cell_size_m,
    )


def _limit(rows: Iterable[Any], max_rows: int) -> Iterable[Any]:
    if int(max_rows) <= 0:
        return rows

    def gen():
        for idx, row in enumerate(rows):
            if idx >= int(max_rows):
                break
            yield row

    return gen()


if __name__ == "__main__":
    raise SystemExit(main())
