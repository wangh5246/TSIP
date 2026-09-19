"""Implementation of the WayBill formal command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from waybill_formal.core import (  # noqa: E402
    FormalError,
    build_code_manifest,
    build_data_manifest,
    execute_job,
    host_preflight,
    initialize_run,
    merge_run,
    read_json,
    read_jsonl,
    render_slurm_array,
    resume_job_ids,
    validate_data_manifest,
    validate_formal_entrypoints,
    validate_protocol,
    validate_tariff_registry,
    write_json,
    write_plan,
)


DEFAULT_PROTOCOL = ROOT / "configs/waybill_formal/protocol-v1.json"
DEFAULT_DATA_REGISTRY = ROOT / "configs/waybill_formal/data-sources-v1.json"
DEFAULT_TARIFF_REGISTRY = ROOT / "configs/waybill_formal/tariff-registry-v1.json"
DEFAULT_CODE_MANIFEST_PATHS = (
    Path(".dockerignore"),
    Path(".env.example"),
    Path(".gitattributes"),
    Path(".gitignore"),
    Path("WayBill"),
    Path("common"),
    Path("configs/waybill_formal"),
    Path("configs/settlement_policy_profiles"),
    Path("containers"),
    Path("circuits"),
    Path("deploy"),
    Path("experiments-heatmap/circuits"),
    Path("experiments/waybill_m1"),
    Path("experiments/waybill_m2"),
    Path("TSIP_heatmap_version/runtime/experiments-heatmap/make_v4_fair_heatmap.py"),
    Path("memory/Research/waybill-ruc"),
    Path("requirements"),
    Path("script"),
    Path("services/charger"),
    Path("services/receiver_signer"),
    Path("services/__init__.py"),
    Path("tests"),
    Path("waybill_formal"),
    Path("zk/settlement_period_v6_k6/verification_key.json"),
    Path("DATA_NOTICE.md"),
    Path("Makefile"),
    Path("README_ARTIFACT.md"),
    Path("README_SERVER_DEPLOY.md"),
    Path("package.json"),
    Path("package-lock.json"),
    Path("pyproject.toml"),
)


def _json_arg(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-config")
    validate.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    validate.add_argument("--tariff-registry", type=Path, default=DEFAULT_TARIFF_REGISTRY)

    data = sub.add_parser("build-data-manifest")
    data.add_argument("--registry", type=Path, default=DEFAULT_DATA_REGISTRY)
    data.add_argument("--data-root", type=Path, required=True)
    data.add_argument("--output-dir", type=Path, required=True)

    data_validate = sub.add_parser("validate-data-manifest")
    data_validate.add_argument("--registry", type=Path, default=DEFAULT_DATA_REGISTRY)
    data_validate.add_argument("--manifest", type=Path, required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    plan.add_argument("--prepared-manifest", type=Path)
    plan.add_argument("--output-dir", type=Path, required=True)

    init_run = sub.add_parser("init-run")
    init_run.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    init_run.add_argument("--plan-dir", type=Path, required=True)
    init_run.add_argument("--output-root", type=Path, required=True)
    init_run.add_argument("--run-id", required=True)
    init_run.add_argument("--code-manifest", type=Path, required=True)
    init_run.add_argument("--data-manifest", type=Path, required=True)
    init_run.add_argument("--environment-manifest", type=Path, required=True)
    init_run.add_argument("--container-manifest", type=Path, required=True)
    init_run.add_argument("--prepared-manifest", type=Path, required=True)
    init_run.add_argument("--gate-receipts", type=Path, required=True)
    init_run.add_argument("--container-runtime-image", type=Path, required=True)
    init_run.add_argument("--prepared-root", type=Path, required=True)
    init_run.add_argument("--corpus-root", type=Path, required=True)
    init_run.add_argument("--ptau", type=Path, required=True)
    init_run.add_argument("--workspace-root", type=Path, required=True)
    init_run.add_argument(
        "--shared-data-root",
        type=Path,
        help="single read-only root containing prepared, corpus, and PTAU inputs",
    )

    code = sub.add_parser("code-manifest")
    code.add_argument("--output", type=Path, required=True)
    code.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=list(DEFAULT_CODE_MANIFEST_PATHS),
    )

    host = sub.add_parser("host-preflight")
    host.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    host.add_argument("--workspace", type=Path, required=True)
    host.add_argument("--ptau", type=Path)
    host.add_argument("--container-digest")
    host.add_argument("--expected-container-digest")
    host.add_argument("--container-runtime-image", type=Path, required=True)
    host.add_argument("--expected-container-runtime-sha256", required=True)
    host.add_argument("--required-workspace-gib", type=int, default=500)
    host.add_argument("--output", type=Path, required=True)

    run_job = sub.add_parser("run-job")
    run_job.add_argument("--run-root", type=Path, required=True)
    run_job.add_argument("--job-id", required=True)

    merge = sub.add_parser("merge")
    merge.add_argument("--run-root", type=Path, required=True)

    resume = sub.add_parser("resume")
    resume.add_argument("--run-root", type=Path, required=True)

    local = sub.add_parser("run-local")
    local.add_argument("--run-root", type=Path, required=True)
    local.add_argument("--stage", choices=["S1", "S2", "S3", "S4", "S5"])
    local.add_argument("--kind")
    local.add_argument(
        "--results",
        type=Path,
        help="append one JSON line per job outcome here (must live outside the run root)",
    )

    job_at = sub.add_parser("job-id-at")
    job_at.add_argument("--run-root", type=Path, required=True)
    job_at.add_argument("--index", type=int, required=True)

    slurm = sub.add_parser("render-slurm")
    slurm.add_argument("--run-root", type=Path, required=True)
    slurm.add_argument("--output", type=Path, required=True)
    slurm.add_argument("--container-image", type=Path, required=True)
    slurm.add_argument("--prepared-root", type=Path, required=True)
    slurm.add_argument("--corpus-root", type=Path, required=True)
    slurm.add_argument("--ptau", type=Path, required=True)
    slurm.add_argument("--workspace-root", type=Path, required=True)
    slurm.add_argument(
        "--shared-data-root",
        type=Path,
        help="single read-only root containing prepared, corpus, and PTAU inputs",
    )
    slurm.add_argument("--stage", choices=["S1", "S2", "S3", "S4", "S5"])
    slurm.add_argument("--kind")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "validate-config":
        protocol_receipt = validate_protocol(read_json(args.protocol))
        tariff_receipt = validate_tariff_registry(read_json(args.tariff_registry), ROOT)
        entrypoint_receipt = validate_formal_entrypoints(ROOT)
        print(
            json.dumps(
                {
                    "protocol": protocol_receipt,
                    "tariff": tariff_receipt,
                    "entrypoints": entrypoint_receipt,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "build-data-manifest":
        manifest = build_data_manifest(
            read_json(args.registry),
            args.data_root.resolve(),
            args.output_dir.resolve(),
        )
        print(json.dumps(manifest, indent=2))
        return 0
    if args.command == "validate-data-manifest":
        manifest = read_json(args.manifest)
        receipt = validate_data_manifest(
            manifest,
            read_json(args.registry),
            args.manifest.resolve().parent,
        )
        print(json.dumps(receipt, indent=2))
        return 0
    if args.command == "plan":
        prepared = read_json(args.prepared_manifest) if args.prepared_manifest else None
        summary = write_plan(read_json(args.protocol), args.output_dir.resolve(), prepared)
        print(json.dumps(summary, indent=2))
        return 0 if summary["materialized"] else 3
    if args.command == "init-run":
        receipts = read_json(args.gate_receipts)
        if not isinstance(receipts, list):
            raise FormalError("--gate-receipts must contain a JSON array")
        run_root = initialize_run(
            protocol=read_json(args.protocol),
            plan_dir=args.plan_dir.resolve(),
            output_root=args.output_root.resolve(),
            run_id=args.run_id,
            manifests={
                "code_manifest": read_json(args.code_manifest),
                "data_manifest": read_json(args.data_manifest),
                "environment": read_json(args.environment_manifest),
                "container_manifest": read_json(args.container_manifest),
                "prepared_manifest": read_json(args.prepared_manifest),
            },
            gate_receipts=receipts,
            container_runtime_image=args.container_runtime_image,
            prepared_root=args.prepared_root,
            corpus_root=args.corpus_root,
            ptau=args.ptau,
            workspace_root=args.workspace_root,
            shared_data_root=args.shared_data_root,
        )
        print(run_root)
        return 0
    if args.command == "code-manifest":
        manifest = build_code_manifest(ROOT, args.paths)
        write_json(args.output.resolve(), manifest)
        print(json.dumps(manifest, indent=2))
        return 0 if not manifest["git_dirty"] else 4
    if args.command == "host-preflight":
        receipt = host_preflight(
            root=ROOT,
            protocol=read_json(args.protocol),
            workspace=args.workspace.resolve(),
            ptau=args.ptau.resolve() if args.ptau else None,
            container_digest=args.container_digest,
            expected_container_digest=args.expected_container_digest,
            container_runtime_image=args.container_runtime_image,
            expected_container_runtime_sha256=args.expected_container_runtime_sha256,
            required_workspace_gib=args.required_workspace_gib,
        )
        write_json(args.output.resolve(), receipt)
        print(json.dumps(receipt, indent=2))
        return 0 if receipt["status"] == "passed" else 5
    if args.command == "run-job":
        receipt = execute_job(args.run_root.resolve(), args.job_id, root=ROOT)
        print(json.dumps(receipt, indent=2))
        return 0 if receipt["status"] == "passed" else 1
    if args.command == "merge":
        aggregate = merge_run(args.run_root.resolve())
        print(json.dumps(aggregate, indent=2))
        return 0 if aggregate["status"] == "passed" else 1
    if args.command == "resume":
        for job_id in resume_job_ids(args.run_root.resolve()):
            print(job_id)
        return 0
    if args.command == "run-local":
        # Successor driver semantics (A4): per-unit failure isolation.  The
        # V14 recovery driver let one exception escape run_group and abort
        # every remaining unit, and refused to resume an existing ops root.
        # Here a failing unit is recorded and the driver moves on; resume
        # semantics come from resume_job_ids, which re-selects only units
        # without a strictly validated passed receipt.
        run_root = args.run_root.resolve()
        jobs = {
            row["job_id"]: row
            for row in read_jsonl(run_root / "jobs/expected.jsonl")
        }
        selected = []
        for job_id in resume_job_ids(run_root):
            job = jobs[job_id]
            if args.stage and job.get("stage") != args.stage:
                continue
            if args.kind and job.get("kind") != args.kind:
                continue
            selected.append(job_id)
        results_path = args.results.resolve() if args.results else None
        if results_path is not None:
            if results_path == run_root or run_root in results_path.parents:
                raise FormalError(
                    "driver results must live outside the immutable run root"
                )
            results_path.parent.mkdir(parents=True, exist_ok=True)
        passed = 0
        failed = 0
        driver_errors = 0
        for index, job_id in enumerate(selected, start=1):
            try:
                record = execute_job(run_root, job_id, root=ROOT)
                passed += int(record["status"] == "passed")
                failed += int(record["status"] != "passed")
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                driver_errors += 1
                failed += 1
                record = {
                    "job_id": job_id,
                    "status": "driver-error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            record["driver_sequence"] = index
            print(json.dumps(record, sort_keys=True), flush=True)
            if results_path is not None:
                with open(results_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True) + "\n")
        summary = {
            "schema": "waybill.formal.driver-run-summary/v1",
            "run_root": str(run_root),
            "selected": len(selected),
            "passed": passed,
            "failed": failed,
            "driver_errors": driver_errors,
            "stage": args.stage,
            "kind": args.kind,
        }
        print(json.dumps({"summary": summary}, sort_keys=True), flush=True)
        if results_path is not None:
            with open(results_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"summary": summary}, sort_keys=True) + "\n")
        return 1 if failed else 0
    if args.command == "job-id-at":
        job_rows = read_jsonl(args.run_root.resolve() / "jobs/expected.jsonl")
        if args.index < 0 or args.index >= len(job_rows):
            raise FormalError(f"job index outside [0, {len(job_rows) - 1}]")
        print(job_rows[args.index]["job_id"])
        return 0
    if args.command == "render-slurm":
        render_slurm_array(
            args.run_root.resolve(),
            args.output.resolve(),
            container_image=args.container_image,
            prepared_root=args.prepared_root,
            corpus_root=args.corpus_root,
            ptau=args.ptau,
            workspace_root=args.workspace_root,
            shared_data_root=args.shared_data_root,
            stage=args.stage,
            kind=args.kind,
        )
        print(args.output.resolve())
        return 0
    raise AssertionError(args.command)
