from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import shutil
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_experiments import e4_required_cameras  # noqa: E402
from common.eval_harness import HarnessParams, compute_bill, total_odometer_distance  # noqa: E402
from common.settlement import ReceiverFix, TariffTable  # noqa: E402


DEFAULT_INPUTS = {
    "geolife": (
        ROOT_DIR / "data" / "e1_mechanism_ablation" / "geolife" / "geolife_medium_identity.jsonl",
        ROOT_DIR / "data" / "e1_mechanism_ablation" / "geolife" / "tariff_block.json",
    ),
    "rome": (
        ROOT_DIR / "experiments" / "e1_rome_real_tariff_ratio_fix" / "periods_60s.jsonl",
        ROOT_DIR / "experiments" / "e1_rome_real_tariff_ratio_fix" / "tariff_block.json",
    ),
    "porto": (
        ROOT_DIR / "data" / "e1_mechanism_ablation" / "porto" / "periods_60s.jsonl",
        ROOT_DIR / "data" / "e1_mechanism_ablation" / "porto" / "tariff_block.json",
    ),
    "tdrive": (
        ROOT_DIR / "data" / "e1_mechanism_ablation" / "tdrive" / "periods_300s.jsonl",
        ROOT_DIR / "data" / "e1_mechanism_ablation" / "tdrive" / "tariff_block.json",
    ),
}

E1_SUMMARIES = {
    "geolife": ROOT_DIR / "experiments" / "e1_objective_fix" / "geolife_summary.csv",
    "porto": ROOT_DIR / "experiments" / "e1_objective_fix" / "porto_summary.csv",
    "tdrive": ROOT_DIR / "experiments" / "e1_objective_fix" / "tdrive_summary.csv",
    "rome": ROOT_DIR / "experiments" / "e1_rome_real_tariff_ratio_fix" / "summary_162.csv",
}

COUNT_CAP = 10**12


@dataclass(frozen=True)
class PeriodRecord:
    dataset: str
    record: dict
    fixes: list[ReceiverFix]
    tariff: TariffTable
    params: HarnessParams
    fee_cents: int
    distance_m: int
    fallback_intervals: int
    n_intervals: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TSIP-RUC E4/E5 proxy experiments without geospatial dependencies.")
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "experiments" / "e4_e5_ruc"), help="Output directory.")
    parser.add_argument("--p-detect-target", type=float, default=0.95)
    parser.add_argument("--max-privacy-periods", type=int, default=24)
    parser.add_argument("--graph-max-steps", type=int, default=8)
    parser.add_argument("--graph-max-states", type=int, default=50_000)
    parser.add_argument("--distance-bucket-m", type=int, default=100)
    parser.add_argument("--fee-bucket-cents", type=int, default=5000)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records_by_dataset = load_all_records(DEFAULT_INPUTS)
    e1_rows = load_e1_rows(E1_SUMMARIES)

    e4_rows: list[dict] = []
    deterrence_rows: list[dict] = []
    empirical_rows: list[dict] = []
    graph_rows: list[dict] = []
    fraud_rows: list[dict] = []

    for dataset, records in records_by_dataset.items():
        if not records:
            continue
        graph = observed_graph(records)
        road = road_proxy_stats(records, graph)
        period_segments = [r.n_intervals for r in records if r.n_intervals > 0]
        segments_per_driver = max(1, int(round(statistics.median(period_segments))))
        area_km2 = road["tariff_area_km2"]
        road_km = max(road["observed_road_km"], 0.001)
        observed_segments = max(1, road["observed_road_segments"])
        grid_segments = max(1, road["grid_road_segments"])

        for proxy_name, road_segments in [
            ("observed_path_proxy_generous", observed_segments),
            ("tariff_grid_proxy_context", grid_segments),
        ]:
            for omit_fraction in [0.05, 0.10, 0.20]:
                row = e4_required_cameras(
                    omit_fraction=omit_fraction,
                    segments_per_driver=segments_per_driver,
                    road_network_segments=road_segments,
                    p_detect_target=float(args.p_detect_target),
                )
                cameras = int(row["required_cameras_spotcheck"])
                e4_rows.append(
                    {
                        "dataset": dataset,
                        "road_proxy": proxy_name,
                        "omit_fraction": omit_fraction,
                        "segments_per_driver": segments_per_driver,
                        "road_network_segments": road_segments,
                        "target_detection_probability": float(args.p_detect_target),
                        "required_coverage_fraction": row["required_coverage_fraction"],
                        "required_cameras_spotcheck": cameras,
                        "required_cameras_tsip_ruc": row["required_cameras_tsip_ruc"],
                        "cameras_per_km_road": cameras / road_km,
                        "cameras_per_km2": cameras / max(area_km2, 0.001),
                        "observed_road_km": road["observed_road_km"],
                        "tariff_area_km2": area_km2,
                    }
                )

        dataset_e1 = e1_rows.get(dataset, [])
        p95 = max((float(row.get("p95_savings") or 0.0) for row in dataset_e1), default=0.0)
        median_fee = statistics.median([r.fee_cents for r in records if r.fee_cents > 0])
        for detection_probability in [0.10, 0.25, 0.50, 0.95]:
            deterrence_rows.append(
                {
                    "dataset": dataset,
                    "expected_saving_source": "max_e1_branch_p95_savings_ratio",
                    "expected_saving_ratio": p95,
                    "median_period_fee_cents": median_fee,
                    "detection_probability": detection_probability,
                    "deterrence_fine_as_fee_multiple": 0.0 if detection_probability <= 0 else p95 / detection_probability,
                    "deterrence_fine_cents": 0.0 if detection_probability <= 0 else p95 * median_fee / detection_probability,
                }
            )

        empirical_rows.extend(empirical_anonymity(records))
        graph_rows.extend(
            graph_privacy_counts(
                records[: max(1, int(args.max_privacy_periods))],
                graph,
                distance_bucket_m=int(args.distance_bucket_m),
                fee_bucket_cents=int(args.fee_bucket_cents),
                graph_max_steps=int(args.graph_max_steps),
                graph_max_states=int(args.graph_max_states),
            )
        )
        fraud_rows.extend(fraud_metric_rows(dataset, records, dataset_e1))

    write_csv(out_dir / "e4_spotcheck_summary.csv", e4_rows)
    write_csv(out_dir / "e4_deterrence.csv", deterrence_rows)
    write_csv(out_dir / "e5_empirical_anonymity.csv", empirical_rows)
    write_csv(out_dir / "e5_graph_privacy_counts.csv", graph_rows)
    write_csv(out_dir / "fraud_metrics.csv", fraud_rows)
    write_receipt(out_dir / "receipt.json", records_by_dataset, e1_rows, args)

    print(f"wrote {out_dir}")
    print(f"e4 rows={len(e4_rows)} e5 empirical rows={len(empirical_rows)} graph rows={len(graph_rows)}")


def load_all_records(inputs: dict[str, tuple[Path, Path]]) -> dict[str, list[PeriodRecord]]:
    out: dict[str, list[PeriodRecord]] = {}
    for dataset, (period_path, tariff_path) in inputs.items():
        if not period_path.exists() or not tariff_path.exists():
            out[dataset] = []
            continue
        tariff, block = load_tariff(tariff_path)
        cell_size_m = int(block.get("cell_size_m", 100))
        records: list[PeriodRecord] = []
        with period_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                fixes = [ReceiverFix.from_dict(x) for x in record["fixes"]]
                params = HarnessParams(cadence_sec=int(record.get("cadence_sec", 60)), cell_size_m=cell_size_m)
                bill = compute_bill(fixes, tariff, params)
                records.append(
                    PeriodRecord(
                        dataset=dataset,
                        record=record,
                        fixes=fixes,
                        tariff=tariff,
                        params=params,
                        fee_cents=int(bill["total_fee_cents"]),
                        distance_m=int(total_odometer_distance(fixes)),
                        fallback_intervals=int(bill["fallback_intervals"]),
                        n_intervals=max(0, len(fixes) - 1),
                    )
                )
        out[dataset] = records
    return out


def load_tariff(path: Path) -> tuple[TariffTable, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tariff_payload = payload.get("tariff", payload)
    return (
        TariffTable(
            tariff_version=int(tariff_payload["tariff_version"]),
            grid_w=int(tariff_payload["grid_w"]),
            cell_zones={int(k): int(v) for k, v in tariff_payload["cell_zones"].items()},
            zone_rates_cents_per_m={int(k): int(v) for k, v in tariff_payload["zone_rates_cents_per_m"].items()},
        ),
        payload.get("block", {}),
    )


def load_e1_rows(paths: dict[str, Path]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for dataset, path in paths.items():
        rows: list[dict] = []
        if path.exists():
            with path.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    rows.append(row)
        out[dataset] = rows
    return out


def observed_graph(records: list[PeriodRecord]) -> dict[int, list[tuple[int, int]]]:
    edges: dict[int, set[tuple[int, int]]] = defaultdict(set)
    cells: set[int] = set()
    if not records:
        return {}
    tariff = records[0].tariff
    params = records[0].params
    for record in records:
        for fix in record.fixes:
            cells.add(tariff.cell_index(fix.cell_x, fix.cell_y))
        for prev, curr in zip(record.fixes, record.fixes[1:]):
            a = tariff.cell_index(prev.cell_x, prev.cell_y)
            b = tariff.cell_index(curr.cell_x, curr.cell_y)
            dist = max(0, int(curr.odometer_reading_m) - int(prev.odometer_reading_m))
            edges[a].add((b, dist))
            edges[b].add((a, dist))
    for cell in cells:
        edges[cell].add((cell, 0))
    return {cell: sorted(nexts) for cell, nexts in sorted(edges.items())}


def road_proxy_stats(records: list[PeriodRecord], graph: dict[int, list[tuple[int, int]]]) -> dict[str, float | int]:
    tariff = records[0].tariff
    params = records[0].params
    undirected: set[tuple[int, int]] = set()
    observed_km = 0.0
    for a, nexts in graph.items():
        for b, dist in nexts:
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            if key not in undirected:
                observed_km += float(dist) / 1000.0
                undirected.add(key)
    grid_edges = 0
    for cell in tariff.cell_zones:
        x, y = idx_to_xy(tariff, cell)
        for nx, ny in [(x + 1, y), (x, y + 1)]:
            ncell = tariff.cell_index(nx, ny)
            if ncell in tariff.cell_zones:
                grid_edges += 1
    area_km2 = len(tariff.cell_zones) * (params.cell_size_m / 1000.0) ** 2
    return {
        "observed_road_segments": len(undirected),
        "observed_road_km": observed_km,
        "grid_road_segments": grid_edges,
        "tariff_area_km2": area_km2,
    }


def empirical_anonymity(records: list[PeriodRecord]) -> list[dict]:
    rows: list[dict] = []
    profiles = [
        {
            "period_id": str(r.record.get("period_id") or r.record.get("trip_id") or r.fixes[0].period_id),
            "fee_cents": r.fee_cents,
            "distance_m": r.distance_m,
            "fallback_intervals": r.fallback_intervals,
            "n_intervals": r.n_intervals,
        }
        for r in records
    ]
    for target in profiles:
        distance_tol = max(100, int(round(0.10 * max(1, target["distance_m"]))))
        fee_tol = max(500, int(round(0.10 * max(1, target["fee_cents"]))))
        counts = {
            "zone_priced_statement": 0,
            "mixed_statement": 0,
            "odometer_only_statement": 0,
        }
        for other in profiles:
            distance_match = abs(other["distance_m"] - target["distance_m"]) <= distance_tol
            fee_match = abs(other["fee_cents"] - target["fee_cents"]) <= fee_tol
            fallback_match = other["fallback_intervals"] == target["fallback_intervals"]
            interval_match = other["n_intervals"] == target["n_intervals"]
            if distance_match and fee_match and fallback_match and interval_match:
                counts["zone_priced_statement"] += 1
            if distance_match and fallback_match and interval_match:
                counts["mixed_statement"] += 1
            if distance_match and interval_match:
                counts["odometer_only_statement"] += 1
        for mode, count in counts.items():
            rows.append(
                {
                    "dataset": records[0].dataset,
                    "period_id": target["period_id"],
                    "mode": mode,
                    "empirical_anonymity_set": count,
                    "empirical_entropy_bits": math.log2(max(1, count)),
                    "distance_tol_m": distance_tol,
                    "fee_tol_cents": fee_tol if mode == "zone_priced_statement" else "",
                }
            )
    return rows


def graph_privacy_counts(
    records: list[PeriodRecord],
    graph: dict[int, list[tuple[int, int]]],
    *,
    distance_bucket_m: int,
    fee_bucket_cents: int,
    graph_max_steps: int,
    graph_max_states: int,
) -> list[dict]:
    rows: list[dict] = []
    for record in records:
        effective_steps = max(1, min(record.n_intervals, int(graph_max_steps)))
        prefix_fixes = record.fixes[: effective_steps + 1]
        target_distance_m = int(total_odometer_distance(prefix_fixes))
        target_fee_cents = int(compute_bill(prefix_fixes, record.tariff, record.params)["total_fee_cents"])
        for mode in ["zone_priced_graph_proxy", "odometer_only_graph_proxy"]:
            count = count_resource_paths(
                graph,
                record.tariff,
                n_steps=effective_steps,
                target_distance_m=target_distance_m,
                target_fee_cents=target_fee_cents,
                mode=mode,
                distance_bucket_m=distance_bucket_m,
                fee_bucket_cents=fee_bucket_cents,
                max_states=graph_max_states,
            )
            rows.append(
                {
                    "dataset": record.dataset,
                    "period_id": str(record.record.get("period_id") or record.record.get("trip_id") or record.fixes[0].period_id),
                    "mode": mode,
                    "graph_proxy_path_count_cap1e12": count,
                    "graph_proxy_entropy_bits": math.log2(max(1, count)),
                    "distance_bucket_m": distance_bucket_m,
                    "fee_bucket_cents": fee_bucket_cents if "zone_priced" in mode else "",
                    "effective_graph_steps": effective_steps,
                    "target_scope": "actual_prefix",
                    "graph_nodes": len(graph),
                    "graph_directed_edges": sum(len(v) for v in graph.values()),
                }
            )
    return rows


def count_resource_paths(
    graph: dict[int, list[tuple[int, int]]],
    tariff: TariffTable,
    *,
    n_steps: int,
    target_distance_m: int,
    target_fee_cents: int,
    mode: str,
    distance_bucket_m: int,
    fee_bucket_cents: int,
    max_states: int,
) -> int:
    if not graph or n_steps <= 0:
        return 0
    use_fee = "zone_priced" in mode
    target_db = int(round(target_distance_m / max(1, distance_bucket_m)))
    target_fb = int(round(target_fee_cents / max(1, fee_bucket_cents)))
    db_tol = max(1, int(math.ceil(0.10 * max(1, target_db))))
    fb_tol = max(1, int(math.ceil(0.10 * max(1, target_fb))))
    max_db = target_db + db_tol
    max_fb = target_fb + fb_tol
    dp: dict[tuple[int, int, int], int] = {(cell, 0, 0): 1 for cell in graph}
    for _ in range(n_steps):
        nxt: dict[tuple[int, int, int], int] = defaultdict(int)
        for (cell, db, fb), count in dp.items():
            for next_cell, dist_m in graph.get(cell, []):
                ndb = db + int(round(dist_m / max(1, distance_bucket_m)))
                if ndb > max_db:
                    continue
                nfb = fb
                if use_fee:
                    rate = tariff.rate_for_zone(tariff.zone_for_cell(cell))
                    nfb += int(round((dist_m * rate) / max(1, fee_bucket_cents)))
                    if nfb > max_fb:
                        continue
                key = (next_cell, ndb, nfb)
                nxt[key] = min(COUNT_CAP, nxt[key] + count)
        if not nxt:
            return 0
        if len(nxt) > int(max_states):
            nxt = prune_states(nxt, target_db=target_db, target_fb=target_fb, use_fee=use_fee, limit=int(max_states))
        dp = nxt
    total = 0
    for _cell, db, fb in dp:
        if abs(db - target_db) > db_tol:
            continue
        if use_fee and abs(fb - target_fb) > fb_tol:
            continue
        total = min(COUNT_CAP, total + dp[(_cell, db, fb)])
    return total


def prune_states(
    states: dict[tuple[int, int, int], int],
    *,
    target_db: int,
    target_fb: int,
    use_fee: bool,
    limit: int,
) -> dict[tuple[int, int, int], int]:
    scored = sorted(
        states.items(),
        key=lambda item: (
            abs(item[0][1] - target_db) + (abs(item[0][2] - target_fb) if use_fee else 0),
            item[0][1],
            item[0][2],
            item[0][0],
        ),
    )
    return dict(scored[: max(1, int(limit))])


def fraud_metric_rows(dataset: str, records: list[PeriodRecord], e1_rows: list[dict]) -> list[dict]:
    median_fee = statistics.median([r.fee_cents for r in records if r.fee_cents > 0])
    rows: list[dict] = []
    for row in e1_rows:
        branch = str(row.get("branch", ""))
        if not branch or branch in {"all_on", "no_continuity"}:
            continue
        p95 = float(row.get("p95_savings") or 0.0)
        median_savings = float(row.get("median_savings") or 0.0)
        rows.append(
            {
                "dataset": dataset,
                "attack_branch": branch,
                "median_savings_ratio": median_savings,
                "p95_savings_ratio": p95,
                "median_period_fee_cents": median_fee,
                "revenue_leakage_per_10k_periods_cents_p95": p95 * median_fee * 10_000,
                "tsip_detection_outcome": "deterministic reject if proof-violating; E3 quantifies proof-consistent residual",
                "spotcheck_detection_outcome": "probabilistic and delayed; see e4_spotcheck_summary.csv",
            }
        )
    return rows


def write_csv(path: Path, rows: Iterable[dict]) -> None:
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            writer.writerow(row)


def write_receipt(path: Path, records_by_dataset: dict[str, list[PeriodRecord]], e1_rows: dict[str, list[dict]], args) -> None:
    receipt = {
        "command": " ".join(sys.argv),
        "python": sys.version,
        "inputs": {
            dataset: {
                "periods": str(DEFAULT_INPUTS[dataset][0].relative_to(ROOT_DIR)),
                "tariff": str(DEFAULT_INPUTS[dataset][1].relative_to(ROOT_DIR)),
                "n_periods": len(records),
            }
            for dataset, records in records_by_dataset.items()
        },
        "e1_summaries": {dataset: str(path.relative_to(ROOT_DIR)) for dataset, path in E1_SUMMARIES.items() if path.exists()},
        "environment": {
            "rapidsnark": shutil.which("rapidsnark"),
            "rapidsnark_prover": shutil.which("prover"),
            "packages": {
                name: bool(importlib.util.find_spec(name))
                for name in ["osmnx", "pyrosm", "geopandas", "shapely", "networkx", "pandas", "numpy"]
            },
        },
        "method_notes": [
            "E4 uses observed_path_proxy_generous as the primary reconstructed spot-check road universe because pyrosm/osmnx are unavailable locally.",
            "tariff_grid_proxy_context is reported as a context sensitivity, not the main generous baseline.",
            "E5 reports both empirical anonymity among observed periods and graph-proxy resource-constrained path counts over observed tariff-grid transitions.",
        ],
        "settings": {
            "p_detect_target": args.p_detect_target,
            "max_privacy_periods": args.max_privacy_periods,
            "graph_max_steps": args.graph_max_steps,
            "graph_max_states": args.graph_max_states,
            "distance_bucket_m": args.distance_bucket_m,
            "fee_bucket_cents": args.fee_bucket_cents,
        },
        "e1_rows_loaded": {dataset: len(rows) for dataset, rows in e1_rows.items()},
    }
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")


def idx_to_xy(tariff: TariffTable, cell: int) -> tuple[int, int]:
    return int(cell) % int(tariff.grid_w), int(cell) // int(tariff.grid_w)


def cell_distance_by_idx_m(tariff: TariffTable, a: int, b: int, cell_size_m: int) -> float:
    ax, ay = idx_to_xy(tariff, a)
    bx, by = idx_to_xy(tariff, b)
    return math.hypot(ax - bx, ay - by) * int(cell_size_m)


if __name__ == "__main__":
    main()
