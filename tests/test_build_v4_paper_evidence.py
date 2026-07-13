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
                {"name": f"static-check-{index:02d}", "passed": True}
                for index in range(22)
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
        "launch": launch,
        "scale_summary": scale_summary,
    }


def valid_scale_summary() -> dict:
    by_dataset = {}
    for index, dataset in enumerate(MODULE.DATASETS):
        by_dataset[dataset] = {
            "units": 3,
            "proofs_per_second_mean": 100.0 + index,
            "proofs_per_second_std": 1.0 + index / 10,
            "wall_seconds_mean": 3600.0 + index,
            "wall_seconds_std": 10.0 + index,
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
        "evaluation_rounds": 150,
        "proof_generated": 225000,
        "proof_verified": 225000,
        "proof_failed": 0,
        "by_dataset": by_dataset,
        "unit_receipts": unit_receipts,
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


def collect(paths: dict[str, Path]) -> dict:
    return MODULE.collect_evidence(**paths)


def assert_summary_not_verified(
    paths: dict[str, Path], summary: dict, *, allow_nan: bool = False
) -> dict:
    write_launcher_pass(paths)
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
    expected_keys = {"manifest", "static", "protocol", "utility", "launch"}
    assert set(evidence["source_receipts"]) == expected_keys
    for name in expected_keys:
        path = paths[name]
        assert evidence["source_receipts"][name] == {
            "path": path.relative_to(paths["repo"]).as_posix(),
            "sha256": MODULE.sha256(path),
        }


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
    write_json(paths["scale_summary"], valid_scale_summary())
    evidence = collect(paths)
    assert evidence["scale"]["status"] == "partial"


def test_strict_summary_upgrades_scale_to_verified(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_launcher_pass(paths)
    write_json(paths["scale_summary"], valid_scale_summary())
    evidence = collect(paths)
    assert evidence["scale"]["status"] == "verified"
    digest = MODULE.sha256(paths["scale_summary"])
    assert evidence["scale"]["summary_sha256"] == digest
    assert evidence["source_receipts"]["scale_summary"] == {
        "path": paths["scale_summary"].relative_to(paths["repo"]).as_posix(),
        "sha256": digest,
    }


def test_strict_summary_rejects_missing_unit_matrix(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = valid_scale_summary()
    summary["unit_receipts"][-1] = dict(summary["unit_receipts"][0])
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_missing_receipt_hash(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = valid_scale_summary()
    summary["unit_receipts"][0].pop("receipt_sha256")
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_wrong_profile(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = valid_scale_summary()
    summary["profile"] = "v4-paper-k30"
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_wrong_proof_totals(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = valid_scale_summary()
    summary["proof_generated"] = 224999
    assert_summary_not_verified(paths, summary)


def test_strict_summary_rejects_wrong_unit_proof_totals(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    summary = valid_scale_summary()
    summary["unit_receipts"][0]["proof_verified"] = 14999
    assert_summary_not_verified(paths, summary)


@pytest.mark.parametrize("mode", ["dataset_order", "seed_order", "dataset_keys"])
def test_strict_summary_rejects_wrong_matrix_metadata(
    tmp_path: Path, mode: str
) -> None:
    paths = fixture_tree(tmp_path)
    summary = valid_scale_summary()
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
    summary = valid_scale_summary()
    summary["by_dataset"]["tdrive"]["proofs_per_second_mean"] = value
    assert_summary_not_verified(paths, summary, allow_nan=not value == value)
