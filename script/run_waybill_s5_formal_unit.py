#!/usr/bin/env python3
"""Benchmark the fixed WayBill verifier corpus and V6 charger workloads."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.eval_harness import HarnessParams  # noqa: E402
from common.policy_profile import PolicyProfile  # noqa: E402
from common.settlement import (  # noqa: E402
    SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
    ReceiverFix,
    receiver_attestation_sha256,
    sign_receiver_fix,
    sign_receiver_root_attestation,
)
from common.settlement_v6 import PUBLIC_SIGNAL_ORDER_V6  # noqa: E402
from script import prove_settlement_period_v6 as v6_prover  # noqa: E402
from script import run_waybill_m2_circuit_matrix as m2  # noqa: E402
from waybill_formal.core import (  # noqa: E402
    FormalError,
    read_json,
    read_jsonl,
    sha256_file,
    write_json,
    write_jsonl,
)
from waybill_formal.stage import finish_stage, load_job_environment  # noqa: E402


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise FormalError("percentile requires samples")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
    return ordered[index]


def _passed_attempt(
    run_root: Path,
    *,
    stage: str,
    kind: str,
    fixes: int,
    depth: int | None = None,
) -> Path:
    jobs = read_jsonl(run_root / "jobs/expected.jsonl")
    matches = [
        row
        for row in jobs
        if row.get("stage") == stage
        and row.get("kind") == kind
        and int(row["parameters"]["fixes"]) == fixes
        and (depth is None or int(row["parameters"].get("depth", 0)) == depth)
    ]
    if len(matches) != 1:
        raise FormalError(
            f"cannot identify {stage}/{kind} fixes={fixes}"
            + ("" if depth is None else f" depth={depth}")
        )
    attempt_root = run_root / "jobs/attempts" / str(matches[0]["job_id"])
    for attempt in sorted(attempt_root.glob("attempt-*")):
        receipt_path = attempt / "receipt.json"
        stage_path = attempt / "stage-result.json"
        if (
            receipt_path.is_file()
            and stage_path.is_file()
            and read_json(receipt_path).get("status") == "passed"
            and read_json(stage_path).get("status") == "passed"
        ):
            return attempt
    raise FormalError(f"{stage}/{kind} fixes={fixes} has no passed attempt")


def _corpus(
    run_root: Path,
    fixes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    manifest_path = run_root / "proof_corpus_manifest.json"
    if not manifest_path.is_file():
        override = os.environ.get("WAYBILL_PROOF_CORPUS_MANIFEST")
        manifest_path = Path(override) if override else manifest_path
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        if manifest.get("schema") != "waybill.formal.proof-corpus/v1":
            raise FormalError("unsupported S5 proof corpus schema")
        matches = [row for row in manifest["corpora"] if int(row["fixes"]) == fixes]
        if len(matches) != 1:
            raise FormalError(f"proof corpus must contain exactly one fixes={fixes} record")
        record = {**manifest, **dict(matches[0])}
        root = Path(os.environ.get("WAYBILL_PROOF_CORPUS_ROOT", manifest_path.parent))
    else:
        corpus_attempt = _passed_attempt(
            run_root,
            stage="S5",
            kind="corpus",
            fixes=fixes,
        )
        record_path = corpus_attempt / "proof-corpus-record.json"
        record = read_json(record_path)
        if record.get("schema") != "waybill.formal.proof-corpus-record/v1":
            raise FormalError("unsupported S5 proof corpus record schema")
        root = corpus_attempt
    path = Path(str(record["bundles_jsonl"]))
    path = path if path.is_absolute() else root / path
    if not path.is_file() or sha256_file(path) != record["sha256"]:
        raise FormalError(f"S5 proof corpus hash mismatch: {path}")
    bundles = read_jsonl(path)
    if len(bundles) != 100:
        raise FormalError(f"S5 fixes={fixes} corpus must contain exactly 100 bundles")
    hashes = [hashlib.sha256(json.dumps(row["proof"], sort_keys=True).encode()).hexdigest() for row in bundles]
    if len(set(hashes)) != 100:
        raise FormalError("S5 proof corpus proofs are not all distinct")
    return record, bundles, root


def _copy_main_artifacts(source_output: Path, target_output: Path, fixes: int) -> dict[str, Path]:
    """Copy proof artifacts into the corpus attempt without link aliasing."""

    source_paths = m2.config_paths(source_output, 14, fixes)
    target_paths = m2.config_paths(target_output, 14, fixes)
    target_paths["directory"].mkdir(parents=True, exist_ok=True)
    for key in ("wasm", "zkey", "vkey"):
        source = source_paths[key]
        target = target_paths[key]
        if not source.is_file():
            raise FormalError(f"S5 corpus requires S2 artifact: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return target_paths


def _build_corpus_input(
    *,
    fixes_count: int,
    corpus_index: int,
    profile: PolicyProfile,
    log_epoch: int = 1,
    previous_attestation_sha256: str = SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tariff, _manifest = m2.load_city_tariff(14)
    period_id = f"2026-05-waybill-s5-n{fixes_count}-bundle-{corpus_index:03d}"
    start_time = 1_777_593_600 + corpus_index * 14_400
    odometer = 50_000 + corpus_index * 1_000_000
    fixes: list[ReceiverFix] = []
    position_valid = [index % 11 != 5 for index in range(fixes_count - 1)]
    previous_xy: tuple[int, int] | None = None
    for seq in range(fixes_count):
        x, y = m2.snake_cell(seq)
        if previous_xy is not None:
            odometer += m2.CELL_SIZE_M
        previous_xy = (x, y)
        raw = ReceiverFix(
            device_id="waybill-m2-benchmark-device",
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=start_time + seq * m2.CADENCE_SEC,
            cell_x=x,
            cell_y=y,
            osnma_status=(
                "authenticated"
                if seq == fixes_count - 1 or position_valid[seq]
                else "unavailable"
            ),
            odometer_reading_m=odometer,
            nonce=f"waybill-s5-n{fixes_count}-bundle-{corpus_index:03d}-fix-{seq}",
        )
        fixes.append(sign_receiver_fix(raw, v6_prover._DEVICE_SEED))
    params = HarnessParams(
        cadence_sec=m2.CADENCE_SEC,
        max_dt_sec=m2.MAX_DT_SEC,
        tier_vmax_mps=m2.TIER_VMAX_MPS,
        cell_size_m=m2.CELL_SIZE_M,
    )
    old_n = v6_prover.N_FIXES
    old_depth = v6_prover.TREE_DEPTH
    old_cap_policy_sq = v6_prover.CAP_POLICY_SQ
    try:
        v6_prover.N_FIXES = fixes_count
        v6_prover.TREE_DEPTH = 14
        v6_prover.CAP_POLICY_SQ = m2.M2_CAP_POLICY_SQ
        circuit_input, submission = v6_prover.build_input_for_fixes(
            fixes,
            tariff,
            position_valid=position_valid,
            params=params,
            policy_profile=profile,
        )
    finally:
        v6_prover.N_FIXES = old_n
        v6_prover.TREE_DEPTH = old_depth
        v6_prover.CAP_POLICY_SQ = old_cap_policy_sq
    test_attestation = submission["receiver_root_attestation"]
    chained_attestation = sign_receiver_root_attestation(
        receiver_id=str(test_attestation["receiver_id"]),
        charger_domain=str(test_attestation["charger_domain"]),
        device_id=str(test_attestation["device_id"]),
        period_id=str(test_attestation["period_id"]),
        log_epoch=log_epoch,
        fix_count=int(test_attestation["fix_count"]),
        receiver_fix_root=str(test_attestation["receiver_fix_root"]),
        device_attestation_commitment=str(
            test_attestation["device_attestation_commitment"]
        ),
        log_sha256=str(test_attestation["log_sha256"]),
        private_key_bytes=v6_prover._DEVICE_SEED,
        previous_attestation_sha256=previous_attestation_sha256,
    )
    submission["receiver_root_attestation"] = chained_attestation
    submission["receiver_attestation_mode"] = "formal-sequential-test-chain"
    return circuit_input, submission


def _corpus_job(
    job: dict[str, Any],
    attempt_dir: Path,
    run_root: Path,
) -> dict[str, Any]:
    fixes = int(job["parameters"]["fixes"])
    required = int(job["parameters"]["valid_bundle_corpus"])
    concurrency = int(job["parameters"]["concurrency"])
    if required != 100:
        raise FormalError("S5 formal corpus must contain exactly 100 bundles")
    main_attempt = _passed_attempt(
        run_root,
        stage="S2",
        kind="main",
        fixes=fixes,
        depth=14,
    )
    source_output = main_attempt / "m2"
    source_name = m2.wrapper_name(14, fixes)
    source_profile_path = source_output / "policy_profiles" / f"{source_name}.json"
    profile = PolicyProfile.from_dict(read_json(source_profile_path))

    corpus_root = attempt_dir / "proof-corpus"
    output_dir = corpus_root / "m2"
    output_dir.mkdir(parents=True)
    target_paths = _copy_main_artifacts(source_output, output_dir, fixes)
    profile = replace(
        profile,
        verification_key_path=str(target_paths["vkey"].resolve()),
        tariff_artifact_path=str(m2.TARIFF_PATH.resolve()),
    )
    profile_dir = corpus_root / "policy_profiles"
    write_json(profile_dir / source_profile_path.name, profile.to_dict())

    inputs: list[tuple[int, Path, dict[str, Any], list[str]]] = []
    previous_attestation_sha256 = SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256
    for index in range(required):
        circuit_input, submission = _build_corpus_input(
            fixes_count=fixes,
            corpus_index=index,
            profile=profile,
            log_epoch=index + 1,
            previous_attestation_sha256=previous_attestation_sha256,
        )
        previous_attestation_sha256 = receiver_attestation_sha256(
            submission["receiver_root_attestation"]
        )
        input_path = output_dir / "inputs" / f"bundle-{index:03d}.json"
        write_json(input_path, circuit_input)
        inputs.append(
            (
                index,
                input_path,
                submission,
                [str(circuit_input[name]) for name in PUBLIC_SIGNAL_ORDER_V6],
            )
        )

    trials: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                m2.run_trial,
                output_dir=output_dir,
                depth=14,
                fixes=fixes,
                trial_label=f"bundle-{index:03d}",
                circuit_input_path=input_path,
                expected_public=expected_public,
                expected_tariff_root=str(profile.tariff_root),
                expected_policy_commitment=str(profile.commitment),
                timeout_sec=7200,
                keep_proof=True,
            ): index
            for index, input_path, _submission, expected_public in inputs
        }
        for future in as_completed(futures):
            trials[futures[future]] = future.result()

    bundles: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    submission_by_index = {index: submission for index, _path, submission, _public in inputs}
    trial_root = output_dir / "trials" / source_name
    for index in range(required):
        trial = trials[index]
        if trial.get("status") != "verified":
            failures.append({"index": index, "trial": trial})
            continue
        trial_dir = trial_root / f"bundle-{index:03d}"
        proof = read_json(trial_dir / "proof.json")
        public_signals = read_json(trial_dir / "public.json")
        submission = submission_by_index[index]
        proof_sha256 = sha256_file(trial_dir / "proof.json")
        bundles.append(
            {
                "bundle_id": f"n{fixes}-{index:03d}-{proof_sha256[:16]}",
                "fixes": fixes,
                "proof_sha256": proof_sha256,
                "proof": proof,
                "public_signals": public_signals,
                "endpoint_payload": {
                    "public_statement": submission["public_statement"],
                    "proof": proof,
                    "public_signals": public_signals,
                    "root_attestation": submission["receiver_root_attestation"],
                },
            }
        )
    if failures or len(bundles) != required:
        return {
            "status": "failed",
            "fixes": fixes,
            "required": required,
            "generated": len(bundles),
            "failures": failures,
        }
    proof_hashes = [row["proof_sha256"] for row in bundles]
    if len(set(proof_hashes)) != required:
        return {
            "status": "failed",
            "fixes": fixes,
            "reason": "S5 corpus proofs are not all distinct",
        }

    bundles_path = corpus_root / f"proof-bundles-n{fixes}.jsonl"
    write_jsonl(bundles_path, bundles)
    record = {
        "schema": "waybill.formal.proof-corpus-record/v1",
        "fixes": fixes,
        "bundle_count": required,
        "bundles_jsonl": str(bundles_path.relative_to(attempt_dir)),
        "sha256": sha256_file(bundles_path),
        "verification_key_path": str(target_paths["vkey"].resolve()),
        "verification_key_sha256": sha256_file(target_paths["vkey"]),
        "policy_profile_dir": str(profile_dir.relative_to(attempt_dir)),
        "policy_profile_sha256": profile.profile_sha256,
        "policy_profile_commitment": str(profile.commitment),
        "jurisdiction_id": profile.jurisdiction_id,
        "device_id": "waybill-m2-benchmark-device",
        "device_public_key_hex": v6_prover._DEVICE_PUBLIC_KEY_BYTES.hex(),
        "charger_endpoint": "/settlement/v6/period/proof-only",
        "source_s2_attempt": str(main_attempt),
    }
    write_json(attempt_dir / "proof-corpus-record.json", record)
    return {
        "status": "passed",
        "fixes": fixes,
        "bundles": required,
        "corpus_concurrency": concurrency,
        "record": "proof-corpus-record.json",
        "proof_corpus_sha256": record["sha256"],
    }


def _verify_once(bundle: dict[str, Any], vkey: Path) -> tuple[bool, float, str]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="waybill-s5-verify-") as directory:
        root = Path(directory)
        proof = root / "proof.json"
        public = root / "public.json"
        proof.write_text(json.dumps(bundle["proof"]), encoding="utf-8")
        public.write_text(json.dumps(bundle["public_signals"]), encoding="utf-8")
        proc = subprocess.run(
            ["snarkjs", "groth16", "verify", str(vkey), str(public), str(proof)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    return proc.returncode == 0 and "OK" in proc.stdout, elapsed_ms, proc.stdout[-4000:]


def _verifier_job(
    job: dict[str, Any],
    attempt_dir: Path,
    run_root: Path,
) -> dict[str, Any]:
    fixes = int(job["parameters"]["fixes"])
    calls = int(job["parameters"]["calls"])
    record, bundles, root = _corpus(run_root, fixes)
    vkey = Path(str(record["verification_key_path"]))
    vkey = vkey if vkey.is_absolute() else root / vkey
    if not vkey.is_file() or sha256_file(vkey) != record["verification_key_sha256"]:
        raise FormalError("S5 verification key missing or hash-mismatched")
    latencies: list[float] = []
    failures: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index in range(calls):
        bundle = bundles[index % len(bundles)]
        ok, elapsed_ms, output = _verify_once(bundle, vkey)
        latencies.append(elapsed_ms)
        if not ok:
            failures.append({"call": index, "bundle_id": bundle["bundle_id"], "output": output})
    elapsed_sec = time.perf_counter() - started
    result = {
        "status": "passed" if not failures else "failed",
        "fixes": fixes,
        "calls": calls,
        "failures": failures,
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "latency_ms_p99": _percentile(latencies, 0.99),
        "throughput_calls_per_sec": calls / elapsed_sec if elapsed_sec else None,
        "elapsed_sec": elapsed_sec,
    }
    return result


def _tampered(payload: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    signals = list(result["public_signals"])
    signals[0] = str(int(signals[0]) + 1)
    result["public_signals"] = signals
    return result


def _request_plan(
    workload: str,
    bundles: list[dict[str, Any]],
    seed: int,
) -> list[tuple[str, dict[str, Any]]]:
    total = 100
    if workload == "valid-100":
        counts = {"valid": 100, "tampered": 0, "replay": 0}
    elif workload == "valid-95-tampered-5":
        counts = {"valid": 95, "tampered": 5, "replay": 0}
    elif workload == "valid-90-tampered-5-replay-5":
        counts = {"valid": 90, "tampered": 5, "replay": 5}
    else:
        raise FormalError(f"unsupported S5 workload: {workload}")
    plan: list[tuple[str, dict[str, Any]]] = []
    for index in range(counts["valid"]):
        plan.append(("valid", copy.deepcopy(bundles[index]["endpoint_payload"])))
    for index in range(counts["tampered"]):
        plan.append(("tampered", _tampered(bundles[90 + index]["endpoint_payload"])))
    for index in range(counts["replay"]):
        plan.append(("replay", copy.deepcopy(bundles[95 + index]["endpoint_payload"])))
    if len(plan) != total:
        raise AssertionError(plan)
    return sorted(
        plan,
        key=lambda row: hashlib.sha256(
            (
                f"{seed}|{row[0]}|"
                f"{row[1].get('period_id') or row[1].get('public_statement', {}).get('period_id', '')}"
            ).encode()
        ).digest(),
    )


def _charger_job(
    job: dict[str, Any],
    attempt_dir: Path,
    run_root: Path,
) -> dict[str, Any]:
    fixes = int(job["parameters"]["fixes"])
    concurrency = int(job["parameters"]["concurrency"])
    workload = str(job["parameters"]["workload"])
    repetition = int(job["parameters"]["repetition"])
    record, bundles, root = _corpus(run_root, fixes)
    profile_dir = Path(str(record["policy_profile_dir"]))
    profile_dir = profile_dir if profile_dir.is_absolute() else root / profile_dir
    if not profile_dir.is_dir():
        raise FormalError("S5 policy profile directory missing")
    os.environ["SETTLEMENT_POLICY_PROFILE_DIR"] = str(profile_dir)
    os.environ["SETTLEMENT_REQUIRE_ZK_PROOF"] = "1"
    os.environ["WAYBILL_CHARGER_TEST_MODE"] = "1"
    os.environ["WAYBILL_CHARGER_DATABASE_URL"] = (
        f"sqlite+pysqlite:///{attempt_dir / 'charger.sqlite'}"
    )
    os.environ["WAYBILL_CHARGER_DOMAIN"] = "ruc-demo.charger-test"
    os.environ["WAYBILL_CHARGER_ADMIN_TOKEN"] = "waybill-test-admin-token"
    os.environ["WAYBILL_CHARGER_TOKEN_PEPPER"] = "waybill-test-token-pepper"
    from fastapi.testclient import TestClient
    from services.charger.app import app

    endpoint = str(record.get("charger_endpoint", "/settlement/v6/period/proof-only"))
    with TestClient(app) as client:
        reset = client.post("/settlement/reset")
        if reset.status_code != 200:
            raise FormalError(f"S5 charger reset failed: {reset.text}")
        registration = client.post(
            "/settlement/devices/register",
            json={
                "device_id": record["device_id"],
                "public_key_hex": record["device_public_key_hex"],
                "jurisdiction_id": record["jurisdiction_id"],
            },
        )
        if registration.status_code != 200:
            raise FormalError(f"S5 device registration failed: {registration.text}")
        for bundle in bundles:
            anchored = client.post(
                "/settlement/receiver-chain/anchor",
                json={
                    "root_attestation": bundle["endpoint_payload"]["root_attestation"]
                },
            )
            if anchored.status_code != 200:
                raise FormalError(
                    "S5 receiver-chain anchoring failed for "
                    f"{bundle['bundle_id']}: {anchored.text}"
                )
    plan = _request_plan(workload, bundles, seed=20260716 + repetition)
    latencies: list[float] = []
    outcomes: list[dict[str, Any]] = []

    def request(item: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        kind, payload = item
        started = time.perf_counter()
        with TestClient(app) as client:
            response = client.post(endpoint, json=payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        expected_accept = kind == "valid"
        accepted = 200 <= response.status_code < 300
        return {
            "kind": kind,
            "status_code": response.status_code,
            "accepted": accepted,
            "correct": accepted == expected_accept,
            "elapsed_ms": elapsed_ms,
            "response_tail": response.text[-1000:],
        }

    if workload == "valid-90-tampered-5-replay-5":
        for bundle in bundles[95:100]:
            with TestClient(app) as client:
                response = client.post(endpoint, json=bundle["endpoint_payload"])
            if not 200 <= response.status_code < 300:
                raise FormalError(
                    "S5 replay pre-seeding failed; corpus payload was not accepted "
                    f"(status={response.status_code})"
                )

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(request, item) for item in plan]
        for future in as_completed(futures):
            outcome = future.result()
            outcomes.append(outcome)
            latencies.append(float(outcome["elapsed_ms"]))
    elapsed_sec = time.perf_counter() - started
    result = {
        "status": "passed" if all(row["correct"] for row in outcomes) else "failed",
        "fixes": fixes,
        "concurrency": concurrency,
        "workload": workload,
        "benchmark_scope": "in-process FastAPI handler with SQLite test ledger",
        "production_server_or_postgresql_claim": False,
        "repetition": repetition,
        "requests": len(outcomes),
        "correct": sum(row["correct"] for row in outcomes),
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "latency_ms_p99": _percentile(latencies, 0.99),
        "throughput_requests_per_sec": len(outcomes) / elapsed_sec if elapsed_sec else None,
        "elapsed_sec": elapsed_sec,
        "outcomes": outcomes,
    }
    return result


def main() -> int:
    job, attempt_dir, run_root = load_job_environment()
    if job.get("stage") != "S5":
        raise FormalError("S5 runner received a non-S5 job")
    if job["kind"] == "corpus":
        payload = _corpus_job(job, attempt_dir, run_root)
    elif job["kind"] == "verifier":
        payload = _verifier_job(job, attempt_dir, run_root)
    elif job["kind"] == "handler":
        payload = _charger_job(job, attempt_dir, run_root)
    else:
        raise FormalError(f"unsupported S5 job kind: {job['kind']}")
    finish_stage(job=job, attempt_dir=attempt_dir, payload=payload)
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
