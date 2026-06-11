from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import TariffTable
from script.run_e4_e5_ruc_experiments import count_resource_paths, observed_graph, road_proxy_stats


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=1,
        grid_w=3,
        cell_zones={0: 1, 1: 2, 2: 2},
        zone_rates_cents_per_m={1: 1, 2: 5},
    )


def test_count_resource_paths_uses_fee_constraint_to_shrink_candidates() -> None:
    tariff = _tariff()
    graph = {
        0: [(0, 0), (1, 100)],
        1: [(1, 0), (2, 100)],
        2: [(2, 0)],
    }

    odometer_only = count_resource_paths(
        graph,
        tariff,
        n_steps=2,
        target_distance_m=200,
        target_fee_cents=600,
        mode="odometer_only_graph_proxy",
        distance_bucket_m=100,
        fee_bucket_cents=100,
        max_states=1000,
    )
    zone_priced = count_resource_paths(
        graph,
        tariff,
        n_steps=2,
        target_distance_m=200,
        target_fee_cents=600,
        mode="zone_priced_graph_proxy",
        distance_bucket_m=100,
        fee_bucket_cents=100,
        max_states=1000,
    )

    assert odometer_only >= zone_priced
    assert zone_priced > 0


def test_observed_graph_and_road_proxy_use_observed_odometer_edges() -> None:
    from common.eval_harness import HarnessParams
    from common.settlement import ReceiverFix
    from script.run_e4_e5_ruc_experiments import PeriodRecord

    tariff = _tariff()
    fixes = [
        ReceiverFix("dev", "p", 0, 0, 0, 0, "authenticated", 0, "n0"),
        ReceiverFix("dev", "p", 1, 60, 1, 0, "authenticated", 125, "n1"),
    ]
    record = PeriodRecord(
        dataset="unit",
        record={"period_id": "p"},
        fixes=fixes,
        tariff=tariff,
        params=HarnessParams(cadence_sec=60, cell_size_m=100),
        fee_cents=125,
        distance_m=125,
        fallback_intervals=0,
        n_intervals=1,
    )

    graph = observed_graph([record])
    stats = road_proxy_stats([record], graph)

    assert graph[0] == [(0, 0), (1, 125)]
    assert stats["observed_road_segments"] == 1
