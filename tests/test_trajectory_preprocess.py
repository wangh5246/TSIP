from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams
from common.osm_vectors import missing_extracts, tariff_at_granularity, tariff_from_geojson
from common.trajectory_preprocess import (
    MAX_DT_SEC,
    REBASE_ANCHOR,
    TariffBlock,
    build_local_tariff_table,
    build_period_records,
    build_resampled_fixes,
    choose_density_peak_block,
    clean_raw_points,
    rebase_points_to_2026,
    IdentityMatcher,
    MatchedPoint,
    RawPoint,
    segment_native_trips,
    select_real_points_by_cadence,
    iter_geolife_driving_trips,
    iter_porto_trips,
    iter_rome_trips,
    iter_tdrive_trips,
    prepare_trip,
    resample_matched_points,
)


def test_four_dataset_parsers(tmp_path: Path):
    tdrive = tmp_path / "T-Drive"
    tdrive.mkdir()
    (tdrive / "1.txt").write_text("1,2008-02-02 13:30:50,116.0,39.0\n1,2008-02-02 13:31:00,116.1,39.1\n")
    assert next(iter_tdrive_trips(tdrive))[1][0].lon == 116.0

    rome = tmp_path / "Rome.txt"
    rome.write_text("7;2014-02-01 00:00:00+01;POINT(41.9 12.4)\n7;2014-02-01 00:00:15+01;POINT(41.91 12.41)\n")
    assert next(iter_rome_trips(rome))[1][0].lat == 41.9

    porto = tmp_path / "porto.csv"
    porto.write_text('TRIP_ID,TAXI_ID,TIMESTAMP,POLYLINE\np1,t1,100,"[[-8.6,41.1],[-8.7,41.2]]"\n')
    assert next(iter_porto_trips(porto))[1][1].timestamp == 115
    porto_zip = tmp_path / "porto.csv.zip"
    with zipfile.ZipFile(porto_zip, "w") as archive:
        archive.write(porto, arcname="train.csv")
    assert next(iter_porto_trips(porto_zip))[1][0].lon == -8.6

    geolife = tmp_path / "Data" / "001"
    (geolife / "Trajectory").mkdir(parents=True)
    (geolife / "labels.txt").write_text("Start Time\tEnd Time\tTransportation Mode\n2008/01/01 00:00:00\t2008/01/01 00:01:00\tcar\n")
    (geolife / "Trajectory" / "a.plt").write_text("h\nh\nh\nh\nh\nh\n39,116,0,0,0,2008-01-01,00:00:00\n39.1,116.1,0,0,0,2008-01-01,00:00:30\n")
    assert next(iter_geolife_driving_trips(tmp_path / "Data"))[1][0].vehicle_id == "001"


def test_resample_prepare_and_tariff_geometry():
    sampled = resample_matched_points(
        [MatchedPoint(0, 0, 0, 0), MatchedPoint(60, 0, 0.001, 100)],
        cadence_sec=30,
    )
    assert [p.timestamp for p in sampled] == [0, 30, 60]
    assert sampled[1].cumulative_distance_m == 50

    geometry = tariff_at_granularity("porto", "medium", grid_w=10, cell_size_m=100)
    tariff = geometry.to_table()
    prepared = prepare_trip(
        "porto",
        "p1",
        [RawPoint("t1", 0, geometry.origin_lat, geometry.origin_lon), RawPoint("t1", 60, geometry.origin_lat, geometry.origin_lon + 0.001)],
        matcher=IdentityMatcher(),
        tariff=tariff,
        params=HarnessParams(cadence_sec=30, cell_size_m=100),
        cadence_sec=30,
        origin_lat=geometry.origin_lat,
        origin_lon=geometry.origin_lon,
    )
    assert prepared is not None
    assert len(prepared.fixes) == 3
    assert prepared.fixes[0].cell_x == 5
    assert prepared.fixes[0].cell_y == 5
    assert prepared.odometer_distance_m > 0
    assert prepared.honest_bill_cents > 0


def test_missing_osm_extracts_are_reported(tmp_path: Path):
    missing = missing_extracts(tmp_path)
    assert {row["city"] for row in missing} == {"beijing", "porto", "rome"}


def test_tariff_boundary_buffer_changes_circle_radius():
    base = tariff_at_granularity("rome", "coarse")
    expanded = tariff_at_granularity("rome", "coarse", boundary_buffer_m=100)
    assert expanded.zones[0].radius_m == base.zones[0].radius_m + 100


def test_tariff_geojson_polygon_overlay(tmp_path: Path):
    overlay = tmp_path / "zones.geojson"
    overlay.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"zone_id":7,"rate_cents_per_m":9},"geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[1,1],[0,1],[0,0]]]}}]}'
    )
    geometry = tariff_from_geojson(
        overlay,
        city="porto",
        granularity="coarse",
        origin_lat=0.5,
        origin_lon=0.5,
        grid_w=2,
        cell_size_m=100,
    )
    assert geometry.zone_at(0.5, 0.5) == 7
    assert geometry.zone_at(2, 2) == 99


def test_tier1_rebase_preserves_intra_device_delta_and_removes_duplicate_timestamp():
    raw, rejects = clean_raw_points(
        "unit",
        [
            RawPoint("dev-b", 100, 39.0, 116.0),
            RawPoint("dev-b", 160, 39.0, 116.001),
            RawPoint("dev-b", 160, 39.0, 116.002),
        ],
    )

    rebased = rebase_points_to_2026(raw)

    assert len(raw) == 2
    assert rejects[0].reason == "duplicate_timestamp"
    assert rebased[0]["t_unix"] == REBASE_ANCHOR
    assert rebased[1]["t_unix"] - rebased[0]["t_unix"] == 60
    assert rebased[0]["t_unix_original"] == 100


def test_tier1_resample_selects_real_points_without_interpolation():
    rows = [
        {"t_unix": 100, "lat": 0.0, "lon": 0.0},
        {"t_unix": 128, "lat": 9.0, "lon": 9.0},
        {"t_unix": 165, "lat": 1.0, "lon": 1.0},
    ]

    sampled = select_real_points_by_cadence(rows, cadence_sec=60)

    assert [row["t_unix"] for row in sampled] == [100, 165]
    assert sampled[1]["lat"] == 1.0


def test_tier1_density_peak_block_uses_distinct_device_cell_visits():
    origin_lat, origin_lon = 0.0, 0.0
    rows = []
    for i in range(50):
        rows.append({"device_id": "idle", "lat": 0.0, "lon": 0.0})
    rows.extend(
        [
            {"device_id": "a", "lat": 0.0, "lon": 0.002},
            {"device_id": "b", "lat": 0.0, "lon": 0.002},
            {"device_id": "c", "lat": 0.0, "lon": 0.002},
        ]
    )

    block = choose_density_peak_block(rows, origin_lat=origin_lat, origin_lon=origin_lon, width=1, cell_size_m=100)

    assert block.global_cell_x_min == 2


def test_tier1_local_tariff_uses_row_major_16x16_leaf_order():
    geometry = tariff_at_granularity("beijing", "medium", grid_w=16, cell_size_m=100)
    block = TariffBlock(geometry.origin_lat, geometry.origin_lon, -8, -8)
    tariff = build_local_tariff_table(block, geometry)

    assert tariff.grid_w == 100
    assert tariff.cell_index(15, 15) == 1515
    assert len(tariff.cell_zones) == 256


def test_tier1_periods_do_not_cross_trip_or_unbridgeable_outage():
    geometry = tariff_at_granularity("beijing", "medium", grid_w=16, cell_size_m=100)
    block = TariffBlock(geometry.origin_lat, geometry.origin_lon, 0, 0)
    tariff = build_local_tariff_table(block, geometry)
    raw = [
        RawPoint("dev", 100 + i * 300, geometry.origin_lat, geometry.origin_lon + i * 0.00001)
        for i in range(26)
    ]
    raw.append(RawPoint("dev", 100 + 26 * 300 + MAX_DT_SEC + 1, geometry.origin_lat, geometry.origin_lon + 26 * 0.00001))
    cleaned, _rejects = clean_raw_points("tdrive", raw)
    rebased = rebase_points_to_2026(cleaned)
    native, _trip_rejects = segment_native_trips("tdrive", rebased, gap_sec=1_800)

    fixes, fix_rejects = build_resampled_fixes("tdrive", native, cadence_sec=300, block=block, tariff=tariff)
    periods, period_rejects = build_period_records("tdrive", fixes, cadence_sec=300, tariff=tariff)

    assert len(periods) == 1
    assert len(periods[0]["fixes"]) == 25
    assert any(row.reason == "max_dt_exceeded" for row in fix_rejects)
    assert any(row.reason == "period_less_than_25_fixes" for row in period_rejects)
