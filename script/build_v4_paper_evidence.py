#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
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

_EXPECTED_R1CS = {
    "constraints": 3547,
    "public_inputs": 16,
    "private_inputs": 25,
    "wires": 3550,
    "outputs": 0,
}
_UTILITY_METRICS = (
    "proposed_avg_jaccard",
    "proposed_std_jaccard",
    "baseline_avg_jaccard",
    "baseline_std_jaccard",
    "delta_jaccard",
    "proposed_frr",
    "proposed_mrr",
)
_DATASET_LABELS = {
    "tdrive": "T-Drive",
    "geolife": "GeoLife",
    "porto": "Porto",
    "rome": "Rome",
    "synthetic": "Synthetic",
}


class EvidenceError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(repo: Path, manifest: dict[str, Any]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise EvidenceError("manifest artifacts must be an object")

    for name, item in artifacts.items():
        if not isinstance(item, dict):
            raise EvidenceError(f"invalid manifest artifact {name}")
        relative_path = item.get("path")
        expected_hash = item.get("sha256")
        if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
            raise EvidenceError(f"invalid manifest artifact {name}")

        path = repo / relative_path
        if not path.is_file():
            raise EvidenceError(f"missing manifest artifact {name}: {path}")
        try:
            actual_hash = sha256(path)
        except OSError as exc:
            raise EvidenceError(f"cannot hash manifest artifact {name}: {path}") from exc
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

    typed_rows = rows
    dataset_names = [row.get("dataset") for row in typed_rows]
    if (
        not all(isinstance(name, str) for name in dataset_names)
        or len(set(dataset_names)) != len(DATASETS)
        or set(dataset_names) != set(DATASETS)
    ):
        raise EvidenceError(f"{receipt_name} rows do not cover exactly five datasets")
    return typed_rows


def _launcher_count(launch: dict[str, Any], key: str) -> int:
    value = launch.get(key, 0)
    if isinstance(value, bool):
        raise EvidenceError(f"launcher {key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"launcher {key} must be an integer") from exc


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
    manifest_data = load_json(manifest)
    static_data = load_json(static)
    protocol_data = load_json(protocol)
    utility_data = load_json(utility)
    launch_data = load_json(launch)
    scale_data = (
        load_json(scale_summary)
        if scale_summary is not None and scale_summary.is_file()
        else None
    )

    verify_manifest(repo, manifest_data)

    counts = manifest_data.get("r1cs")
    if not isinstance(counts, dict) or counts != _EXPECTED_R1CS:
        raise EvidenceError(f"unexpected manifest-bound paper R1CS: {counts}")
    if tuple(manifest_data.get("public_signal_order", [])) != PUBLIC_SIGNALS:
        raise EvidenceError("unexpected public-signal order")

    if (
        static_data.get("state") != "pass"
        or static_data.get("summary") != {"failed": 0, "passed": 22}
    ):
        raise EvidenceError("static gate is not pass with summary 22/0")

    _require_exact_datasets(protocol_data.get("results"), "protocol")
    if protocol_data.get("state") != "pass" or protocol_data.get("pass_count") != 5:
        raise EvidenceError("five-dataset protocol gate is not pass")

    if utility_data.get("pass") is not True:
        raise EvidenceError("fixed utility gate is not pass")
    utility_rows = _require_exact_datasets(utility_data.get("rows"), "fixed utility")
    if not all(row.get("pass") is True for row in utility_rows):
        raise EvidenceError("one or more fixed utility rows failed")

    epsilon = utility_data.get("epsilon")
    tau = utility_data.get("tau")
    if (epsilon, tau) != (5, 2) or not all(
        (row.get("fixed_epsilon"), row.get("fixed_tau")) == (5, 2)
        for row in utility_rows
    ):
        raise EvidenceError("fixed utility configuration is not epsilon=5, tau=2")
    for row in utility_rows:
        if row.get("strongest_baseline") != "nebula":
            raise EvidenceError(
                f"unexpected strongest baseline for {row.get('dataset')}"
            )
        if any(not isinstance(row.get(metric), (int, float)) for metric in _UTILITY_METRICS):
            raise EvidenceError(f"missing utility metric for {row.get('dataset')}")

    completed = _launcher_count(launch_data, "completed_units")
    total = _launcher_count(launch_data, "total_units")
    scale_verified = (
        launch_data.get("state") == "pass"
        and completed == total == 15
        and launch_data.get("failed_units") == 0
        and scale_data is not None
        and scale_data.get("status") == "verified"
        and scale_data.get("units") == 15
        and scale_data.get("rounds") == 240
        and scale_data.get("evaluation_rounds") == 150
        and scale_data.get("proof_failed") == 0
    )

    artifacts = manifest_data["artifacts"]
    return {
        "schema_version": 1,
        "profile": manifest_data.get("profile"),
        "setup_scope": manifest_data.get("setup"),
        "circuit": dict(_EXPECTED_R1CS),
        "public_signal_order": list(PUBLIC_SIGNALS),
        "artifact_hashes": {
            name: item["sha256"] for name, item in artifacts.items()
        },
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
            "summary_sha256": sha256(scale_summary) if scale_data is not None else None,
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
    args.out_json.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.out_macros.write_text(render_macros(evidence), encoding="utf-8")
    args.out_table.write_text(render_utility_table(evidence), encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
