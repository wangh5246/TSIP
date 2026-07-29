#!/usr/bin/env python3
"""Execute one immutable canonical S3 certified-bound instance."""

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


def _instance_path(job: dict, manifest: dict) -> Path:
    raw = Path(str(job["parameters"]["instance_path"]))
    root_label = str(manifest.get("corpus_root_label", ""))
    root_value = os.environ.get(root_label) if root_label else None
    if not raw.is_absolute() and not root_value:
        raise FormalError("formal corpus root is not bound into the S3 runtime")
    root = Path(str(root_value)) if root_value else Path("/")
    return raw if raw.is_absolute() else root / raw


def main() -> int:
    job, attempt_dir, run_root = load_job_environment()
    if job.get("stage") != "S3" or job.get("kind") != "certified-bound":
        raise FormalError("S3 runner received an unsupported job")
    manifest = load_prepared_manifest(run_root)
    path = _instance_path(job, manifest)
    if not path.is_file():
        raise FormalError(f"canonical instance missing: {path}")
    expected_hash = job["parameters"].get("instance_sha256")
    if expected_hash and sha256_file(path) != expected_hash:
        raise FormalError(f"canonical instance hash mismatch: {path}")
    payload = read_json(path)
    if isinstance(payload, list):
        if len(payload) != 1:
            raise FormalError("one S3 job must contain exactly one canonical instance")
        payload = payload[0]
    instance = E3Instance.from_dict(payload)
    scale = int(instance.profile.coordinate_scale_per_m)
    if instance.bucket_size_units != int(job["parameters"]["bucket_m"]) * scale:
        raise FormalError("S3 instance bucket does not match the frozen job")
    if instance.profile.relay_radius_units != int(job["parameters"]["radius_m"]) * scale:
        raise FormalError("S3 instance radius does not match the frozen job")

    output_dir = attempt_dir / "m3"
    command = [
        sys.executable,
        "script/run_m3_certified_e3.py",
        "--instances",
        str(path),
        "--output-dir",
        str(output_dir),
        "--limit-per-input",
        "0",
        "--max-fixes",
        "0",
        "--timeout-sec",
        "7200",
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
    receipts = read_jsonl(receipts_path) if receipts_path.is_file() else []
    certified = len(receipts) == 1 and receipts[0].get("status") == "certified"
    result = {
        "status": "passed" if proc.returncode == 0 and certified else "failed",
        "instance_id": instance.instance_id,
        "bucket_m": job["parameters"]["bucket_m"],
        "radius_m": job["parameters"]["radius_m"],
        "runner_returncode": proc.returncode,
        "stdout_tail": proc.stdout[-16000:],
        "stderr_tail": proc.stderr[-16000:],
        "bound_receipt": receipts[0] if receipts else None,
    }
    finish_stage(job=job, attempt_dir=attempt_dir, payload=result)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
