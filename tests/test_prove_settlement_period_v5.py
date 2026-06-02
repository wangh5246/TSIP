from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dataclasses import replace

import pytest

from common.eval_harness import HarnessParams
from script.prove_settlement_period_v5 import (
    CADENCE_SEC,
    MAX_DT_SEC,
    SETTLEMENT_PROFILE,
    TIER_VMAX_MPS,
    build_fixes,
    build_input,
    build_input_for_fixes,
    build_raw_witness_input_for_fixes,
    build_tariff,
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
