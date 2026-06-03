from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_experiments import (
    e2_fallback_penalty,
    e2_pareto_frontier,
    e3_soundness_check,
    e4_deterrence_to_pd,
    e4_required_cameras,
    inject_outages,
)
from common.eval_harness import HarnessParams, cross_check_against_circuit
from common.settlement import ReceiverFix, TariffTable


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=1,
        grid_w=3,
        cell_zones={0: 10, 1: 20, 2: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def _fix(seq: int, ts: int, odo: int, x: int) -> ReceiverFix:
    return ReceiverFix(
        device_id="dev-1",
        period_id="p1",
        fix_seq=seq,
        auth_gnss_time=ts,
        cell_x=x,
        cell_y=0,
        osnma_status="authenticated",
        odometer_reading_m=odo,
        nonce=f"n-{seq}",
    )


def _fixes() -> list[ReceiverFix]:
    return [
        _fix(0, 0, 0, 0),
        _fix(1, 60, 100, 1),
        _fix(2, 120, 200, 2),
    ]


def test_cross_check_against_circuit_accepts_match_and_rejects_drift():
    params = HarnessParams(cadence_sec=60, tier_vmax_mps=10)
    tariff = _tariff()

    checked = cross_check_against_circuit(
        [_fixes()],
        tariff,
        params,
        lambda fixes, table, p: 600,
    )

    assert checked == 1
    with pytest.raises(AssertionError, match="fee mismatch"):
        cross_check_against_circuit([_fixes()], tariff, params, lambda fixes, table, p: 599)


def test_inject_outages_drops_unavailable_fix_and_uses_circuit_style_fallback():
    params = HarnessParams(cadence_sec=60, tier_vmax_mps=10)
    outage = inject_outages(
        _fixes(),
        lambda fix: "tunnel",
        outage_rates={"tunnel": 1.0},
        ttfaf_sec=60,
    )

    assert [fix.fix_seq for fix in outage.kept_fixes] == [0, 2]
    result = e2_fallback_penalty(
        _fixes(),
        _tariff(),
        params,
        lambda fix: "tunnel",
        outage_rates={"tunnel": 1.0},
        n_mc=3,
    )
    assert result["median"] == pytest.approx((6_000 - 600) / 600)
    assert result["dropped_fixes_by_environment"] == {"tunnel": 3}


def test_pareto_frontier_zeroes_withholding_at_max_zone_rate():
    params = HarnessParams(cadence_sec=60, tier_vmax_mps=10)

    rows = e2_pareto_frontier(
        [_fixes()],
        _tariff(),
        params,
        lambda fix: "open_sky",
        [1, 5],
        outage_rates={"open_sky": 0.0},
    )

    assert rows[0]["withholding_gain_median"] > 0
    assert rows[1]["ge_max_zone_rate"] is True
    assert rows[1]["withholding_gain_median"] == 0


def test_e4_camera_model_and_deterrence_threshold():
    row = e4_required_cameras(omit_fraction=0.10, segments_per_driver=100, road_network_segments=10_000)

    assert row["required_cameras_tsip_ruc"] == 0
    assert row["tsip_detection_rate"] == 1.0
    assert row["required_cameras_spotcheck"] == 2996
    assert e4_deterrence_to_pd(expected_saving=25, fine=100) == 0.25


def test_e3_soundness_check_rejects_basic_violation_claims():
    result = e3_soundness_check(
        _fixes(),
        _tariff(),
        HarnessParams(cadence_sec=60, tier_vmax_mps=10),
    )

    assert result == {
        "teleport": True,
        "replay": True,
        "drop_segment": True,
        "detection_rate": 1.0,
    }
