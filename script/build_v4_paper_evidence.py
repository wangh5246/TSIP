#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


DATASETS = ("tdrive", "geolife", "porto", "rome", "synthetic")
PUBLIC_SIGNALS = (
    "hash_prev",
    "hash_curr",
    "hash_anchor",
    "step_dt_sq",
    "tier_vmax_sq",
    "tier_anchor_cap_sq",
    "cap_policy_sq",
    "primary_commitment",
    "payload_commitment_v2",
    "share_content_commitment_a",
    "share_content_commitment_r",
    "context_commitment",
    "blob_hash",
    "secret_commitment",
    "modeset_commitment",
    "mode_tag",
)
REQUIRED_ARTIFACTS = (
    "bindings",
    "circuit_base",
    "circuit_wrapper",
    "client",
    "r1cs",
    "shuffler",
    "vkey",
    "wasm",
    "zkey",
)

_EXPECTED_R1CS = {
    "constraints": 3547,
    "public_inputs": 16,
    "private_inputs": 25,
    "wires": 3550,
    "outputs": 0,
}
_UTILITY_MEANS = ("proposed_avg_jaccard", "baseline_avg_jaccard")
_UTILITY_STDS = ("proposed_std_jaccard", "baseline_std_jaccard")
_UTILITY_RATES = ("proposed_frr", "proposed_mrr")
_UTILITY_METRICS = (
    *_UTILITY_MEANS,
    *_UTILITY_STDS,
    "delta_jaccard",
    *_UTILITY_RATES,
)
_SCALE_AGGREGATE_METRICS = (
    "proofs_per_second_mean",
    "proofs_per_second_std",
    "wall_seconds_mean",
    "wall_seconds_std",
)
_SEEDS = (101, 202, 303)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DATASET_LABELS = {
    "tdrive": "T-Drive",
    "geolife": "GeoLife",
    "porto": "Porto",
    "rome": "Rome",
    "synthetic": "Synthetic",
}


class EvidenceError(RuntimeError):
    pass


def _load_json_receipt(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value, _ = _load_json_receipt(path)
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_repo(repo: Path) -> Path:
    try:
        return repo.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(f"cannot resolve repository path {repo}: {exc}") from exc


def verify_manifest(repo: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("profile") != "v4-paper-k6":
        raise EvidenceError("unexpected manifest profile")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise EvidenceError("manifest artifacts must be an object")
    expected_names = set(REQUIRED_ARTIFACTS)
    actual_names = set(artifacts)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise EvidenceError(
            f"manifest artifact set mismatch: missing={missing}, extra={extra}"
        )

    repo_root = _resolved_repo(repo)
    for name in REQUIRED_ARTIFACTS:
        item = artifacts[name]
        if not isinstance(item, dict):
            raise EvidenceError(f"invalid manifest artifact {name}")
        path_value = item.get("path")
        expected_hash = item.get("sha256")
        if (
            not isinstance(path_value, str)
            or not isinstance(expected_hash, str)
            or _SHA256_RE.fullmatch(expected_hash) is None
        ):
            raise EvidenceError(f"invalid manifest artifact {name}")

        relative_path = Path(path_value)
        if (
            not relative_path.parts
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise EvidenceError(
                f"manifest artifact path must be repository-relative for {name}"
            )
        candidate = repo_root / relative_path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise EvidenceError(f"missing manifest artifact {name}: {candidate}") from exc
        try:
            resolved.relative_to(repo_root)
        except ValueError as exc:
            raise EvidenceError(
                f"manifest artifact path escapes repository for {name}: {candidate}"
            ) from exc
        if not resolved.is_file():
            raise EvidenceError(f"missing manifest artifact {name}: {resolved}")
        try:
            actual_hash = sha256(resolved)
        except OSError as exc:
            raise EvidenceError(
                f"cannot hash manifest artifact {name}: {resolved}"
            ) from exc
        if actual_hash != expected_hash:
            raise EvidenceError(
                f"manifest hash mismatch for {name}: "
                f"expected {expected_hash}, got {actual_hash}"
            )


def _require_exact_datasets(rows: Any, receipt_name: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) != len(DATASETS):
        raise EvidenceError(f"{receipt_name} must contain exactly five rows")
    if not all(isinstance(row, dict) for row in rows):
        raise EvidenceError(f"{receipt_name} rows must be objects")

    dataset_names = [row.get("dataset") for row in rows]
    if (
        not all(isinstance(name, str) for name in dataset_names)
        or len(set(dataset_names)) != len(DATASETS)
        or set(dataset_names) != set(DATASETS)
    ):
        raise EvidenceError(f"{receipt_name} rows do not cover exactly five datasets")
    return rows


def _is_exact_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _is_real_number(value: Any) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _validate_r1cs(manifest: dict[str, Any]) -> None:
    counts = manifest.get("r1cs")
    if (
        not isinstance(counts, dict)
        or set(counts) != set(_EXPECTED_R1CS)
        or any(
            not _is_exact_int(counts.get(key), expected)
            for key, expected in _EXPECTED_R1CS.items()
        )
    ):
        raise EvidenceError(f"unexpected manifest-bound paper R1CS: {counts}")
    if tuple(manifest.get("public_signal_order", [])) != PUBLIC_SIGNALS:
        raise EvidenceError("unexpected public-signal order")


def _validate_static(static: dict[str, Any]) -> None:
    summary = static.get("summary")
    summary_valid = (
        isinstance(summary, dict)
        and set(summary) == {"passed", "failed"}
        and _is_exact_int(summary.get("passed"), 22)
        and _is_exact_int(summary.get("failed"), 0)
    )
    checks = static.get("checks")
    if (
        static.get("state") != "pass"
        or not summary_valid
        or not isinstance(checks, list)
        or len(checks) != 22
        or not all(isinstance(check, dict) for check in checks)
    ):
        raise EvidenceError("static gate is not pass with 22 detailed checks")

    names = []
    for check in checks:
        name = check.get("name")
        if (
            not isinstance(name, str)
            or not name.strip()
            or check.get("passed") is not True
        ):
            raise EvidenceError("static gate has an invalid detailed check")
        names.append(name)
    if len(set(names)) != 22:
        raise EvidenceError("static gate check names are not unique")


def _validate_protocol(protocol: dict[str, Any]) -> None:
    rows = _require_exact_datasets(protocol.get("results"), "protocol")
    if (
        protocol.get("state") != "pass"
        or not _is_exact_int(protocol.get("pass_count"), 5)
    ):
        raise EvidenceError("five-dataset protocol gate is not pass")
    for row in rows:
        if not _is_exact_int(row.get("returncode"), 0):
            raise EvidenceError(
                f"protocol result is not pass for {row.get('dataset')}"
            )


def _validate_fixed_config(value: Any, expected: int, label: str) -> None:
    if not _is_real_number(value) or value != expected:
        raise EvidenceError(f"utility {label} must be numeric {expected}")


def _validate_utility(utility: dict[str, Any]) -> tuple[Any, Any, list[dict[str, Any]]]:
    if utility.get("pass") is not True:
        raise EvidenceError("fixed utility gate is not pass")
    rows = _require_exact_datasets(utility.get("rows"), "fixed utility")
    if not all(row.get("pass") is True for row in rows):
        raise EvidenceError("one or more fixed utility rows failed")

    epsilon = utility.get("epsilon")
    tau = utility.get("tau")
    _validate_fixed_config(epsilon, 5, "epsilon")
    _validate_fixed_config(tau, 2, "tau")
    for row in rows:
        dataset = row.get("dataset")
        _validate_fixed_config(row.get("fixed_epsilon"), 5, "fixed_epsilon")
        _validate_fixed_config(row.get("fixed_tau"), 2, "fixed_tau")
        if row.get("strongest_baseline") != "nebula":
            raise EvidenceError(f"unexpected utility baseline for {dataset}")
        for metric in _UTILITY_METRICS:
            if not _is_real_number(row.get(metric)):
                raise EvidenceError(f"utility metric {metric} is invalid for {dataset}")
        for metric in (*_UTILITY_MEANS, *_UTILITY_STDS, *_UTILITY_RATES):
            value = row[metric]
            if not 0 <= value <= 1:
                raise EvidenceError(
                    f"utility metric {metric} is out of range for {dataset}"
                )
        expected_delta = (
            row["proposed_avg_jaccard"] - row["baseline_avg_jaccard"]
        )
        if not math.isclose(
            row["delta_jaccard"],
            expected_delta,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise EvidenceError(f"utility delta mismatch for {dataset}")
    return epsilon, tau, rows


def _launcher_count(launch: dict[str, Any], key: str) -> int:
    value = launch.get(key)
    if type(value) is not int:
        raise EvidenceError(f"launcher {key} must be an integer")
    return value


def _validate_launcher(launch: dict[str, Any]) -> tuple[int, int]:
    completed = _launcher_count(launch, "completed_units")
    total = _launcher_count(launch, "total_units")
    if total != 15:
        raise EvidenceError("launcher total_units must equal 15")
    if not 0 <= completed <= 15:
        raise EvidenceError("launcher completed_units must be between 0 and 15")
    return completed, total


def _strict_scale_summary_is_verified(summary: dict[str, Any]) -> bool:
    if (
        not _is_exact_int(summary.get("schema_version"), 1)
        or summary.get("profile") != "v4-paper-k6"
        or summary.get("status") != "verified"
        or summary.get("datasets") != list(DATASETS)
        or summary.get("seeds") != list(_SEEDS)
        or not all(type(seed) is int for seed in summary.get("seeds", []))
        or not _is_exact_int(summary.get("units"), 15)
        or not _is_exact_int(summary.get("rounds"), 240)
        or not _is_exact_int(summary.get("evaluation_rounds"), 150)
        or not _is_exact_int(summary.get("proof_generated"), 225000)
        or not _is_exact_int(summary.get("proof_verified"), 225000)
        or not _is_exact_int(summary.get("proof_failed"), 0)
    ):
        return False

    by_dataset = summary.get("by_dataset")
    if not isinstance(by_dataset, dict) or set(by_dataset) != set(DATASETS):
        return False
    for dataset in DATASETS:
        row = by_dataset.get(dataset)
        if not isinstance(row, dict) or not _is_exact_int(row.get("units"), 3):
            return False
        if any(
            not _is_real_number(row.get(metric)) or row[metric] < 0
            for metric in _SCALE_AGGREGATE_METRICS
        ):
            return False

    unit_receipts = summary.get("unit_receipts")
    if not isinstance(unit_receipts, list) or len(unit_receipts) != 15:
        return False
    expected_pairs = {(dataset, seed) for dataset in DATASETS for seed in _SEEDS}
    actual_pairs = []
    for row in unit_receipts:
        if not isinstance(row, dict):
            return False
        dataset = row.get("dataset")
        seed = row.get("seed")
        if not isinstance(dataset, str) or type(seed) is not int:
            return False
        actual_pairs.append((dataset, seed))
        receipt_hash = row.get("receipt_sha256")
        if (
            not _is_exact_int(row.get("rounds"), 16)
            or not _is_exact_int(row.get("evaluation_rounds"), 10)
            or not _is_exact_int(row.get("proof_generated"), 15000)
            or not _is_exact_int(row.get("proof_verified"), 15000)
            or not _is_exact_int(row.get("proof_failed"), 0)
            or not isinstance(receipt_hash, str)
            or _SHA256_RE.fullmatch(receipt_hash) is None
        ):
            return False
    return len(set(actual_pairs)) == 15 and set(actual_pairs) == expected_pairs


def _receipt_metadata(repo: Path, path: Path, digest: str) -> dict[str, str]:
    repo_root = _resolved_repo(repo)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise EvidenceError(f"cannot resolve source receipt {path}: {exc}") from exc
    try:
        display_path = resolved.relative_to(repo_root).as_posix()
    except ValueError:
        display_path = resolved.as_posix()
    return {"path": display_path, "sha256": digest}


def collect_evidence(
    *,
    repo: Path,
    manifest: Path,
    static: Path,
    protocol: Path,
    utility: Path,
    launch: Path,
    scale_summary: Path | None,
) -> dict[str, Any]:
    manifest_data, manifest_digest = _load_json_receipt(manifest)
    static_data, static_digest = _load_json_receipt(static)
    protocol_data, protocol_digest = _load_json_receipt(protocol)
    utility_data, utility_digest = _load_json_receipt(utility)
    launch_data, launch_digest = _load_json_receipt(launch)
    if scale_summary is not None and scale_summary.is_file():
        scale_data, scale_digest = _load_json_receipt(scale_summary)
    else:
        scale_data, scale_digest = None, None

    verify_manifest(repo, manifest_data)
    _validate_r1cs(manifest_data)
    _validate_static(static_data)
    _validate_protocol(protocol_data)
    epsilon, tau, utility_rows = _validate_utility(utility_data)
    completed, total = _validate_launcher(launch_data)

    launcher_verified = (
        launch_data.get("state") == "pass"
        and completed == 15
        and _is_exact_int(launch_data.get("failed_units"), 0)
    )
    scale_verified = (
        launcher_verified
        and scale_data is not None
        and _strict_scale_summary_is_verified(scale_data)
    )

    source_inputs = (
        ("manifest", manifest, manifest_digest),
        ("static", static, static_digest),
        ("protocol", protocol, protocol_digest),
        ("utility", utility, utility_digest),
        ("launch", launch, launch_digest),
    )
    source_receipts = {
        name: _receipt_metadata(repo, path, digest)
        for name, path, digest in source_inputs
    }
    if scale_data is not None and scale_summary is not None and scale_digest is not None:
        source_receipts["scale_summary"] = _receipt_metadata(
            repo, scale_summary, scale_digest
        )

    artifacts = manifest_data["artifacts"]
    return {
        "schema_version": 1,
        "profile": manifest_data["profile"],
        "setup_scope": manifest_data.get("setup"),
        "circuit": dict(_EXPECTED_R1CS),
        "public_signal_order": list(PUBLIC_SIGNALS),
        "artifact_hashes": {
            name: artifacts[name]["sha256"] for name in REQUIRED_ARTIFACTS
        },
        "source_receipts": source_receipts,
        "gates": {"static": "pass", "protocol": "pass", "utility": "pass"},
        "fixed_config": {"epsilon": epsilon, "tau": tau},
        "fixed_utility": sorted(
            utility_rows, key=lambda row: DATASETS.index(row["dataset"])
        ),
        "scale": {
            "status": "verified" if scale_verified else "partial",
            "state": launch_data.get("state"),
            "completed_units": completed,
            "total_units": total,
            "summary_sha256": scale_digest,
        },
    }


def render_macros(evidence: dict[str, Any]) -> str:
    circuit = evidence["circuit"]
    constraints = f"{circuit['constraints']:,}".replace(",", r"{,}")
    return "\n".join(
        [
            "% Generated by script/build_v4_paper_evidence.py; do not edit.",
            rf"\newcommand{{\VFourConstraints}}{{{constraints}}}",
            rf"\newcommand{{\VFourPublicInputs}}{{{circuit['public_inputs']}}}",
            rf"\newcommand{{\VFourPrivateInputs}}{{{circuit['private_inputs']}}}",
            r"\newcommand{\VFourStaticChecks}{22}",
            r"\newcommand{\VFourProtocolDatasets}{5}",
            "",
        ]
    )


def render_utility_table(evidence: dict[str, Any]) -> str:
    lines = [
        "% Generated by script/build_v4_paper_evidence.py; do not edit.",
        r"\begin{table*}[t]",
        r"\centering",
        r"\scriptsize",
        r"\caption{Fixed fair five-dataset utility comparison at $N{=}1000$, three seeds, $\varepsilon{=}5.0$, and $\tau{=}2.0$. Higher Jaccard is better.}",
        r"\label{tab:v4-fixed-utility}",
        r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Dataset & SHTPC $\pm$ std & Nebula $\pm$ std & $\Delta$ & FRR & MRR \\",
        r"\midrule",
    ]
    for row in evidence["fixed_utility"]:
        lines.append(
            f"{_DATASET_LABELS[row['dataset']]} & "
            f"{row['proposed_avg_jaccard']:.3f} $\\pm$ "
            f"{row['proposed_std_jaccard']:.3f} & "
            f"{row['baseline_avg_jaccard']:.3f} $\\pm$ "
            f"{row['baseline_std_jaccard']:.3f} & "
            f"{row['delta_jaccard']:+.3f} & "
            f"{row['proposed_frr']:.3f} & {row['proposed_mrr']:.3f} \\\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--static", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--utility", type=Path, required=True)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--scale-summary", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-macros", type=Path, required=True)
    parser.add_argument("--out-table", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence = collect_evidence(
        repo=args.repo,
        manifest=args.manifest,
        static=args.static,
        protocol=args.protocol,
        utility=args.utility,
        launch=args.launch,
        scale_summary=args.scale_summary,
    )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_macros.parent.mkdir(parents=True, exist_ok=True)
    args.out_table.parent.mkdir(parents=True, exist_ok=True)
    evidence_json = json.dumps(
        evidence, allow_nan=False, indent=2, sort_keys=True
    )
    args.out_json.write_text(evidence_json + "\n", encoding="utf-8")
    args.out_macros.write_text(render_macros(evidence), encoding="utf-8")
    args.out_table.write_text(render_utility_table(evidence), encoding="utf-8")
    print(evidence_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
