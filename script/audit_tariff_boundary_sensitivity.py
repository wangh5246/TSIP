#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import replace
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams, compute_bill
from common.osm_vectors import tariff_at_granularity
from common.settlement import ReceiverFix


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure honest-bill sensitivity to tariff zone boundary buffers.")
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--city", choices=["beijing", "porto", "rome"], required=True)
    parser.add_argument("--granularity", choices=["coarse", "medium", "fine"], default="medium")
    parser.add_argument("--buffers-m", default="-300,-100,0,100,300")
    parser.add_argument("--grid-w", type=int, default=100)
    parser.add_argument("--cell-size-m", type=int, default=100)
    args = parser.parse_args()
    buffers = [float(v) for v in args.buffers_m.split(",")]
    records = [json.loads(line) for line in args.input_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    params = HarnessParams(cell_size_m=args.cell_size_m)
    base = _bills(records, args.city, args.granularity, 0, args.grid_w, args.cell_size_m, params)
    rows = []
    for buffer_m in buffers:
        bills = _bills(records, args.city, args.granularity, buffer_m, args.grid_w, args.cell_size_m, params)
        rel = [abs(bill - ref) / max(1, ref) for bill, ref in zip(bills, base)]
        rows.append({"buffer_m": buffer_m, "median_relative_bill_change": statistics.median(rel), "max_relative_bill_change": max(rel, default=0)})
    print(json.dumps(rows, indent=2))
    return 0


def _bills(records, city, granularity, buffer_m, grid_w, cell_size_m, params):
    tariff = tariff_at_granularity(city, granularity, grid_w=grid_w, cell_size_m=cell_size_m, boundary_buffer_m=buffer_m).to_table()
    return [int(compute_bill([ReceiverFix.from_dict(fix) for fix in record["fixes"]], tariff, params)["total_fee_cents"]) for record in records]


if __name__ == "__main__":
    raise SystemExit(main())
