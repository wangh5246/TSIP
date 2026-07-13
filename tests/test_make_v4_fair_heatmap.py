import csv
import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "TSIP_heatmap_version"
    / "runtime"
    / "experiments-heatmap"
    / "make_v4_fair_heatmap.py"
)
SPEC = importlib.util.spec_from_file_location("make_v4_fair_heatmap", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def rows() -> list[dict[str, object]]:
    result = []
    for index, dataset in enumerate(MODULE.DATASETS):
        baseline = 0.20 + index * 0.05
        proposed = baseline + 0.01 + index * 0.001
        result.append(
            {
                "dataset": dataset,
                "fixed_epsilon": 5.0,
                "fixed_tau": 2.0,
                "proposed_avg_jaccard": proposed,
                "proposed_std_jaccard": 0.01,
                "strongest_baseline": "nebula",
                "baseline_avg_jaccard": baseline,
                "baseline_std_jaccard": 0.01,
                "delta_jaccard": proposed - baseline,
                "proposed_frr": 0.0,
                "proposed_mrr": 1.0,
                "pass": True,
            }
        )
    return result


def write_rows(path: Path, payload: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(payload[0]))
        writer.writeheader()
        writer.writerows(payload)


def test_load_fixed_frame_accepts_canonical_receipt(tmp_path: Path) -> None:
    path = tmp_path / "fixed.csv"
    write_rows(path, rows())

    frame = MODULE.load_fixed_frame(path)

    assert frame.index.tolist() == MODULE.DATASETS
    assert frame["strongest_baseline"].tolist() == ["nebula"] * 5
    assert MODULE.FIGURE_SOURCE_DATE_EPOCH == "1783900800"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fixed_epsilon", 2.0, "epsilon=5.0"),
        ("fixed_tau", 3.0, "tau=2.0"),
        ("strongest_baseline", "eiffel", "Nebula"),
        ("pass", False, "every row gate"),
        ("proposed_avg_jaccard", float("nan"), "non-finite"),
        ("proposed_frr", 1.1, "within \\[0, 1\\]"),
        ("delta_jaccard", -0.1, "does not match"),
    ],
)
def test_load_fixed_frame_rejects_invalid_receipt(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = rows()
    payload[0][field] = value
    path = tmp_path / "fixed.csv"
    write_rows(path, payload)

    with pytest.raises(ValueError, match=message):
        MODULE.load_fixed_frame(path)


def test_load_fixed_frame_rejects_noncanonical_dataset_order(tmp_path: Path) -> None:
    payload = rows()
    payload[0], payload[1] = payload[1], payload[0]
    path = tmp_path / "fixed.csv"
    write_rows(path, payload)

    with pytest.raises(ValueError, match="canonical five-dataset order"):
        MODULE.load_fixed_frame(path)


def test_load_fixed_frame_rejects_missing_column(tmp_path: Path) -> None:
    payload = rows()
    for row in payload:
        del row["proposed_mrr"]
    path = tmp_path / "fixed.csv"
    write_rows(path, payload)

    with pytest.raises(ValueError, match="missing columns"):
        MODULE.load_fixed_frame(path)
