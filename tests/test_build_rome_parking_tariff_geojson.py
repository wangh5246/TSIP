from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from script import build_rome_parking_tariff_geojson as builder


def test_parking_segments_parse_official_tariff_strings() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "FID": 1,
                    "TARIFFA": "1,20 euro/h",
                    "ZONA": "ZONA08",
                    "AMBITO": "Centro Storico",
                },
                "geometry": {"type": "MultiLineString", "coordinates": [[(12.4964, 41.9028), (12.4974, 41.9028)]]},
            },
            {
                "type": "Feature",
                "properties": {"FID": 2, "TARIFFA": "unknown"},
                "geometry": {"type": "LineString", "coordinates": [(12.4964, 41.9028), (12.4964, 41.9038)]},
            },
        ],
    }

    segments = builder._parking_segments(payload, origin_lat=41.9028, origin_lon=12.4964)

    assert len(segments) == 1
    assert segments[0]["rate"] == 12
    assert segments[0]["source_tariff"] == "1,20 euro/h"
    assert segments[0]["source_zona"] == "ZONA08"


def test_row_run_features_merge_contiguous_same_rate_cells() -> None:
    assignments = [
        [
            {"x": 0, "y": 0, "rate": 10, "source_tariff": "1 euro/h", "source_zona": "A", "source_ambito": "N", "nearest_distance_m": 1.0},
            {"x": 1, "y": 0, "rate": 10, "source_tariff": "1 euro/h", "source_zona": "A", "source_ambito": "N", "nearest_distance_m": 2.0},
            {
                "x": 2,
                "y": 0,
                "rate": 12,
                "source_tariff": "1,20 euro/h",
                "source_zona": "B",
                "source_ambito": "C",
                "nearest_distance_m": 3.0,
            },
        ]
    ]

    features = builder._row_run_features(
        assignments,
        origin_lat=41.9028,
        origin_lon=12.4964,
        grid_w=3,
        cell_size_m=100,
    )

    assert len(features) == 2
    assert features[0]["properties"]["rate_cents_per_m"] == 10
    assert features[0]["properties"]["grid_x_min"] == 0
    assert features[0]["properties"]["grid_x_max_exclusive"] == 2
    assert features[1]["properties"]["rate_cents_per_m"] == 12
    assert features[1]["geometry"]["type"] == "Polygon"
    assert features[1]["geometry"]["coordinates"][0][0] == features[1]["geometry"]["coordinates"][0][-1]


def test_assign_grid_uses_nearest_official_line_rate() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"FID": 1, "TARIFFA": "0,50 euro/h", "ZONA": "LOW", "AMBITO": "L"},
                "geometry": {"type": "LineString", "coordinates": [(12.4958, 41.9028), (12.4958, 41.9038)]},
            },
            {
                "type": "Feature",
                "properties": {"FID": 2, "TARIFFA": "1,20 euro/h", "ZONA": "HIGH", "AMBITO": "H"},
                "geometry": {"type": "LineString", "coordinates": [(12.4970, 41.9028), (12.4970, 41.9038)]},
            },
        ],
    }
    segments = builder._parking_segments(payload, origin_lat=41.9028, origin_lon=12.4964)

    rows = builder._assign_grid(
        segments,
        origin_lat=41.9028,
        origin_lon=12.4964,
        grid_w=2,
        cell_size_m=100,
        bucket_m=500,
    )

    assert rows[0][0]["rate"] == 5
    assert rows[0][1]["rate"] == 12
