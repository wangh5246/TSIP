"""E5 statement-bucketing mitigation, measured.

The proof-only statement leaks an EXACT per-period (fee, distance, fallback,
interval) tuple; on Rome the exact-match anonymity set is small. A cheap
mitigation reports the fee and distance rounded to a coarse grid, settling the
exact remainder at month end. This sweep measures how anonymity grows with grid
width, turning a discussion claim into a measured two-level curve.

Grid width is expressed as a fraction of the dataset's median fee/distance so
it is interpretable across datasets. `exact` (bucket_pct = 0) is the true
minimal-disclosure leak; increasing the grid coarsens fee and distance jointly.

Reuses the production E5 record loader so the pool matches the authoritative
E5 numbers.

Outputs: experiments/e4_e5_ruc/e5_statement_bucketing.csv.
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

from script.run_e4_e5_ruc_experiments import DEFAULT_INPUTS, load_all_records  # noqa: E402

E4_DIR = ROOT_DIR / "experiments" / "e4_e5_ruc"
BUCKET_PCTS = (0.0, 0.02, 0.05, 0.10, 0.25, 0.50)


def anonymity_sets(records, bucket_pct: float) -> list[int]:
    fees = [int(r.fee_cents) for r in records]
    dists = [int(r.distance_m) for r in records]
    med_fee = max(1, int(statistics.median(fees)))
    med_dist = max(1, int(statistics.median(dists)))
    feats = [
        {
            "fee": int(r.fee_cents),
            "distance": int(r.distance_m),
            "fallback": int(r.fallback_intervals),
            "intervals": int(r.n_intervals),
        }
        for r in records
    ]

    def key(f):
        if bucket_pct <= 0:
            return (f["fee"], f["distance"], f["fallback"], f["intervals"])
        gf = max(1, int(bucket_pct * med_fee))
        gd = max(1, int(bucket_pct * med_dist))
        return (round(f["fee"] / gf), round(f["distance"] / gd), f["fallback"], f["intervals"])

    keys = [key(f) for f in feats]
    sizes = [keys.count(k) for k in keys]
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description="E5 statement-bucketing anonymity sweep.")
    parser.add_argument("--out-dir", default=str(E4_DIR))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records_by_dataset = load_all_records(DEFAULT_INPUTS)
    rows: list[dict] = []
    for dataset, records in sorted(records_by_dataset.items()):
        if len(records) < 2:
            continue
        for pct in BUCKET_PCTS:
            sizes = sorted(anonymity_sets(records, pct))
            rows.append(
                {
                    "dataset": dataset,
                    "bucket_pct_of_median": pct,
                    "label": "exact" if pct == 0 else f"{int(pct*100)}%",
                    "n_periods": len(sizes),
                    "median_anonymity_set": statistics.median(sizes),
                    "p95_anonymity_set": sizes[max(0, int(0.95 * len(sizes)) - 1)],
                    "min_anonymity_set": sizes[0],
                }
            )

    with open(out_dir / "e5_statement_bucketing.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {out_dir / 'e5_statement_bucketing.csv'}")
    for r in rows:
        if r["dataset"] in ("rome", "geolife"):
            print(f"  {r['dataset']:8s} grid={r['label']:>5} median={r['median_anonymity_set']:>5} p95={r['p95_anonymity_set']:>5} min={r['min_anonymity_set']}")


if __name__ == "__main__":
    main()
