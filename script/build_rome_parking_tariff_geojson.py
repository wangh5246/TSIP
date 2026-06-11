#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.osm_vectors import tariff_at_granularity


STRISCE_BLU_URL = (
    "https://services2.arcgis.com/NZMqCJwY3kMjFOqf/arcgis/rest/services/"
    "strisce_blu_strade/FeatureServer/0/query?"
    "where=1%3D1&outFields=FID,TOPONIMO,ZONA,AMBITO,GIORNI,DALLE,ALLE,TARIFFA"
    "&returnGeometry=true&outSR=4326&f=geojson&resultRecordCount=2000"
)
ZTL_URL = (
    "https://services2.arcgis.com/NZMqCJwY3kMjFOqf/arcgis/rest/services/"
    "confini_ZTL_centro_diurna/FeatureServer/0/query?"
    "where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson&resultRecordCount=2000"
)
RATE_MAP = {
    "0,50 euro/h": 5,
    "1 euro/h": 10,
    "1,20 euro/h": 12,
}
EARTH_RADIUS_M = 6_371_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Rome tariff polygon overlay from the official Roma Mobilita "
            "blue-stripe parking FeatureServer."
        )
    )
    parser.add_argument("--strisce-source", default=STRISCE_BLU_URL, help="GeoJSON file or URL for strisce_blu_strade.")
    parser.add_argument("--ztl-source", default=ZTL_URL, help="GeoJSON file or URL for ZTL boundary provenance.")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_DIR / "dataset" / "osm" / "zones" / "rome_medium.geojson",
    )
    parser.add_argument("--raw-output-dir", type=Path, help="Optional directory for cached official source GeoJSON.")
    parser.add_argument("--granularity", default="medium", choices=["coarse", "medium", "fine"])
    parser.add_argument("--grid-w", type=int, default=100)
    parser.add_argument("--cell-size-m", type=int, default=100)
    parser.add_argument("--nearest-bucket-m", type=int, default=500)
    parser.add_argument(
        "--max-nearest-m",
        type=float,
        default=2_000.0,
        help="Fail if any generated cell center is farther than this from an official blue-stripe segment.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    strisce = _load_geojson(args.strisce_source)
    ztl = _load_geojson(args.ztl_source)
    if args.raw_output_dir:
        args.raw_output_dir.mkdir(parents=True, exist_ok=True)
        (args.raw_output_dir / "rome_strisce_blu_strade.geojson").write_text(
            json.dumps(strisce, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (args.raw_output_dir / "rome_ztl_centro_diurna.geojson").write_text(
            json.dumps(ztl, ensure_ascii=True, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    fallback = tariff_at_granularity("rome", args.granularity, grid_w=args.grid_w, cell_size_m=args.cell_size_m)
    segments = _parking_segments(strisce, origin_lat=fallback.origin_lat, origin_lon=fallback.origin_lon)
    if not segments:
        raise SystemExit("no usable parking line segments found in strisce_blu source")
    assignments = _assign_grid(
        segments,
        origin_lat=fallback.origin_lat,
        origin_lon=fallback.origin_lon,
        grid_w=args.grid_w,
        cell_size_m=args.cell_size_m,
        bucket_m=args.nearest_bucket_m,
    )
    farthest = max(float(cell["nearest_distance_m"]) for row in assignments for cell in row)
    if farthest > args.max_nearest_m:
        raise SystemExit(
            f"nearest blue-stripe segment is too far for at least one cell: {farthest:.1f}m > {args.max_nearest_m:.1f}m"
        )

    features = _row_run_features(
        assignments,
        origin_lat=fallback.origin_lat,
        origin_lon=fallback.origin_lon,
        grid_w=args.grid_w,
        cell_size_m=args.cell_size_m,
    )
    output = {
        "type": "FeatureCollection",
        "metadata": {
            "city": "rome",
            "granularity": args.granularity,
            "source": "Roma Mobilita public ArcGIS FeatureServer, Sosta tariffata web map",
            "webmap_item": "b7be6a72ce2b4e54b1b9adde1a11df8f",
            "app_item": "962c8b4334d74dc6ae043a5e4b8643d0",
            "strisce_blu_layer": STRISCE_BLU_URL.split("/query?", 1)[0],
            "ztl_layer": ZTL_URL.split("/query?", 1)[0],
            "rate_mapping": RATE_MAP,
            "rate_mapping_note": "Preserves official hourly-rate ratios exactly using integer cents-per-meter tiers.",
            "method_doc": "dataset/osm/zones/README_rome_tariff.md",
            "grid_w": args.grid_w,
            "cell_size_m": args.cell_size_m,
            "origin_lat": fallback.origin_lat,
            "origin_lon": fallback.origin_lon,
            "assignment": "Each tariff grid cell is assigned the normalized rate of the nearest official blue-stripe street segment.",
            "ztl_feature_count": len(ztl.get("features", [])),
            "source_feature_count": len(strisce.get("features", [])),
            "source_segment_count": len(segments),
            "max_nearest_distance_m": round(farthest, 3),
        },
        "features": features,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    summary = _summary(assignments, features)
    summary["output"] = str(args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


def _load_geojson(source: str) -> dict[str, Any]:
    path = Path(source)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    request = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _parking_segments(payload: dict[str, Any], *, origin_lat: float, origin_lon: float) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        raw_tariff = str(props.get("TARIFFA", "")).strip()
        if raw_tariff not in RATE_MAP:
            continue
        geometry = feature.get("geometry") or {}
        for line in _iter_lines(geometry):
            for start, end in zip(line, line[1:]):
                x1, y1 = _project_xy_m(float(start[1]), float(start[0]), origin_lat, origin_lon)
                x2, y2 = _project_xy_m(float(end[1]), float(end[0]), origin_lat, origin_lon)
                if x1 == x2 and y1 == y2:
                    continue
                segments.append(
                    {
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2,
                        "rate": int(RATE_MAP[raw_tariff]),
                        "source_tariff": raw_tariff,
                        "source_fid": props.get("FID"),
                        "source_zona": props.get("ZONA"),
                        "source_ambito": props.get("AMBITO"),
                    }
                )
    return segments


def _iter_lines(geometry: dict[str, Any]) -> Iterable[list[list[float]]]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates", [])
    if kind == "LineString":
        yield coords
    elif kind == "MultiLineString":
        yield from coords


def _assign_grid(
    segments: list[dict[str, Any]],
    *,
    origin_lat: float,
    origin_lon: float,
    grid_w: int,
    cell_size_m: int,
    bucket_m: int,
) -> list[list[dict[str, Any]]]:
    buckets = _segment_buckets(segments, bucket_m=bucket_m)
    half = grid_w * cell_size_m / 2.0
    rows: list[list[dict[str, Any]]] = []
    for y in range(grid_w):
        row: list[dict[str, Any]] = []
        cy = (y + 0.5) * cell_size_m - half
        for x in range(grid_w):
            cx = (x + 0.5) * cell_size_m - half
            segment, dist = _nearest_segment(cx, cy, segments, buckets, bucket_m=bucket_m)
            lat, lon = _xy_to_latlon(cx, cy, origin_lat, origin_lon)
            row.append(
                {
                    "x": x,
                    "y": y,
                    "lat": lat,
                    "lon": lon,
                    "rate": int(segment["rate"]),
                    "source_tariff": segment["source_tariff"],
                    "source_fid": segment["source_fid"],
                    "source_zona": segment["source_zona"],
                    "source_ambito": segment["source_ambito"],
                    "nearest_distance_m": dist,
                }
            )
        rows.append(row)
    return rows


def _segment_buckets(segments: list[dict[str, Any]], *, bucket_m: int) -> dict[tuple[int, int], list[int]]:
    buckets: dict[tuple[int, int], list[int]] = {}
    for idx, seg in enumerate(segments):
        min_x = min(float(seg["x1"]), float(seg["x2"]))
        max_x = max(float(seg["x1"]), float(seg["x2"]))
        min_y = min(float(seg["y1"]), float(seg["y2"]))
        max_y = max(float(seg["y1"]), float(seg["y2"]))
        bx0 = math.floor(min_x / bucket_m)
        bx1 = math.floor(max_x / bucket_m)
        by0 = math.floor(min_y / bucket_m)
        by1 = math.floor(max_y / bucket_m)
        for bx in range(bx0, bx1 + 1):
            for by in range(by0, by1 + 1):
                buckets.setdefault((bx, by), []).append(idx)
    return buckets


def _nearest_segment(
    x: float,
    y: float,
    segments: list[dict[str, Any]],
    buckets: dict[tuple[int, int], list[int]],
    *,
    bucket_m: int,
) -> tuple[dict[str, Any], float]:
    bx = math.floor(x / bucket_m)
    by = math.floor(y / bucket_m)
    candidate_ids: set[int] = set()
    for radius in range(0, 8):
        for cx in range(bx - radius, bx + radius + 1):
            for cy in range(by - radius, by + radius + 1):
                candidate_ids.update(buckets.get((cx, cy), []))
        if candidate_ids and radius >= 2:
            break
    if not candidate_ids:
        candidate_ids.update(range(len(segments)))
    best_idx = -1
    best_dist2 = float("inf")
    for idx in candidate_ids:
        seg = segments[idx]
        dist2 = _point_segment_distance2(x, y, float(seg["x1"]), float(seg["y1"]), float(seg["x2"]), float(seg["y2"]))
        if dist2 < best_dist2:
            best_idx = idx
            best_dist2 = dist2
    return segments[best_idx], math.sqrt(best_dist2)


def _row_run_features(
    assignments: list[list[dict[str, Any]]],
    *,
    origin_lat: float,
    origin_lon: float,
    grid_w: int,
    cell_size_m: int,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    zone_id_for_rate = {5: 50, 10: 100, 12: 120}
    for y, row in enumerate(assignments):
        x0 = 0
        while x0 < grid_w:
            rate = int(row[x0]["rate"])
            x1 = x0 + 1
            while x1 < grid_w and int(row[x1]["rate"]) == rate:
                x1 += 1
            cells = row[x0:x1]
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "zone_id": zone_id_for_rate[rate],
                        "rate_cents_per_m": rate,
                        "source": "rome_strisce_blu_nearest_grid",
                        "source_tariffs": sorted({str(cell["source_tariff"]) for cell in cells}),
                        "source_zonas": sorted({str(cell["source_zona"]) for cell in cells if cell["source_zona"] is not None}),
                        "source_ambiti": sorted({str(cell["source_ambito"]) for cell in cells if cell["source_ambito"] is not None}),
                        "nearest_distance_m_max": round(max(float(cell["nearest_distance_m"]) for cell in cells), 3),
                        "grid_y": y,
                        "grid_x_min": x0,
                        "grid_x_max_exclusive": x1,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            _grid_rect_ring(
                                x0,
                                y,
                                x1,
                                y + 1,
                                origin_lat=origin_lat,
                                origin_lon=origin_lon,
                                grid_w=grid_w,
                                cell_size_m=cell_size_m,
                            )
                        ],
                    },
                }
            )
            x0 = x1
    return features


def _grid_rect_ring(
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    *,
    origin_lat: float,
    origin_lon: float,
    grid_w: int,
    cell_size_m: int,
) -> list[list[float]]:
    half = grid_w * cell_size_m / 2.0
    west = x0 * cell_size_m - half
    east = x1 * cell_size_m - half
    south = y0 * cell_size_m - half
    north = y1 * cell_size_m - half
    corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    return [[lon, lat] for lat, lon in (_xy_to_latlon(x, y, origin_lat, origin_lon) for x, y in corners)]


def _summary(assignments: list[list[dict[str, Any]]], features: list[dict[str, Any]]) -> dict[str, Any]:
    rate_hist = Counter(int(cell["rate"]) for row in assignments for cell in row)
    source_hist = Counter(str(cell["source_tariff"]) for row in assignments for cell in row)
    return {
        "features": len(features),
        "grid_cells": sum(rate_hist.values()),
        "rate_hist": dict(sorted(rate_hist.items())),
        "source_tariff_hist": dict(sorted(source_hist.items())),
        "nearest_distance_m": {
            "max": round(max(float(cell["nearest_distance_m"]) for row in assignments for cell in row), 3),
            "mean": round(
                sum(float(cell["nearest_distance_m"]) for row in assignments for cell in row) / max(1, sum(rate_hist.values())),
                3,
            ),
        },
    }


def _project_xy_m(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    x = math.radians(lon - lon0) * math.cos(math.radians((lat + lat0) / 2.0)) * EARTH_RADIUS_M
    y = math.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def _xy_to_latlon(x: float, y: float, lat0: float, lon0: float) -> tuple[float, float]:
    lat = lat0 + math.degrees(y / EARTH_RADIUS_M)
    lon = lon0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lat, lon


def _point_segment_distance2(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = min(1.0, max(0.0, t))
    qx = x1 + t * dx
    qy = y1 + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


if __name__ == "__main__":
    raise SystemExit(main())
