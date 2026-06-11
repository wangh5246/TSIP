#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import ALL_CONSTRAINTS, HarnessParams, adversary_min_fee, check_constraints
from common.settlement import ReceiverFix, TariffTable


DEFAULT_INPUTS = [
    ROOT_DIR / "data" / "e1_mechanism_ablation" / "geolife" / "geolife_medium_identity.jsonl",
    ROOT_DIR / "experiments" / "e1_rome_real_tariff_ratio_fix" / "periods_60s.jsonl",
]
DEFAULT_OUTPUT_DIR = ROOT_DIR / "experiments" / "e3_relay_residual"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run E3 proof-consistent relay/meaconing residual sweep.")
    parser.add_argument("--inputs", nargs="+", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--granularities", default="coarse,medium,fine")
    parser.add_argument("--cadences", default="60,120,300")
    parser.add_argument("--relay-radii-m", default="0,100,200,400")
    parser.add_argument("--payload-modes", default="cell,intra_cell")
    parser.add_argument("--geolife-periods", type=int, default=14)
    parser.add_argument("--rome-periods", type=int, default=162)
    parser.add_argument("--max-dt-sec", type=int, default=600)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument("--cell-size-m", type=int, default=100)
    parser.add_argument("--distance-bucket-m", type=int, default=100)
    parser.add_argument("--min-distance-m", type=int, default=500)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--forensic-top-k",
        type=int,
        default=48,
        help="Number of highest-savings proof-consistent paths to keep in e3_forensic_paths.csv.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    granularities = _parse_str_list(args.granularities, allowed={"coarse", "medium", "fine"})
    cadences = _parse_int_list(args.cadences, option_name="--cadences", min_value=1)
    relay_radii_m = _parse_int_list(args.relay_radii_m, option_name="--relay-radii-m", min_value=0)
    payload_modes = _parse_str_list(args.payload_modes, allowed={"cell", "intra_cell"})

    records = _load_input_records(
        args.inputs,
        geolife_periods=args.geolife_periods,
        rome_periods=args.rome_periods,
        min_distance_m=args.min_distance_m,
    )
    tasks: list[dict[str, Any]] = []

    for dataset, record, fixes, base_tariff in records:
        period_id = str(record.get("period_id") or record.get("trip_id") or fixes[0].period_id)
        tariffs = {granularity: _tariff_at_granularity(base_tariff, granularity) for granularity in granularities}
        for granularity in granularities:
            tariff = tariffs[granularity]
            for cadence_sec in cadences:
                for payload_mode in payload_modes:
                    for relay_radius_m in relay_radii_m:
                        tasks.append(
                            {
                                "dataset": dataset,
                                "period_id": period_id,
                                "fixes": fixes,
                                "tariff": tariff,
                                "granularity": granularity,
                                "cadence_sec": cadence_sec,
                                "payload_mode": payload_mode,
                                "relay_radius_m": relay_radius_m,
                                "max_dt_sec": args.max_dt_sec,
                                "tier_vmax_mps": args.tier_vmax_mps,
                                "cell_size_m": args.cell_size_m,
                                "distance_bucket_m": args.distance_bucket_m,
                            }
                        )

    if int(args.workers) > 1:
        with ProcessPoolExecutor(max_workers=int(args.workers)) as pool:
            task_results = list(pool.map(_run_task, tasks))
    else:
        task_results = [_run_task(task) for task in tasks]
    period_rows = [row for row, _ in task_results]
    forensic_candidates = [row for _, row in task_results if row]

    summary_rows = _summary_rows(period_rows)
    forensic_rows = sorted(
        forensic_candidates,
        key=lambda row: (float(row["savings_ratio"]), str(row["dataset"]), str(row["period_id"])),
        reverse=True,
    )[: max(0, int(args.forensic_top_k))]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    period_path = args.output_dir / "e3_period_rows.csv"
    summary_path = args.output_dir / "tab_e3_residual_by_granularity.csv"
    forensic_path = args.output_dir / "e3_forensic_paths.csv"
    figure_path = args.output_dir / "fig_e3_relay_residual.png"
    receipt_path = args.output_dir / "receipt.json"
    _write_csv(period_rows, period_path)
    _write_csv(summary_rows, summary_path)
    _write_csv(forensic_rows, forensic_path)
    _plot_relay_residual(summary_rows, figure_path)
    receipt = {
        "experiment": "E3 proof-consistent relay/meaconing residual",
        "inputs": [str(path) for path in args.inputs],
        "periods_loaded": len(records),
        "datasets": {
            dataset: sum(1 for row in records if row[0] == dataset)
            for dataset in sorted({row[0] for row in records})
        },
        "granularities": granularities,
        "cadences_sec": cadences,
        "relay_radii_m": relay_radii_m,
        "payload_modes": payload_modes,
        "payload_mode_semantics": {
            "cell": "cell-center abstraction with one distance-bucket odometer projection tolerance",
            "intra_cell": "conservative upper bound: relay radius expanded by half-cell diagonal and payload odometer tolerance adds half a cell on top of projection tolerance",
        },
        "min_distance_m": int(args.min_distance_m),
        "distance_bucket_m": int(args.distance_bucket_m),
        "outputs": {
            "period_rows": str(period_path),
            "summary": str(summary_path),
            "forensic_paths": str(forensic_path),
            "figure": str(figure_path),
        },
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"period_rows": len(period_rows), "summary_rows": len(summary_rows), "output_dir": str(args.output_dir)}, indent=2))
    return 0


def _load_input_records(
    paths: Iterable[Path],
    *,
    geolife_periods: int,
    rome_periods: int,
    min_distance_m: int,
) -> list[tuple[str, dict[str, Any], list[ReceiverFix], TariffTable]]:
    records: list[tuple[str, dict[str, Any], list[ReceiverFix], TariffTable]] = []
    for path in paths:
        dataset = _dataset_name(path)
        limit = geolife_periods if dataset == "geolife" else rome_periods if dataset == "rome" else 0
        tariff = _load_input_tariff(path)
        emitted = 0
        for record in _load_jsonl(path):
            fixes = [ReceiverFix.from_dict(row) for row in record.get("fixes", [])]
            if len(fixes) < 2:
                continue
            if _total_distance_m(fixes) < int(min_distance_m):
                continue
            records.append((dataset, record, fixes, tariff))
            emitted += 1
            if limit > 0 and emitted >= limit:
                break
    return records


def _run_task(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    fixes = list(task["fixes"])
    tariff = task["tariff"]
    params, effective_radius_m = _params_for_payload_mode_values(
        cadence_sec=int(task["cadence_sec"]),
        payload_mode=str(task["payload_mode"]),
        relay_radius_m=int(task["relay_radius_m"]),
        max_dt_sec=int(task["max_dt_sec"]),
        tier_vmax_mps=int(task["tier_vmax_mps"]),
        cell_size_m=int(task["cell_size_m"]),
        distance_bucket_m=int(task["distance_bucket_m"]),
    )
    allowed = _relay_allowed_cells_by_fix(
        fixes,
        tariff,
        radius_m=effective_radius_m,
        cell_size_m=int(task["cell_size_m"]),
    )
    base_row = {
        "dataset": str(task["dataset"]),
        "period_id": str(task["period_id"]),
        "granularity": str(task["granularity"]),
        "cadence_sec": int(task["cadence_sec"]),
        "payload_mode": str(task["payload_mode"]),
        "relay_radius_m": int(task["relay_radius_m"]),
        "effective_radius_m": effective_radius_m,
        "distance_bucket_m": int(params.distance_bucket_m),
        "payload_odometer_tolerance_m": int(params.odometer_tolerance_m),
        "odometer_check_tolerance_m": _odometer_check_tolerance_m(params, len(fixes)),
        "n_fixes": len(fixes),
        "true_distance_m": _total_distance_m(fixes),
    }
    try:
        result = adversary_min_fee(
            fixes,
            tariff,
            enabled=ALL_CONSTRAINTS,
            params=params,
            allowed_cells_by_fix=allowed,
        )
        check_params = replace(
            params,
            odometer_tolerance_m=_odometer_check_tolerance_m(params, len(fixes)),
        )
        constraints_ok = check_constraints(
            result.claimed_fixes,
            true_fixes=fixes,
            enabled=ALL_CONSTRAINTS,
            params=check_params,
            allowed_cells_by_fix=allowed,
            tariff=tariff,
        )
        row = {
            **base_row,
            "honest_fee_cents": int(result.honest_fee_cents),
            "adversarial_min_fee_cents": int(result.min_fee_cents),
            "savings_ratio": float(result.savings_ratio),
            "claimed_distance_m": int(result.total_distance_m),
            "constraints_ok": bool(constraints_ok),
            "skip_reason": "",
        }
        forensic = None
        if result.savings_ratio > 0:
            forensic = {
                **row,
                "true_path": _path_cells(fixes, tariff),
                "claimed_path": _path_cells(result.claimed_fixes, tariff),
                "path_changed_fixes": _path_changed_count(fixes, result.claimed_fixes),
            }
        return row, forensic
    except ValueError as exc:
        return (
            {
                **base_row,
                "honest_fee_cents": "",
                "adversarial_min_fee_cents": "",
                "savings_ratio": "",
                "claimed_distance_m": "",
                "constraints_ok": False,
                "skip_reason": str(exc),
            },
            None,
        )


def _load_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            yield json.loads(line)


def _load_input_tariff(path: Path) -> TariffTable:
    candidates = [path.parent / "tariff_block.json", path.parent.parent / "tariff_block.json"]
    for candidate in candidates:
        if candidate.exists():
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            tariff = payload.get("tariff", payload)
            return TariffTable(
                tariff_version=int(tariff["tariff_version"]),
                grid_w=int(tariff["grid_w"]),
                cell_zones={int(k): int(v) for k, v in tariff["cell_zones"].items()},
                zone_rates_cents_per_m={int(k): int(v) for k, v in tariff["zone_rates_cents_per_m"].items()},
            )
    raise FileNotFoundError(f"missing tariff_block.json next to {path} or its parent")


def _tariff_at_granularity(base: TariffTable, granularity: str) -> TariffTable:
    if granularity == "fine":
        return base
    block_size = 2 if granularity == "medium" else 4
    block_cells: dict[tuple[int, int], list[int]] = {}
    for cell in base.cell_zones:
        x = int(cell) % int(base.grid_w)
        y = int(cell) // int(base.grid_w)
        block_cells.setdefault((x // block_size, y // block_size), []).append(int(cell))
    zone_rates: dict[int, int] = {}
    cell_zones: dict[int, int] = {}
    for block_id, block in enumerate(sorted(block_cells), start=1):
        cells = block_cells[block]
        rate = _median_int([base.rate_for_zone(base.zone_for_cell(cell)) for cell in cells])
        zone_id = block_id
        zone_rates[zone_id] = int(rate)
        for cell in cells:
            cell_zones[cell] = zone_id
    return TariffTable(
        tariff_version=int(base.tariff_version) * 10 + {"coarse": 1, "medium": 2}[granularity],
        grid_w=int(base.grid_w),
        cell_zones=cell_zones,
        zone_rates_cents_per_m=zone_rates,
    )


def _params_for_payload_mode(
    *,
    cadence_sec: int,
    payload_mode: str,
    relay_radius_m: int,
    args: argparse.Namespace,
) -> tuple[HarnessParams, float]:
    return _params_for_payload_mode_values(
        cadence_sec=cadence_sec,
        payload_mode=payload_mode,
        relay_radius_m=relay_radius_m,
        max_dt_sec=int(args.max_dt_sec),
        tier_vmax_mps=int(args.tier_vmax_mps),
        cell_size_m=int(args.cell_size_m),
        distance_bucket_m=int(args.distance_bucket_m),
    )


def _params_for_payload_mode_values(
    *,
    cadence_sec: int,
    payload_mode: str,
    relay_radius_m: int,
    max_dt_sec: int,
    tier_vmax_mps: int,
    cell_size_m: int,
    distance_bucket_m: int,
) -> tuple[HarnessParams, float]:
    if payload_mode == "cell":
        odometer_tolerance_m = int(distance_bucket_m)
        effective_radius_m = float(relay_radius_m)
    elif payload_mode == "intra_cell":
        odometer_tolerance_m = int(distance_bucket_m) + int(cell_size_m) // 2
        effective_radius_m = float(relay_radius_m) + (math.sqrt(2.0) * float(cell_size_m) / 2.0)
    else:
        raise ValueError(f"unknown payload mode: {payload_mode}")
    return (
        HarnessParams(
            cadence_sec=int(cadence_sec),
            max_dt_sec=int(max_dt_sec),
            tier_vmax_mps=int(tier_vmax_mps),
            cell_size_m=int(cell_size_m),
            distance_bucket_m=int(distance_bucket_m),
            odometer_tolerance_m=int(odometer_tolerance_m),
        ),
        effective_radius_m,
    )


def _relay_allowed_cells_by_fix(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    radius_m: float,
    cell_size_m: int,
) -> list[set[int]]:
    cells = _candidate_cells_near_path(fixes, tariff, radius_m=radius_m, cell_size_m=cell_size_m)
    out: list[set[int]] = []
    for fix in fixes:
        true_cell = tariff.cell_index(fix.cell_x, fix.cell_y)
        allowed = {
            cell
            for cell in cells
            if _cell_distance_by_idx_m(tariff, true_cell, cell, cell_size_m) <= float(radius_m)
        }
        if not allowed and true_cell in tariff.cell_zones:
            allowed = {true_cell}
        out.append(allowed)
    return out


def _candidate_cells_near_path(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    radius_m: float,
    cell_size_m: int,
) -> set[int]:
    radius_cells = int(math.ceil(float(radius_m) / max(1, int(cell_size_m))))
    cells: set[int] = set()
    for fix in fixes:
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                x = int(fix.cell_x) + dx
                y = int(fix.cell_y) + dy
                if x < 0 or y < 0 or x >= int(tariff.grid_w):
                    continue
                cell = tariff.cell_index(x, y)
                if cell in tariff.cell_zones:
                    cells.add(cell)
    return cells


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, int, str, int], list[float]] = {}
    skips: dict[tuple[str, str, int, str, int], int] = {}
    for row in rows:
        key = (
            str(row["dataset"]),
            str(row["granularity"]),
            int(row["cadence_sec"]),
            str(row["payload_mode"]),
            int(row["relay_radius_m"]),
        )
        if row.get("skip_reason"):
            skips[key] = skips.get(key, 0) + 1
            continue
        grouped.setdefault(key, []).append(float(row["savings_ratio"]))

    out: list[dict[str, Any]] = []
    for key in sorted(set(grouped) | set(skips)):
        values = grouped.get(key, [])
        out.append(
            {
                "dataset": key[0],
                "granularity": key[1],
                "cadence_sec": key[2],
                "payload_mode": key[3],
                "relay_radius_m": key[4],
                "n": len(values),
                "skip_count": skips.get(key, 0),
                "mean_residual": statistics.fmean(values) if values else "",
                "median_residual": statistics.median(values) if values else "",
                "p95_residual": _percentile(values, 95) if values else "",
                "max_residual": max(values) if values else "",
                "positive_share": (sum(1 for value in values if value > 0) / len(values)) if values else "",
            }
        )
    return out


def _plot_relay_residual(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    focus = [
        row
        for row in rows
        if str(row["payload_mode"]) == "intra_cell" and int(row["cadence_sec"]) == 60 and not row.get("skip_count") == row.get("n")
    ]
    if not focus:
        focus = rows
    datasets = sorted({str(row["dataset"]) for row in focus})
    granularities = ["coarse", "medium", "fine"]
    fig, axes = plt.subplots(1, len(datasets), figsize=(5.0 * len(datasets), 3.6), squeeze=False)
    for ax, dataset in zip(axes[0], datasets):
        for granularity in granularities:
            series = sorted(
                [row for row in focus if row["dataset"] == dataset and row["granularity"] == granularity],
                key=lambda row: int(row["relay_radius_m"]),
            )
            if not series:
                continue
            ax.plot(
                [int(row["relay_radius_m"]) for row in series],
                [float(row["p95_residual"] or 0.0) for row in series],
                marker="o",
                label=granularity,
            )
        ax.set_title(dataset)
        ax.set_xlabel("relay radius (m)")
        ax.set_ylabel("p95 residual savings")
        ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.25)
        ax.legend()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=200)
    plt.close(fig)


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({field for row in rows for field in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field, "")) for field in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _path_cells(fixes: list[ReceiverFix], tariff: TariffTable) -> list[int]:
    return [int(tariff.cell_index(fix.cell_x, fix.cell_y)) for fix in fixes]


def _path_changed_count(true_fixes: list[ReceiverFix], claimed_fixes: list[ReceiverFix]) -> int:
    return sum(
        1
        for true, claimed in zip(true_fixes, claimed_fixes)
        if (int(true.cell_x), int(true.cell_y)) != (int(claimed.cell_x), int(claimed.cell_y))
    )


def _total_distance_m(fixes: list[ReceiverFix]) -> int:
    return int(fixes[-1].odometer_reading_m) - int(fixes[0].odometer_reading_m)


def _odometer_check_tolerance_m(params: HarnessParams, n_fixes: int) -> int:
    n_edges = max(0, int(n_fixes) - 1)
    return int(params.odometer_tolerance_m) + n_edges * (int(params.distance_bucket_m) // 2)


def _cell_distance_by_idx_m(tariff: TariffTable, a: int, b: int, cell_size_m: int) -> float:
    ax, ay = int(a) % int(tariff.grid_w), int(a) // int(tariff.grid_w)
    bx, by = int(b) % int(tariff.grid_w), int(b) // int(tariff.grid_w)
    return math.hypot(ax - bx, ay - by) * int(cell_size_m)


def _median_int(values: list[int]) -> int:
    if not values:
        raise ValueError("median requires values")
    return int(round(statistics.median(values)))


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * float(pct) / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def _dataset_name(path: Path) -> str:
    text = str(path).lower()
    if "geolife" in text:
        return "geolife"
    if "rome" in text or "roma" in text:
        return "rome"
    if "tdrive" in text or "t-drive" in text:
        return "tdrive"
    if "porto" in text:
        return "porto"
    return path.stem


def _parse_int_list(raw: str, *, option_name: str, min_value: int) -> list[int]:
    values: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError as exc:
            raise ValueError(f"{option_name} must be a comma-separated integer list") from exc
    if not values:
        raise ValueError(f"{option_name} must contain at least one value")
    bad = [value for value in values if value < int(min_value)]
    if bad:
        raise ValueError(f"{option_name} values must be >= {min_value}: {bad}")
    return values


def _parse_str_list(raw: str, *, allowed: set[str]) -> list[str]:
    values = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not values:
        raise ValueError("list option must contain at least one value")
    bad = [value for value in values if value not in allowed]
    if bad:
        raise ValueError(f"unsupported values {bad}; allowed={sorted(allowed)}")
    return values


if __name__ == "__main__":
    raise SystemExit(main())
