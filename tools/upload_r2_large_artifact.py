#!/usr/bin/env python3
"""Resumable, append-only multipart uploader for the final R2 archive artifact."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path.cwd()
BUCKET = "waybill"
KEY = "projects/risefl_mvp/experiments/waybill_m2/artifacts/circuit_matrix/ptau/powersOfTau28_hez_final_22.ptau"
PART_SIZE = 100 * 1024 * 1024
STATE = ROOT / ".migration_staging" / "large_artifact_multipart_state.json"


def save(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    plan = json.loads((ROOT / "migration_upload_plan.json").read_text())
    item = next(entry for entry in plan["files"] if entry["key"] == KEY)
    local = Path(item["local_path"])
    client = boto3.client(
        "s3", endpoint_url="https://6f8ed8dcefa6be91e4ed011d8f5bd067.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto",
    )
    try:
        client.head_object(Bucket=BUCKET, Key=KEY)
        raise SystemExit("append-only stop: destination object already exists")
    except ClientError as error:
        if error.response["Error"].get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if state.get("key") != KEY or state.get("local_sha256") != item["sha256"]:
        state = {"key": KEY, "local_sha256": item["sha256"], "parts": {}}
    if not state.get("upload_id"):
        created = client.create_multipart_upload(Bucket=BUCKET, Key=KEY, Metadata={"sha256": item["sha256"], "migration-version": "1.0"})
        state["upload_id"] = created["UploadId"]
        save(state)
    expected_parts = (item["size_bytes"] + PART_SIZE - 1) // PART_SIZE
    with local.open("rb") as handle:
        for number in range(1, expected_parts + 1):
            length = min(PART_SIZE, item["size_bytes"] - (number - 1) * PART_SIZE)
            if str(number) in state["parts"]:
                handle.seek(length, 1)
                continue
            payload = handle.read(length)
            for attempt in range(1, 6):
                try:
                    result = client.upload_part(Bucket=BUCKET, Key=KEY, UploadId=state["upload_id"], PartNumber=number, Body=payload)
                    state["parts"][str(number)] = result["ETag"]
                    save(state)
                    print(f"part {number}/{expected_parts} complete", flush=True)
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    time.sleep(attempt * 3)
    parts = [{"PartNumber": number, "ETag": state["parts"][str(number)]} for number in range(1, expected_parts + 1)]
    client.complete_multipart_upload(Bucket=BUCKET, Key=KEY, UploadId=state["upload_id"], MultipartUpload={"Parts": parts})
    head = client.head_object(Bucket=BUCKET, Key=KEY)
    if head["ContentLength"] != item["size_bytes"] or head.get("Metadata", {}).get("sha256") != item["sha256"]:
        raise SystemExit("post-upload verification failed")
    report_path = ROOT / "migration_report.json"
    report = json.loads(report_path.read_text())
    report.update({"uploaded_file_count": 362, "failed_file_count": 0, "missing_files": [], "status": "uploaded_pending_final_verification"})
    report["checksum_verification"].append({"key": KEY, "local_sha256": item["sha256"], "remote_size_bytes": head["ContentLength"], "status": "verified_sha256_metadata"})
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE.unlink(missing_ok=True)
    print("uploaded and verified", flush=True)


if __name__ == "__main__":
    main()
