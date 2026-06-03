from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dataclasses import replace

import pytest

from common.eval_harness import HarnessParams
from script.prove_settlement_period_v5 import (
    CADENCE_SEC,
    CELL_SIZE,
    MAX_DT_SEC,
    SETTLEMENT_PROFILE,
    TIER_VMAX_MPS,
    build_fixes,
    build_input,
    build_input_for_fixes,
    build_raw_witness_input_for_fixes,
    build_tariff,
)

WASM = (
    ROOT_DIR
    / "zk"
    / "settlement_period_v5_k6"
    / "settlement_period_v5_k6_js"
    / "settlement_period_v5_k6.wasm"
)


def run_wtns(input_json: dict[str, object]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="settlement-v5-test-") as td:
        input_path = Path(td) / "input.json"
        witness_path = Path(td) / "witness.wtns"
        input_path.write_text(json.dumps(input_json, sort_keys=True), encoding="utf-8")
        return subprocess.run(
            ["snarkjs", "wtns", "calculate", str(WASM), str(input_path), str(witness_path)],
            cwd=ROOT_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )


def test_build_input_includes_time_window_and_canonical_month_public_signals():
    input_json, _submission = build_input()

    assert input_json["max_dt_sec"] == str(MAX_DT_SEC)
    assert input_json["period_start_time"] == input_json["auth_time"][0]
    assert input_json["period_end_time"] == input_json["auth_time"][-1]
    assert input_json["month_id"] == "202605"
    assert input_json["month_start_time"] == "1777593600"
    assert input_json["month_end_time"] == "1780272000"


def test_build_input_delegates_to_explicit_fixes_builder(monkeypatch):
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    tariff = build_tariff()
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)

    monkeypatch.setattr("script.prove_settlement_period_v5.build_tariff", lambda: tariff)
    monkeypatch.setattr("script.prove_settlement_period_v5.build_fixes", lambda _period_id: fixes)

    assert build_input() == build_input_for_fixes(fixes, tariff, params=params)


def test_raw_witness_builder_uses_2026_month_window_and_zero_cell_remainders():
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)

    input_json = build_raw_witness_input_for_fixes(fixes, build_tariff(), params=params)

    assert input_json["month_id"] == "202605"
    assert input_json["month_start_time"] == "1777593600"
    assert input_json["month_end_time"] == "1780272000"
    assert input_json["payload_rem_x"] == ["0"] * 24
    assert input_json["payload_rem_y"] == ["0"] * 24


def test_raw_witness_builder_serializes_dt_above_max_without_python_rejection():
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)
    invalid = list(fixes)
    invalid[1] = replace(invalid[1], auth_gnss_time=invalid[0].auth_gnss_time + MAX_DT_SEC + 1)

    input_json = build_raw_witness_input_for_fixes(invalid, build_tariff(), params=params)

    assert int(input_json["auth_time"][1]) - int(input_json["auth_time"][0]) == MAX_DT_SEC + 1


def test_raw_witness_builder_receiver_root_does_not_bind_receiver_signatures():
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)

    signed = build_raw_witness_input_for_fixes(fixes, build_tariff(), params=params)
    unsigned = build_raw_witness_input_for_fixes(
        [replace(fix, receiver_sig="") for fix in fixes],
        build_tariff(),
        params=params,
    )

    assert unsigned["receiver_fix_root"] == signed["receiver_fix_root"]


def test_raw_witness_builder_requires_compiled_fix_count():
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)

    with pytest.raises(ValueError, match="expected exactly 25 fixes"):
        build_raw_witness_input_for_fixes(fixes[:-1], build_tariff(), params=params)


@pytest.mark.skipif(not WASM.exists(), reason="settlement v5 WASM is not compiled")
def test_witness_rejects_terminal_fix_cell_separated_from_terminal_geometry():
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)
    invalid = list(fixes)
    invalid[-1] = replace(invalid[-1], cell_x=99, cell_y=99)
    input_json = build_raw_witness_input_for_fixes(invalid, build_tariff(), params=params)
    input_json["x"][-1] = "2400"
    input_json["y"][-1] = "0"

    result = run_wtns(input_json)

    assert result.returncode != 0, result.stdout


@pytest.mark.skipif(not WASM.exists(), reason="settlement v5 WASM is not compiled")
def test_witness_rejects_in_range_terminal_cell_teleport_at_step_continuity():
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    tariff = build_tariff()
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)
    honest_input = build_raw_witness_input_for_fixes(fixes, tariff, params=params)
    invalid = list(fixes)
    invalid[-1] = replace(invalid[-1], cell_x=99, cell_y=99)
    input_json = build_raw_witness_input_for_fixes(invalid, tariff, params=params)

    assert input_json["fix_cell_x"][-1] == "99"
    assert input_json["fix_cell_y"][-1] == "99"
    assert int(input_json["auth_time"][-1]) - int(input_json["auth_time"][-2]) == CADENCE_SEC
    assert int(input_json["odometer_m"][-1]) - int(input_json["odometer_m"][-2]) == CELL_SIZE
    assert input_json["payload_cell_idx"] == honest_input["payload_cell_idx"]
    assert input_json["receiver_fix_root"] != honest_input["receiver_fix_root"]

    result = run_wtns(input_json)

    assert result.returncode != 0
    assert "SettlementPeriodV5_101 line: 310" in result.stdout
