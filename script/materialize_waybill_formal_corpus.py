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
    read_json,
    sha256_file,
    write_json,
)
from waybill_formal.s4_eligibility import eligibility_summary  # noqa: E402


DATASETS = ("tdrive", "geolife", "porto", "rome")
BUCKETS = (100, 50, 25, 10)
RADII = (50, 100, 200)
PROTOCOL_PATH = ROOT / "configs" / "waybill_formal" / "protocol-v1.json"


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


def _records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _s4_eligibility_artifact(
    *, dataset_rows: list[dict[str, Any]], prepared_root: Path
) -> dict[str, Any]:
    """Materialize S4 evaluability before an immutable plan is generated."""

    protocol = read_json(PROTOCOL_PATH)
    spec = protocol["stages"]["S4"]
    minimum = int(spec["eligibility"]["minimum_sequence_identities"])
    temporal_gap = int(spec["temporal_gap_periods"])
    rows: list[dict[str, Any]] = []
    for dataset_row in dataset_rows:
        dataset = str(dataset_row["dataset"])
        periods_path = prepared_root / str(dataset_row["periods_path"])
        records = _records(periods_path)
        for horizon in spec["horizons"]:
            try:
                summary = eligibility_summary(
                    records,
                    horizon=int(horizon),
                    temporal_gap_periods=temporal_gap,
                    minimum_sequence_identities=minimum,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise FormalError(
                    f"S4 eligibility cannot be materialized for {dataset}"
                ) from exc
            eligible = bool(summary["eligible"])
            rows.append(
                {
                    "dataset": dataset,
                    "horizon": int(horizon),
                    "periods_sha256": str(dataset_row["periods_sha256"]),
                    **summary,
                    "status": "eligible" if eligible else "not-evaluable",
                    "reason": (
                        None
                        if eligible
                        else "insufficient-original-identities-with-two-disjoint-windows"
                    ),
                }
            )
    rows.sort(key=lambda row: (str(row["dataset"]), int(row["horizon"])))
    artifact = {
        "schema": "waybill.formal.s4-eligibility/v1",
        "split": str(spec["split"]),
        "temporal_gap_periods": temporal_gap,
        "minimum_sequence_identities": minimum,
        "ineligible_stratum_policy": str(
            spec["eligibility"]["ineligible_stratum_policy"]
        ),
        "rows": rows,
    }
    artifact["matrix_sha256"] = canonical_sha256(artifact)
    return artifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-dt-sec", type=int, default=600)
    parser.add_argument("--tier-vmax-mps", type=int, default=33)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="verify and reuse an interrupted canonical corpus without changing any instance",
    )
    return parser.parse_args()


def _write_or_verify_instance(path: Path, payload: dict[str, Any], *, resume: bool) -> None:
    """Write a new canonical instance or verify an interrupted write before reuse."""

    if not path.exists() and not path.is_symlink():
        write_json(path, payload, exclusive=True)
        return
    if not resume:
        raise FormalError(f"canonical instance already exists; rerun with --resume: {path}")
    if path.is_symlink() or not path.is_file():
        raise FormalError(f"existing canonical instance is not a regular file: {path}")
    existing = read_json(path)
    if canonical_sha256(existing) != canonical_sha256(payload):
        raise FormalError(f"existing canonical instance differs from expected payload: {path}")


def _write_or_verify_manifest(path: Path, manifest: dict[str, Any], *, resume: bool) -> None:
    if not path.exists() and not path.is_symlink():
        write_json(path, manifest, exclusive=True)
        return
    if not resume:
        raise FormalError(f"prepared manifest already exists; rerun with --resume: {path}")
    if path.is_symlink() or not path.is_file():
        raise FormalError(f"existing prepared manifest is not a regular file: {path}")
    if read_json(path) != manifest:
        raise FormalError(f"existing prepared manifest differs from expected payload: {path}")


def main() -> int:
    args = parse_args()
    prepared_root = args.prepared_root.resolve()
    output_dir = args.output_dir.resolve()
    instances_dir = output_dir / "instances"
    if output_dir.exists():
        if not args.resume:
            raise FormalError(
                f"output directory already exists; rerun with --resume to verify it: {output_dir}"
            )
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise FormalError(f"output directory is not a regular directory: {output_dir}")
        if not instances_dir.is_dir() or instances_dir.is_symlink():
            raise FormalError(f"resumed corpus lacks a regular instances directory: {instances_dir}")
    else:
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
                _write_or_verify_instance(path, payload, resume=args.resume)
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

    s4_eligibility = _s4_eligibility_artifact(
        dataset_rows=dataset_rows, prepared_root=prepared_root
    )
    s4_eligibility_path = output_dir / "s4_eligibility.json"
    _write_or_verify_manifest(s4_eligibility_path, s4_eligibility, resume=args.resume)

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
        "s4_eligibility": {
            "path": s4_eligibility_path.name,
            "sha256": sha256_file(s4_eligibility_path),
            "matrix_sha256": s4_eligibility["matrix_sha256"],
            "rows": s4_eligibility["rows"],
        },
        "materializer": {
            "path": "script/materialize_waybill_formal_corpus.py",
            "sha256": sha256_file(Path(__file__)),
            "mode": "persistent canonical JSON instances; solver uses canonical mode only",
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    _write_or_verify_manifest(
        output_dir / "prepared_manifest.json", manifest, resume=args.resume
    )
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
