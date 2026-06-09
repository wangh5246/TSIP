#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import (
    ALL_CONSTRAINTS,
    AdversaryResult,
    Constraint,
    HarnessParams,
    adversary_min_fee,
    check_constraints,
    compute_bill,
    e1_forensic_rows,
    write_e1_forensic_csv,
)
from common.settlement import ReceiverFix, TariffTable


N_FIXES = 25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run E1 forensic solver rows on cleaned TSIP-ready trajectories.")
    parser.add_argument(
        "--inputs",
        nargs="+",
        type=Path,
        default=[
            ROOT_DIR / "experiments" / "geolife_tsip_ready_50u.jsonl",
            ROOT_DIR / "experiments" / "tdrive_tsip_ready_50u.jsonl",
        ],
    )
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "experiments" / "e1_forensic_rows.csv")
    parser.add_argument("--summary", type=Path, default=ROOT_DIR / "experiments" / "e1_forensic_summary.csv")
    parser.add_argument("--max-users", type=int, default=50)
    parser.add_argument("--periods-per-user", type=int, default=1)
    parser.add_argument("--cadence-sec", type=int, default=60)
    parser.add_argument("--max-dt-sec", type=int, default=600)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument("--cell-size-m", type=int, default=100)
    parser.add_argument("--distance-bucket-m", type=int, default=None)
    parser.add_argument("--neighbor-radius-cells", type=int, default=2)
    parser.add_argument("--audit-output", type=Path, default=None)
    parser.add_argument("--audit-top-k", type=int, default=3)
    parser.add_argument("--branches", default=None, help="Comma-separated branch filter; default runs all branches.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params = HarnessParams(
        cadence_sec=args.cadence_sec,
        max_dt_sec=args.max_dt_sec,
        tier_vmax_mps=args.tier_vmax_mps,
        cell_size_m=args.cell_size_m,
        distance_bucket_m=args.distance_bucket_m or args.cell_size_m,
    )
    branch_names = _parse_branches(args.branches)
    rows: list[dict[str, str | int | float]] = []
    audit_rows: list[dict[str, Any]] = []
    for path in args.inputs:
        dataset = _dataset_name(path)
        input_tariff = _load_input_tariff(path)
        for record in _load_records(path, args.max_users):
            periods = _periods_from_record(record, periods_per_user=args.periods_per_user, max_dt_sec=args.max_dt_sec)
            for period_idx, fixes in enumerate(periods):
                if input_tariff is not None:
                    tariff = input_tariff
                    lifted = _lifted_cells_from_tariff(
                        fixes,
                        tariff,
                        radius_cells=args.neighbor_radius_cells,
                        cell_size_m=args.cell_size_m,
                    )
                else:
                    tariff, lifted = _record_tariff_and_lifted_cells(
                        record,
                        fixes,
                        radius_cells=args.neighbor_radius_cells,
                        cell_size_m=args.cell_size_m,
                    )
                label = _period_label(dataset, record, period_idx)
                period_rows = e1_forensic_rows(
                    fixes,
                    tariff,
                    params,
                    dataset=label,
                    lifted_allowed_cells_by_fix=lifted,
                    branch_names=branch_names,
                )
                rows.extend(row for row in period_rows if row["branch"] != "no_max_dt")
                if args.audit_output is not None:
                    audit_rows.extend(_audit_continuity_pair(label, fixes, tariff, params, lifted))
    count = write_e1_forensic_csv(rows, args.output)
    _write_summary(rows, args.summary)
    if args.audit_output is not None:
        _write_audit(audit_rows, args.audit_output, top_k=args.audit_top_k)
    print(json.dumps({"rows": count, "output": str(args.output), "summary": str(args.summary)}, indent=2))
    return 0


def _load_records(path: Path, max_users: int) -> Iterable[dict[str, Any]]:
    emitted = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            yield json.loads(line)
            emitted += 1
            if max_users > 0 and emitted >= max_users:
                return


def _periods_from_record(record: dict[str, Any], *, periods_per_user: int, max_dt_sec: int) -> list[list[ReceiverFix]]:
    if "fixes" in record:
        fixes = [ReceiverFix.from_dict(row) for row in record["fixes"]]
        periods: list[list[ReceiverFix]] = []
        current: list[ReceiverFix] = []
        for fix in fixes:
            if current:
                dt = int(fix.auth_gnss_time) - int(current[-1].auth_gnss_time)
                if dt <= 0 or dt > int(max_dt_sec):
                    current = []
            current.append(fix)
            if len(current) == N_FIXES:
                periods.append(list(current))
                if periods_per_user > 0 and len(periods) >= periods_per_user:
                    return periods
                current = current[-1:]
        return periods
    windows = sorted(record.get("windows", []), key=lambda row: int(row["timestamp"]))
    periods: list[list[ReceiverFix]] = []
    current: list[dict[str, Any]] = []
    for window in windows:
        if current:
            dt = int(window["timestamp"]) - int(current[-1]["timestamp"])
            if dt <= 0 or dt > int(max_dt_sec):
                current = []
        current.append(window)
        if len(current) == N_FIXES:
            periods.append(_fixes_from_windows(record, current))
            if periods_per_user > 0 and len(periods) >= periods_per_user:
                return periods
            current = current[-1:]
    return periods


def _fixes_from_windows(record: dict[str, Any], windows: list[dict[str, Any]]) -> list[ReceiverFix]:
    fixes: list[ReceiverFix] = []
    odo = 0.0
    prev: dict[str, Any] | None = None
    period_id = f"{record.get('user_id', record.get('vehicle_id', 'u'))}:{int(windows[0]['timestamp'])}"
    for seq, window in enumerate(windows):
        if prev is not None:
            odo += math.hypot(float(window["x_m"]) - float(prev["x_m"]), float(window["y_m"]) - float(prev["y_m"]))
        fixes.append(
            ReceiverFix(
                device_id=str(record.get("user_id", record.get("vehicle_id", "u"))),
                period_id=period_id,
                fix_seq=seq,
                auth_gnss_time=int(window["timestamp"]),
                cell_x=int(window["cell_x"]),
                cell_y=int(window["cell_y"]),
                osnma_status="authenticated",
                odometer_reading_m=int(round(odo)),
                nonce=f"{period_id}:{seq}",
                receiver_sig="",
            )
        )
        prev = window
    return fixes


def _record_tariff_and_lifted_cells(
    record: dict[str, Any],
    fixes: list[ReceiverFix],
    *,
    radius_cells: int,
    cell_size_m: int,
) -> tuple[TariffTable, list[set[int]]]:
    grid_w = max(1, int(record.get("grid_w") or 100))
    candidate_cells: set[int] = set()
    lifted: list[set[int]] = []
    for fix in fixes:
        allowed: set[int] = set()
        for dy in range(-int(radius_cells), int(radius_cells) + 1):
            for dx in range(-int(radius_cells), int(radius_cells) + 1):
                x = int(fix.cell_x) + dx
                y = int(fix.cell_y) + dy
                if x < 0 or y < 0:
                    continue
                if x >= grid_w or y >= grid_w:
                    continue
                if math.hypot(dx, dy) * int(cell_size_m) > int(radius_cells) * int(cell_size_m):
                    continue
                cell = y * grid_w + x
                allowed.add(cell)
                candidate_cells.add(cell)
        lifted.append(allowed)
    cell_zones = {cell: _zone_for_cell(cell, grid_w) for cell in candidate_cells}
    return (
        TariffTable(
            tariff_version=101,
            grid_w=grid_w,
            cell_zones=cell_zones,
            zone_rates_cents_per_m={10: 1, 20: 5},
        ),
        lifted,
    )


def _lifted_cells_from_tariff(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    radius_cells: int,
    cell_size_m: int,
) -> list[set[int]]:
    lifted: list[set[int]] = []
    for fix in fixes:
        allowed: set[int] = set()
        for dy in range(-int(radius_cells), int(radius_cells) + 1):
            for dx in range(-int(radius_cells), int(radius_cells) + 1):
                x = int(fix.cell_x) + dx
                y = int(fix.cell_y) + dy
                if x < 0 or y < 0:
                    continue
                if math.hypot(dx, dy) * int(cell_size_m) > int(radius_cells) * int(cell_size_m):
                    continue
                cell = tariff.cell_index(x, y)
                if cell in tariff.cell_zones:
                    allowed.add(cell)
        lifted.append(allowed)
    return lifted


def _load_input_tariff(path: Path) -> TariffTable:
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    candidates = [
        path.parent / "tariff_block.json",
        path.parent.parent / "tariff_block.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        tariff = payload.get("tariff", payload)
        return TariffTable(
            tariff_version=int(tariff["tariff_version"]),
            grid_w=int(tariff["grid_w"]),
            cell_zones={int(k): int(v) for k, v in tariff["cell_zones"].items()},
            zone_rates_cents_per_m={int(k): int(v) for k, v in tariff["zone_rates_cents_per_m"].items()},
        )
    raise FileNotFoundError(
        "missing tariff_block.json next to input or its parent; refusing to use a synthetic checkerboard tariff"
    )


def _zone_for_cell(cell: int, grid_w: int) -> int:
    x = int(cell) % int(grid_w)
    y = int(cell) // int(grid_w)
    return 20 if ((x // 3) + (y // 3)) % 2 else 10


def _write_summary(rows: list[dict[str, str | int | float]], path: Path) -> None:
    grouped: dict[tuple[str, str], list[float]] = {}
    skip_counts: dict[tuple[str, str], int] = {}
    for row in rows:
        dataset = str(row["dataset"]).split(":", 1)[0]
        branch = str(row["branch"])
        key = (dataset, branch)
        if row.get("skip_reason"):
            skip_counts[key] = skip_counts.get(key, 0) + 1
            continue
        grouped.setdefault(key, []).append(float(row["savings_ratio"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "dataset",
                "branch",
                "n",
                "skip_count",
                "min_savings",
                "mean_savings",
                "median_savings",
                "p95_savings",
            ],
        )
        writer.writeheader()
        for key in sorted(set(grouped) | set(skip_counts)):
            values = grouped.get(key, [])
            writer.writerow(
                {
                    "dataset": key[0],
                    "branch": key[1],
                    "n": len(values),
                    "skip_count": skip_counts.get(key, 0),
                    "min_savings": min(values) if values else "",
                    "mean_savings": statistics.fmean(values) if values else "",
                    "median_savings": statistics.median(values) if values else "",
                    "p95_savings": _percentile(values, 95) if values else "",
                }
            )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((float(pct) / 100) * len(ordered)) - 1))
    return ordered[idx]


def _dataset_name(path: Path) -> str:
    name = path.name.lower()
    if "geolife" in name:
        return "geolife"
    if "tdrive" in name or "t-drive" in name:
        return "tdrive"
    if "porto" in name:
        return "porto"
    if "rome" in name or "roma" in name:
        return "rome"
    return path.stem


def _parse_branches(raw: str | None) -> set[str] | None:
    if raw is None or not str(raw).strip():
        return None
    return {part.strip() for part in str(raw).split(",") if part.strip()}


def _period_label(dataset: str, record: dict[str, Any], period_idx: int) -> str:
    if record.get("period_id"):
        return str(record["period_id"])
    subject = record.get("user_id", record.get("vehicle_id", record.get("device_id", "unknown")))
    trip = record.get("trip_id")
    if trip:
        return f"{dataset}:{subject}:{trip}:p{period_idx}"
    return f"{dataset}:{subject}:p{period_idx}"


def _audit_continuity_pair(
    label: str,
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    lifted_allowed_cells_by_fix: list[set[int]],
) -> list[dict[str, Any]]:
    lifted_attack: AdversaryResult | None = None
    lifted_error = ""
    try:
        lifted_attack = adversary_min_fee(
            fixes,
            tariff,
            enabled=ALL_CONSTRAINTS - {Constraint.CONTINUITY},
            params=params,
            allowed_cells_by_fix=lifted_allowed_cells_by_fix,
        )
    except ValueError as exc:
        lifted_error = str(exc)
    branches = [
        ("no_continuity", ALL_CONSTRAINTS - {Constraint.CONTINUITY}, None),
        ("no_continuity_osnma_lifted", ALL_CONSTRAINTS - {Constraint.CONTINUITY}, lifted_allowed_cells_by_fix),
    ]
    out: list[dict[str, Any]] = []
    for branch, enabled, allowed in branches:
        try:
            result = adversary_min_fee(
                fixes,
                tariff,
                enabled=enabled,
                params=params,
                allowed_cells_by_fix=allowed,
            )
            honest_bill = compute_bill(fixes, tariff, params)
            attack_bill = compute_bill(result.claimed_fixes, tariff, params)
            replay_claim = lifted_attack.claimed_fixes if branch == "no_continuity" and lifted_attack else result.claimed_fixes
            passed = check_constraints(
                replay_claim,
                true_fixes=fixes,
                enabled=enabled,
                params=params,
                allowed_cells_by_fix=allowed,
                tariff=tariff,
            )
            violations = _constraint_violations(
                replay_claim,
                true_fixes=fixes,
                enabled=enabled,
                params=params,
                allowed_cells_by_fix=allowed,
                tariff=tariff,
            )
            out.append(
                {
                    "dataset": label,
                    "branch": branch,
                    "honest_fee_cents": int(honest_bill["total_fee_cents"]),
                    "attack_fee_cents": int(attack_bill["total_fee_cents"]),
                    "savings_ratio": float(result.savings_ratio),
                    "replayed_attack_source": (
                        "no_continuity_osnma_lifted" if branch == "no_continuity" and lifted_attack else branch
                    ),
                    "chk.passed": bool(passed),
                    "chk.violations": violations,
                    "receipt_savings_ratio": 0.0 if branch == "no_continuity" and not passed else float(result.savings_ratio),
                    "lifted_attack_error": lifted_error,
                    "honest_distance_m": int(honest_bill["total_distance_m"]),
                    "attack_distance_m": int(attack_bill["total_distance_m"]),
                    "honest_private_zone_distance_m": honest_bill["private_zone_distance_m"],
                    "attack_private_zone_distance_m": attack_bill["private_zone_distance_m"],
                    "honest_edges": _edge_audit(fixes, tariff, params),
                    "attack_edges": _edge_audit(result.claimed_fixes, tariff, params),
                }
            )
        except ValueError as exc:
            out.append({"dataset": label, "branch": branch, "skip_reason": str(exc)})
    return out


def _constraint_violations(
    claimed_fixes: list[ReceiverFix],
    *,
    true_fixes: list[ReceiverFix],
    enabled: Iterable[Constraint],
    params: HarnessParams,
    allowed_cells_by_fix: list[set[int]] | None,
    tariff: TariffTable,
) -> list[dict[str, Any]]:
    enabled_set = {Constraint(c) for c in enabled}
    violations: list[dict[str, Any]] = []
    if len(claimed_fixes) < 2:
        violations.append({"constraint": "shape", "reason": "fewer than two fixes"})
        return violations
    if Constraint.ODOMETER in enabled_set:
        claimed_distance = int(claimed_fixes[-1].odometer_reading_m) - int(claimed_fixes[0].odometer_reading_m)
        true_distance = int(true_fixes[-1].odometer_reading_m) - int(true_fixes[0].odometer_reading_m)
        delta = abs(claimed_distance - true_distance)
        if delta > int(params.odometer_tolerance_m):
            violations.append(
                {
                    "constraint": "odometer",
                    "delta_m": int(delta),
                    "tolerance_m": int(params.odometer_tolerance_m),
                }
            )
    for idx, (prev, curr) in enumerate(zip(claimed_fixes, claimed_fixes[1:])):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        if dt <= 0:
            violations.append({"constraint": "time", "edge": idx, "dt_sec": int(dt)})
            continue
        if Constraint.MAX_DT in enabled_set and dt > int(params.max_dt_sec):
            violations.append(
                {"constraint": "max_dt", "edge": idx, "dt_sec": int(dt), "max_dt_sec": int(params.max_dt_sec)}
            )
        if Constraint.CONTINUITY in enabled_set:
            dist_m = math.hypot(int(curr.cell_x) - int(prev.cell_x), int(curr.cell_y) - int(prev.cell_y)) * int(
                params.cell_size_m
            )
            cap_m = int(params.tier_vmax_mps) * dt
            if dist_m > cap_m:
                violations.append(
                    {
                        "constraint": "continuity",
                        "edge": idx,
                        "dist_m": float(dist_m),
                        "cap_m": int(cap_m),
                    }
                )
    if Constraint.OSNMA in enabled_set:
        if allowed_cells_by_fix is not None:
            if len(allowed_cells_by_fix) != len(claimed_fixes):
                violations.append(
                    {
                        "constraint": "osnma",
                        "reason": "allowed_cells length mismatch",
                        "allowed_len": len(allowed_cells_by_fix),
                        "claimed_len": len(claimed_fixes),
                    }
                )
            else:
                for idx, (fix, allowed) in enumerate(zip(claimed_fixes, allowed_cells_by_fix)):
                    cell = tariff.cell_index(fix.cell_x, fix.cell_y)
                    if cell not in allowed:
                        violations.append({"constraint": "osnma", "fix": idx, "cell": int(cell), "reason": "outside allowed set"})
        else:
            if len(claimed_fixes) != len(true_fixes):
                violations.append(
                    {
                        "constraint": "osnma",
                        "reason": "pinned fix count mismatch",
                        "claimed_len": len(claimed_fixes),
                        "true_len": len(true_fixes),
                    }
                )
            for idx, (claimed, true) in enumerate(zip(claimed_fixes, true_fixes)):
                if (int(claimed.cell_x), int(claimed.cell_y)) != (int(true.cell_x), int(true.cell_y)):
                    violations.append(
                        {
                            "constraint": "osnma",
                            "fix": idx,
                            "claimed_cell": int(tariff.cell_index(claimed.cell_x, claimed.cell_y)),
                            "true_cell": int(tariff.cell_index(true.cell_x, true.cell_y)),
                            "reason": "pinned cell mismatch",
                        }
                    )
    return violations


def _edge_audit(fixes: list[ReceiverFix], tariff: TariffTable, params: HarnessParams) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for prev, curr in zip(fixes, fixes[1:]):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        cell_idx = tariff.cell_index(prev.cell_x, prev.cell_y)
        zone_id = tariff.zone_for_cell(cell_idx)
        zone_rate = tariff.rate_for_zone(zone_id)
        fallback = dt > int(params.cadence_sec)
        charged_distance = int(math.ceil(dt * int(params.tier_vmax_mps))) if fallback else odo_delta
        fee = charged_distance * (tariff.max_zone_rate_cents_per_m if fallback else zone_rate)
        edges.append(
            {
                "prev_seq": int(prev.fix_seq),
                "curr_seq": int(curr.fix_seq),
                "prev_cell": int(cell_idx),
                "prev_x": int(prev.cell_x),
                "prev_y": int(prev.cell_y),
                "curr_x": int(curr.cell_x),
                "curr_y": int(curr.cell_y),
                "dt_sec": int(dt),
                "odo_delta_m": int(odo_delta),
                "zone_id": int(zone_id),
                "rate_cents_per_m": int(zone_rate),
                "fallback": bool(fallback),
                "charged_distance_m": int(charged_distance),
                "fee_cents": int(fee),
            }
        )
    return edges


def _write_audit(rows: list[dict[str, Any]], path: Path, *, top_k: int) -> None:
    complete = [row for row in rows if not row.get("skip_reason")]
    top = sorted(
        (row for row in complete if row["branch"] == "no_continuity_osnma_lifted"),
        key=lambda row: (float(row["savings_ratio"]), int(row["honest_fee_cents"])),
        reverse=True,
    )[: max(0, int(top_k))]
    payload = {
        "rows": rows,
        "top_lifted_savings": top,
        "savings_dotplot": [
            {
                "dataset": row["dataset"],
                "branch": row["branch"],
                "honest_fee_cents": row.get("honest_fee_cents"),
                "attack_fee_cents": row.get("attack_fee_cents"),
                "savings_ratio": row.get("savings_ratio"),
            }
            for row in complete
            if row["branch"] in {"no_continuity", "no_continuity_osnma_lifted"}
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
