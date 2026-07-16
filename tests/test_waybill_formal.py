from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from common.resource_probe import parse_time_evidence
from script import run_waybill_m2_circuit_matrix as m2
from waybill_formal.core import (
    FormalError,
    build_code_manifest,
    build_data_manifest,
    canonical_sha256,
    expand_protocol_jobs,
    merge_run,
    next_attempt,
    read_json,
    resume_job_ids,
    validate_data_manifest,
    validate_formal_entrypoints,
    validate_protocol,
    validate_tariff_registry,
    write_json,
    write_jsonl,
)


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "configs/waybill_formal/protocol-v1.json"
TARIFF_REGISTRY_PATH = ROOT / "configs/waybill_formal/tariff-registry-v1.json"


def test_protocol_is_frozen_to_m4_and_static_cardinality_is_exact() -> None:
    protocol = read_json(PROTOCOL_PATH)
    receipt = validate_protocol(protocol)
    jobs, plan = expand_protocol_jobs(protocol)

    assert receipt["status"] == "passed"
    assert plan["materialized"] is False
    assert plan["stage_job_counts"] == {
        "S1": 292,
        "S2": 56,
        "S3": 0,
        "S4": 1260,
        "S5": 87,
    }
    assert plan["static_job_count_excluding_S3"] == 1695
    assert len(jobs) == 1695
    assert len({job["job_id"] for job in jobs}) == len(jobs)


def test_protocol_rejects_any_development_cap() -> None:
    protocol = read_json(PROTOCOL_PATH)
    protocol["formal_caps"]["max_raw_points"] = 1
    with pytest.raises(FormalError, match="caps must be zero"):
        validate_protocol(protocol)


def test_s3_cardinality_materializes_from_canonical_instance_ledger() -> None:
    protocol = read_json(PROTOCOL_PATH)
    instances = []
    for period in ("a", "b"):
        for bucket in (100, 50, 25, 10):
            for radius in (50, 100, 200):
                instances.append(
                    {
                        "instance_id": f"{period}-{bucket}-{radius}",
                        "path": f"instances/{period}-{bucket}-{radius}.json",
                        "sha256": "1" * 64,
                        "bucket_m": bucket,
                        "radius_m": radius,
                    }
                )
    prepared = {
        "canonical_period_count": 2,
        "canonical_instances": instances,
    }
    jobs, plan = expand_protocol_jobs(protocol, prepared)

    assert plan["materialized"] is True
    assert plan["canonical_period_count"] == 2
    assert plan["canonical_instance_count"] == 24
    assert plan["stage_job_counts"]["S3"] == 24
    assert plan["expected_job_count"] == 1719
    assert len(jobs) == 1719


def test_tariff_registry_separates_capacity_and_economic_semantics() -> None:
    receipt = validate_tariff_registry(read_json(TARIFF_REGISTRY_PATH), ROOT)
    assert receipt["status"] == "passed"
    assert {row["semantic_class"] for row in receipt["checks"]} == {
        "normalized_capacity",
        "experimental_economic",
    }
    assert validate_formal_entrypoints(ROOT)["status"] == "passed"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_code_manifest_reads_skip_worktree_files_from_frozen_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = repo / "source"
    source.mkdir(parents=True)
    (source / "present.txt").write_text("present\n", encoding="utf-8")
    hidden = source / "hidden.txt"
    hidden.write_text("hidden\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "source"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    subprocess.run(
        ["git", "update-index", "--skip-worktree", "source/hidden.txt"],
        cwd=repo,
        check=True,
    )
    hidden.unlink()

    manifest = build_code_manifest(repo, [Path("source")])

    assert manifest["git_dirty"] is False
    assert [row["path"] for row in manifest["files"]] == [
        "source/hidden.txt",
        "source/present.txt",
    ]
    assert manifest["files"][0]["sha256"] == hashlib.sha256(b"hidden\n").hexdigest()


def test_raw_data_manifest_enforces_counts_hashes_and_zero_caps(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    tdrive = data_root / "raw/tdrive"
    geolife = data_root / "raw/geolife/001/Trajectory"
    porto = data_root / "raw/porto"
    rome = data_root / "raw/rome"
    for directory in (tdrive, geolife, porto, rome):
        directory.mkdir(parents=True)
    (tdrive / "1.txt").write_text("a", encoding="utf-8")
    (tdrive / "2.txt").write_text("b", encoding="utf-8")
    (geolife / "x.plt").write_text("g", encoding="utf-8")
    (porto / "train.zip").write_bytes(b"porto")
    (rome / "Roma.txt").write_bytes(b"rome")
    registry = {
        "schema": "waybill.formal.data-sources/v1",
        "datasets": [
            {
                "dataset": "tdrive",
                "relative_path": "raw/tdrive",
                "kind": "directory",
                "include_glob": "*.txt",
                "expected_file_count": 2,
                "expected_entity_count": 2,
                "official_url": "https://example.test/tdrive",
                "terms": "test",
            },
            {
                "dataset": "geolife",
                "relative_path": "raw/geolife",
                "kind": "directory",
                "include_glob": "**/*.plt",
                "expected_file_count": 1,
                "expected_entity_count": 1,
                "official_url": "https://example.test/geolife",
                "terms": "test",
            },
            {
                "dataset": "porto",
                "relative_path": "raw/porto/train.zip",
                "kind": "file",
                "expected_file_count": 1,
                "expected_bytes": 5,
                "expected_sha256": _sha(porto / "train.zip"),
                "expected_entity_count": 1,
                "official_url": "https://example.test/porto",
                "terms": "test",
            },
            {
                "dataset": "rome",
                "relative_path": "raw/rome/Roma.txt",
                "kind": "file",
                "expected_file_count": 1,
                "expected_bytes": 4,
                "expected_sha256": _sha(rome / "Roma.txt"),
                "expected_entity_count": 1,
                "official_url": "https://example.test/rome",
                "terms": "test",
            },
        ],
    }

    output_dir = tmp_path / "manifest"
    manifest = build_data_manifest(registry, data_root, output_dir)
    receipt = validate_data_manifest(manifest, registry, output_dir)

    assert receipt["status"] == "passed"
    assert manifest["raw_file_count"] == 5
    assert all(value == 0 for value in manifest["formal_caps"].values())


def _fake_run(tmp_path: Path, job_ids: list[str]) -> Path:
    run_root = tmp_path / "run"
    write_jsonl(
        run_root / "jobs/expected.jsonl",
        [
            {
                "job_id": job_id,
                "stage": "S1",
                "kind": "test",
                "parameters": {},
                "timeout_sec": 1,
                "resource": {},
                "command": ["true"],
            }
            for job_id in job_ids
        ],
    )
    return run_root


def test_strict_merge_fails_closed_on_missing_unit(tmp_path: Path) -> None:
    run_root = _fake_run(tmp_path, ["a", "b"])
    attempt, attempt_dir = next_attempt(run_root, "a")
    write_json(
        attempt_dir / "receipt.json",
        {"schema": "test", "job_id": "a", "attempt": attempt, "status": "passed"},
        exclusive=True,
    )

    aggregate = merge_run(run_root)

    assert aggregate["status"] == "failed"
    assert aggregate["missing_jobs"] == ["b"]
    assert read_json(run_root / "status.json")["status"] == "failed"


def test_attempts_are_immutable_resume_is_bounded_and_first_success_wins(tmp_path: Path) -> None:
    run_root = _fake_run(tmp_path, ["a"])
    attempt1, dir1 = next_attempt(run_root, "a")
    write_json(
        dir1 / "receipt.json",
        {"schema": "test", "job_id": "a", "attempt": attempt1, "status": "failed"},
        exclusive=True,
    )
    assert resume_job_ids(run_root) == ["a"]

    attempt2, dir2 = next_attempt(run_root, "a")
    write_json(
        dir2 / "receipt.json",
        {"schema": "test", "job_id": "a", "attempt": attempt2, "status": "passed"},
        exclusive=True,
    )
    with pytest.raises(FormalError, match="exhausted"):
        next_attempt(run_root, "a")

    aggregate = merge_run(run_root)
    assert aggregate["status"] == "passed"
    assert aggregate["units"][0]["selected_attempt"] == 2
    assert resume_job_ids(run_root) == []


def test_resource_parser_distinguishes_linux_kib_and_macos_bytes() -> None:
    linux = parse_time_evidence(
        "Maximum resident set size (kbytes): 2048\n"
        "User time (seconds): 1.25\n"
        "System time (seconds): 0.50\n",
        "gnu-time-v",
    )
    mac = parse_time_evidence("  2048  maximum resident set size\n", "bsd-time-l")

    assert linux["max_rss_bytes"] == 2 * 1024 * 1024
    assert linux["user_cpu_sec"] == 1.25
    assert linux["system_cpu_sec"] == 0.5
    assert mac["max_rss_bytes"] == 2048


def test_s2_capacity_matched_tariffs_cover_all_frozen_depths() -> None:
    counts = {}
    roots = {}
    for depth in (8, 12, 14, 16):
        tariff, manifest = m2.load_city_tariff(depth, fresh=True)
        counts[depth] = len(tariff.cell_zones)
        roots[depth] = tariff.root(depth)
        assert len(tariff.path_for_cell(0, depth)) == depth
        assert int(manifest["tree"]["depth"]) == depth

    assert counts == {8: 256, 12: 4096, 14: 10000, 16: 10000}
    assert len(set(roots.values())) == 4


@pytest.mark.parametrize("depth", [8, 12, 14, 16])
def test_s2_formal_input_binds_each_depth_to_its_own_profile(
    tmp_path: Path,
    depth: int,
) -> None:
    paths = m2.config_paths(tmp_path, depth, 25)
    paths["vkey"].parent.mkdir(parents=True, exist_ok=True)
    paths["vkey"].write_text('{"protocol":"groth16"}\n', encoding="utf-8")
    profile = m2.create_policy_profile_for_config(
        output_dir=tmp_path,
        depth=depth,
        fixes_count=25,
        verification_key_path=paths["vkey"],
    )
    circuit_input, metadata = m2.build_city_input_for_config(
        depth,
        25,
        policy_profile=profile,
    )

    assert profile.tariff_tree_depth == depth
    assert profile.circuit_id == m2.wrapper_name(depth, 25)
    assert metadata["tariff_tree_depth"] == depth
    assert len(circuit_input["zone_path_sibling"]) == 24
    assert all(len(path) == depth for path in circuit_input["zone_path_sibling"])


def test_canonical_hash_is_independent_of_mapping_order() -> None:
    assert canonical_sha256({"a": 1, "b": 2}) == canonical_sha256({"b": 2, "a": 1})
