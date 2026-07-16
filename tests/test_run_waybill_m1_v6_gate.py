from __future__ import annotations

from common.settlement_v6 import reconcile_month_v6
from script.run_waybill_m1_v6_gate import deterministic_outage_edges, evaluate_mask


def _edge(*, edge: int = 0, dt: int = 300, delta: int = 100, rate: int = 2) -> dict[str, int]:
    return {
        "edge": edge,
        "dt_sec": dt,
        "delta_odo_m": delta,
        "cell_idx": edge,
        "zone_id": 1,
        "zone_rate_cents_per_m": rate,
    }


def test_outage_masks_are_reproducible_and_nonempty() -> None:
    first = deterministic_outage_edges(
        dataset="rome", period_id="p1", n_intervals=17, alpha=0.1, seed=17
    )
    second = deterministic_outage_edges(
        dataset="rome", period_id="p1", n_intervals=17, alpha=0.1, seed=17
    )
    assert first == second
    assert len(first) == 2
    assert first != deterministic_outage_edges(
        dataset="rome", period_id="p1", n_intervals=17, alpha=0.1, seed=31
    )


def test_v6_withholding_is_monotone_and_uses_no_time_distance() -> None:
    result = evaluate_mask([_edge(dt=600, delta=100, rate=2)], outage_edges=[0], r_max_cents_per_m=5)
    assert result["oracle_fee_cents"] == 200
    assert result["v6_fee_cents"] == 500
    assert result["v5_fee_cents"] == 600 * 33 * 5
    assert result["max_withholding_advantage_cents"] == 0


def test_parking_outage_is_zero_and_month_close_only_bills_unaccounted() -> None:
    parking = evaluate_mask(
        [_edge(dt=600, delta=0, rate=2)], outage_edges=[0], r_max_cents_per_m=5
    )
    assert parking["v6_fee_cents"] == 0
    assert parking["parking_v6_fee_cents"] == 0
    assert parking["parking_v5_fee_cents"] > 0

    close = reconcile_month_v6(
        monthly_odometer_start_m=1_000,
        monthly_odometer_end_m=2_000,
        accounted_distance_m=70,
        accepted_period_fee_cents=70,
        r_max_cents_per_m=5,
    )
    assert close["unaccounted_distance_m"] == 930
    assert close["total_month_bill_cents"] == 70 + 930 * 5


def test_period_evaluation_reports_admission_bounds() -> None:
    result = evaluate_mask(
        [_edge(edge=0, dt=10, delta=331), _edge(edge=1, dt=601, delta=0)],
        outage_edges=[0, 1],
        r_max_cents_per_m=5,
    )
    assert result["speed_bound_ok"] is False
    assert result["max_dt_ok"] is False
