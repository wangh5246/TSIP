#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare identity and externally map-matched odometer lengths.")
    parser.add_argument("--identity-jsonl", type=Path, required=True)
    parser.add_argument("--matched-csv", type=Path, required=True, help="CSV columns: trip_id,map_matched_distance_m")
    args = parser.parse_args()
    matched = {}
    with args.matched_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            matched[row["trip_id"]] = float(row["map_matched_distance_m"])
    errors = []
    with args.identity_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            trip_id = record["trip_id"]
            if trip_id not in matched or matched[trip_id] <= 0:
                continue
            identity = float(record["odometer_distance_m"])
            errors.append(abs(identity - matched[trip_id]) / matched[trip_id])
    errors.sort()
    if not errors:
        raise SystemExit("no overlapping trip_id rows")
    print(json.dumps({"n": len(errors), "median_relative_error": _pct(errors, 50), "p95_relative_error": _pct(errors, 95)}, indent=2))
    return 0


def _pct(values: list[float], q: int) -> float:
    return values[round((len(values) - 1) * q / 100)]


if __name__ == "__main__":
    raise SystemExit(main())
