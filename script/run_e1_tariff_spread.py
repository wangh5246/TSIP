"""E1 tariff-spread sweep: how much does zone-binding's economic value depend
on the tariff's progressivity?

The headline E1 gap (GeoLife no_zone_binding epsilon ~0.27 vs Rome ~0.006) is
partly driven by tariff spread, not the dataset: GeoLife's synthetic tariff has
a 5x rate spread, Rome's official working block only 1.2x. A reviewer will ask
whether 0.27 is an artifact of a steep synthetic tariff. This sweep answers it
directly: holding the SAME GeoLife trajectories and zone topology fixed, vary
only the rate spread and measure the no_zone_binding epsilon.

Expected finding (policy-level): zone-binding's marginal value grows with rate
spread — flatter tariffs need less cryptographic integrity.

Reuses the production solver (zone_binding_min_fee) and billing oracle
(compute_bill), so numbers are comparable to the authoritative E1 outputs.

Outputs: experiments/e1_tariff_spread/e1_tariff_spread.csv, receipt.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams, compute_bill, zone_binding_min_fee  # noqa: E402
from common.settlement import ReceiverFix, TariffTable  # noqa: E402

ABLATION = ROOT_DIR / "data" / "e1_mechanism_ablation"
N_FIXES = 25
BASE_RATE = 10  # cheapest zone; spread s sets the most expensive zone to s * BASE_RATE


def load_topology(dataset: str) -> tuple[TariffTable, list[int]]:
    """Load the dataset tariff and return (template tariff, sorted distinct rate tiers)."""

    raw = json.load(open(ABLATION / dataset / "tariff_block.json"))
    t = raw["tariff"]
    tariff = TariffTable(
        tariff_version=int(t["tariff_version"]),
        grid_w=int(t["grid_w"]),
        cell_zones={int(k): int(v) for k, v in t["cell_zones"].items()},
        zone_rates_cents_per_m={int(k): int(v) for k, v in t["zone_rates_cents_per_m"].items()},
    )
    tiers = sorted(set(tariff.zone_rates_cents_per_m.values()))
    return tariff, tiers


def respread_tariff(template: TariffTable, spread: float) -> TariffTable:
    """Rebuild the tariff with the same zone topology but rate spread = `spread`.

    Distinct rate tiers r0<...<rk are mapped linearly onto [BASE_RATE, spread*BASE_RATE],
    preserving zone ordering. With one tier the tariff is flat (spread ignored).
    """

    rates = template.zone_rates_cents_per_m
    tiers = sorted(set(rates.values()))
    if len(tiers) == 1:
        new_for_tier = {tiers[0]: BASE_RATE}
    else:
        lo, hi = tiers[0], tiers[-1]
        new_for_tier = {
            r: int(round(BASE_RATE * (1.0 + (spread - 1.0) * (r - lo) / (hi - lo)))) for r in tiers
        }
    new_rates = {zone: new_for_tier[rate] for zone, rate in rates.items()}
    return TariffTable(
        tariff_version=template.tariff_version,
        grid_w=template.grid_w,
        cell_zones=dict(template.cell_zones),
        zone_rates_cents_per_m=new_rates,
    )


def periods_from_record(record: dict, max_dt_sec: int) -> list[list[ReceiverFix]]:
    fixes = [ReceiverFix.from_dict(row) for row in record.get("fixes", [])]
    periods: list[list[ReceiverFix]] = []
    current: list[ReceiverFix] = []
    for fix in fixes:
        if current:
            dt = int(fix.auth_gnss_time) - int(current[-1].auth_gnss_time)
            if dt <= 0 or dt > max_dt_sec:
                current = []
        current.append(fix)
        if len(current) == N_FIXES:
            periods.append(list(current))
            current = current[-1:]
    return periods


def main() -> None:
    parser = argparse.ArgumentParser(description="E1 zone-binding epsilon vs tariff spread.")
    parser.add_argument("--dataset", default="geolife")
    parser.add_argument("--input", default=str(ABLATION / "geolife" / "geolife_medium_identity.jsonl"))
    parser.add_argument("--spreads", default="1.2,2,3,5,10")
    parser.add_argument("--max-users", type=int, default=50)
    parser.add_argument("--periods-per-user", type=int, default=1)
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "experiments" / "e1_tariff_spread"))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    template, tiers = load_topology(args.dataset)
    params = HarnessParams(cadence_sec=60, max_dt_sec=600, tier_vmax_mps=33, cell_size_m=100)
    spreads = [float(s) for s in args.spreads.split(",")]

    # Collect periods once.
    all_periods: list[list[ReceiverFix]] = []
    with open(args.input) as fh:
        emitted = 0
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            for period in periods_from_record(record, params.max_dt_sec)[: args.periods_per_user]:
                all_periods.append(period)
            emitted += 1
            if args.max_users > 0 and emitted >= args.max_users:
                break

    rows: list[dict] = []
    for spread in spreads:
        tariff = respread_tariff(template, spread)
        savings: list[float] = []
        for period in all_periods:
            honest = int(compute_bill(period, tariff, params)["total_fee_cents"])
            if honest <= 0:
                continue
            result = zone_binding_min_fee(period, tariff, params)
            savings.append(result.savings_ratio)
        if not savings:
            continue
        s = sorted(savings)
        rows.append(
            {
                "dataset": args.dataset,
                "tariff_spread": spread,
                "rates": "|".join(str(v) for v in sorted(set(tariff.zone_rates_cents_per_m.values()))),
                "n_periods": len(savings),
                "mean_savings": round(statistics.fmean(savings), 6),
                "median_savings": round(statistics.median(s), 6),
                "p95_savings": round(s[max(0, int(0.95 * len(s)) - 1)], 6),
            }
        )

    with open(out_dir / "e1_tariff_spread.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    receipt = {
        "experiment": "E1 zone-binding epsilon vs tariff spread",
        "dataset": args.dataset,
        "input": str(Path(args.input).relative_to(ROOT_DIR)),
        "base_rate_cents_per_m": BASE_RATE,
        "original_rate_tiers": tiers,
        "spreads": spreads,
        "n_periods": len(all_periods),
        "branch": "no_zone_binding (zone_binding_min_fee)",
        "note": "same trajectories and zone topology across spreads; only rate scale varies",
    }
    json.dump(receipt, open(out_dir / "receipt.json", "w"), indent=1, sort_keys=True)
    print(f"wrote {len(rows)} spread rows to {out_dir}")
    for r in rows:
        print(f"  spread={r['tariff_spread']:>5} rates={r['rates']:10s} median eps={r['median_savings']:.4f} p95={r['p95_savings']:.4f}")


if __name__ == "__main__":
    main()
