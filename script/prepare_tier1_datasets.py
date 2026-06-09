#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams  # noqa: E402
from common.osm_vectors import tariff_at_granularity, tariff_from_geojson  # noqa: E402
from common.trajectory_preprocess import (  # noqa: E402
    CELL_SIZE_M,
    CITY_BBOX,
    DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M,
    LEGAL_CADENCES,
    MAX_DT_SEC,
    N_PERIOD_FIXES,
    REBASE_ANCHOR,
    TRIP_GAP_SEC,
    build_local_tariff_table,
    build_period_records,
    build_resampled_fixes,
    choose_density_peak_block,
    clean_raw_points,
    iter_geolife_driving_raw_points,
    iter_porto_raw_points,
    iter_rome_raw_points,
    iter_tdrive_raw_points,
    rebase_points_to_2026,
    receiver_fixes_from_period,
    segment_native_trips,
)
from script.prove_settlement_period_v5 import build_raw_witness_input_for_fixes  # noqa: E402


DATASET_DIR = ROOT_DIR / "dataset"
FIELDNAMES_REJECTS = ["dataset", "cadence_sec", "device_id", "trip_id", "stage", "reason", "count"]
FIELDNAMES_MANIFEST = [
    "dataset",
    "cadence_sec",
    "legal_cadence",
    "n_devices",
    "n_raw_points",
    "n_native_trips",
    "n_resampled_fixes",
    "n_periods",
    "n_period_fixes",
    "n_outage_intervals",
    "n_periods_with_outage",
    "max_intra_period_dt",
    "n_witness_input_ok",
    "n_dropped_outside_tariff",
    "n_dropped_short_trips",
    "bbox_lat_min",
    "bbox_lat_max",
    "bbox_lon_min",
    "bbox_lon_max",
    "cell_x_min",
    "cell_x_max",
    "cell_y_min",
    "cell_y_max",
    "date_min_unix",
    "date_max_unix",
    "month_ids",
    "tariff_cells_used",
    "tariff_cells_capacity",
    "block_width",
    "block_global_cell_x_min",
    "block_global_cell_y_min",
    "projection",
    "status",
    "notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Tier-1 TSIP trajectory periods without map matching.")
    parser.add_argument("--dataset", choices=["tdrive", "geolife", "porto", "rome", "all"], default="tdrive")
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "data" / "processed")
    parser.add_argument("--granularity", choices=["coarse", "medium", "fine"], default="medium")
    parser.add_argument("--cell-size-m", type=int, default=CELL_SIZE_M)
    parser.add_argument("--block-width", type=int, default=16, help="Local tariff block width in cells; 16 gives 256 leaves.")
    parser.add_argument("--circuit-grid-w", type=int, default=100, help="Grid side baked into the settlement circuit cell_idx formula.")
    parser.add_argument("--trip-gap-sec", type=int, default=TRIP_GAP_SEC)
    parser.add_argument("--max-dt-sec", type=int, default=MAX_DT_SEC)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument("--outage-bridge-max-odo-m", type=int, default=DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M)
    parser.add_argument("--max-raw-points", type=int, default=0, help="Development cap; 0 means all points.")
    parser.add_argument("--witness-smoke-periods", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    _require_pyarrow()
    import pandas as pd

    args = parse_args()
    selected = ["tdrive", "geolife", "porto", "rome"] if args.dataset == "all" else [args.dataset]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, Any]] = []
    for dataset in selected:
        manifest_rows.extend(_prepare_dataset(dataset, args, pd))
    _write_csv(args.output_dir / "manifest.csv", FIELDNAMES_MANIFEST, manifest_rows)
    print(json.dumps({"manifest": str(args.output_dir / "manifest.csv"), "rows": len(manifest_rows)}, indent=2))
    return 0


def _prepare_dataset(dataset: str, args: argparse.Namespace, pd) -> list[dict[str, Any]]:
    city = "beijing" if dataset in {"tdrive", "geolife"} else dataset
    geometry = _load_geometry(city, args.granularity, args.cell_size_m)
    dataset_dir = args.output_dir / dataset
    dataset_dir.mkdir(parents=True, exist_ok=True)

    raw_points, stage0_rejects = clean_raw_points(
        dataset,
        _limit(_iter_raw(dataset), args.max_raw_points),
        city_bbox=CITY_BBOX[city],
    )
    rebased = rebase_points_to_2026(raw_points, anchor=REBASE_ANCHOR)
    native, stage2_rejects = segment_native_trips(dataset, rebased, gap_sec=args.trip_gap_sec)
    block = choose_density_peak_block(
        native or rebased,
        origin_lat=geometry.origin_lat,
        origin_lon=geometry.origin_lon,
        width=args.block_width,
        cell_size_m=args.cell_size_m,
        moving_only=True,
    )
    tariff = build_local_tariff_table(block, geometry, circuit_grid_w=args.circuit_grid_w)

    _write_parquet(pd, dataset_dir / "raw_points.parquet", rebased)
    _write_parquet(pd, dataset_dir / "trips_native.parquet", native)
    (dataset_dir / "tariff_block.json").write_text(
        json.dumps(
            {
                "dataset": dataset,
                "city": city,
                "granularity": args.granularity,
                "projection": "local_equirectangular_origin_city_center",
                "block": block.to_dict(),
                "tariff": {
                    "tariff_version": tariff.tariff_version,
                    "grid_w": tariff.grid_w,
                    "logical_block_width": block.width,
                    "cell_zones": tariff.cell_zones,
                    "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest_rows: list[dict[str, Any]] = []
    for cadence_sec in LEGAL_CADENCES[dataset]:
        fixes, cadence_rejects = build_resampled_fixes(
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
        _write_parquet(pd, dataset_dir / f"fixes_{cadence_sec}s.parquet", fixes)
        _write_jsonl(dataset_dir / f"periods_{cadence_sec}s.jsonl", periods)
        rejects = _cadence_rejects(cadence_sec, [*stage0_rejects, *stage2_rejects, *cadence_rejects, *period_rejects])
        _write_csv(dataset_dir / f"rejects_{cadence_sec}s.csv", FIELDNAMES_REJECTS, [row.to_dict() for row in rejects])
        witness_ok = _witness_smoke_count(periods, tariff, cadence_sec=cadence_sec, params=args)
        manifest_rows.append(_manifest_row(dataset, cadence_sec, rebased, native, fixes, periods, rejects, block, witness_ok))
    return manifest_rows


def _manifest_row(
    dataset: str,
    cadence_sec: int,
    raw_rows: list[dict[str, Any]],
    native_rows: list[dict[str, Any]],
    fixes: list[dict[str, Any]],
    periods: list[dict[str, Any]],
    rejects,
    block,
    witness_ok: int,
) -> dict[str, Any]:
    outside_tariff = sum(row.count for row in rejects if row.reason == "outside_tariff_region")
    short_trips = sum(row.count for row in rejects if row.reason == "too_few_points")
    months = sorted({int(period["month_id"]) for period in periods})
    n_outage = sum(int(period["n_outage_intervals"]) for period in periods)
    row = {
        "dataset": dataset,
        "cadence_sec": int(cadence_sec),
        "legal_cadence": int(cadence_sec) in LEGAL_CADENCES[dataset],
        "n_devices": len({row["device_id"] for row in raw_rows}),
        "n_raw_points": len(raw_rows),
        "n_native_trips": len({row["trip_id"] for row in native_rows}),
        "n_resampled_fixes": len(fixes),
        "n_periods": len(periods),
        "n_period_fixes": len(periods) * N_PERIOD_FIXES,
        "n_outage_intervals": n_outage,
        "n_periods_with_outage": sum(1 for period in periods if int(period["n_outage_intervals"]) > 0),
        "max_intra_period_dt": max([int(period["max_intra_period_dt"]) for period in periods] or [0]),
        "n_witness_input_ok": int(witness_ok),
        "n_dropped_outside_tariff": int(outside_tariff),
        "n_dropped_short_trips": int(short_trips),
        "bbox_lat_min": _min(raw_rows, "lat"),
        "bbox_lat_max": _max(raw_rows, "lat"),
        "bbox_lon_min": _min(raw_rows, "lon"),
        "bbox_lon_max": _max(raw_rows, "lon"),
        "cell_x_min": _min(fixes, "cell_x"),
        "cell_x_max": _max(fixes, "cell_x"),
        "cell_y_min": _min(fixes, "cell_y"),
        "cell_y_max": _max(fixes, "cell_y"),
        "date_min_unix": _min(raw_rows, "t_unix"),
        "date_max_unix": _max(raw_rows, "t_unix"),
        "month_ids": " ".join(str(month) for month in months),
        "tariff_cells_used": len({int(fix["cell_idx"]) for fix in fixes}),
        "tariff_cells_capacity": int(block.cells_capacity),
        "block_width": int(block.width),
        "block_global_cell_x_min": int(block.global_cell_x_min),
        "block_global_cell_y_min": int(block.global_cell_y_min),
        "projection": "local_equirectangular_origin_city_center",
        "status": "ok" if periods and len({int(fix["cell_idx"]) for fix in fixes}) <= int(block.cells_capacity) else "empty",
        "notes": f"tier1_no_map_matching_no_interpolation_{int(block.width)}x{int(block.width)}_density_peak",
    }
    return row


def _witness_smoke_count(periods: list[dict[str, Any]], tariff, *, cadence_sec: int, params: argparse.Namespace) -> int:
    count = 0
    harness_params = HarnessParams(cadence_sec=cadence_sec, max_dt_sec=params.max_dt_sec, tier_vmax_mps=params.tier_vmax_mps)
    for period in periods[: max(0, int(params.witness_smoke_periods))]:
        try:
            build_raw_witness_input_for_fixes(receiver_fixes_from_period(period), tariff, params=harness_params)
        except Exception:
            continue
        count += 1
    return count


def _iter_raw(dataset: str):
    if dataset == "tdrive":
        return iter_tdrive_raw_points(DATASET_DIR / "T-Drive")
    if dataset == "geolife":
        return iter_geolife_driving_raw_points(DATASET_DIR / "Geolife Trajectories 1.3" / "Data")
    if dataset == "porto":
        csv_path = DATASET_DIR / "porto" / "train.csv"
        zip_path = DATASET_DIR / "porto" / "train.csv.zip"
        return iter_porto_raw_points(csv_path if csv_path.exists() else zip_path)
    if dataset == "rome":
        rome_path = DATASET_DIR / "Rome.txt"
        roma_path = DATASET_DIR / "Roma.txt"
        return iter_rome_raw_points(rome_path if rome_path.exists() else roma_path)
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


def _cadence_rejects(cadence_sec: int, rejects) -> list:
    return [
        type(row)(
            row.dataset,
            int(cadence_sec),
            row.device_id,
            row.trip_id,
            row.stage,
            row.reason,
            row.count,
        )
        for row in rejects
    ]


def _write_parquet(pd, path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    try:
        frame.to_parquet(path, index=False, engine="pyarrow")
    except (ImportError, OSError):
        frame.to_csv(path.with_suffix(".csv"), index=False)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _require_pyarrow() -> None:
    try:
        import pyarrow  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit("pyarrow is required for Tier-1 parquet output; install it in .venv first") from exc


def _min(rows: list[dict[str, Any]], key: str) -> Any:
    values = [row[key] for row in rows if key in row and row[key] is not None]
    return min(values) if values else ""


def _max(rows: list[dict[str, Any]], key: str) -> Any:
    values = [row[key] for row in rows if key in row and row[key] is not None]
    return max(values) if values else ""


if __name__ == "__main__":
    raise SystemExit(main())
