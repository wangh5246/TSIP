#!/usr/bin/env python3
"""Prepare and upload append-only WayBill experiment archives to Cloudflare R2.

No network action occurs unless `upload --execute` is supplied.  Existing R2 objects
are never overwritten: a matching SHA-256 is skipped, any different object is failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

EXCLUDE_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "tmp", "temp", "cache", ".pytest_cache", ".pycache-codex"}
SECRET_MARKERS = (".env", "secret", "credential", "api_key", "apikey")
MIGRATION_VERSION = "1.0"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def command(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def included_files(directory: Path):
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if any(part in EXCLUDE_PARTS for part in path.parts) or any(marker in lowered for marker in SECRET_MARKERS):
            continue
        yield path


def artifact_class(relative: Path) -> str:
    suffix = relative.suffix.lower()
    name = relative.name.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".pdf", ".svg"} or name.startswith("fig_"):
        return "figures"
    if "table" in name or name.startswith("tab_"):
        return "tables"
    if suffix in {".csv", ".jsonl"} or "metric" in name or "summary" in name:
        return "metrics"
    if suffix in {".log", ".out", ".err"}:
        return "logs"
    if suffix in {".yaml", ".yml", ".toml", ".ini"} or any(x in name for x in ("config", "policy", "tariff")):
        return "config"
    return "artifacts"


def manifests(root: Path, staging: Path) -> list[dict]:
    experiments_root = root / "experiments"
    git_commit = command(root, "rev-parse", "HEAD")
    dirty = bool(command(root, "status", "--porcelain"))
    created = datetime.now(timezone.utc).isoformat()
    records = []
    for experiment in sorted(path for path in experiments_root.iterdir() if path.is_dir()):
        experiment_id = experiment.name
        artifacts = []
        config, metrics = [], []
        for path in included_files(experiment):
            rel = path.relative_to(experiment)
            category = artifact_class(rel)
            entry = {"path": str(rel), "category": category, "size_bytes": path.stat().st_size, "sha256": digest(path)}
            artifacts.append(entry)
            (config if category == "config" else metrics if category == "metrics" else []).append(str(rel))
        provenance = "complete" if git_commit and config else "partial"
        manifest = {"project": root.name, "experiment_id": experiment_id, "created_at": datetime.fromtimestamp(experiment.stat().st_mtime, timezone.utc).isoformat(),
                    "source_path": str(experiment.relative_to(root)), "git_commit": git_commit, "git_dirty_state": dirty,
                    "dataset": None, "method": None, "seed": None, "config": config, "metrics": metrics,
                    "artifact_list": artifacts, "provenance_status": provenance,
                    "migration_timestamp": created, "migration_version": MIGRATION_VERSION}
        target = staging / "experiments" / experiment_id / "manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append({"id": experiment_id, "path": experiment, "manifest": target, "artifacts": artifacts})
    return records


def prepare(root: Path, staging: Path) -> list[dict]:
    records = manifests(root, staging)
    commit = command(root, "rev-parse", "HEAD")
    if commit:
        snapshot = staging / "source-snapshots" / f"{commit}.tar.gz"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["git", "archive", "--format=tar.gz", "--output", str(snapshot), commit], cwd=root, check=False)
        if result.returncode:
            raise RuntimeError("git archive failed; source snapshot was not created")
    project = {"project": root.name, "migration_version": MIGRATION_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
               "git_remote": command(root, "remote", "get-url", "origin"), "git_commit": commit,
               "source_of_truth": "Git/GitHub", "r2_policy": "append-only immutable experiment archives", "experiments": [x["id"] for x in records]}
    rendered = json.dumps(project, ensure_ascii=False, indent=2) + "\n"
    (staging / "project-manifest.json").write_text(rendered, encoding="utf-8")
    (root / "project-manifest.json").write_text(rendered, encoding="utf-8")
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "upload"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--staging", type=Path, default=Path(".migration_staging"))
    parser.add_argument("--bucket", default=os.getenv("R2_BUCKET"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(); staging = (args.staging if args.staging.is_absolute() else root / args.staging)
    records = prepare(root, staging)
    if args.action == "prepare":
        report = {"dry_run": True, "local_file_count": sum(len(record["artifacts"]) + 1 for record in records) + 1,
                  "uploaded_file_count": 0, "skipped_file_count": 0, "failed_file_count": 0,
                  "checksum_verification": "not attempted: dry-run", "missing_files": [], "unexpected_files": [],
                  "r2_status": "not contacted by dry-run"}
        (root / "migration_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**report, "experiments": len(records), "staging": str(staging)}, ensure_ascii=False)); return
    if not args.execute or not args.bucket:
        raise SystemExit("Refusing upload: supply --execute and R2_BUCKET. No upload was attempted.")
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError as error:
        raise SystemExit("Install boto3 in an isolated migration environment before upload.") from error
    endpoint = os.environ["R2_ENDPOINT_URL"]
    client = boto3.client("s3", endpoint_url=endpoint, aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"])
    prefix = f"projects/{root.name}"
    plan = [(staging / "project-manifest.json", f"{prefix}/project-manifest.json")]
    if commit:
        plan.append((staging / "source-snapshots" / f"{commit}.tar.gz", f"{prefix}/source-snapshots/{commit}.tar.gz"))
    for record in records:
        plan.append((record["manifest"], f"{prefix}/experiments/{record['id']}/manifest.json"))
        for artifact in record["artifacts"]:
            local = record["path"] / artifact["path"]
            key = f"{prefix}/experiments/{record['id']}/{artifact['category']}/{artifact['path']}"
            plan.append((local, key))
    report = {"local_file_count": len(plan), "uploaded_file_count": 0, "skipped_file_count": 0, "failed_file_count": 0, "checksum_verification": [], "missing_files": [], "unexpected_files": []}
    for local, key in plan:
        expected = digest(local)
        try:
            head = client.head_object(Bucket=args.bucket, Key=key)
            if head.get("Metadata", {}).get("sha256") == expected:
                report["skipped_file_count"] += 1; report["checksum_verification"].append({"key": key, "status": "existing_match"}); continue
            raise RuntimeError("append-only collision: existing object differs")
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                report["failed_file_count"] += 1; report["missing_files"].append({"key": key, "error": str(error)}); continue
        except RuntimeError as error:
            report["failed_file_count"] += 1; report["unexpected_files"].append({"key": key, "error": str(error)}); continue
        client.upload_file(str(local), args.bucket, key, ExtraArgs={"Metadata": {"sha256": expected}})
        head = client.head_object(Bucket=args.bucket, Key=key)
        status = "verified" if head.get("Metadata", {}).get("sha256") == expected and head["ContentLength"] == local.stat().st_size else "failed_verification"
        report["uploaded_file_count"] += 1 if status == "verified" else 0
        report["failed_file_count"] += 0 if status == "verified" else 1
        report["checksum_verification"].append({"key": key, "status": status})
    (root / "migration_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
