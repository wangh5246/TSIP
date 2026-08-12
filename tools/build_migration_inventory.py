#!/usr/bin/env python3
"""Build a read-only inventory for the WayBill R2 archive migration."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_NAMES = {".git", ".venv", "venv", "node_modules", "__pycache__", "tmp", "temp", "cache", ".pytest_cache", ".pycache-codex"}
SECRET_NAMES = {".env", ".env.local", ".env.production", "credentials", "credential", "secrets", "secret"}
SOURCE_DIRS = {"common", "services", "client", "baselines", "zk", "tests", "script"}
CONFIG_DIRS = {"configs"}
EXPERIMENT_DIRS = {"experiments", "experiments-heatmap"}
FIGURE_DIRS = {"figures", "tables"}
DATA_DIRS = {"data", "dataset", "release"}


def sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def classify(relative: Path) -> tuple[str, bool, str, str | None]:
    parts = relative.parts
    name = relative.name.lower()
    if any(part in EXCLUDED_NAMES for part in parts):
        return "cache_or_environment", False, "Excluded by preserve-first policy: generated environment/cache/temp content.", None
    if name in SECRET_NAMES or name.startswith(".env") or any(token in name for token in ("credential", "secret", "api_key", "apikey")):
        return "secret_or_credential", False, "Excluded: potential secret/credential; filename only is recorded.", None
    top = parts[0] if parts else ""
    if top in EXPERIMENT_DIRS:
        return "historical_experiments", True, "Archive immutable experimental evidence with manifests and SHA-256.", "experiments/<experiment-id>/"
    if top in FIGURE_DIRS:
        return "figures_or_tables", True, "Archive research figures/tables as reproducibility artifacts.", "experiments/<experiment-id>/figures|tables/"
    if top in CONFIG_DIRS:
        return "frozen_configs", True, "Archive only frozen copies referenced by an experiment.", "experiments/<experiment-id>/config/"
    if top in DATA_DIRS:
        return "dataset", False, "Exclude by default; public/re-downloadable data is not archived unless an experiment freezes a modified subset.", None
    if top in SOURCE_DIRS or top in {"WayBill", "heatmap-version"}:
        return "source_code", False, "Git/GitHub remains source of truth; include only an immutable Git source snapshot per archived commit.", "source-snapshots/<git-commit>/"
    if top in {"outputs", "ppt-master-projects", "projects", "memory", "docx_work", "UML期末大报告交付", "paper"}:
        return "unrelated_or_potentially_sensitive_output", False, "Out of WayBill experiment scope and may contain personal or publication material; require explicit allow-list.", None
    return "other", False, "Not automatically in scope; preserve locally and require explicit allow-list.", None


def directory_stats(path: Path) -> tuple[int, int]:
    count = size = 0
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {".git"}]
        for filename in files:
            item = Path(base, filename)
            try:
                size += item.stat().st_size
                count += 1
            except OSError:
                pass
    return count, size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("migration_inventory.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    commit = git_value(root, "rev-parse", "HEAD")
    dirty = bool(git_value(root, "status", "--porcelain"))
    entries = []
    for item in sorted(root.iterdir(), key=lambda value: value.name.lower()):
        if not item.is_dir() and item.name not in {".env", ".env.example"}:
            continue
        relative = item.relative_to(root)
        kind, include, reason, destination = classify(relative)
        count, size = directory_stats(item) if item.is_dir() else (1, item.stat().st_size)
        entries.append({"path": str(relative), "type": kind, "file_count": count, "total_size_bytes": size,
                        "migration_destination": destination, "decision": "include" if include else "exclude", "reason": reason})
    secrets = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root)
        kind, include, _, _ = classify(relative)
        if kind == "secret_or_credential":
            secrets.append({"path": str(relative), "decision": "excluded", "content_inspected": False})
    payload = {"schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
               "project": root.name, "root": str(root), "git": {"commit": commit, "dirty": dirty, "remote": git_value(root, "remote", "get-url", "origin")},
               "policy": {"preserve_first": True, "append_only": True, "r2_not_source_of_truth": True},
               "sensitive_files": secrets, "entries": entries}
    output = args.output if args.output.is_absolute() else root / args.output
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
