#!/usr/bin/env python3
"""Execute one immutable four-bucket S3 certified-bound group."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.e3_certification import E3Instance  # noqa: E402
from waybill_formal.core import (  # noqa: E402
    FormalError,
    read_json,
    read_jsonl,
    sha256_file,
)
from waybill_formal.stage import finish_stage, load_job_environment  # noqa: E402
from waybill_formal.stage import load_prepared_manifest  # noqa: E402


def _instance_path(raw_value: object, manifest: dict) -> Path:
    raw = Path(str(raw_value))
    root_label = str(manifest.get("corpus_root_label", ""))
    root_value = os.environ.get(root_label) if root_label else None
    if not raw.is_absolute() and not root_value:
        raise FormalError("formal corpus root is not bound into the S3 runtime")
    root = Path(str(root_value)) if root_value else Path("/")
    return raw if raw.is_absolute() else root / raw


def main() -> int:
    job, attempt_dir, run_root = load_job_environment()
    if job.get("stage") != "S3" or job.get("kind") != "certified-bound-group":
        raise FormalError("S3 runner received an unsupported job")
    manifest = load_prepared_manifest(run_root)
    parameters = job["parameters"]
    records = list(parameters.get("instances", []))
    if len(records) != 4:
        raise FormalError("one S3 group must contain exactly four canonical buckets")
    paths: list[Path] = []
    instances: list[E3Instance] = []
    for record in records:
        path = _instance_path(record["instance_path"], manifest)
        if not path.is_file():
            raise FormalError(f"canonical instance missing: {path}")
        expected_hash = record.get("instance_sha256")
        if expected_hash and sha256_file(path) != expected_hash:
            raise FormalError(f"canonical instance hash mismatch: {path}")
        payload = read_json(path)
        if isinstance(payload, list):
            if len(payload) != 1:
                raise FormalError("one S3 path must contain exactly one canonical instance")
            payload = payload[0]
        instance = E3Instance.from_dict(payload)
        scale = int(instance.profile.coordinate_scale_per_m)
        if instance.bucket_size_units != int(record["bucket_m"]) * scale:
            raise FormalError("S3 instance bucket does not match the frozen group")
        if instance.profile.relay_radius_units != int(parameters["radius_m"]) * scale:
            raise FormalError("S3 instance radius does not match the frozen group")
        if str(instance.dataset) != str(parameters["dataset"]):
            raise FormalError("S3 instance dataset does not match the frozen group")
        if not instance.fixes or str(instance.fixes[0].period_id) != str(parameters["period_id"]):
            raise FormalError("S3 instance period does not match the frozen group")
        paths.append(path)
        instances.append(instance)

    output_dir = attempt_dir / "m3"
    command = [
        sys.executable,
        "script/run_m3_certified_e3.py",
        "--instances",
        *[str(path) for path in paths],
        "--output-dir",
        str(output_dir),
        "--limit-per-input",
        "0",
        "--max-fixes",
        "0",
        "--timeout-sec",
        str(parameters["instance_timeout_sec"]),
        "--oracle-max-fixes",
        str(job["parameters"]["oracle_max_fixes"]),
    ]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    receipts_path = output_dir / "bound_receipts.jsonl"
    summary_path = output_dir / "summary.json"
    receipts = read_jsonl(receipts_path) if receipts_path.is_file() else []
    summary = read_json(summary_path) if summary_path.is_file() else {}
    expected_ids = {instance.instance_id for instance in instances}
    actual_ids = {
        str(receipt.get("instance", {}).get("instance_id", "")) for receipt in receipts
    }
    summary_rows = summary.get("instance_results", []) if isinstance(summary, dict) else []
    summary_ids = {
        str(row.get("instance_id", ""))
        for row in summary_rows
        if isinstance(row, dict)
    }
    summary_complete = (
        isinstance(summary, dict)
        and summary.get("attempted") == 4
        and len(summary_rows) == 4
        and summary_ids == expected_ids
    )
    complete = len(receipts) == 4 and actual_ids == expected_ids and summary_complete
    small_oracle_gate_passed = bool(
        isinstance(summary, dict)
        and summary.get("small_oracle_gate", {}).get("passed") is True
    )
    runner_returncode_accepted = proc.returncode in {0, 1}
    soundness_failures: list[str] = []
    for receipt in receipts:
        if receipt.get("status") != "certified":
            if receipt.get("failure_class") == "soundness-failure":
                soundness_failures.append(
                    str(receipt.get("instance", {}).get("instance_id", "unknown"))
                )
            continue
        lower_ok = bool(receipt.get("lower_bound", {}).get("checker", {}).get("accepted"))
        direction_ok = bool(
            receipt.get("upper_bound", {})
            .get("independent_cross_check", {})
            .get("direction_ok")
        )
        lb = receipt.get("LB_cents")
        ub = receipt.get("UB_cents")
        if not lower_ok or not direction_ok or not isinstance(lb, int) or not isinstance(ub, int) or lb > ub:
            soundness_failures.append(
                str(receipt.get("instance", {}).get("instance_id", "unknown"))
            )
    result = {
        "status": (
            "passed"
            if complete
            and small_oracle_gate_passed
            and runner_returncode_accepted
            and not soundness_failures
            else "failed"
        ),
        "group_id": parameters["group_id"],
        "dataset": parameters["dataset"],
        "period_id": parameters["period_id"],
        "radius_m": parameters["radius_m"],
        "instance_count": len(receipts),
        "expected_instance_ids": sorted(expected_ids),
        "runner_returncode": proc.returncode,
        "runner_returncode_accepted": runner_returncode_accepted,
        "small_oracle_gate_passed": small_oracle_gate_passed,
        "runner_gates": summary.get("gates") if isinstance(summary, dict) else None,
        "stdout_tail": proc.stdout[-16000:],
        "stderr_tail": proc.stderr[-16000:],
        "soundness_failures": soundness_failures,
        "bound_receipts": receipts,
    }
    finish_stage(job=job, attempt_dir=attempt_dir, payload=result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
