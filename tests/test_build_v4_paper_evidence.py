import hashlib
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "script" / "build_v4_paper_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_v4_paper_evidence", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture_tree(tmp_path: Path) -> dict[str, Path]:
    artifact = tmp_path / "artifact.r1cs"
    artifact.write_bytes(b"paper-r1cs")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    static = tmp_path / "static.json"
    protocol = tmp_path / "protocol.json"
    utility = tmp_path / "utility.json"
    launch = tmp_path / "launch.json"
    scale_summary = tmp_path / "aggregate_summary.json"
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
            "artifacts": {
                "r1cs": {"path": "artifact.r1cs", "sha256": digest}
            },
            "setup": "development Groth16 setup; not a production ceremony",
        },
    )
    write_json(
        static,
        {"state": "pass", "summary": {"passed": 22, "failed": 0}},
    )
    write_json(
        protocol,
        {
            "state": "pass",
            "dataset_count": 5,
            "pass_count": 5,
            "results": [{"dataset": name} for name in MODULE.DATASETS],
        },
    )
    rows = []
    for name in MODULE.DATASETS:
        rows.append(
            {
                "dataset": name,
                "fixed_epsilon": 5,
                "fixed_tau": 2,
                "proposed_avg_jaccard": 0.7,
                "proposed_std_jaccard": 0.02,
                "strongest_baseline": "nebula",
                "baseline_avg_jaccard": 0.6,
                "baseline_std_jaccard": 0.01,
                "delta_jaccard": 0.1,
                "proposed_frr": 0,
                "proposed_mrr": 1,
                "pass": True,
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
        "repo": tmp_path,
        "manifest": manifest,
        "static": static,
        "protocol": protocol,
        "utility": utility,
        "launch": launch,
        "scale_summary": scale_summary,
    }


def test_collect_evidence_separates_verified_and_partial_layers(
    tmp_path: Path,
) -> None:
    paths = fixture_tree(tmp_path)
    evidence = MODULE.collect_evidence(**paths)
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


def test_collect_evidence_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    (tmp_path / "artifact.r1cs").write_bytes(b"tampered")
    try:
        MODULE.collect_evidence(**paths)
    except MODULE.EvidenceError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("hash mismatch must fail evidence collection")


def test_rendered_tex_uses_current_artifact_and_five_datasets(
    tmp_path: Path,
) -> None:
    evidence = MODULE.collect_evidence(**fixture_tree(tmp_path))
    macros = MODULE.render_macros(evidence)
    table = MODULE.render_utility_table(evidence)
    assert r"\newcommand{\VFourConstraints}{3{,}547}" in macros
    assert r"\newcommand{\VFourPublicInputs}{16}" in macros
    assert all(
        label in table
        for label in ("T-Drive", "GeoLife", "Porto", "Rome", "Synthetic")
    )
    assert "SHTPC $\\pm$ std" in table
    assert "Nebula $\\pm$ std" in table
    assert "FRR" in table and "MRR" in table
    assert "partial" not in table


def test_launch_pass_is_not_verified_without_strict_summary(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_json(
        paths["launch"],
        {
            "state": "pass",
            "completed_units": 15,
            "total_units": 15,
            "failed_units": 0,
        },
    )
    evidence = MODULE.collect_evidence(**paths)
    assert evidence["scale"]["status"] == "partial"


def test_strict_summary_upgrades_scale_to_verified(tmp_path: Path) -> None:
    paths = fixture_tree(tmp_path)
    write_json(
        paths["launch"],
        {
            "state": "pass",
            "completed_units": 15,
            "total_units": 15,
            "failed_units": 0,
        },
    )
    write_json(
        paths["scale_summary"],
        {
            "status": "verified",
            "units": 15,
            "rounds": 240,
            "evaluation_rounds": 150,
            "proof_failed": 0,
        },
    )
    evidence = MODULE.collect_evidence(**paths)
    assert evidence["scale"]["status"] == "verified"
    assert evidence["scale"]["summary_sha256"] == MODULE.sha256(
        paths["scale_summary"]
    )
