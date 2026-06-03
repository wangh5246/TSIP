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

from common.eval_harness import HarnessParams, e1_forensic_rows, write_e1_forensic_csv
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
    parser.add_argument("--neighbor-radius-cells", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params = HarnessParams(
        cadence_sec=args.cadence_sec,
        max_dt_sec=args.max_dt_sec,
        tier_vmax_mps=args.tier_vmax_mps,
        cell_size_m=args.cell_size_m,
        distance_bucket_m=args.cell_size_m,
    )
    rows: list[dict[str, str | int | float]] = []
    for path in args.inputs:
        dataset = _dataset_name(path)
        for record in _load_records(path, args.max_users):
            periods = _periods_from_record(record, periods_per_user=args.periods_per_user, max_dt_sec=args.max_dt_sec)
            for period_idx, fixes in enumerate(periods):
                tariff, lifted = _local_tariff_and_lifted_cells(
                    fixes,
                    radius_cells=args.neighbor_radius_cells,
                    cell_size_m=args.cell_size_m,
                )
                label = f"{dataset}:{record.get('user_id', record.get('vehicle_id', 'unknown'))}:p{period_idx}"
                period_rows = e1_forensic_rows(
                    fixes,
                    tariff,
                    params,
                    dataset=label,
                    lifted_allowed_cells_by_fix=lifted,
                )
                rows.extend(row for row in period_rows if row["branch"] != "no_max_dt")
    count = write_e1_forensic_csv(rows, args.output)
    _write_summary(rows, args.summary)
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


def _local_tariff_and_lifted_cells(
    fixes: list[ReceiverFix],
    *,
    radius_cells: int,
    cell_size_m: int,
) -> tuple[TariffTable, list[set[int]]]:
    max_x = max(int(fix.cell_x) for fix in fixes) + int(radius_cells) + 1
    grid_w = max(1, max_x + 1)
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
            fieldnames=["dataset", "branch", "n", "skip_count", "mean_savings", "median_savings", "p95_savings"],
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
    return path.stem


if __name__ == "__main__":
    raise SystemExit(main())
