"""Fail-closed infrastructure for WayBill paper-grade server experiments."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import platform
import re
import shutil
import signal
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from common.resource_probe import collect_host_evidence, measured_command, parse_time_evidence


EMBEDDED_RELEASE_BINDING_PATH = Path("/opt/waybill/release-bindings.json")
FORMAL_PTAU_BYTES = 4_831_921_304
FORMAL_PTAU_BLAKE2B = (
    "0d64f63dba1a6f11139df765cb690da69d9b2f469a1ddd0de5e4aa628abb28f7"
    "87f04c6a5fb84a235ec5ea7f41d0548746653ecab0559add658a83502d1cb21b"
)
_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_SEALED_RUN_INPUTS = (
    "protocol.json",
    "plan.json",
    "jobs/expected.jsonl",
    "code_manifest.json",
    "data_manifest.json",
    "environment.json",
    "container_manifest.json",
    "prepared_manifest.json",
    "gate_receipts.json",
    "execution-container.json",
)


class FormalError(RuntimeError):
    """Raised when a formal gate must fail closed."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _is_lower_hex(value: Any, length: int) -> bool:
    text = str(value)
    return len(text) == length and all(character in "0123456789abcdef" for character in text)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalError(f"cannot read valid JSON from {path}: {exc}") from exc


def write_json(path: Path, payload: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(dict(row)) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise FormalError(f"{path}:{line_number} is not a JSON object")
                rows.append(payload)
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalError(f"cannot read JSONL {path}: {exc}") from exc
    return rows


_STAGE_RESERVED_FILES = {"job.json", "receipt.json", "stage-result.json"}


def build_stage_artifact_manifest(attempt_dir: Path) -> list[dict[str, Any]]:
    """Hash all stage-produced files without following symbolic links."""

    rows: list[dict[str, Any]] = []
    for path in sorted(attempt_dir.rglob("*")):
        if path.is_symlink():
            raise FormalError(f"stage artifact must not be a symbolic link: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(attempt_dir).as_posix()
        if relative in _STAGE_RESERVED_FILES:
            continue
        rows.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def validate_stage_result(
    result: Mapping[str, Any], *, job: Mapping[str, Any], attempt_dir: Path
) -> dict[str, Any]:
    _require(
        result.get("schema") == "waybill.formal.stage-result/v2",
        "unsupported stage-result schema",
    )
    _require(result.get("job_id") == job.get("job_id"), "stage-result job id mismatch")
    _require(result.get("stage") == job.get("stage"), "stage-result stage mismatch")
    _require(result.get("kind") == job.get("kind"), "stage-result kind mismatch")
    _require(
        result.get("job_sha256") == canonical_sha256(job),
        "stage-result job hash mismatch",
    )
    _require(result.get("status") in {"passed", "failed"}, "invalid stage-result status")
    declared_result_sha256 = str(result.get("result_sha256", ""))
    unsigned = dict(result)
    unsigned.pop("result_sha256", None)
    _require(
        declared_result_sha256 == canonical_sha256(unsigned),
        "stage-result canonical hash mismatch",
    )
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list):
        raise FormalError("stage-result artifact manifest is missing")
    _require(
        result.get("artifact_manifest_sha256") == canonical_sha256(artifacts),
        "stage-result artifact manifest hash mismatch",
    )
    seen: set[str] = set()
    for record in artifacts:
        _require(isinstance(record, dict), "stage artifact record is not an object")
        relative = str(record.get("path", ""))
        relative_path = Path(relative)
        _require(
            bool(relative)
            and not relative_path.is_absolute()
            and ".." not in relative_path.parts
            and relative not in _STAGE_RESERVED_FILES,
            f"unsafe stage artifact path: {relative}",
        )
        _require(relative not in seen, f"duplicate stage artifact path: {relative}")
        seen.add(relative)
        path = attempt_dir / relative_path
        _require(path.is_file() and not path.is_symlink(), f"stage artifact missing: {relative}")
        _require(path.stat().st_size == int(record.get("bytes", -1)), f"stage artifact size mismatch: {relative}")
        _require(sha256_file(path) == record.get("sha256"), f"stage artifact hash mismatch: {relative}")
    actual_artifacts = build_stage_artifact_manifest(attempt_dir)
    _require(actual_artifacts == artifacts, "stage artifact manifest is incomplete or stale")
    return {
        "stage_result_sha256": declared_result_sha256,
        "artifact_manifest_sha256": str(result["artifact_manifest_sha256"]),
        "artifact_count": len(artifacts),
        "status": str(result["status"]),
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FormalError(message)


def validate_protocol(protocol: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the frozen M4 protocol invariants and return a receipt."""

    _require(protocol.get("schema") == "waybill.formal.protocol/v1", "unsupported protocol schema")
    _require(protocol.get("formal") is True, "formal protocol must set formal=true")
    _require(int(protocol.get("max_attempts_per_job", 0)) == 2, "formal runs require exactly two attempts")
    caps = protocol.get("formal_caps", {})
    _require(
        set(caps) == {"max_trips", "max_raw_points", "limit_per_input", "max_fixes"},
        "formal cap set is incomplete",
    )
    _require(all(int(value) == 0 for value in caps.values()), "all formal development caps must be zero")
    _require(
        protocol.get("datasets") == ["tdrive", "geolife", "porto", "rome"],
        "dataset order or membership differs from M4",
    )
    _require(protocol.get("seeds") == [17, 31, 47, 73, 101], "formal seed set differs from M4")
    toolchain = protocol.get("toolchain", {})
    expected_toolchain = {
        "python": "3.12",
        "node": "26.5.1",
        "npm": "11.17.0",
        "circom": "2.1.9",
        "snarkjs": "0.7.6",
        "circomlib": "2.0.5",
        "architecture": "linux-x86_64",
    }
    for key, expected in expected_toolchain.items():
        _require(str(toolchain.get(key)) == expected, f"toolchain {key} must be {expected}")
    stages = protocol.get("stages", {})
    _require(set(stages) == {"S1", "S2", "S3", "S4", "S5"}, "protocol must define S1-S5")
    statistics_spec = protocol.get("statistics", {})
    _require(
        statistics_spec.get("cluster_unit") == "original vehicle or user"
        and statistics_spec.get("confidence_interval") == "cluster bootstrap 95%"
        and int(statistics_spec.get("bootstrap_replicates", 0)) == 5000
        and statistics_spec.get("percentiles") == [50, 95, 99],
        "S1 cluster-bootstrap statistics differ from the frozen protocol",
    )
    reporting = protocol.get("reporting", {})
    _require(
        reporting.get("cross_seed_rule")
        == "report every seed and the median/min/max across the five seeds for identical non-seed parameters"
        and reporting.get("multiplicity")
        == "descriptive confidence intervals; no familywise confirmatory significance claim"
        and set(reporting.get("primary_endpoints", {}))
        == {"S1", "S2", "S3", "S4", "S5"},
        "formal reporting and cross-seed rules are incomplete",
    )
    _require(
        stages["S1"].get("methods")
        == [
            "oracle-position",
            "v5-dt-vmax-rmax",
            "v6-dodo-rmax",
            "v6-without-month-close",
        ]
        and stages["S1"].get("month_close_ablation")
        == "whole-period-withholding-with-versus-without-rmax-reconciliation"
        and stages["S1"].get("rejected_period_policy") == "fail-closed",
        "S1 methods or fail-closed policy differ from the frozen protocol",
    )
    expected_view_schemas = {
        "O0": [
            "interval_count",
            "period_duration_sec",
            "total_distance_m",
            "total_fee_cents",
        ],
        "O1": [
            "fallback_indicator",
            "fallback_intervals",
            "interval_count",
            "period_duration_sec",
            "total_distance_m",
            "total_fee_cents",
        ],
        "O2": [
            "amount_bucket_500c",
            "distance_bucket_100m",
            "fallback_indicator",
            "fallback_intervals",
            "interval_count",
            "period_duration_sec",
        ],
        "O3": [
            "amount_bucket_500c",
            "distance_bucket_100m",
            "fallback_indicator",
            "fallback_intervals",
            "interval_count",
            "opened_cells",
            "period_duration_sec",
        ],
    }
    _require(
        stages["S4"].get("view_schemas") == expected_view_schemas
        and int(stages["S4"].get("temporal_gap_periods", 0)) == 1
        and stages["S4"].get("gallery_query_overlap_policy")
        == "forbid-any-shared-period"
        and stages["S4"].get("split_policy")
        == {
            "target_train_fraction": 0.7,
            "minimum_train_identities": 2,
            "minimum_test_identities": 2,
        }
        and stages["S4"].get("eligibility")
        == {
            "minimum_sequence_identities": 4,
            "ineligible_stratum_policy": "exclude-before-run-and-report",
        },
        "S4 observation schemas or temporal split differ from the frozen protocol",
    )
    _require(
        stages["S4"].get("statistics")
        == {
            "cluster_unit": "original-vehicle-or-user",
            "bootstrap_replicates": 5000,
            "confidence_interval": 0.95,
            "aggregation": "macro-by-identity",
        },
        "S4 identity-cluster statistics differ from the frozen protocol",
    )
    _require(int(stages["S2"].get("measured_trials", 0)) == 10, "S2 requires 10 measured trials")
    _require(
        int(stages["S3"].get("instance_timeout_sec", 0)) == 7200
        and int(stages["S3"].get("timeout_sec", 0)) == 28800,
        "S3 must allow 7200 seconds per instance and 28800 seconds per four-bucket group",
    )
    _require(
        stages["S2"].get("depths") == [8, 12, 14, 16]
        and stages["S2"].get("fixes") == [25, 50, 100, 200],
        "S2 main matrix differs from M4",
    )
    _require(
        stages["S3"].get("buckets_m") == [100, 50, 25, 10]
        and stages["S3"].get("attacker_or_relay_radius_m") == [50, 100, 200],
        "S3 matrix differs from M4",
    )
    _require(
        float(stages["S3"].get("main_gap_max", -1)) == 0.01
        and float(stages["S3"].get("all_instance_certified_share_min", -1)) == 0.95
        and float(stages["S3"].get("all_instance_gap_max", -1)) == 0.05,
        "S3 aggregate thresholds differ from M4",
    )
    _require(
        stages["S5"].get("fixes") == [25, 100, 200]
        and int(stages["S5"].get("valid_bundle_corpus_per_fixes", 0)) == 100
        and int(stages["S5"].get("corpus_concurrency", 0)) == 8
        and int(stages["S5"].get("verifier_calls_per_fixes", 0)) == 10000,
        "S5 fixed-corpus matrix differs from M4",
    )
    return {
        "gate": "RG7-protocol-shape",
        "status": "passed",
        "protocol_sha256": canonical_sha256(protocol),
        "checked_at": utc_now(),
    }


def validate_tariff_registry(registry: Mapping[str, Any], root: Path) -> dict[str, Any]:
    _require(
        registry.get("schema") == "waybill.formal.tariff-registry/v1",
        "unsupported tariff registry schema",
    )
    records = registry.get("tariffs")
    if not isinstance(records, list) or not records:
        raise FormalError("tariff registry is empty")
    seen: set[str] = set()
    classes: set[str] = set()
    checks: list[dict[str, Any]] = []
    for raw in records:
        _require(isinstance(raw, dict), "tariff record is not an object")
        tariff_id = str(raw.get("tariff_id", ""))
        _require(bool(tariff_id) and tariff_id not in seen, f"duplicate tariff id: {tariff_id}")
        seen.add(tariff_id)
        semantic_class = str(raw.get("semantic_class", ""))
        classes.add(semantic_class)
        artifact = root / str(raw.get("artifact_path", ""))
        _require(artifact.is_file(), f"tariff artifact missing: {artifact}")
        actual_sha256 = sha256_file(artifact)
        _require(
            actual_sha256 == raw.get("artifact_sha256"),
            f"tariff artifact hash mismatch: {tariff_id}",
        )
        allowed = [str(item).lower() for item in raw.get("allowed_claims", [])]
        forbidden = [str(item).lower() for item in raw.get("forbidden_claims", [])]
        if semantic_class == "normalized_capacity":
            _require(
                any("real bill" in item or "real road-use" in item for item in forbidden),
                f"normalized tariff {tariff_id} lacks an economic-claim prohibition",
            )
            _require(
                not any("real bill" in item or "real taxpayer" in item for item in allowed),
                f"normalized tariff {tariff_id} permits an economic claim",
            )
        checks.append(
            {
                "tariff_id": tariff_id,
                "semantic_class": semantic_class,
                "artifact_sha256": actual_sha256,
                "unit": raw.get("unit"),
                "passed": True,
            }
        )
    _require(
        "normalized_capacity" in classes and "experimental_economic" in classes,
        "registry must separate normalized capacity and experimental economic semantics",
    )
    return {
        "gate": "RG3",
        "status": "passed",
        "registry_sha256": canonical_sha256(registry),
        "checks": checks,
        "checked_at": utc_now(),
    }


def validate_formal_entrypoints(root: Path) -> dict[str, Any]:
    paths = [
        root / f"script/run_waybill_s{stage}_formal_unit.py"
        for stage in range(1, 6)
    ]
    paths.extend(
        [
            root / "script/waybill_formal.py",
            root / "script/materialize_waybill_formal_corpus.py",
            root / "script/check_deploy_host.sh",
        ]
    )
    checks = [{"path": str(path.relative_to(root)), "exists": path.is_file()} for path in paths]
    _require(all(check["exists"] for check in checks), "a formal runtime entrypoint is missing")
    return {
        "gate": "RG5-entrypoints",
        "status": "passed",
        "checks": checks,
        "checked_at": utc_now(),
    }


def _matching_files(path: Path, record: Mapping[str, Any]) -> list[Path]:
    kind = str(record.get("kind"))
    if kind == "file":
        return [path] if path.is_file() else []
    if kind == "directory":
        pattern = str(record.get("include_glob", "**/*"))
        return sorted(item for item in path.glob(pattern) if item.is_file())
    raise FormalError(f"unsupported data source kind: {kind}")


def _entity_count(dataset: str, base_path: Path, files: Sequence[Path]) -> int | None:
    if dataset == "tdrive":
        return len(files)
    if dataset == "geolife":
        return len({item.relative_to(base_path).parts[0] for item in files})
    return None


def _data_file_rows(data_root: Path, source: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    base_path = data_root / str(source["relative_path"])
    files = _matching_files(base_path, source)
    for path in files:
        yield {
            "dataset": source["dataset"],
            "path": str(path.relative_to(data_root)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }


def build_data_manifest(
    registry: Mapping[str, Any],
    data_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Hash all restricted raw inputs and enforce provider completeness counts."""

    _require(
        registry.get("schema") == "waybill.formal.data-sources/v1",
        "unsupported data source registry schema",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    for source in registry.get("datasets", []):
        dataset = str(source["dataset"])
        base_path = data_root / str(source["relative_path"])
        rows = list(_data_file_rows(data_root, source))
        file_count = len(rows)
        expected_file_count = int(source["expected_file_count"])
        _require(
            file_count == expected_file_count,
            f"{dataset}: expected {expected_file_count} files, found {file_count}",
        )
        total_bytes = sum(int(row["bytes"]) for row in rows)
        if source.get("expected_bytes") is not None:
            _require(
                total_bytes == int(source["expected_bytes"]),
                f"{dataset}: byte count mismatch",
            )
        if source.get("expected_sha256") is not None:
            _require(
                len(rows) == 1 and rows[0]["sha256"] == source["expected_sha256"],
                f"{dataset}: raw file hash mismatch",
            )
        entity_count = _entity_count(dataset, base_path, [data_root / row["path"] for row in rows])
        if entity_count is not None:
            _require(
                entity_count == int(source["expected_entity_count"]),
                f"{dataset}: expected {source['expected_entity_count']} entities, found {entity_count}",
            )
        tree_sha256 = hashlib.sha256(
            "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")
        ).hexdigest()
        datasets.append(
            {
                "dataset": dataset,
                "relative_path": source["relative_path"],
                "file_count": file_count,
                "entity_count": entity_count or source.get("expected_entity_count"),
                "total_bytes": total_bytes,
                "tree_sha256": tree_sha256,
                "official_url": source["official_url"],
                "terms": source["terms"],
                "complete": True,
            }
        )
        all_rows.extend(rows)
    files_path = output_dir / "raw-files.jsonl"
    write_jsonl(files_path, all_rows)
    manifest = {
        "schema": "waybill.formal.data-manifest/v1",
        "generated_at": utc_now(),
        "data_root_label": "WAYBILL_DATA_ROOT",
        "registry_sha256": canonical_sha256(registry),
        "raw_files_jsonl": files_path.name,
        "raw_files_jsonl_sha256": sha256_file(files_path),
        "raw_file_count": len(all_rows),
        "raw_total_bytes": sum(int(row["bytes"]) for row in all_rows),
        "datasets": datasets,
        "formal_caps": {
            "max_trips": 0,
            "max_raw_points": 0,
            "limit_per_input": 0,
            "max_fixes": 0,
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    write_json(output_dir / "data-manifest.json", manifest)
    return manifest


def validate_data_manifest(
    manifest: Mapping[str, Any],
    registry: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    _require(manifest.get("schema") == "waybill.formal.data-manifest/v1", "bad data manifest schema")
    _require(manifest.get("registry_sha256") == canonical_sha256(registry), "data registry hash mismatch")
    files_path = output_dir / str(manifest.get("raw_files_jsonl"))
    _require(files_path.is_file(), "raw file ledger is missing")
    _require(
        sha256_file(files_path) == manifest.get("raw_files_jsonl_sha256"),
        "raw file ledger hash mismatch",
    )
    datasets = manifest.get("datasets", [])
    _require(
        [record.get("dataset") for record in datasets] == ["tdrive", "geolife", "porto", "rome"],
        "data manifest dataset order or membership mismatch",
    )
    _require(all(record.get("complete") is True for record in datasets), "a raw dataset is incomplete")
    _require(all(int(value) == 0 for value in manifest.get("formal_caps", {}).values()), "data caps are nonzero")
    return {
        "gate": "RG2",
        "status": "passed",
        "manifest_sha256": manifest.get("manifest_sha256"),
        "checked_at": utc_now(),
    }


def _job(stage: str, kind: str, parameters: Mapping[str, Any], stage_spec: Mapping[str, Any]) -> dict[str, Any]:
    identity = {"stage": stage, "kind": kind, "parameters": dict(parameters)}
    job_id = f"{stage.lower()}-{canonical_sha256(identity)[:20]}"
    return {
        "job_id": job_id,
        **identity,
        "timeout_sec": int(stage_spec["timeout_sec"])
        if "timeout_sec" in stage_spec
        else int(stage_spec.get("timeout_sec_per_stage", 7200)),
        "resource": dict(stage_spec.get("resource", {})),
        # A host interpreter path is not portable into the frozen runtime.
        # Run the stage as a module: executing a file below ``script/`` puts
        # that directory at sys.path[0], where ``script/waybill_formal.py``
        # shadows the real ``waybill_formal`` package.
        "command": [
            "python",
            "-m",
            f"script.run_waybill_{stage.lower()}_formal_unit",
        ],
    }


def _expand_s1(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S1"]
    jobs: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = [
        {"scenario": "natural", "seed": int(protocol["seeds"][0])}
    ]
    scenarios.extend(
        {"scenario": "independent", "alpha": alpha, "seed": seed}
        for alpha, seed in itertools.product(spec["independent_mask_alpha"], protocol["seeds"])
    )
    scenarios.extend(
        {
            "scenario": "burst",
            "share": spec["burst_share"],
            "length_fixes": length,
            "seed": seed,
        }
        for length, seed in itertools.product(spec["burst_lengths_fixes"], protocol["seeds"])
    )
    for dataset, scenario in itertools.product(protocol["datasets"], scenarios):
        jobs.append(
            _job(
                "S1",
                "paired-fallback",
                {"dataset": dataset, "methods": spec["methods"], **scenario},
                spec,
            )
        )
    contexts = [{"context": "natural", "seed": int(protocol["seeds"][0])}]
    contexts.extend(
        {"context": "independent-alpha-0.10", "seed": seed} for seed in protocol["seeds"]
    )
    for dataset, error, context in itertools.product(
        protocol["datasets"], spec["odometer_errors"], contexts
    ):
        jobs.append(
            _job(
                "S1",
                "odometer-sensitivity",
                {"dataset": dataset, "odometer_error": error, **context},
                spec,
            )
        )
    return jobs


def _expand_s2(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S2"]
    jobs = [
        _job(
            "S2",
            "main",
            {
                "depth": depth,
                "fixes": fixes,
                "warmup_trials": spec["warmup_trials"],
                "measured_trials": spec["measured_trials"],
            },
            spec,
        )
        for depth, fixes in itertools.product(spec["depths"], spec["fixes"])
    ]
    for fixes, concurrency, batch in itertools.product(
        spec["concurrency_fixes"],
        spec["concurrency"],
        range(1, int(spec["concurrency_batches"]) + 1),
    ):
        job = _job(
            "S2",
            "concurrency",
            {
                "depth": 14,
                "fixes": fixes,
                "concurrency": concurrency,
                "batch": batch,
            },
            spec,
        )
        job["resource"]["storage_gib_per_attempt"] = 0.05
        job["resource"]["expected_cpu_hours_per_job"] = max(0.5, concurrency * 0.5)
        jobs.append(job)
    return jobs


def _prepared_instance_rows(prepared_manifest: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if prepared_manifest is None:
        return []
    rows = prepared_manifest.get("canonical_instances")
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        _require(isinstance(row, dict), "canonical instance entry is not an object")
        _require(row.get("instance_id") and row.get("path"), "canonical instance lacks id or path")
        _require(
            int(row.get("bucket_m", 0)) in {100, 50, 25, 10},
            "canonical instance lacks a registered bucket_m",
        )
        _require(
            int(row.get("radius_m", 0)) in {50, 100, 200},
            "canonical instance lacks a registered radius_m",
        )
        normalized.append(dict(row))
    return normalized


def _prepared_s4_eligibility(
    protocol: Mapping[str, Any], prepared_manifest: Mapping[str, Any] | None
) -> tuple[dict[tuple[str, int], dict[str, Any]], str | None]:
    """Return the immutable S4 evaluability matrix for a materialized plan."""

    if prepared_manifest is None:
        return {}, None
    block = prepared_manifest.get("s4_eligibility")
    if block is None and "datasets" not in prepared_manifest:
        return {}, None
    _require(isinstance(block, dict), "prepared S4 eligibility artifact is missing")
    rows = block.get("rows")
    _require(isinstance(rows, list), "prepared S4 eligibility rows are missing")
    spec = protocol["stages"]["S4"]
    matrix = {
        "schema": "waybill.formal.s4-eligibility/v1",
        "split": str(spec["split"]),
        "temporal_gap_periods": int(spec["temporal_gap_periods"]),
        "minimum_sequence_identities": int(
            spec["eligibility"]["minimum_sequence_identities"]
        ),
        "ineligible_stratum_policy": str(
            spec["eligibility"]["ineligible_stratum_policy"]
        ),
        "rows": rows,
    }
    matrix_sha256 = str(block.get("matrix_sha256", ""))
    _require(
        matrix_sha256 == canonical_sha256(matrix),
        "prepared S4 eligibility matrix hash mismatch",
    )
    expected_keys = {
        (str(dataset), int(horizon))
        for dataset in protocol["datasets"]
        for horizon in spec["horizons"]
    }
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        _require(isinstance(row, dict), "prepared S4 eligibility row is not an object")
        key = (str(row.get("dataset", "")), int(row.get("horizon", 0)))
        _require(key in expected_keys and key not in by_key, "invalid S4 eligibility key")
        eligible_count = int(row.get("sequence_eligible_identity_count", -1))
        minimum = int(row.get("minimum_sequence_identities", -1))
        eligible_raw = row.get("eligible")
        _require(isinstance(eligible_raw, bool), "S4 eligibility flag is not boolean")
        eligible = eligible_raw
        _require(
            minimum == matrix["minimum_sequence_identities"],
            "S4 eligibility minimum identity count differs from protocol",
        )
        _require(
            eligible == (eligible_count >= minimum),
            "S4 eligibility status does not match its identity count",
        )
        _require(
            row.get("status") == ("eligible" if eligible else "not-evaluable"),
            "S4 eligibility artifact has an invalid status",
        )
        if not eligible:
            _require(
                row.get("reason")
                == "insufficient-original-identities-with-two-disjoint-windows",
                "S4 ineligible stratum has no truthful reason",
            )
        else:
            _require(row.get("reason") is None, "S4 eligible stratum has a failure reason")
        by_key[key] = dict(row)
    _require(set(by_key) == expected_keys, "S4 eligibility matrix is incomplete")
    return by_key, matrix_sha256


def _expand_s3(
    protocol: Mapping[str, Any], prepared_manifest: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S3"]
    instances = _prepared_instance_rows(prepared_manifest)
    groups: dict[tuple[str, str, int], dict[int, dict[str, Any]]] = {}
    for instance in instances:
        dataset = str(instance.get("dataset", ""))
        period_id = str(instance.get("period_id", ""))
        radius_m = int(instance["radius_m"])
        _require(bool(dataset and period_id), "S3 instance lacks dataset or period_id")
        bucket_m = int(instance["bucket_m"])
        group = groups.setdefault((dataset, period_id, radius_m), {})
        _require(bucket_m not in group, "duplicate S3 bucket in one period/radius group")
        group[bucket_m] = instance

    expected_buckets = [int(value) for value in spec["buckets_m"]]
    jobs: list[dict[str, Any]] = []
    for (dataset, period_id, radius_m), by_bucket in sorted(groups.items()):
        _require(
            set(by_bucket) == set(expected_buckets),
            "S3 period/radius group does not contain the frozen four-bucket grid",
        )
        grouped_instances = [
            {
                "instance_id": by_bucket[bucket]["instance_id"],
                "instance_path": by_bucket[bucket]["path"],
                "instance_sha256": by_bucket[bucket].get("sha256"),
                "bucket_m": bucket,
            }
            for bucket in expected_buckets
        ]
        jobs.append(
            _job(
                "S3",
                "certified-bound-group",
                {
                    "group_id": f"{dataset}:{period_id}:radius-{radius_m}m",
                    "dataset": dataset,
                    "period_id": period_id,
                    "radius_m": radius_m,
                    "instances": grouped_instances,
                    "instance_timeout_sec": spec["instance_timeout_sec"],
                    "oracle_max_fixes": spec["oracle_max_fixes"],
                    "main_gap_max": spec["main_gap_max"],
                    "all_instance_certified_share_min": spec[
                        "all_instance_certified_share_min"
                    ],
                    "all_instance_gap_max": spec["all_instance_gap_max"],
                },
                spec,
            )
        )
    return jobs


def _expand_s4(
    protocol: Mapping[str, Any], prepared_manifest: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S4"]
    eligibility, matrix_sha256 = _prepared_s4_eligibility(protocol, prepared_manifest)
    jobs = [
        _job(
            "S4",
            "privacy-attack",
            {
                "dataset": dataset,
                "view": view["view"],
                "opening": view["opening"],
                "horizon": horizon,
                "attacker": attacker,
                "seed": seed,
                "split": spec["split"],
                "split_policy": spec["split_policy"],
                "temporal_gap_periods": spec["temporal_gap_periods"],
                "bootstrap_replicates": spec["statistics"]["bootstrap_replicates"],
                **(
                    {
                        "minimum_sequence_identities": spec["eligibility"][
                            "minimum_sequence_identities"
                        ],
                        "s4_eligibility_matrix_sha256": matrix_sha256,
                    }
                    if matrix_sha256 is not None
                    else {}
                ),
            },
            spec,
        )
        for dataset, view, horizon, attacker, seed in itertools.product(
            protocol["datasets"],
            spec["views"],
            spec["horizons"],
            spec["attackers"],
            protocol["seeds"],
        )
        if not eligibility or eligibility[(str(dataset), int(horizon))]["eligible"]
    ]
    return jobs


def _expand_s5(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S5"]
    jobs: list[dict[str, Any]] = []
    for fixes in spec["fixes"]:
        job = _job(
            "S5",
            "corpus",
            {
                "fixes": fixes,
                "valid_bundle_corpus": spec["valid_bundle_corpus_per_fixes"],
                "concurrency": spec["corpus_concurrency"],
                "source_depth": 14,
            },
            spec,
        )
        job["resource"]["storage_gib_per_attempt"] = 1
        job["resource"]["expected_cpu_hours_per_job"] = 16
        jobs.append(job)
    jobs.extend(
        _job(
            "S5",
            "verifier",
            {
                "fixes": fixes,
                "valid_bundle_corpus": spec["valid_bundle_corpus_per_fixes"],
                "calls": spec["verifier_calls_per_fixes"],
            },
            spec,
        )
        for fixes in spec["fixes"]
    )
    jobs.extend(
        _job(
            "S5",
            "handler",
            {
                "fixes": fixes,
                "concurrency": concurrency,
                "workload": workload,
                "repetition": repetition,
                "valid_bundle_corpus": spec["valid_bundle_corpus_per_fixes"],
            },
            spec,
        )
        for fixes, concurrency, workload, repetition in itertools.product(
            spec["fixes"],
            spec["concurrency"],
            spec["workloads"],
            range(1, int(spec["repetitions"]) + 1),
        )
    )
    return jobs


def expand_protocol_jobs(
    protocol: Mapping[str, Any],
    prepared_manifest: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validate_protocol(protocol)
    stage_jobs = {
        "S1": _expand_s1(protocol),
        "S2": _expand_s2(protocol),
        "S3": _expand_s3(protocol, prepared_manifest),
        "S4": _expand_s4(protocol, prepared_manifest),
        "S5": _expand_s5(protocol),
    }
    jobs = [job for stage in ("S1", "S2", "S3", "S4", "S5") for job in stage_jobs[stage]]
    _require(len({job["job_id"] for job in jobs}) == len(jobs), "job id collision")
    instance_count = len(_prepared_instance_rows(prepared_manifest))
    canonical_period_count = (
        int(prepared_manifest.get("canonical_period_count", 0))
        if prepared_manifest is not None
        else 0
    )
    materialized = (
        instance_count > 0
        and canonical_period_count > 0
        and instance_count == 12 * canonical_period_count
    )
    counts = {stage: len(rows) for stage, rows in stage_jobs.items()}
    max_attempts = int(protocol["max_attempts_per_job"])
    worst_case_cpu_hours = sum(
        int(job["timeout_sec"]) * int(job["resource"].get("cpus", 1)) / 3600
        for job in jobs
    ) * max_attempts
    storage_gib = sum(
        float(job["resource"].get("storage_gib_per_attempt", 0.0))
        for job in jobs
    ) * max_attempts
    expected_cpu_hours = sum(
        float(job["resource"].get("expected_cpu_hours_per_job", 0.0))
        for job in jobs
    )
    peak_memory_by_stage = {
        stage: int(spec["resource"]["memory_gib"])
        * int(spec["resource"]["scheduler_max_parallel"])
        for stage, spec in protocol["stages"].items()
    }
    summary = {
        "schema": "waybill.formal.plan/v1",
        "protocol_sha256": canonical_sha256(protocol),
        "materialized": materialized,
        "canonical_period_count": canonical_period_count,
        "canonical_instance_count": instance_count,
        "expected_job_count": len(jobs) if materialized else None,
        "static_job_count_excluding_S3": counts["S1"] + counts["S2"] + counts["S4"] + counts["S5"],
        "S3_job_count_formula": "3 four-bucket groups * canonical_period_count",
        "stage_job_counts": counts,
        "resource_budget": {
            "minimum_target_workspace_gib": 500,
            "minimum_memory_gib_per_setup_or_prove_job": 32,
            "S2_peak_requested_memory_gib": max(
                int(job["resource"].get("memory_gib", 0)) for job in stage_jobs["S2"]
            ),
            "peak_scheduled_memory_gib": max(peak_memory_by_stage.values()),
            "peak_scheduled_memory_by_stage_gib": peak_memory_by_stage,
            "worst_case_cpu_hours_including_two_attempts": (
                round(worst_case_cpu_hours, 3) if materialized else None
            ),
            "expected_cpu_hours": (
                round(expected_cpu_hours, 3) if materialized else None
            ),
            "expected_cpu_hours_static_excluding_S3": round(
                expected_cpu_hours
                - counts["S3"]
                * float(
                    protocol["stages"]["S3"]["resource"][
                        "expected_cpu_hours_per_job"
                    ]
                ),
                3,
            ),
            "worst_case_cpu_hours_static_excluding_S3": round(
                worst_case_cpu_hours
                - counts["S3"]
                * int(protocol["stages"]["S3"]["timeout_sec"])
                * int(protocol["stages"]["S3"]["resource"]["cpus"])
                / 3600
                * max_attempts,
                3,
            ),
            "estimated_attempt_storage_gib_including_two_attempts": (
                round(storage_gib + 10, 3) if materialized else None
            ),
            "estimated_attempt_storage_gib_static_excluding_S3": round(
                storage_gib
                - counts["S3"]
                * float(
                    protocol["stages"]["S3"]["resource"]["storage_gib_per_attempt"]
                )
                * max_attempts
                + 10,
                3,
            ),
            "S3_timeout_cpu_hours_upper_formula": "24 * canonical_period_count",
            "S3_expected_cpu_hours_formula": "6 * canonical_period_count",
            "note": (
                "Worst-case CPU uses every job timeout, requested CPUs, and both attempts. "
                "Storage uses the frozen per-attempt envelope plus 10 GiB shared overhead."
            ),
        },
        "generated_at": utc_now(),
    }
    return jobs, summary


def write_plan(
    protocol: Mapping[str, Any],
    output_dir: Path,
    prepared_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    jobs, summary = expand_protocol_jobs(protocol, prepared_manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "plan.json", summary)
    if summary["materialized"]:
        write_jsonl(output_dir / "expected.jsonl", jobs)
        summary["expected_jsonl_sha256"] = sha256_file(output_dir / "expected.jsonl")
        write_json(output_dir / "plan.json", summary)
    return summary


def _git_output(root: Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def build_code_manifest(root: Path, paths: Sequence[Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    tracked_output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if tracked_output.returncode != 0 and (root / ".git").exists():
        diagnostic = tracked_output.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {diagnostic}" if diagnostic else ""
        raise FormalError(f"git repository metadata is present but inaccessible{suffix}")
    tracked_files = (
        {
            item.decode("utf-8")
            for item in tracked_output.stdout.split(b"\0")
            if item
        }
        if tracked_output.returncode == 0
        else None
    )
    if tracked_files is not None:
        selected: set[str] = set()
        resolved_root = root.resolve()
        for raw in paths:
            path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
            try:
                relative_path = path.relative_to(resolved_root)
            except ValueError as exc:
                raise FormalError(f"code manifest path outside repository: {path}") from exc
            relative = relative_path.as_posix()
            prefix = f"{relative.rstrip('/')}/"
            matches = {
                tracked
                for tracked in tracked_files
                if tracked == relative or tracked.startswith(prefix)
            }
            _require(bool(matches), f"code manifest path has no tracked files: {path}")
            selected.update(matches)
        for relative in sorted(selected):
            blob = subprocess.run(
                ["git", "show", f"HEAD:{relative}"],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            _require(blob.returncode == 0, f"cannot read tracked code blob: {relative}")
            rows.append(
                {
                    "path": relative,
                    "bytes": len(blob.stdout),
                    "sha256": hashlib.sha256(blob.stdout).hexdigest(),
                }
            )
    else:
        for raw in paths:
            path = raw if raw.is_absolute() else root / raw
            _require(path.exists(), f"code manifest path missing: {path}")
            candidates = (
                [path]
                if path.is_file()
                else sorted(item for item in path.rglob("*") if item.is_file())
            )
            for item in candidates:
                if any(part in {".git", "__pycache__", ".pytest_cache"} for part in item.parts):
                    continue
                rows.append(
                    {
                        "path": str(item.relative_to(root)),
                        "bytes": item.stat().st_size,
                        "sha256": sha256_file(item),
                    }
                )
    dirty = bool(_git_output(root, "status", "--porcelain"))
    return {
        "schema": "waybill.formal.code-manifest/v1",
        "git_head": _git_output(root, "rev-parse", "HEAD"),
        "git_branch": _git_output(root, "branch", "--show-current"),
        "git_dirty": dirty,
        "tracked_files_only": tracked_files is not None,
        "files": rows,
        "tree_sha256": canonical_sha256(rows),
        "generated_at": utc_now(),
    }


def seal_gate_receipt(
    *, gate: str, status: str, evidence: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema": "waybill.formal.gate-receipt/v2",
        "gate": str(gate),
        "status": str(status),
        "evidence": dict(evidence),
    }
    payload["payload_sha256"] = canonical_sha256(payload)
    return payload


def validate_gate_receipts(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_gate = {str(receipt.get("gate")): receipt for receipt in receipts}
    expected = {f"RG{index}" for index in range(9)}
    _require(set(by_gate) == expected, f"gate receipt set mismatch: {sorted(by_gate)}")
    for gate, receipt in by_gate.items():
        _require(
            receipt.get("schema") == "waybill.formal.gate-receipt/v2",
            f"{gate}: unsupported gate receipt schema",
        )
        _require(isinstance(receipt.get("evidence"), dict), f"{gate}: gate evidence is missing")
        declared = str(receipt.get("payload_sha256", ""))
        unsigned = dict(receipt)
        unsigned.pop("payload_sha256", None)
        _require(declared == canonical_sha256(unsigned), f"{gate}: gate receipt hash mismatch")
    failed = [gate for gate, receipt in by_gate.items() if receipt.get("status") != "passed"]
    _require(not failed, f"formal run blocked by gates: {sorted(failed)}")
    rg6 = by_gate["RG6"].get("evidence")
    _require(
        isinstance(rg6, dict)
        and rg6.get("schema") == "waybill.formal.target-host-preflight/v2"
        and rg6.get("status") == "passed",
        "RG6 must embed a passed target-host preflight V2 receipt",
    )
    assert isinstance(rg6, dict)
    rg6_checks = rg6.get("checks")
    _require(
        isinstance(rg6_checks, dict)
        and bool(rg6_checks)
        and all(value is True for value in rg6_checks.values()),
        "RG6 target-host checks are not all true",
    )
    runtime = rg6.get("container_runtime")
    _require(
        isinstance(runtime, dict)
        and isinstance(runtime.get("sha256"), str)
        and len(runtime["sha256"]) == 64
        and runtime.get("sha256") == runtime.get("expected_sha256"),
        "RG6 container runtime hash is not exact",
    )
    assert isinstance(runtime, dict)
    _require(
        isinstance(rg6.get("container_digest"), str)
        and rg6.get("container_digest") == rg6.get("expected_container_digest"),
        "RG6 OCI image digest is not exact",
    )
    ptau = rg6.get("ptau")
    _require(
        isinstance(ptau, dict)
        and ptau.get("exists") is True
        and ptau.get("bytes") == FORMAL_PTAU_BYTES
        and ptau.get("blake2b") == FORMAL_PTAU_BLAKE2B,
        "RG6 PTAU binding is not exact",
    )
    embedded = rg6.get("embedded_release_binding")
    _require(
        isinstance(embedded, dict)
        and embedded.get("schema") == "waybill.formal.embedded-release-binding/v1"
        and _is_lower_hex(embedded.get("git_commit"), 40)
        and _is_lower_hex(embedded.get("git_tree"), 40)
        and _is_lower_hex(embedded.get("code_manifest_sha256"), 64)
        and _is_lower_hex(embedded.get("protocol_sha256"), 64),
        "RG6 embedded release binding is invalid",
    )
    return {
        "gate": "formal-launch",
        "status": "passed",
        "gate_receipts_sha256": canonical_sha256(receipts),
        "checked_at": utc_now(),
    }


def _is_sha256_digest(value: Any) -> bool:
    text = str(value)
    return text.startswith("sha256:") and _is_lower_hex(text[7:], 64)


def _digest_component(value: Any) -> str | None:
    text = str(value)
    candidate = text.rsplit("@", 1)[-1]
    return candidate if _is_sha256_digest(candidate) else None


def _embedded_release_binding(bindings: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": "waybill.formal.embedded-release-binding/v1",
        "git_commit": str(bindings.get("git_commit", "")),
        "git_tree": str(bindings.get("git_tree", "")),
        "code_manifest_sha256": str(bindings.get("code_manifest_sha256", "")),
        "protocol_sha256": str(bindings.get("protocol_sha256", "")),
    }
    _require(_is_lower_hex(payload["git_commit"], 40), "release Git commit binding is invalid")
    _require(_is_lower_hex(payload["git_tree"], 40), "release Git tree binding is invalid")
    _require(
        _is_lower_hex(payload["code_manifest_sha256"], 64),
        "release code manifest binding is invalid",
    )
    _require(
        _is_lower_hex(payload["protocol_sha256"], 64),
        "release protocol binding is invalid",
    )
    return payload


def _formal_runner_image_metadata(
    container_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    _require(
        container_manifest.get("schema") == "waybill-container-manifest/v1",
        "unsupported container manifest schema",
    )
    bindings = container_manifest.get("bindings")
    images = container_manifest.get("images")
    _require(isinstance(bindings, dict), "container manifest bindings are missing")
    _require(isinstance(images, dict), "container manifest images are missing")
    assert isinstance(bindings, dict)
    assert isinstance(images, dict)
    formal = images.get("formal-runner")
    _require(isinstance(formal, dict), "formal-runner image metadata is missing")
    assert isinstance(formal, dict)
    _require(formal.get("bindings") == bindings, "formal-runner source bindings mismatch")
    _require(
        _is_sha256_digest(formal.get("image_digest")),
        "formal-runner image digest is invalid",
    )
    _require(
        formal.get("platform") == "linux/amd64",
        "formal-runner image platform must be linux/amd64",
    )
    _require(
        formal.get("user") == "10003:10003",
        "formal-runner image user must be 10003:10003",
    )
    return dict(formal)


def _validate_materialized_plan(
    *,
    protocol: Mapping[str, Any],
    prepared_manifest: Mapping[str, Any],
    plan: Mapping[str, Any],
    expected_jobs: Sequence[Mapping[str, Any]],
    expected_jsonl_sha256: str,
) -> None:
    generated_jobs, generated_plan = expand_protocol_jobs(protocol, prepared_manifest)
    _require(generated_plan.get("materialized") is True, "formal jobs are not fully materialized")
    _require(list(expected_jobs) == generated_jobs, "expected job ledger differs from frozen protocol")
    _require(
        plan.get("expected_jsonl_sha256") == expected_jsonl_sha256,
        "plan/expected job ledger hash mismatch",
    )
    actual_summary = dict(plan)
    actual_summary.pop("generated_at", None)
    actual_summary.pop("expected_jsonl_sha256", None)
    frozen_summary = dict(generated_plan)
    frozen_summary.pop("generated_at", None)
    _require(actual_summary == frozen_summary, "plan summary differs from frozen protocol")


def _bound_regular_file(root: Path, relative: Any, *, label: str) -> Path:
    raw = Path(str(relative))
    _require(
        str(raw) not in {"", "."} and not raw.is_absolute() and ".." not in raw.parts,
        f"{label} must be a safe relative path",
    )
    current = root
    for part in raw.parts:
        current = current / part
        _require(not current.is_symlink(), f"{label} must not traverse a symlink: {raw}")
    path = (root / raw).resolve()
    _require(path.is_relative_to(root), f"{label} escapes its frozen root: {raw}")
    _require(path.is_file(), f"{label} is missing: {path}")
    return path


def _validate_prepared_artifacts(
    manifest: Mapping[str, Any], *, prepared_root: Path, corpus_root: Path
) -> None:
    _require(
        manifest.get("schema") == "waybill.formal.prepared-manifest/v1",
        "unsupported prepared manifest schema",
    )
    _require(
        manifest.get("prepared_root_label") == "WAYBILL_PREPARED_ROOT"
        and manifest.get("corpus_root_label") == "WAYBILL_CORPUS_ROOT",
        "prepared manifest root labels are not frozen",
    )
    declared_manifest_sha256 = str(manifest.get("manifest_sha256", ""))
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    _require(
        declared_manifest_sha256 == canonical_sha256(unsigned),
        "prepared manifest canonical hash mismatch",
    )
    datasets = manifest.get("datasets")
    instances = manifest.get("canonical_instances")
    _require(isinstance(datasets, list), "prepared dataset ledger is missing")
    _require(isinstance(instances, list), "canonical instance ledger is missing")
    assert isinstance(datasets, list)
    assert isinstance(instances, list)
    _require(
        [row.get("dataset") for row in datasets if isinstance(row, dict)]
        == ["tdrive", "geolife", "porto", "rome"],
        "prepared dataset order or membership mismatch",
    )
    period_count = 0
    for row in datasets:
        _require(isinstance(row, dict), "prepared dataset record is not an object")
        period_count += int(row.get("period_count", 0))
        for path_key, hash_key in (
            ("periods_path", "periods_sha256"),
            ("tariff_path", "tariff_sha256"),
        ):
            path = _bound_regular_file(
                prepared_root,
                row.get(path_key),
                label=f"prepared dataset {path_key}",
            )
            _require(sha256_file(path) == row.get(hash_key), f"prepared {path_key} hash mismatch")
    dataset_period_hashes = {
        str(row["dataset"]): str(row["periods_sha256"])
        for row in datasets
        if isinstance(row, dict)
    }
    s4_eligibility = manifest.get("s4_eligibility")
    _require(isinstance(s4_eligibility, dict), "prepared S4 eligibility artifact is missing")
    eligibility_path = _bound_regular_file(
        corpus_root,
        s4_eligibility.get("path"),
        label="prepared S4 eligibility artifact",
    )
    _require(
        sha256_file(eligibility_path) == s4_eligibility.get("sha256"),
        "prepared S4 eligibility artifact hash mismatch",
    )
    eligibility_artifact = read_json(eligibility_path)
    _require(
        eligibility_artifact.get("schema") == "waybill.formal.s4-eligibility/v1",
        "prepared S4 eligibility artifact schema is invalid",
    )
    eligibility_unsigned = dict(eligibility_artifact)
    declared_matrix_sha256 = str(eligibility_unsigned.pop("matrix_sha256", ""))
    _require(
        declared_matrix_sha256 == canonical_sha256(eligibility_unsigned),
        "prepared S4 eligibility artifact canonical hash mismatch",
    )
    _require(
        s4_eligibility.get("matrix_sha256") == declared_matrix_sha256
        and s4_eligibility.get("rows") == eligibility_artifact.get("rows"),
        "prepared S4 eligibility manifest binding mismatch",
    )
    for row in eligibility_artifact.get("rows", []):
        _require(
            str(row.get("periods_sha256")) == dataset_period_hashes.get(str(row.get("dataset"))),
            "prepared S4 eligibility period hash is not bound to the dataset ledger",
        )
    coverage: dict[tuple[str, str], set[tuple[int, int]]] = {}
    for row in instances:
        _require(isinstance(row, dict), "canonical instance record is not an object")
        path = _bound_regular_file(
            corpus_root,
            row.get("path"),
            label="canonical instance",
        )
        _require(sha256_file(path) == row.get("sha256"), "canonical instance hash mismatch")
        dataset = str(row.get("dataset", ""))
        period_id = str(row.get("period_id", ""))
        bucket_m = int(row.get("bucket_m", 0))
        radius_m = int(row.get("radius_m", 0))
        _require(dataset in {"tdrive", "geolife", "porto", "rome"}, "invalid instance dataset")
        _require(bool(period_id), "canonical instance period id is missing")
        coverage.setdefault((dataset, period_id), set()).add((bucket_m, radius_m))
    expected_grid = {
        (bucket_m, radius_m)
        for bucket_m in (100, 50, 25, 10)
        for radius_m in (50, 100, 200)
    }
    _require(
        bool(coverage)
        and all(combinations == expected_grid for combinations in coverage.values()),
        "canonical instance coverage is not exactly 12 per period",
    )
    _require(
        manifest.get("canonical_period_count") == period_count == len(coverage),
        "canonical period count mismatch",
    )
    _require(
        manifest.get("canonical_instance_count") == len(instances) == 12 * period_count,
        "canonical instance count mismatch",
    )


def _build_execution_container_binding(
    *,
    run_root: Path,
    container_manifest: Mapping[str, Any],
    gate_receipts: Sequence[Mapping[str, Any]],
    container_image: Path,
    prepared_root: Path,
    corpus_root: Path,
    ptau: Path,
    workspace_root: Path,
    shared_data_root: Path | None = None,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    _require(not container_image.is_symlink(), "Apptainer image must not be a symlink")
    container_image = container_image.resolve()
    _require(not prepared_root.is_symlink(), "prepared root must not be a symlink")
    _require(not corpus_root.is_symlink(), "formal corpus root must not be a symlink")
    _require(not ptau.is_symlink(), "PTAU must not be a symlink")
    prepared_root = prepared_root.resolve()
    corpus_root = corpus_root.resolve()
    ptau = ptau.resolve()
    workspace_root = workspace_root.resolve()
    if shared_data_root is not None:
        _require(not shared_data_root.is_symlink(), "shared data root must not be a symlink")
        shared_data_root = shared_data_root.resolve()
    _require(container_image.is_file(), f"Apptainer image is missing: {container_image}")
    _require(workspace_root.is_dir(), f"formal workspace root is missing: {workspace_root}")
    _require(prepared_root.is_dir(), f"prepared dataset root is missing: {prepared_root}")
    _require(corpus_root.is_dir(), f"formal corpus root is missing: {corpus_root}")
    _require(ptau.is_file(), f"PTAU is missing: {ptau}")
    if shared_data_root is not None:
        _require(shared_data_root.is_dir(), f"shared data root is missing: {shared_data_root}")
        for path, label in (
            (prepared_root, "prepared dataset root"),
            (corpus_root, "formal corpus root"),
            (ptau, "PTAU"),
        ):
            _require(
                path.is_relative_to(shared_data_root),
                f"{label} must be contained by the shared data root",
            )
        _require(
            not workspace_root.is_relative_to(shared_data_root)
            and not shared_data_root.is_relative_to(workspace_root),
            "shared data root must be disjoint from the writable formal workspace",
        )
    _require(
        run_root.is_relative_to(workspace_root),
        "run root must be contained by the formal workspace root",
    )
    _require(
        not container_image.is_relative_to(workspace_root),
        "Apptainer image must be outside the writable formal workspace",
    )
    for read_only_root, label in (
        (prepared_root, "prepared dataset root"),
        (corpus_root, "formal corpus root"),
    ):
        _require(
            not run_root.is_relative_to(read_only_root)
            and not read_only_root.is_relative_to(run_root),
            f"{label} must be disjoint from the writable run root",
        )
    _require(
        not prepared_root.is_relative_to(corpus_root)
        and not corpus_root.is_relative_to(prepared_root),
        "prepared dataset and formal corpus roots must be disjoint",
    )
    _require(
        not ptau.is_relative_to(run_root),
        "PTAU must be outside the writable run root",
    )
    formal_image = _formal_runner_image_metadata(container_manifest)
    release_bindings = _embedded_release_binding(formal_image["bindings"])
    rg6_receipts = [receipt for receipt in gate_receipts if receipt.get("gate") == "RG6"]
    _require(len(rg6_receipts) == 1, "run must contain exactly one RG6 receipt")
    rg6 = rg6_receipts[0].get("evidence")
    _require(isinstance(rg6, dict), "RG6 target-host evidence is missing")
    assert isinstance(rg6, dict)
    rg6_runtime = rg6.get("container_runtime")
    runtime_sha256 = sha256_file(container_image)
    _require(
        isinstance(rg6_runtime, dict)
        and rg6_runtime.get("sha256") == runtime_sha256
        and rg6_runtime.get("expected_sha256") == runtime_sha256,
        "Apptainer SIF does not match the passed RG6 receipt",
    )
    rg6_ptau = rg6.get("ptau")
    _require(
        isinstance(rg6_ptau, dict)
        and Path(str(rg6_ptau.get("path", ""))).resolve() == ptau
        and rg6_ptau.get("exists") is True
        and rg6_ptau.get("bytes") == ptau.stat().st_size == FORMAL_PTAU_BYTES
        and rg6_ptau.get("blake2b") == FORMAL_PTAU_BLAKE2B,
        "PTAU does not match the passed RG6 receipt",
    )
    assert isinstance(rg6_ptau, dict)
    image_digest = str(formal_image["image_digest"])
    _require(
        _digest_component(rg6.get("container_digest")) == image_digest
        and _digest_component(rg6.get("expected_container_digest")) == image_digest,
        "formal-runner image digest does not match the passed RG6 receipt",
    )
    _require(
        rg6.get("embedded_release_binding") == release_bindings,
        "formal-runner embedded source binding does not match the release manifest",
    )
    binding = {
        "schema": "waybill.formal.execution-container/v2",
        "container_source_root": "/work",
        "launcher": "apptainer",
        "network_mode": "none",
        "release_bindings": release_bindings,
        "release_image_digest": image_digest,
        "runtime_image_path": str(container_image),
        "runtime_image_sha256": runtime_sha256,
        "prepared_root": str(prepared_root),
        "corpus_root": str(corpus_root),
        "ptau_path": str(ptau),
        "ptau_bytes": ptau.stat().st_size,
        "ptau_blake2b": rg6_ptau["blake2b"],
        "workspace_root": str(workspace_root),
    }
    if shared_data_root is not None:
        binding["shared_data_root"] = str(shared_data_root)
    return binding


def _sealed_run_input_hashes(run_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in _SEALED_RUN_INPUTS:
        path = run_root / relative
        _require(not path.is_symlink(), f"sealed run input must not be a symlink: {relative}")
        _require(path.is_file(), f"sealed run input is missing: {relative}")
        hashes[relative] = sha256_file(path)
    return hashes


def validate_run_seal(run_root: Path) -> dict[str, Any]:
    run_root = run_root.resolve()
    run_path = run_root / "run.json"
    _require(not run_path.is_symlink(), "run seal must not be a symlink")
    run = read_json(run_path)
    _require(
        isinstance(run, dict)
        and run.get("schema") == "waybill.formal.run/v2"
        and run.get("immutable") is True,
        "unsupported or mutable formal run seal",
    )
    sealed = run.get("sealed_inputs")
    _require(
        isinstance(sealed, dict) and set(sealed) == set(_SEALED_RUN_INPUTS),
        "formal run sealed input set mismatch",
    )
    actual = _sealed_run_input_hashes(run_root)
    _require(actual == sealed, "formal run sealed input hash mismatch")
    _require(
        run.get("sealed_inputs_sha256") == canonical_sha256(actual),
        "formal run aggregate input seal mismatch",
    )
    protocol = read_json(run_root / "protocol.json")
    execution = read_json(run_root / "execution-container.json")
    _require(
        run.get("protocol_sha256") == canonical_sha256(protocol),
        "run/protocol binding mismatch",
    )
    _require(
        run.get("execution_container_sha256") == canonical_sha256(execution),
        "run/execution container binding mismatch",
    )
    return dict(run)


def _validate_run_semantics(run_root: Path) -> list[dict[str, Any]]:
    validate_run_seal(run_root)
    protocol = read_json(run_root / "protocol.json")
    validate_protocol(protocol)
    plan = read_json(run_root / "plan.json")
    prepared = read_json(run_root / "prepared_manifest.json")
    code_manifest = read_json(run_root / "code_manifest.json")
    container_manifest = read_json(run_root / "container_manifest.json")
    gate_receipts = read_json(run_root / "gate_receipts.json")
    _require(isinstance(prepared, dict), "prepared manifest is not an object")
    _require(isinstance(code_manifest, dict), "code manifest is not an object")
    _require(isinstance(container_manifest, dict), "container manifest is not an object")
    _require(isinstance(gate_receipts, list), "gate receipt ledger is not an array")
    validate_gate_receipts(gate_receipts)
    _require(
        code_manifest.get("schema") == "waybill-code-manifest/v2",
        "formal run requires a release code manifest V2",
    )
    files = code_manifest.get("files")
    _require(
        isinstance(files, list) and code_manifest.get("file_count") == len(files),
        "release code manifest file count is invalid",
    )
    formal_image = _formal_runner_image_metadata(container_manifest)
    bindings = formal_image["bindings"]
    _require(
        bindings.get("code_manifest_sha256") == canonical_sha256(code_manifest),
        "container/code manifest binding mismatch",
    )
    _require(
        bindings.get("protocol_sha256") == canonical_sha256(protocol),
        "container/protocol binding mismatch",
    )
    _require(
        bindings.get("git_commit") == code_manifest.get("git_commit")
        and bindings.get("git_tree") == code_manifest.get("git_tree"),
        "container/code Git identity binding mismatch",
    )
    execution = read_json(run_root / "execution-container.json")
    _require(
        execution.get("schema") == "waybill.formal.execution-container/v2"
        and execution.get("release_image_digest") == formal_image.get("image_digest")
        and execution.get("release_bindings") == _embedded_release_binding(bindings),
        "execution/release container binding mismatch",
    )
    expected_path = run_root / "jobs" / "expected.jsonl"
    expected_jobs = read_jsonl(expected_path)
    _validate_materialized_plan(
        protocol=protocol,
        prepared_manifest=prepared,
        plan=plan,
        expected_jobs=expected_jobs,
        expected_jsonl_sha256=sha256_file(expected_path),
    )
    return expected_jobs


def initialize_run(
    *,
    protocol: Mapping[str, Any],
    plan_dir: Path,
    output_root: Path,
    run_id: str,
    manifests: Mapping[str, Mapping[str, Any]],
    gate_receipts: Sequence[Mapping[str, Any]],
    container_runtime_image: Path,
    prepared_root: Path,
    corpus_root: Path,
    ptau: Path,
    workspace_root: Path,
    shared_data_root: Path | None = None,
) -> Path:
    validate_protocol(protocol)
    validate_gate_receipts(gate_receipts)
    _require(
        _RUN_ID_PATTERN.fullmatch(run_id) is not None,
        "run id must be a 1-128 character portable identifier",
    )
    required_manifests = {
        "code_manifest",
        "data_manifest",
        "environment",
        "container_manifest",
        "prepared_manifest",
    }
    _require(
        set(manifests) == required_manifests,
        f"run manifest set mismatch: {sorted(manifests)}",
    )
    code_manifest = manifests["code_manifest"]
    container_manifest = manifests["container_manifest"]
    _require(
        code_manifest.get("schema") == "waybill-code-manifest/v2",
        "formal run requires a release code manifest V2",
    )
    formal_image = _formal_runner_image_metadata(container_manifest)
    container_bindings = formal_image["bindings"]
    _require(
        container_bindings.get("code_manifest_sha256")
        == canonical_sha256(manifests["code_manifest"]),
        "container/code manifest binding mismatch",
    )
    _require(
        container_bindings.get("protocol_sha256") == canonical_sha256(protocol),
        "container/protocol binding mismatch",
    )
    _require(
        formal_image.get("bindings") == container_bindings,
        "formal-runner/container manifest binding mismatch",
    )
    _require(
        container_bindings.get("git_commit") == code_manifest.get("git_commit")
        and container_bindings.get("git_tree") == code_manifest.get("git_tree"),
        "container/code Git identity binding mismatch",
    )
    plan = read_json(plan_dir / "plan.json")
    expected_path = plan_dir / "expected.jsonl"
    _require(expected_path.is_file(), "expected job ledger missing")
    prepared_manifest = manifests["prepared_manifest"]
    _require(isinstance(prepared_manifest, dict), "prepared manifest is not an object")
    _require(not prepared_root.is_symlink(), "prepared root must not be a symlink")
    _require(not corpus_root.is_symlink(), "formal corpus root must not be a symlink")
    prepared_root = prepared_root.resolve()
    corpus_root = corpus_root.resolve()
    _require(prepared_root.is_dir(), f"prepared dataset root is missing: {prepared_root}")
    _require(corpus_root.is_dir(), f"formal corpus root is missing: {corpus_root}")
    _validate_prepared_artifacts(
        prepared_manifest,
        prepared_root=prepared_root,
        corpus_root=corpus_root,
    )
    _validate_materialized_plan(
        protocol=protocol,
        prepared_manifest=prepared_manifest,
        plan=plan,
        expected_jobs=read_jsonl(expected_path),
        expected_jsonl_sha256=sha256_file(expected_path),
    )
    protocol_id = f"wbfp-{canonical_sha256(protocol)[:16]}"
    workspace_root = workspace_root.resolve()
    output_root = output_root.resolve()
    _require(workspace_root.is_dir(), f"formal workspace root is missing: {workspace_root}")
    _require(
        output_root.is_relative_to(workspace_root),
        "formal output root must be inside the writable workspace",
    )
    run_root = output_root / protocol_id / run_id
    _require(not run_root.exists(), f"run directory already exists: {run_root}")
    execution_container = _build_execution_container_binding(
        run_root=run_root,
        container_manifest=container_manifest,
        gate_receipts=gate_receipts,
        container_image=container_runtime_image,
        prepared_root=prepared_root,
        corpus_root=corpus_root,
        ptau=ptau,
        workspace_root=workspace_root,
        shared_data_root=shared_data_root,
    )
    run_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = run_root.parent / f".{run_id}.initializing-{os.getpid()}"
    _require(not staging_root.exists(), f"stale run initializer exists: {staging_root}")
    try:
        staging_root.mkdir()
        write_json(staging_root / "protocol.json", protocol, exclusive=True)
        write_json(staging_root / "plan.json", plan, exclusive=True)
        write_jsonl(
            staging_root / "jobs" / "expected.jsonl",
            read_jsonl(expected_path),
            exclusive=True,
        )
        for name, payload in manifests.items():
            write_json(staging_root / f"{name}.json", payload, exclusive=True)
        write_json(staging_root / "gate_receipts.json", list(gate_receipts), exclusive=True)
        write_json(
            staging_root / "execution-container.json",
            execution_container,
            exclusive=True,
        )
        sealed_inputs = _sealed_run_input_hashes(staging_root)
        write_json(
            staging_root / "run.json",
            {
                "schema": "waybill.formal.run/v2",
                "protocol_id": protocol_id,
                "protocol_sha256": canonical_sha256(protocol),
                "run_id": run_id,
                "created_at": utc_now(),
                "execution_container_sha256": canonical_sha256(execution_container),
                "sealed_inputs": sealed_inputs,
                "sealed_inputs_sha256": canonical_sha256(sealed_inputs),
                "immutable": True,
            },
            exclusive=True,
        )
        validate_run_seal(staging_root)
        staging_root.replace(run_root)
    except Exception:
        if staging_root.exists():
            shutil.rmtree(staging_root)
        raise
    return run_root


def _attempt_paths(run_root: Path, job_id: str) -> list[Path]:
    attempt_root = run_root / "jobs" / "attempts" / job_id
    return sorted(path for path in attempt_root.glob("attempt-*") if path.is_dir())


def next_attempt(run_root: Path, job_id: str, *, max_attempts: int = 2) -> tuple[int, Path]:
    attempts = _attempt_paths(run_root, job_id)
    _require(len(attempts) < max_attempts, f"{job_id} exhausted {max_attempts} attempts")
    number = len(attempts) + 1
    path = run_root / "jobs" / "attempts" / job_id / f"attempt-{number:02d}"
    path.mkdir(parents=True, exist_ok=False)
    return number, path


def configure_execution_container(
    run_root: Path,
    *,
    container_image: Path,
    prepared_root: Path,
    corpus_root: Path,
    ptau: Path,
    workspace_root: Path,
    shared_data_root: Path | None = None,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    gate_receipts = read_json(run_root / "gate_receipts.json")
    _require(isinstance(gate_receipts, list), "run gate receipts are invalid")
    binding = _build_execution_container_binding(
        run_root=run_root,
        container_manifest=read_json(run_root / "container_manifest.json"),
        gate_receipts=gate_receipts,
        container_image=container_image,
        prepared_root=prepared_root,
        corpus_root=corpus_root,
        ptau=ptau,
        workspace_root=workspace_root,
        shared_data_root=shared_data_root,
    )
    path = run_root / "execution-container.json"
    if path.exists():
        _require(read_json(path) == binding, "execution container binding already differs")
        run_path = run_root / "run.json"
        if run_path.exists():
            validate_run_seal(run_root)
    else:
        _require(not (run_root / "run.json").exists(), "sealed run lacks execution binding")
        write_json(path, binding, exclusive=True)
    return binding


def validate_execution_container_environment(
    run_root: Path, *, root: Path
) -> dict[str, Any]:
    validate_run_seal(run_root)
    binding_path = run_root / "execution-container.json"
    _require(binding_path.is_file(), "execution container binding is missing")
    binding = read_json(binding_path)
    _require(
        isinstance(binding, dict)
        and binding.get("schema") == "waybill.formal.execution-container/v2",
        "execution container binding is invalid",
    )
    _require(os.getenv("WAYBILL_CONTAINER") == "1", "formal job is not running in its container")
    _require(
        os.getenv("WAYBILL_EXECUTION_LAUNCHER") == binding.get("launcher"),
        "formal execution launcher binding mismatch",
    )
    _require(
        os.getenv("WAYBILL_EXECUTION_IMAGE_DIGEST")
        == binding.get("release_image_digest"),
        "formal execution image digest binding mismatch",
    )
    _require(
        os.getenv("WAYBILL_EXECUTION_RUNTIME_SHA256")
        == binding.get("runtime_image_sha256"),
        "formal execution runtime hash binding mismatch",
    )
    for variable, key in (
        ("WAYBILL_PREPARED_ROOT", "prepared_root"),
        ("WAYBILL_CORPUS_ROOT", "corpus_root"),
        ("WAYBILL_PTAU", "ptau_path"),
    ):
        _require(
            os.getenv(variable) == binding.get(key),
            f"formal execution input binding mismatch: {variable}",
        )
    _require(
        root.resolve() == Path(str(binding.get("container_source_root", ""))),
        "formal source is not mounted at the frozen container path",
    )
    embedded = read_json(EMBEDDED_RELEASE_BINDING_PATH)
    _require(
        embedded == binding.get("release_bindings"),
        "embedded release source binding differs from the sealed execution binding",
    )
    return dict(binding)


@dataclass
class ExecutionReceipt:
    schema: str
    job_id: str
    attempt: int
    status: str
    command: list[str]
    started_at: str
    elapsed_ms: float
    returncode: int | None
    timed_out: bool
    max_rss_bytes: int | None
    user_cpu_sec: float | None
    system_cpu_sec: float | None
    measurement_backend: str
    stdout_tail: str
    stderr_tail: str
    error: str | None
    execution_container: dict[str, Any]
    job_sha256: str
    stage_status: str | None
    stage_outcome_class: str | None
    stage_result_sha256: str | None
    artifact_manifest_sha256: str | None


#: Longest we ever wait for a timed-out job's processes to leave on their own.
#: Every wait that follows a timeout is bounded by this value, so a timed-out
#: attempt can never report an ``elapsed_ms`` far above its ``timeout_sec``.
_TERMINATION_GRACE_SEC = 30.0


def _signal_process_group(process: subprocess.Popen[str], signal_number: int) -> bool:
    """Signal a job's whole process group; report whether the group existed.

    ``execute_job`` launches every job with ``start_new_session=True``, so the
    direct child leads its own session and process group while the launcher
    wrapper's descendants stay inside that same group.  Signalling only
    ``process.pid`` would leave those descendants running, and the drain that
    follows would then block until they exit by themselves -- which is how a
    timed-out attempt could report ``elapsed_ms`` far above its ``timeout_sec``
    and still be recorded as ``error="timeout after <n>s"``.
    """

    try:
        group = os.getpgid(process.pid)
    except ProcessLookupError:
        return False
    try:
        os.killpg(group, signal_number)
    except ProcessLookupError:
        return False
    return True


def execute_job(run_root: Path, job_id: str, *, root: Path) -> dict[str, Any]:
    execution_container = validate_execution_container_environment(run_root, root=root)
    expected_jobs = _validate_run_semantics(run_root)
    jobs = {row["job_id"]: row for row in expected_jobs}
    _require(job_id in jobs, f"unknown job id: {job_id}")
    job = jobs[job_id]
    attempt_number, attempt_dir = next_attempt(run_root, job_id)
    job_path = attempt_dir / "job.json"
    write_json(job_path, job, exclusive=True)
    command = [
        str(item).replace("{attempt_dir}", str(attempt_dir)).replace("{job_json}", str(job_path))
        for item in job["command"]
    ]
    entrypoint = root / command[1] if len(command) > 1 and command[1].startswith("script/") else None
    if entrypoint is not None:
        _require(entrypoint.is_file(), f"formal stage entrypoint missing: {entrypoint}")
    wrapped, backend = measured_command(command)
    environment = os.environ.copy()
    environment.update(
        {
            "WAYBILL_RUN_ROOT": str(run_root),
            "WAYBILL_ATTEMPT_DIR": str(attempt_dir),
            "WAYBILL_JOB_JSON": str(job_path),
            "PYTHONPATH": str(root),
        }
    )
    started_at = utc_now()
    started = time.perf_counter()
    timed_out = False
    returncode: int | None = None
    stdout = ""
    stderr = ""
    error: str | None = None
    process = subprocess.Popen(
        wrapped,
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=int(job["timeout_sec"]))
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        error = f"timeout after {job['timeout_sec']}s"
        # Signal the whole group, then escalate once, and bound every wait. A
        # bare ``process.terminate()`` reaches only the measured wrapper, so the
        # stage interpreter inside the container survives and the unbounded
        # ``communicate()`` that used to follow blocked until it finished.
        _signal_process_group(process, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=_TERMINATION_GRACE_SEC)
        except subprocess.TimeoutExpired:
            _signal_process_group(process, signal.SIGKILL)
            try:
                stdout, stderr = process.communicate(timeout=_TERMINATION_GRACE_SEC)
            except subprocess.TimeoutExpired:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                error = (
                    f"timeout after {job['timeout_sec']}s; "
                    "job process group survived SIGTERM and SIGKILL"
                )
                stdout, stderr = "", ""
        returncode = process.returncode
    time_evidence = parse_time_evidence(stderr, backend)
    if returncode and error is None:
        error = f"command exited with status {returncode}"
    stage_evidence: dict[str, Any] | None = None
    stage_result: dict[str, Any] | None = None
    stage_path = attempt_dir / "stage-result.json"
    # A timeout says the wall-clock allowance was exceeded, not that the stage
    # produced nothing. Skipping this validation whenever ``timed_out`` was set
    # discarded a stage result that had in fact completed and validated -- the
    # V14 S5 unit s5-a0e46c6ac75554e9a48f is exactly that case, and its receipt
    # ends up with ``stage_result_sha256 == null`` even though the stage result
    # on disk is a passing one. Always validate what is there; the attempt is
    # still recorded as failed below, because ``timed_out`` alone decides that.
    if stage_path.is_file():
        try:
            raw_stage_result = read_json(stage_path)
            if not isinstance(raw_stage_result, dict):
                raise FormalError("stage-result is not an object")
            stage_result = raw_stage_result
            stage_evidence = validate_stage_result(
                raw_stage_result,
                job=job,
                attempt_dir=attempt_dir,
            )
            if returncode == 0 and not timed_out:
                _require(
                    stage_evidence["status"] == "passed",
                    "stage semantic status is not passed",
                )
        except FormalError as exc:
            error = str(exc)
            stage_evidence = None
            stage_result = None
    elif returncode == 0 and not timed_out:
        error = "stage-result.json is missing"
    if timed_out and stage_evidence is not None and stage_evidence["status"] == "passed":
        # Keep the failure verdict, but make the receipt say what actually
        # happened so the evidence is not read as "the stage never produced a
        # result".
        error = (
            f"timeout after {job['timeout_sec']}s; the stage result is present and "
            f"validates as '{stage_evidence['status']}', but the attempt is recorded "
            "as failed because the timeout fired"
        )
    raw_rss = time_evidence["max_rss_bytes"]
    raw_user = time_evidence["user_cpu_sec"]
    raw_system = time_evidence["system_cpu_sec"]
    receipt = ExecutionReceipt(
        schema="waybill.formal.attempt-receipt/v2",
        job_id=job_id,
        attempt=attempt_number,
        status=(
            "passed"
            if returncode == 0 and not timed_out and error is None and stage_evidence is not None
            else "failed"
        ),
        command=command,
        started_at=started_at,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        returncode=returncode,
        timed_out=timed_out,
        max_rss_bytes=int(raw_rss) if isinstance(raw_rss, int) else None,
        user_cpu_sec=float(raw_user) if isinstance(raw_user, (int, float)) else None,
        system_cpu_sec=float(raw_system) if isinstance(raw_system, (int, float)) else None,
        measurement_backend=str(time_evidence["measurement_backend"]),
        stdout_tail=stdout[-16000:],
        stderr_tail=stderr[-16000:],
        error=error,
        execution_container=execution_container,
        job_sha256=canonical_sha256(job),
        stage_status=(
            None if stage_evidence is None else str(stage_evidence["status"])
        ),
        stage_outcome_class=(
            None
            if stage_evidence is None or stage_result is None
            else str(stage_result.get("outcome_class") or "") or None
        ),
        stage_result_sha256=(
            None if stage_evidence is None else str(stage_evidence["stage_result_sha256"])
        ),
        artifact_manifest_sha256=(
            None if stage_evidence is None else str(stage_evidence["artifact_manifest_sha256"])
        ),
    )
    payload = asdict(receipt)
    payload["receipt_sha256"] = canonical_sha256(payload)
    write_json(attempt_dir / "receipt.json", payload, exclusive=True)
    return payload


def validate_attempt_receipt(
    receipt: Mapping[str, Any],
    *,
    job: Mapping[str, Any],
    attempt_dir: Path,
) -> dict[str, Any]:
    _require(
        receipt.get("schema") == "waybill.formal.attempt-receipt/v2",
        "unsupported attempt receipt schema",
    )
    _require(receipt.get("job_id") == job.get("job_id"), "attempt receipt job id mismatch")
    _require(receipt.get("job_sha256") == canonical_sha256(job), "attempt job hash mismatch")
    attempt_run_root = attempt_dir.parents[3]
    validate_run_seal(attempt_run_root)
    expected_execution_container = read_json(
        attempt_run_root / "execution-container.json"
    )
    _require(
        receipt.get("execution_container") == expected_execution_container,
        "attempt execution container binding mismatch",
    )
    try:
        expected_attempt = int(attempt_dir.name.removeprefix("attempt-"))
    except ValueError as exc:
        raise FormalError("invalid attempt directory name") from exc
    _require(int(receipt.get("attempt", 0)) == expected_attempt, "attempt number mismatch")
    job_path = attempt_dir / "job.json"
    _require(job_path.is_file(), "attempt job.json is missing")
    stored_job = read_json(job_path)
    _require(stored_job == dict(job), "attempt job.json differs from expected job")
    expected_command = [
        str(item)
        .replace("{attempt_dir}", str(attempt_dir))
        .replace("{job_json}", str(job_path))
        for item in job["command"]
    ]
    _require(receipt.get("command") == expected_command, "attempt command mismatch")
    declared_receipt_sha256 = str(receipt.get("receipt_sha256", ""))
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    _require(
        declared_receipt_sha256 == canonical_sha256(unsigned),
        "attempt receipt canonical hash mismatch",
    )
    status = str(receipt.get("status"))
    _require(status in {"passed", "failed"}, "invalid attempt status")
    stage_path = attempt_dir / "stage-result.json"
    if receipt.get("stage_result_sha256") is not None:
        _require(stage_path.is_file(), "attempt-bound stage-result.json is missing")
        stage_result = read_json(stage_path)
        _require(isinstance(stage_result, dict), "stage-result is not an object")
        evidence = validate_stage_result(stage_result, job=job, attempt_dir=attempt_dir)
        _require(
            receipt.get("stage_result_sha256") == evidence["stage_result_sha256"],
            "attempt/stage result hash mismatch",
        )
        _require(
            receipt.get("artifact_manifest_sha256")
            == evidence["artifact_manifest_sha256"],
            "attempt/stage artifact manifest mismatch",
        )
        if receipt.get("stage_status") is not None:
            _require(
                receipt.get("stage_status") == evidence["status"],
                "attempt/stage semantic status mismatch",
            )
        if receipt.get("stage_outcome_class") is not None:
            _require(
                receipt.get("stage_outcome_class") == stage_result.get("outcome_class"),
                "attempt/stage outcome class mismatch",
            )
    if status == "passed":
        _require(receipt.get("returncode") == 0, "passed attempt has nonzero return code")
        _require(receipt.get("timed_out") is False, "passed attempt timed out")
        _require(receipt.get("error") is None, "passed attempt declares an error")
        _require(stage_path.is_file(), "passed attempt lacks stage-result.json")
        stage_result = read_json(stage_path)
        _require(isinstance(stage_result, dict), "stage-result is not an object")
        evidence = validate_stage_result(stage_result, job=job, attempt_dir=attempt_dir)
        _require(evidence["status"] == "passed", "passed attempt has failed stage semantics")
        _require(receipt.get("stage_result_sha256") is not None, "passed attempt lacks stage binding")
    return {"status": status, "receipt_sha256": declared_receipt_sha256}


def _s3_aggregate_gate(
    expected_jobs: Sequence[Mapping[str, Any]],
    selected_results: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, Any]:
    """Evaluate the frozen group-aware S3 thresholds across all instances."""

    s3_jobs = [job for job in expected_jobs if job.get("stage") == "S3"]
    if not s3_jobs:
        return {"required": False, "status": "not-applicable", "passed": True}

    result_by_job = {str(job["job_id"]): result for job, result in selected_results}
    thresholds = {
        (
            float(job["parameters"]["main_gap_max"]),
            float(job["parameters"]["all_instance_certified_share_min"]),
            float(job["parameters"]["all_instance_gap_max"]),
        )
        for job in s3_jobs
    }
    _require(len(thresholds) == 1, "S3 jobs disagree on aggregate thresholds")
    main_gap_max, certified_share_min, all_gap_max = next(iter(thresholds))
    main_gap_ppm = round(main_gap_max * 1_000_000)
    all_gap_ppm = round(all_gap_max * 1_000_000)

    rows: list[dict[str, Any]] = []
    missing_groups: list[str] = []
    malformed_groups: list[str] = []
    for job in s3_jobs:
        job_id = str(job["job_id"])
        parameters = job["parameters"]
        result = result_by_job.get(job_id)
        if result is None:
            missing_groups.append(str(parameters["group_id"]))
            continue
        receipts = result.get("bound_receipts")
        expected_group_instances = list(parameters.get("instances", []))
        if (
            not expected_group_instances
            or not isinstance(receipts, list)
            or len(receipts) != len(expected_group_instances)
        ):
            malformed_groups.append(str(parameters["group_id"]))
            continue
        receipt_by_id = {
            str(receipt.get("instance", {}).get("instance_id", "")): receipt
            for receipt in receipts
            if isinstance(receipt, dict)
        }
        if len(receipt_by_id) != len(expected_group_instances):
            malformed_groups.append(str(parameters["group_id"]))
            continue
        main_bucket = max(int(record["bucket_m"]) for record in expected_group_instances)
        for record in expected_group_instances:
            instance_id = str(record["instance_id"])
            receipt = receipt_by_id.get(instance_id)
            if receipt is None:
                malformed_groups.append(str(parameters["group_id"]))
                continue
            certified = receipt.get("status") == "certified"
            explicit_soundness_failure = (
                receipt.get("failure_class") == "soundness-failure"
            )
            lb = receipt.get("LB_cents")
            ub = receipt.get("UB_cents")
            checker_passed = bool(
                certified
                and receipt.get("lower_bound", {}).get("checker", {}).get("accepted")
            )
            direction_passed = bool(
                certified
                and receipt.get("upper_bound", {})
                .get("independent_cross_check", {})
                .get("direction_ok")
            )
            bound_order_passed = (
                certified
                and isinstance(lb, int)
                and isinstance(ub, int)
                and lb <= ub
            )
            soundness_passed = checker_passed and direction_passed and bound_order_passed
            relative_gap_ppm = receipt.get("relative_gap_ppm")
            no_timeout = not bool(receipt.get("timeout"))
            bucket_m = int(record["bucket_m"])
            main_representative = bucket_m == main_bucket
            gap_threshold_ppm = main_gap_ppm if main_representative else all_gap_ppm
            gap_passed = (
                isinstance(relative_gap_ppm, int)
                and relative_gap_ppm <= gap_threshold_ppm
            )
            gate_passed = certified and soundness_passed and no_timeout and gap_passed
            rows.append(
                {
                    "group_id": parameters["group_id"],
                    "instance_id": instance_id,
                    "bucket_m": bucket_m,
                    "radius_m": parameters["radius_m"],
                    "main_representative": main_representative,
                    "certified": certified,
                    "soundness_passed": soundness_passed,
                    "explicit_soundness_failure": explicit_soundness_failure,
                    "timeout": not no_timeout,
                    "relative_gap_ppm": relative_gap_ppm,
                    "gap_threshold_ppm": gap_threshold_ppm,
                    "gate_passed": gate_passed,
                }
            )

    expected_instances = sum(len(job["parameters"].get("instances", [])) for job in s3_jobs)
    all_receipts_present = (
        not missing_groups
        and not malformed_groups
        and len(rows) == expected_instances
    )
    fatal_soundness = [
        row["instance_id"]
        for row in rows
        if row["explicit_soundness_failure"]
        or (row["certified"] and not row["soundness_passed"])
    ]
    main_rows = [row for row in rows if row["main_representative"]]
    main_gate_passed = (
        len(main_rows) == len(s3_jobs) and all(row["gate_passed"] for row in main_rows)
    )
    certified_and_bounded = sum(row["gate_passed"] for row in rows)
    certified_share = certified_and_bounded / expected_instances if expected_instances else 0.0
    share_gate_passed = certified_share >= certified_share_min
    passed = (
        all_receipts_present
        and not fatal_soundness
        and main_gate_passed
        and share_gate_passed
    )
    return {
        "required": True,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "expected_groups": len(s3_jobs),
        "expected_instances": expected_instances,
        "evaluated_instances": len(rows),
        "missing_groups": sorted(set(missing_groups)),
        "malformed_groups": sorted(set(malformed_groups)),
        "fatal_soundness_instances": sorted(fatal_soundness),
        "main_gap_max": main_gap_max,
        "main_gate_passed": main_gate_passed,
        "all_instance_gap_max": all_gap_max,
        "certified_share_min": certified_share_min,
        "certified_and_bounded_instances": certified_and_bounded,
        "certified_and_bounded_share": certified_share,
        "share_gate_passed": share_gate_passed,
        "rows": rows,
    }


def _attempt_failure_class(attempt: Mapping[str, Any]) -> str:
    if attempt.get("status") == "invalid":
        return "invalid-receipt"
    if attempt.get("timed_out") is True:
        return "timeout"
    text = " ".join(
        str(attempt.get(key, ""))
        for key in (
            "error",
            "stderr_tail",
            "stdout_tail",
            "validation_error",
            "stage_outcome_class",
        )
    ).lower()
    if "out of memory" in text or "oom" in text or attempt.get("returncode") == 137:
        return "out-of-memory"
    if "resource-rejected" in text or "below" in text and "required" in text:
        return "resource-rejected"
    if attempt.get("returncode") not in (None, 0):
        return "nonzero-exit"
    if attempt.get("status") == "failed":
        return "failed"
    return "passed"


def _failure_summary(
    expected_jobs: Sequence[Mapping[str, Any]], units: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    jobs = {str(job["job_id"]): job for job in expected_jobs}
    breakdown: dict[tuple[str, str, str, str], int] = {}
    failure_receipts: list[dict[str, Any]] = []
    resource_rows: list[dict[str, Any]] = []
    for unit in units:
        job_id = str(unit["job_id"])
        job = jobs[job_id]
        parameters = job.get("parameters", {})
        dataset = str(parameters.get("dataset", "not-applicable"))
        unit_status = str(unit["status"])
        key = (str(job["stage"]), str(job["kind"]), dataset, unit_status)
        breakdown[key] = breakdown.get(key, 0) + 1
        for attempt in unit.get("attempts", []):
            failure_class = _attempt_failure_class(attempt)
            if attempt.get("max_rss_bytes") is not None or attempt.get("elapsed_ms") is not None:
                resource_rows.append(
                    {
                        "job_id": job_id,
                        "attempt": attempt.get("attempt"),
                        "elapsed_ms": attempt.get("elapsed_ms"),
                        "max_rss_bytes": attempt.get("max_rss_bytes"),
                        "user_cpu_sec": attempt.get("user_cpu_sec"),
                        "system_cpu_sec": attempt.get("system_cpu_sec"),
                    }
                )
            if failure_class != "passed":
                failure_receipts.append(
                    {
                        "job_id": job_id,
                        "stage": job["stage"],
                        "kind": job["kind"],
                        "dataset": dataset,
                        "attempt": attempt.get("attempt"),
                        "class": failure_class,
                        "returncode": attempt.get("returncode"),
                        "receipt_sha256": attempt.get("receipt_sha256"),
                        "stage_result_sha256": attempt.get("stage_result_sha256"),
                        "stage_outcome_class": attempt.get("stage_outcome_class"),
                        "reason": attempt.get("error")
                        or attempt.get("validation_error")
                        or "unspecified",
                    }
                )
    by_class: dict[str, int] = {}
    for row in failure_receipts:
        label = str(row["class"])
        by_class[label] = by_class.get(label, 0) + 1
    return {
        "expected_job_denominator": len(expected_jobs),
        "passed_jobs": sum(unit.get("status") == "passed" for unit in units),
        "failed_or_unresolved_jobs": sum(unit.get("status") != "passed" for unit in units),
        "by_stage_kind_dataset": [
            {
                "stage": stage,
                "kind": kind,
                "dataset": dataset,
                "status": status,
                "jobs": count,
            }
            for (stage, kind, dataset, status), count in sorted(breakdown.items())
        ],
        "failure_attempts_by_class": dict(sorted(by_class.items())),
        "failure_receipts": failure_receipts,
        "attempt_resources": resource_rows,
    }


def _scientific_summary(
    selected_results: Sequence[
        tuple[Mapping[str, Any], Mapping[str, Any], Path, Mapping[str, Any]]
    ],
) -> dict[str, Any]:
    """Create paper-fillable, receipt-bound rows without bulky raw artifacts."""

    excluded = {
        "artifacts",
        "artifact_manifest_sha256",
        "bound_receipts",
        "host",
        "job_id",
        "job_sha256",
        "outcomes",
        "overlap_checks",
        "result_sha256",
        "schema",
        "stderr_tail",
        "stdout_tail",
        "trials",
    }
    rows: list[dict[str, Any]] = []
    for job, result, attempt_dir, attempt_receipt in selected_results:
        metrics = {
            key: value
            for key, value in result.items()
            if key not in excluded and key != "status"
        }
        if job.get("stage") == "S2" and job.get("kind") == "main":
            raw_path = result.get("proof_receipt")
            if raw_path:
                proof_path = Path(str(raw_path))
                proof_path = (
                    proof_path if proof_path.is_absolute() else attempt_dir / proof_path
                ).resolve()
                _require(
                    proof_path.is_relative_to(attempt_dir.resolve())
                    and proof_path.is_file()
                    and not proof_path.is_symlink(),
                    "selected S2 proof receipt escapes its validated attempt",
                )
                proof_receipt = read_json(proof_path)
                metrics["proof_metrics"] = proof_receipt.get("metrics", {})
                metrics["proof_receipt_status"] = proof_receipt.get("status")
                metrics["proof_receipt_sha256"] = sha256_file(proof_path)
        rows.append(
            {
                "job_id": job["job_id"],
                "stage": job["stage"],
                "kind": job["kind"],
                "parameters": job.get("parameters", {}),
                "selected_attempt": attempt_receipt.get("attempt"),
                "attempt_receipt_sha256": attempt_receipt.get("receipt_sha256"),
                "stage_result_sha256": result.get("result_sha256"),
                "metrics": metrics,
            }
        )
    by_stage: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for row in rows:
        by_stage[str(row["stage"])] = by_stage.get(str(row["stage"]), 0) + 1
        key = f"{row['stage']}/{row['kind']}"
        by_kind[key] = by_kind.get(key, 0) + 1
    seed_groups: dict[str, list[dict[str, Any]]] = {}
    seed_group_metadata: dict[str, dict[str, Any]] = {}
    for row in rows:
        parameters = dict(row["parameters"])
        if "seed" not in parameters:
            continue
        seed = int(parameters.pop("seed"))
        group_metadata = {
            "stage": row["stage"],
            "kind": row["kind"],
            "parameters_without_seed": parameters,
        }
        key = canonical_sha256(group_metadata)
        seed_group_metadata[key] = group_metadata
        seed_groups.setdefault(key, []).append(
            {"seed": seed, "metrics": row["metrics"]}
        )
    cross_seed: list[dict[str, Any]] = []
    for key, items in sorted(seed_groups.items()):
        numeric_keys = set.intersection(
            *[
                {
                    name
                    for name, value in item["metrics"].items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                }
                for item in items
            ]
        )
        numeric_summary = {}
        for name in sorted(numeric_keys):
            values = [float(item["metrics"][name]) for item in items]
            numeric_summary[name] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        cross_seed.append(
            {
                **seed_group_metadata[key],
                "seeds": sorted(item["seed"] for item in items),
                "seed_count": len(items),
                "numeric_metrics": numeric_summary,
            }
        )
    return {
        "schema": "waybill.formal.scientific-aggregate/v1",
        "claim_boundary": (
            "Rows are deterministic summaries of selected immutable attempts. "
            "S1 is formula-level trace mechanism sensitivity; S5 handler is "
            "in-process FastAPI/SQLite and is not deployed PostgreSQL load."
        ),
        "selected_job_count": len(rows),
        "by_stage": dict(sorted(by_stage.items())),
        "by_stage_kind": dict(sorted(by_kind.items())),
        "cross_seed_rule": (
            "every seed plus median/min/max across identical non-seed parameters"
        ),
        "cross_seed_groups": cross_seed,
        "rows": rows,
    }


def merge_run(run_root: Path) -> dict[str, Any]:
    validate_run_seal(run_root)
    expected = read_jsonl(run_root / "jobs" / "expected.jsonl")
    units: list[dict[str, Any]] = []
    missing: list[str] = []
    unresolved: list[str] = []
    selected_results: list[
        tuple[Mapping[str, Any], Mapping[str, Any], Path, Mapping[str, Any]]
    ] = []
    for job in expected:
        job_id = str(job["job_id"])
        attempts: list[dict[str, Any]] = []
        valid_attempts: list[tuple[dict[str, Any], Path]] = []
        for attempt_dir in _attempt_paths(run_root, job_id):
            receipt_path = attempt_dir / "receipt.json"
            if receipt_path.is_file():
                receipt = read_json(receipt_path)
                try:
                    _require(isinstance(receipt, dict), "attempt receipt is not an object")
                    validate_attempt_receipt(receipt, job=job, attempt_dir=attempt_dir)
                    attempts.append(receipt)
                    valid_attempts.append((receipt, attempt_dir))
                except FormalError as exc:
                    attempts.append(
                        {
                            "schema": "waybill.formal.invalid-attempt/v1",
                            "job_id": job_id,
                            "attempt_dir": str(attempt_dir),
                            "status": "invalid",
                            "validation_error": str(exc),
                        }
                    )
        if not attempts:
            missing.append(job_id)
            units.append({"job_id": job_id, "status": "missing", "attempts": []})
            continue
        first_success_pair = next(
            (pair for pair in valid_attempts if pair[0].get("status") == "passed"),
            None,
        )
        first_success = first_success_pair[0] if first_success_pair else None
        if first_success is None:
            unresolved.append(job_id)
        elif first_success_pair is not None:
            selected_results.append(
                (
                    job,
                    read_json(first_success_pair[1] / "stage-result.json"),
                    first_success_pair[1],
                    first_success,
                )
            )
        units.append(
            {
                "job_id": job_id,
                "status": "passed" if first_success else "unresolved",
                "selected_attempt": first_success.get("attempt") if first_success else None,
                "attempts": attempts,
            }
        )
    s3_gate = _s3_aggregate_gate(
        expected,
        [
            (job, result)
            for job, result, _attempt_dir, _receipt in selected_results
            if job.get("stage") == "S3"
        ],
    )
    passed = (
        not missing
        and not unresolved
        and len(units) == len(expected)
        and s3_gate["passed"] is True
    )
    failure_summary = _failure_summary(expected, units)
    scientific_summary = _scientific_summary(selected_results)
    write_json(run_root / "failure-summary.json", failure_summary)
    write_json(run_root / "scientific-aggregate.json", scientific_summary)
    aggregate = {
        "schema": "waybill.formal.aggregate/v1",
        "status": "passed" if passed else "failed",
        "expected_jobs": len(expected),
        "passed_jobs": sum(unit["status"] == "passed" for unit in units),
        "missing_jobs": missing,
        "unresolved_jobs": unresolved,
        "stage_gates": {"S3": s3_gate},
        "failure_summary": failure_summary,
        "failure_summary_sha256": sha256_file(run_root / "failure-summary.json"),
        "scientific_summary": scientific_summary,
        "scientific_summary_sha256": sha256_file(
            run_root / "scientific-aggregate.json"
        ),
        "units": units,
        "generated_at": utc_now(),
    }
    aggregate["aggregate_sha256"] = canonical_sha256(aggregate)
    write_json(run_root / "aggregate.json", aggregate)
    write_json(
        run_root / "status.json",
        {
            "schema": "waybill.formal.status/v1",
            "status": aggregate["status"],
            "aggregate_sha256": aggregate["aggregate_sha256"],
            "validator": "waybill_formal.core.merge_run",
            "generated_at": utc_now(),
        },
    )
    return aggregate


def resume_job_ids(run_root: Path, *, max_attempts: int = 2) -> list[str]:
    validate_run_seal(run_root)
    expected = read_jsonl(run_root / "jobs" / "expected.jsonl")
    result: list[str] = []
    for job in expected:
        job_id = str(job["job_id"])
        receipts = [
            (path, read_json(path / "receipt.json"))
            for path in _attempt_paths(run_root, job_id)
            if (path / "receipt.json").is_file()
        ]
        valid_success = False
        for attempt_dir, receipt in receipts:
            try:
                _require(isinstance(receipt, dict), "attempt receipt is not an object")
                validate_attempt_receipt(receipt, job=job, attempt_dir=attempt_dir)
                valid_success = valid_success or receipt.get("status") == "passed"
            except FormalError:
                continue
        if valid_success:
            continue
        if len(receipts) < max_attempts:
            result.append(job_id)
    return result


def render_slurm_array(
    run_root: Path,
    output_path: Path,
    *,
    container_image: Path,
    prepared_root: Path,
    corpus_root: Path,
    ptau: Path,
    workspace_root: Path,
    shared_data_root: Path | None = None,
    stage: str | None = None,
    kind: str | None = None,
) -> None:
    binding = configure_execution_container(
        run_root,
        container_image=container_image,
        prepared_root=prepared_root,
        corpus_root=corpus_root,
        ptau=ptau,
        workspace_root=workspace_root,
        shared_data_root=shared_data_root,
    )
    jobs = read_jsonl(run_root / "jobs" / "expected.jsonl")
    if stage is not None:
        jobs = [job for job in jobs if job.get("stage") == stage]
    if kind is not None:
        jobs = [job for job in jobs if job.get("kind") == kind]
    count = len(jobs)
    _require(count > 0, "cannot render an empty Slurm array")
    ledger_path = output_path.with_suffix(output_path.suffix + ".jobids")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        "".join(str(job["job_id"]) + "\n" for job in jobs),
        encoding="utf-8",
    )
    cpus = max(int(job.get("resource", {}).get("cpus", 1)) for job in jobs)
    memory_gib = max(int(job.get("resource", {}).get("memory_gib", 1)) for job in jobs)
    timeout_sec = max(int(job.get("timeout_sec", 3600)) for job in jobs)
    hours = max(1, (timeout_sec + 3599) // 3600)
    shared_root = binding.get("shared_data_root")
    if shared_root is not None:
        mount_variables = f"SHARED_DATA_ROOT={json.dumps(str(shared_root))}\n"
        read_only_binds = '  --bind "$SHARED_DATA_ROOT:$SHARED_DATA_ROOT:ro" \\\n'
    else:
        mount_variables = ""
        read_only_binds = (
            '  --bind "$PREPARED_ROOT:$PREPARED_ROOT:ro" \\\n'
            '  --bind "$CORPUS_ROOT:$CORPUS_ROOT:ro" \\\n'
            '  --bind "$PTAU_PATH:$PTAU_PATH:ro" \\\n'
        )
    script = f"""#!/usr/bin/env bash
set -euo pipefail
#SBATCH --array=0-{count - 1}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={memory_gib}G
#SBATCH --time={hours}:00:00

RUN_ROOT={json.dumps(str(run_root))}
JOB_LEDGER={json.dumps(str(ledger_path))}
CONTAINER_IMAGE={json.dumps(str(binding["runtime_image_path"]))}
CONTAINER_RUNTIME_SHA256={json.dumps(str(binding["runtime_image_sha256"]))}
CONTAINER_IMAGE_DIGEST={json.dumps(str(binding["release_image_digest"]))}
PREPARED_ROOT={json.dumps(str(binding["prepared_root"]))}
CORPUS_ROOT={json.dumps(str(binding["corpus_root"]))}
PTAU_PATH={json.dumps(str(binding["ptau_path"]))}
{mount_variables}JOB_ID=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$JOB_LEDGER")
test -n "$JOB_ID"
test "$(sha256sum "$CONTAINER_IMAGE" | awk '{{print $1}}')" = "$CONTAINER_RUNTIME_SHA256"
command -v apptainer >/dev/null
exec apptainer exec \
  --containall --cleanenv --no-home --no-mount hostfs \
  --net --network none \
  --bind "$RUN_ROOT:$RUN_ROOT:rw" \
{read_only_binds}  --pwd /work \
  --env WAYBILL_CONTAINER=1 \
  --env WAYBILL_EXECUTION_LAUNCHER=apptainer \
  --env "WAYBILL_EXECUTION_IMAGE_DIGEST=$CONTAINER_IMAGE_DIGEST" \
  --env "WAYBILL_EXECUTION_RUNTIME_SHA256=$CONTAINER_RUNTIME_SHA256" \
  --env "WAYBILL_PREPARED_ROOT=$PREPARED_ROOT" \
  --env "WAYBILL_CORPUS_ROOT=$CORPUS_ROOT" \
  --env "WAYBILL_PTAU=$PTAU_PATH" \
  "$CONTAINER_IMAGE" \
  python script/waybill_formal.py run-job --run-root "$RUN_ROOT" --job-id "$JOB_ID"
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(script, encoding="utf-8")
    output_path.chmod(0o755)


def command_output(
    command: Sequence[str],
    *,
    timeout_sec: int = 60,
    allowed_returncodes: Iterable[int] = (0,),
) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            list(command),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return proc.returncode in frozenset(allowed_returncodes), proc.stdout.strip()


def tool_version(
    command: Sequence[str],
    *,
    allowed_returncodes: Iterable[int] = (0,),
) -> str | None:
    succeeded, output = command_output(
        command,
        allowed_returncodes=allowed_returncodes,
    )
    return output.splitlines()[0].strip() if succeeded and output else None


def host_preflight(
    *,
    root: Path,
    protocol: Mapping[str, Any],
    workspace: Path,
    ptau: Path | None = None,
    container_digest: str | None = None,
    expected_container_digest: str | None = None,
    container_runtime_image: Path | None = None,
    expected_container_runtime_sha256: str | None = None,
    required_workspace_gib: int = 500,
) -> dict[str, Any]:
    validate_protocol(protocol)
    _require(int(required_workspace_gib) > 0, "required workspace must be positive")
    host = collect_host_evidence(workspace)
    apptainer_version = tool_version(["apptainer", "--version"])
    runtime_path = container_runtime_image.resolve() if container_runtime_image else None
    runtime_safe = bool(
        runtime_path
        and runtime_path.is_file()
        and container_runtime_image is not None
        and not container_runtime_image.is_symlink()
    )
    runtime_sha256 = sha256_file(runtime_path) if runtime_safe and runtime_path else None
    runtime_secure = False
    runtime_outside_workspace = False
    if runtime_safe and runtime_path:
        image_stat = runtime_path.stat()
        parent_stat = runtime_path.parent.stat()
        runtime_secure = (
            image_stat.st_uid == 0
            and parent_stat.st_uid == 0
            and image_stat.st_mode & 0o022 == 0
            and parent_stat.st_mode & 0o022 == 0
        )
        runtime_outside_workspace = not runtime_path.is_relative_to(workspace.resolve())
    container_versions: dict[str, str | None] = {
        "python": None,
        "node": None,
        "npm": None,
        "circom": None,
        "snarkjs": None,
    }
    embedded_release_binding: dict[str, Any] | None = None
    container_config_valid = False
    if apptainer_version and runtime_safe and runtime_path:
        prefix = [
            "apptainer",
            "exec",
            "--containall",
            "--cleanenv",
            "--no-home",
            "--no-mount",
            "hostfs",
            "--net",
            "--network",
            "none",
            "--pwd",
            "/work",
            str(runtime_path),
        ]
        container_versions = {
            "python": tool_version([*prefix, "python", "--version"]),
            "node": tool_version([*prefix, "node", "--version"]),
            "npm": tool_version(
                [
                    *prefix,
                    "sh",
                    "-c",
                    "if command -v npm >/dev/null; then npm --version; else echo absent; fi",
                ]
            ),
            "circom": tool_version([*prefix, "circom", "--version"]),
            # snarkjs 0.7.6 prints its exact version and usage, then exits 99.
            # Accept only that documented CLI outcome here; the version string
            # is still checked exactly below.
            "snarkjs": tool_version(
                [*prefix, "snarkjs", "--version"],
                allowed_returncodes=(0, 99),
            ),
        }
        binding_ok, binding_output = command_output(
            [*prefix, "cat", str(EMBEDDED_RELEASE_BINDING_PATH)]
        )
        if binding_ok:
            try:
                parsed_binding = json.loads(binding_output)
            except json.JSONDecodeError:
                parsed_binding = None
            if isinstance(parsed_binding, dict):
                embedded_release_binding = parsed_binding
        container_config_valid, _config_output = command_output(
            [*prefix, "python", "/work/script/waybill_formal.py", "validate-config"],
            timeout_sec=120,
        )
    checks = {
        "linux": platform.system() == "Linux",
        "x86_64": platform.machine() in {"x86_64", "amd64"},
        "memory_at_least_32_gib": int(host.get("physical_memory_bytes") or 0) >= 32 * 1024**3,
        "workspace_free_meets_frozen_requirement": (
            int(host["disk"]["free_bytes"]) >= int(required_workspace_gib) * 1024**3
        ),
        "apptainer_available": bool(apptainer_version),
        "container_runtime_present_and_regular": runtime_safe,
        "container_runtime_root_owned_and_not_group_world_writable": runtime_secure,
        "container_runtime_outside_writable_workspace": runtime_outside_workspace,
        "container_runtime_sha256_matches": bool(
            runtime_sha256
            and expected_container_runtime_sha256
            and runtime_sha256 == expected_container_runtime_sha256
        ),
        "container_python_3_12": bool(
            container_versions["python"] and "3.12" in container_versions["python"]
        ),
        "container_node_26_5_1": container_versions["node"] == "v26.5.1",
        "container_npm_absent": container_versions["npm"] == "absent",
        "container_circom_2_1_9": container_versions["circom"]
        == "circom compiler 2.1.9",
        "container_snarkjs_0_7_6": bool(
            container_versions["snarkjs"]
            and "snarkjs@0.7.6" in container_versions["snarkjs"]
        ),
        "container_embeds_frozen_waybill_source": container_config_valid,
        "container_embedded_protocol_matches": bool(
            embedded_release_binding
            and embedded_release_binding.get("schema")
            == "waybill.formal.embedded-release-binding/v1"
            and embedded_release_binding.get("protocol_sha256")
            == canonical_sha256(protocol)
        ),
        "container_digest_matches": bool(
            container_digest
            and expected_container_digest
            and container_digest == expected_container_digest
        ),
    }
    ptau_record: dict[str, Any] | None = None
    if ptau is not None:
        ptau_record = {
            "path": str(ptau),
            "exists": ptau.is_file(),
            "bytes": ptau.stat().st_size if ptau.is_file() else None,
            "blake2b": None,
        }
        if ptau.is_file():
            digest = hashlib.blake2b()
            with ptau.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            ptau_record["blake2b"] = digest.hexdigest()
            checks["ptau_exact"] = (
                ptau.stat().st_size == FORMAL_PTAU_BYTES
                and ptau_record["blake2b"] == FORMAL_PTAU_BLAKE2B
            )
    else:
        checks["ptau_exact"] = False
    passed = all(checks.values())
    return {
        "gate": "RG6",
        "schema": "waybill.formal.target-host-preflight/v2",
        "status": "passed" if passed else "blocked-on-target",
        "checks": checks,
        "host": host,
        "versions": {
            "apptainer": apptainer_version,
            "container": container_versions,
        },
        "container_runtime": {
            "path": str(runtime_path) if runtime_path else None,
            "sha256": runtime_sha256,
            "expected_sha256": expected_container_runtime_sha256,
        },
        "embedded_release_binding": embedded_release_binding,
        "ptau": ptau_record,
        "container_digest": container_digest,
        "expected_container_digest": expected_container_digest,
        "required_workspace_gib": int(required_workspace_gib),
        "git_head": _git_output(root, "rev-parse", "HEAD"),
        "checked_at": utc_now(),
    }
