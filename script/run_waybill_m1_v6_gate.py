#!/usr/bin/env python3
"""Run the WayBill M1 odometer-fallback data and property gate.

This runner deliberately keeps the historical V5 time/speed fallback as a
baseline.  V6 and the oracle use the same authenticated odometer deltas; only
the rate used on a position-unavailable interval differs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import ReceiverFix, TariffTable
from common.settlement_v6 import reconcile_month_v6


MASK_DOMAIN = "waybill-m1-position-outage-mask-v1"
MASK_SEEDS = (17, 31, 47, 73, 101)
OUTAGE_ALPHAS = (0.05, 0.10, 0.20)
ODOMETER_ERRORS = (-0.02, -0.01, -0.005, 0.0, 0.005, 0.01, 0.02)
BOOTSTRAP_SEED = 20260713
BOOTSTRAP_REPLICATES = 5_000
MAX_DT_SEC = 600
TIER_VMAX_MPS = 33

DEFAULT_INPUTS = (
    ROOT_DIR / "data/e1_mechanism_ablation/geolife/geolife_medium_identity.jsonl",
    ROOT_DIR / "experiments/e1_rome_real_tariff_ratio_fix/periods_60s.jsonl",
    ROOT_DIR / "data/e1_mechanism_ablation/porto/periods_60s.jsonl",
    ROOT_DIR / "data/e1_mechanism_ablation/tdrive/periods_300s.jsonl",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dataset_name(path: Path) -> str:
    text = str(path).lower()
    for name in ("geolife", "rome", "porto", "tdrive"):
        if name in text:
            return name
    raise ValueError(f"cannot infer dataset from {path}")


def _load_tariff(path: Path) -> tuple[TariffTable, Path]:
    for candidate in (path.parent / "tariff_block.json", path.parent.parent / "tariff_block.json"):
        if not candidate.exists():
            continue
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        raw = payload.get("tariff", payload)
        return (
            TariffTable(
                tariff_version=int(raw["tariff_version"]),
                grid_w=int(raw["grid_w"]),
                cell_zones={int(k): int(v) for k, v in raw["cell_zones"].items()},
                zone_rates_cents_per_m={
                    int(k): int(v) for k, v in raw["zone_rates_cents_per_m"].items()
                },
            ),
            candidate,
        )
    raise FileNotFoundError(f"missing tariff_block.json for {path}")


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def deterministic_outage_edges(
    *, dataset: str, period_id: str, n_intervals: int, alpha: float, seed: int
) -> list[int]:
    """Select a frozen, reproducible outage mask without using process RNG state."""

    if n_intervals <= 0:
        return []
    if not 0.0 < float(alpha) <= 1.0:
        raise ValueError("alpha must be in (0, 1]")
    selected = max(1, int(math.ceil(n_intervals * float(alpha))))
    ranked: list[tuple[bytes, int]] = []
    for edge in range(n_intervals):
        message = f"{MASK_DOMAIN}|{seed}|{dataset}|{period_id}|{edge}".encode()
        ranked.append((hashlib.sha256(message).digest(), edge))
    return sorted(edge for _score, edge in sorted(ranked)[:selected])


def _edge_rows(fixes: list[ReceiverFix], tariff: TariffTable) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for edge, (prev, curr) in enumerate(zip(fixes, fixes[1:])):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        if dt <= 0:
            raise ValueError("authenticated time must be strictly increasing")
        if delta < 0:
            raise ValueError("odometer readings must be monotonic")
        cell_idx = tariff.cell_index(prev.cell_x, prev.cell_y)
        zone_id = tariff.zone_for_cell(cell_idx)
        rate = tariff.rate_for_zone(zone_id)
        rows.append(
            {
                "edge": edge,
                "dt_sec": dt,
                "delta_odo_m": delta,
                "cell_idx": cell_idx,
                "zone_id": zone_id,
                "zone_rate_cents_per_m": rate,
            }
        )
    return rows


def evaluate_mask(
    edge_rows: list[dict[str, int]], *, outage_edges: Iterable[int], r_max_cents_per_m: int
) -> dict[str, int | float | bool]:
    outage = {int(edge) for edge in outage_edges}
    oracle_fee = 0
    v5_fee = 0
    v6_fee = 0
    total_distance = 0
    outage_distance = 0
    max_withholding_advantage = 0
    parking_outage_edges = 0
    parking_v5_fee = 0
    parking_v6_fee = 0
    speed_bound_ok = True
    max_dt_ok = True
    for row in edge_rows:
        edge = int(row["edge"])
        dt = int(row["dt_sec"])
        delta = int(row["delta_odo_m"])
        rate = int(row["zone_rate_cents_per_m"])
        exact = delta * rate
        fallback_v6 = delta * int(r_max_cents_per_m)
        fallback_v5 = dt * TIER_VMAX_MPS * int(r_max_cents_per_m)
        oracle_fee += exact
        total_distance += delta
        max_withholding_advantage = max(max_withholding_advantage, exact - fallback_v6)
        speed_bound_ok = speed_bound_ok and delta <= dt * TIER_VMAX_MPS
        max_dt_ok = max_dt_ok and dt <= MAX_DT_SEC
        if edge in outage:
            v5_fee += fallback_v5
            v6_fee += fallback_v6
            outage_distance += delta
            if delta == 0:
                parking_outage_edges += 1
                parking_v5_fee += fallback_v5
                parking_v6_fee += fallback_v6
        else:
            v5_fee += exact
            v6_fee += exact
    denominator = max(1, oracle_fee)
    return {
        "oracle_fee_cents": oracle_fee,
        "v5_fee_cents": v5_fee,
        "v6_fee_cents": v6_fee,
        "total_distance_m": total_distance,
        "outage_distance_m": outage_distance,
        "v5_surcharge_cents": v5_fee - oracle_fee,
        "v6_surcharge_cents": v6_fee - oracle_fee,
        "v5_surcharge_rate": (v5_fee - oracle_fee) / denominator,
        "v6_surcharge_rate": (v6_fee - oracle_fee) / denominator,
        "paired_improvement_cents": v5_fee - v6_fee,
        "paired_improvement_rate": (v5_fee - v6_fee) / denominator,
        "v6_undercharge_cents": max(0, oracle_fee - v6_fee),
        "max_withholding_advantage_cents": max_withholding_advantage,
        "parking_outage_edges": parking_outage_edges,
        "parking_v5_fee_cents": parking_v5_fee,
        "parking_v6_fee_cents": parking_v6_fee,
        "speed_bound_ok": speed_bound_ok,
        "max_dt_ok": max_dt_ok,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * float(percentile) / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _cluster_bootstrap(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    clusters: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        clusters[(str(row["dataset"]), str(row["period_id"]))].append(
            float(row["paired_improvement_cents"])
        )
    values = [statistics.median(group) for group in clusters.values()]
    if not values:
        raise ValueError("bootstrap requires rows")
    rng = random.Random(BOOTSTRAP_SEED)
    replicates: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = [values[rng.randrange(len(values))] for _ in values]
        replicates.append(statistics.median(sample))
    return {
        "cluster_count": len(values),
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "paired_median_improvement_cents": statistics.median(values),
        "ci95_low_cents": _percentile(replicates, 2.5),
        "ci95_high_cents": _percentile(replicates, 97.5),
    }


def _scale_delta(delta: int, error: float) -> int:
    # Non-negative half-up quantization, matching an exact integer billing unit.
    return max(0, int(math.floor(delta * (1.0 + float(error)) + 0.5)))


def _sensitivity_rows(
    periods: list[dict[str, Any]], tariffs: dict[str, TariffTable]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for period in periods:
        dataset = str(period["dataset"])
        tariff = tariffs[dataset]
        r_max = tariff.max_zone_rate_cents_per_m
        edges = list(period["edge_rows"])
        outage = set(
            deterministic_outage_edges(
                dataset=dataset,
                period_id=str(period["period_id"]),
                n_intervals=len(edges),
                alpha=0.10,
                seed=17,
            )
        )
        true_fee = sum(int(edge["delta_odo_m"]) * int(edge["zone_rate_cents_per_m"]) for edge in edges)
        outage_premium = sum(
            int(edge["delta_odo_m"]) * (r_max - int(edge["zone_rate_cents_per_m"]))
            for edge in edges
            if int(edge["edge"]) in outage
        )
        for error in ODOMETER_ERRORS:
            observed_fee = 0
            epsilon_m = 0
            for edge in edges:
                delta = int(edge["delta_odo_m"])
                observed = _scale_delta(delta, error)
                epsilon_m += abs(observed - delta)
                rate = r_max if int(edge["edge"]) in outage else int(edge["zone_rate_cents_per_m"])
                observed_fee += observed * rate
            revenue_lower = true_fee - r_max * epsilon_m
            fairness_upper = true_fee + outage_premium + r_max * epsilon_m
            rows.append(
                {
                    "dataset": dataset,
                    "period_id": period["period_id"],
                    "odometer_error_fraction": error,
                    "true_fee_cents": true_fee,
                    "observed_v6_fee_cents": observed_fee,
                    "outage_premium_cents": outage_premium,
                    "epsilon_odometer_m": epsilon_m,
                    "revenue_lower_bound_cents": revenue_lower,
                    "fairness_upper_bound_cents": fairness_upper,
                    "revenue_sound": observed_fee >= revenue_lower,
                    "honest_user_fair": observed_fee <= fairness_upper,
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _git_metadata() -> dict[str, Any]:
    def command(*args: str) -> str:
        try:
            return subprocess.check_output(args, cwd=ROOT_DIR, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return "unavailable"

    return {
        "head": command("git", "rev-parse", "HEAD"),
        "worktree_dirty": bool(command("git", "status", "--porcelain")),
    }


def _formal_note() -> str:
    return """# M1 formal property note — odometer-backed fallback v1

## Model and trust boundary

For each interval `i`, authenticated checkpoints bind strict time/sequence,
monotone odometer readings and a position-valid bit. Let the true traversed
distance be `d_i`, the attested integer odometer delta be `dhat_i`, the true
zone rate be `r_i`, and the canonical authority maximum be `R=max_z r(z)`.
The deployment claim is conditional on the odometer attestation and its stated
calibration/reset guarantees; OSNMA alone does not establish physical location
or odometer truth.

V6 charges `dhat_i*r_i` when position is valid and `dhat_i*R` otherwise.
Month close charges only `max(0, monthly_delta-sum(accepted_dhat_i))*R`.
Arithmetic is unsigned exact integer multiplication/addition with rejection on
u64/u32/u96 overflow; therefore `epsilon_arith=0` for accepted inputs.

## Revenue soundness

Assume `r_i <= R` and total odometer under-reading is bounded by
`epsilon_o >= sum_i max(0,d_i-dhat_i)`. For valid intervals,
`dhat_i*r_i >= d_i*r_i-R*max(0,d_i-dhat_i)`. For outage intervals,
`dhat_i*R >= dhat_i*r_i` and the same bound follows. Summing accepted periods
and applying month reconciliation gives

`B_accept >= B_true - R*epsilon_o - epsilon_arith`.

Whole-period omission leaves the corresponding distance unaccounted and bills
it at `R`; a missing month attestation enters the administrative-exception
state and is not interpreted as a zero bill.

## Honest-user fairness and withholding

Let `epsilon_o >= sum_i |d_i-dhat_i|`. Then

`B_accept <= B_true + sum_outage d_i*(R-r_i) + R*epsilon_o + epsilon_arith`.

Changing one position-valid interval to outage changes the bill by
`dhat_i*(R-r_i) >= 0`, so position withholding has no underpayment benefit.
If a vehicle is parked, `dhat_i=0`, and its outage charge is exactly zero
regardless of dwell time. These are conditional protocol properties, not a
claim that a real receiver/odometer has already been field-certified.
"""


def run(*, inputs: tuple[Path, ...], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tariffs: dict[str, TariffTable] = {}
    tariff_paths: dict[str, Path] = {}
    periods: list[dict[str, Any]] = []
    input_manifest: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for path in inputs:
        dataset = _dataset_name(path)
        tariff, tariff_path = _load_tariff(path)
        tariffs[dataset] = tariff
        tariff_paths[dataset] = tariff_path
        count = 0
        for record in _records(path):
            count += 1
            period_id = str(record.get("period_id") or record.get("trip_id"))
            try:
                fixes = [ReceiverFix.from_dict(raw) for raw in record["fixes"]]
                if len(fixes) < 2:
                    raise ValueError("period has fewer than two fixes")
                edges = _edge_rows(fixes, tariff)
                base = evaluate_mask(
                    edges, outage_edges=[], r_max_cents_per_m=tariff.max_zone_rate_cents_per_m
                )
                if not bool(base["speed_bound_ok"]):
                    raise ValueError("odometer delta exceeds tier speed budget")
                if not bool(base["max_dt_ok"]):
                    raise ValueError("authenticated time delta exceeds maximum")
                periods.append({"dataset": dataset, "period_id": period_id, "edge_rows": edges})
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                rejected.append({"dataset": dataset, "period_id": period_id, "reason": str(exc)})
        input_manifest.append(
            {
                "dataset": dataset,
                "path": str(path.relative_to(ROOT_DIR)),
                "sha256": _sha256(path),
                "records": count,
                "tariff_path": str(tariff_path.relative_to(ROOT_DIR)),
                "tariff_sha256": _sha256(tariff_path),
                "tariff_version": tariff.tariff_version,
                "r_max_cents_per_m": tariff.max_zone_rate_cents_per_m,
            }
        )

    data_rows: list[dict[str, Any]] = []
    for period in periods:
        dataset = str(period["dataset"])
        tariff = tariffs[dataset]
        for alpha in OUTAGE_ALPHAS:
            for seed in MASK_SEEDS:
                mask = deterministic_outage_edges(
                    dataset=dataset,
                    period_id=str(period["period_id"]),
                    n_intervals=len(period["edge_rows"]),
                    alpha=alpha,
                    seed=seed,
                )
                result = evaluate_mask(
                    list(period["edge_rows"]),
                    outage_edges=mask,
                    r_max_cents_per_m=tariff.max_zone_rate_cents_per_m,
                )
                data_rows.append(
                    {
                        "dataset": dataset,
                        "period_id": period["period_id"],
                        "mask_domain": MASK_DOMAIN,
                        "mask_seed": seed,
                        "outage_alpha": alpha,
                        "n_intervals": len(period["edge_rows"]),
                        "n_outage_intervals": len(mask),
                        "outage_edges": ";".join(str(edge) for edge in mask),
                        "r_max_cents_per_m": tariff.max_zone_rate_cents_per_m,
                        **result,
                    }
                )

    if not data_rows:
        raise RuntimeError("no M1 data rows were accepted")
    sensitivity = _sensitivity_rows(periods, tariffs)
    summary_rows: list[dict[str, Any]] = []
    for dataset in sorted(tariffs):
        group = [row for row in data_rows if row["dataset"] == dataset]
        if not group:
            summary_rows.append({"dataset": dataset, "n_rows": 0, "gate_passed": False})
            continue
        v5_abs = [float(row["v5_surcharge_cents"]) for row in group]
        v6_abs = [float(row["v6_surcharge_cents"]) for row in group]
        v5_rel = [float(row["v5_surcharge_rate"]) for row in group]
        v6_rel = [float(row["v6_surcharge_rate"]) for row in group]
        p95_v5_abs = _percentile(v5_abs, 95)
        p95_v6_abs = _percentile(v6_abs, 95)
        p95_v5_rel = _percentile(v5_rel, 95)
        p95_v6_rel = _percentile(v6_rel, 95)
        summary_rows.append(
            {
                "dataset": dataset,
                "n_periods": len({str(row["period_id"]) for row in group}),
                "n_paired_rows": len(group),
                "r_max_cents_per_m": tariffs[dataset].max_zone_rate_cents_per_m,
                "v5_surcharge_median_cents": statistics.median(v5_abs),
                "v6_surcharge_median_cents": statistics.median(v6_abs),
                "v5_surcharge_p95_cents": p95_v5_abs,
                "v6_surcharge_p95_cents": p95_v6_abs,
                "v5_surcharge_p95_rate": p95_v5_rel,
                "v6_surcharge_p95_rate": p95_v6_rel,
                "max_v6_undercharge_cents": max(int(row["v6_undercharge_cents"]) for row in group),
                "max_withholding_advantage_cents": max(
                    int(row["max_withholding_advantage_cents"]) for row in group
                ),
                "parking_outage_edges": sum(int(row["parking_outage_edges"]) for row in group),
                "parking_v5_fee_cents": sum(int(row["parking_v5_fee_cents"]) for row in group),
                "parking_v6_fee_cents": sum(int(row["parking_v6_fee_cents"]) for row in group),
                "p95_absolute_improved": p95_v6_abs < p95_v5_abs,
                "p95_relative_improved": p95_v6_rel < p95_v5_rel,
                "gate_passed": (
                    p95_v6_abs < p95_v5_abs
                    and p95_v6_rel < p95_v5_rel
                    and max(int(row["v6_undercharge_cents"]) for row in group) == 0
                    and max(int(row["max_withholding_advantage_cents"]) for row in group) == 0
                    and sum(int(row["parking_v6_fee_cents"]) for row in group) == 0
                ),
            }
        )

    bootstrap = _cluster_bootstrap(data_rows)
    constructed = {
        "parking_600s_zero_distance": evaluate_mask(
            [
                {
                    "edge": 0,
                    "dt_sec": 600,
                    "delta_odo_m": 0,
                    "cell_idx": 0,
                    "zone_id": 1,
                    "zone_rate_cents_per_m": 1,
                }
            ],
            outage_edges=[0],
            r_max_cents_per_m=5,
        ),
        "month_close_omission": reconcile_month_v6(
            monthly_odometer_start_m=1_000,
            monthly_odometer_end_m=2_000,
            accounted_distance_m=70,
            accepted_period_fee_cents=70,
            r_max_cents_per_m=5,
        ),
    }
    sensitivity_gate = all(
        bool(row["revenue_sound"]) and bool(row["honest_user_fair"]) for row in sensitivity
    )
    dataset_gate = all(bool(row.get("gate_passed")) for row in summary_rows)
    hard_gate = bool(
        dataset_gate
        and sensitivity_gate
        and float(bootstrap["ci95_low_cents"]) > 0
        and int(constructed["parking_600s_zero_distance"]["v6_fee_cents"]) == 0
        and int(constructed["month_close_omission"]["unaccounted_distance_m"]) == 930
        and int(constructed["month_close_omission"]["reconciliation_fee_cents"]) == 4_650
    )

    _write_csv(output_dir / "paired_period_rows.csv", data_rows)
    _write_csv(output_dir / "dataset_summary.csv", summary_rows)
    _write_csv(output_dir / "odometer_sensitivity.csv", sensitivity)
    if rejected:
        _write_csv(output_dir / "rejected_periods.csv", rejected)
    (output_dir / "formal_properties.md").write_text(_formal_note(), encoding="utf-8")
    result = {
        "artifact_type": "waybill.m1.odometer-fallback-gate/v1",
        "status": "verified" if hard_gate else "failed",
        "hard_gate_passed": hard_gate,
        "semantics": {
            "normal": "delta_odometer_m * zone_rate_cents_per_m",
            "position_unavailable": "delta_odometer_m * canonical_r_max_cents_per_m",
            "v5_baseline": "delta_time_sec * tier_vmax_mps * canonical_r_max_cents_per_m",
            "monthly": "max(0, monthly_delta_odometer-accounted_distance) * canonical_r_max",
            "currency": "dataset experimental cents",
            "rounding": "exact integer; sensitivity uses half-up to integer metres",
            "overflow": "reject-u96",
        },
        "pre_registered_masks": {
            "domain": MASK_DOMAIN,
            "seeds": list(MASK_SEEDS),
            "outage_alphas": list(OUTAGE_ALPHAS),
        },
        "inputs": input_manifest,
        "accepted_periods": len(periods),
        "rejected_periods": len(rejected),
        "paired_rows": len(data_rows),
        "dataset_summary": summary_rows,
        "bootstrap": bootstrap,
        "odometer_sensitivity_rows": len(sensitivity),
        "odometer_sensitivity_gate": sensitivity_gate,
        "constructed_cases": constructed,
        "conditional_deployment_claim": (
            "Protocol bounds assume authenticated, monotone, calibrated odometer readings; "
            "no receiver/odometer field certification was performed by this experiment."
        ),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "git": _git_metadata(),
            "runner_sha256": _sha256(Path(__file__)),
            "reference_sha256": _sha256(ROOT_DIR / "common/settlement_v6.py"),
        },
        "outputs": {
            "paired_rows": "paired_period_rows.csv",
            "dataset_summary": "dataset_summary.csv",
            "odometer_sensitivity": "odometer_sensitivity.csv",
            "formal_properties": "formal_properties.md",
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(DEFAULT_INPUTS))
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT_DIR / "experiments/waybill_m1/v1"
    )
    args = parser.parse_args()
    result = run(inputs=tuple(path.resolve() for path in args.inputs), output_dir=args.output_dir.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["hard_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
