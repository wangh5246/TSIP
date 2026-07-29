#!/usr/bin/env python3
"""Materialize the full prepared ledger and canonical 12-way S3 instance corpus."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from script.run_m3_certified_e3 import (  # noqa: E402
    _load_legacy_instances,
)
from waybill_formal.core import (  # noqa: E402
    FormalError,
    canonical_sha256,
    sha256_file,
    write_json,
)


DATASETS = ("tdrive", "geolife", "porto", "rome")
BUCKETS = (100, 50, 25, 10)
RADII = (50, 100, 200)


def _period_path(prepared_root: Path, dataset: str) -> Path:
    directory = prepared_root / dataset
    candidates = sorted(directory.glob("periods_*s.jsonl"))
    if not candidates:
        raise FormalError(f"no prepared period corpus for {dataset}")
    preferred = {
        "tdrive": "periods_300s.jsonl",
        "geolife": "periods_60s.jsonl",
        "porto": "periods_60s.jsonl",
        "rome": "periods_60s.jsonl",
    }[dataset]
    matches = [path for path in candidates if path.name == preferred]
    return matches[0] if matches else candidates[0]


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-dt-sec", type=int, default=600)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prepared_root = args.prepared_root.resolve()
    output_dir = args.output_dir.resolve()
    instances_dir = output_dir / "instances"
    instances_dir.mkdir(parents=True, exist_ok=False)
    dataset_rows: list[dict[str, Any]] = []
    instance_rows: list[dict[str, Any]] = []
    base_periods: set[tuple[str, str]] = set()
    coverage: Counter[tuple[str, str]] = Counter()

    for dataset in DATASETS:
        periods_path = _period_path(prepared_root, dataset)
        tariff_path = periods_path.parent / "tariff_block.json"
        if not tariff_path.is_file():
            raise FormalError(f"prepared tariff missing for {dataset}")
        period_count = _line_count(periods_path)
        dataset_rows.append(
            {
                "dataset": dataset,
                "periods_path": str(periods_path.relative_to(prepared_root)),
                "periods_sha256": sha256_file(periods_path),
                "period_count": period_count,
                "tariff_path": str(tariff_path.relative_to(prepared_root)),
                "tariff_sha256": sha256_file(tariff_path),
            }
        )
        for radius in RADII:
            cadence_sec = 300 if dataset == "tdrive" else 60
            instances = _load_legacy_instances(
                [periods_path],
                buckets_m=list(BUCKETS),
                relay_radius_m=radius,
                cadence_sec=cadence_sec,
                max_dt_sec=int(args.max_dt_sec),
                tier_vmax_mps=int(args.tier_vmax_mps),
                limit_per_input=0,
                max_fixes=0,
                stratify_rome=False,
            )
            for instance in instances:
                bucket_m = int(instance.bucket_size_units or 0) // int(
                    instance.profile.coordinate_scale_per_m
                )
                period_id = str(instance.fixes[0].period_id)
                base_key = (dataset, period_id)
                base_periods.add(base_key)
                coverage[base_key] += 1
                unique_id = f"{instance.instance_id}:radius-{radius}m"
                instance = replace(instance, instance_id=unique_id)
                payload = instance.to_dict()
                relative = Path("instances") / dataset / f"{canonical_sha256(payload)}.json"
                path = output_dir / relative
                write_json(path, payload, exclusive=True)
                instance_rows.append(
                    {
                        "instance_id": unique_id,
                        "dataset": dataset,
                        "period_id": period_id,
                        "bucket_m": bucket_m,
                        "radius_m": radius,
                        "path": str(relative),
                        "sha256": sha256_file(path),
                        "fixes": len(instance.fixes),
                    }
                )

    bad_coverage = {
        f"{dataset}:{period_id}": count
        for (dataset, period_id), count in coverage.items()
        if count != len(BUCKETS) * len(RADII)
    }
    if bad_coverage:
        raise FormalError(f"canonical S3 coverage is not 12 per period: {bad_coverage}")
    if sum(row["period_count"] for row in dataset_rows) != len(base_periods):
        raise FormalError(
            "prepared period ledger and canonical S3 base-period cardinality differ; "
            "no period may be silently dropped"
        )
    manifest = {
        "schema": "waybill.formal.prepared-manifest/v1",
        "formal_caps": {
            "max_trips": 0,
            "max_raw_points": 0,
            "limit_per_input": 0,
            "max_fixes": 0,
        },
        "prepared_root_label": "WAYBILL_PREPARED_ROOT",
        "corpus_root_label": "WAYBILL_CORPUS_ROOT",
        "datasets": dataset_rows,
        "canonical_period_count": len(base_periods),
        "canonical_instance_count": len(instance_rows),
        "canonical_instances": sorted(
            instance_rows,
            key=lambda row: (
                row["dataset"],
                row["period_id"],
                -row["bucket_m"],
                row["radius_m"],
            ),
        ),
        "materializer": {
            "path": "script/materialize_waybill_formal_corpus.py",
            "sha256": sha256_file(Path(__file__)),
            "mode": "persistent canonical JSON instances; solver uses canonical mode only",
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    write_json(output_dir / "prepared_manifest.json", manifest, exclusive=True)
    print(
        json.dumps(
            {
                "prepared_manifest": str(output_dir / "prepared_manifest.json"),
                "canonical_period_count": manifest["canonical_period_count"],
                "canonical_instance_count": manifest["canonical_instance_count"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
