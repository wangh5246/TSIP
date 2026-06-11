#!/usr/bin/env python3
"""Per-device histogram of surviving provable periods for the GeoLife g16/60s leg
at N=8/10/12. Analysis-only: reuses the same pipeline + window logic as
sweep_n_fixes (clean->rebase->segment->resample, non-overlapping N-windows gated on
span<=PERIOD_MAX_SEC and positive odometer). No circuit work.

Tests whether the per-N device counts reflect broad participation or are dominated
by a few high-yield devices.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.trajectory_preprocess import (  # noqa: E402
    CELL_SIZE_M,
    CITY_BBOX,
    PERIOD_MAX_SEC,
    REBASE_ANCHOR,
    TRIP_GAP_SEC,
    MAX_DT_SEC,
    DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M,
    build_local_tariff_table,
    build_resampled_fixes,
    choose_density_peak_block,
    clean_raw_points,
    rebase_points_to_2026,
    segment_native_trips,
)
from script.sweep_n_fixes import _build_runs, _iter_raw, _load_geometry  # noqa: E402

DATASET = "geolife"
CITY = "beijing"
GRID = 16
CADENCE = 60
N_VALUES = [8, 10, 12]


def surviving_periods(runs, n_fixes):
    """Return list of device_id, one per surviving (span_ok + positive_odo) window."""
    devices = []
    for rows in runs:
        for start in range(0, max(0, len(rows) - n_fixes + 1), n_fixes):
            chunk = rows[start : start + n_fixes]
            span = int(chunk[-1]["t_unix"]) - int(chunk[0]["t_unix"])
            if span > PERIOD_MAX_SEC:
                continue
            if int(chunk[-1]["odometer_reading_m"]) - int(chunk[0]["odometer_reading_m"]) <= 0:
                continue
            devices.append(str(chunk[0]["device_id"]))
    return devices


def main() -> int:
    geometry = _load_geometry(CITY, "medium", CELL_SIZE_M)
    raw, _ = clean_raw_points(DATASET, _iter_raw(DATASET), city_bbox=CITY_BBOX[CITY])
    rebased = rebase_points_to_2026(raw, anchor=REBASE_ANCHOR)
    native, _ = segment_native_trips(DATASET, rebased, gap_sec=TRIP_GAP_SEC)
    block = choose_density_peak_block(
        native or rebased,
        origin_lat=geometry.origin_lat,
        origin_lon=geometry.origin_lon,
        width=GRID,
        cell_size_m=CELL_SIZE_M,
        moving_only=True,
    )
    tariff = build_local_tariff_table(block, geometry, circuit_grid_w=100)
    fixes, _ = build_resampled_fixes(
        DATASET,
        native,
        cadence_sec=CADENCE,
        block=block,
        tariff=tariff,
        tier_vmax_mps=33,
        max_dt_sec=MAX_DT_SEC,
        outage_bridge_max_odo_m=DEFAULT_OUTAGE_BRIDGE_MAX_ODO_M,
    )
    runs = _build_runs(fixes)

    # Pre-committed rule (applied uniformly, identically, to every N; this is the
    # all_on / all-predicates-enabled arm, which is the UPPER BOUND for every ablation
    # arm — arms only shrink the per-device survival set):
    #   inverse-Simpson >= 5  AND heaviest-device share < 40%  -> qualifies
    #   inverse-Simpson 4-5                                     -> danger zone
    #   inverse-Simpson < 4                                     -> eliminate this N
    import statistics

    summary = []
    for n in N_VALUES:
        devs = surviving_periods(runs, n)
        hist = Counter(devs)
        total = len(devs)
        n_dev = len(hist)
        ordered = hist.most_common()
        counts = [c for _, c in ordered]
        top2 = sum(counts[:2])
        heaviest = counts[0] if counts else 0
        heaviest_share = heaviest / total if total else 0.0
        median_ppd = statistics.median(counts) if counts else 0.0
        # Effective number of devices (Hill number / inverse Simpson): 1 / sum(p_i^2)
        eff = (total * total) / sum(c * c for c in counts) if total else 0.0
        if eff >= 5 and heaviest_share < 0.40:
            verdict = "QUALIFIES"
        elif eff >= 4:
            verdict = "DANGER (4-5)"
        else:
            verdict = "ELIMINATE (<4)"
        summary.append((n, total, n_dev, eff, heaviest_share, median_ppd, verdict))
        print(f"\n===== N={n}  (g16 / {CADENCE}s, all_on) =====")
        print(f"total periods                  = {total}")
        print(f"raw contributing devices       = {n_dev}")
        print(f"effective #devices (1/Simpson) = {eff:.2f}")
        print(f"heaviest single-device share   = {heaviest}/{total}" + (f" ({100*heaviest_share:.0f}%)" if total else "") + ("  <-- RED FLAG >40%" if heaviest_share > 0.40 else ""))
        print(f"median periods/device          = {median_ppd:g}")
        print(f"top-2 device share             = {top2}/{total}" + (f" ({100*top2/total:.0f}%)" if total else ""))
        print(f"RULE VERDICT                   = {verdict}")
        print("per-device period counts (device_id: count):")
        for dev, c in ordered:
            print(f"  {dev:>8}: {c:>3}  {'#' * c}")

    print("\n" + "=" * 64)
    print(f"{'N':>3} {'periods':>8} {'raw_dev':>8} {'invSimpson':>11} {'heaviest%':>10} {'med_ppd':>8}  verdict")
    for n, total, n_dev, eff, hs, med, verdict in summary:
        print(f"{n:>3} {total:>8} {n_dev:>8} {eff:>11.2f} {100*hs:>9.0f}% {med:>8g}  {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
