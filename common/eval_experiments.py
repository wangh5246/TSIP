from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from common.eval_harness import (
    ALL_CONSTRAINTS,
    HarnessParams,
    adversary_min_fee,
    check_constraints,
    compute_bill,
)
from common.settlement import ReceiverFix, TariffTable


DEFAULT_OUTAGE_RATES: dict[str, float] = {
    "highway": 0.01,
    "open_sky": 0.01,
    "rural": 0.02,
    "suburban": 0.05,
    "urban": 0.30,
    "tunnel": 1.00,
    "underground": 1.00,
}
DEFAULT_TTFAF_SEC = 60

EnvLabeler = Callable[[ReceiverFix], str]
TariffAtGranularity = Callable[[str], TariffTable]
Verifier = Callable[[list[ReceiverFix]], bool]


@dataclass(frozen=True)
class OutageRun:
    kept_fixes: list[ReceiverFix]
    dropped_by_environment: dict[str, int]


def inject_outages(
    fixes: list[ReceiverFix],
    env_labeler: EnvLabeler,
    *,
    outage_rates: dict[str, float] | None = None,
    ttfaf_sec: int = DEFAULT_TTFAF_SEC,
    rng: random.Random | None = None,
) -> OutageRun:
    """Drop unavailable authenticated fixes so settlement charges gap fallback."""

    if len(fixes) < 2:
        raise ValueError("at least two fixes are required")
    outage_rates = outage_rates or DEFAULT_OUTAGE_RATES
    rng = rng or random.Random()
    kept = [fixes[0]]
    dropped: dict[str, int] = {}
    reacquire_until = -1
    for fix in fixes[1:-1]:
        env = env_labeler(fix)
        unavailable = int(fix.auth_gnss_time) < reacquire_until or rng.random() < outage_rates.get(env, 0.05)
        if unavailable:
            dropped[env] = dropped.get(env, 0) + 1
            reacquire_until = max(reacquire_until, int(fix.auth_gnss_time) + int(ttfaf_sec))
        else:
            kept.append(fix)
    kept.append(fixes[-1])
    return OutageRun(kept_fixes=kept, dropped_by_environment=dropped)


def e2_fallback_penalty(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    env_labeler: EnvLabeler,
    *,
    outage_rates: dict[str, float] | None = None,
    ttfaf_sec: int = DEFAULT_TTFAF_SEC,
    n_mc: int = 200,
    seed: int = 0,
) -> dict:
    honest = max(1, int(compute_bill(fixes, tariff, params)["total_fee_cents"]))
    rng = random.Random(seed)
    penalties: list[float] = []
    dropped: dict[str, int] = {}
    for _ in range(int(n_mc)):
        outage = inject_outages(
            fixes,
            env_labeler,
            outage_rates=outage_rates,
            ttfaf_sec=ttfaf_sec,
            rng=rng,
        )
        bill = int(compute_bill(outage.kept_fixes, tariff, params)["total_fee_cents"])
        penalties.append((bill - honest) / honest)
        for env, count in outage.dropped_by_environment.items():
            dropped[env] = dropped.get(env, 0) + count
    return {
        "median": statistics.median(penalties),
        "p25": _percentile(penalties, 25),
        "p75": _percentile(penalties, 75),
        "p95": _percentile(penalties, 95),
        "mean": statistics.fmean(penalties),
        "dropped_fixes_by_environment": dict(sorted(dropped.items())),
    }


def e2_pareto_frontier(
    trajectories: Iterable[list[ReceiverFix]],
    tariff: TariffTable,
    params: HarnessParams,
    env_labeler: EnvLabeler,
    fallback_rates_cents_per_m: Iterable[int],
    *,
    outage_rates: dict[str, float] | None = None,
    seed: int = 0,
) -> list[dict]:
    """Compare honest fallback penalty with rate-only withholding benefit."""

    rng = random.Random(seed)
    rows: list[dict] = []
    trajectories = list(trajectories)
    for fallback_rate in fallback_rates_cents_per_m:
        honest_penalties: list[float] = []
        withholding_gains: list[float] = []
        for fixes in trajectories:
            honest = max(1, int(compute_bill(fixes, tariff, params)["total_fee_cents"]))
            outage = inject_outages(fixes, env_labeler, outage_rates=outage_rates, rng=rng)
            fallback_bill = _bill_with_fallback_rate(outage.kept_fixes, tariff, params, fallback_rate)
            honest_penalties.append((fallback_bill - honest) / honest)
            gain = 0
            for prev, curr in zip(fixes, fixes[1:]):
                odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
                zone = tariff.zone_for_cell(tariff.cell_index(prev.cell_x, prev.cell_y))
                gain += max(0, tariff.rate_for_zone(zone) - int(fallback_rate)) * odo_delta
            withholding_gains.append(gain / honest)
        rows.append(
            {
                "fallback_rate_cents_per_m": int(fallback_rate),
                "ge_max_zone_rate": int(fallback_rate) >= tariff.max_zone_rate_cents_per_m,
                "honest_penalty_median": statistics.median(honest_penalties),
                "withholding_gain_median": statistics.median(withholding_gains),
            }
        )
    return rows


def e3_residual_sweep(
    trajectories: Iterable[list[ReceiverFix]],
    tariff_at_granularity: TariffAtGranularity,
    granularities: Iterable[str],
    relay_modes: dict[str, tuple[HarnessParams, Callable[[list[ReceiverFix], TariffTable], list[set[int]]]]],
) -> dict[tuple[str, str], dict[str, float]]:
    """Run the proof-consistent relay adversary over granularity and relay modes."""

    trajectories = list(trajectories)
    grid: dict[tuple[str, str], dict[str, float]] = {}
    for granularity in granularities:
        tariff = tariff_at_granularity(granularity)
        for mode, (params, allowed_cells_fn) in relay_modes.items():
            savings: list[float] = []
            for fixes in trajectories:
                result = adversary_min_fee(
                    fixes,
                    tariff,
                    enabled=ALL_CONSTRAINTS,
                    params=params,
                    allowed_cells_by_fix=allowed_cells_fn(fixes, tariff),
                )
                savings.append(result.savings_ratio)
            grid[(granularity, mode)] = {
                "median_residual": statistics.median(savings),
                "p95_residual": _percentile(savings, 95),
            }
    return grid


def e3_soundness_check(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    *,
    verifier: Verifier | None = None,
) -> dict[str, bool | float]:
    """Check teleport, replay, and dropped-segment claims with a real verifier hook."""

    attacks = {
        "teleport": _teleport_claim(true_fixes),
        "replay": _replay_claim(true_fixes),
        "drop_segment": _drop_claim(true_fixes),
    }
    results: dict[str, bool | float] = {}
    for name, claim in attacks.items():
        accepted = (
            bool(verifier(claim))
            if verifier is not None
            else check_constraints(
                claim,
                true_fixes=true_fixes,
                enabled=ALL_CONSTRAINTS,
                params=params,
                tariff=tariff,
            )
        )
        results[name] = not accepted
    results["detection_rate"] = sum(bool(results[name]) for name in attacks) / len(attacks)
    return results


def e4_required_cameras(
    omit_fraction: float,
    segments_per_driver: int,
    road_network_segments: int,
    *,
    p_detect_target: float = 0.95,
) -> dict:
    if not 0 < p_detect_target < 1:
        raise ValueError("p_detect_target must be between 0 and 1")
    if omit_fraction <= 0 or segments_per_driver <= 0 or road_network_segments <= 0:
        raise ValueError("E4 inputs must be positive")
    omitted = float(omit_fraction) * int(segments_per_driver)
    coverage = min(1.0, -math.log(1.0 - float(p_detect_target)) / omitted)
    return {
        "required_coverage_fraction": coverage,
        "required_cameras_spotcheck": math.ceil(coverage * int(road_network_segments)),
        "required_cameras_tsip_ruc": 0,
        "tsip_detection_rate": 1.0,
    }


def e4_deterrence_to_pd(expected_saving: float, fine: float) -> float:
    if expected_saving < 0 or fine <= 0:
        raise ValueError("expected_saving must be non-negative and fine must be positive")
    return min(float(expected_saving) / float(fine), 0.999)


def _bill_with_fallback_rate(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    fallback_rate: int,
) -> int:
    total = 0
    for prev, curr in zip(fixes, fixes[1:]):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        if dt > int(params.cadence_sec):
            total += math.ceil(dt * int(params.tier_vmax_mps)) * int(fallback_rate)
        else:
            zone = tariff.zone_for_cell(tariff.cell_index(prev.cell_x, prev.cell_y))
            total += (int(curr.odometer_reading_m) - int(prev.odometer_reading_m)) * tariff.rate_for_zone(zone)
    return total


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    rank = (len(ordered) - 1) * float(q) / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def _teleport_claim(fixes: list[ReceiverFix]) -> list[ReceiverFix]:
    out = list(fixes)
    middle = len(out) // 2
    out[middle] = replace(out[middle], cell_x=out[middle].cell_x + 1000, receiver_sig="")
    return out


def _replay_claim(fixes: list[ReceiverFix]) -> list[ReceiverFix]:
    out = list(fixes)
    if len(out) >= 2:
        out[1] = replace(out[1], auth_gnss_time=out[0].auth_gnss_time, receiver_sig="")
    return out


def _drop_claim(fixes: list[ReceiverFix]) -> list[ReceiverFix]:
    if len(fixes) < 3:
        return list(fixes)
    return [fixes[0], *fixes[2:]]
