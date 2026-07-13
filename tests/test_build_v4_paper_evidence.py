import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "script" / "build_v4_paper_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_v4_paper_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

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

STATIC_CHECK_NAMES = (
    "archive_k6_compatibility",
    "archive_k30_compatibility",
    "paper_positive",
    "tampered_public_hash_prev",
    "changed_blob_hash",
    "replayed_proof_new_context",
    "tampered_current_coordinate",
    "swapped_primary",
    "swapped_a_share_digest",
    "swapped_r_share_digest",
    "cross_swapped_share_digests",
    "changed_context_commitment",
    "wrong_predecessor",
    "wrong_anchor",
    "wrong_secret",
    "route_a_positive",
    "route_r_positive",
    "swapped_a_share",
    "swapped_r_share",
    "a_r_cross_swap",
    "changed_route_context",
    "changed_route_blob_hash",
)

UTILITY_METRICS = {
    "tdrive": {
        "proposed_avg_jaccard": 0.7114,
        "proposed_std_jaccard": 0.0114,
        "baseline_avg_jaccard": 0.5104,
        "baseline_std_jaccard": 0.0214,
        "delta_jaccard": 0.201,
        "proposed_frr": 0.0014,
        "proposed_mrr": 0.9014,
    },
    "geolife": {
        "proposed_avg_jaccard": 0.7224,
        "proposed_std_jaccard": 0.0224,
        "baseline_avg_jaccard": 0.5204,
        "baseline_std_jaccard": 0.0324,
        "delta_jaccard": 0.202,
        "proposed_frr": 0.0024,
        "proposed_mrr": 0.9024,
    },
    "porto": {
        "proposed_avg_jaccard": 0.7334,
        "proposed_std_jaccard": 0.0334,
        "baseline_avg_jaccard": 0.5304,
        "baseline_std_jaccard": 0.0434,
        "delta_jaccard": 0.203,
        "proposed_frr": 0.0034,
        "proposed_mrr": 0.9034,
    },
    "rome": {
        "proposed_avg_jaccard": 0.7444,
        "proposed_std_jaccard": 0.0444,
        "baseline_avg_jaccard": 0.5404,
        "baseline_std_jaccard": 0.0544,
        "delta_jaccard": 0.204,
        "proposed_frr": 0.0044,
        "proposed_mrr": 0.9044,
    },
    "synthetic": {
        "proposed_avg_jaccard": 0.7554,
        "proposed_std_jaccard": 0.0554,
        "baseline_avg_jaccard": 0.5504,
        "baseline_std_jaccard": 0.0654,
        "delta_jaccard": 0.205,
        "proposed_frr": 0.0054,
        "proposed_mrr": 0.9054,
    },
}

EXPECTED_UTILITY_ROWS = [
    r"T-Drive & 0.711 $\pm$ 0.011 & 0.510 $\pm$ 0.021 & +0.201 & 0.001 & 0.901 \\",
    r"GeoLife & 0.722 $\pm$ 0.022 & 0.520 $\pm$ 0.032 & +0.202 & 0.002 & 0.902 \\",
    r"Porto & 0.733 $\pm$ 0.033 & 0.530 $\pm$ 0.043 & +0.203 & 0.003 & 0.903 \\",
    r"Rome & 0.744 $\pm$ 0.044 & 0.540 $\pm$ 0.054 & +0.204 & 0.004 & 0.904 \\",
    r"Synthetic & 0.755 $\pm$ 0.055 & 0.550 $\pm$ 0.065 & +0.205 & 0.005 & 0.905 \\",
]

SOURCE_RECEIPT_NAMES = (
    "manifest",
    "static",
    "protocol",
    "utility",
    "utility_status",
    "launch",
    "scale_summary",
)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=False, sort_keys=True), encoding="utf-8"
    )


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def fixture_tree(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    receipts = repo / "receipts"
    artifacts = {}
    for name in REQUIRED_ARTIFACTS:
        filename = "artifact.r1cs" if name == "r1cs" else f"{name}.bin"
        artifact = repo / "artifacts" / filename
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_bytes(f"{name}-artifact".encode())
        artifacts[name] = {
            "path": artifact.relative_to(repo).as_posix(),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }

    manifest = receipts / "manifest.json"
    static = receipts / "static.json"
    protocol = receipts / "protocol.json"
    utility = receipts / "utility.json"
    utility_status = receipts / "utility_status.json"
    launch = receipts / "launch.json"
    scale_summary = receipts / "aggregate_summary.json"
    write_json(
        manifest,
        {
            "profile": "v4-paper-k6",
            "r1cs": {
                "wires": 3550,
                "constraints": 3547,
                "private_inputs": 25,
                "public_inputs": 16,
                "outputs": 0,
            },
            "public_signal_order": list(MODULE.PUBLIC_SIGNALS),
            "artifacts": artifacts,
            "setup": "development Groth16 setup; not a production ceremony",
        },
    )
    write_json(
        static,
        {
            "state": "pass",
            "summary": {"passed": 22, "failed": 0},
            "checks": [
                {"name": name, "passed": True} for name in STATIC_CHECK_NAMES
            ],
        },
    )
    write_json(
        protocol,
        {
            "state": "pass",
            "dataset_count": 5,
            "pass_count": 5,
            "results": [
                {"dataset": name, "returncode": 0} for name in MODULE.DATASETS
            ],
        },
    )
    rows = []
    for name in MODULE.DATASETS:
        rows.append(
            {
                "dataset": name,
                "fixed_epsilon": 5,
                "fixed_tau": 2,
                "strongest_baseline": "nebula",
                "pass": True,
                **UTILITY_METRICS[name],
            }
        )
    write_json(utility, {"epsilon": 5, "tau": 2, "pass": True, "rows": rows})
    write_json(
        utility_status,
        {
            "state": "pass",
            "quality_gate": True,
            "fair_fixed_gate": True,
            "config": {
                "datasets": list(MODULE.DATASETS),
                "seeds": [101, 202, 303],
                "users": 1000,
                "rounds": 10,
            },
        },
    )
    write_json(
        launch,
        {
            "state": "running",
            "completed_units": 13,
            "total_units": 15,
            "results": [],
        },
    )
    return {
        "repo": repo,
        "manifest": manifest,
        "static": static,
        "protocol": protocol,
        "utility": utility,
        "utility_status": utility_status,
        "launch": launch,
        "scale_summary": scale_summary,
    }


def valid_scale_summary(paths: dict[str, Path]) -> dict:
    proofs_per_second = 15000 / 3600
    by_dataset = {}
    for dataset in MODULE.DATASETS:
        by_dataset[dataset] = {
            "units": 3,
            "timing_units": 3,
            "timing_excluded_units": 0,
            "proofs_per_second_mean": proofs_per_second,
            "proofs_per_second_std": 0.0,
            "wall_seconds_mean": 3600.0,
            "wall_seconds_std": 0.0,
        }
    unit_receipts = []
    for dataset in MODULE.DATASETS:
        for seed in (101, 202, 303):
            unit_receipts.append(
                {
                    "dataset": dataset,
                    "seed": seed,
                    "rounds": 16,
                    "evaluation_rounds": 10,
                    "proof_generated": 15000,
                    "proof_verified": 15000,
                    "proof_failed": 0,
                    "observed_wall_seconds": 3600.0,
                    "timing_status": "verified",
                    "timing_exclusion_reason": None,
                    "timing_wall_seconds": 3600.0,
                    "proofs_per_second": proofs_per_second,
                    "max_inter_round_gap_seconds": 1000.0,
                    "receipt_sha256": hashlib.sha256(
                        f"{dataset}:{seed}".encode()
                    ).hexdigest(),
                }
            )
    return {
        "schema_version": 1,
        "profile": "v4-paper-k6",
        "status": "verified",
        "datasets": list(MODULE.DATASETS),
        "seeds": [101, 202, 303],
        "units": 15,
        "rounds": 240,
        "warmup_rounds": 90,
        "evaluation_rounds": 150,
        "client_proof_attempts": 225000,
        "shuffler_proof_attempts": 225000,
        "proof_generated": 225000,
        "proof_verified": 225000,
        "proof_failed": 0,
        "route_received_a": 150000,
        "route_received_r": 150000,
        "reconstruction_passed": 150,
        "dp_release_passed": 150,
        "timing_units": 15,
        "timing_excluded_units": 0,
        "timing_excluded_pairs": [],
        "timing_rule": {
            "clock": "receipt wall clock",
            "maximum_inter_round_gap_seconds": 7200.0,
            "exclusion": "exclude timing when a round-id gap exceeds the configured round timeout",
            "minimum_timing_units_per_dataset": 2,
        },
        "overall": {
            "units": 15,
            "timing_units": 15,
            "timing_excluded_units": 0,
            "proof_generated": 225000,
            "proof_verified": 225000,
            "proof_failed": 0,
            "proofs_per_second_mean": proofs_per_second,
            "proofs_per_second_std": 0.0,
            "wall_seconds_mean": 3600.0,
            "wall_seconds_std": 0.0,
        },
        "by_dataset": by_dataset,
        "unit_receipts": unit_receipts,
        "source_receipts": {
            "manifest_sha256": MODULE.sha256(paths["manifest"]),
            "launch_sha256": MODULE.sha256(paths["launch"]),
        },
    }


def write_launcher_pass(paths: dict[str, Path], failed_units: object = 0) -> None:
    write_json(
        paths["launch"],
        {
            "state": "pass",
            "completed_units": 15,
            "total_units": 15,
            "failed_units": failed_units,
        },
    )


def collect_kwargs(paths: dict[str, Path]) -> dict[str, Path]:
    kwargs = dict(paths)
    repo = kwargs["repo"]
    for name in SOURCE_RECEIPT_NAMES:
        kwargs[name] = kwargs[name].relative_to(repo)
    return kwargs


def collect(paths: dict[str, Path]) -> dict:
    return MODULE.collect_evidence(**collect_kwargs(paths))


def assert_summary_not_verified(
    paths: dict[str, Path], summary: dict, *, allow_nan: bool = False
) -> dict:
    if allow_nan:
        paths["scale_summary"].write_text(
            json.dumps(summary, allow_nan=True), encoding="utf-8"
        )
    else:
        write_json(paths["scale_summary"], summary)
    evidence = collect(paths)
    assert evidence["scale"]["status"] == "partial"
    digest = MODULE.sha256(paths["scale_summary"])
    assert evidence["scale"]["summary_sha256"] == digest
    assert evidence["source_receipts"]["scale_summary"]["sha256"] == digest
    return evidence


def bound_scale_summary(paths: dict[str, Path]) -> dict:
    write_launcher_pass(paths)
    return valid_scale_summary(paths)


def test_collect_evidence_separates_verified_and_partial_layers(
    tmp_path: Path,
) -> None:
    paths = fixture_tree(tmp_path)
    evidence = collect(paths)
    assert evidence["circuit"]["constraints"] == 3547
    assert evidence["circuit"]["public_inputs"] == 16
    assert evidence["circuit"]["private_inputs"] == 25
    assert evidence["gates"] == {
        "static": "pass",
        "protocol": "pass",
        "utility": "pass",
    }
    assert evidence["scale"]["status"] == "partial"
    assert evidence["scale"]["completed_units"] == 13
    assert len(evidence["fixed_utility"]) == 5


def test_collect_evidence_binds_source_receipts(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    evidence = collect(paths)
    expected_keys = {
        "manifest",
        "static",
        "protocol",
        "utility",
        "utility_status",
        "launch",
    }
    assert set(evidence["source_receipts"]) == expected_keys
    for name in expected_keys:
        path = paths[name]
        assert evidence["source_receipts"][name] == {
            "path": path.relative_to(paths["repo"]).as_posix(),
            "sha256": MODULE.sha256(path),
        }


@pytest.mark.parametrize("source_name", SOURCE_RECEIPT_NAMES)
@pytest.mark.parametrize("mode", ["absolute", "parent", "symlink"])
def test_source_receipt_rejects_non_repository_relative_path(
    tmp_path: Path, source_name: str, mode: str
) -> None:
    paths = fixture_tree(tmp_path)
    kwargs = collect_kwargs(paths)
    outside = tmp_path / f"outside-{source_name}.json"
    source = paths[source_name]
    outside.write_bytes(source.read_bytes() if source.is_file() else b"{}")
    if mode == "absolute":
        kwargs[source_name] = source
    elif mode == "parent":
        kwargs[source_name] = Path("../") / outside.name
    else:
        link = paths["repo"] / "receipts" / f"escape-{source_name}.json"
        link.symlink_to(outside)
        kwargs[source_name] = link.relative_to(paths["repo"])
    with pytest.raises(MODULE.EvidenceError, match="source receipt"):
        MODULE.collect_evidence(**kwargs)


def test_evidence_json_serialization_wraps_value_error() -> None:
    with pytest.raises(MODULE.EvidenceError, match="serialize"):
        MODULE._serialize_evidence_json({"unexpected": float("nan")})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("users", 999),
        ("seeds", [303, 202, 101]),
        ("datasets", list(reversed(MODULE.DATASETS))),
    ],
)
def test_utility_status_rejects_mismatched_fixed_run_config(
    tmp_path: Path, field: str, value: object
) -> None:
    paths = fixture_tree(tmp_path)
    status = read_json(paths["utility_status"])
    status["config"][field] = value
    write_json(paths["utility_status"], status)
    with pytest.raises(MODULE.EvidenceError, match="utility status"):
        collect(paths)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "failed"),
        ("quality_gate", False),
        ("fair_fixed_gate", False),
    ],
)
def test_utility_status_rejects_failed_gate(
    tmp_path: Path, field: str, value: object
) -> None:
    paths = fixture_tree(tmp_path)
    status = read_json(paths["utility_status"])
    status[field] = value
    write_json(paths["utility_status"], status)
    with pytest.raises(MODULE.EvidenceError, match="utility status"):
        collect(paths)


def test_collect_evidence_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    (paths["repo"] / "artifacts/artifact.r1cs").write_bytes(b"tampered")
    with pytest.raises(MODULE.EvidenceError, match="hash mismatch"):
        collect(paths)


def test_required_manifest_artifact_set_is_exact() -> None:
    assert tuple(MODULE.REQUIRED_ARTIFACTS) == REQUIRED_ARTIFACTS


@pytest.mark.parametrize("mode", ["empty", "missing"])
def test_manifest_rejects_incomplete_artifact_set(
    tmp_path: Path, mode: str
) -> None:
    paths = fixture_tree(tmp_path)
    manifest = read_json(paths["manifest"])
    if mode == "empty":
        manifest["artifacts"] = {}
    else:
        manifest["artifacts"].pop("zkey")
    write_json(paths["manifest"], manifest)
    with pytest.raises(MODULE.EvidenceError, match="artifact set"):
        collect(paths)


def test_manifest_rejects_wrong_profile(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    manifest = read_json(paths["manifest"])
    manifest["profile"] = "v4-paper-k30"
    write_json(paths["manifest"], manifest)
    with pytest.raises(MODULE.EvidenceError, match="profile"):
        collect(paths)


def test_manifest_rejects_non_list_public_signal_order(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    manifest = read_json(paths["manifest"])
    manifest["public_signal_order"] = {
        signal: True for signal in MODULE.PUBLIC_SIGNALS
    }
    paths["manifest"].write_text(
        json.dumps(manifest, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(MODULE.EvidenceError, match="public-signal"):
        collect(paths)


@pytest.mark.parametrize("mode", ["absolute", "parent", "symlink"])
def test_manifest_rejects_artifact_path_escape(tmp_path: Path, mode: str) -> None:
    paths = fixture_tree(tmp_path)
    outside = tmp_path / "outside.r1cs"
    outside.write_bytes(b"outside-artifact")
    manifest = read_json(paths["manifest"])
    item = manifest["artifacts"]["r1cs"]
    if mode == "absolute":
        item["path"] = str(outside.resolve())
    elif mode == "parent":
        item["path"] = "../outside.r1cs"
    else:
        link = paths["repo"] / "artifacts/escape.r1cs"
        link.symlink_to(outside)
        item["path"] = link.relative_to(paths["repo"]).as_posix()
    item["sha256"] = hashlib.sha256(outside.read_bytes()).hexdigest()
    write_json(paths["manifest"], manifest)
    with pytest.raises(MODULE.EvidenceError, match="artifact path"):
        collect(paths)


@pytest.mark.parametrize("mode", ["failed", "duplicate", "empty_name", "short"])
def test_static_gate_rejects_contradictory_details(tmp_path: Path, mode: str) -> None:
    paths = fixture_tree(tmp_path)
    static = read_json(paths["static"])
    if mode == "failed":
        static["checks"][0]["passed"] = False
    elif mode == "duplicate":
        static["checks"][1]["name"] = static["checks"][0]["name"]
    elif mode == "empty_name":
        static["checks"][0]["name"] = " "
    else:
        static["checks"].pop()
    write_json(paths["static"], static)
    with pytest.raises(MODULE.EvidenceError, match="static"):
        collect(paths)


def test_static_gate_rejects_stale_check_name(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    static = read_json(paths["static"])
    static["checks"][0]["name"] = "stale_archive_compatibility"
    write_json(paths["static"], static)
    with pytest.raises(MODULE.EvidenceError, match="static"):
        collect(paths)


@pytest.mark.parametrize("returncode", [1, False])
def test_protocol_gate_rejects_failed_result_detail(
    tmp_path: Path, returncode: object
) -> None:
    paths = fixture_tree(tmp_path)
    protocol = read_json(paths["protocol"])
    protocol["results"][0]["returncode"] = returncode
    write_json(paths["protocol"], protocol)
    with pytest.raises(MODULE.EvidenceError, match="protocol"):
        collect(paths)


@pytest.mark.parametrize("dataset_count", [4, 5.0, False])
def test_protocol_gate_rejects_invalid_dataset_count(
    tmp_path: Path, dataset_count: object
) -> None:
    paths = fixture_tree(tmp_path)
    protocol = read_json(paths["protocol"])
    protocol["dataset_count"] = dataset_count
    write_json(paths["protocol"], protocol)
    with pytest.raises(MODULE.EvidenceError, match="protocol"):
        collect(paths)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposed_avg_jaccard", True),
        ("baseline_avg_jaccard", "0.5"),
        ("proposed_std_jaccard", -0.001),
        ("baseline_std_jaccard", 1.001),
        ("proposed_frr", 1.001),
        ("proposed_mrr", -0.001),
    ],
)
def test_utility_rejects_unsafe_numeric_values(
    tmp_path: Path, field: str, value: object
) -> None:
    paths = fixture_tree(tmp_path)
    utility = read_json(paths["utility"])
    utility["rows"][0][field] = value
    write_json(paths["utility"], utility)
    with pytest.raises(MODULE.EvidenceError, match="utility"):
        collect(paths)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_utility_rejects_nonfinite_values(tmp_path: Path, value: float) -> None:
    paths = fixture_tree(tmp_path)
    utility = read_json(paths["utility"])
    utility["rows"][0]["proposed_avg_jaccard"] = value
    paths["utility"].write_text(
        json.dumps(utility, allow_nan=True), encoding="utf-8"
    )
    with pytest.raises(MODULE.EvidenceError, match="utility"):
        collect(paths)


@pytest.mark.parametrize(
    ("location", "field", "value"),
    [
        ("top", "epsilon", True),
        ("top", "tau", "2"),
        ("row", "fixed_epsilon", False),
        ("row", "fixed_tau", "2"),
    ],
)
def test_utility_rejects_non_numeric_fixed_config(
    tmp_path: Path, location: str, field: str, value: object
) -> None:
    paths = fixture_tree(tmp_path)
    utility = read_json(paths["utility"])
    target = utility if location == "top" else utility["rows"][0]
    target[field] = value
    write_json(paths["utility"], utility)
    with pytest.raises(MODULE.EvidenceError, match="utility"):
        collect(paths)


def test_utility_rejects_inconsistent_delta(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    utility = read_json(paths["utility"])
    utility["rows"][0]["delta_jaccard"] += 0.001
    write_json(paths["utility"], utility)
    with pytest.raises(MODULE.EvidenceError, match="delta"):
        collect(paths)


def test_utility_output_drops_unknown_nonfinite_fields(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    utility = read_json(paths["utility"])
    utility["rows"][0]["unknown_metric"] = float("nan")
    paths["utility"].write_text(
        json.dumps(utility, allow_nan=True), encoding="utf-8"
    )
    evidence = collect(paths)
    assert set(evidence["fixed_utility"][0]) == {
        "dataset",
        "fixed_epsilon",
        "fixed_tau",
        "proposed_avg_jaccard",
        "proposed_std_jaccard",
        "strongest_baseline",
        "baseline_avg_jaccard",
        "baseline_std_jaccard",
        "delta_jaccard",
        "proposed_frr",
        "proposed_mrr",
        "pass",
    }


def test_rendered_tex_uses_current_artifact_and_five_datasets(
    tmp_path: Path,
) -> None:
    evidence = collect(fixture_tree(tmp_path))
    macros = MODULE.render_macros(evidence)
    table = MODULE.render_utility_table(evidence)
    assert r"\newcommand{\VFourConstraints}{3{,}547}" in macros
    assert r"\newcommand{\VFourPublicInputs}{16}" in macros
    assert "SHTPC $\\pm$ std" in table
    assert "Nebula $\\pm$ std" in table
    assert "FRR" in table and "MRR" in table
    assert "partial" not in table

    lines = table.splitlines()
    rendered_rows = lines[lines.index(r"\midrule") + 1 : lines.index(r"\bottomrule")]
    assert rendered_rows == EXPECTED_UTILITY_ROWS
    for row in rendered_rows:
        numeric_values = re.findall(r"[+-]?\d+\.\d+", row)
        assert len(numeric_values) == 7
        assert all(re.fullmatch(r"[+-]?\d+\.\d{3}", value) for value in numeric_values)


def test_rendered_macros_include_only_verified_scale_facts(tmp_path: Path) -> None:
    partial_macros = MODULE.render_macros(collect(fixture_tree(tmp_path / "partial")))
    assert r"\VFourScaleUnits" not in partial_macros

    paths = fixture_tree(tmp_path / "verified")
    write_launcher_pass(paths)
    write_json(paths["scale_summary"], valid_scale_summary(paths))
    macros = MODULE.render_macros(collect(paths))
    assert r"\newcommand{\VFourScaleUnits}{15}" in macros
    assert r"\newcommand{\VFourScaleProofs}{225{,}000}" in macros
    assert r"\newcommand{\VFourScaleProofFailures}{0}" in macros
    assert r"\newcommand{\VFourScaleEvaluationRounds}{150}" in macros
    assert r"\newcommand{\VFourScaleRouteA}{150{,}000}" in macros
    assert r"\newcommand{\VFourScaleRouteR}{150{,}000}" in macros
    assert r"\newcommand{\VFourScaleReconstructions}{150}" in macros
    assert r"\newcommand{\VFourScaleDPReleases}{150}" in macros
    assert r"\newcommand{\VFourScaleTimingUnits}{15}" in macros
    assert r"\newcommand{\VFourScaleTimingExcluded}{0}" in macros
    assert r"\newcommand{\VFourScaleThroughputMean}{4.167}" in macros
    assert r"\newcommand{\VFourScaleThroughputStd}{0.000}" in macros
    assert r"\newcommand{\VFourScaleWallHoursMean}{1.000}" in macros


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("completed_units", "15"),
        ("completed_units", 15.0),
        ("completed_units", True),
        ("completed_units", -1),
        ("completed_units", 16),
        ("total_units", 14),
    ],
)
def test_launcher_rejects_malformed_counts(
    tmp_path: Path, key: str, value: object
) -> None:
    paths = fixture_tree(tmp_path)
    launch = read_json(paths["launch"])
    launch[key] = value
    write_json(paths["launch"], launch)
    with pytest.raises(MODULE.EvidenceError, match="launcher"):
        collect(paths)


def test_launch_pass_is_not_verified_without_strict_summary(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_launcher_pass(paths)
    evidence = collect(paths)
    assert evidence["scale"]["status"] == "partial"


def test_launcher_bool_failed_units_cannot_verify(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_launcher_pass(paths, failed_units=False)
    write_json(paths["scale_summary"], valid_scale_summary(paths))
    evidence = collect(paths)
    assert evidence["scale"]["status"] == "partial"


def test_strict_summary_upgrades_scale_to_verified(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_launcher_pass(paths)
    write_json(paths["scale_summary"], valid_scale_summary(paths))
    evidence = collect(paths)
    assert evidence["scale"]["status"] == "verified"
    assert evidence["scale"]["proof_verified"] == 225000
    assert evidence["scale"]["proof_failed"] == 0
    assert evidence["scale"]["evaluation_rounds"] == 150
    assert evidence["scale"]["route_received_a"] == 150000
    assert evidence["scale"]["route_received_r"] == 150000
    assert evidence["scale"]["reconstruction_passed"] == 150
    assert evidence["scale"]["dp_release_passed"] == 150
    assert evidence["scale"]["timing_units"] == 15
    assert evidence["scale"]["timing_excluded_units"] == 0
    assert evidence["scale"]["proofs_per_second_mean"] == 15000 / 3600
    assert evidence["scale"]["proofs_per_second_std"] == 0.0
    digest = MODULE.sha256(paths["scale_summary"])
    assert evidence["scale"]["summary_sha256"] == digest
    assert evidence["source_receipts"]["scale_summary"] == {
        "path": paths["scale_summary"].relative_to(paths["repo"]).as_posix(),
        "sha256": digest,
    }


def test_strict_summary_accepts_coherent_host_suspension_exclusion(
    tmp_path: Path,
) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["timing_units"] = 14
    summary["timing_excluded_units"] = 1
    summary["timing_excluded_pairs"] = [{"dataset": "tdrive", "seed": 101}]
    summary["overall"]["timing_units"] = 14
    summary["overall"]["timing_excluded_units"] = 1
    summary["by_dataset"]["tdrive"]["timing_units"] = 2
    summary["by_dataset"]["tdrive"]["timing_excluded_units"] = 1
    unit = summary["unit_receipts"][0]
    unit["timing_status"] = "excluded_host_suspension"
    unit["timing_exclusion_reason"] = (
        "inter-round gap exceeds the 7200-second round timeout"
    )
    unit["timing_wall_seconds"] = None
    unit["proofs_per_second"] = None
    unit["max_inter_round_gap_seconds"] = 8000.0
    write_json(paths["scale_summary"], summary)

    evidence = collect(paths)

    assert evidence["scale"]["status"] == "verified"
    assert evidence["scale"]["timing_units"] == 14
    assert evidence["scale"]["timing_excluded_units"] == 1


def test_strict_summary_rejects_missing_unit_matrix(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["unit_receipts"][-1] = dict(summary["unit_receipts"][0])
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_missing_receipt_hash(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["unit_receipts"][0].pop("receipt_sha256")
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_duplicate_unit_hash(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["unit_receipts"][1]["receipt_sha256"] = summary["unit_receipts"][0][
        "receipt_sha256"
    ]
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_stale_manifest_binding(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["source_receipts"]["manifest_sha256"] = "0" * 64
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_stale_launch_binding(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["source_receipts"]["launch_sha256"] = "0" * 64
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_wrong_profile(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["profile"] = "v4-paper-k30"
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_wrong_proof_totals(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["proof_generated"] = 224999
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_wrong_unit_proof_totals(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["unit_receipts"][0]["proof_verified"] = 14999
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_unknown_unit_dataset_without_crashing(
    tmp_path: Path,
) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["unit_receipts"][0]["dataset"] = "unknown"
    assert_summary_not_verified(paths, summary)


@pytest.mark.parametrize("mode", ["dataset_order", "seed_order", "dataset_keys"])
def test_strict_summary_rejects_wrong_matrix_metadata(
    tmp_path: Path, mode: str
) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    if mode == "dataset_order":
        summary["datasets"] = list(reversed(summary["datasets"]))
    elif mode == "seed_order":
        summary["seeds"] = list(reversed(summary["seeds"]))
    else:
        summary["by_dataset"].pop("synthetic")
    assert_summary_not_verified(paths, summary)


@pytest.mark.parametrize("value", [-1.0, float("nan")])
def test_strict_summary_rejects_invalid_aggregate_metric(
    tmp_path: Path, value: float
) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    summary["by_dataset"]["tdrive"]["proofs_per_second_mean"] = value
    assert_summary_not_verified(paths, summary, allow_nan=not value == value)


@pytest.mark.parametrize("scope", ["overall", "dataset"])
def test_strict_summary_rejects_tampered_timing_aggregate(
    tmp_path: Path, scope: str
) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    target = summary["overall"] if scope == "overall" else summary["by_dataset"]["tdrive"]
    target["proofs_per_second_mean"] += 0.25
    assert_summary_not_verified(paths, summary)


@pytest.mark.parametrize(
    ("mutation", "allow_nan"),
    [
        (lambda summary: summary.__setitem__("timing_units", 14), False),
        (
            lambda summary: summary["by_dataset"]["tdrive"].__setitem__(
                "timing_units", 1
            ),
            False,
        ),
        (
            lambda summary: summary["unit_receipts"][0].__setitem__(
                "timing_status", "unknown"
            ),
            False,
        ),
        (
            lambda summary: summary["overall"].__setitem__(
                "proofs_per_second_mean", float("nan")
            ),
            True,
        ),
    ],
)
def test_strict_summary_rejects_incoherent_timing_contract(
    tmp_path: Path, mutation, allow_nan: bool
) -> None:
    paths = fixture_tree(tmp_path)
    summary = bound_scale_summary(paths)
    mutation(summary)
    assert_summary_not_verified(paths, summary, allow_nan=allow_nan)
