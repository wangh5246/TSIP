#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.trajectory_preprocess import (  # noqa: E402
    IdentityMatcher,
    MatchedPoint,
    RawPoint,
    haversine_m,
    iter_geolife_driving_trips,
    iter_porto_trips,
    iter_tdrive_trips,
    resample_matched_points,
)


@dataclass(frozen=True)
class Interval:
    dataset: str
    trip_id: str
    cadence_sec: int
    dt_sec: int
    odo_delta_m: float
    dist_m: float
    ratio: float
    odo_speed_mps: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit whether per-interval GPS-polyline distance can be tightly bound to endpoint geometric distance."
    )
    parser.add_argument("--dataset", choices=["tdrive", "geolife", "porto", "all"], default="all")
    parser.add_argument("--cadence-sec", nargs="+", type=int, default=[60, 300])
    parser.add_argument("--gap-sec", type=int, default=120)
    parser.add_argument("--max-trips", type=int, default=5000, help="Per-dataset scan cap; use 0 for all trips.")
    parser.add_argument("--tier-vmax-mps", type=float, default=33.0)
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "experiments" / "geometric_binding_audit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if any(cadence <= 0 for cadence in args.cadence_sec):
        raise SystemExit("cadence-sec values must be positive")
    if args.gap_sec <= 0:
        raise SystemExit("gap-sec must be positive")
    if args.tier_vmax_mps <= 0:
        raise SystemExit("tier-vmax-mps must be positive")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    datasets = ["tdrive", "geolife", "porto"] if args.dataset == "all" else [args.dataset]
    intervals: list[Interval] = []
    inventory: list[dict[str, int | str]] = []
    for dataset in datasets:
        dataset_intervals, trip_count = audit_dataset(
            dataset,
            cadence_values=sorted(set(args.cadence_sec)),
            gap_sec=args.gap_sec,
            max_trips=args.max_trips,
        )
        intervals.extend(dataset_intervals)
        inventory.append({"dataset": dataset, "scanned_trips": trip_count, "intervals": len(dataset_intervals)})

    write_intervals(args.output_dir / "intervals.csv", intervals)
    summary = build_summary(intervals, tier_vmax_mps=args.tier_vmax_mps)
    write_summary(args.output_dir / "summary.csv", summary)
    report = build_report(args, inventory, summary)
    (args.output_dir / "analysis-report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"inventory": inventory, "summary_rows": len(summary), "output_dir": str(args.output_dir)}, indent=2))
    return 0


def audit_dataset(
    dataset: str,
    *,
    cadence_values: list[int],
    gap_sec: int,
    max_trips: int,
) -> tuple[list[Interval], int]:
    matcher = IdentityMatcher()
    intervals: list[Interval] = []
    trip_count = 0
    for trip_id, points in iter_source(dataset, gap_sec=gap_sec):
        trip_count += 1
        matched = matcher.match(points)
        for cadence_sec in cadence_values:
            sampled = resample_matched_points(matched, cadence_sec=cadence_sec)
            intervals.extend(intervals_for_trip(dataset, trip_id, sampled, cadence_sec=cadence_sec))
        if max_trips > 0 and trip_count >= max_trips:
            break
    return intervals, trip_count


def iter_source(dataset: str, *, gap_sec: int) -> Iterator[tuple[str, list[RawPoint]]]:
    dataset_dir = ROOT_DIR / "dataset"
    if dataset == "tdrive":
        return iter_tdrive_trips(dataset_dir / "T-Drive", gap_sec=gap_sec)
    if dataset == "geolife":
        return iter_geolife_driving_trips(dataset_dir / "Geolife Trajectories 1.3" / "Data", gap_sec=gap_sec)
    if dataset == "porto":
        return iter_porto_trips(dataset_dir / "porto" / "train.csv")
    raise ValueError(dataset)


def intervals_for_trip(
    dataset: str,
    trip_id: str,
    sampled: list[MatchedPoint],
    *,
    cadence_sec: int,
) -> Iterable[Interval]:
    for prev, curr in zip(sampled, sampled[1:]):
        dt_sec = int(curr.timestamp) - int(prev.timestamp)
        if dt_sec != cadence_sec:
            continue
        odo_delta_m = float(curr.cumulative_distance_m) - float(prev.cumulative_distance_m)
        dist_m = haversine_m(prev.lat, prev.lon, curr.lat, curr.lon)
        if odo_delta_m <= 0 or dist_m <= 0:
            continue
        yield Interval(
            dataset=dataset,
            trip_id=trip_id,
            cadence_sec=cadence_sec,
            dt_sec=dt_sec,
            odo_delta_m=odo_delta_m,
            dist_m=dist_m,
            ratio=odo_delta_m / dist_m,
            odo_speed_mps=odo_delta_m / dt_sec,
        )


def build_summary(intervals: list[Interval], *, tier_vmax_mps: float) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    datasets = sorted({interval.dataset for interval in intervals})
    cadences = sorted({interval.cadence_sec for interval in intervals})
    dataset_groups = datasets + ["combined"]
    for dataset in dataset_groups:
        for cadence_sec in cadences:
            candidates = [
                interval
                for interval in intervals
                if (dataset == "combined" or interval.dataset == dataset) and interval.cadence_sec == cadence_sec
            ]
            for min_dist_m in (0, 25, 50, 100):
                selected = [
                    interval
                    for interval in candidates
                    if interval.dist_m >= min_dist_m and interval.odo_speed_mps <= tier_vmax_mps
                ]
                ratios = sorted(interval.ratio for interval in selected)
                rows.append(
                    {
                        "dataset": dataset,
                        "cadence_sec": cadence_sec,
                        "min_dist_m": min_dist_m,
                        "tier_vmax_mps": tier_vmax_mps,
                        "n": len(ratios),
                        "excluded_speed_gt_tier": sum(interval.odo_speed_mps > tier_vmax_mps for interval in candidates),
                        "ratio_p50": percentile(ratios, 50),
                        "ratio_p90": percentile(ratios, 90),
                        "ratio_p95": percentile(ratios, 95),
                        "ratio_p99": percentile(ratios, 99),
                        "ratio_max": max(ratios) if ratios else math.nan,
                        "share_ratio_gt_1_4": share_gt(ratios, 1.4),
                        "share_ratio_gt_2_5": share_gt(ratios, 2.5),
                    }
                )
    return rows


def percentile(values: list[float], q: int) -> float:
    if not values:
        return math.nan
    pos = (len(values) - 1) * q / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def share_gt(values: list[float], threshold: float) -> float:
    if not values:
        return math.nan
    return sum(value > threshold for value in values) / len(values)


def write_intervals(path: Path, intervals: list[Interval]) -> None:
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(Interval.__dataclass_fields__))
        writer.writeheader()
        for interval in intervals:
            writer.writerow(interval.__dict__)


def write_summary(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_report(args: argparse.Namespace, inventory: list[dict[str, int | str]], rows: list[dict[str, float | int | str]]) -> str:
    default_view = next(
        (
            row
            for row in rows
            if row["dataset"] == "combined" and int(row["cadence_sec"]) == 300 and int(row["min_dist_m"]) == 50
        ),
        None,
    )
    lines = [
        "# Geometric Binding Audit",
        "",
        "## Scope",
        "",
        "This is a data-only audit. It does not modify circuits, signatures, or services.",
        "`odo_delta` is a reproducible proxy: the cumulative haversine length of the raw GPS polyline.",
        "`dist` is the haversine distance between the two cadence-sampled endpoints.",
        "The proxy is not a physical vehicle odometer and is sensitive to GPS noise.",
        "",
        f"Only full cadence intervals are retained. Segments are split when raw-point gaps exceed {args.gap_sec}s.",
        f"Rows with proxy speed above the {args.tier_vmax_mps:g}m/s tier limit are excluded from calibration summaries.",
        "",
        "## Inventory",
        "",
        "| Dataset | Scanned trips | Candidate intervals |",
        "| --- | ---: | ---: |",
    ]
    for item in inventory:
        lines.append(f"| {item['dataset']} | {item['scanned_trips']} | {item['intervals']} |")
    lines.extend(
        [
            "",
            "## Decision Table",
            "",
            "The primary calibration view uses `dist >= 50m`. Smaller endpoint motion is reported in `summary.csv` but is unstable for ratio calibration.",
            "",
            "| Dataset | Cadence | n | p50 | p95 | p99 | >1.4 | >2.5 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        if int(row["min_dist_m"]) != 50:
            continue
        lines.append(
            f"| {row['dataset']} | {row['cadence_sec']}s | {row['n']} | "
            f"{fmt(row['ratio_p50'])} | {fmt(row['ratio_p95'])} | {fmt(row['ratio_p99'])} | "
            f"{pct(row['share_ratio_gt_1_4'])} | {pct(row['share_ratio_gt_2_5'])} |"
        )
    lines.extend(["", "## Decision", ""])
    if default_view is None:
        lines.append("No combined `300s`, `dist >= 50m` row is available. Do not choose a geometric bound from this run.")
    elif float(default_view["ratio_p95"]) > 2.5:
        lines.append(
            f"At the default settlement cadence (`300s`), the combined `dist >= 50m` p95 ratio is "
            f"`{fmt(default_view['ratio_p95'])}`. Do not deploy a fixed geometric upper bound yet. "
            "Use the low-cost path-one constraint `odo_delta <= dt * tier_vmax` and collect physical-odometer calibration data."
        )
    else:
        lines.append(
            f"At the default settlement cadence (`300s`), the combined `dist >= 50m` p95 ratio is "
            f"`{fmt(default_view['ratio_p95'])}`. A geometric upper bound may be feasible, but still requires "
            "physical-odometer calibration and an explicit target false-reject rate."
        )
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- A fixed geometric upper bound is credible only after checking dataset-specific tails and physical-odometer data.",
            "- Ratios near stationary endpoints are not suitable for choosing `max_sinuosity`; inspect the `25m`, `50m`, and `100m` strata together.",
            "- The cheap path-one constraint `odo_delta <= dt * tier_vmax` is orthogonal and does not depend on this calibration.",
            "",
        ]
    )
    return "\n".join(lines)


def fmt(value: float | int | str) -> str:
    number = float(value)
    return "NA" if math.isnan(number) else f"{number:.3f}"


def pct(value: float | int | str) -> str:
    number = float(value)
    return "NA" if math.isnan(number) else f"{100 * number:.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
