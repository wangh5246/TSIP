#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DATASETS = ("tdrive", "geolife", "porto", "rome", "synthetic")
SEEDS = (101, 202, 303)
LABELS = {
    "tdrive": "T-Drive",
    "geolife": "GeoLife",
    "porto": "Porto",
    "rome": "Rome",
    "synthetic": "Synthetic",
}
REQUIRED_UNIT_GATES = (
    "protocol",
    "paired_routes",
    "full_groth16",
    "reconstruction",
    "dp_release",
)
REQUIRED_PREFLIGHT_GATES = (
    "compose_config",
    "datasets_1000",
    "disk_space",
    "docker_capacity",
    "docker_images",
    "manifest_artifacts",
    "ports_free",
    "protocol",
    "resource_headroom",
    "static",
    "utility",
)
REQUIRED_ARTIFACTS = ("vkey", "wasm", "zkey")
EXPECTED_PROFILE = "v4-paper-k6"
EXPECTED_CLIENTS = 1000
EXPECTED_WARMUP_ROUNDS = 6
EXPECTED_EVALUATION_ROUNDS = 10
EXPECTED_ROUNDS = 16
EXPECTED_PROOFS_PER_UNIT = 15_000
EXPECTED_UNIT_COUNT = len(DATASETS) * len(SEEDS)
ROUND_ID_MODULUS = 2_000_000_000
TIMING_GAP_LIMIT_SECONDS = 7200.0
MIN_TIMING_UNITS_PER_DATASET = 2
_SHA256_LENGTH = 64


class ScaleReceiptError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_int(value: object, expected: int | None = None) -> bool:
    return type(value) is int and (expected is None or value == expected)


def _is_number(value: object, expected: float | None = None) -> bool:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        return False
    return expected is None or float(value) == expected


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        return False
    return all(character in "0123456789abcdef" for character in value)


def _resolve_under_repo(repo: Path, path: Path, label: str) -> Path:
    repo_root = repo.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ScaleReceiptError(f"{label} path escapes repository: {path}") from exc
    return resolved


def _display_path(repo: Path, path: Path) -> str:
    return path.resolve().relative_to(repo.resolve()).as_posix()


def read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ScaleReceiptError(f"missing {label}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScaleReceiptError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScaleReceiptError(f"{label} is not an object: {path}")
    return payload


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ScaleReceiptError(f"invalid {label} timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScaleReceiptError(f"invalid {label} timestamp") from exc
    if parsed.tzinfo is None:
        raise ScaleReceiptError(f"invalid {label} timestamp")
    return parsed


def _expected_pairs() -> set[tuple[str, int]]:
    return {(dataset, seed) for dataset in DATASETS for seed in SEEDS}


def _port_base(dataset: str, seed: int) -> int:
    return 11000 + 1000 * SEEDS.index(seed) + 100 * DATASETS.index(dataset)


def validate_manifest(path: Path) -> dict[str, str]:
    payload = read_json(path, "manifest")
    if payload.get("profile") != EXPECTED_PROFILE:
        raise ScaleReceiptError("manifest profile mismatch")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ScaleReceiptError("manifest artifact mismatch")
    result: dict[str, str] = {}
    for name in REQUIRED_ARTIFACTS:
        row = artifacts.get(name)
        if not isinstance(row, dict) or not _is_sha256(row.get("sha256")):
            raise ScaleReceiptError(f"manifest artifact mismatch: {name}")
        result[name] = row["sha256"]
    return result


def validate_launch_plan(path: Path, root: Path) -> None:
    payload = read_json(path, "launch plan")
    config = payload.get("config")
    expected_config = {
        "clients": EXPECTED_CLIENTS,
        "datasets": list(DATASETS),
        "eval_rounds": EXPECTED_EVALUATION_ROUNDS,
        "jobs": 2,
        "round_timeout_sec": 7200,
        "seeds": list(SEEDS),
        "warmup_rounds": EXPECTED_WARMUP_ROUNDS,
    }
    if not isinstance(config, dict) or any(
        config.get(key) != value for key, value in expected_config.items()
    ):
        raise ScaleReceiptError("launch plan config mismatch")
    out_dir = config.get("out_dir")
    if not isinstance(out_dir, str) or Path(out_dir).resolve() != root.resolve():
        raise ScaleReceiptError("launch plan config mismatch")

    gates = payload.get("gates")
    if not isinstance(gates, dict) or any(
        gates.get(name) is not True for name in REQUIRED_PREFLIGHT_GATES
    ):
        raise ScaleReceiptError("launch plan gate mismatch")

    units = payload.get("units")
    if not isinstance(units, list) or len(units) != EXPECTED_UNIT_COUNT:
        raise ScaleReceiptError("launch plan matrix mismatch")
    actual_pairs: list[tuple[str, int]] = []
    for row in units:
        if not isinstance(row, dict):
            raise ScaleReceiptError("launch plan matrix mismatch")
        dataset = row.get("dataset")
        seed = row.get("seed")
        if not isinstance(dataset, str) or not _is_int(seed):
            raise ScaleReceiptError("launch plan matrix mismatch")
        if dataset not in DATASETS or seed not in SEEDS:
            raise ScaleReceiptError("launch plan matrix mismatch")
        expected_dir = root / dataset / f"seed_{seed}" / "clean"
        out_dir = row.get("out_dir")
        if (
            not isinstance(out_dir, str)
            or Path(out_dir).resolve() != expected_dir.resolve()
            or not _is_int(row.get("port_base"), _port_base(dataset, seed))
        ):
            raise ScaleReceiptError("launch plan matrix mismatch")
        actual_pairs.append((dataset, seed))
    if len(set(actual_pairs)) != EXPECTED_UNIT_COUNT or set(actual_pairs) != _expected_pairs():
        raise ScaleReceiptError("launch plan matrix mismatch")


def validate_launch_status(path: Path, root: Path) -> None:
    payload = read_json(path, "launch status")
    if (
        payload.get("state") != "pass"
        or not _is_int(payload.get("completed_units"), EXPECTED_UNIT_COUNT)
        or not _is_int(payload.get("failed_units"), 0)
        or not _is_int(payload.get("total_units"), EXPECTED_UNIT_COUNT)
        or not _is_int(payload.get("jobs"), 2)
    ):
        raise ScaleReceiptError("launch status mismatch")
    started = _timestamp(payload.get("started_at"), "launch started_at")
    finished = _timestamp(payload.get("finished_at"), "launch finished_at")
    if finished <= started:
        raise ScaleReceiptError("launch status mismatch")

    results = payload.get("results")
    if not isinstance(results, list) or len(results) != EXPECTED_UNIT_COUNT:
        raise ScaleReceiptError("launch result matrix mismatch")
    actual_pairs: list[tuple[str, int]] = []
    for row in results:
        if not isinstance(row, dict):
            raise ScaleReceiptError("launch result matrix mismatch")
        dataset = row.get("dataset")
        seed = row.get("seed")
        if not isinstance(dataset, str) or not _is_int(seed):
            raise ScaleReceiptError("launch result matrix mismatch")
        if dataset not in DATASETS or seed not in SEEDS:
            raise ScaleReceiptError("launch result matrix mismatch")
        out_dir = row.get("out_dir")
        expected_dir = root / dataset / f"seed_{seed}" / "clean"
        if (
            row.get("state") not in {"pass", "skipped_pass"}
            or not _is_int(row.get("returncode"), 0)
            or not isinstance(out_dir, str)
            or Path(out_dir).resolve() != expected_dir.resolve()
        ):
            raise ScaleReceiptError("launch result matrix mismatch")
        actual_pairs.append((dataset, seed))
    if len(set(actual_pairs)) != EXPECTED_UNIT_COUNT or set(actual_pairs) != _expected_pairs():
        raise ScaleReceiptError("launch result matrix mismatch")


def _sum_exact_ints(rows: Iterable[dict[str, Any]], key: str) -> int:
    values = [row.get(key) for row in rows]
    if not all(_is_int(value) for value in values):
        raise ScaleReceiptError(f"proof accounting mismatch: invalid {key}")
    return sum(values)


def _validate_rounds(
    rounds: object, dataset: str, seed: int
) -> dict[str, int | float]:
    unit = f"{dataset}/{seed}"
    if not isinstance(rounds, list) or len(rounds) != EXPECTED_ROUNDS:
        raise ScaleReceiptError(f"round count mismatch: {unit}")
    if not all(isinstance(row, dict) for row in rounds):
        raise ScaleReceiptError(f"round count mismatch: {unit}")
    typed_rounds: list[dict[str, Any]] = rounds
    if [row.get("logical_round") for row in typed_rounds] != list(
        range(EXPECTED_ROUNDS)
    ):
        raise ScaleReceiptError(f"logical round mismatch: {unit}")
    expected_phases = ["warmup"] * EXPECTED_WARMUP_ROUNDS + [
        "evaluation"
    ] * EXPECTED_EVALUATION_ROUNDS
    if [row.get("phase") for row in typed_rounds] != expected_phases:
        raise ScaleReceiptError(f"round phase mismatch: {unit}")

    round_ids: list[int] = []
    for index, row in enumerate(typed_rounds):
        expected_proofs = 0 if index == 0 else EXPECTED_CLIENTS
        proof_keys = (
            "client_proof_attempts",
            "client_proof_generated",
            "shuffler_proof_attempts",
            "shuffler_proof_verified",
        )
        if (
            any(not _is_int(row.get(key), expected_proofs) for key in proof_keys)
            or not _is_int(row.get("shuffler_proof_failed"), 0)
        ):
            raise ScaleReceiptError(f"proof accounting mismatch: {unit}")
        if (
            row.get("attack_type") != "none"
            or not _is_int(row.get("total"), EXPECTED_CLIENTS)
            or not _is_int(row.get("valid_clients"), EXPECTED_CLIENTS)
            or not _is_int(row.get("rejected"), 0)
            or row.get("rejection_evidence") != ""
            or not _is_int(row.get("malicious_total"), 0)
            or not _is_number(row.get("false_reject_rate"), 0.0)
            or not _is_number(row.get("malicious_reject_rate"), 0.0)
        ):
            raise ScaleReceiptError(f"clean round mismatch: {unit}")
        round_id = row.get("round_id")
        if not _is_int(round_id) or round_id <= 0:
            raise ScaleReceiptError(f"clean round mismatch: {unit}")
        round_ids.append(round_id)

        if index < EXPECTED_WARMUP_ROUNDS:
            if (
                not _is_int(row.get("warmup_held"), EXPECTED_CLIENTS)
                or row.get("received_a") is not None
                or row.get("received_r") is not None
                or row.get("reconstruction_ok") is not None
                or row.get("dp_ok") is not None
                or row.get("cells_final") is not None
                or row.get("cells_kept_post") is not None
            ):
                raise ScaleReceiptError(f"warmup round mismatch: {unit}")
        else:
            if (
                not _is_int(row.get("warmup_held"), 0)
                or not _is_int(row.get("received_a"), EXPECTED_CLIENTS)
                or not _is_int(row.get("received_r"), EXPECTED_CLIENTS)
            ):
                raise ScaleReceiptError(f"route count mismatch: {unit}")
            if row.get("reconstruction_ok") is not True or row.get("dp_ok") is not True:
                raise ScaleReceiptError(f"release gate mismatch: {unit}")
            cells_final = row.get("cells_final")
            cells_kept = row.get("cells_kept_post")
            if (
                not _is_int(cells_final)
                or cells_final <= 0
                or not _is_int(cells_kept)
                or not 0 <= cells_kept <= cells_final
            ):
                raise ScaleReceiptError(f"release gate mismatch: {unit}")
    if len(set(round_ids)) != EXPECTED_ROUNDS:
        raise ScaleReceiptError(f"clean round mismatch: {unit}")
    inter_round_gaps = [
        ((current - previous) % ROUND_ID_MODULUS) / 1000.0
        for previous, current in zip(round_ids, round_ids[1:])
    ]
    if any(gap <= 0 for gap in inter_round_gaps):
        raise ScaleReceiptError(f"clean round mismatch: {unit}")

    client_attempted = _sum_exact_ints(typed_rounds, "client_proof_attempts")
    generated = _sum_exact_ints(typed_rounds, "client_proof_generated")
    shuffler_attempted = _sum_exact_ints(typed_rounds, "shuffler_proof_attempts")
    verified = _sum_exact_ints(typed_rounds, "shuffler_proof_verified")
    failed = _sum_exact_ints(typed_rounds, "shuffler_proof_failed")
    if (
        client_attempted != EXPECTED_PROOFS_PER_UNIT
        or generated != EXPECTED_PROOFS_PER_UNIT
        or shuffler_attempted != EXPECTED_PROOFS_PER_UNIT
        or verified != EXPECTED_PROOFS_PER_UNIT
        or failed != 0
    ):
        raise ScaleReceiptError(f"proof accounting mismatch: {unit}")
    evaluation = typed_rounds[EXPECTED_WARMUP_ROUNDS:]
    return {
        "client_proof_attempts": client_attempted,
        "proof_generated": generated,
        "shuffler_proof_attempts": shuffler_attempted,
        "proof_verified": verified,
        "proof_failed": failed,
        "route_received_a": sum(row["received_a"] for row in evaluation),
        "route_received_r": sum(row["received_r"] for row in evaluation),
        "reconstruction_passed": sum(
            row["reconstruction_ok"] is True for row in evaluation
        ),
        "dp_release_passed": sum(row["dp_ok"] is True for row in evaluation),
        "max_inter_round_gap_seconds": max(inter_round_gaps),
    }


def validate_unit(
    *,
    repo: Path,
    root: Path,
    dataset: str,
    seed: int,
    manifest_artifacts: dict[str, str],
) -> dict[str, object]:
    path = root / dataset / f"seed_{seed}" / "clean" / "status.json"
    if not path.is_file():
        raise ScaleReceiptError(f"missing unit receipt: {path}")
    payload = read_json(path, "unit receipt")
    unit = f"{dataset}/{seed}"
    if payload.get("state") != "pass" or not payload.get("finished_at"):
        raise ScaleReceiptError(f"unit not pass: {unit}")

    config = payload.get("config")
    expected_config = {
        "attack_sequence": [],
        "attack_type": "none",
        "clients": EXPECTED_CLIENTS,
        "condition": "clean",
        "dataset": dataset,
        "eval_rounds": EXPECTED_EVALUATION_ROUNDS,
        "malicious_rate": 0.0,
        "profile": EXPECTED_PROFILE,
        "project": f"v4n1000_{dataset}_{seed}",
        "seed": seed,
        "tau": 3.0,
        "tau2": 3.0,
        "warmup_rounds": EXPECTED_WARMUP_ROUNDS,
    }
    if not isinstance(config, dict) or any(
        config.get(key) != value for key, value in expected_config.items()
    ):
        raise ScaleReceiptError(f"unit config mismatch: {unit}")
    base = _port_base(dataset, seed)
    expected_ports = {
        "aggregator_a": base + 2,
        "aggregator_r": base + 3,
        "decoder": base + 10,
        "shuffler": base + 1,
    }
    if config.get("ports") != expected_ports:
        raise ScaleReceiptError(f"unit config mismatch: {unit}")

    gate = payload.get("gate")
    if not isinstance(gate, dict) or any(
        gate.get(name) != "pass" for name in REQUIRED_UNIT_GATES
    ):
        raise ScaleReceiptError(f"unit gate mismatch: {unit}")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ScaleReceiptError(f"artifact mismatch: {unit}")
    for name in REQUIRED_ARTIFACTS:
        row = artifacts.get(name)
        if not isinstance(row, dict) or row.get("sha256") != manifest_artifacts[name]:
            raise ScaleReceiptError(f"artifact mismatch: {unit}/{name}")

    accounting = _validate_rounds(payload.get("rounds"), dataset, seed)
    started = _timestamp(payload.get("started_at"), f"{unit} started_at")
    finished = _timestamp(payload.get("finished_at"), f"{unit} finished_at")
    wall_seconds = (finished - started).total_seconds()
    if wall_seconds <= 0:
        raise ScaleReceiptError(f"non-positive unit duration: {unit}")
    max_gap = float(accounting["max_inter_round_gap_seconds"])
    timing_included = max_gap <= TIMING_GAP_LIMIT_SECONDS
    return {
        "dataset": dataset,
        "seed": seed,
        "receipt_path": _display_path(repo, path),
        "started_at": payload["started_at"],
        "finished_at": payload["finished_at"],
        "rounds": EXPECTED_ROUNDS,
        "warmup_rounds": EXPECTED_WARMUP_ROUNDS,
        "evaluation_rounds": EXPECTED_EVALUATION_ROUNDS,
        **accounting,
        "observed_wall_seconds": wall_seconds,
        "timing_status": (
            "verified" if timing_included else "excluded_host_suspension"
        ),
        "timing_exclusion_reason": (
            None
            if timing_included
            else "inter-round gap exceeds the 7200-second round timeout"
        ),
        "timing_wall_seconds": wall_seconds if timing_included else None,
        "proofs_per_second": (
            accounting["proof_verified"] / wall_seconds if timing_included else None
        ),
        "receipt_sha256": sha256(path),
    }


def _metric_summary(
    units: list[dict[str, object]],
) -> dict[str, float | int]:
    timed = [row for row in units if row["timing_status"] == "verified"]
    if len(timed) < MIN_TIMING_UNITS_PER_DATASET:
        raise ScaleReceiptError("insufficient timing receipts for sample statistics")
    rates = [float(row["proofs_per_second"]) for row in timed]
    walls = [float(row["timing_wall_seconds"]) for row in timed]
    return {
        "units": len(units),
        "timing_units": len(timed),
        "timing_excluded_units": len(units) - len(timed),
        "proof_generated": sum(int(row["proof_generated"]) for row in units),
        "proof_verified": sum(int(row["proof_verified"]) for row in units),
        "proof_failed": sum(int(row["proof_failed"]) for row in units),
        "proofs_per_second_mean": statistics.mean(rates),
        "proofs_per_second_std": statistics.stdev(rates),
        "proofs_per_second_min": min(rates),
        "proofs_per_second_max": max(rates),
        "wall_seconds_mean": statistics.mean(walls),
        "wall_seconds_std": statistics.stdev(walls),
        "wall_seconds_min": min(walls),
        "wall_seconds_max": max(walls),
        "wall_seconds_total": sum(walls),
        "aggregate_proofs_per_second": (
            sum(int(row["proof_verified"]) for row in timed) / sum(walls)
        ),
    }


def summarize(
    *,
    repo: Path,
    root: Path,
    manifest: Path,
    launch_plan: Path,
    launch_status: Path,
) -> dict[str, Any]:
    repo = repo.resolve()
    root = _resolve_under_repo(repo, root, "scale root")
    manifest = _resolve_under_repo(repo, manifest, "manifest")
    launch_plan = _resolve_under_repo(repo, launch_plan, "launch plan")
    launch_status = _resolve_under_repo(repo, launch_status, "launch status")
    manifest_artifacts = validate_manifest(manifest)
    validate_launch_plan(launch_plan, root)
    validate_launch_status(launch_status, root)

    units = [
        validate_unit(
            repo=repo,
            root=root,
            dataset=dataset,
            seed=seed,
            manifest_artifacts=manifest_artifacts,
        )
        for dataset in DATASETS
        for seed in SEEDS
    ]
    receipt_hashes = [str(row["receipt_sha256"]) for row in units]
    if len(set(receipt_hashes)) != EXPECTED_UNIT_COUNT:
        raise ScaleReceiptError("duplicate unit receipt hash")

    by_dataset = {
        dataset: _metric_summary(
            [row for row in units if row["dataset"] == dataset]
        )
        for dataset in DATASETS
    }
    timed_units = [row for row in units if row["timing_status"] == "verified"]
    excluded_units = [
        row for row in units if row["timing_status"] != "verified"
    ]
    return {
        "schema_version": 1,
        "profile": EXPECTED_PROFILE,
        "status": "verified",
        "datasets": list(DATASETS),
        "seeds": list(SEEDS),
        "units": len(units),
        "rounds": sum(int(row["rounds"]) for row in units),
        "warmup_rounds": sum(int(row["warmup_rounds"]) for row in units),
        "evaluation_rounds": sum(
            int(row["evaluation_rounds"]) for row in units
        ),
        "client_proof_attempts": sum(
            int(row["client_proof_attempts"]) for row in units
        ),
        "proof_generated": sum(int(row["proof_generated"]) for row in units),
        "shuffler_proof_attempts": sum(
            int(row["shuffler_proof_attempts"]) for row in units
        ),
        "proof_verified": sum(int(row["proof_verified"]) for row in units),
        "proof_failed": sum(int(row["proof_failed"]) for row in units),
        "route_received_a": sum(int(row["route_received_a"]) for row in units),
        "route_received_r": sum(int(row["route_received_r"]) for row in units),
        "reconstruction_passed": sum(
            int(row["reconstruction_passed"]) for row in units
        ),
        "dp_release_passed": sum(
            int(row["dp_release_passed"]) for row in units
        ),
        "timing_rule": {
            "clock": "receipt wall clock",
            "maximum_inter_round_gap_seconds": TIMING_GAP_LIMIT_SECONDS,
            "exclusion": "exclude timing when a round-id gap exceeds the configured round timeout",
            "minimum_timing_units_per_dataset": MIN_TIMING_UNITS_PER_DATASET,
        },
        "timing_units": len(timed_units),
        "timing_excluded_units": len(excluded_units),
        "timing_excluded_pairs": [
            {"dataset": row["dataset"], "seed": row["seed"]}
            for row in excluded_units
        ],
        "overall": _metric_summary(units),
        "by_dataset": by_dataset,
        "unit_receipts": units,
        "source_receipts": {
            "manifest_path": _display_path(repo, manifest),
            "manifest_sha256": sha256(manifest),
            "launch_plan_path": _display_path(repo, launch_plan),
            "launch_plan_sha256": sha256(launch_plan),
            "launch_path": _display_path(repo, launch_status),
            "launch_sha256": sha256(launch_status),
        },
    }


def _tex_integer(value: int) -> str:
    return f"{value:,}".replace(",", r"{,}")


def render_tex(summary: dict[str, Any]) -> str:
    lines = [
        "% Generated by script/summarize_v4_n1000_scale.py; do not edit.",
        r"\begin{table}[t]",
        r"  \centering",
        rf"  \caption{{Groth16 protocol execution at $N{{=}}1000$ over three seeds. All functionally valid units contribute to proof totals. Timing excludes units with an inter-round gap above {int(TIMING_GAP_LIMIT_SECONDS):,} seconds; entries report mean $\pm$ sample standard deviation over the remaining timing-eligible units.}}",
        r"  \label{tab:v4-n1000-scale}",
        r"  \scriptsize",
        r"  \setlength{\tabcolsep}{3pt}",
        r"  \begin{tabular}{@{}lrrrr@{}}",
        r"    \toprule",
        r"    Dataset & Verified & Timing $n$ & Proofs/s & Wall time (h) \\",
        r"    \midrule",
    ]
    for dataset in DATASETS:
        row = summary["by_dataset"][dataset]
        lines.append(
            f"    {LABELS[dataset]} & {_tex_integer(int(row['proof_verified']))} & "
            f"{int(row['timing_units'])} & "
            f"{row['proofs_per_second_mean']:.3f} $\\pm$ "
            f"{row['proofs_per_second_std']:.3f} & "
            f"{row['wall_seconds_mean'] / 3600:.3f} $\\pm$ "
            f"{row['wall_seconds_std'] / 3600:.3f} \\\\"
        )
    lines.extend(
        [
            r"    \bottomrule",
            r"  \end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    summary: dict[str, Any], *, out_json: Path, out_csv: Path, out_tex: Path
) -> None:
    for path in (out_json, out_csv, out_tex):
        path.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    fieldnames = [
        "dataset",
        "units",
        "proof_generated",
        "proof_verified",
        "proof_failed",
        "timing_units",
        "timing_excluded_units",
        "proofs_per_second_mean",
        "proofs_per_second_std",
        "proofs_per_second_min",
        "proofs_per_second_max",
        "wall_seconds_mean",
        "wall_seconds_std",
        "wall_seconds_min",
        "wall_seconds_max",
        "wall_seconds_total",
        "aggregate_proofs_per_second",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for dataset in DATASETS:
            writer.writerow({"dataset": dataset, **summary["by_dataset"][dataset]})
    out_tex.write_text(render_tex(summary), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strictly validate and summarize the V4 N=1000 Docker matrix."
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--launch-plan", type=Path, required=True)
    parser.add_argument("--launch-status", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument("--out-tex", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = summarize(
            repo=args.repo,
            root=args.root,
            manifest=args.manifest,
            launch_plan=args.launch_plan,
            launch_status=args.launch_status,
        )
        write_outputs(
            summary,
            out_json=args.out_json,
            out_csv=args.out_csv,
            out_tex=args.out_tex,
        )
    except ScaleReceiptError as exc:
        print(f"scale receipt validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
