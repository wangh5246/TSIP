from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from common.resource_probe import parse_time_evidence
from script import materialize_waybill_formal_corpus as materialize_corpus
from script import run_waybill_m2_circuit_matrix as m2
from script.waybill_formal_cli import DEFAULT_CODE_MANIFEST_PATHS
from waybill_formal import core as formal_core
from waybill_formal.core import (
    FORMAL_PTAU_BLAKE2B,
    FORMAL_PTAU_BYTES,
    FormalError,
    build_code_manifest,
    build_data_manifest,
    canonical_sha256,
    execute_job,
    expand_protocol_jobs,
    initialize_run,
    merge_run,
    next_attempt,
    read_json,
    read_jsonl,
    render_slurm_array,
    resume_job_ids,
    seal_gate_receipt,
    validate_data_manifest,
    validate_formal_entrypoints,
    validate_gate_receipts,
    validate_protocol,
    validate_run_seal,
    validate_tariff_registry,
    write_json,
    write_jsonl,
    write_plan,
    tool_version,
    _s3_aggregate_gate,
)
from waybill_formal.stage import finish_stage


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = ROOT / "configs/waybill_formal/protocol-v1.json"
TARIFF_REGISTRY_PATH = ROOT / "configs/waybill_formal/tariff-registry-v1.json"


def test_tool_version_accepts_only_explicit_nonzero_cli_contract() -> None:
    command = ["sh", "-c", "printf 'snarkjs@0.7.6\\n'; exit 99"]
    assert tool_version(command) is None
    assert tool_version(command, allowed_returncodes=(0, 99)) == "snarkjs@0.7.6"


def test_materializer_resume_reuses_only_verified_canonical_payloads(tmp_path: Path) -> None:
    path = tmp_path / "instances" / "tdrive" / "instance.json"
    payload = {"instance_id": "a", "fixes": [{"t": 1}]}

    materialize_corpus._write_or_verify_instance(path, payload, resume=False)
    materialize_corpus._write_or_verify_instance(path, payload, resume=True)

    with pytest.raises(FormalError, match="differs from expected"):
        materialize_corpus._write_or_verify_instance(
            path, {"instance_id": "a", "fixes": [{"t": 2}]}, resume=True
        )

    manifest_path = tmp_path / "prepared_manifest.json"
    manifest = {"schema": "waybill.formal.prepared-manifest/v1", "value": 1}
    materialize_corpus._write_or_verify_manifest(manifest_path, manifest, resume=False)
    materialize_corpus._write_or_verify_manifest(manifest_path, manifest, resume=True)

    with pytest.raises(FormalError, match="prepared manifest differs"):
        materialize_corpus._write_or_verify_manifest(
            manifest_path, {"schema": "waybill.formal.prepared-manifest/v1", "value": 2}, resume=True
        )


def test_host_preflight_pins_workdir_and_accepts_snarkjs_cli_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime/formal.sif"
    workspace = tmp_path / "workspace"
    runtime.parent.mkdir()
    workspace.mkdir()
    runtime.write_bytes(b"sif")
    observed: list[tuple[list[str], tuple[int, ...]]] = []

    def fake_tool_version(
        command: list[str],
        *,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> str | None:
        observed.append((list(command), tuple(allowed_returncodes)))
        executable = command[-2] if command[-1] == "--version" else "npm"
        return {
            "apptainer": "apptainer version 1.5.3",
            "python": "Python 3.12.13",
            "node": "v26.5.1",
            "npm": "absent",
            "circom": "circom compiler 2.1.9",
            "snarkjs": "snarkjs@0.7.6",
        }.get(executable)

    bindings = {
        "schema": "waybill.formal.embedded-release-binding/v1",
        "protocol_sha256": canonical_sha256(read_json(PROTOCOL_PATH)),
    }

    def fake_command_output(
        command: list[str],
        *,
        timeout_sec: int = 60,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> tuple[bool, str]:
        del timeout_sec, allowed_returncodes
        if "cat" in command:
            import json

            return True, json.dumps(bindings)
        return True, "passed"

    monkeypatch.setattr(formal_core, "tool_version", fake_tool_version)
    monkeypatch.setattr(formal_core, "command_output", fake_command_output)
    monkeypatch.setattr(
        formal_core,
        "collect_host_evidence",
        lambda _workspace: {
            "physical_memory_bytes": 64 * 1024**3,
            "disk": {"free_bytes": 600 * 1024**3},
        },
    )

    receipt = formal_core.host_preflight(
        root=ROOT,
        protocol=read_json(PROTOCOL_PATH),
        workspace=workspace,
        container_digest="sha256:" + "a" * 64,
        expected_container_digest="sha256:" + "a" * 64,
        container_runtime_image=runtime,
        expected_container_runtime_sha256=hashlib.sha256(b"sif").hexdigest(),
    )

    snarkjs_calls = [item for item in observed if item[0][-2:] == ["snarkjs", "--version"]]
    assert snarkjs_calls and snarkjs_calls[0][1] == (0, 99)
    assert "--pwd" in snarkjs_calls[0][0]
    assert snarkjs_calls[0][0][snarkjs_calls[0][0].index("--pwd") + 1] == "/work"
    assert receipt["checks"]["container_snarkjs_0_7_6"] is True


def _embedded_binding(bindings: dict[str, str]) -> dict[str, str]:
    return {
        "schema": "waybill.formal.embedded-release-binding/v1",
        "git_commit": bindings["git_commit"],
        "git_tree": bindings["git_tree"],
        "code_manifest_sha256": bindings["code_manifest_sha256"],
        "protocol_sha256": bindings["protocol_sha256"],
    }


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
    assert all(
        job["command"]
        == ["python", "-m", f"script.run_waybill_{job['stage'].lower()}_formal_unit"]
        for job in jobs
    )


def test_materialized_plan_excludes_only_explicitly_inevaluable_s4_strata() -> None:
    protocol = read_json(PROTOCOL_PATH)
    spec = protocol["stages"]["S4"]
    rows = []
    for dataset in protocol["datasets"]:
        for horizon in spec["horizons"]:
            eligible = not (dataset == "tdrive" and horizon == 4)
            rows.append(
                {
                    "dataset": dataset,
                    "horizon": horizon,
                    "periods_sha256": "a" * 64,
                    "original_identity_count": 4 if eligible else 3,
                    "sequence_eligible_identity_count": 4 if eligible else 3,
                    "sequence_count": 8 if eligible else 6,
                    "minimum_sequence_identities": 4,
                    "eligible": eligible,
                    "status": "eligible" if eligible else "not-evaluable",
                    "reason": (
                        None
                        if eligible
                        else "insufficient-original-identities-with-two-disjoint-windows"
                    ),
                }
            )
    matrix = {
        "schema": "waybill.formal.s4-eligibility/v1",
        "split": spec["split"],
        "temporal_gap_periods": spec["temporal_gap_periods"],
        "minimum_sequence_identities": 4,
        "ineligible_stratum_policy": "exclude-before-run-and-report",
        "rows": rows,
    }
    jobs, _plan = expand_protocol_jobs(
        protocol,
        {
            "canonical_instances": [],
            "s4_eligibility": {"matrix_sha256": canonical_sha256(matrix), "rows": rows},
        },
    )
    s4_jobs = [job for job in jobs if job["stage"] == "S4"]

    assert len(s4_jobs) == 1_155
    assert not any(
        job["parameters"]["dataset"] == "tdrive"
        and job["parameters"]["horizon"] == 4
        for job in s4_jobs
    )
    assert {
        job["parameters"]["s4_eligibility_matrix_sha256"] for job in s4_jobs
    } == {canonical_sha256(matrix)}


def test_s4_eligibility_matrix_rejects_non_boolean_status() -> None:
    protocol = read_json(PROTOCOL_PATH)
    spec = protocol["stages"]["S4"]
    rows = [
        {
            "dataset": dataset,
            "horizon": horizon,
            "periods_sha256": "a" * 64,
            "original_identity_count": 4,
            "sequence_eligible_identity_count": 4,
            "sequence_count": 8,
            "minimum_sequence_identities": 4,
            "eligible": True,
            "status": "eligible",
            "reason": None,
        }
        for dataset in protocol["datasets"]
        for horizon in spec["horizons"]
    ]
    rows[0]["eligible"] = "true"
    matrix = {
        "schema": "waybill.formal.s4-eligibility/v1",
        "split": spec["split"],
        "temporal_gap_periods": spec["temporal_gap_periods"],
        "minimum_sequence_identities": 4,
        "ineligible_stratum_policy": "exclude-before-run-and-report",
        "rows": rows,
    }

    with pytest.raises(FormalError, match="eligibility flag is not boolean"):
        expand_protocol_jobs(
            protocol,
            {
                "canonical_instances": [],
                "s4_eligibility": {
                    "matrix_sha256": canonical_sha256(matrix),
                    "rows": rows,
                },
            },
        )


def test_protocol_rejects_any_development_cap() -> None:
    protocol = read_json(PROTOCOL_PATH)
    protocol["formal_caps"]["max_raw_points"] = 1
    with pytest.raises(FormalError, match="caps must be zero"):
        validate_protocol(protocol)


def test_gate_receipts_require_v2_schema_and_canonical_hash() -> None:
    bindings = {
        "code_manifest_sha256": "c" * 64,
        "git_commit": "d" * 40,
        "git_tree": "e" * 40,
        "protocol_sha256": "f" * 64,
    }
    receipts = [
        seal_gate_receipt(
            gate=f"RG{index}",
            status="passed",
            evidence=(
                {
                    "schema": "waybill.formal.target-host-preflight/v2",
                    "status": "passed",
                    "checks": {"all": True},
                    "container_runtime": {
                        "sha256": "a" * 64,
                        "expected_sha256": "a" * 64,
                    },
                    "ptau": {
                        "path": "/frozen/powers.ptau",
                        "exists": True,
                        "bytes": FORMAL_PTAU_BYTES,
                        "blake2b": FORMAL_PTAU_BLAKE2B,
                    },
                    "container_digest": "sha256:" + "b" * 64,
                    "expected_container_digest": "sha256:" + "b" * 64,
                    "embedded_release_binding": _embedded_binding(bindings),
                }
                if index == 6
                else {"ok": True}
            ),
        )
        for index in range(9)
    ]
    assert validate_gate_receipts(receipts)["status"] == "passed"
    receipts[0]["evidence"]["ok"] = False
    with pytest.raises(FormalError, match="hash mismatch"):
        validate_gate_receipts(receipts)


def test_s3_cardinality_materializes_from_canonical_instance_ledger() -> None:
    protocol = read_json(PROTOCOL_PATH)
    instances = []
    for period in ("a", "b"):
        for bucket in (100, 50, 25, 10):
            for radius in (50, 100, 200):
                instances.append(
                    {
                        "instance_id": f"{period}-{bucket}-{radius}",
                        "dataset": "tdrive",
                        "period_id": period,
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
    assert plan["stage_job_counts"]["S3"] == 6
    assert plan["expected_job_count"] == 1701
    assert len(jobs) == 1701
    s3_jobs = [job for job in jobs if job["stage"] == "S3"]
    assert all(job["kind"] == "certified-bound-group" for job in s3_jobs)
    assert all(len(job["parameters"]["instances"]) == 4 for job in s3_jobs)
    assert all(job["parameters"]["instance_timeout_sec"] == 7200 for job in s3_jobs)


def _s3_receipt(instance_id: str, *, gap_ppm: int, status: str = "certified") -> dict:
    if status != "certified":
        return {
            "status": status,
            "instance": {"instance_id": instance_id},
            "error": "retained unresolved instance",
        }
    return {
        "status": "certified",
        "instance": {"instance_id": instance_id},
        "LB_cents": 100,
        "UB_cents": 101,
        "relative_gap_ppm": gap_ppm,
        "timeout": False,
        "lower_bound": {"checker": {"accepted": True}},
        "upper_bound": {"independent_cross_check": {"direction_ok": True}},
    }


def _s3_group(index: int) -> tuple[dict, dict]:
    instances = [
        {
            "instance_id": f"period-{index}:bucket-{bucket}m:radius-50m",
            "bucket_m": bucket,
        }
        for bucket in (100, 50, 25, 10)
    ]
    job = {
        "job_id": f"s3-{index}",
        "stage": "S3",
        "parameters": {
            "group_id": f"period-{index}:radius-50m",
            "radius_m": 50,
            "instances": instances,
            "main_gap_max": 0.01,
            "all_instance_certified_share_min": 0.95,
            "all_instance_gap_max": 0.05,
        },
    }
    result = {
        "small_oracle_gate_passed": True,
        "soundness_failures": [],
        "bound_receipts": [
            _s3_receipt(record["instance_id"], gap_ppm=9_000 if record["bucket_m"] == 100 else 40_000)
            for record in instances
        ]
    }
    return job, result


def test_s3_aggregate_enforces_main_gap_and_95_percent_all_instance_gate() -> None:
    selected = [_s3_group(index) for index in range(5)]
    jobs = [job for job, _result in selected]

    passed = _s3_aggregate_gate(jobs, selected)
    assert passed["passed"] is True
    assert passed["certified_and_bounded_share"] == 1.0
    assert all(
        row["gap_threshold_ppm"] == (10_000 if row["main_representative"] else 50_000)
        for row in passed["rows"]
    )

    selected[0][1]["bound_receipts"][-1] = _s3_receipt(
        selected[0][0]["parameters"]["instances"][-1]["instance_id"],
        gap_ppm=0,
        status="failed",
    )
    exactly_95 = _s3_aggregate_gate(jobs, selected)
    assert exactly_95["passed"] is True
    assert exactly_95["certified_and_bounded_share"] == 0.95

    selected[0][1]["bound_receipts"][-1]["failure_class"] = "soundness-failure"
    fatal_at_95 = _s3_aggregate_gate(jobs, selected)
    assert fatal_at_95["passed"] is False
    assert fatal_at_95["fatal_soundness_instances"]
    selected[0][1]["bound_receipts"][-1].pop("failure_class")

    selected[1][1]["bound_receipts"][-1] = _s3_receipt(
        selected[1][0]["parameters"]["instances"][-1]["instance_id"],
        gap_ppm=0,
        status="failed",
    )
    below_95 = _s3_aggregate_gate(jobs, selected)
    assert below_95["passed"] is False
    assert below_95["share_gate_passed"] is False

    selected = [_s3_group(index) for index in range(5)]
    selected[0][1]["bound_receipts"][0]["relative_gap_ppm"] = 10_001
    main_failed = _s3_aggregate_gate(
        [job for job, _result in selected], selected
    )
    assert main_failed["passed"] is False
    assert main_failed["main_gate_passed"] is False


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


def test_code_manifest_fails_closed_when_git_metadata_is_inaccessible(tmp_path: Path) -> None:
    repo = tmp_path / "broken-worktree"
    source = repo / "source"
    source.mkdir(parents=True)
    (source / "present.txt").write_text("present\n", encoding="utf-8")
    (repo / ".git").write_text("gitdir: /missing/worktree-metadata\n", encoding="utf-8")

    with pytest.raises(FormalError, match="git repository metadata is present but inaccessible"):
        build_code_manifest(repo, [Path("source")])


def test_default_code_manifest_covers_security_critical_release_inputs() -> None:
    paths = {path.as_posix() for path in DEFAULT_CODE_MANIFEST_PATHS}
    assert {
        ".dockerignore",
        ".env.example",
        ".gitattributes",
        ".gitignore",
        "DATA_NOTICE.md",
        "README_ARTIFACT.md",
        "deploy",
        "services/charger",
        "services/receiver_signer",
        "zk/settlement_period_v6_k6/verification_key.json",
    } <= paths


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
    release_bindings = {
        "schema": "waybill.formal.embedded-release-binding/v1",
        "git_commit": "c" * 40,
        "git_tree": "d" * 40,
        "code_manifest_sha256": "e" * 64,
        "protocol_sha256": "f" * 64,
    }
    execution_container = {
        "schema": "waybill.formal.execution-container/v2",
        "container_source_root": "/work",
        "launcher": "apptainer",
        "network_mode": "none",
        "release_bindings": release_bindings,
        "release_image_digest": "sha256:" + "a" * 64,
        "runtime_image_path": "/opt/waybill/formal.sif",
        "runtime_image_sha256": "b" * 64,
        "workspace_root": "/srv/waybill",
    }
    write_json(run_root / "protocol.json", {})
    write_json(run_root / "plan.json", {})
    write_json(run_root / "code_manifest.json", {})
    write_json(run_root / "data_manifest.json", {})
    write_json(run_root / "environment.json", {})
    write_json(run_root / "container_manifest.json", {})
    write_json(run_root / "prepared_manifest.json", {})
    write_json(run_root / "gate_receipts.json", [])
    write_json(
        run_root / "execution-container.json",
        execution_container,
    )
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
    sealed_inputs = {
        relative: _sha(run_root / relative)
        for relative in (
            "protocol.json",
            "plan.json",
            "jobs/expected.jsonl",
            "code_manifest.json",
            "data_manifest.json",
            "environment.json",
            "container_manifest.json",
            "prepared_manifest.json",
            "gate_receipts.json",
            "execution-container.json",
        )
    }
    write_json(
        run_root / "run.json",
        {
            "schema": "waybill.formal.run/v2",
            "protocol_sha256": canonical_sha256({}),
            "execution_container_sha256": canonical_sha256(execution_container),
            "sealed_inputs": sealed_inputs,
            "sealed_inputs_sha256": canonical_sha256(sealed_inputs),
            "immutable": True,
        },
    )
    return run_root


def _write_valid_passed_attempt(
    *, run_root: Path, job_id: str, attempt: int, attempt_dir: Path
) -> None:
    job = {
        row["job_id"]: row for row in read_jsonl(run_root / "jobs/expected.jsonl")
    }[job_id]
    write_json(attempt_dir / "job.json", job, exclusive=True)
    (attempt_dir / "output.txt").write_text("verified\n", encoding="utf-8")
    finish_stage(
        job=job,
        attempt_dir=attempt_dir,
        payload={"status": "passed", "output": "output.txt"},
    )
    stage = read_json(attempt_dir / "stage-result.json")
    receipt = {
        "schema": "waybill.formal.attempt-receipt/v2",
        "job_id": job_id,
        "attempt": attempt,
        "status": "passed",
        "command": ["true"],
        "started_at": "2026-07-28T00:00:00+00:00",
        "elapsed_ms": 1.0,
        "returncode": 0,
        "timed_out": False,
        "max_rss_bytes": None,
        "user_cpu_sec": None,
        "system_cpu_sec": None,
        "measurement_backend": "test",
        "stdout_tail": "",
        "stderr_tail": "",
        "error": None,
        "execution_container": read_json(run_root / "execution-container.json"),
        "job_sha256": canonical_sha256(job),
        "stage_result_sha256": stage["result_sha256"],
        "artifact_manifest_sha256": stage["artifact_manifest_sha256"],
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    write_json(attempt_dir / "receipt.json", receipt, exclusive=True)


def _write_valid_resource_rejected_attempt(
    *, run_root: Path, job_id: str, attempt: int, attempt_dir: Path
) -> None:
    job = {
        row["job_id"]: row for row in read_jsonl(run_root / "jobs/expected.jsonl")
    }[job_id]
    write_json(attempt_dir / "job.json", job, exclusive=True)
    finish_stage(
        job=job,
        attempt_dir=attempt_dir,
        payload={
            "status": "failed",
            "outcome_class": "resource-rejected",
            "reason": "available memory is below required memory",
        },
    )
    stage = read_json(attempt_dir / "stage-result.json")
    receipt = {
        "schema": "waybill.formal.attempt-receipt/v2",
        "job_id": job_id,
        "attempt": attempt,
        "status": "failed",
        "command": ["true"],
        "started_at": "2026-08-12T00:00:00+00:00",
        "elapsed_ms": 1.0,
        "returncode": 1,
        "timed_out": False,
        "max_rss_bytes": 1024,
        "user_cpu_sec": 0.1,
        "system_cpu_sec": 0.1,
        "measurement_backend": "test",
        "stdout_tail": "",
        "stderr_tail": "",
        "error": "command exited with status 1",
        "execution_container": read_json(run_root / "execution-container.json"),
        "job_sha256": canonical_sha256(job),
        "stage_status": "failed",
        "stage_outcome_class": "resource-rejected",
        "stage_result_sha256": stage["result_sha256"],
        "artifact_manifest_sha256": stage["artifact_manifest_sha256"],
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    write_json(attempt_dir / "receipt.json", receipt, exclusive=True)


def test_execute_job_fails_closed_outside_frozen_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_root = _fake_run(tmp_path, ["a"])
    monkeypatch.delenv("WAYBILL_CONTAINER", raising=False)
    with pytest.raises(FormalError, match="not running in its container"):
        execute_job(run_root, "a", root=ROOT)
    assert not (run_root / "jobs/attempts/a").exists()


def _stubborn_job_script(pid_file: Path, grandchild_sleep: int) -> str:
    """A job that ignores SIGTERM and leaves a grandchild holding the pipes.

    This reproduces the V14 S5 timeout shape: the measured wrapper's descendant
    outlives a pid-only signal, so an unbounded drain inside ``execute_job``
    would keep waiting for that descendant instead of honouring the timeout.
    """

    return (
        "import signal, subprocess, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        f"'import time; time.sleep({grandchild_sleep})'])\n"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
        "sys.stdout.write('grandchild=' + str(child.pid) + chr(10))\n"
        "sys.stdout.flush()\n"
        f"time.sleep({grandchild_sleep})\n"
    )


def _install_timeout_job(
    run_root: Path, *, timeout_sec: int, command: list[str]
) -> None:
    row = {
        "job_id": "a",
        "stage": "S1",
        "kind": "test",
        "parameters": {},
        "timeout_sec": timeout_sec,
        "resource": {},
        "command": command,
    }
    write_jsonl(run_root / "jobs/expected.jsonl", [row])


def _patch_execution_guards(
    run_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bypass the container/run-seal guards so the process path can be tested."""

    monkeypatch.setattr(
        formal_core,
        "validate_execution_container_environment",
        lambda run_root, *, root: read_json(run_root / "execution-container.json"),
    )
    monkeypatch.setattr(
        formal_core,
        "_validate_run_semantics",
        lambda run_root: read_jsonl(run_root / "jobs/expected.jsonl"),
    )
    monkeypatch.setattr(
        formal_core, "measured_command", lambda command: ([str(c) for c in command], "test")
    )


def test_execute_job_timeout_kills_the_whole_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out job must not report an elapsed time above its own timeout."""

    run_root = _fake_run(tmp_path, ["a"])
    pid_file = tmp_path / "grandchild.pid"
    _install_timeout_job(
        run_root,
        timeout_sec=2,
        command=[
            sys.executable,
            "-c",
            _stubborn_job_script(pid_file, grandchild_sleep=300),
        ],
    )
    _patch_execution_guards(run_root, monkeypatch)

    started = time.perf_counter()
    receipt = execute_job(run_root, "a", root=ROOT)
    wall = time.perf_counter() - started

    assert receipt["timed_out"] is True
    assert receipt["status"] == "failed"
    assert receipt["error"] == "timeout after 2s"

    # The regression: with a pid-only signal plus an unbounded drain, this call
    # returned only after the 300 s grandchild exited, so elapsed_ms contradicted
    # the recorded timeout. Bounding every wait keeps it near the timeout.
    assert wall < 90.0, f"execute_job blocked for {wall:.1f}s after a 2s timeout"
    assert receipt["elapsed_ms"] < 90_000, receipt["elapsed_ms"]

    # The grandchild must have been signalled with the group, not orphaned.
    assert pid_file.is_file(), "the job never reported its grandchild pid"
    grandchild = int(pid_file.read_text(encoding="utf-8").strip())
    for _ in range(100):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(grandchild, signal.SIGKILL)
        finally:
            pytest.fail("the timed-out job's grandchild outlived the timeout")


def test_execute_job_completed_within_timeout_is_not_marked_timed_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bounded termination path must not disturb a job that finishes in time."""

    run_root = _fake_run(tmp_path, ["a"])
    _install_timeout_job(
        run_root,
        timeout_sec=60,
        command=[sys.executable, "-c", "print('done')"],
    )
    _patch_execution_guards(run_root, monkeypatch)

    receipt = execute_job(run_root, "a", root=ROOT)

    assert receipt["timed_out"] is False
    assert receipt["returncode"] == 0
    assert "done" in receipt["stdout_tail"]
    # No stage-result is written, so a zero exit still fails closed.
    assert receipt["status"] == "failed"
    assert receipt["error"] == "stage-result.json is missing"


def test_rendered_slurm_array_binds_and_isolates_apptainer_runtime(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    run_root = workspace / "runs/run-01"
    runtime_image = tmp_path / "runtime/waybill-formal.sif"
    shared_data_root = tmp_path / "shared-data"
    prepared_root = shared_data_root / "prepared"
    corpus_root = shared_data_root / "corpus"
    ptau = shared_data_root / "ptau/powers.ptau"
    workspace.mkdir()
    runtime_image.parent.mkdir()
    runtime_image.write_bytes(b"fixture-sif")
    prepared_root.mkdir(parents=True)
    corpus_root.mkdir()
    ptau.parent.mkdir()
    ptau.touch()
    with ptau.open("r+b") as handle:
        handle.truncate(FORMAL_PTAU_BYTES)
    bindings = {
        "code_manifest_sha256": "c" * 64,
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "protocol_sha256": "d" * 64,
    }
    write_json(
        run_root / "container_manifest.json",
        {
            "schema": "waybill-container-manifest/v1",
            "bindings": bindings,
            "images": {
                "formal-runner": {
                    "bindings": bindings,
                    "image_digest": "sha256:" + "e" * 64,
                    "platform": "linux/amd64",
                    "user": "10003:10003",
                }
            },
        },
    )
    write_json(
        run_root / "gate_receipts.json",
        [
            seal_gate_receipt(
                gate="RG6",
                status="passed",
                evidence={
                    "schema": "waybill.formal.target-host-preflight/v2",
                    "status": "passed",
                    "checks": {"all": True},
                    "container_runtime": {
                        "sha256": _sha(runtime_image),
                        "expected_sha256": _sha(runtime_image),
                    },
                    "ptau": {
                        "path": str(ptau.resolve()),
                        "exists": True,
                        "bytes": ptau.stat().st_size,
                        "blake2b": FORMAL_PTAU_BLAKE2B,
                    },
                    "container_digest": "sha256:" + "e" * 64,
                    "expected_container_digest": "sha256:" + "e" * 64,
                    "embedded_release_binding": _embedded_binding(bindings),
                },
            )
        ],
    )
    write_jsonl(
        run_root / "jobs/expected.jsonl",
        [
            {
                "job_id": "job-1",
                "stage": "S1",
                "kind": "test",
                "resource": {"cpus": 2, "memory_gib": 4},
                "timeout_sec": 3600,
                "command": ["python", "script/run_waybill_s1_formal_unit.py"],
            }
        ],
    )
    output = run_root / "slurm/s1.sbatch"
    render_slurm_array(
        run_root,
        output,
        container_image=runtime_image,
        prepared_root=prepared_root,
        corpus_root=corpus_root,
        ptau=ptau,
        workspace_root=workspace,
        shared_data_root=shared_data_root,
        stage="S1",
    )
    script = output.read_text(encoding="utf-8")
    execution = read_json(run_root / "execution-container.json")
    assert "exec apptainer exec" in script
    assert "--containall --cleanenv --no-home --no-mount hostfs" in script
    assert "--net --network none" in script
    assert "SOURCE_ROOT=" not in script
    assert ":/work:ro" not in script
    assert '--bind "$RUN_ROOT:$RUN_ROOT:rw"' in script
    assert '--bind "$SHARED_DATA_ROOT:$SHARED_DATA_ROOT:ro"' in script
    assert '--bind "$PREPARED_ROOT:$PREPARED_ROOT:ro"' not in script
    assert '--bind "$CORPUS_ROOT:$CORPUS_ROOT:ro"' not in script
    assert '--bind "$PTAU_PATH:$PTAU_PATH:ro"' not in script
    assert execution["shared_data_root"] == str(shared_data_root.resolve())
    assert execution["runtime_image_sha256"] == _sha(runtime_image)
    assert execution["release_image_digest"] == "sha256:" + "e" * 64


def test_initialize_run_binds_release_container_and_runtime_before_jobs(
    tmp_path: Path,
) -> None:
    protocol = read_json(PROTOCOL_PATH)
    workspace = tmp_path / "workspace"
    output_root = workspace / "runs"
    plan_dir = workspace / "plan"
    runtime_image = tmp_path / "runtime/formal.sif"
    prepared_root = tmp_path / "prepared"
    corpus_root = tmp_path / "corpus"
    ptau = tmp_path / "ptau/powers.ptau"
    workspace.mkdir()
    runtime_image.parent.mkdir()
    runtime_image.write_bytes(b"frozen-sif")
    prepared_root.mkdir()
    corpus_root.mkdir()
    ptau.parent.mkdir()
    ptau.touch()
    with ptau.open("r+b") as handle:
        handle.truncate(FORMAL_PTAU_BYTES)
    dataset_rows = []
    for dataset in ("tdrive", "geolife", "porto", "rome"):
        directory = prepared_root / dataset
        directory.mkdir()
        periods = directory / "periods.jsonl"
        tariff = directory / "tariff.json"
        periods.write_text("{}\n", encoding="utf-8")
        tariff.write_text("{}\n", encoding="utf-8")
        dataset_rows.append(
            {
                "dataset": dataset,
                "periods_path": f"{dataset}/periods.jsonl",
                "periods_sha256": _sha(periods),
                "period_count": 1,
                "tariff_path": f"{dataset}/tariff.json",
                "tariff_sha256": _sha(tariff),
            }
        )
    instance_rows = []
    for dataset in ("tdrive", "geolife", "porto", "rome"):
        for bucket in (100, 50, 25, 10):
            for radius in (50, 100, 200):
                relative = (
                    Path("instances") / dataset / f"period-{bucket}-{radius}.json"
                )
                path = corpus_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
                instance_rows.append(
                    {
                        "instance_id": f"{dataset}-period-{bucket}-{radius}",
                        "dataset": dataset,
                        "period_id": f"{dataset}-period",
                        "path": str(relative),
                        "sha256": _sha(path),
                        "bucket_m": bucket,
                        "radius_m": radius,
                    }
                )
    s4_rows = [
        {
            "dataset": dataset,
            "horizon": horizon,
            "periods_sha256": next(
                row["periods_sha256"] for row in dataset_rows if row["dataset"] == dataset
            ),
            "original_identity_count": 4,
            "sequence_eligible_identity_count": 4,
            "sequence_count": 8,
            "minimum_sequence_identities": 4,
            "eligible": True,
            "status": "eligible",
            "reason": None,
        }
        for dataset in ("tdrive", "geolife", "porto", "rome")
        for horizon in (1, 4, 12)
    ]
    s4_artifact = {
        "schema": "waybill.formal.s4-eligibility/v1",
        "split": "vehicle-or-user-disjoint",
        "temporal_gap_periods": 1,
        "minimum_sequence_identities": 4,
        "ineligible_stratum_policy": "exclude-before-run-and-report",
        "rows": s4_rows,
    }
    s4_artifact["matrix_sha256"] = canonical_sha256(s4_artifact)
    s4_path = corpus_root / "s4_eligibility.json"
    write_json(s4_path, s4_artifact)
    prepared_manifest = {
        "schema": "waybill.formal.prepared-manifest/v1",
        "prepared_root_label": "WAYBILL_PREPARED_ROOT",
        "corpus_root_label": "WAYBILL_CORPUS_ROOT",
        "datasets": dataset_rows,
        "canonical_period_count": 4,
        "canonical_instance_count": len(instance_rows),
        "canonical_instances": instance_rows,
        "s4_eligibility": {
            "path": s4_path.name,
            "sha256": _sha(s4_path),
            "matrix_sha256": s4_artifact["matrix_sha256"],
            "rows": s4_rows,
        },
    }
    prepared_manifest["manifest_sha256"] = canonical_sha256(prepared_manifest)
    write_plan(protocol, plan_dir, prepared_manifest)
    code_manifest = {
        "schema": "waybill-code-manifest/v2",
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "file_count": 0,
        "files": [],
    }
    bindings = {
        "code_manifest_sha256": canonical_sha256(code_manifest),
        "git_commit": "a" * 40,
        "git_tree": "b" * 40,
        "protocol_sha256": canonical_sha256(protocol),
    }
    image_digest = "sha256:" + "e" * 64
    container_manifest = {
        "schema": "waybill-container-manifest/v1",
        "bindings": bindings,
        "images": {
            "formal-runner": {
                "bindings": bindings,
                "image_digest": image_digest,
                "platform": "linux/amd64",
                "user": "10003:10003",
            }
        },
    }
    runtime_sha = _sha(runtime_image)
    gate_receipts = [
        seal_gate_receipt(
            gate=f"RG{index}",
            status="passed",
            evidence=(
                {
                    "schema": "waybill.formal.target-host-preflight/v2",
                    "status": "passed",
                    "checks": {"all": True},
                    "container_runtime": {
                        "sha256": runtime_sha,
                        "expected_sha256": runtime_sha,
                    },
                    "ptau": {
                        "path": str(ptau.resolve()),
                        "exists": True,
                        "bytes": ptau.stat().st_size,
                        "blake2b": FORMAL_PTAU_BLAKE2B,
                    },
                    "container_digest": image_digest,
                    "expected_container_digest": image_digest,
                    "embedded_release_binding": _embedded_binding(bindings),
                }
                if index == 6
                else {"ok": True}
            ),
        )
        for index in range(9)
    ]
    run_root = initialize_run(
        protocol=protocol,
        plan_dir=plan_dir,
        output_root=output_root,
        run_id="run-01",
        manifests={
            "code_manifest": code_manifest,
            "data_manifest": {"schema": "test-data"},
            "environment": {"schema": "test-environment"},
            "container_manifest": container_manifest,
            "prepared_manifest": prepared_manifest,
        },
        gate_receipts=gate_receipts,
        container_runtime_image=runtime_image,
        prepared_root=prepared_root,
        corpus_root=corpus_root,
        ptau=ptau,
        workspace_root=workspace,
    )
    execution = read_json(run_root / "execution-container.json")
    run = read_json(run_root / "run.json")
    assert execution["runtime_image_sha256"] == runtime_sha
    assert execution["release_image_digest"] == image_digest
    assert run["execution_container_sha256"] == canonical_sha256(execution)
    assert validate_run_seal(run_root)["sealed_inputs_sha256"] == canonical_sha256(
        run["sealed_inputs"]
    )


def test_run_seal_detects_expected_job_ledger_drift(tmp_path: Path) -> None:
    run_root = _fake_run(tmp_path, ["a"])
    with (run_root / "jobs/expected.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{}\n")
    with pytest.raises(FormalError, match="sealed input hash mismatch"):
        validate_run_seal(run_root)


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
    assert aggregate["failure_summary"]["expected_job_denominator"] == 2
    assert aggregate["failure_summary"]["failed_or_unresolved_jobs"] == 2
    assert read_json(run_root / "status.json")["status"] == "failed"


def test_attempts_reject_self_declared_pass_and_first_valid_success_wins(tmp_path: Path) -> None:
    run_root = _fake_run(tmp_path, ["a"])
    attempt1, dir1 = next_attempt(run_root, "a")
    write_json(
        dir1 / "receipt.json",
        {"schema": "test", "job_id": "a", "attempt": attempt1, "status": "failed"},
        exclusive=True,
    )
    assert resume_job_ids(run_root) == ["a"]

    attempt2, dir2 = next_attempt(run_root, "a")
    _write_valid_passed_attempt(
        run_root=run_root,
        job_id="a",
        attempt=attempt2,
        attempt_dir=dir2,
    )
    with pytest.raises(FormalError, match="exhausted"):
        next_attempt(run_root, "a")

    aggregate = merge_run(run_root)
    assert aggregate["status"] == "passed"
    assert aggregate["units"][0]["selected_attempt"] == 2
    assert resume_job_ids(run_root) == []
    assert aggregate["failure_summary"]["failure_attempts_by_class"] == {
        "invalid-receipt": 1
    }
    assert aggregate["failure_summary"]["failure_receipts"][0]["attempt"] is None
    assert aggregate["scientific_summary"]["selected_job_count"] == 1
    assert aggregate["scientific_summary"]["by_stage_kind"] == {"S1/test": 1}
    assert aggregate["scientific_summary"]["rows"][0]["attempt_receipt_sha256"]
    assert (run_root / "scientific-aggregate.json").is_file()
    assert (run_root / "failure-summary.json").is_file()


def test_failed_stage_result_is_receipt_bound_and_resource_classified(tmp_path: Path) -> None:
    run_root = _fake_run(tmp_path, ["a"])
    attempt, attempt_dir = next_attempt(run_root, "a")
    _write_valid_resource_rejected_attempt(
        run_root=run_root,
        job_id="a",
        attempt=attempt,
        attempt_dir=attempt_dir,
    )

    aggregate = merge_run(run_root)

    assert aggregate["status"] == "failed"
    assert aggregate["failure_summary"]["failure_attempts_by_class"] == {
        "resource-rejected": 1
    }
    failure = aggregate["failure_summary"]["failure_receipts"][0]
    assert failure["stage_outcome_class"] == "resource-rejected"
    assert failure["stage_result_sha256"] == read_json(
        attempt_dir / "stage-result.json"
    )["result_sha256"]


def test_strict_merge_rejects_tampered_stage_artifact(tmp_path: Path) -> None:
    run_root = _fake_run(tmp_path, ["a"])
    attempt, attempt_dir = next_attempt(run_root, "a")
    _write_valid_passed_attempt(
        run_root=run_root,
        job_id="a",
        attempt=attempt,
        attempt_dir=attempt_dir,
    )
    (attempt_dir / "output.txt").write_text("tampered\n", encoding="utf-8")

    aggregate = merge_run(run_root)

    assert aggregate["status"] == "failed"
    assert aggregate["units"][0]["attempts"][0]["status"] == "invalid"
    assert "artifact" in aggregate["units"][0]["attempts"][0]["validation_error"]


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
