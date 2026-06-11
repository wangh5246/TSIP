from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams
from common.settlement import ReceiverFix, TariffTable
from script.run_baseline_r_simulator import camera_sets, omitted_segments, period_segments, segment_key
from script.run_e4_e5_ruc_experiments import PeriodRecord

_MAY_2026_START = 1_777_593_600


def _record() -> PeriodRecord:
    # 2x2 grid; cells 0,1 in cheap zone (1 c/m), cells 2,3 expensive (5 c/m).
    tariff = TariffTable(
        tariff_version=1,
        grid_w=2,
        cell_zones={0: 0, 1: 0, 2: 1, 3: 1},
        zone_rates_cents_per_m={0: 1, 1: 5},
    )
    # Edge fees use the prev fix's cell rate: (0,0)->cell0 cheap, (0,1)->cell2 expensive.
    coords = [(0, 0), (0, 1), (1, 1), (1, 1)]  # last hop dwells (no movement)
    fixes = [
        ReceiverFix(
            device_id="dev",
            period_id="p",
            fix_seq=i,
            auth_gnss_time=_MAY_2026_START + 300 * i,
            cell_x=x,
            cell_y=y,
            osnma_status="authenticated",
            odometer_reading_m=100 * i if i < 3 else 200 + 100 * (i - 1),
            nonce=f"n{i}",
        )
        for i, (x, y) in enumerate(coords)
    ]
    params = HarnessParams(cadence_sec=300, max_dt_sec=600, tier_vmax_mps=33)
    return PeriodRecord(
        dataset="test",
        record={},
        fixes=fixes,
        tariff=tariff,
        params=params,
        fee_cents=0,
        distance_m=0,
        fallback_intervals=0,
        n_intervals=len(fixes) - 1,
    )


def test_period_segments_skips_dwell_and_bills_by_zone() -> None:
    segs = dict(period_segments(_record()))
    # Two movement segments: 0->2 billed at cheap prev-cell rate, 2->3 at expensive; dwell edge dropped.
    assert set(segs) == {segment_key(0, 2), segment_key(2, 3)}
    assert segs[segment_key(2, 3)] > segs[segment_key(0, 2)]


def test_rational_omission_hides_most_expensive_segment() -> None:
    segs = period_segments(_record())
    omitted = omitted_segments(segs, 0.2, "rational_topfee", random.Random(0))
    assert omitted == [segment_key(2, 3)]


def test_full_universe_cameras_always_detect() -> None:
    segs = period_segments(_record())
    universe = [key for key, _fee in segs]
    cams = camera_sets(
        universe, Counter(universe), Counter(), len(universe), "traffic_weighted_generous", random.Random(0), 1
    )
    omitted = omitted_segments(segs, 0.2, "random", random.Random(1))
    assert any(key in cams[0] for key in omitted)


def test_uniform_random_draw_count_and_size() -> None:
    universe = [(0, 1), (1, 3), (2, 3), (0, 2)]
    draws = camera_sets(universe, Counter(universe), Counter(), 2, "uniform_random", random.Random(0), 7)
    assert len(draws) == 7
    assert all(len(d) == 2 for d in draws)


def test_adaptive_omitter_evades_partial_coverage_with_positive_saving() -> None:
    # Cameras on the most expensive segment; the adaptive omitter hides the
    # cheaper uncovered one — never detected, still saves money.
    segs = period_segments(_record())
    fee_weight = Counter({key: fee for key, fee in segs})
    universe = [key for key, _fee in segs]
    cams = camera_sets(universe, Counter(universe), fee_weight, 1, "fee_weighted_adversary_aware", random.Random(0), 1)
    assert cams[0] == frozenset({segment_key(2, 3)})  # highest-fee segment covered
    omitted = omitted_segments(segs, 0.2, "adaptive_uncovered", random.Random(0), cameras=cams[0])
    assert omitted == [segment_key(0, 2)]  # hides the uncovered segment instead
    assert not any(key in cams[0] for key in omitted)  # zero detection
    assert dict(segs)[segment_key(0, 2)] > 0  # but positive undetected saving


def test_adaptive_omitter_under_full_coverage_has_no_evasion() -> None:
    segs = period_segments(_record())
    universe = [key for key, _fee in segs]
    full = frozenset(universe)
    omitted = omitted_segments(segs, 0.2, "adaptive_uncovered", random.Random(0), cameras=full)
    assert omitted == []  # nothing uncovered left to hide
