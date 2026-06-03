from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import (
    ALL_CONSTRAINTS,
    Constraint,
    HarnessParams,
    adversary_min_fee,
    check_constraints,
    compute_bill,
    e1_ablation_row,
    e1_forensic_rows,
    relay_allowed_cells_by_fix,
    write_e1_forensic_csv,
)
from common.settlement import ReceiverFix, TariffTable


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=1,
        grid_w=3,
        cell_zones={
            0: 10,
            1: 20,
            2: 20,
            3: 10,
            4: 20,
            5: 20,
            6: 10,
            7: 20,
            8: 20,
        },
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def _fix(seq: int, ts: int, odo: int, x: int, y: int) -> ReceiverFix:
    return ReceiverFix(
        device_id="dev-1",
        period_id="p1",
        fix_seq=seq,
        auth_gnss_time=ts,
        cell_x=x,
        cell_y=y,
        osnma_status="authenticated",
        odometer_reading_m=odo,
        nonce=f"n-{seq}",
    )


def test_compute_bill_delegates_to_settlement_fee_logic():
    params = HarnessParams(cadence_sec=60, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 1, 0), _fix(1, 30, 100, 2, 0)]

    bill = compute_bill(fixes, _tariff(), params)

    assert bill["total_fee_cents"] == 500
    assert bill["total_distance_m"] == 100
    assert bill["private_zone_distance_m"] == {20: 100}


def test_check_constraints_catches_odometer_continuity_and_osnma_relaxations():
    params = HarnessParams(cadence_sec=60, tier_vmax_mps=1, cell_size_m=100, distance_bucket_m=100)
    true_fixes = [_fix(0, 0, 0, 0, 0), _fix(1, 50, 100, 1, 0)]
    claimed = [_fix(0, 0, 0, 0, 0), _fix(1, 50, 0, 2, 0)]

    assert not check_constraints(claimed, true_fixes=true_fixes, enabled=ALL_CONSTRAINTS, params=params, tariff=_tariff())
    assert check_constraints(
        claimed,
        true_fixes=true_fixes,
        enabled={Constraint.CADENCE},
        params=params,
        tariff=_tariff(),
    )


def test_check_constraints_enforces_max_dt_independently_from_cadence():
    params = HarnessParams(
        cadence_sec=300,
        max_dt_sec=60,
        tier_vmax_mps=33,
        cell_size_m=100,
        distance_bucket_m=100,
    )
    true_fixes = [_fix(0, 0, 0, 0, 0), _fix(1, 120, 0, 0, 0)]

    assert not check_constraints(
        true_fixes,
        true_fixes=true_fixes,
        enabled={Constraint.MAX_DT},
        params=params,
        tariff=_tariff(),
    )
    assert check_constraints(
        true_fixes,
        true_fixes=true_fixes,
        enabled={Constraint.CADENCE},
        params=params,
        tariff=_tariff(),
    )


def test_adversary_all_on_strict_osnma_matches_honest_bill():
    params = HarnessParams(cadence_sec=120, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 1, 0), _fix(1, 60, 100, 2, 0)]

    result = adversary_min_fee(fixes, _tariff(), enabled=ALL_CONSTRAINTS, params=params)

    assert result.min_fee_cents == result.honest_fee_cents == 500
    assert result.savings_ratio == 0.0
    assert [(f.cell_x, f.cell_y) for f in result.claimed_fixes] == [(1, 0), (2, 0)]


def test_adversary_without_max_dt_does_not_use_honest_fast_path():
    params = HarnessParams(cadence_sec=120, max_dt_sec=600, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 1, 0), _fix(1, 60, 100, 2, 0)]

    result = adversary_min_fee(
        fixes,
        _tariff(),
        enabled=ALL_CONSTRAINTS - {Constraint.MAX_DT},
        params=params,
    )

    assert [fix.nonce for fix in result.claimed_fixes] == ["adv-0-0-1", "adv-1-1-2"]


def test_adversary_without_odometer_can_collapse_distance_to_zero():
    params = HarnessParams(cadence_sec=120, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 1, 0), _fix(1, 60, 100, 2, 0)]

    result = adversary_min_fee(
        fixes,
        _tariff(),
        enabled={Constraint.CONTINUITY, Constraint.CADENCE},
        params=params,
    )

    assert result.honest_fee_cents == 500
    assert result.min_fee_cents == 0
    assert result.savings_ratio == 1.0


def test_adversary_without_continuity_moves_distance_to_cheapest_zone():
    params = HarnessParams(cadence_sec=120, tier_vmax_mps=2, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 1, 0), _fix(1, 60, 100, 2, 0)]

    result = adversary_min_fee(
        fixes,
        _tariff(),
        enabled={Constraint.ODOMETER, Constraint.CADENCE},
        params=params,
    )

    assert result.honest_fee_cents == 500
    assert result.min_fee_cents == 100
    assert result.savings_ratio == 0.8


def test_adversary_without_cadence_can_drop_expensive_middle_fix():
    params = HarnessParams(cadence_sec=60, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [
        _fix(0, 0, 0, 0, 0),
        _fix(1, 60, 100, 1, 0),
        _fix(2, 120, 200, 2, 0),
    ]

    result = adversary_min_fee(
        fixes,
        _tariff(),
        enabled={Constraint.ODOMETER, Constraint.CONTINUITY, Constraint.OSNMA},
        params=params,
    )

    assert result.honest_fee_cents == 600
    assert result.min_fee_cents == 200
    assert [(f.cell_x, f.cell_y) for f in result.claimed_fixes] == [(0, 0), (2, 0)]


def test_e1_row_uses_fast_odometer_relaxation_and_relay_candidates_are_local():
    params = HarnessParams(cadence_sec=120, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 1, 0), _fix(1, 60, 100, 2, 0)]

    row = e1_ablation_row(fixes, _tariff(), params)
    relay = relay_allowed_cells_by_fix(fixes, _tariff(), radius_m=100, params=params)

    assert row["all_on"] == 0
    assert row["no_odometer"] == 1
    assert "no_max_dt" in row
    assert relay[0] == {0, 1, 2}


def test_e1_forensic_rows_record_claim_length_savings_and_skip_reason(tmp_path: Path):
    params = HarnessParams(cadence_sec=120, max_dt_sec=120, tier_vmax_mps=33, cell_size_m=100, distance_bucket_m=100)
    fixes = [_fix(0, 0, 0, 2, 0), _fix(1, 60, 100, 1, 0)]

    rows = e1_forensic_rows(fixes, _tariff(), params, dataset="unit")
    by_branch = {str(row["branch"]): row for row in rows}

    assert by_branch["no_odometer"]["savings_ratio"] == 1.0
    assert by_branch["no_odometer"]["len_claimed_fixes"] == 2
    assert by_branch["no_zone_binding"]["savings_ratio"] > 0.0
    assert by_branch["no_continuity"]["savings_ratio"] == 0.0
    assert by_branch["no_continuity_osnma_lifted"]["savings_ratio"] > 0.0
    assert by_branch["no_max_dt"]["skip_reason"] == ""

    skip_rows = e1_forensic_rows(fixes[:1], _tariff(), params, dataset="unit")
    assert skip_rows[0]["skip_reason"] == "at least two fixes are required"

    output = tmp_path / "e1_forensic.csv"
    assert write_e1_forensic_csv(rows, output) == 7
    assert output.read_text(encoding="utf-8").splitlines()[0] == (
        "branch,dataset,len_claimed_fixes,savings_ratio,skip_reason"
    )
