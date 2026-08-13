#!/usr/bin/env python3
"""Execute one S2 compile/setup/prove or concurrency formal unit."""

from __future__ import annotations

import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.resource_probe import collect_host_evidence  # noqa: E402
from common.settlement_v6 import PUBLIC_SIGNAL_ORDER_V6  # noqa: E402
from script import run_waybill_m2_circuit_matrix as m2  # noqa: E402
from waybill_formal.core import FormalError, read_json, read_jsonl  # noqa: E402
from waybill_formal.stage import finish_stage, load_job_environment  # noqa: E402


def _ptau() -> Path:
    path = Path(os.environ.get("WAYBILL_PTAU", ""))
    if not path.is_file():
        raise FormalError("S2 requires WAYBILL_PTAU pointing to the verified 4.83 GB PTAU")
    receipt = m2.ensure_ptau(path, allow_download=False, timeout_sec=1)
    if receipt["status"] != "verified":
        raise FormalError(f"PTAU verification failed: {receipt.get('error')}")
    return path


def _main_job(job: dict[str, Any], attempt_dir: Path) -> dict[str, Any]:
    parameters = job["parameters"]
    depth = int(parameters["depth"])
    fixes = int(parameters["fixes"])
    measured_trials = int(parameters["measured_trials"])
    output_dir = attempt_dir / "m2"
    output_dir.mkdir()
    ptau = _ptau()
    m2.environment_manifest(output_dir, ptau=ptau, measured_trials=measured_trials)
    compile_receipt = m2.compile_one(output_dir, depth, fixes, timeout_sec=3600)
    if compile_receipt.get("status") != "compiled":
        return {"status": "failed", "compile": compile_receipt}
    setup_receipt = m2.setup_one(
        output_dir,
        depth,
        fixes,
        ptau=ptau,
        timeout_sec=7200,
        formal_all_depths=True,
    )
    if setup_receipt.get("status") != "ready":
        return {"status": "failed", "compile": compile_receipt, "setup": setup_receipt}
    proof_receipt = m2.prove_one(
        output_dir,
        depth,
        fixes,
        timeout_sec=7200,
        measured_trials=measured_trials,
    )
    return {
        "status": "passed" if proof_receipt.get("status") == "verified" else "failed",
        "config_id": m2.wrapper_name(depth, fixes),
        "compile_receipt": str(
            output_dir / "receipts/compile" / f"{m2.wrapper_name(depth, fixes)}.json"
        ),
        "setup_receipt": str(
            output_dir / "receipts/setup" / f"{m2.wrapper_name(depth, fixes)}.json"
        ),
        "proof_receipt": str(
            output_dir / "receipts/proof" / f"{m2.wrapper_name(depth, fixes)}.json"
        ),
        "proof_status": proof_receipt.get("status"),
    }


def _find_main_attempt(run_root: Path, fixes: int) -> Path:
    jobs = read_jsonl(run_root / "jobs/expected.jsonl")
    matches = [
        row
        for row in jobs
        if row.get("stage") == "S2"
        and row.get("kind") == "main"
        and int(row["parameters"]["depth"]) == 14
        and int(row["parameters"]["fixes"]) == fixes
    ]
    if len(matches) != 1:
        raise FormalError(f"cannot identify the depth-14 n={fixes} main job")
    job_id = str(matches[0]["job_id"])
    attempt_root = run_root / "jobs/attempts" / job_id
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
    raise FormalError(f"S2 concurrency requires a passed depth-14 n={fixes} main attempt")


def _copy_artifacts(source_output: Path, target_output: Path, fixes: int) -> tuple[Path, dict[str, Any]]:
    """Copy immutable S2 inputs into the writable attempt tree.

    Formal attempt manifests reject symbolic links so that every hashed byte is
    physically contained in the attempt.  A regular copy also avoids hard-link
    aliasing that could let a later job mutate an earlier passed attempt.
    """

    name = m2.wrapper_name(14, fixes)
    source_paths = m2.config_paths(source_output, 14, fixes)
    target_paths = m2.config_paths(target_output, 14, fixes)
    target_paths["directory"].mkdir(parents=True, exist_ok=True)
    for key in ("wasm", "zkey", "vkey"):
        source = source_paths[key]
        target = target_paths[key]
        if not source.is_file():
            raise FormalError(f"missing main S2 artifact: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    source_input = source_output / "inputs" / f"{name}.json"
    source_proof_receipt = source_output / "receipts/proof" / f"{name}.json"
    if not source_input.is_file() or not source_proof_receipt.is_file():
        raise FormalError("main S2 input or proof receipt missing")
    target_input = target_output / "inputs" / f"{name}.json"
    target_input.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_input, target_input)
    return target_input, read_json(source_proof_receipt)


def _concurrency_job(
    job: dict[str, Any],
    attempt_dir: Path,
    run_root: Path,
) -> dict[str, Any]:
    parameters = job["parameters"]
    fixes = int(parameters["fixes"])
    concurrency = int(parameters["concurrency"])
    batch = int(parameters["batch"])
    host = collect_host_evidence(attempt_dir)
    memory_bytes = int(host.get("physical_memory_bytes") or 0)
    required_bytes = concurrency * 8 * 1024**3
    if memory_bytes and memory_bytes < required_bytes:
        return {
            "status": "failed",
            "outcome_class": "resource-rejected",
            "reason": f"{memory_bytes} bytes available is below {required_bytes} bytes required",
            "fixes": fixes,
            "concurrency": concurrency,
            "batch": batch,
            "host": host,
        }
    main_attempt = _find_main_attempt(run_root, fixes)
    source_output = main_attempt / "m2"
    output_dir = attempt_dir / "m2-concurrency"
    output_dir.mkdir()
    input_path, proof_receipt = _copy_artifacts(source_output, output_dir, fixes)
    circuit_input = read_json(input_path)
    binding = proof_receipt["city_tariff_binding"]
    expected_public = [circuit_input[name] for name in PUBLIC_SIGNAL_ORDER_V6]
    started = time.perf_counter()
    trials: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                m2.run_trial,
                output_dir=output_dir,
                depth=14,
                fixes=fixes,
                trial_label=f"c{concurrency}-b{batch}-worker{worker + 1}",
                circuit_input_path=input_path,
                expected_public=expected_public,
                expected_tariff_root=str(binding["tariff_root"]),
                expected_policy_commitment=str(binding["policy_profile_commitment"]),
                timeout_sec=7200,
                keep_proof=True,
            )
            for worker in range(concurrency)
        ]
        for future in as_completed(futures):
            trials.append(future.result())
    elapsed_sec = time.perf_counter() - started
    verified = [trial for trial in trials if trial.get("status") == "verified"]
    return {
        "status": "passed" if len(verified) == concurrency else "failed",
        "fixes": fixes,
        "concurrency": concurrency,
        "batch": batch,
        "elapsed_sec": elapsed_sec,
        "verified": len(verified),
        "failed": len(trials) - len(verified),
        "throughput_proofs_per_sec": len(verified) / elapsed_sec if elapsed_sec else None,
        "prove": m2.stage_summary(trials, "prove"),
        "verify": m2.stage_summary(trials, "verify"),
        "trials": trials,
        "host": host,
    }


def main() -> int:
    job, attempt_dir, run_root = load_job_environment()
    if job.get("stage") != "S2":
        raise FormalError("S2 runner received a non-S2 job")
    if job["kind"] == "main":
        payload = _main_job(job, attempt_dir)
    elif job["kind"] == "concurrency":
        payload = _concurrency_job(job, attempt_dir, run_root)
    else:
        raise FormalError(f"unsupported S2 job kind: {job['kind']}")
    finish_stage(job=job, attempt_dir=attempt_dir, payload=payload)
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
