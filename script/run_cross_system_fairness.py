"""Cross-system symmetric evaluation: same adversary, same metric, same data.

Closes three asymmetries in the Baseline R comparison so that both systems
face the SAME experiment under the SAME conditions:

A) Same attack, both systems. The segment-omission strategies used against
   spot-check (rational_topfee / random, omit 0.1/0.2) are replayed against
   TSIP billing on the same periods with the same seed: an omitted interval
   becomes an authenticated-fix gap and is billed by the protocol's fallback
   rule (ceil(dt * vmax) * max_zone_rate, the E2 monotone-degradation path).
   Expected: negative savings — the omitter PAYS MORE under TSIP, while the
   same strategy against partial-coverage spot-check yields undetected gains.

B) Same cost discipline. Baseline R's client cost ("commitments only,
   modeled as zero") is replaced with a measured number: per-period Poseidon
   fix-commitment chain generation in the same reference stack that produced
   TSIP's witness numbers. Labeled reference-implementation; native hashes
   are faster, which keeps the comparison generous to the baseline.

C) Same privacy metric. Spot-check leakage is re-expressed as an empirical
   anonymity set (the E5 metric): the observer sees the target period's
   camera-covered segments (no timestamps — generous), and the anonymity set
   counts pool periods whose segment set contains that observation.

Outputs: experiments/e4_e5_ruc/cross_system_omission_vs_tsip.csv,
cross_system_anonymity.csv, cross_system_receipt.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import compute_fix_commitment, fee_for_interval_values, poseidon_chain  # noqa: E402
from script.run_baseline_r_simulator import camera_sets, omitted_segments, period_segments, segment_key  # noqa: E402
from script.run_e4_e5_ruc_experiments import DEFAULT_INPUTS, PeriodRecord, load_all_records  # noqa: E402

E4_DIR = ROOT_DIR / "experiments" / "e4_e5_ruc"
OMIT_FRACTIONS = (0.10, 0.20)
OMIT_POLICIES = ("rational_topfee", "random")


def tsip_bill_with_omission(record: PeriodRecord, omitted: set[tuple[int, int]]) -> dict[str, int | bool]:
    """Bill the period under TSIP when the omitter withholds fixes on `omitted` segments.

    Withheld fixes turn the interval into an authenticated-fix gap: the
    protocol bills it with the fallback rule on the same dt. Consecutive
    omitted intervals are merged into one gap (their dts add up); a merged
    gap longer than max_dt cannot be proven exactly and must go through the
    outage declaration path — same fallback arithmetic, flagged in output.
    """

    tariff, params = record.tariff, record.params
    honest = 0
    omitter = 0
    gap_dt = 0
    needs_outage_declaration = False

    def flush_gap() -> int:
        nonlocal gap_dt, needs_outage_declaration
        if gap_dt <= 0:
            return 0
        if gap_dt > params.max_dt_sec:
            needs_outage_declaration = True
        fee = int(math.ceil(gap_dt * params.tier_vmax_mps)) * tariff.max_zone_rate_cents_per_m
        gap_dt = 0
        return fee

    for prev, curr in zip(record.fixes, record.fixes[1:]):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        a = tariff.cell_index(prev.cell_x, prev.cell_y)
        b = tariff.cell_index(curr.cell_x, curr.cell_y)
        exact = int(
            fee_for_interval_values(
                dt_sec=dt,
                odo_delta_m=int(curr.odometer_reading_m) - int(prev.odometer_reading_m),
                cell_idx=a,
                tariff=tariff,
                cadence_sec=params.cadence_sec,
                tier_vmax_mps=params.tier_vmax_mps,
                max_dt_sec=params.max_dt_sec,
            )["fee_cents"]
        )
        honest += exact
        if a != b and segment_key(a, b) in omitted:
            gap_dt += dt
        else:
            omitter += flush_gap()
            omitter += exact
    omitter += flush_gap()
    return {
        "honest_fee_cents": honest,
        "omitter_fee_cents": omitter,
        "needs_outage_declaration": needs_outage_declaration,
    }


def commitment_microbench_ms(record: PeriodRecord, runs: int = 20) -> float:
    """Measured per-period cost of the baseline OBU's commitment generation."""

    t0 = time.perf_counter()
    for _ in range(int(runs)):
        poseidon_chain([compute_fix_commitment(fix) for fix in record.fixes])
    return (time.perf_counter() - t0) * 1000.0 / int(runs)


def spotcheck_anonymity(
    per_period: list[tuple[PeriodRecord, list[tuple[tuple[int, int], int]]]],
    cams: frozenset[tuple[int, int]],
) -> list[int]:
    """E5-metric anonymity sets under the camera observer's view (no timestamps; generous)."""

    seg_sets = [frozenset(key for key, _fee in segs) for _record, segs in per_period]
    sizes = []
    for target in seg_sets:
        observed = target & cams
        sizes.append(sum(1 for other in seg_sets if observed <= other))
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the cross-system symmetric fairness evaluation.")
    parser.add_argument("--out-dir", default=str(E4_DIR))
    parser.add_argument("--seed", type=int, default=20260611)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(int(args.seed))

    records_by_dataset = load_all_records(DEFAULT_INPUTS)
    omission_rows: list[dict] = []
    anonymity_rows: list[dict] = []
    bench_ms: dict[str, float] = {}

    for dataset, records in sorted(records_by_dataset.items()):
        per_period = [(record, period_segments(record)) for record in records]
        per_period = [(record, segs) for record, segs in per_period if segs]
        if not per_period:
            continue
        traffic: Counter = Counter()
        fee_weight: Counter = Counter()
        for _record, segs in per_period:
            traffic.update(key for key, _fee in segs)
            for key, fee in segs:
                fee_weight[key] += fee
        universe = sorted(traffic)
        bench_ms[dataset] = round(commitment_microbench_ms(per_period[0][0]), 3)

        # A) the spot-check omission strategies, replayed against TSIP billing.
        for omit_policy in OMIT_POLICIES:
            for omit in OMIT_FRACTIONS:
                savings: list[float] = []
                outage_declarations = 0
                for record, segs in per_period:
                    omitted = set(omitted_segments(segs, omit, omit_policy, rng))
                    bill = tsip_bill_with_omission(record, omitted)
                    if int(bill["honest_fee_cents"]) <= 0:
                        continue
                    savings.append(
                        (int(bill["honest_fee_cents"]) - int(bill["omitter_fee_cents"])) / int(bill["honest_fee_cents"])
                    )
                    outage_declarations += int(bool(bill["needs_outage_declaration"]))
                omission_rows.append(
                    {
                        "dataset": dataset,
                        "omit_policy": omit_policy,
                        "omit_fraction": omit,
                        "n_periods": len(savings),
                        "tsip_mean_savings_ratio": round(statistics.fmean(savings), 6) if savings else "",
                        "tsip_median_savings_ratio": round(statistics.median(savings), 6) if savings else "",
                        "tsip_max_savings_ratio": round(max(savings), 6) if savings else "",
                        "share_needing_outage_declaration": round(outage_declarations / len(savings), 6)
                        if savings
                        else "",
                        "spotcheck_reference": "baseline_r_detection_empirical.csv (same strategies, same seed)",
                    }
                )

        # C) spot-check leakage in the E5 anonymity-set metric.
        for cameras in (50, len(universe)):
            cams = camera_sets(
                universe, traffic, fee_weight, cameras, "traffic_weighted_generous", rng, 1
            )[0]
            sizes = sorted(spotcheck_anonymity(per_period, cams))
            anonymity_rows.append(
                {
                    "dataset": dataset,
                    "observer": "spot_check_cameras",
                    "cameras": min(cameras, len(universe)),
                    "median_anonymity_set": statistics.median(sizes),
                    "p95_anonymity_set": sizes[max(0, int(0.95 * len(sizes)) - 1)],
                    "n_periods": len(sizes),
                    "metric_note": "segment-only observation, no timestamps (generous); TSIP rows in e5_empirical_anonymity.csv",
                }
            )

    write_csv(out_dir / "cross_system_omission_vs_tsip.csv", omission_rows)
    write_csv(out_dir / "cross_system_anonymity.csv", anonymity_rows)
    receipt = {
        "experiment": "cross-system symmetric fairness evaluation",
        "seed": int(args.seed),
        "same_conditions": {
            "data": "identical period records and tariffs as Baseline R simulator (DEFAULT_INPUTS)",
            "adversary": "identical omission strategies and fractions, same RNG seed discipline",
            "billing_oracle": "fee_for_interval_values + protocol fallback rule",
            "privacy_metric": "E5 empirical anonymity set on both systems",
        },
        "baseline_client_commitment_ms_reference_impl": bench_ms,
        "note_on_B": (
            "Python reference implementation; native Poseidon is orders faster, "
            "which is generous to the baseline. Either way it is far below the "
            "TSIP prove time it replaces in the head-to-head table."
        ),
        "outputs": ["cross_system_omission_vs_tsip.csv", "cross_system_anonymity.csv"],
    }
    json.dump(receipt, open(out_dir / "cross_system_receipt.json", "w"), indent=1, sort_keys=True)
    print(f"wrote {len(omission_rows)} omission rows, {len(anonymity_rows)} anonymity rows; bench={bench_ms}")


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
