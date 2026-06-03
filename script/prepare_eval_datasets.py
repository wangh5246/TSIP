#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams
from common.osm_vectors import tariff_at_granularity, tariff_from_geojson
from common.trajectory_preprocess import (
    IdentityMatcher,
    PreparedTrip,
    iter_geolife_driving_trips,
    iter_porto_trips,
    iter_rome_trips,
    iter_tdrive_trips,
    prepare_trip,
    write_jsonl,
)


DATASET_DIR = ROOT_DIR / "dataset"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare TSIP-RUC E1-E4 trajectories with the shared identity pipeline.")
    parser.add_argument("--dataset", choices=["tdrive", "geolife", "porto", "rome", "all"], default="all")
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "experiments" / "eval_ready")
    parser.add_argument("--max-trips", type=int, default=20, help="Per-dataset cap; use 0 for all trips.")
    parser.add_argument("--max-scan-trips", type=int, default=5000, help="Candidate scan cap after filtering; use 0 for unlimited.")
    parser.add_argument("--gap-sec", type=int, default=120)
    parser.add_argument("--cadence-sec", type=int, default=30)
    parser.add_argument("--cell-size-m", type=int, default=100)
    parser.add_argument("--grid-w", type=int, default=100)
    parser.add_argument("--granularity", choices=["coarse", "medium", "fine"], default="medium")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = ["tdrive", "geolife", "porto", "rome"] if args.dataset == "all" else [args.dataset]
    matcher = IdentityMatcher()
    summary: dict[str, dict] = {}
    for dataset in selected:
        city = "beijing" if dataset in {"tdrive", "geolife"} else dataset
        geometry, tariff_source = _load_tariff(city, args.granularity, args.grid_w, args.cell_size_m)
        tariff = geometry.to_table()
        params = HarnessParams(cadence_sec=args.cadence_sec, cell_size_m=args.cell_size_m)
        prepared = _prepare_source(
            dataset,
            _iter_source(dataset, args.gap_sec),
            matcher=matcher,
            tariff=tariff,
            params=params,
            cadence_sec=args.cadence_sec,
            origin_lat=geometry.origin_lat,
            origin_lon=geometry.origin_lon,
            max_trips=args.max_trips,
            max_scan_trips=args.max_scan_trips,
        )
        output = args.output_dir / f"{dataset}_{args.granularity}_{matcher.name}.jsonl"
        count = write_jsonl(output, prepared)
        summary[dataset] = {"output": str(output), "trips": count, "matcher": matcher.name, "city": city, "tariff_source": tariff_source}
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


def _prepare_source(dataset, source, *, matcher, tariff, params, cadence_sec, origin_lat, origin_lon, max_trips, max_scan_trips):
    emitted = 0
    for scanned, (trip_id, points) in enumerate(source, start=1):
        if max_scan_trips > 0 and scanned > max_scan_trips:
            return
        trip = prepare_trip(
            dataset,
            trip_id,
            points,
            matcher=matcher,
            tariff=tariff,
            params=params,
            cadence_sec=cadence_sec,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
        )
        if trip is None:
            continue
        yield trip
        emitted += 1
        if max_trips > 0 and emitted >= max_trips:
            return


def _iter_source(dataset: str, gap_sec: int):
    if dataset == "tdrive":
        return iter_tdrive_trips(DATASET_DIR / "T-Drive", gap_sec=gap_sec)
    if dataset == "geolife":
        return iter_geolife_driving_trips(DATASET_DIR / "Geolife Trajectories 1.3" / "Data", gap_sec=gap_sec)
    if dataset == "porto":
        return iter_porto_trips(DATASET_DIR / "porto" / "train.csv")
    if dataset == "rome":
        return iter_rome_trips(DATASET_DIR / "Rome.txt", gap_sec=gap_sec)
    raise ValueError(dataset)


def _load_tariff(city: str, granularity: str, grid_w: int, cell_size_m: int):
    fallback = tariff_at_granularity(city, granularity, grid_w=grid_w, cell_size_m=cell_size_m)
    overlay = DATASET_DIR / "osm" / "zones" / f"{city}_{granularity}.geojson"
    if not overlay.exists():
        return fallback, "provisional_builtin"
    return (
        tariff_from_geojson(
            overlay,
            city=city,
            granularity=granularity,
            origin_lat=fallback.origin_lat,
            origin_lon=fallback.origin_lon,
            grid_w=grid_w,
            cell_size_m=cell_size_m,
        ),
        str(overlay),
    )


if __name__ == "__main__":
    raise SystemExit(main())
