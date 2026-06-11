from __future__ import annotations

import csv
import heapq
import math
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable

from common.settlement import ReceiverFix, TariffTable, fee_for_interval_values, fee_for_period


class Constraint(StrEnum):
    ODOMETER = "odometer"
    CONTINUITY = "continuity"
    CADENCE = "cadence"
    MAX_DT = "max_dt"
    OSNMA = "osnma"


ALL_CONSTRAINTS: frozenset[Constraint] = frozenset(Constraint)


@dataclass(frozen=True)
class HarnessParams:
    cadence_sec: int = 60
    max_dt_sec: int = 600
    tier_vmax_mps: int = 33
    cell_size_m: int = 100
    distance_bucket_m: int = 100
    odometer_tolerance_m: int = 0
    fallback_rate_cents_per_m: int | None = None


@dataclass(frozen=True)
class AdversaryResult:
    min_fee_cents: int
    honest_fee_cents: int
    savings_ratio: float
    claimed_fixes: list[ReceiverFix]
    total_distance_m: int


def compute_bill(
    claimed_fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
) -> dict:
    """Circuit-compatible fee recomputation wrapper for evaluation code.

    This intentionally delegates to the settlement implementation used by the
    charger tests. Evaluation experiments should not maintain a second fee
    formula unless the circuit formula changes.
    """

    return fee_for_period(
        claimed_fixes,
        tariff,
        cadence_sec=int(params.cadence_sec),
        tier_vmax_mps=int(params.tier_vmax_mps),
        max_dt_sec=int(params.max_dt_sec),
        fallback_rate_cents_per_m=params.fallback_rate_cents_per_m,
    )


def total_odometer_distance(fixes: list[ReceiverFix]) -> int:
    if len(fixes) < 2:
        return 0
    return int(fixes[-1].odometer_reading_m) - int(fixes[0].odometer_reading_m)


def check_constraints(
    claimed_fixes: list[ReceiverFix],
    *,
    true_fixes: list[ReceiverFix],
    enabled: Iterable[Constraint],
    params: HarnessParams,
    allowed_cells_by_fix: list[set[int]] | None = None,
    tariff: TariffTable | None = None,
) -> bool:
    enabled_set = {Constraint(c) for c in enabled}
    if len(claimed_fixes) < 2:
        return False
    if Constraint.ODOMETER in enabled_set:
        delta = abs(total_odometer_distance(claimed_fixes) - total_odometer_distance(true_fixes))
        if delta > int(params.odometer_tolerance_m):
            return False
    for i, (prev, curr) in enumerate(zip(claimed_fixes, claimed_fixes[1:])):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        if dt <= 0:
            return False
        if Constraint.MAX_DT in enabled_set and dt > int(params.max_dt_sec):
            return False
        if Constraint.CONTINUITY in enabled_set:
            dist_m = _cell_distance_m(prev.cell_x, prev.cell_y, curr.cell_x, curr.cell_y, params.cell_size_m)
            if dist_m > int(params.tier_vmax_mps) * dt:
                return False
    if Constraint.OSNMA in enabled_set:
        if allowed_cells_by_fix is not None:
            if len(allowed_cells_by_fix) != len(claimed_fixes):
                return False
            for fix, allowed in zip(claimed_fixes, allowed_cells_by_fix):
                if _cell_idx(tariff, fix.cell_x, fix.cell_y) not in allowed:
                    return False
        else:
            if len(claimed_fixes) != len(true_fixes):
                return False
            for claimed, true in zip(claimed_fixes, true_fixes):
                if (claimed.cell_x, claimed.cell_y) != (true.cell_x, true.cell_y):
                    return False
    return True


def adversary_min_fee(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    enabled: Iterable[Constraint] = ALL_CONSTRAINTS,
    params: HarnessParams | None = None,
    candidate_cells: Iterable[int] | None = None,
    allowed_cells_by_fix: list[set[int]] | None = None,
) -> AdversaryResult:
    """Solve the E1/E3 adversarial billing relaxation on a tariff grid.

    The solver is a shortest path over (fix index, tariff cell, distance bucket).
    With ODOMETER enabled, paths must accumulate the true odometer distance.
    With CADENCE enabled, edges only connect adjacent fixes; otherwise the path
    may skip intermediate fixes, modeling dropped/censored receiver fixes.
    """

    if len(true_fixes) < 2:
        raise ValueError("at least two fixes are required")
    params = params or HarnessParams()
    enabled_set = {Constraint(c) for c in enabled}
    default_cells = (
        tariff.cell_zones.keys()
        if Constraint.OSNMA in enabled_set
        else _restricted_global_grid(true_fixes, tariff)
    )
    cells = sorted(set(candidate_cells or default_cells))
    if not cells:
        raise ValueError("candidate cell set is empty")
    cell_set = set(cells)
    distance_cache: dict[tuple[int, int], float] = {}

    def distance_by_cell(a: int, b: int) -> float:
        key = (a, b) if a <= b else (b, a)
        cached = distance_cache.get(key)
        if cached is None:
            cached = _cell_distance_by_idx_m(tariff, a, b, params.cell_size_m)
            distance_cache[key] = cached
        return cached

    honest = compute_bill(true_fixes, tariff, params)
    honest_fee = int(honest["total_fee_cents"])
    target_distance_m = total_odometer_distance(true_fixes)

    if enabled_set == set(ALL_CONSTRAINTS) and allowed_cells_by_fix is None:
        return AdversaryResult(
            min_fee_cents=honest_fee,
            honest_fee_cents=honest_fee,
            savings_ratio=0.0,
            claimed_fixes=list(true_fixes),
            total_distance_m=target_distance_m,
        )

    if (
        allowed_cells_by_fix is None
        and enabled_set == set(ALL_CONSTRAINTS - {Constraint.CONTINUITY})
    ):
        return AdversaryResult(
            min_fee_cents=honest_fee,
            honest_fee_cents=honest_fee,
            savings_ratio=0.0,
            claimed_fixes=list(true_fixes),
            total_distance_m=target_distance_m,
        )

    if Constraint.ODOMETER not in enabled_set:
        parked = _parked_claim(true_fixes, tariff)
        bill = compute_bill(parked, tariff, params)
        min_fee = int(bill["total_fee_cents"])
        return AdversaryResult(
            min_fee_cents=min_fee,
            honest_fee_cents=honest_fee,
            savings_ratio=0.0 if honest_fee <= 0 else max(0.0, (honest_fee - min_fee) / honest_fee),
            claimed_fixes=parked,
            total_distance_m=0,
        )

    if Constraint.CONTINUITY not in enabled_set and Constraint.OSNMA not in enabled_set:
        parked = _parked_claim(true_fixes, tariff, preserve_odometer=True)
        bill = compute_bill(parked, tariff, params)
        min_fee = int(bill["total_fee_cents"])
        return AdversaryResult(
            min_fee_cents=min_fee,
            honest_fee_cents=honest_fee,
            savings_ratio=0.0 if honest_fee <= 0 else max(0.0, (honest_fee - min_fee) / honest_fee),
            claimed_fixes=parked,
            total_distance_m=target_distance_m,
        )

    if Constraint.OSNMA in enabled_set and allowed_cells_by_fix is None:
        allowed_cells_by_fix = [
            {_cell_idx(tariff, fix.cell_x, fix.cell_y)}
            for fix in true_fixes
        ]
    elif allowed_cells_by_fix is None:
        allowed_cells_by_fix = [set(cells) for _ in true_fixes]

    if len(allowed_cells_by_fix) != len(true_fixes):
        raise ValueError("allowed_cells_by_fix length must match true_fixes")
    allowed_cell_lists = [sorted(set(allowed) & cell_set) for allowed in allowed_cells_by_fix]

    bucket_m = max(1, int(params.distance_bucket_m))
    target_bucket = int(round(target_distance_m / bucket_m)) if Constraint.ODOMETER in enabled_set else None
    max_bucket = max(0, int(math.ceil((target_distance_m + params.odometer_tolerance_m) / bucket_m)) + 1)
    if target_bucket is None:
        max_bucket = 0

    start_states: list[tuple[int, tuple[int, int, int]]] = []
    for cell in allowed_cell_lists[0]:
        start_states.append((0, (0, int(cell), 0)))
    if not start_states:
        raise ValueError("no feasible start cells")

    pq: list[tuple[int, int, int, int]] = []
    best: dict[tuple[int, int, int], int] = {}
    parent: dict[tuple[int, int, int], tuple[int, int, int] | None] = {}
    for cost, state in start_states:
        best[state] = cost
        parent[state] = None
        heapq.heappush(pq, (cost, *state))

    final_state: tuple[int, int, int] | None = None
    while pq:
        cost, i, cell, bucket = heapq.heappop(pq)
        state = (i, cell, bucket)
        if cost != best.get(state):
            continue
        if i == len(true_fixes) - 1:
            if target_bucket is None or abs(bucket - target_bucket) * bucket_m <= params.odometer_tolerance_m + bucket_m // 2:
                final_state = state
                break
        for j in _next_indices(i, len(true_fixes), Constraint.CADENCE in enabled_set):
            dt = int(true_fixes[j].auth_gnss_time) - int(true_fixes[i].auth_gnss_time)
            if dt <= 0:
                continue
            if Constraint.MAX_DT in enabled_set and dt > int(params.max_dt_sec):
                continue
            for next_cell in allowed_cell_lists[j]:
                dist_m = distance_by_cell(cell, next_cell)
                if Constraint.CONTINUITY in enabled_set and dist_m > int(params.tier_vmax_mps) * dt:
                    continue
                next_bucket = bucket
                if Constraint.ODOMETER in enabled_set:
                    next_bucket = bucket + int(round(dist_m / bucket_m))
                    if next_bucket > max_bucket:
                        continue
                edge_fee = int(
                    fee_for_interval_values(
                        dt_sec=dt,
                        odo_delta_m=int(round(dist_m)),
                        cell_idx=cell,
                        tariff=tariff,
                        cadence_sec=int(params.cadence_sec),
                        tier_vmax_mps=int(params.tier_vmax_mps),
                        max_dt_sec=int(params.max_dt_sec) if Constraint.MAX_DT in enabled_set else None,
                        fallback_rate_cents_per_m=params.fallback_rate_cents_per_m,
                    )["fee_cents"]
                )
                next_cost = cost + edge_fee
                next_state = (j, int(next_cell), next_bucket)
                if next_cost < best.get(next_state, 1 << 120):
                    best[next_state] = next_cost
                    parent[next_state] = state
                    heapq.heappush(pq, (next_cost, *next_state))

    if final_state is None:
        raise ValueError("no feasible adversarial claim under enabled constraints")

    path_states = _reconstruct_path(parent, final_state)
    claimed = _states_to_fixes(path_states, true_fixes, tariff, params)
    min_fee = int(compute_bill(claimed, tariff, params)["total_fee_cents"])
    savings = 0.0 if honest_fee <= 0 else max(0.0, (honest_fee - min_fee) / honest_fee)
    return AdversaryResult(
        min_fee_cents=min_fee,
        honest_fee_cents=honest_fee,
        savings_ratio=savings,
        claimed_fixes=claimed,
        total_distance_m=total_odometer_distance(claimed),
    )


def zone_binding_min_fee(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
) -> AdversaryResult:
    """Evaluate a rate/zone-binding bypass while preserving the true trajectory."""

    if len(true_fixes) < 2:
        raise ValueError("at least two fixes are required")
    honest = compute_bill(true_fixes, tariff, params)
    honest_fee = int(honest["total_fee_cents"])
    min_rate = min(int(tariff.rate_for_zone(zone)) for zone in tariff.cell_zones.values())
    attack_fee = 0
    for prev, curr in zip(true_fixes, true_fixes[1:]):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        if dt <= 0:
            raise ValueError("non-positive authenticated time delta")
        if dt > int(params.max_dt_sec):
            raise ValueError("authenticated time delta exceeds maximum")
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        if odo_delta < 0:
            raise ValueError("negative odometer delta")
        if odo_delta > dt * int(params.tier_vmax_mps):
            raise ValueError("odometer delta exceeds tier speed budget")
        if dt > int(params.cadence_sec):
            attack_fee += int(math.ceil(dt * int(params.tier_vmax_mps))) * tariff.max_zone_rate_cents_per_m
        else:
            attack_fee += odo_delta * min_rate
    savings = 0.0 if honest_fee <= 0 else max(0.0, (honest_fee - attack_fee) / honest_fee)
    return AdversaryResult(
        min_fee_cents=int(attack_fee),
        honest_fee_cents=honest_fee,
        savings_ratio=savings,
        claimed_fixes=list(true_fixes),
        total_distance_m=total_odometer_distance(true_fixes),
    )


def cross_check_against_circuit(
    honest_trajectories: Iterable[list[ReceiverFix]],
    tariff: TariffTable,
    params: HarnessParams,
    circuit_fee_fn: Callable[[list[ReceiverFix], TariffTable, HarnessParams], int],
) -> int:
    """Assert that the offline bill equals the circuit witness public fee.

    Run this gate on a representative honest sample before producing E1 rows.
    ``circuit_fee_fn`` is intentionally injected by the caller because witness
    generation depends on the selected settlement profile and build artifacts.
    """

    checked = 0
    for fixes in honest_trajectories:
        ours = int(compute_bill(fixes, tariff, params)["total_fee_cents"])
        circuit = int(circuit_fee_fn(fixes, tariff, params))
        if ours != circuit:
            raise AssertionError(f"fee mismatch: harness={ours} circuit={circuit}")
        checked += 1
    return checked


def e1_ablation_row(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
) -> dict[str, float]:
    """Return the single-trajectory E1 saving row under grid/circuit semantics."""

    return {
        "all_on": adversary_min_fee(true_fixes, tariff, enabled=ALL_CONSTRAINTS, params=params).savings_ratio,
        "no_odometer": adversary_min_fee(
            true_fixes,
            tariff,
            enabled=ALL_CONSTRAINTS - {Constraint.ODOMETER},
            params=params,
        ).savings_ratio,
        "no_continuity": adversary_min_fee(
            true_fixes,
            tariff,
            enabled=ALL_CONSTRAINTS - {Constraint.CONTINUITY},
            params=params,
        ).savings_ratio,
        "no_cadence": adversary_min_fee(
            true_fixes,
            tariff,
            enabled=ALL_CONSTRAINTS - {Constraint.CADENCE},
            params=params,
        ).savings_ratio,
        "no_max_dt": adversary_min_fee(
            true_fixes,
            tariff,
            enabled=ALL_CONSTRAINTS - {Constraint.MAX_DT},
            params=params,
        ).savings_ratio,
    }


def e1_forensic_rows(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    *,
    dataset: str,
    lifted_allowed_cells_by_fix: list[set[int]] | None = None,
    branch_names: set[str] | None = None,
) -> list[dict[str, str | int | float]]:
    """Return per-branch E1 forensic rows for desk-reject root-cause audits."""

    lifted_allowed_cells_by_fix = lifted_allowed_cells_by_fix or _all_cells_by_fix(true_fixes, tariff)
    branches: list[tuple[str, frozenset[Constraint], list[set[int]] | None]] = [
        ("all_on", ALL_CONSTRAINTS, None),
        ("no_odometer", ALL_CONSTRAINTS - {Constraint.ODOMETER}, None),
        ("no_zone_binding", ALL_CONSTRAINTS, None),
        ("no_continuity", ALL_CONSTRAINTS - {Constraint.CONTINUITY}, None),
        ("no_continuity_osnma_lifted", ALL_CONSTRAINTS - {Constraint.CONTINUITY}, lifted_allowed_cells_by_fix),
        ("no_cadence", ALL_CONSTRAINTS - {Constraint.CADENCE}, None),
        ("no_max_dt", ALL_CONSTRAINTS - {Constraint.MAX_DT}, None),
    ]
    if branch_names is not None:
        branches = [branch for branch in branches if branch[0] in branch_names]
    rows: list[dict[str, str | int | float]] = []
    for branch, enabled, allowed_cells_by_fix in branches:
        try:
            if branch == "no_zone_binding":
                result = zone_binding_min_fee(true_fixes, tariff, params)
            else:
                result = adversary_min_fee(
                    true_fixes,
                    tariff,
                    enabled=enabled,
                    params=params,
                    allowed_cells_by_fix=allowed_cells_by_fix,
                )
            rows.append(
                {
                    "branch": branch,
                    "dataset": str(dataset),
                    "len_claimed_fixes": len(result.claimed_fixes),
                    "savings_ratio": result.savings_ratio,
                    "skip_reason": "",
                }
            )
        except ValueError as exc:
            rows.append(
                {
                    "branch": branch,
                    "dataset": str(dataset),
                    "len_claimed_fixes": 0,
                    "savings_ratio": 0.0,
                    "skip_reason": str(exc),
                }
            )
    return rows


def _all_cells_by_fix(true_fixes: list[ReceiverFix], tariff: TariffTable) -> list[set[int]]:
    cells = set(int(cell) for cell in tariff.cell_zones)
    return [set(cells) for _ in true_fixes]


def write_e1_forensic_csv(rows: Iterable[dict[str, str | int | float]], path: Path) -> int:
    """Write E1 forensic rows with a stable schema and return row count."""

    fieldnames = [
        "branch",
        "dataset",
        "distance_bucket_m",
        "neighbor_radius_cells",
        "len_claimed_fixes",
        "savings_ratio",
        "skip_reason",
    ]
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return len(materialized)


def relay_allowed_cells_by_fix(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    radius_m: float,
    params: HarnessParams,
) -> list[set[int]]:
    """Build relay candidate sets S_i within ``radius_m`` of each true cell."""

    cells = _restricted_global_grid(true_fixes, tariff)
    allowed: list[set[int]] = []
    for fix in true_fixes:
        allowed.append(
            {
                cell
                for cell in cells
                if _cell_distance_by_idx_m(
                    tariff,
                    tariff.cell_index(fix.cell_x, fix.cell_y),
                    cell,
                    params.cell_size_m,
                )
                <= float(radius_m)
            }
        )
    return allowed


def _next_indices(i: int, n: int, cadence_enabled: bool) -> range:
    if cadence_enabled:
        return range(i + 1, min(i + 2, n))
    return range(i + 1, n)


def _reconstruct_path(
    parent: dict[tuple[int, int, int], tuple[int, int, int] | None],
    final_state: tuple[int, int, int],
) -> list[tuple[int, int, int]]:
    out: list[tuple[int, int, int]] = []
    cur: tuple[int, int, int] | None = final_state
    while cur is not None:
        out.append(cur)
        cur = parent[cur]
    out.reverse()
    return out


def _states_to_fixes(
    states: list[tuple[int, int, int]],
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
) -> list[ReceiverFix]:
    fixes: list[ReceiverFix] = []
    odo = int(true_fixes[0].odometer_reading_m)
    prev_cell: int | None = None
    for seq, (true_idx, cell, _bucket) in enumerate(states):
        x, y = _idx_to_xy(tariff, cell)
        if prev_cell is not None:
            odo += int(round(_cell_distance_by_idx_m(tariff, prev_cell, cell, params.cell_size_m)))
        base = true_fixes[true_idx]
        fixes.append(
            ReceiverFix(
                device_id=base.device_id,
                period_id=base.period_id,
                fix_seq=seq,
                auth_gnss_time=int(base.auth_gnss_time),
                cell_x=x,
                cell_y=y,
                osnma_status="authenticated",
                odometer_reading_m=int(odo),
                nonce=f"adv-{seq}-{true_idx}-{cell}",
                receiver_sig="",
            )
        )
        prev_cell = cell
    return fixes


def _restricted_global_grid(true_fixes: list[ReceiverFix], tariff: TariffTable) -> set[int]:
    """Limit global candidates to the true-path bbox plus cheapest-zone cells."""

    xs = [int(fix.cell_x) for fix in true_fixes]
    ys = [int(fix.cell_y) for fix in true_fixes]
    bbox = {
        tariff.cell_index(x, y)
        for y in range(min(ys), max(ys) + 1)
        for x in range(min(xs), max(xs) + 1)
        if tariff.cell_index(x, y) in tariff.cell_zones
    }
    min_rate = min(int(rate) for rate in tariff.zone_rates_cents_per_m.values())
    cheapest = sorted(
        int(cell)
        for cell, zone in tariff.cell_zones.items()
        if tariff.rate_for_zone(zone) == min_rate
    )
    if len(cheapest) > 64:
        stride = max(1, len(cheapest) // 64)
        cheapest = cheapest[::stride][:64]
    return bbox | set(cheapest)


def _parked_claim(
    true_fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    preserve_odometer: bool = False,
) -> list[ReceiverFix]:
    min_rate = min(int(tariff.rate_for_zone(zone)) for zone in tariff.cell_zones.values())
    cell = next(
        int(cell)
        for cell, zone in sorted(tariff.cell_zones.items())
        if tariff.rate_for_zone(zone) == min_rate
    )
    x, y = _idx_to_xy(tariff, cell)
    initial_odo = int(true_fixes[0].odometer_reading_m)
    return [
        replace(
            fix,
            cell_x=x,
            cell_y=y,
            odometer_reading_m=int(fix.odometer_reading_m) if preserve_odometer else initial_odo,
            nonce=f"park-{i}-{cell}",
            receiver_sig="",
        )
        for i, fix in enumerate(true_fixes)
    ]


def _cell_idx(tariff: TariffTable | None, x: int, y: int) -> int:
    grid_w = tariff.grid_w if tariff is not None else 100
    return int(y) * int(grid_w) + int(x)


def _idx_to_xy(tariff: TariffTable, cell: int) -> tuple[int, int]:
    return int(cell) % int(tariff.grid_w), int(cell) // int(tariff.grid_w)


def _cell_distance_by_idx_m(tariff: TariffTable, a: int, b: int, cell_size_m: int) -> float:
    ax, ay = _idx_to_xy(tariff, a)
    bx, by = _idx_to_xy(tariff, b)
    return _cell_distance_m(ax, ay, bx, by, cell_size_m)


def _cell_distance_m(ax: int, ay: int, bx: int, by: int, cell_size_m: int) -> float:
    return math.hypot(int(ax) - int(bx), int(ay) - int(by)) * int(cell_size_m)
