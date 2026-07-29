"""Shared helpers for one immutable formal job attempt."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .core import (
    FormalError,
    build_stage_artifact_manifest,
    canonical_sha256,
    read_json,
    write_json,
)


def load_job_environment() -> tuple[dict[str, Any], Path, Path]:
    job_path = Path(os.environ.get("WAYBILL_JOB_JSON", ""))
    attempt_dir = Path(os.environ.get("WAYBILL_ATTEMPT_DIR", ""))
    run_root = Path(os.environ.get("WAYBILL_RUN_ROOT", ""))
    if not job_path.is_file() or not attempt_dir.is_dir() or not run_root.is_dir():
        raise FormalError("formal stage requires WAYBILL_JOB_JSON, WAYBILL_ATTEMPT_DIR, and WAYBILL_RUN_ROOT")
    job = read_json(job_path)
    if not isinstance(job, dict):
        raise FormalError("formal job is not a JSON object")
    return job, attempt_dir, run_root


def load_prepared_manifest(run_root: Path) -> dict[str, Any]:
    path = run_root / "prepared_manifest.json"
    if not path.is_file():
        override = os.environ.get("WAYBILL_PREPARED_MANIFEST")
        path = Path(override) if override else path
    if not path.is_file():
        raise FormalError("prepared_manifest.json is required for formal stage execution")
    payload = read_json(path)
    if payload.get("schema") != "waybill.formal.prepared-manifest/v1":
        raise FormalError("unsupported prepared manifest schema")
    return payload


def prepared_dataset(
    manifest: Mapping[str, Any], dataset: str, *, prepared_root: Path | None = None
) -> dict[str, Any]:
    rows = manifest.get("datasets", [])
    matches = [row for row in rows if row.get("dataset") == dataset]
    if len(matches) != 1:
        raise FormalError(f"prepared manifest must contain exactly one {dataset} record")
    row = dict(matches[0])
    root_label = str(manifest.get("prepared_root_label", ""))
    root_value = os.environ.get(root_label) if root_label else None
    root = prepared_root or (Path(root_value) if root_value else None)
    if root is None:
        raise FormalError("prepared dataset root is not bound into the formal runtime")
    for key in ("periods_path", "tariff_path"):
        path = Path(str(row[key]))
        row[key] = path if path.is_absolute() else root / path
    return row


def finish_stage(
    *,
    job: Mapping[str, Any],
    attempt_dir: Path,
    payload: Mapping[str, Any],
) -> None:
    artifacts = build_stage_artifact_manifest(attempt_dir)
    result = {
        **dict(payload),
        "schema": "waybill.formal.stage-result/v2",
        "job_id": job["job_id"],
        "stage": job["stage"],
        "kind": job["kind"],
        "job_sha256": canonical_sha256(job),
        "artifacts": artifacts,
        "artifact_manifest_sha256": canonical_sha256(artifacts),
    }
    if result.get("status") not in {"passed", "failed"}:
        raise FormalError("stage payload must declare status passed or failed")
    result["result_sha256"] = canonical_sha256(result)
    write_json(attempt_dir / "stage-result.json", result, exclusive=True)
