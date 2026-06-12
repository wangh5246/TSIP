"""E5 x dispute arbitration: how much anonymity does each opened interval cost?

The selective-disclosure dispute protocol (common/dispute.py) opens one
interval at level 2: the arbiter sees the two bounding fixes' cells at their
sequence positions. This sweep quantifies the privacy price of k such
openings: starting from the proof-only statement observer (the E5 tolerance
profile: fee/distance within 10%, exact fallback and interval counts), each
opened interval adds a "same cells at the same sequence positions" constraint,
and the anonymity set shrinks.

Opened intervals are chosen as the period's highest-fee intervals — the ones a
charger would actually dispute. k = 0 reproduces the E5 baseline.

Outputs: experiments/e4_e5_ruc/e5_dispute_leakage.csv.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import fee_for_interval_values  # noqa: E402
from script.run_e4_e5_ruc_experiments import DEFAULT_INPUTS, PeriodRecord, load_all_records  # noqa: E402

E4_DIR = ROOT_DIR / "experiments" / "e4_e5_ruc"
K_OPENINGS = (0, 1, 2, 4, 8)


def period_profile(record: PeriodRecord) -> dict:
    tariff, params = record.tariff, record.params
    cells = [tariff.cell_index(f.cell_x, f.cell_y) for f in record.fixes]
    interval_fees: list[tuple[int, int]] = []  # (interval index, fee)
    for i, (prev, curr) in enumerate(zip(record.fixes, record.fixes[1:])):
        fee = int(
            fee_for_interval_values(
                dt_sec=int(curr.auth_gnss_time) - int(prev.auth_gnss_time),
                odo_delta_m=int(curr.odometer_reading_m) - int(prev.odometer_reading_m),
                cell_idx=cells[i],
                tariff=tariff,
                cadence_sec=params.cadence_sec,
                tier_vmax_mps=params.tier_vmax_mps,
                max_dt_sec=params.max_dt_sec,
            )["fee_cents"]
        )
        interval_fees.append((i, fee))
    disputed = [i for i, _fee in sorted(interval_fees, key=lambda x: (-x[1], x[0]))]
    return {
        "fee": int(record.fee_cents),
        "distance": int(record.distance_m),
        "fallback": int(record.fallback_intervals),
        "intervals": int(record.n_intervals),
        "cells": cells,
        "disputed_order": disputed,
    }


def statement_match(target: dict, other: dict) -> bool:
    distance_tol = max(100, int(round(0.10 * max(1, target["distance"]))))
    fee_tol = max(500, int(round(0.10 * max(1, target["fee"]))))
    return (
        abs(other["distance"] - target["distance"]) <= distance_tol
        and abs(other["fee"] - target["fee"]) <= fee_tol
        and other["fallback"] == target["fallback"]
        and other["intervals"] == target["intervals"]
    )


def opening_match(target: dict, other: dict, k: int) -> bool:
    """Does `other` stay consistent after k level-2 openings of `target`?"""

    for idx in target["disputed_order"][:k]:
        if idx + 1 >= len(other["cells"]):
            return False
        if other["cells"][idx] != target["cells"][idx] or other["cells"][idx + 1] != target["cells"][idx + 1]:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Anonymity shrink per dispute opening.")
    parser.add_argument("--out-dir", default=str(E4_DIR))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records_by_dataset = load_all_records(DEFAULT_INPUTS)
    rows: list[dict] = []
    for dataset, records in sorted(records_by_dataset.items()):
        if len(records) < 2:
            continue
        profiles = [period_profile(r) for r in records]
        for k in K_OPENINGS:
            sizes = []
            for target in profiles:
                count = sum(
                    1
                    for other in profiles
                    if statement_match(target, other) and opening_match(target, other, k)
                )
                sizes.append(count)
            sizes.sort()
            rows.append(
                {
                    "dataset": dataset,
                    "openings_k": k,
                    "n_periods": len(sizes),
                    "median_anonymity_set": statistics.median(sizes),
                    "p95_anonymity_set": sizes[max(0, int(0.95 * len(sizes)) - 1)],
                    "share_fully_identified": round(sum(1 for s in sizes if s == 1) / len(sizes), 4),
                }
            )

    with open(out_dir / "e5_dispute_leakage.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out_dir / 'e5_dispute_leakage.csv'}")
    for r in rows:
        if r["dataset"] == "rome":
            print(
                f"  rome k={r['openings_k']} median={r['median_anonymity_set']} "
                f"p95={r['p95_anonymity_set']} fully_identified={r['share_fully_identified']:.0%}"
            )


if __name__ == "__main__":
    main()
