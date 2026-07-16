"""Fail-closed infrastructure for WayBill paper-grade server experiments."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from common.resource_probe import collect_host_evidence, measured_command, parse_time_evidence


class FormalError(RuntimeError):
    """Raised when a formal gate must fail closed."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


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
        "node": "26.0.0",
        "circom": "2.1.9",
        "snarkjs": "0.7.6",
        "circomlib": "2.0.5",
        "architecture": "linux-x86_64",
    }
    for key, expected in expected_toolchain.items():
        _require(str(toolchain.get(key)) == expected, f"toolchain {key} must be {expected}")
    stages = protocol.get("stages", {})
    _require(set(stages) == {"S1", "S2", "S3", "S4", "S5"}, "protocol must define S1-S5")
    _require(int(stages["S2"].get("measured_trials", 0)) == 10, "S2 requires 10 measured trials")
    _require(int(stages["S3"].get("timeout_sec", 0)) == 7200, "S3 timeout must be 7200 seconds")
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
        "command": [sys.executable, f"script/run_waybill_{stage.lower()}_formal_unit.py"],
    }


def _expand_s1(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S1"]
    jobs: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = [{"scenario": "natural"}]
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
    contexts = [{"context": "natural"}]
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


def _expand_s3(
    protocol: Mapping[str, Any], prepared_manifest: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S3"]
    instances = _prepared_instance_rows(prepared_manifest)
    return [
        _job(
            "S3",
            "certified-bound",
            {
                "instance_id": instance["instance_id"],
                "instance_path": instance["path"],
                "instance_sha256": instance.get("sha256"),
                "bucket_m": instance["bucket_m"],
                "radius_m": instance["radius_m"],
                "oracle_max_fixes": spec["oracle_max_fixes"],
            },
            spec,
        )
        for instance in instances
    ]


def _expand_s4(protocol: Mapping[str, Any]) -> list[dict[str, Any]]:
    spec = protocol["stages"]["S4"]
    return [
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
    ]


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
            "charger",
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
        "S4": _expand_s4(protocol),
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
        "S3_job_count_formula": "12 * canonical_period_count",
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
        stderr=subprocess.DEVNULL,
        check=False,
    )
    tracked_files = (
        {
            item.decode("utf-8")
            for item in tracked_output.stdout.split(b"\0")
            if item
        }
        if tracked_output.returncode == 0
        else None
    )
    for raw in paths:
        path = raw if raw.is_absolute() else root / raw
        _require(path.exists(), f"code manifest path missing: {path}")
        candidates = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
        for item in candidates:
            if any(part in {".git", "__pycache__", ".pytest_cache"} for part in item.parts):
                continue
            relative = str(item.relative_to(root))
            if tracked_files is not None and relative not in tracked_files:
                continue
            rows.append(
                {
                    "path": relative,
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


def validate_gate_receipts(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_gate = {str(receipt.get("gate")): receipt for receipt in receipts}
    expected = {f"RG{index}" for index in range(9)}
    _require(set(by_gate) == expected, f"gate receipt set mismatch: {sorted(by_gate)}")
    failed = [gate for gate, receipt in by_gate.items() if receipt.get("status") != "passed"]
    _require(not failed, f"formal run blocked by gates: {sorted(failed)}")
    return {
        "gate": "formal-launch",
        "status": "passed",
        "gate_receipts_sha256": canonical_sha256(receipts),
        "checked_at": utc_now(),
    }


def initialize_run(
    *,
    protocol: Mapping[str, Any],
    plan_dir: Path,
    output_root: Path,
    run_id: str,
    manifests: Mapping[str, Mapping[str, Any]],
    gate_receipts: Sequence[Mapping[str, Any]],
) -> Path:
    validate_protocol(protocol)
    validate_gate_receipts(gate_receipts)
    plan = read_json(plan_dir / "plan.json")
    _require(plan.get("materialized") is True, "formal jobs are not fully materialized")
    expected_path = plan_dir / "expected.jsonl"
    _require(expected_path.is_file(), "expected job ledger missing")
    protocol_id = f"wbfp-{canonical_sha256(protocol)[:16]}"
    run_root = output_root / protocol_id / run_id
    _require(not run_root.exists(), f"run directory already exists: {run_root}")
    run_root.mkdir(parents=True)
    write_json(run_root / "protocol.json", protocol, exclusive=True)
    write_json(run_root / "plan.json", plan, exclusive=True)
    write_jsonl(run_root / "jobs" / "expected.jsonl", read_jsonl(expected_path), exclusive=True)
    for name, payload in manifests.items():
        write_json(run_root / f"{name}.json", payload, exclusive=True)
    write_json(run_root / "gate_receipts.json", list(gate_receipts), exclusive=True)
    write_json(
        run_root / "run.json",
        {
            "schema": "waybill.formal.run/v1",
            "protocol_id": protocol_id,
            "protocol_sha256": canonical_sha256(protocol),
            "run_id": run_id,
            "created_at": utc_now(),
            "immutable": True,
        },
        exclusive=True,
    )
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


def execute_job(run_root: Path, job_id: str, *, root: Path) -> dict[str, Any]:
    jobs = {row["job_id"]: row for row in read_jsonl(run_root / "jobs" / "expected.jsonl")}
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
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        returncode = process.returncode
    time_evidence = parse_time_evidence(stderr, backend)
    if returncode and error is None:
        error = f"command exited with status {returncode}"
    raw_rss = time_evidence["max_rss_bytes"]
    raw_user = time_evidence["user_cpu_sec"]
    raw_system = time_evidence["system_cpu_sec"]
    receipt = ExecutionReceipt(
        schema="waybill.formal.attempt-receipt/v1",
        job_id=job_id,
        attempt=attempt_number,
        status="passed" if returncode == 0 and not timed_out else "failed",
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
    )
    payload = asdict(receipt)
    write_json(attempt_dir / "receipt.json", payload, exclusive=True)
    return payload


def merge_run(run_root: Path) -> dict[str, Any]:
    expected = read_jsonl(run_root / "jobs" / "expected.jsonl")
    units: list[dict[str, Any]] = []
    missing: list[str] = []
    unresolved: list[str] = []
    for job in expected:
        job_id = str(job["job_id"])
        attempts: list[dict[str, Any]] = []
        for attempt_dir in _attempt_paths(run_root, job_id):
            receipt_path = attempt_dir / "receipt.json"
            if receipt_path.is_file():
                attempts.append(read_json(receipt_path))
        if not attempts:
            missing.append(job_id)
            units.append({"job_id": job_id, "status": "missing", "attempts": []})
            continue
        first_success = next(
            (attempt for attempt in attempts if attempt.get("status") == "passed"),
            None,
        )
        if first_success is None:
            unresolved.append(job_id)
        units.append(
            {
                "job_id": job_id,
                "status": "passed" if first_success else "unresolved",
                "selected_attempt": first_success.get("attempt") if first_success else None,
                "attempts": attempts,
            }
        )
    passed = not missing and not unresolved and len(units) == len(expected)
    aggregate = {
        "schema": "waybill.formal.aggregate/v1",
        "status": "passed" if passed else "failed",
        "expected_jobs": len(expected),
        "passed_jobs": sum(unit["status"] == "passed" for unit in units),
        "missing_jobs": missing,
        "unresolved_jobs": unresolved,
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
    expected = read_jsonl(run_root / "jobs" / "expected.jsonl")
    result: list[str] = []
    for job in expected:
        job_id = str(job["job_id"])
        receipts = [
            read_json(path / "receipt.json")
            for path in _attempt_paths(run_root, job_id)
            if (path / "receipt.json").is_file()
        ]
        if any(receipt.get("status") == "passed" for receipt in receipts):
            continue
        if len(receipts) < max_attempts:
            result.append(job_id)
    return result


def render_slurm_array(
    run_root: Path,
    output_path: Path,
    *,
    stage: str | None = None,
    kind: str | None = None,
) -> None:
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
    script = f"""#!/usr/bin/env bash
set -euo pipefail
#SBATCH --array=0-{count - 1}
#SBATCH --cpus-per-task={cpus}
#SBATCH --mem={memory_gib}G
#SBATCH --time={hours}:00:00

RUN_ROOT={json.dumps(str(run_root))}
JOB_LEDGER={json.dumps(str(ledger_path))}
JOB_ID=$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$JOB_LEDGER")
test -n "$JOB_ID"
python script/waybill_formal.py run-job --run-root "$RUN_ROOT" --job-id "$JOB_ID"
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(script, encoding="utf-8")
    output_path.chmod(0o755)


def tool_version(command: Sequence[str]) -> str | None:
    try:
        proc = subprocess.run(
            list(command),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError:
        return None
    return proc.stdout.splitlines()[0].strip() if proc.stdout else None


def host_preflight(
    *,
    root: Path,
    protocol: Mapping[str, Any],
    workspace: Path,
    ptau: Path | None = None,
    container_digest: str | None = None,
    expected_container_digest: str | None = None,
    required_workspace_gib: int = 500,
) -> dict[str, Any]:
    validate_protocol(protocol)
    _require(int(required_workspace_gib) > 0, "required workspace must be positive")
    host = collect_host_evidence(workspace)
    versions = {
        "python": tool_version([sys.executable, "--version"]),
        "node": tool_version(["node", "--version"]),
        "npm": tool_version(["npm", "--version"]),
        "circom": tool_version(["circom", "--version"]),
        "snarkjs": tool_version(["snarkjs", "--version"]),
    }
    checks = {
        "linux": platform.system() == "Linux",
        "x86_64": platform.machine() in {"x86_64", "amd64"},
        "memory_at_least_32_gib": int(host.get("physical_memory_bytes") or 0) >= 32 * 1024**3,
        "workspace_free_meets_frozen_requirement": (
            int(host["disk"]["free_bytes"]) >= int(required_workspace_gib) * 1024**3
        ),
        "python_3_12": bool(versions["python"] and "3.12" in versions["python"]),
        "node_26_0_0": versions["node"] == "v26.0.0",
        "circom_2_1_9": versions["circom"] == "circom compiler 2.1.9",
        "snarkjs_0_7_6": bool(versions["snarkjs"] and "snarkjs@0.7.6" in versions["snarkjs"]),
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
                ptau.stat().st_size == 4_831_921_304
                and ptau_record["blake2b"]
                == "0d64f63dba1a6f11139df765cb690da69d9b2f469a1ddd0de5e4aa628abb28f7"
                "87f04c6a5fb84a235ec5ea7f41d0548746653ecab0559add658a83502d1cb21b"
            )
    else:
        checks["ptau_exact"] = False
    passed = all(checks.values())
    return {
        "gate": "RG6",
        "schema": "waybill.formal.target-host-preflight/v1",
        "status": "passed" if passed else "blocked-on-target",
        "checks": checks,
        "host": host,
        "versions": versions,
        "ptau": ptau_record,
        "container_digest": container_digest,
        "expected_container_digest": expected_container_digest,
        "required_workspace_gib": int(required_workspace_gib),
        "git_head": _git_output(root, "rev-parse", "HEAD"),
        "checked_at": utc_now(),
    }
