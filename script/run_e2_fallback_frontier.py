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

from common.eval_experiments import bill_with_declared_outages, e2_withholding_min_fee
from common.eval_harness import HarnessParams
from common.settlement import ReceiverFix, TariffTable, fee_for_interval_values


DEFAULT_INPUTS = [
    ROOT_DIR / "data" / "e1_mechanism_ablation" / "geolife" / "geolife_medium_identity.jsonl",
    ROOT_DIR / "experiments" / "e1_rome_real_tariff_ratio_fix" / "periods_60s.jsonl",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run E2 fallback-rate Pareto frontier.")
    parser.add_argument("--inputs", nargs="+", type=Path, default=DEFAULT_INPUTS)
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "experiments" / "e2_fallback_frontier")
    parser.add_argument("--fallback-rates", default="1,2,3,4,5,6,7,8,9,10,11,12,13,14")
    parser.add_argument("--alphas", default="0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2")
    parser.add_argument("--epsilon-targets", default="0,0.01,0.05")
    parser.add_argument("--controlled-durations-sec", default="60,120,300")
    parser.add_argument("--controlled-windows-per-period", type=int, default=3)
    parser.add_argument("--geolife-periods", type=int, default=14)
    parser.add_argument("--rome-periods", type=int, default=162)
    parser.add_argument("--cadence-sec", type=int, default=60)
    parser.add_argument("--max-dt-sec", type=int, default=600)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument("--cell-size-m", type=int, default=100)
    parser.add_argument("--dwell-threshold-m", type=int, default=10)
    parser.add_argument("--moving-ratio-threshold", type=float, default=0.005)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fallback_rates = _parse_rates(args.fallback_rates)
    alphas = _parse_float_list(args.alphas, option_name="--alphas", min_value=0.0)
    epsilon_targets = _parse_float_list(args.epsilon_targets, option_name="--epsilon-targets", min_value=0.0)
    controlled_durations_sec = _parse_rates(args.controlled_durations_sec)
    params = HarnessParams(
        cadence_sec=args.cadence_sec,
        max_dt_sec=args.max_dt_sec,
        tier_vmax_mps=args.tier_vmax_mps,
        cell_size_m=args.cell_size_m,
        distance_bucket_m=args.cell_size_m,
    )
    records = []
    for path in args.inputs:
        dataset = _dataset_name(path)
        limit = args.geolife_periods if dataset == "geolife" else args.rome_periods if dataset == "rome" else 0
        tariff = _load_input_tariff(path)
        for record in _load_records(path, limit):
            fixes = [ReceiverFix.from_dict(row) for row in record["fixes"]]
            if len(fixes) < 2:
                continue
            records.append((dataset, record, fixes, tariff))
    period_rows: list[dict[str, Any]] = []
    forensic_rows: list[dict[str, Any]] = []
    for fallback_rate in fallback_rates:
        for dataset, record, fixes, tariff in records:
            period_id = str(record.get("period_id") or record.get("trip_id") or fixes[0].period_id)
            outage_edges, outage_source = _outage_edges_from_record(record, fixes, params)
            moving_outage_edges = _moving_outage_edges(
                fixes,
                outage_edges,
                params=params,
                dwell_threshold_m=args.dwell_threshold_m,
                moving_ratio_threshold=args.moving_ratio_threshold,
            )
            exact_bill = bill_with_declared_outages(
                fixes,
                tariff,
                params,
                [],
                fallback_rate_cents_per_m=fallback_rate,
            )
            honest_bill = bill_with_declared_outages(
                fixes,
                tariff,
                params,
                outage_edges,
                fallback_rate_cents_per_m=fallback_rate,
            )
            moving_honest_bill = bill_with_declared_outages(
                fixes,
                tariff,
                params,
                moving_outage_edges,
                fallback_rate_cents_per_m=fallback_rate,
            )
            outage_motion = _outage_motion(fixes, params, outage_edges, dwell_threshold_m=args.dwell_threshold_m)
            moving_outage_motion = _outage_motion(
                fixes,
                params,
                moving_outage_edges,
                dwell_threshold_m=args.dwell_threshold_m,
            )
            attack = e2_withholding_min_fee(
                fixes,
                tariff,
                params,
                fallback_rate_cents_per_m=fallback_rate,
            )
            exact_fee = max(1, int(exact_bill["total_fee_cents"]))
            penalty = "" if not outage_edges else (int(honest_bill["total_fee_cents"]) - exact_fee) / exact_fee
            moving_penalty = (
                ""
                if not moving_outage_edges
                else (int(moving_honest_bill["total_fee_cents"]) - exact_fee) / exact_fee
            )
            period_rows.append(
                {
                    "dataset": dataset,
                    "period_id": period_id,
                    "fallback_rate_cents_per_m": fallback_rate,
                    "max_zone_rate_cents_per_m": tariff.max_zone_rate_cents_per_m,
                    "ge_max_zone_rate": fallback_rate >= tariff.max_zone_rate_cents_per_m,
                    "exact_fee_cents": int(exact_bill["total_fee_cents"]),
                    "honest_paid_fee_cents": int(honest_bill["total_fee_cents"]),
                    "moving_honest_paid_fee_cents": int(moving_honest_bill["total_fee_cents"]),
                    "strategic_min_fee_cents": int(attack["strategic_min_fee_cents"]),
                    "honest_penalty": penalty,
                    "honest_penalty_moving_only": moving_penalty,
                    "withholding_gain": float(attack["withholding_gain"]),
                    "n_intervals": len(fixes) - 1,
                    "n_honest_outage_intervals": len(outage_edges),
                    "n_moving_honest_outage_intervals": len(moving_outage_edges),
                    "n_strategic_declared_intervals": int(attack["declared_outage_intervals"]),
                    "honest_outage_source": outage_source,
                    "honest_outage_actual_distance_m": outage_motion["actual_distance_m"],
                    "honest_outage_charged_distance_m": outage_motion["charged_distance_m"],
                    "honest_outage_movement_ratio": outage_motion["movement_ratio"],
                    "honest_outage_dwell_edge_share": outage_motion["dwell_edge_share"],
                    "moving_outage_actual_distance_m": moving_outage_motion["actual_distance_m"],
                    "moving_outage_charged_distance_m": moving_outage_motion["charged_distance_m"],
                    "moving_outage_movement_ratio": moving_outage_motion["movement_ratio"],
                    "moving_outage_dwell_edge_share": moving_outage_motion["dwell_edge_share"],
                    "speed_bound_ok": bool(honest_bill["speed_bound_ok"]) and bool(attack["speed_bound_ok"]),
                    "honest_min_speed_bound_slack_m": honest_bill["min_speed_bound_slack_m"],
                    "strategic_min_speed_bound_slack_m": attack["min_speed_bound_slack_m"],
                }
            )
            forensic_rows.extend(_forensic_edges(dataset, period_id, fixes, tariff, params, fallback_rate, outage_edges, attack))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    combined_frontier_rows = _frontier_rows(period_rows, penalty_scope="all_outages")
    dataset_summary_rows = _dataset_summary_rows(period_rows, penalty_scope="all_outages")
    moving_combined_frontier_rows = _frontier_rows(
        period_rows,
        penalty_scope="moving_only",
        penalty_key="honest_penalty_moving_only",
        movement_ratio_key="moving_outage_movement_ratio",
        dwell_share_key="moving_outage_dwell_edge_share",
    )
    moving_dataset_summary_rows = _dataset_summary_rows(
        period_rows,
        penalty_scope="moving_only",
        penalty_key="honest_penalty_moving_only",
        movement_ratio_key="moving_outage_movement_ratio",
        dwell_share_key="moving_outage_dwell_edge_share",
    )
    _write_csv(period_rows, args.output_dir / "period_rows.csv")
    _write_csv(forensic_rows, args.output_dir / "forensic_edges.csv")
    _write_csv(dataset_summary_rows, args.output_dir / "frontier.csv")
    _write_csv(combined_frontier_rows, args.output_dir / "frontier_combined.csv")
    _write_csv(dataset_summary_rows, args.output_dir / "frontier_by_dataset.csv")
    _write_csv(dataset_summary_rows, args.output_dir / "summary_by_dataset.csv")
    _write_csv(moving_dataset_summary_rows, args.output_dir / "frontier_moving_by_dataset.csv")
    _write_csv(moving_combined_frontier_rows, args.output_dir / "frontier_moving_combined.csv")
    _write_csv(moving_dataset_summary_rows, args.output_dir / "summary_moving_by_dataset.csv")
    figure_path = args.output_dir / "fig_e2_fallback_frontier.png"
    moving_figure_path = args.output_dir / "fig_e2_fallback_frontier_moving.png"
    _plot_frontier_by_dataset(dataset_summary_rows, figure_path)
    _plot_frontier_by_dataset(moving_dataset_summary_rows, moving_figure_path)
    interval_rows = _break_even_interval_rows(records, params, dwell_threshold_m=args.dwell_threshold_m)
    alpha_period_rows = _alpha_period_rows(
        records,
        params,
        alphas,
        dwell_threshold_m=args.dwell_threshold_m,
        moving_ratio_threshold=args.moving_ratio_threshold,
    )
    controlled_rows = _controlled_outage_rows(
        records,
        params,
        alphas,
        controlled_durations_sec,
        dwell_threshold_m=args.dwell_threshold_m,
        moving_ratio_threshold=args.moving_ratio_threshold,
        max_windows_per_period=args.controlled_windows_per_period,
    )
    alpha_frontier_rows = _alpha_frontier_rows(alpha_period_rows)
    controlled_frontier_rows = _controlled_frontier_rows(controlled_rows, alpha_period_rows)
    outage_diagnostic_rows = _outage_diagnostic_rows(
        records,
        params,
        controlled_rows,
        dwell_threshold_m=args.dwell_threshold_m,
        moving_ratio_threshold=args.moving_ratio_threshold,
    )
    threshold_rows = _incentive_threshold_rows(
        alpha_frontier_rows,
        controlled_frontier_rows,
        epsilon_targets,
    )
    break_even_figure_path = args.output_dir / "fig_e2_break_even_cdf.png"
    alpha_figure_path = args.output_dir / "fig_e2_pareto_alpha.png"
    _write_csv(interval_rows, args.output_dir / "break_even_intervals.csv")
    _write_csv(alpha_period_rows, args.output_dir / "alpha_period_rows.csv")
    _write_csv(alpha_frontier_rows, args.output_dir / "alpha_frontier_by_dataset.csv")
    _write_csv(controlled_rows, args.output_dir / "controlled_outage_rows.csv")
    _write_csv(controlled_frontier_rows, args.output_dir / "controlled_frontier_by_dataset.csv")
    _write_csv(threshold_rows, args.output_dir / "tab_e2_incentive_thresholds.csv")
    _write_csv(outage_diagnostic_rows, args.output_dir / "tab_e2_outage_diagnostic.csv")
    _plot_break_even_cdf(interval_rows, break_even_figure_path)
    _plot_alpha_pareto(controlled_frontier_rows, alpha_figure_path, controlled_duration_sec=120)
    receipt = {
        "inputs": [str(path) for path in args.inputs],
        "fallback_rates_cents_per_m": fallback_rates,
        "alphas": alphas,
        "epsilon_targets": epsilon_targets,
        "controlled_durations_sec": controlled_durations_sec,
        "periods_loaded": len(records),
        "datasets": dict(sorted((dataset, sum(1 for item in records if item[0] == dataset)) for dataset in {r[0] for r in records})),
        "outputs": {
            "break_even_intervals": str(args.output_dir / "break_even_intervals.csv"),
            "alpha_period_rows": str(args.output_dir / "alpha_period_rows.csv"),
            "alpha_frontier_by_dataset": str(args.output_dir / "alpha_frontier_by_dataset.csv"),
            "controlled_outage_rows": str(args.output_dir / "controlled_outage_rows.csv"),
            "controlled_frontier_by_dataset": str(args.output_dir / "controlled_frontier_by_dataset.csv"),
            "tab_e2_incentive_thresholds": str(args.output_dir / "tab_e2_incentive_thresholds.csv"),
            "tab_e2_outage_diagnostic": str(args.output_dir / "tab_e2_outage_diagnostic.csv"),
            "break_even_figure": str(break_even_figure_path),
            "alpha_pareto_figure": str(alpha_figure_path),
            "frontier_by_dataset": str(args.output_dir / "frontier_by_dataset.csv"),
            "frontier_combined": str(args.output_dir / "frontier_combined.csv"),
            "frontier_moving_by_dataset": str(args.output_dir / "frontier_moving_by_dataset.csv"),
            "frontier_moving_combined": str(args.output_dir / "frontier_moving_combined.csv"),
            "summary_by_dataset": str(args.output_dir / "summary_by_dataset.csv"),
            "summary_moving_by_dataset": str(args.output_dir / "summary_moving_by_dataset.csv"),
            "period_rows": str(args.output_dir / "period_rows.csv"),
            "forensic_edges": str(args.output_dir / "forensic_edges.csv"),
            "figure": str(figure_path),
            "moving_figure": str(moving_figure_path),
        },
    }
    (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


def _load_records(path: Path, limit: int) -> Iterable[dict[str, Any]]:
    emitted = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            yield json.loads(line)
            emitted += 1
            if limit > 0 and emitted >= limit:
                return


def _load_input_tariff(path: Path) -> TariffTable:
    for candidate in [path.parent / "tariff_block.json", path.parent.parent / "tariff_block.json"]:
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
    raise FileNotFoundError(f"missing tariff_block.json for {path}")


def _outage_edges_from_record(
    record: dict[str, Any],
    fixes: list[ReceiverFix],
    params: HarnessParams,
) -> tuple[list[int], str]:
    raw_fixes = list(record.get("fixes", []))
    explicit: list[int] = []
    for idx in range(len(fixes) - 1):
        curr = raw_fixes[idx + 1] if idx + 1 < len(raw_fixes) else {}
        if bool(curr.get("outage_candidate") or curr.get("native_outage_candidate")):
            explicit.append(idx)
    if explicit:
        return explicit, "explicit_fix_flag"
    native = [
        idx
        for idx, (prev, curr) in enumerate(zip(fixes, fixes[1:]))
        if int(curr.auth_gnss_time) - int(prev.auth_gnss_time) > int(params.cadence_sec)
    ]
    expected = int(record.get("n_outage_intervals") or 0)
    if expected > 0 and len(native) == expected:
        return native, "derived_from_native_gap_count"
    if native:
        return native, "derived_from_native_gap"
    return [], "none"


def _forensic_edges(
    dataset: str,
    period_id: str,
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    fallback_rate: int,
    honest_outage_edges: list[int],
    attack: dict,
) -> list[dict[str, Any]]:
    honest_set = set(honest_outage_edges)
    strategic_set = {int(edge) for edge in attack["declared_outage_edges"]}
    rows: list[dict[str, Any]] = []
    for edge_idx, (prev, curr) in enumerate(zip(fixes, fixes[1:])):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        cell_idx = tariff.cell_index(prev.cell_x, prev.cell_y)
        exact = fee_for_interval_values(
            dt_sec=dt,
            odo_delta_m=odo_delta,
            cell_idx=cell_idx,
            tariff=tariff,
            cadence_sec=int(params.cadence_sec),
            tier_vmax_mps=int(params.tier_vmax_mps),
            max_dt_sec=int(params.max_dt_sec),
            fallback_override=False,
        )
        fallback = fee_for_interval_values(
            dt_sec=dt,
            odo_delta_m=odo_delta,
            cell_idx=cell_idx,
            tariff=tariff,
            cadence_sec=int(params.cadence_sec),
            tier_vmax_mps=int(params.tier_vmax_mps),
            max_dt_sec=int(params.max_dt_sec),
            fallback_rate_cents_per_m=fallback_rate,
            fallback_override=True,
        )
        rows.append(
            {
                "dataset": dataset,
                "period_id": period_id,
                "edge_idx": edge_idx,
                "fallback_rate_cents_per_m": fallback_rate,
                "dt_sec": dt,
                "odo_delta_m": odo_delta,
                "cell_idx": cell_idx,
                "zone_id": int(exact["zone_id"]),
                "zone_rate_cents_per_m": int(exact["zone_rate_cents_per_m"]),
                "exact_fee_cents": int(exact["fee_cents"]),
                "fallback_fee_cents": int(fallback["fee_cents"]),
                "fallback_charged_distance_m": int(fallback["charged_distance_m"]),
                "speed_bound_slack_m": int(fallback["charged_distance_m"]) - odo_delta,
                "honest_outage": edge_idx in honest_set,
                "strategic_declared_outage": edge_idx in strategic_set,
            }
        )
    return rows


def _outage_motion(
    fixes: list[ReceiverFix],
    params: HarnessParams,
    outage_edges: list[int],
    *,
    dwell_threshold_m: int,
) -> dict[str, Any]:
    if not outage_edges:
        return {
            "actual_distance_m": "",
            "charged_distance_m": "",
            "movement_ratio": "",
            "dwell_edge_share": "",
        }
    actual_distance = 0
    charged_distance = 0
    dwell_edges = 0
    for edge_idx in outage_edges:
        prev = fixes[edge_idx]
        curr = fixes[edge_idx + 1]
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        actual_distance += odo_delta
        charged_distance += int(math.ceil(dt * int(params.tier_vmax_mps)))
        if odo_delta <= int(dwell_threshold_m):
            dwell_edges += 1
    return {
        "actual_distance_m": int(actual_distance),
        "charged_distance_m": int(charged_distance),
        "movement_ratio": 0.0 if charged_distance <= 0 else actual_distance / charged_distance,
        "dwell_edge_share": dwell_edges / len(outage_edges),
    }


def _moving_outage_edges(
    fixes: list[ReceiverFix],
    outage_edges: list[int],
    *,
    params: HarnessParams,
    dwell_threshold_m: int,
    moving_ratio_threshold: float,
) -> list[int]:
    moving: list[int] = []
    for edge_idx in outage_edges:
        idx = int(edge_idx)
        prev = fixes[idx]
        curr = fixes[idx + 1]
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        fallback_distance = int(math.ceil(dt * int(params.tier_vmax_mps)))
        movement_ratio = 0.0 if fallback_distance <= 0 else odo_delta / fallback_distance
        if odo_delta > int(dwell_threshold_m) or movement_ratio > float(moving_ratio_threshold):
            moving.append(idx)
    return moving


def _break_even_interval_rows(
    records: list[tuple[str, dict[str, Any], list[ReceiverFix], TariffTable]],
    params: HarnessParams,
    *,
    dwell_threshold_m: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dataset, record, fixes, tariff in records:
        period_id = _period_id(record, fixes)
        rows.extend(
            _interval_value_rows(
                dataset,
                period_id,
                fixes,
                tariff,
                params,
                dwell_threshold_m=dwell_threshold_m,
            )
        )
    return rows


def _alpha_period_rows(
    records: list[tuple[str, dict[str, Any], list[ReceiverFix], TariffTable]],
    params: HarnessParams,
    alphas: list[float],
    *,
    dwell_threshold_m: int,
    moving_ratio_threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dataset, record, fixes, tariff in records:
        period_id = _period_id(record, fixes)
        interval_rows = _interval_value_rows(
            dataset,
            period_id,
            fixes,
            tariff,
            params,
            dwell_threshold_m=dwell_threshold_m,
        )
        exact_period_fee = sum(float(row["exact_fee_cents"]) for row in interval_rows)
        outage_edges, outage_source = _outage_edges_from_record(record, fixes, params)
        moving_outage_edges = _moving_outage_edges(
            fixes,
            outage_edges,
            params=params,
            dwell_threshold_m=dwell_threshold_m,
            moving_ratio_threshold=moving_ratio_threshold,
        )
        outage_motion = _outage_motion(fixes, params, outage_edges, dwell_threshold_m=dwell_threshold_m)
        moving_motion = _outage_motion(fixes, params, moving_outage_edges, dwell_threshold_m=dwell_threshold_m)
        max_rate = float(tariff.max_zone_rate_cents_per_m)
        for alpha in alphas:
            fallback_rate = float(alpha) * max_rate
            strategic_min_fee = 0.0
            declared_edges = 0
            all_delta = 0.0
            moving_delta = 0.0
            outage_set = set(outage_edges)
            moving_set = set(moving_outage_edges)
            speed_bound_ok = True
            for interval in interval_rows:
                edge_idx = int(interval["edge_idx"])
                exact_fee = float(interval["exact_fee_cents"])
                fallback_fee = float(interval["fallback_distance_m"]) * fallback_rate
                strategic_min_fee += min(exact_fee, fallback_fee)
                if fallback_fee < exact_fee:
                    declared_edges += 1
                if edge_idx in outage_set:
                    all_delta += fallback_fee - exact_fee
                if edge_idx in moving_set:
                    moving_delta += fallback_fee - exact_fee
                speed_bound_ok = speed_bound_ok and bool(interval["speed_bound_ok"])
            gain = 0.0 if exact_period_fee <= 0 else max(0.0, (exact_period_fee - strategic_min_fee) / exact_period_fee)
            rows.append(
                {
                    "dataset": dataset,
                    "period_id": period_id,
                    "alpha": float(alpha),
                    "fallback_rate_cents_per_m": fallback_rate,
                    "max_zone_rate_cents_per_m": max_rate,
                    "exact_fee_cents": exact_period_fee,
                    "strategic_min_fee_cents": strategic_min_fee,
                    "withholding_gain": gain,
                    "declared_outage_intervals": declared_edges,
                    "honest_penalty_all_outage": ""
                    if not outage_edges or exact_period_fee <= 0
                    else all_delta / exact_period_fee,
                    "honest_penalty_moving_outage": ""
                    if not moving_outage_edges or exact_period_fee <= 0
                    else moving_delta / exact_period_fee,
                    "n_intervals": len(interval_rows),
                    "n_all_outage_edges": len(outage_edges),
                    "n_moving_outage_edges": len(moving_outage_edges),
                    "honest_outage_source": outage_source,
                    "all_outage_movement_ratio": outage_motion["movement_ratio"],
                    "all_outage_dwell_edge_share": outage_motion["dwell_edge_share"],
                    "moving_outage_movement_ratio": moving_motion["movement_ratio"],
                    "moving_outage_dwell_edge_share": moving_motion["dwell_edge_share"],
                    "speed_bound_ok": speed_bound_ok,
                }
            )
    return rows


def _controlled_outage_rows(
    records: list[tuple[str, dict[str, Any], list[ReceiverFix], TariffTable]],
    params: HarnessParams,
    alphas: list[float],
    controlled_durations_sec: list[int],
    *,
    dwell_threshold_m: int,
    moving_ratio_threshold: float,
    max_windows_per_period: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dataset, record, fixes, tariff in records:
        period_id = _period_id(record, fixes)
        interval_rows = _interval_value_rows(
            dataset,
            period_id,
            fixes,
            tariff,
            params,
            dwell_threshold_m=dwell_threshold_m,
        )
        exact_period_fee = sum(float(row["exact_fee_cents"]) for row in interval_rows)
        max_rate = float(tariff.max_zone_rate_cents_per_m)
        for duration_sec in controlled_durations_sec:
            windows = _controlled_windows(
                interval_rows,
                target_duration_sec=int(duration_sec),
                dwell_threshold_m=int(dwell_threshold_m),
                moving_ratio_threshold=float(moving_ratio_threshold),
                max_windows_per_period=int(max_windows_per_period),
            )
            for alpha in alphas:
                fallback_rate = float(alpha) * max_rate
                for window_id, window in enumerate(windows):
                    exact_window_fee = float(window["exact_window_fee_cents"])
                    fallback_window_fee = float(window["fallback_distance_m"]) * fallback_rate
                    period_penalty = (
                        ""
                        if exact_period_fee <= 0
                        else (fallback_window_fee - exact_window_fee) / exact_period_fee
                    )
                    window_penalty = (
                        ""
                        if exact_window_fee <= 0
                        else (fallback_window_fee - exact_window_fee) / exact_window_fee
                    )
                    rows.append(
                        {
                            "dataset": dataset,
                            "period_id": period_id,
                            "controlled_duration_sec": int(duration_sec),
                            "window_id": int(window_id),
                            "start_edge": int(window["start_edge"]),
                            "end_edge": int(window["end_edge"]),
                            "alpha": float(alpha),
                            "fallback_rate_cents_per_m": fallback_rate,
                            "max_zone_rate_cents_per_m": max_rate,
                            "exact_period_fee_cents": exact_period_fee,
                            "exact_window_fee_cents": exact_window_fee,
                            "fallback_window_fee_cents": fallback_window_fee,
                            "honest_penalty_controlled_period": period_penalty,
                            "honest_penalty_controlled_window": window_penalty,
                            "actual_distance_m": float(window["actual_distance_m"]),
                            "fallback_distance_m": float(window["fallback_distance_m"]),
                            "duration_sec": float(window["duration_sec"]),
                            "movement_ratio": float(window["movement_ratio"]),
                            "dwell_edge_share": float(window["dwell_edge_share"]),
                            "n_edges": int(window["n_edges"]),
                            "speed_bound_ok": bool(window["speed_bound_ok"]),
                        }
                    )
    return rows


def _alpha_frontier_rows(alpha_period_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    keys = sorted({(str(row["dataset"]), float(row["alpha"])) for row in alpha_period_rows})
    for dataset, alpha in keys:
        group = [row for row in alpha_period_rows if str(row["dataset"]) == dataset and float(row["alpha"]) == alpha]
        rows.extend(
            [
                _frontier_row_for_scope(
                    dataset,
                    alpha,
                    group,
                    penalty_scope="all_outage",
                    penalty_key="honest_penalty_all_outage",
                ),
                _frontier_row_for_scope(
                    dataset,
                    alpha,
                    group,
                    penalty_scope="moving_outage",
                    penalty_key="honest_penalty_moving_outage",
                ),
            ]
        )
    return rows


def _controlled_frontier_rows(
    controlled_rows: list[dict[str, Any]],
    alpha_period_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gain_by_key: dict[tuple[str, float], dict[str, Any]] = {}
    for dataset, alpha in sorted({(str(row["dataset"]), float(row["alpha"])) for row in alpha_period_rows}):
        group = [row for row in alpha_period_rows if str(row["dataset"]) == dataset and float(row["alpha"]) == alpha]
        gains = [float(row["withholding_gain"]) for row in group]
        gain_by_key[(dataset, alpha)] = {
            "n_periods": len(group),
            "withholding_gain_mean": _mean_or_blank(gains),
            "withholding_gain_median": _median_or_blank(gains),
            "withholding_gain_p95": _percentile_or_blank(gains, 95),
        }
    rows: list[dict[str, Any]] = []
    keys = sorted(
        {
            (str(row["dataset"]), int(row["controlled_duration_sec"]), float(row["alpha"]))
            for row in controlled_rows
        }
    )
    for dataset, duration_sec, alpha in keys:
        group = [
            row
            for row in controlled_rows
            if str(row["dataset"]) == dataset
            and int(row["controlled_duration_sec"]) == duration_sec
            and float(row["alpha"]) == alpha
        ]
        penalties = [
            float(row["honest_penalty_controlled_period"])
            for row in group
            if row["honest_penalty_controlled_period"] != ""
        ]
        fallback_rates = [float(row["fallback_rate_cents_per_m"]) for row in group]
        max_rates = [float(row["max_zone_rate_cents_per_m"]) for row in group]
        gain_summary = gain_by_key.get((dataset, alpha), {})
        rows.append(
            {
                "dataset": dataset,
                "penalty_scope": f"controlled_{duration_sec}s",
                "controlled_duration_sec": duration_sec,
                "alpha": alpha,
                "fallback_rate_cents_per_m": _mean_or_blank(fallback_rates),
                "max_zone_rate_cents_per_m": max(max_rates) if max_rates else "",
                "n_periods": gain_summary.get("n_periods", ""),
                "n_penalty_observations": len(penalties),
                "honest_penalty_median": _median_or_blank(penalties),
                "honest_penalty_p95": _percentile_or_blank(penalties, 95),
                "withholding_gain_mean": gain_summary.get("withholding_gain_mean", ""),
                "withholding_gain_median": gain_summary.get("withholding_gain_median", ""),
                "withholding_gain_p95": gain_summary.get("withholding_gain_p95", ""),
            }
        )
    return rows


def _outage_diagnostic_rows(
    records: list[tuple[str, dict[str, Any], list[ReceiverFix], TariffTable]],
    params: HarnessParams,
    controlled_rows: list[dict[str, Any]],
    *,
    dwell_threshold_m: int,
    moving_ratio_threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    datasets = sorted({dataset for dataset, _, _, _ in records})
    for dataset in datasets:
        dataset_records = [item for item in records if item[0] == dataset]
        all_edge_rows: list[dict[str, Any]] = []
        moving_edge_rows: list[dict[str, Any]] = []
        periods_with_all = set()
        periods_with_moving = set()
        for _, record, fixes, tariff in dataset_records:
            period_id = _period_id(record, fixes)
            outage_edges, _ = _outage_edges_from_record(record, fixes, params)
            moving_edges = _moving_outage_edges(
                fixes,
                outage_edges,
                params=params,
                dwell_threshold_m=dwell_threshold_m,
                moving_ratio_threshold=moving_ratio_threshold,
            )
            interval_rows = _interval_value_rows(
                dataset,
                period_id,
                fixes,
                tariff,
                params,
                dwell_threshold_m=dwell_threshold_m,
            )
            by_edge = {int(row["edge_idx"]): row for row in interval_rows}
            for edge_idx in outage_edges:
                edge = by_edge[int(edge_idx)]
                all_edge_rows.append(edge)
                periods_with_all.add(period_id)
            for edge_idx in moving_edges:
                edge = by_edge[int(edge_idx)]
                moving_edge_rows.append(edge)
                periods_with_moving.add(period_id)
        rows.append(
            _diagnostic_row(
                dataset=dataset,
                penalty_scope="all_outage",
                n_periods=len(dataset_records),
                n_periods_with_scope=len(periods_with_all),
                edge_rows=all_edge_rows,
                dwell_threshold_m=dwell_threshold_m,
            )
        )
        rows.append(
            _diagnostic_row(
                dataset=dataset,
                penalty_scope="moving_outage",
                n_periods=len(dataset_records),
                n_periods_with_scope=len(periods_with_moving),
                edge_rows=moving_edge_rows,
                dwell_threshold_m=dwell_threshold_m,
            )
        )
    controlled_unique: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for row in controlled_rows:
        key = (
            str(row["dataset"]),
            str(row["period_id"]),
            int(row["controlled_duration_sec"]),
            int(row["window_id"]),
        )
        controlled_unique[key] = row
    for dataset, duration_sec in sorted({(key[0], key[2]) for key in controlled_unique}):
        windows = [
            row
            for key, row in controlled_unique.items()
            if key[0] == dataset and key[2] == duration_sec
        ]
        actual_distances = [float(row["actual_distance_m"]) for row in windows]
        fallback_distances = [float(row["fallback_distance_m"]) for row in windows]
        movement_ratios = [float(row["movement_ratio"]) for row in windows]
        dwell_shares = [float(row["dwell_edge_share"]) for row in windows]
        rows.append(
            {
                "dataset": dataset,
                "penalty_scope": f"controlled_{duration_sec}s",
                "controlled_duration_sec": duration_sec,
                "n_periods": sum(1 for item in records if item[0] == dataset),
                "n_periods_with_scope": len({str(row["period_id"]) for row in windows}),
                "n_edges_or_windows": len(windows),
                "actual_distance_m": sum(actual_distances),
                "fallback_distance_m": sum(fallback_distances),
                "movement_ratio_mean": _mean_or_blank(movement_ratios),
                "movement_ratio_median": _median_or_blank(movement_ratios),
                "dwell_edge_share_mean": _mean_or_blank(dwell_shares),
                "speed_bound_ok": all(float(row["fallback_distance_m"]) >= float(row["actual_distance_m"]) for row in windows),
            }
        )
    return rows


def _incentive_threshold_rows(
    alpha_frontier_rows: list[dict[str, Any]],
    controlled_frontier_rows: list[dict[str, Any]],
    epsilon_targets: list[float],
) -> list[dict[str, Any]]:
    frontier = alpha_frontier_rows + controlled_frontier_rows
    out: list[dict[str, Any]] = []
    keys = sorted({(str(row["dataset"]), str(row["penalty_scope"])) for row in frontier})
    for dataset, penalty_scope in keys:
        scope_rows = [row for row in frontier if str(row["dataset"]) == dataset and str(row["penalty_scope"]) == penalty_scope]
        usable = [
            row
            for row in scope_rows
            if row.get("withholding_gain_p95", "") != "" and int(row.get("n_penalty_observations") or 0) > 0
        ]
        for epsilon in epsilon_targets:
            candidates = [
                row
                for row in usable
                if float(row["withholding_gain_p95"]) <= float(epsilon) + 1e-12
            ]
            if not candidates:
                reason = "no_penalty_observations" if not usable else "no_alpha_meets_target"
                out.append(
                    {
                        "dataset": dataset,
                        "penalty_scope": penalty_scope,
                        "target_gain_epsilon": float(epsilon),
                        "min_alpha": "",
                        "fallback_rate_cents_per_m": "",
                        "max_zone_rate_cents_per_m": "",
                        "n_periods": "",
                        "n_penalty_observations": "",
                        "withholding_gain_p95": "",
                        "honest_penalty_median": "",
                        "honest_penalty_p95": "",
                        "skip_reason": reason,
                    }
                )
                continue
            selected = min(candidates, key=lambda row: float(row["alpha"]))
            out.append(
                {
                    "dataset": dataset,
                    "penalty_scope": penalty_scope,
                    "target_gain_epsilon": float(epsilon),
                    "min_alpha": float(selected["alpha"]),
                    "fallback_rate_cents_per_m": selected.get("fallback_rate_cents_per_m", ""),
                    "max_zone_rate_cents_per_m": selected.get("max_zone_rate_cents_per_m", ""),
                    "n_periods": selected.get("n_periods", ""),
                    "n_penalty_observations": selected.get("n_penalty_observations", ""),
                    "withholding_gain_p95": selected.get("withholding_gain_p95", ""),
                    "honest_penalty_median": selected.get("honest_penalty_median", ""),
                    "honest_penalty_p95": selected.get("honest_penalty_p95", ""),
                    "skip_reason": "",
                }
            )
    return out


def _interval_value_rows(
    dataset: str,
    period_id: str,
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    params: HarnessParams,
    *,
    dwell_threshold_m: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    max_rate = float(tariff.max_zone_rate_cents_per_m)
    for edge_idx, (prev, curr) in enumerate(zip(fixes, fixes[1:])):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        cell_idx = tariff.cell_index(prev.cell_x, prev.cell_y)
        exact = fee_for_interval_values(
            dt_sec=dt,
            odo_delta_m=odo_delta,
            cell_idx=cell_idx,
            tariff=tariff,
            cadence_sec=int(params.cadence_sec),
            tier_vmax_mps=int(params.tier_vmax_mps),
            max_dt_sec=int(params.max_dt_sec),
            fallback_override=False,
        )
        fallback_unit = fee_for_interval_values(
            dt_sec=dt,
            odo_delta_m=odo_delta,
            cell_idx=cell_idx,
            tariff=tariff,
            cadence_sec=int(params.cadence_sec),
            tier_vmax_mps=int(params.tier_vmax_mps),
            max_dt_sec=int(params.max_dt_sec),
            fallback_rate_cents_per_m=1,
            fallback_override=True,
        )
        fallback_distance = float(fallback_unit["charged_distance_m"])
        exact_fee = float(exact["fee_cents"])
        break_even_rate = "" if fallback_distance <= 0 else exact_fee / fallback_distance
        break_even_alpha = "" if break_even_rate == "" or max_rate <= 0 else float(break_even_rate) / max_rate
        movement_ratio = "" if fallback_distance <= 0 else odo_delta / fallback_distance
        rows.append(
            {
                "dataset": dataset,
                "period_id": period_id,
                "edge_idx": edge_idx,
                "dt_sec": dt,
                "odo_delta_m": odo_delta,
                "cell_idx": cell_idx,
                "zone_id": int(exact["zone_id"]),
                "zone_rate_cents_per_m": int(exact["zone_rate_cents_per_m"]),
                "exact_fee_cents": exact_fee,
                "fallback_distance_m": fallback_distance,
                "max_zone_rate_cents_per_m": max_rate,
                "break_even_rate_cents_per_m": break_even_rate,
                "break_even_alpha": break_even_alpha,
                "movement_ratio": movement_ratio,
                "dwell_edge": odo_delta <= int(dwell_threshold_m),
                "speed_bound_slack_m": fallback_distance - odo_delta,
                "speed_bound_ok": fallback_distance >= odo_delta,
            }
        )
    return rows


def _controlled_windows(
    interval_rows: list[dict[str, Any]],
    *,
    target_duration_sec: int,
    dwell_threshold_m: int,
    moving_ratio_threshold: float,
    max_windows_per_period: int,
) -> list[dict[str, Any]]:
    if max_windows_per_period <= 0:
        return []
    tolerance = max(30.0, float(target_duration_sec) * 0.35)
    candidates: list[dict[str, Any]] = []
    for start in range(len(interval_rows)):
        duration = 0.0
        actual_distance = 0.0
        fallback_distance = 0.0
        exact_fee = 0.0
        dwell_edges = 0
        speed_bound_ok = True
        for end in range(start, len(interval_rows)):
            row = interval_rows[end]
            duration += float(row["dt_sec"])
            actual_distance += float(row["odo_delta_m"])
            fallback_distance += float(row["fallback_distance_m"])
            exact_fee += float(row["exact_fee_cents"])
            dwell_edges += 1 if bool(row["dwell_edge"]) else 0
            speed_bound_ok = speed_bound_ok and bool(row["speed_bound_ok"])
            if duration < float(target_duration_sec) - tolerance:
                continue
            if duration > float(target_duration_sec) + tolerance:
                break
            movement_ratio = 0.0 if fallback_distance <= 0 else actual_distance / fallback_distance
            is_moving = actual_distance > float(dwell_threshold_m) or movement_ratio > float(moving_ratio_threshold)
            if not is_moving:
                continue
            candidates.append(
                {
                    "start_edge": int(interval_rows[start]["edge_idx"]),
                    "end_edge": int(row["edge_idx"]),
                    "duration_sec": duration,
                    "actual_distance_m": actual_distance,
                    "fallback_distance_m": fallback_distance,
                    "exact_window_fee_cents": exact_fee,
                    "movement_ratio": movement_ratio,
                    "dwell_edge_share": dwell_edges / (end - start + 1),
                    "n_edges": end - start + 1,
                    "speed_bound_ok": speed_bound_ok,
                    "_target_error": abs(duration - float(target_duration_sec)),
                }
            )
    candidates.sort(key=lambda row: (float(row["_target_error"]), -float(row["actual_distance_m"]), int(row["start_edge"])))
    selected: list[dict[str, Any]] = []
    used_edges: set[int] = set()
    for candidate in candidates:
        edges = set(range(int(candidate["start_edge"]), int(candidate["end_edge"]) + 1))
        if edges & used_edges:
            continue
        used_edges.update(edges)
        selected.append({key: value for key, value in candidate.items() if not key.startswith("_")})
        if len(selected) >= int(max_windows_per_period):
            break
    selected.sort(key=lambda row: int(row["start_edge"]))
    return selected


def _frontier_row_for_scope(
    dataset: str,
    alpha: float,
    group: list[dict[str, Any]],
    *,
    penalty_scope: str,
    penalty_key: str,
) -> dict[str, Any]:
    penalties = [float(row[penalty_key]) for row in group if row[penalty_key] != ""]
    gains = [float(row["withholding_gain"]) for row in group]
    fallback_rates = [float(row["fallback_rate_cents_per_m"]) for row in group]
    max_rates = [float(row["max_zone_rate_cents_per_m"]) for row in group]
    return {
        "dataset": dataset,
        "penalty_scope": penalty_scope,
        "controlled_duration_sec": "",
        "alpha": alpha,
        "fallback_rate_cents_per_m": _mean_or_blank(fallback_rates),
        "max_zone_rate_cents_per_m": max(max_rates) if max_rates else "",
        "n_periods": len(group),
        "n_penalty_observations": len(penalties),
        "honest_penalty_median": _median_or_blank(penalties),
        "honest_penalty_p95": _percentile_or_blank(penalties, 95),
        "withholding_gain_mean": _mean_or_blank(gains),
        "withholding_gain_median": _median_or_blank(gains),
        "withholding_gain_p95": _percentile_or_blank(gains, 95),
    }


def _diagnostic_row(
    *,
    dataset: str,
    penalty_scope: str,
    n_periods: int,
    n_periods_with_scope: int,
    edge_rows: list[dict[str, Any]],
    dwell_threshold_m: int,
) -> dict[str, Any]:
    actual_distances = [float(row["odo_delta_m"]) for row in edge_rows]
    fallback_distances = [float(row["fallback_distance_m"]) for row in edge_rows]
    movement_ratios = [
        float(row["movement_ratio"])
        for row in edge_rows
        if row["movement_ratio"] != ""
    ]
    dwell_edges = sum(1 for row in edge_rows if float(row["odo_delta_m"]) <= int(dwell_threshold_m))
    return {
        "dataset": dataset,
        "penalty_scope": penalty_scope,
        "controlled_duration_sec": "",
        "n_periods": int(n_periods),
        "n_periods_with_scope": int(n_periods_with_scope),
        "n_edges_or_windows": len(edge_rows),
        "actual_distance_m": sum(actual_distances),
        "fallback_distance_m": sum(fallback_distances),
        "movement_ratio_mean": _mean_or_blank(movement_ratios),
        "movement_ratio_median": _median_or_blank(movement_ratios),
        "dwell_edge_share_mean": "" if not edge_rows else dwell_edges / len(edge_rows),
        "speed_bound_ok": all(float(row["fallback_distance_m"]) >= float(row["odo_delta_m"]) for row in edge_rows),
    }


def _frontier_rows(
    period_rows: list[dict[str, Any]],
    *,
    penalty_scope: str,
    penalty_key: str = "honest_penalty",
    movement_ratio_key: str = "honest_outage_movement_ratio",
    dwell_share_key: str = "honest_outage_dwell_edge_share",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fallback_rate in sorted({int(row["fallback_rate_cents_per_m"]) for row in period_rows}):
        rows = [row for row in period_rows if int(row["fallback_rate_cents_per_m"]) == fallback_rate]
        penalties = [float(row[penalty_key]) for row in rows if row[penalty_key] != ""]
        gains = [float(row["withholding_gain"]) for row in rows]
        exact_fees = [float(row["exact_fee_cents"]) for row in rows]
        movement_ratios = [float(row[movement_ratio_key]) for row in rows if row[movement_ratio_key] != ""]
        dwell_shares = [float(row[dwell_share_key]) for row in rows if row[dwell_share_key] != ""]
        out.append(
            {
                "penalty_scope": penalty_scope,
                "fallback_rate_cents_per_m": fallback_rate,
                "n_periods": len(rows),
                "n_honest_outage_periods": len(penalties),
                "min_exact_fee_cents": min(exact_fees) if exact_fees else "",
                "p05_exact_fee_cents": _percentile_or_blank(exact_fees, 5),
                "median_exact_fee_cents": _median_or_blank(exact_fees),
                "honest_penalty_mean": _mean_or_blank(penalties),
                "honest_penalty_median": _median_or_blank(penalties),
                "honest_penalty_p95": _percentile_or_blank(penalties, 95),
                "withholding_gain_mean": _mean_or_blank(gains),
                "withholding_gain_median": _median_or_blank(gains),
                "withholding_gain_p95": _percentile_or_blank(gains, 95),
                "honest_outage_movement_ratio_median": _median_or_blank(movement_ratios),
                "honest_outage_dwell_edge_share_mean": _mean_or_blank(dwell_shares),
                "all_speed_bounds_ok": all(bool(row["speed_bound_ok"]) for row in rows),
            }
        )
    return out


def _dataset_summary_rows(
    period_rows: list[dict[str, Any]],
    *,
    penalty_scope: str,
    penalty_key: str = "honest_penalty",
    movement_ratio_key: str = "honest_outage_movement_ratio",
    dwell_share_key: str = "honest_outage_dwell_edge_share",
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    keys = sorted({(str(row["dataset"]), int(row["fallback_rate_cents_per_m"])) for row in period_rows})
    for dataset, fallback_rate in keys:
        rows = [
            row
            for row in period_rows
            if str(row["dataset"]) == dataset and int(row["fallback_rate_cents_per_m"]) == fallback_rate
        ]
        penalties = [float(row[penalty_key]) for row in rows if row[penalty_key] != ""]
        gains = [float(row["withholding_gain"]) for row in rows]
        exact_fees = [float(row["exact_fee_cents"]) for row in rows]
        movement_ratios = [float(row[movement_ratio_key]) for row in rows if row[movement_ratio_key] != ""]
        dwell_shares = [float(row[dwell_share_key]) for row in rows if row[dwell_share_key] != ""]
        out.append(
            {
                "penalty_scope": penalty_scope,
                "dataset": dataset,
                "fallback_rate_cents_per_m": fallback_rate,
                "n_periods": len(rows),
                "n_honest_outage_periods": len(penalties),
                "max_zone_rate_cents_per_m": max(int(row["max_zone_rate_cents_per_m"]) for row in rows),
                "ge_dataset_max_zone_rate": fallback_rate >= max(int(row["max_zone_rate_cents_per_m"]) for row in rows),
                "min_exact_fee_cents": min(exact_fees) if exact_fees else "",
                "p05_exact_fee_cents": _percentile_or_blank(exact_fees, 5),
                "median_exact_fee_cents": _median_or_blank(exact_fees),
                "honest_penalty_mean": _mean_or_blank(penalties),
                "honest_penalty_median": _median_or_blank(penalties),
                "honest_penalty_p95": _percentile_or_blank(penalties, 95),
                "withholding_gain_mean": _mean_or_blank(gains),
                "withholding_gain_median": _median_or_blank(gains),
                "withholding_gain_p95": _percentile_or_blank(gains, 95),
                "honest_outage_movement_ratio_median": _median_or_blank(movement_ratios),
                "honest_outage_dwell_edge_share_mean": _mean_or_blank(dwell_shares),
                "all_speed_bounds_ok": all(bool(row["speed_bound_ok"]) for row in rows),
            }
        )
    return out


def _plot_frontier_by_dataset(rows: list[dict[str, Any]], output: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    plotted = False
    for dataset in sorted({str(row["dataset"]) for row in rows}):
        dataset_rows = [row for row in rows if str(row["dataset"]) == dataset and row["honest_penalty_mean"] != ""]
        if not dataset_rows:
            continue
        xs = [float(row["honest_penalty_mean"]) for row in dataset_rows]
        ys = [float(row["withholding_gain_mean"]) for row in dataset_rows]
        labels = [int(row["fallback_rate_cents_per_m"]) for row in dataset_rows]
        ax.plot(xs, ys, marker="o", linewidth=1.8, label=dataset)
        for x, y, label in zip(xs, ys, labels):
            ax.annotate(str(label), (x, y), textcoords="offset points", xytext=(5, 4), fontsize=8)
        zero = next((row for row in dataset_rows if float(row["withholding_gain_mean"]) <= 1e-12), None)
        if zero:
            ax.scatter([float(zero["honest_penalty_mean"])], [0.0], s=50, zorder=3)
            ax.annotate(
                f"{dataset} gain=0 @ {zero['fallback_rate_cents_per_m']}",
                (float(zero["honest_penalty_mean"]), 0.0),
                textcoords="offset points",
                xytext=(8, 12),
                fontsize=8,
            )
        plotted = True
    ax.set_xlabel("Honest fallback penalty (mean)")
    ax.set_ylabel("Withholding gain (mean)")
    if plotted:
        ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def _plot_break_even_cdf(rows: list[dict[str, Any]], output: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    plotted = False
    for dataset in sorted({str(row["dataset"]) for row in rows}):
        values = sorted(
            float(row["break_even_alpha"])
            for row in rows
            if str(row["dataset"]) == dataset and row["break_even_alpha"] != ""
        )
        if not values:
            continue
        ys = [(idx + 1) / len(values) for idx in range(len(values))]
        ax.step(values, ys, where="post", linewidth=1.9, label=dataset)
        p95 = _percentile_or_blank(values, 95)
        if p95 != "":
            ax.scatter([float(p95)], [0.95], s=24)
            ax.annotate(
                f"p95={float(p95):.2f}",
                (float(p95), 0.95),
                textcoords="offset points",
                xytext=(6, -12),
                fontsize=8,
            )
        plotted = True
    ax.axvline(1.0, color="black", linestyle="--", linewidth=1.0, alpha=0.65)
    ax.set_xlabel("Break-even fallback rate alpha")
    ax.set_ylabel("Empirical CDF of intervals")
    ax.set_xlim(left=0.0)
    ax.set_ylim(0.0, 1.02)
    if plotted:
        ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def _plot_alpha_pareto(
    rows: list[dict[str, Any]],
    output: Path,
    *,
    controlled_duration_sec: int,
) -> None:
    import matplotlib.pyplot as plt

    target_scope = f"controlled_{int(controlled_duration_sec)}s"
    datasets = [
        dataset
        for dataset in sorted({str(row["dataset"]) for row in rows})
        if any(str(row["dataset"]) == dataset and str(row["penalty_scope"]) == target_scope for row in rows)
    ]
    if not datasets:
        fig, ax = plt.subplots(figsize=(6.2, 4.2))
        ax.set_xlabel(f"Honest penalty median, controlled {int(controlled_duration_sec)}s")
        ax.set_ylabel("Withholding gain p95")
        fig.tight_layout()
        fig.savefig(output, dpi=200)
        plt.close(fig)
        return
    fig, axes = plt.subplots(1, len(datasets), figsize=(5.2 * len(datasets), 4.0), sharey=True)
    if len(datasets) == 1:
        axes = [axes]
    key_alphas = {0.1, 0.3, 0.6, 1.0, 1.2}
    for ax, dataset in zip(axes, datasets):
        dataset_rows = [
            row
            for row in rows
            if str(row["dataset"]) == dataset
            and str(row["penalty_scope"]) == target_scope
            and row["honest_penalty_median"] != ""
            and row["withholding_gain_p95"] != ""
        ]
        if not dataset_rows:
            continue
        dataset_rows.sort(key=lambda row: float(row["alpha"]))
        xs = [float(row["honest_penalty_median"]) for row in dataset_rows]
        ys = [float(row["withholding_gain_p95"]) for row in dataset_rows]
        labels = [float(row["alpha"]) for row in dataset_rows]
        ax.plot(xs, ys, marker="o", linewidth=1.8, label=dataset)
        for x, y, alpha in zip(xs, ys, labels):
            if round(alpha, 1) not in key_alphas:
                continue
            ax.annotate(f"{alpha:.1f}", (x, y), textcoords="offset points", xytext=(5, 4), fontsize=8)
        corner = next((row for row in dataset_rows if float(row["withholding_gain_p95"]) <= 1e-12), None)
        if corner:
            ax.scatter([float(corner["honest_penalty_median"])], [0.0], s=52, zorder=3)
            ax.annotate(
                f"zero @ {float(corner['alpha']):.1f}",
                (float(corner["honest_penalty_median"]), 0.0),
                textcoords="offset points",
                xytext=(6, 12),
                fontsize=8,
            )
        ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.55)
        ax.set_title(dataset)
        ax.set_xlabel(f"Honest penalty median, controlled {int(controlled_duration_sec)}s")
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("Withholding gain p95")
    fig.tight_layout()
    fig.savefig(output, dpi=200)
    plt.close(fig)


def _write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _parse_rates(raw: str) -> list[int]:
    values = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
    if not values:
        raise ValueError("--fallback-rates must contain at least one integer")
    if any(value < 0 for value in values):
        raise ValueError("--fallback-rates must be non-negative")
    return values


def _parse_float_list(raw: str, *, option_name: str, min_value: float | None = None) -> list[float]:
    values = [float(part.strip()) for part in str(raw).split(",") if part.strip()]
    if not values:
        raise ValueError(f"{option_name} must contain at least one number")
    if min_value is not None and any(value < float(min_value) for value in values):
        raise ValueError(f"{option_name} values must be >= {min_value}")
    return values


def _dataset_name(path: Path) -> str:
    text = str(path).lower()
    if "geolife" in text:
        return "geolife"
    if "rome" in text or "roma" in text:
        return "rome"
    if "porto" in text:
        return "porto"
    if "tdrive" in text or "t-drive" in text:
        return "tdrive"
    return path.stem


def _period_id(record: dict[str, Any], fixes: list[ReceiverFix]) -> str:
    return str(record.get("period_id") or record.get("trip_id") or fixes[0].period_id)


def _mean_or_blank(values: list[float]) -> float | str:
    return statistics.fmean(values) if values else ""


def _median_or_blank(values: list[float]) -> float | str:
    return statistics.median(values) if values else ""


def _percentile_or_blank(values: list[float], pct: float) -> float | str:
    if not values:
        return ""
    ordered = sorted(values)
    rank = (len(ordered) - 1) * float(pct) / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


if __name__ == "__main__":
    raise SystemExit(main())
