#!/usr/bin/env python3
"""Analysis-only sweep of period length (N_FIXES) against the in-region run-length
distribution, to find the N that maximizes provable yield without trivializing the
settlement-period claim.

No circuit work: this reuses the preprocessing pipeline (clean -> rebase -> segment ->
resample) ONCE per (dataset, grid, cadence) config, then re-buckets the resulting fixes
into N-fix windows for each candidate N. The window validity proxy mirrors
diagnose_tier1_grid_yield._run_stats (span <= PERIOD_MAX_SEC, positive odometer delta),
which is what build_period_records ultimately gates on for Tier-1 periods.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.osm_vectors import tariff_at_granularity, tariff_from_geojson  # noqa: E402
from common.trajectory_preprocess import (  # noqa: E402
    CELL_SIZE_M,
    CITY_BBOX,
    DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M,
    LEGAL_CADENCES,
    MAX_DT_SEC,
    PERIOD_MAX_SEC,
    REBASE_ANCHOR,
    TRIP_GAP_SEC,
    build_local_tariff_table,
    build_resampled_fixes,
    choose_density_peak_block,
    clean_raw_points,
    iter_geolife_driving_raw_points,
    iter_porto_raw_points,
    iter_rome_raw_points,
    iter_tdrive_raw_points,
    rebase_points_to_2026,
    segment_native_trips,
)

DATASET_DIR = ROOT_DIR / "dataset"
FIELDS = [
    "dataset",
    "cadence_sec",
    "grid_side",
    "n_fixes",
    "span_max_sec",
    "n_runs",
    "n_runs_ge_n",
    "n_candidate_windows",
    "n_candidate_windows_span_ok",
    "n_candidate_windows_positive_odo",
    "est_provable_periods",
    "n_devices_with_period",
    "frac_runs_ge_n",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep N_FIXES against run-length distribution (analysis only).")
    parser.add_argument("--dataset", choices=["tdrive", "geolife", "porto", "rome", "all"], default="geolife")
    parser.add_argument("--grid-sides", nargs="+", type=int, default=[6, 16])
    parser.add_argument("--n-values", nargs="+", type=int, default=list(range(5, 26)))
    parser.add_argument("--cadences", nargs="+", type=int, default=[])
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "data" / "processed" / "n_fixes_sweep.csv")
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
        rows.extend(_sweep_dataset(dataset, args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))
    return 0


def _sweep_dataset(dataset: str, args: argparse.Namespace) -> list[dict[str, Any]]:
    city = "beijing" if dataset in {"tdrive", "geolife"} else dataset
    geometry = _load_geometry(city, args.granularity, args.cell_size_m)
    raw, _ = clean_raw_points(dataset, _limit(_iter_raw(dataset), args.max_raw_points), city_bbox=CITY_BBOX[city])
    rebased = rebase_points_to_2026(raw, anchor=REBASE_ANCHOR)
    native, _ = segment_native_trips(dataset, rebased, gap_sec=args.trip_gap_sec)
    cadences = args.cadences or list(LEGAL_CADENCES[dataset])
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
        for cadence_sec in cadences:
            fixes, _ = build_resampled_fixes(
                dataset,
                native,
                cadence_sec=cadence_sec,
                block=block,
                tariff=tariff,
                tier_vmax_mps=args.tier_vmax_mps,
                max_dt_sec=args.max_dt_sec,
                outage_bridge_max_odo_m=args.outage_bridge_max_odo_m,
            )
            runs = _build_runs(fixes)
            for n_fixes in args.n_values:
                out.append(_sweep_row(dataset, cadence_sec, int(grid_side), int(n_fixes), runs))
    return out


def _build_runs(fixes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fix in fixes:
        grouped[(str(fix["device_id"]), str(fix["trip_id"]), str(fix["tariff_segment_id"]))].append(fix)
    runs = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["t_unix"]))
        runs.append(rows)
    return runs


def _sweep_row(dataset: str, cadence_sec: int, grid_side: int, n_fixes: int, runs: list[list[dict[str, Any]]]) -> dict[str, Any]:
    n_runs = len(runs)
    n_runs_ge_n = 0
    candidate_windows = 0
    span_ok = 0
    positive_odo = 0
    span_max = 0
    devices_with_period: set[str] = set()
    for rows in runs:
        if len(rows) >= n_fixes:
            n_runs_ge_n += 1
        for start in range(0, max(0, len(rows) - n_fixes + 1), n_fixes):
            chunk = rows[start : start + n_fixes]
            candidate_windows += 1
            span = int(chunk[-1]["t_unix"]) - int(chunk[0]["t_unix"])
            span_max = max(span_max, span)
            if span <= PERIOD_MAX_SEC:
                span_ok += 1
                if int(chunk[-1]["odometer_reading_m"]) - int(chunk[0]["odometer_reading_m"]) > 0:
                    positive_odo += 1
                    devices_with_period.add(str(chunk[0]["device_id"]))
    return {
        "dataset": dataset,
        "cadence_sec": int(cadence_sec),
        "grid_side": int(grid_side),
        "n_fixes": int(n_fixes),
        "span_max_sec": int(span_max),
        "n_runs": int(n_runs),
        "n_runs_ge_n": int(n_runs_ge_n),
        "n_candidate_windows": int(candidate_windows),
        "n_candidate_windows_span_ok": int(span_ok),
        "n_candidate_windows_positive_odo": int(positive_odo),
        "est_provable_periods": int(positive_odo),
        "n_devices_with_period": len(devices_with_period),
        "frac_runs_ge_n": round(n_runs_ge_n / n_runs, 4) if n_runs else 0.0,
    }


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
