#!/usr/bin/env python3
"""Build the WayBill M2 10,000-cell Rome tariff authenticity artifact.

The source GeoJSON is a row-run representation of a 100 x 100 grid.  This
builder expands every run, validates exact coverage, commits the 10,000 real
cells in a depth-14 tree, and emits deterministic membership samples.

The normalized values in this artifact preserve official Rome parking hourly
rate *ratios*.  They are not real road-use prices or billing amounts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.poseidon2_py import _poseidon2  # noqa: E402
from common.settlement import TariffTable, verify_merkle_path  # noqa: E402


# Kept local so the independent implementation does not depend on the Merkle
# helpers or field constant in common.settlement.
BN254_SCALAR_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
TREE_DEPTH = 14
TREE_CAPACITY = 1 << TREE_DEPTH
GRID_W = 100
GRID_H = 100
REAL_CELL_COUNT = GRID_W * GRID_H
TARIFF_VERSION = 202
RANDOM_SAMPLE_COUNT = 8
SAMPLE_SEED = "waybill-m2-rome-medium-depth14-membership-v1"

DEFAULT_SOURCE = ROOT_DIR / "dataset" / "osm" / "zones" / "rome_medium.geojson"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "experiments" / "waybill_m2"
TARIFF_FILENAME = "tariff_rome_medium_10000_cells.json"
MEMBERSHIP_FILENAME = "membership_samples_depth14.json"
MANIFEST_FILENAME = "tariff_manifest_depth14.json"

EXPECTED_RATE_MAPPING = {
    "0,50 euro/h": 5,
    "1 euro/h": 10,
    "1,20 euro/h": 12,
}

RATE_DISCLAIMER = (
    "Values 5, 10, and 12 preserve only the ratios of the official Rome parking hourly rates "
    "EUR 0.50/h, EUR 1.00/h, and EUR 1.20/h. They are dimensionless normalized test tiers used "
    "only to validate tariff-domain capacity and source provenance. They are not real road-use "
    "prices, not cents per metre, and must not be presented as actual billing amounts."
)


@dataclass(frozen=True)
class CellRecord:
    cell_idx: int
    x: int
    y: int
    zone_id: int
    normalized_rate: int
    source_tariffs: tuple[str, ...]
    source_feature_index: int


@dataclass(frozen=True)
class ExpandedTariff:
    source_path: Path
    source_sha256: str
    metadata: dict[str, Any]
    cells: tuple[CellRecord, ...]
    zone_rates: dict[int, int]
    source_rate_mapping: dict[str, int]
    grid_w: int = GRID_W
    grid_h: int = GRID_H
    tariff_version: int = TARIFF_VERSION

    def to_tariff_table(self) -> TariffTable:
        return TariffTable(
            tariff_version=self.tariff_version,
            grid_w=self.grid_w,
            cell_zones={cell.cell_idx: cell.zone_id for cell in self.cells},
            zone_rates_cents_per_m=dict(self.zone_rates),
        )


@dataclass(frozen=True)
class BuildResult:
    tariff_path: Path
    membership_path: Path
    manifest_path: Path
    tariff_root: int
    real_cell_count: int
    tree_depth: int


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and independently verify the WayBill M2 depth-14 Rome tariff artifact."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--random-samples", type=int, default=RANDOM_SAMPLE_COUNT)
    return parser.parse_args(argv)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT_DIR.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, payload: Any) -> str:
    encoded = _json_bytes(payload)
    path.write_bytes(encoded)
    return _sha256_bytes(encoded)


def _required_int(properties: dict[str, Any], key: str, feature_index: int) -> int:
    if key not in properties or isinstance(properties[key], bool):
        raise ValueError(f"feature {feature_index} is missing integer {key}")
    try:
        value = int(properties[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"feature {feature_index} has invalid integer {key}") from exc
    if value != properties[key]:
        raise ValueError(f"feature {feature_index} has non-integral {key}")
    return value


def expand_source_geojson(source_path: Path) -> ExpandedTariff:
    """Expand and validate the source row runs into exactly 10,000 cells."""

    raw_bytes = source_path.read_bytes()
    try:
        payload = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid GeoJSON JSON: {source_path}") from exc
    if payload.get("type") != "FeatureCollection":
        raise ValueError("tariff source must be a GeoJSON FeatureCollection")

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("tariff source is missing metadata")
    if metadata.get("city") != "rome" or metadata.get("granularity") != "medium":
        raise ValueError("tariff source must be the Rome medium overlay")
    if int(metadata.get("grid_w", -1)) != GRID_W:
        raise ValueError(f"tariff source grid_w must be {GRID_W}")
    if int(metadata.get("cell_size_m", -1)) != 100:
        raise ValueError("tariff source cell_size_m must be 100")

    raw_rate_mapping = metadata.get("rate_mapping")
    if not isinstance(raw_rate_mapping, dict):
        raise ValueError("tariff source metadata is missing rate_mapping")
    try:
        source_rate_mapping = {str(key): int(value) for key, value in raw_rate_mapping.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("tariff source rate_mapping contains a non-integer value") from exc
    if source_rate_mapping != EXPECTED_RATE_MAPPING:
        raise ValueError("tariff source rate_mapping does not match the frozen official hourly-rate ratios")

    features = payload.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("tariff source has no features")

    slots: list[CellRecord | None] = [None] * REAL_CELL_COUNT
    zone_rates: dict[int, int] = {}
    for feature_index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"feature {feature_index} is not an object")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"feature {feature_index} is not a Polygon/MultiPolygon")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError(f"feature {feature_index} is missing properties")

        y = _required_int(properties, "grid_y", feature_index)
        x_min = _required_int(properties, "grid_x_min", feature_index)
        x_max = _required_int(properties, "grid_x_max_exclusive", feature_index)
        zone_id = _required_int(properties, "zone_id", feature_index)
        normalized_rate = _required_int(properties, "rate_cents_per_m", feature_index)
        if not 0 <= y < GRID_H:
            raise ValueError(f"feature {feature_index} grid_y is outside [0,{GRID_H})")
        if not 0 <= x_min < x_max <= GRID_W:
            raise ValueError(f"feature {feature_index} has an invalid half-open x run")
        if zone_id < 0 or normalized_rate <= 0:
            raise ValueError(f"feature {feature_index} has an invalid zone/rate")

        raw_source_tariffs = properties.get("source_tariffs")
        if not isinstance(raw_source_tariffs, list) or not raw_source_tariffs:
            raise ValueError(f"feature {feature_index} is missing source_tariffs provenance")
        source_tariffs = tuple(sorted({str(value) for value in raw_source_tariffs}))
        for source_tariff in source_tariffs:
            mapped_rate = source_rate_mapping.get(source_tariff)
            if mapped_rate is None:
                raise ValueError(f"feature {feature_index} cites an unknown official tariff string")
            if mapped_rate != normalized_rate:
                raise ValueError(f"feature {feature_index} rate disagrees with its official tariff ratio mapping")

        previous_rate = zone_rates.setdefault(zone_id, normalized_rate)
        if previous_rate != normalized_rate:
            raise ValueError(f"zone {zone_id} maps to more than one normalized rate")

        for x in range(x_min, x_max):
            cell_idx = y * GRID_W + x
            if slots[cell_idx] is not None:
                raise ValueError(f"overlapping row runs assign cell {cell_idx} more than once")
            slots[cell_idx] = CellRecord(
                cell_idx=cell_idx,
                x=x,
                y=y,
                zone_id=zone_id,
                normalized_rate=normalized_rate,
                source_tariffs=source_tariffs,
                source_feature_index=feature_index,
            )

    missing = [index for index, cell in enumerate(slots) if cell is None]
    if missing:
        preview = ",".join(str(index) for index in missing[:8])
        raise ValueError(f"row runs do not cover all {REAL_CELL_COUNT} cells; missing {preview}")
    cells = tuple(cell for cell in slots if cell is not None)
    if len(cells) != REAL_CELL_COUNT or [cell.cell_idx for cell in cells] != list(range(REAL_CELL_COUNT)):
        raise ValueError("expanded tariff is not a dense row-major 10,000-cell domain")

    return ExpandedTariff(
        source_path=source_path,
        source_sha256=_sha256_bytes(raw_bytes),
        metadata=dict(metadata),
        cells=cells,
        zone_rates=dict(sorted(zone_rates.items())),
        source_rate_mapping=dict(sorted(source_rate_mapping.items())),
    )


def independent_leaf_hash(
    tariff_version: int,
    cell_idx: int,
    zone_id: int,
    normalized_rate: int,
) -> int:
    """Reimplement the circuit-compatible legacy tariff leaf hash directly."""

    state = 0
    for value in (tariff_version, cell_idx, zone_id, normalized_rate):
        state = int(_poseidon2(state % BN254_SCALAR_FIELD, int(value) % BN254_SCALAR_FIELD))
    return state


def independent_merkle_levels(
    cells: Sequence[CellRecord],
    *,
    tariff_version: int,
    depth: int,
) -> list[list[int]]:
    """Build all levels without calling TariffTable or settlement Merkle helpers."""

    if depth < 0:
        raise ValueError("Merkle depth must be non-negative")
    capacity = 1 << depth
    if len(cells) > capacity:
        raise ValueError("too many real tariff cells for the requested depth")
    ordered = sorted(cells, key=lambda cell: cell.cell_idx)
    if len({cell.cell_idx for cell in ordered}) != len(ordered):
        raise ValueError("duplicate cell_idx in independent root input")

    leaves = [
        independent_leaf_hash(
            tariff_version,
            cell.cell_idx,
            cell.zone_id,
            cell.normalized_rate,
        )
        for cell in ordered
    ]
    if not leaves:
        leaves = [0]
    # Compatibility rule used by TariffTable.root(depth): repeat the final real
    # leaf to capacity.  This populated artifact is deliberately not zero-filled.
    leaves.extend([leaves[-1]] * (capacity - len(leaves)))

    levels = [leaves]
    level = leaves
    while len(level) > 1:
        level = [
            int(_poseidon2(level[index] % BN254_SCALAR_FIELD, level[index + 1] % BN254_SCALAR_FIELD))
            for index in range(0, len(level), 2)
        ]
        levels.append(level)
    return levels


def independent_root(
    cells: Sequence[CellRecord],
    *,
    tariff_version: int,
    depth: int,
) -> int:
    return independent_merkle_levels(cells, tariff_version=tariff_version, depth=depth)[-1][0]


def independent_path(levels: Sequence[Sequence[int]], leaf_position: int) -> list[dict[str, int]]:
    if not levels or not levels[0]:
        raise ValueError("Merkle levels are empty")
    if leaf_position < 0 or leaf_position >= len(levels[0]):
        raise ValueError("Merkle leaf position is out of range")
    index = leaf_position
    path: list[dict[str, int]] = []
    for level_number, level in enumerate(levels[:-1]):
        path.append(
            {
                "level": level_number,
                "sibling": int(level[index ^ 1]),
                "is_right": int(index & 1),
            }
        )
        index //= 2
    return path


def independent_verify_path(leaf: int, path: Iterable[dict[str, Any]], root: int) -> bool:
    accumulator = int(leaf) % BN254_SCALAR_FIELD
    for step in path:
        sibling = int(step["sibling"]) % BN254_SCALAR_FIELD
        is_right = int(step["is_right"])
        if is_right not in {0, 1}:
            return False
        left, right = (sibling, accumulator) if is_right else (accumulator, sibling)
        accumulator = int(_poseidon2(left, right))
    return accumulator == int(root) % BN254_SCALAR_FIELD


def deterministic_random_indices(
    *,
    cell_count: int,
    sample_count: int,
    excluded: Iterable[int] = (),
    seed: str = SAMPLE_SEED,
) -> list[int]:
    if cell_count <= 0:
        raise ValueError("cell_count must be positive")
    excluded_set = {int(index) for index in excluded}
    available = cell_count - len({index for index in excluded_set if 0 <= index < cell_count})
    if sample_count < 0 or sample_count > available:
        raise ValueError("random sample count exceeds the available cells")
    selected: list[int] = []
    counter = 0
    while len(selected) < sample_count:
        digest = hashlib.sha256(f"{seed}:{counter}".encode("utf-8")).digest()
        candidate = int.from_bytes(digest, "big") % cell_count
        counter += 1
        if candidate in excluded_set or candidate in selected:
            continue
        selected.append(candidate)
    return selected


def _rate_semantics(expanded: ExpandedTariff) -> dict[str, Any]:
    return {
        "actual_billing_amount_claimed": False,
        "disclaimer": RATE_DISCLAIMER,
        "intended_use": ["tariff-domain capacity validation", "source-provenance validation"],
        "legacy_storage_field": "zone_rates_cents_per_m",
        "normalized_unit": "dimensionless_relative_tier",
        "official_hourly_rate_to_normalized_value": expanded.source_rate_mapping,
        "official_ratio_preserved": "0.50:1.00:1.20 = 5:10:12",
    }


def _tariff_payload(expanded: ExpandedTariff) -> dict[str, Any]:
    return {
        "schema": "waybill_m2_tariff_cells_v1",
        "tariff_version": expanded.tariff_version,
        "grid_w": expanded.grid_w,
        "grid_h": expanded.grid_h,
        "cell_count": len(expanded.cells),
        "cell_ordering": "ascending cell_idx; cell_idx = y * grid_w + x (row-major)",
        "cell_zones": {str(cell.cell_idx): cell.zone_id for cell in expanded.cells},
        # The key is retained for compatibility with TariffTable and the circuit.
        # rate_value_semantics explicitly prevents treating it as a monetary unit.
        "zone_rates_cents_per_m": {str(zone): rate for zone, rate in expanded.zone_rates.items()},
        "rate_value_semantics": _rate_semantics(expanded),
        "source_geojson": _portable_path(expanded.source_path),
        "source_geojson_sha256": expanded.source_sha256,
    }


def _membership_payload(
    expanded: ExpandedTariff,
    *,
    table: TariffTable,
    levels: Sequence[Sequence[int]],
    root: int,
    random_sample_count: int,
) -> dict[str, Any]:
    boundary_indices = [0, expanded.grid_w - 1, len(expanded.cells) - expanded.grid_w, len(expanded.cells) - 1]
    random_indices = deterministic_random_indices(
        cell_count=len(expanded.cells),
        sample_count=random_sample_count,
        excluded=boundary_indices,
    )
    samples: list[dict[str, Any]] = []
    for kind, indices in (("boundary_corner", boundary_indices), ("seeded_random", random_indices)):
        for cell_idx in indices:
            cell = expanded.cells[cell_idx]
            leaf = independent_leaf_hash(
                expanded.tariff_version,
                cell.cell_idx,
                cell.zone_id,
                cell.normalized_rate,
            )
            path = independent_path(levels, cell_idx)
            if len(path) != TREE_DEPTH:
                raise RuntimeError(f"membership sample {cell_idx} does not have a depth-{TREE_DEPTH} path")
            if not independent_verify_path(leaf, path, root):
                raise RuntimeError(f"independent membership verification failed for cell {cell_idx}")
            common_path = [
                {"sibling": int(step["sibling"]), "is_right": int(step["is_right"])}
                for step in path
            ]
            if not verify_merkle_path(table.leaf_for_cell(cell_idx), common_path, root):
                raise RuntimeError(f"settlement membership verification failed for cell {cell_idx}")
            samples.append(
                {
                    "sample_kind": kind,
                    "cell_idx": cell.cell_idx,
                    "leaf_position": cell.cell_idx,
                    "x": cell.x,
                    "y": cell.y,
                    "zone_id": cell.zone_id,
                    "normalized_rate": cell.normalized_rate,
                    "leaf": str(leaf),
                    "path": [
                        {
                            "level": int(step["level"]),
                            "sibling": str(step["sibling"]),
                            "is_right": int(step["is_right"]),
                        }
                        for step in path
                    ],
                }
            )
    return {
        "schema": "waybill_m2_tariff_membership_samples_v1",
        "tariff_root": str(root),
        "tree_depth": TREE_DEPTH,
        "sample_strategy": {
            "boundary_indices": boundary_indices,
            "random_derivation": "uint256(sha256(utf8(seed + ':' + counter))) mod cell_count; reject duplicates/exclusions",
            "random_indices": random_indices,
            "random_sample_count": random_sample_count,
            "seed": SAMPLE_SEED,
        },
        "samples": samples,
    }


def _manifest_payload(
    expanded: ExpandedTariff,
    *,
    primary_root: int,
    independent_root_value: int,
    padding_leaf: int,
    tariff_sha256: str,
    membership_sha256: str,
    membership_payload: dict[str, Any],
) -> dict[str, Any]:
    rate_histogram = Counter(cell.normalized_rate for cell in expanded.cells)
    zone_histogram = Counter(cell.zone_id for cell in expanded.cells)
    metadata = expanded.metadata
    return {
        "schema": "waybill_m2_tariff_manifest_v1",
        "artifact_id": "waybill-m2-rome-medium-10000-depth14-v1",
        "tariff_root": str(primary_root),
        "source": {
            "path": _portable_path(expanded.source_path),
            "sha256": expanded.source_sha256,
            "geojson_feature_count": int(len(json.loads(expanded.source_path.read_bytes())["features"])),
            "city": metadata["city"],
            "granularity": metadata["granularity"],
            "cell_size_m": int(metadata["cell_size_m"]),
            "official_source_description": metadata.get("source"),
            "official_blue_stripe_layer": metadata.get("strisce_blu_layer"),
            "official_webmap_item": metadata.get("webmap_item"),
            "official_app_item": metadata.get("app_item"),
            "method_doc": metadata.get("method_doc"),
            "transformation": (
                "Expand each validated [grid_x_min, grid_x_max_exclusive) row run at grid_y; "
                "the upstream overlay assigns every cell the normalized rate of the nearest official "
                "blue-stripe parking street segment."
            ),
            "spatial_assignment_limit": (
                "This 100x100 nearest-segment overlay is derived from official street-linear parking data; "
                "it is not an official road-use charging map or an assertion that parking rules apply over every cell area."
            ),
        },
        "tariff": {
            "tariff_version": expanded.tariff_version,
            "grid_w": expanded.grid_w,
            "grid_h": expanded.grid_h,
            "real_valid_cell_count": len(expanded.cells),
            "cell_index_range": [0, len(expanded.cells) - 1],
            "cell_ordering": {
                "rule": "ascending cell_idx",
                "index_formula": "cell_idx = y * grid_w + x",
                "coordinate_iteration": "y=0..99 outer, x=0..99 inner",
                "leaf_position": "equal to cell_idx for this dense artifact",
            },
            "normalized_rate_histogram": {str(key): value for key, value in sorted(rate_histogram.items())},
            "zone_histogram": {str(key): value for key, value in sorted(zone_histogram.items())},
            "zone_to_normalized_rate": {str(key): value for key, value in expanded.zone_rates.items()},
            "rate_value_semantics": _rate_semantics(expanded),
        },
        "tree": {
            "depth": TREE_DEPTH,
            "capacity": TREE_CAPACITY,
            "real_leaf_count": len(expanded.cells),
            "padded_leaf_count": TREE_CAPACITY - len(expanded.cells),
            "padding_rule": "repeat-last-real-leaf",
            "padding_positions_inclusive": [len(expanded.cells), TREE_CAPACITY - 1],
            "padding_leaf_source_position": len(expanded.cells) - 1,
            "padding_leaf_value": str(padding_leaf),
            "empty_leaf_value": "0",
            "empty_leaf_value_usage": (
                "Only seeds an entirely empty input before fixed-depth repeat-last padding; "
                "it is not used by this populated 10,000-cell artifact."
            ),
            "zero_filled_unused_capacity": False,
            "hash_domain": {
                "compatibility_name": "tsip-settlement-tariff-leaf-v1-legacy",
                "explicit_numeric_domain_tag_present": False,
                "explicit_numeric_domain_tag": None,
                "domain_note": (
                    "Compatibility is defined by hash function, arity, seed, ordered leaf fields, and tree role; "
                    "the legacy circuit adds no numeric domain-separation tag."
                ),
                "field": "BN254 scalar field",
                "field_modulus": str(BN254_SCALAR_FIELD),
                "leaf_hash": (
                    "state=0; for value in [tariff_version, cell_idx, zone_id, normalized_rate]: "
                    "state=Poseidon2(state,value); leaf=state"
                ),
                "internal_node_hash": "Poseidon2(left_child,right_child)",
            },
        },
        "root_recomputation": {
            "primary": {
                "implementation": "common.settlement.TariffTable.root(depth=14)",
                "root": str(primary_root),
            },
            "independent": {
                "implementation": "script/build_waybill_m2_tariff.py direct Poseidon leaf/tree fold",
                "calls_tariff_table_root": False,
                "root": str(independent_root_value),
            },
            "roots_match": primary_root == independent_root_value,
        },
        "membership_validation": {
            "sample_file": MEMBERSHIP_FILENAME,
            "path_length": TREE_DEPTH,
            "boundary_indices": membership_payload["sample_strategy"]["boundary_indices"],
            "seeded_random_indices": membership_payload["sample_strategy"]["random_indices"],
            "all_samples_verified_by_common_and_independent_implementations": True,
        },
        "artifacts": {
            "tariff_cells": {"path": TARIFF_FILENAME, "sha256": tariff_sha256},
            "membership_samples": {"path": MEMBERSHIP_FILENAME, "sha256": membership_sha256},
        },
        "generator": {
            "path": _portable_path(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
            "deterministic_output": True,
        },
    }


def build_artifacts(
    source_path: Path = DEFAULT_SOURCE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    random_sample_count: int = RANDOM_SAMPLE_COUNT,
) -> BuildResult:
    expanded = expand_source_geojson(source_path)
    if len(expanded.cells) > TREE_CAPACITY:
        raise ValueError("the 10,000-cell artifact does not fit depth 14")

    table = expanded.to_tariff_table()
    primary_root = int(table.root(TREE_DEPTH))
    independent_levels = independent_merkle_levels(
        expanded.cells,
        tariff_version=expanded.tariff_version,
        depth=TREE_DEPTH,
    )
    independent_root_value = int(independent_levels[-1][0])
    if primary_root != independent_root_value:
        raise RuntimeError("primary and independent depth-14 tariff roots disagree")

    output_dir.mkdir(parents=True, exist_ok=True)
    tariff_path = output_dir / TARIFF_FILENAME
    membership_path = output_dir / MEMBERSHIP_FILENAME
    manifest_path = output_dir / MANIFEST_FILENAME

    tariff_sha256 = _write_json(tariff_path, _tariff_payload(expanded))
    membership_payload = _membership_payload(
        expanded,
        table=table,
        levels=independent_levels,
        root=primary_root,
        random_sample_count=random_sample_count,
    )
    membership_sha256 = _write_json(membership_path, membership_payload)
    padding_leaf = int(independent_levels[0][-1])
    manifest_payload = _manifest_payload(
        expanded,
        primary_root=primary_root,
        independent_root_value=independent_root_value,
        padding_leaf=padding_leaf,
        tariff_sha256=tariff_sha256,
        membership_sha256=membership_sha256,
        membership_payload=membership_payload,
    )
    _write_json(manifest_path, manifest_payload)
    return BuildResult(
        tariff_path=tariff_path,
        membership_path=membership_path,
        manifest_path=manifest_path,
        tariff_root=primary_root,
        real_cell_count=len(expanded.cells),
        tree_depth=TREE_DEPTH,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_artifacts(
        source_path=args.source,
        output_dir=args.output_dir,
        random_sample_count=args.random_samples,
    )
    print(
        json.dumps(
            {
                "manifest": _portable_path(result.manifest_path),
                "membership_samples": _portable_path(result.membership_path),
                "real_cell_count": result.real_cell_count,
                "tariff_artifact": _portable_path(result.tariff_path),
                "tariff_root": str(result.tariff_root),
                "tree_depth": result.tree_depth,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
