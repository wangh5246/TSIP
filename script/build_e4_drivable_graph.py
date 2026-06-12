"""E4 upgrade: replace the observed-grid road universe with the real drivable graph.

For each dataset whose tariff_block.json carries the Tier-1 block geo anchor
(porto, rome, tdrive/beijing), this clips the city PBF to the proof-compatible
tariff footprint with osmium, loads the drivable network with pyrosm, and
recomputes the E4 spot-check camera requirement against the real road
universe instead of the observed-path proxy.

GeoLife uses the centred-grid anchor recovered on 2026-06-12: the builtin
Beijing geometry (tariff_at_granularity) reproduces its archived cell_zones
byte-for-byte, so its footprint is the 10km x 10km grid centred on the city
origin. T-Drive provides the density-peak block on the same Beijing PBF.

Segment unit: the proxy counts observed 100m tariff-grid transitions, so the
real graph is normalized to 100m segments (road_length_m / 100) to keep
`segments_per_driver` and the camera math in the same unit.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_experiments import e4_required_cameras  # noqa: E402

EARTH_RADIUS_M = 6_371_000.0
SEGMENT_UNIT_M = 100.0
PBF_BY_DATASET = {
    "porto": ROOT_DIR / "dataset" / "osm" / "portugal-latest.osm.pbf",
    "rome": ROOT_DIR / "dataset" / "osm" / "centro-latest.osm.pbf",
    "tdrive": ROOT_DIR / "dataset" / "osm" / "beijing.osm.pbf",
}
TARIFF_BLOCKS = {
    dataset: ROOT_DIR / "data" / "e1_mechanism_ablation" / dataset / "tariff_block.json"
    for dataset in PBF_BY_DATASET
}
PROXY_SUMMARY = ROOT_DIR / "experiments" / "e4_e5_ruc" / "e4_spotcheck_summary.csv"


def footprint_bbox(block: dict, *, margin_m: float) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) of the tariff footprint."""

    cell = float(block["cell_size_m"])
    east_min = float(block["global_cell_x_min"]) * cell - margin_m
    east_max = (float(block["global_cell_x_min"]) + float(block["width"])) * cell + margin_m
    north_min = float(block["global_cell_y_min"]) * cell - margin_m
    north_max = (float(block["global_cell_y_min"]) + float(block["width"])) * cell + margin_m
    origin_lat = float(block["origin_lat"])
    origin_lon = float(block["origin_lon"])

    def lat(north: float) -> float:
        return origin_lat + math.degrees(north / EARTH_RADIUS_M)

    def lon(east: float) -> float:
        return origin_lon + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(origin_lat))))

    return (lon(east_min), lat(north_min), lon(east_max), lat(north_max))


def clip_pbf(src: Path, bbox: tuple[float, float, float, float], dst: Path) -> None:
    cmd = [
        "osmium",
        "extract",
        "-b",
        ",".join(f"{v:.6f}" for v in bbox),
        str(src),
        "-o",
        str(dst),
        "--overwrite",
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def drivable_stats(clip_path: Path) -> dict[str, float]:
    from pyrosm import OSM

    osm = OSM(str(clip_path))
    edges = osm.get_network(network_type="driving")
    if edges is None or len(edges) == 0:
        return {"edge_count": 0, "road_km": 0.0}
    if "length" in edges.columns:
        road_m = float(edges["length"].sum())
    else:
        road_m = float(edges.to_crs(epsg=3857).geometry.length.sum())
    return {"edge_count": int(len(edges)), "road_km": road_m / 1000.0}


def proxy_segments_per_driver() -> dict[str, int]:
    out: dict[str, int] = {}
    with open(PROXY_SUMMARY, newline="") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["dataset"], int(row["segments_per_driver"]))
    return out


def geolife_bbox(margin_m: float) -> tuple[float, float, float, float]:
    """GeoLife footprint: the 10km x 10km centred grid recovered from the
    builtin Beijing geometry (verified byte-identical cell_zones)."""

    from common.osm_vectors import tariff_at_granularity

    g = tariff_at_granularity("beijing", "medium", grid_w=100, cell_size_m=100)
    half = 100 * 100 / 2.0 + margin_m

    def lat(north: float) -> float:
        return g.origin_lat + math.degrees(north / EARTH_RADIUS_M)

    def lon(east: float) -> float:
        return g.origin_lon + math.degrees(east / (EARTH_RADIUS_M * math.cos(math.radians(g.origin_lat))))

    return (lon(-half), lat(-half), lon(half), lat(half))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute E4 camera requirements on the real drivable graph.")
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "experiments" / "e4_e5_ruc"))
    parser.add_argument("--margin-m", type=float, default=200.0)
    parser.add_argument("--p-detect-target", type=float, default=0.95)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    segments_per_driver = proxy_segments_per_driver()

    rows: list[dict] = []
    receipt: dict = {
        "experiment": "E4 drivable-graph road universe",
        "tool": "osmium extract + pyrosm get_network(driving)",
        "segment_unit_m": SEGMENT_UNIT_M,
        "margin_m": float(args.margin_m),
        "notes": {"geolife": "centred-grid anchor recovered 2026-06-12; footprint is the full 10km x 10km tariff grid"},
        "datasets": {},
    }

    with tempfile.TemporaryDirectory(prefix="e4_clips_") as tmp:
        jobs = dict(PBF_BY_DATASET)
        jobs["geolife"] = ROOT_DIR / "dataset" / "osm" / "beijing.osm.pbf"
        for dataset, pbf in jobs.items():
            if not pbf.exists():
                receipt["datasets"][dataset] = {"error": f"missing PBF {pbf}"}
                continue
            if dataset == "geolife":
                bbox = geolife_bbox(float(args.margin_m))
                block = {"width": 100, "cell_size_m": 100, "anchor": "builtin beijing centred grid (recovered 2026-06-12)"}
            else:
                block = json.load(open(TARIFF_BLOCKS[dataset]))["block"]
                bbox = footprint_bbox(block, margin_m=float(args.margin_m))
            clip = Path(tmp) / f"{dataset}.osm.pbf"
            clip_pbf(pbf, bbox, clip)
            stats = drivable_stats(clip)
            width_km = float(block["width"]) * float(block["cell_size_m"]) / 1000.0
            area_km2 = width_km * width_km
            segments_100m = max(1, int(round(stats["road_km"] * 1000.0 / SEGMENT_UNIT_M)))
            receipt["datasets"][dataset] = {
                "pbf": str(pbf.relative_to(ROOT_DIR)),
                "bbox_lon_lat": list(bbox),
                "block": block,
                "edge_count": stats["edge_count"],
                "drivable_road_km": stats["road_km"],
                "segments_100m": segments_100m,
                "tariff_area_km2": area_km2,
            }
            for omit_fraction in (0.05, 0.10, 0.20):
                cams = e4_required_cameras(
                    omit_fraction=omit_fraction,
                    segments_per_driver=segments_per_driver.get(dataset, 24),
                    road_network_segments=segments_100m,
                    p_detect_target=float(args.p_detect_target),
                )
                required = int(cams["required_cameras_spotcheck"])
                rows.append(
                    {
                        "dataset": dataset,
                        "road_universe": "drivable_graph_pyrosm",
                        "omit_fraction": omit_fraction,
                        "segments_per_driver": segments_per_driver.get(dataset, 24),
                        "road_network_segments": segments_100m,
                        "drivable_road_km": round(stats["road_km"], 3),
                        "edge_count": stats["edge_count"],
                        "target_detection_probability": float(args.p_detect_target),
                        "required_coverage_fraction": cams["required_coverage_fraction"],
                        "required_cameras_spotcheck": required,
                        "required_cameras_tsip_ruc": cams["required_cameras_tsip_ruc"],
                        "cameras_per_km_road": required / max(stats["road_km"], 0.001),
                        "cameras_per_km2": required / max(area_km2, 0.001),
                        "tariff_area_km2": area_km2,
                    }
                )

    out_csv = out_dir / "e4_drivable_graph_summary.csv"
    with open(out_csv, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    receipt_path = out_dir / "e4_drivable_receipt.json"
    json.dump(receipt, open(receipt_path, "w"), indent=1, sort_keys=True)
    print(f"wrote {out_csv} ({len(rows)} rows) and {receipt_path}")


if __name__ == "__main__":
    main()
