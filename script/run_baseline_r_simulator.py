"""Baseline R: reconstructed spot-check simulator on real period trajectories.

The closed-form E4 model (P = 1 - exp(-c f S)) assumes independent coverage.
This simulator drops that assumption and measures spot-check enforcement
empirically on the actual Tier-1 periods:

- Universe: undirected observed tariff-grid segments (same definition as
  ``road_proxy_stats`` in run_e4_e5_ruc_experiments; no map matching, per the
  Tier-1 pipeline discipline — the drivable-graph universe stays closed-form).
- Camera placement: ``uniform_random`` Monte Carlo draws, and a
  ``traffic_weighted_generous`` deterministic policy that puts cameras on the
  most-traversed segments first (favoring the baseline).
- Adversary: omits a fraction of its traversed segments; ``rational_topfee``
  hides the most expensive ones (per-edge fee from fee_for_interval_values,
  the billing single source of truth), ``random`` hides uniformly.
- Detection: a period is caught iff any omitted segment carries a camera.
- Privacy: for honest drivers the same cameras observe route segments, which
  yields the spot-check row of the E5 leakage spectrum (policy-protected GPS
  = full route visible; TSIP proof-only = zero route segments visible).

Outputs land in experiments/e4_e5_ruc/: baseline_r_detection_empirical.csv,
baseline_r_privacy_leakage.csv, e5_leakage_spectrum.csv,
fig_baseline_r_empirical_detection.png, baseline_r_receipt.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import fee_for_interval_values  # noqa: E402
from script.run_e4_e5_ruc_experiments import DEFAULT_INPUTS, PeriodRecord, load_all_records  # noqa: E402

E4_DIR = ROOT_DIR / "experiments" / "e4_e5_ruc"
CAMERA_BUDGET_GRID = (1, 2, 5, 10, 20, 50, 100, 200, 500)
OMIT_FRACTIONS = (0.10, 0.20)
OMIT_POLICIES = ("rational_topfee", "random")
PLACEMENTS = ("uniform_random", "traffic_weighted_generous")


def segment_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def period_segments(record: PeriodRecord) -> list[tuple[tuple[int, int], int]]:
    """Distinct traversed segments of one period with their billed fee (movement edges only)."""

    tariff, params = record.tariff, record.params
    fees: dict[tuple[int, int], int] = {}
    for prev, curr in zip(record.fixes, record.fixes[1:]):
        a = tariff.cell_index(prev.cell_x, prev.cell_y)
        b = tariff.cell_index(curr.cell_x, curr.cell_y)
        if a == b:
            continue
        interval = fee_for_interval_values(
            dt_sec=int(curr.auth_gnss_time) - int(prev.auth_gnss_time),
            odo_delta_m=int(curr.odometer_reading_m) - int(prev.odometer_reading_m),
            cell_idx=a,
            tariff=tariff,
            cadence_sec=params.cadence_sec,
            tier_vmax_mps=params.tier_vmax_mps,
            max_dt_sec=params.max_dt_sec,
        )
        key = segment_key(a, b)
        fees[key] = fees.get(key, 0) + int(interval["fee_cents"])
    return sorted(fees.items())


def omitted_segments(
    segments: list[tuple[tuple[int, int], int]],
    omit_fraction: float,
    policy: str,
    rng: random.Random,
) -> list[tuple[int, int]]:
    if not segments:
        return []
    k = max(1, math.ceil(float(omit_fraction) * len(segments)))
    if policy == "rational_topfee":
        ranked = sorted(segments, key=lambda item: (-item[1], item[0]))
        return [key for key, _fee in ranked[:k]]
    if policy == "random":
        return [key for key, _fee in rng.sample(segments, k)]
    raise ValueError(policy)


def camera_sets(
    universe: list[tuple[int, int]],
    traffic: Counter,
    cameras: int,
    placement: str,
    rng: random.Random,
    draws: int,
) -> list[frozenset[tuple[int, int]]]:
    cams = min(int(cameras), len(universe))
    if placement == "traffic_weighted_generous":
        ranked = sorted(universe, key=lambda key: (-traffic[key], key))
        return [frozenset(ranked[:cams])]
    if placement == "uniform_random":
        return [frozenset(rng.sample(universe, cams)) for _ in range(int(draws))]
    raise ValueError(placement)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Baseline R reconstructed spot-check simulator.")
    parser.add_argument("--out-dir", default=str(E4_DIR))
    parser.add_argument("--draws", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260611)
    parser.add_argument("--p-detect-target", type=float, default=0.95)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(args.seed))

    records_by_dataset = load_all_records(DEFAULT_INPUTS)
    detection_rows: list[dict] = []
    leakage_rows: list[dict] = []
    spectrum_rows: list[dict] = []
    receipt_datasets: dict[str, dict] = {}

    for dataset, records in sorted(records_by_dataset.items()):
        per_period = [(record, period_segments(record)) for record in records]
        per_period = [(record, segs) for record, segs in per_period if segs]
        if not per_period:
            receipt_datasets[dataset] = {"skipped": "no movement segments"}
            continue
        traffic: Counter = Counter()
        for _record, segs in per_period:
            traffic.update(key for key, _fee in segs)
        universe = sorted(traffic)
        budgets = sorted({c for c in CAMERA_BUDGET_GRID if c <= len(universe)} | {len(universe)})
        receipt_datasets[dataset] = {
            "periods": len(per_period),
            "universe_segments": len(universe),
            "camera_budgets": budgets,
        }

        equal_detection: dict[str, int | None] = {}
        for placement in PLACEMENTS:
            for cameras in budgets:
                sets = camera_sets(universe, traffic, cameras, placement, rng, int(args.draws))
                visibility: list[float] = []
                observed_counts: list[int] = []
                for cams in sets:
                    for _record, segs in per_period:
                        seen = sum(1 for key, _fee in segs if key in cams)
                        visibility.append(seen / len(segs))
                        observed_counts.append(seen)
                leakage_rows.append(
                    {
                        "dataset": dataset,
                        "placement": placement,
                        "cameras": cameras,
                        "honest_route_visibility_mean": round(statistics.fmean(visibility), 6),
                        "honest_route_visibility_median": round(statistics.median(visibility), 6),
                        "observed_segments_per_period_mean": round(statistics.fmean(observed_counts), 4),
                        "n_periods": len(per_period),
                        "draws": len(sets),
                    }
                )
                for omit_policy in OMIT_POLICIES:
                    for omit in OMIT_FRACTIONS:
                        caught = 0
                        trials = 0
                        for cams in sets:
                            for _record, segs in per_period:
                                omitted = omitted_segments(segs, omit, omit_policy, rng)
                                trials += 1
                                if any(key in cams for key in omitted):
                                    caught += 1
                        p_emp = caught / trials if trials else 0.0
                        detection_rows.append(
                            {
                                "dataset": dataset,
                                "placement": placement,
                                "omit_policy": omit_policy,
                                "omit_fraction": omit,
                                "cameras": cameras,
                                "empirical_p_detect": round(p_emp, 6),
                                "trials": trials,
                                "tsip_p_detect_proof_violating": 1.0,
                                "tsip_cameras": 0,
                            }
                        )
                        if (
                            omit_policy == "rational_topfee"
                            and omit == 0.20
                            and placement == "traffic_weighted_generous"
                            and equal_detection.get(placement) is None
                            and p_emp >= float(args.p_detect_target)
                        ):
                            equal_detection[placement] = cameras

        # E5 leakage spectrum at the spot-check equal-detection work point.
        workpoint = equal_detection.get("traffic_weighted_generous")
        spectrum_cams = workpoint if workpoint is not None else len(universe)
        vis_row = next(
            row
            for row in leakage_rows
            if row["dataset"] == dataset
            and row["placement"] == "traffic_weighted_generous"
            and row["cameras"] == spectrum_cams
        )
        spectrum_rows.extend(
            [
                {
                    "dataset": dataset,
                    "system": "policy_protected_gps_collection",
                    "route_visibility_to_charger": 1.0,
                    "infrastructure": "0 roadside; full trajectory upload",
                    "note": "privacy by policy/access control only",
                },
                {
                    "dataset": dataset,
                    "system": "spot_check_lineage_baseline_r",
                    "route_visibility_to_charger": vis_row["honest_route_visibility_mean"],
                    "infrastructure": f"{spectrum_cams} cameras (traffic-weighted; "
                    + (
                        "empirical P>=0.95 @ rational omit 0.20"
                        if workpoint is not None
                        else "full universe, target unreachable"
                    )
                    + ")",
                    "note": "honest drivers observed at every covered segment",
                },
                {
                    "dataset": dataset,
                    "system": "tsip_ruc_proof_only",
                    "route_visibility_to_charger": 0.0,
                    "infrastructure": "0 roadside",
                    "note": "charger sees leakage profile L only; anonymity sets in e5_empirical_anonymity.csv",
                },
            ]
        )

    write_csv(out_dir / "baseline_r_detection_empirical.csv", detection_rows)
    write_csv(out_dir / "baseline_r_privacy_leakage.csv", leakage_rows)
    write_csv(out_dir / "e5_leakage_spectrum.csv", spectrum_rows)
    plot_detection(detection_rows, out_dir / "fig_baseline_r_empirical_detection.png")
    receipt = {
        "experiment": "Baseline R reconstructed spot-check simulator",
        "seed": int(args.seed),
        "draws_uniform_random": int(args.draws),
        "omit_policies": list(OMIT_POLICIES),
        "placements": list(PLACEMENTS),
        "universe": "observed undirected tariff-grid segments (Tier-1 discipline: no map matching)",
        "edge_fee_source": "fee_for_interval_values (billing single source of truth)",
        "datasets": receipt_datasets,
        "outputs": [
            "baseline_r_detection_empirical.csv",
            "baseline_r_privacy_leakage.csv",
            "e5_leakage_spectrum.csv",
            "fig_baseline_r_empirical_detection.png",
        ],
    }
    json.dump(receipt, open(out_dir / "baseline_r_receipt.json", "w"), indent=1, sort_keys=True)
    print(
        f"wrote {len(detection_rows)} detection rows, {len(leakage_rows)} leakage rows, "
        f"{len(spectrum_rows)} spectrum rows to {out_dir}"
    )


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_detection(rows: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    datasets = sorted({r["dataset"] for r in rows})
    fig, axes = plt.subplots(1, len(datasets), figsize=(4.0 * len(datasets), 3.8), sharey=True, squeeze=False)
    for ax, dataset in zip(axes[0], datasets):
        for placement, style in (("uniform_random", "-o"), ("traffic_weighted_generous", "-s")):
            sub = [
                r
                for r in rows
                if r["dataset"] == dataset
                and r["placement"] == placement
                and r["omit_policy"] == "rational_topfee"
                and r["omit_fraction"] == 0.20
            ]
            sub.sort(key=lambda r: r["cameras"])
            ax.plot([r["cameras"] for r in sub], [r["empirical_p_detect"] for r in sub], style, ms=3, label=placement)
        ax.axhline(1.0, color="black", ls="--", lw=1)
        ax.set_xscale("symlog")
        ax.set_title(dataset)
        ax.set_xlabel("cameras")
        ax.grid(alpha=0.3)
    axes[0][0].set_ylabel("empirical P(detect), rational omit 0.20")
    axes[0][0].legend(fontsize=7)
    fig.suptitle("Baseline R simulator: empirical spot-check detection (TSIP dashed at 1.0, 0 cameras)")
    fig.tight_layout()
    fig.savefig(path, dpi=160)


if __name__ == "__main__":
    main()
