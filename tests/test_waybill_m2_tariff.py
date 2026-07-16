from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import verify_merkle_path
from script import build_waybill_m2_tariff as builder


SOURCE = ROOT_DIR / "dataset" / "osm" / "zones" / "rome_medium.geojson"
ARTIFACT_DIR = ROOT_DIR / "experiments" / "waybill_m2"


@pytest.fixture(scope="module")
def expanded() -> builder.ExpandedTariff:
    return builder.expand_source_geojson(SOURCE)


@pytest.fixture(scope="module")
def root_material(expanded: builder.ExpandedTariff) -> dict[str, object]:
    table = expanded.to_tariff_table()
    primary_root = table.root(builder.TREE_DEPTH)
    levels = builder.independent_merkle_levels(
        expanded.cells,
        tariff_version=expanded.tariff_version,
        depth=builder.TREE_DEPTH,
    )
    return {"table": table, "primary_root": primary_root, "levels": levels}


def _load_artifact(name: str) -> dict:
    return json.loads((ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def test_source_expands_to_exactly_10000_real_cells(expanded: builder.ExpandedTariff) -> None:
    assert len(expanded.cells) == 10_000
    assert [cell.cell_idx for cell in expanded.cells] == list(range(10_000))
    assert all(cell.cell_idx == cell.y * 100 + cell.x for cell in expanded.cells)
    assert expanded.source_rate_mapping == builder.EXPECTED_RATE_MAPPING
    assert expanded.zone_rates == {50: 5, 100: 10, 120: 12}
    assert Counter(cell.normalized_rate for cell in expanded.cells) == {5: 800, 10: 8_755, 12: 445}


def test_source_expansion_rejects_a_row_run_gap(tmp_path: Path) -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    broken = copy.deepcopy(payload)
    broken["features"][0]["properties"]["grid_x_min"] = 1
    broken_path = tmp_path / "broken.geojson"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="do not cover all 10000 cells"):
        builder.expand_source_geojson(broken_path)


def test_depth14_root_matches_a_direct_independent_recomputation(
    expanded: builder.ExpandedTariff,
    root_material: dict[str, object],
) -> None:
    levels = root_material["levels"]
    assert isinstance(levels, list)
    independent_root = levels[-1][0]
    primary_root = root_material["primary_root"]
    manifest = _load_artifact(builder.MANIFEST_FILENAME)

    assert primary_root == independent_root
    assert str(primary_root) == manifest["tariff_root"]
    assert manifest["root_recomputation"]["primary"]["root"] == str(primary_root)
    assert manifest["root_recomputation"]["independent"]["root"] == str(independent_root)
    assert manifest["root_recomputation"]["roots_match"] is True


def test_independent_root_does_not_call_tariff_table_root(
    monkeypatch: pytest.MonkeyPatch,
    expanded: builder.ExpandedTariff,
) -> None:
    def forbidden_root(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("independent root called TariffTable.root")

    monkeypatch.setattr(builder.TariffTable, "root", forbidden_root)
    small_root = builder.independent_root(
        expanded.cells[:4],
        tariff_version=expanded.tariff_version,
        depth=2,
    )
    assert isinstance(small_root, int)


def test_manifest_freezes_padding_empty_leaf_hash_domain_and_rate_disclaimer() -> None:
    manifest = _load_artifact(builder.MANIFEST_FILENAME)
    tree = manifest["tree"]
    semantics = manifest["tariff"]["rate_value_semantics"]

    assert tree["depth"] == 14
    assert tree["capacity"] == 16_384
    assert tree["real_leaf_count"] == 10_000
    assert tree["padded_leaf_count"] == 6_384
    assert tree["padding_rule"] == "repeat-last-real-leaf"
    assert tree["padding_positions_inclusive"] == [10_000, 16_383]
    assert tree["empty_leaf_value"] == "0"
    assert tree["zero_filled_unused_capacity"] is False
    assert tree["hash_domain"]["explicit_numeric_domain_tag_present"] is False
    assert tree["hash_domain"]["explicit_numeric_domain_tag"] is None
    assert semantics["actual_billing_amount_claimed"] is False
    assert semantics["normalized_unit"] == "dimensionless_relative_tier"
    assert "not real road-use prices" in semantics["disclaimer"]
    assert "not cents per metre" in semantics["disclaimer"]


def test_boundary_and_seeded_random_membership_paths_verify_and_tampering_fails(
    expanded: builder.ExpandedTariff,
    root_material: dict[str, object],
) -> None:
    membership = _load_artifact(builder.MEMBERSHIP_FILENAME)
    root = int(membership["tariff_root"])
    primary_root = int(root_material["primary_root"])
    table = root_material["table"]
    assert root == primary_root

    strategy = membership["sample_strategy"]
    assert strategy["boundary_indices"] == [0, 99, 9_900, 9_999]
    expected_random = builder.deterministic_random_indices(
        cell_count=10_000,
        sample_count=builder.RANDOM_SAMPLE_COUNT,
        excluded=strategy["boundary_indices"],
    )
    assert strategy["random_indices"] == expected_random

    samples = membership["samples"]
    assert len(samples) == 4 + builder.RANDOM_SAMPLE_COUNT
    assert {sample["cell_idx"] for sample in samples if sample["sample_kind"] == "boundary_corner"} == {
        0,
        99,
        9_900,
        9_999,
    }
    for sample in samples:
        cell_idx = int(sample["cell_idx"])
        cell = expanded.cells[cell_idx]
        leaf = builder.independent_leaf_hash(
            expanded.tariff_version,
            cell.cell_idx,
            cell.zone_id,
            cell.normalized_rate,
        )
        path = sample["path"]
        assert len(path) == 14
        assert leaf == int(sample["leaf"])
        assert builder.independent_verify_path(leaf, path, root)
        assert verify_merkle_path(leaf, path, root)

    tampered_path = copy.deepcopy(samples[0]["path"])
    tampered_path[0]["sibling"] = str(int(tampered_path[0]["sibling"]) + 1)
    assert not builder.independent_verify_path(int(samples[0]["leaf"]), tampered_path, root)
    assert not builder.independent_verify_path(int(samples[0]["leaf"]) + 1, samples[0]["path"], root)
    assert table.leaf_for_cell(0) == int(samples[0]["leaf"])


def test_checked_in_artifact_hashes_and_explicit_cell_table_are_self_consistent(
    expanded: builder.ExpandedTariff,
) -> None:
    manifest = _load_artifact(builder.MANIFEST_FILENAME)
    tariff = _load_artifact(builder.TARIFF_FILENAME)

    assert manifest["source"]["sha256"] == builder.sha256_file(SOURCE)
    for record in manifest["artifacts"].values():
        artifact_path = ARTIFACT_DIR / record["path"]
        assert builder.sha256_file(artifact_path) == record["sha256"]
    assert tariff["cell_count"] == 10_000
    assert len(tariff["cell_zones"]) == 10_000
    assert tariff["cell_zones"] == {str(cell.cell_idx): cell.zone_id for cell in expanded.cells}
    assert tariff["zone_rates_cents_per_m"] == {"50": 5, "100": 10, "120": 12}
    assert tariff["rate_value_semantics"]["actual_billing_amount_claimed"] is False
