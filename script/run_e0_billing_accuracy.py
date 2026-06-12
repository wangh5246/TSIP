"""E0: honest-billing accuracy vs continuous-GPS truth.

Every other experiment asks "how much can an adversary save". E0 answers the
question a transport reviewer asks first: how far is the HONEST bill from the
fee implied by the full-resolution trajectory?

The protocol bills each cadence interval at the zone of its starting fix, over
the odometer distance of the whole interval. The fine-grained reference walks
every raw GPS step and bills it at the zone of that step's own cell. Both use
the same cumulative-haversine distance, so the relative difference isolates
exactly the cell-quantization + single-endpoint attribution error that cadence
downsampling introduces — no adversary, no fallback.

    relative_error = (coarse_protocol_fee - fine_reference_fee) / fine_reference_fee

Reuses the production projection, tariff block, and raw-point iterators so the
coarse bill matches what the charger would actually accept. T-Drive is skipped
(no local raw trajectory file; its single period is not an E0 anchor).

Outputs: experiments/e0_billing_accuracy/e0_billing_accuracy.csv,
e0_period_rows.csv, receipt.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import TariffTable  # noqa: E402
from common.trajectory_preprocess import (  # noqa: E402
    TariffBlock,
    haversine_m,
    iter_geolife_driving_trips,
    iter_porto_trips,
    iter_rome_trips,
    project_xy_m,
    select_real_points_by_cadence,
)

# Rome: real official tariff (zone-homogeneous along trajectories — exact).
# GeoLife: anchor recovered from the builtin Beijing centred grid (cell_zones
# reproduce the archive byte-for-byte), 3-tier tariff over 10,000 cells — the
# genuine multi-zone case. Porto: robustness leg, streamed per trip.
DATASET_DIR = ROOT_DIR / "dataset"
CADENCE = {"rome": 60, "porto": 60, "geolife": 60}
ABLATION = ROOT_DIR / "data" / "e1_mechanism_ablation"


class CenteredGrid:
    """GeoLife's tariff geometry: a grid_w x grid_w grid centred on the city
    origin, cell = floor((x_m + half) / cell_size). Recovered from
    tariff_at_granularity('beijing', 'medium', grid_w=100, cell_size_m=100),
    whose cell_zones reproduce the archived tariff byte-for-byte."""

    def __init__(self, origin_lat: float, origin_lon: float, grid_w: int, cell_size_m: int):
        self.origin_lat = float(origin_lat)
        self.origin_lon = float(origin_lon)
        self.grid_w = int(grid_w)
        self.cell_size_m = int(cell_size_m)
        self.half_m = self.grid_w * self.cell_size_m / 2.0

    def cell_of(self, x_m: float, y_m: float):
        cx = math.floor((x_m + self.half_m) / self.cell_size_m)
        cy = math.floor((y_m + self.half_m) / self.cell_size_m)
        if 0 <= cx < self.grid_w and 0 <= cy < self.grid_w:
            return cx, cy
        return None


def load_block_and_tariff(dataset: str):
    raw = json.load(open(ABLATION / dataset / "tariff_block.json"))
    if "block" not in raw:
        # GeoLife: centred-grid geometry recovered from the builtin city anchor.
        from common.osm_vectors import tariff_at_granularity

        t = raw["tariff"]
        g = tariff_at_granularity("beijing", "medium", grid_w=int(t["grid_w"]), cell_size_m=100)
        tariff = TariffTable(
            tariff_version=int(t["tariff_version"]),
            grid_w=int(t["grid_w"]),
            cell_zones={int(k): int(v) for k, v in t["cell_zones"].items()},
            zone_rates_cents_per_m={int(k): int(v) for k, v in t["zone_rates_cents_per_m"].items()},
        )
        return CenteredGrid(g.origin_lat, g.origin_lon, int(t["grid_w"]), 100), tariff
    b = raw["block"]
    block = TariffBlock(
        origin_lat=float(b["origin_lat"]),
        origin_lon=float(b["origin_lon"]),
        global_cell_x_min=int(b["global_cell_x_min"]),
        global_cell_y_min=int(b["global_cell_y_min"]),
        width=int(b["width"]),
        cell_size_m=int(b["cell_size_m"]),
    )
    t = raw["tariff"]
    tariff = TariffTable(
        tariff_version=int(t["tariff_version"]),
        grid_w=int(t["grid_w"]),
        cell_zones={int(k): int(v) for k, v in t["cell_zones"].items()},
        zone_rates_cents_per_m={int(k): int(v) for k, v in t["zone_rates_cents_per_m"].items()},
    )
    return block, tariff


def rate_at(block, tariff: TariffTable, lat: float, lon: float) -> int | None:
    x_m, y_m = project_xy_m(lat, lon, block.origin_lat, block.origin_lon)
    if isinstance(block, CenteredGrid):
        cell = block.cell_of(x_m, y_m)
        if cell is None:
            return None
        cell_x, cell_y = cell
    else:
        gx = math.floor(x_m / block.cell_size_m)
        gy = math.floor(y_m / block.cell_size_m)
        if not block.contains_global(gx, gy):
            return None
        cell_x, cell_y, _ = block.local_cell(gx, gy)
    cell_idx = tariff.cell_index(cell_x, cell_y)
    if cell_idx not in tariff.cell_zones:
        return None
    return int(tariff.rate_for_zone(tariff.zone_for_cell(cell_idx)))


def iter_vehicles(dataset: str):
    """Yield (trip_id, [sorted (t_unix, lat, lon)]) streaming, one trip at a time.

    Trip-level iterators avoid buffering whole datasets in memory (the Porto
    zip is ~1.7GB; vehicle-level grouping had to read it all before yielding).
    """

    if dataset == "geolife":
        trips = iter_geolife_driving_trips(DATASET_DIR / "Geolife Trajectories 1.3" / "Data", gap_sec=120)
    elif dataset == "rome":
        trips = iter_rome_trips(DATASET_DIR / "Roma.txt", gap_sec=120)
    elif dataset == "porto":
        trips = iter_porto_trips(DATASET_DIR / "porto" / "train.csv.zip")
    else:
        raise ValueError(dataset)
    for trip_id, pts in trips:
        yield trip_id, sorted((int(p.timestamp), float(p.lat), float(p.lon)) for p in pts)


def in_region_runs(block, tariff, pts):
    """Split a vehicle stream into contiguous runs of in-tariff-region points with rates."""

    run: list[dict] = []
    for t_unix, lat, lon in pts:
        rate = rate_at(block, tariff, lat, lon)
        if rate is None:
            if len(run) >= 2:
                yield run
            run = []
            continue
        run.append({"t_unix": t_unix, "lat": lat, "lon": lon, "rate": rate})
    if len(run) >= 2:
        yield run


def bill_run(run: list[dict], cadence_sec: int) -> tuple[float, float, float] | None:
    """Return (fine_fee, coarse_fee, distance_m) for one in-region run.

    Both bills cover the IDENTICAL span [first sampled fix, last sampled fix]
    so total distance is the same and the difference is pure zone attribution.
    (An earlier version billed fine over the whole run but coarse only up to
    the last sampled point, dropping the tail distance and producing a spurious
    one-sided under-billing — fixed by clipping fine to the sampled span.)
    """

    sampled = select_real_points_by_cadence(run, cadence_sec=cadence_sec)
    if len(sampled) < 2:
        return None
    # Map each sampled point to its index in run (cadence picks one per bucket,
    # so sampled is a subsequence of run by timestamp).
    sample_t = [s["t_unix"] for s in sampled]
    idx_of: dict[int, int] = {}
    j = 0
    for i, p in enumerate(run):
        if j < len(sample_t) and p["t_unix"] == sample_t[j]:
            idx_of[j] = i
            j += 1
    if len(idx_of) != len(sampled):
        return None
    first_idx, last_idx = idx_of[0], idx_of[len(sampled) - 1]
    if last_idx <= first_idx:
        return None

    # Fine reference: every raw step in [first_idx, last_idx] at its own cell rate.
    fine = 0.0
    dist = 0.0
    for a, b in zip(run[first_idx:last_idx], run[first_idx + 1:last_idx + 1]):
        step = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
        fine += step * a["rate"]
        dist += step
    if dist <= 0:
        return None
    # Coarse protocol bill: each cadence interval's span distance at the
    # starting fix's rate — same total span, coarser zone attribution.
    coarse = 0.0
    for k in range(len(sampled) - 1):
        i0, i1 = idx_of[k], idx_of[k + 1]
        span = 0.0
        for a, b in zip(run[i0:i1], run[i0 + 1:i1 + 1]):
            span += haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])
        coarse += span * sampled[k]["rate"]
    return fine, coarse, dist


def main() -> None:
    parser = argparse.ArgumentParser(description="E0 honest-billing accuracy vs continuous-GPS truth.")
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "experiments" / "e0_billing_accuracy"))
    # Rome is the E0 anchor: its real official tariff has genuine sub-cell zone
    # structure, which is exactly where cell quantization introduces error.
    # Porto is opt-in: its raw trajectories live in a ~1.7GB zip that the
    # whole-file vehicle grouping must buffer before yielding, which is cost-
    # prohibitive in this environment (documented in the receipt).
    parser.add_argument("--datasets", default="rome,geolife,porto")
    parser.add_argument("--max-runs-per-dataset", type=int, default=400)
    parser.add_argument("--min-distance-m", type=int, default=200)
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    period_rows: list[dict] = []
    receipt: dict = {"experiment": "E0 honest billing accuracy", "datasets": {}, "cadence_sec": CADENCE}

    for dataset in args.datasets.split(","):
        dataset = dataset.strip()
        block, tariff = load_block_and_tariff(dataset)
        errors: list[float] = []
        abs_errors: list[float] = []
        runs_used = 0
        multi_zone_runs = 0
        for _vid, pts in iter_vehicles(dataset):
            if runs_used >= args.max_runs_per_dataset:
                break
            for run in in_region_runs(block, tariff, pts):
                if runs_used >= args.max_runs_per_dataset:
                    break
                billed = bill_run(run, CADENCE[dataset])
                if billed is None:
                    continue
                fine, coarse, dist = billed
                if fine <= 0 or dist < args.min_distance_m:
                    continue
                rel = (coarse - fine) / fine
                errors.append(rel)
                abs_errors.append(abs(rel))
                if len({p["rate"] for p in run}) > 1:
                    multi_zone_runs += 1
                runs_used += 1
                period_rows.append(
                    {
                        "dataset": dataset,
                        "vehicle_id": _vid,
                        "distance_m": round(dist, 1),
                        "fine_reference_fee": round(fine, 2),
                        "coarse_protocol_fee": round(coarse, 2),
                        "relative_error": round(rel, 6),
                    }
                )
        if not errors:
            receipt["datasets"][dataset] = {"runs": 0, "note": "no in-region runs found"}
            continue
        errors_sorted = sorted(errors)
        abs_sorted = sorted(abs_errors)
        summary_rows.append(
            {
                "dataset": dataset,
                "n_runs": len(errors),
                "cadence_sec": CADENCE[dataset],
                "mean_signed_error": round(statistics.fmean(errors), 6),
                "median_abs_error": round(statistics.median(abs_sorted), 6),
                "p95_abs_error": round(abs_sorted[max(0, int(0.95 * len(abs_sorted)) - 1)], 6),
                "max_abs_error": round(abs_sorted[-1], 6),
                "p05_signed": round(errors_sorted[max(0, int(0.05 * len(errors_sorted)) - 1)], 6),
                "p95_signed": round(errors_sorted[max(0, int(0.95 * len(errors_sorted)) - 1)], 6),
            }
        )
        receipt["datasets"][dataset] = {
            "runs": len(errors),
            "multi_zone_runs": multi_zone_runs,
            "zone_homogeneous_share": round(1.0 - multi_zone_runs / len(errors), 4),
        }

    write_csv(out_dir / "e0_billing_accuracy.csv", summary_rows)
    write_csv(out_dir / "e0_period_rows.csv", period_rows)
    receipt["skipped"] = {
        "geolife": "tariff_block.json has no geo anchor; synthetic per-cell tariff has zero quantization error by construction",
        "porto": "opt-in via --datasets porto; raw trajectories in a ~1.7GB zip are cost-prohibitive to stream here",
        "tdrive": "no local raw trajectory file; single-period dataset, not an E0 anchor",
    }
    json.dump(receipt, open(out_dir / "receipt.json", "w"), indent=1, sort_keys=True)
    print(f"wrote {len(summary_rows)} summary rows, {len(period_rows)} period rows to {out_dir}")
    for r in summary_rows:
        print(
            f"  {r['dataset']:8s} n={r['n_runs']:4d} median|err|={r['median_abs_error']:.4f} "
            f"p95|err|={r['p95_abs_error']:.4f} mean signed={r['mean_signed_error']:+.4f}"
        )


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("")
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
