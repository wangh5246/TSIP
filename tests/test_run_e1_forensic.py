from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import ReceiverFix
from script import run_e1_forensic


def _fix(seq: int) -> ReceiverFix:
    return ReceiverFix(
        device_id="dev-1",
        period_id="rome:unit:p0",
        fix_seq=seq,
        auth_gnss_time=seq * 60,
        cell_x=2,
        cell_y=2,
        osnma_status="authenticated",
        odometer_reading_m=seq * 100,
        nonce=f"n-{seq}",
    )


def _write_fixture(tmp_path: Path) -> Path:
    input_dir = tmp_path / "rome"
    input_dir.mkdir()
    input_path = input_dir / "periods_60s.jsonl"
    record = {
        "period_id": "rome:unit:p0",
        "fixes": [_fix(seq).to_dict() for seq in range(run_e1_forensic.N_FIXES)],
    }
    input_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    cell_zones = {
        str(cell): (10 if cell % 5 < 2 else 20)
        for cell in range(25)
    }
    tariff = {
        "tariff": {
            "tariff_version": 1,
            "grid_w": 5,
            "cell_zones": cell_zones,
            "zone_rates_cents_per_m": {"10": 1, "20": 5},
        }
    }
    (input_dir / "tariff_block.json").write_text(json.dumps(tariff), encoding="utf-8")
    return input_path


def _run_forensic(monkeypatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["run_e1_forensic.py", *argv])
    assert run_e1_forensic.main() == 0


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_e1_forensic_sweep_schema_grouping_receipt_and_single_value_regression(tmp_path: Path, monkeypatch):
    input_path = _write_fixture(tmp_path)
    branches = "no_continuity,no_continuity_osnma_lifted"

    sweep_rows_path = tmp_path / "sweep_rows.csv"
    sweep_summary_path = tmp_path / "sweep_summary.csv"
    sweep_receipt_path = tmp_path / "sweep_receipt.json"
    _run_forensic(
        monkeypatch,
        [
            "--inputs",
            str(input_path),
            "--output",
            str(sweep_rows_path),
            "--summary",
            str(sweep_summary_path),
            "--audit-output",
            str(sweep_receipt_path),
            "--max-users",
            "0",
            "--periods-per-user",
            "0",
            "--cadence-sec",
            "60",
            "--max-dt-sec",
            "600",
            "--distance-bucket-ms",
            "50,100",
            "--neighbor-radius-cells-list",
            "1,2",
            "--branches",
            branches,
        ],
    )

    rows = _csv_rows(sweep_rows_path)
    assert rows[0].keys() == {
        "branch",
        "dataset",
        "distance_bucket_m",
        "neighbor_radius_cells",
        "len_claimed_fixes",
        "savings_ratio",
        "skip_reason",
    }
    expected_sweep_points = {("50", "1"), ("50", "2"), ("100", "1"), ("100", "2")}
    assert {(row["distance_bucket_m"], row["neighbor_radius_cells"]) for row in rows} == expected_sweep_points

    summary_rows = _csv_rows(sweep_summary_path)
    assert summary_rows[0].keys() == {
        "dataset",
        "branch",
        "distance_bucket_m",
        "neighbor_radius_cells",
        "n",
        "skip_count",
        "min_savings",
        "mean_savings",
        "median_savings",
        "p95_savings",
    }
    summary_keys = {
        (row["dataset"], row["branch"], row["distance_bucket_m"], row["neighbor_radius_cells"])
        for row in summary_rows
    }
    assert summary_keys == {
        ("rome", branch, bucket_m, radius)
        for bucket_m, radius in expected_sweep_points
        for branch in branches.split(",")
    }
    assert all(int(row["n"]) + int(row["skip_count"]) == 1 for row in summary_rows)

    receipt = json.loads(sweep_receipt_path.read_text(encoding="utf-8"))
    assert all("distance_bucket_m" in row and "neighbor_radius_cells" in row for row in receipt["rows"])
    assert all(
        "distance_bucket_m" in row and "neighbor_radius_cells" in row
        for row in receipt["savings_dotplot"]
    )

    old_rows_path = tmp_path / "old_rows.csv"
    old_summary_path = tmp_path / "old_summary.csv"
    _run_forensic(
        monkeypatch,
        [
            "--inputs",
            str(input_path),
            "--output",
            str(old_rows_path),
            "--summary",
            str(old_summary_path),
            "--max-users",
            "0",
            "--periods-per-user",
            "0",
            "--cadence-sec",
            "60",
            "--max-dt-sec",
            "600",
            "--distance-bucket-m",
            "100",
            "--neighbor-radius-cells",
            "1",
            "--branches",
            branches,
        ],
    )
    new_rows_path = tmp_path / "new_rows.csv"
    new_summary_path = tmp_path / "new_summary.csv"
    _run_forensic(
        monkeypatch,
        [
            "--inputs",
            str(input_path),
            "--output",
            str(new_rows_path),
            "--summary",
            str(new_summary_path),
            "--max-users",
            "0",
            "--periods-per-user",
            "0",
            "--cadence-sec",
            "60",
            "--max-dt-sec",
            "600",
            "--distance-bucket-ms",
            "100",
            "--neighbor-radius-cells-list",
            "1",
            "--branches",
            branches,
        ],
    )

    old_baseline = {
        (row["branch"], row["dataset"]): (row["len_claimed_fixes"], row["savings_ratio"], row["skip_reason"])
        for row in _csv_rows(old_rows_path)
    }
    new_single_value = {
        (row["branch"], row["dataset"]): (row["len_claimed_fixes"], row["savings_ratio"], row["skip_reason"])
        for row in _csv_rows(new_rows_path)
    }
    assert old_baseline == new_single_value
