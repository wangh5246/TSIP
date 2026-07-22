import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "script" / "summarize_v4_n1000_scale.py"
SPEC = importlib.util.spec_from_file_location("summarize_v4_n1000_scale", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def round_row(logical_round: int) -> dict[str, object]:
    bootstrap = logical_round == 0
    evaluation = logical_round >= 6
    proofs = 0 if bootstrap else 1000
    return {
        "attack_type": "none",
        "cells_final": 10000 if evaluation else None,
        "cells_kept_post": 100 if evaluation else None,
        "client_proof_attempts": proofs,
        "client_proof_generated": proofs,
        "dp_ok": True if evaluation else None,
        "false_reject_rate": 0.0,
        "logical_round": logical_round,
        "malicious_reject_rate": 0.0,
        "malicious_total": 0,
        "phase": "evaluation" if evaluation else "warmup",
        "received_a": 1000 if evaluation else None,
        "received_r": 1000 if evaluation else None,
        "reconstruction_ok": True if evaluation else None,
        "rejected": 0,
        "rejection_evidence": "",
        "round_id": 1_000_000 + logical_round,
        "shuffler_proof_attempts": proofs,
        "shuffler_proof_failed": 0,
        "shuffler_proof_verified": proofs,
        "total": 1000,
        "valid_clients": 1000,
        "warmup_held": 0 if evaluation else 1000,
    }


def write_unit(
    root: Path,
    dataset: str,
    seed: int,
    *,
    state: str = "pass",
) -> Path:
    path = root / dataset / f"seed_{seed}" / "clean" / "status.json"
    dataset_index = MODULE.DATASETS.index(dataset)
    seed_index = MODULE.SEEDS.index(seed)
    port_base = 11000 + 1000 * seed_index + 100 * dataset_index
    start_hour = dataset_index * 3 + seed_index
    payload = {
        "artifacts": {
            "vkey": {"path": "/artifact/vkey", "sha256": digest("vkey")},
            "wasm": {"path": "/artifact/wasm", "sha256": digest("wasm")},
            "zkey": {"path": "/artifact/zkey", "sha256": digest("zkey")},
        },
        "config": {
            "attack_sequence": [],
            "attack_type": "none",
            "clients": 1000,
            "condition": "clean",
            "dataset": dataset,
            "eval_rounds": 10,
            "malicious_rate": 0.0,
            "ports": {
                "aggregator_a": port_base + 2,
                "aggregator_r": port_base + 3,
                "decoder": port_base + 10,
                "shuffler": port_base + 1,
            },
            "profile": "v4-paper-k6",
            "project": f"v4n1000_{dataset}_{seed}",
            "seed": seed,
            "tau": 3.0,
            "tau2": 3.0,
            "warmup_rounds": 6,
        },
        "finished_at": f"2026-07-13T{start_hour + 1:02d}:00:00Z",
        "gate": {
            "dp_release": "pass",
            "full_groth16": "pass",
            "paired_routes": "pass",
            "protocol": "pass",
            "reconstruction": "pass",
        },
        "rounds": [round_row(index) for index in range(16)],
        "started_at": f"2026-07-13T{start_hour:02d}:00:00Z",
        "state": state,
    }
    write_json(path, payload)
    return path


def write_sources(repo: Path, root: Path) -> dict[str, Path]:
    manifest = repo / "manifest.json"
    launch_plan = root / "launch_plan.json"
    launch_status = root / "launch_status.json"
    write_json(
        manifest,
        {
            "profile": "v4-paper-k6",
            "artifacts": {
                "vkey": {"path": "artifact/vkey", "sha256": digest("vkey")},
                "wasm": {"path": "artifact/wasm", "sha256": digest("wasm")},
                "zkey": {"path": "artifact/zkey", "sha256": digest("zkey")},
            },
        },
    )
    units = [
        {
            "dataset": dataset,
            "seed": seed,
            "port_base": (
                11000
                + 1000 * MODULE.SEEDS.index(seed)
                + 100 * MODULE.DATASETS.index(dataset)
            ),
            "out_dir": str(root / dataset / f"seed_{seed}" / "clean"),
        }
        for seed in MODULE.SEEDS
        for dataset in MODULE.DATASETS
    ]
    write_json(
        launch_plan,
        {
            "config": {
                "clients": 1000,
                "datasets": list(MODULE.DATASETS),
                "eval_rounds": 10,
                "jobs": 2,
                "out_dir": str(root),
                "round_timeout_sec": 7200,
                "seeds": list(MODULE.SEEDS),
                "warmup_rounds": 6,
            },
            "gates": {name: True for name in MODULE.REQUIRED_PREFLIGHT_GATES},
            "units": units,
        },
    )
    write_json(
        launch_status,
        {
            "completed_units": 15,
            "failed_units": 0,
            "finished_at": "2026-07-13T15:24:37Z",
            "jobs": 2,
            "results": [
                {
                    "dataset": dataset,
                    "out_dir": str(root / dataset / f"seed_{seed}" / "clean"),
                    "returncode": 0,
                    "seed": seed,
                    "state": "skipped_pass",
                }
                for seed in MODULE.SEEDS
                for dataset in MODULE.DATASETS
            ],
            "started_at": "2026-07-13T11:11:51Z",
            "state": "pass",
            "total_units": 15,
        },
    )
    return {
        "manifest": manifest,
        "launch_plan": launch_plan,
        "launch_status": launch_status,
    }


def complete_tree(tmp_path: Path) -> tuple[Path, Path, dict[str, Path]]:
    repo = tmp_path
    root = repo / "scale"
    for dataset in MODULE.DATASETS:
        for seed in MODULE.SEEDS:
            write_unit(root, dataset, seed)
    return repo, root, write_sources(repo, root)


def summarize_complete(tmp_path: Path) -> tuple[dict, Path, dict[str, Path]]:
    repo, root, sources = complete_tree(tmp_path)
    summary = MODULE.summarize(
        repo=repo,
        root=root,
        manifest=sources["manifest"],
        launch_plan=sources["launch_plan"],
        launch_status=sources["launch_status"],
    )
    return summary, root, sources


def mutate(path: Path, callback) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    callback(payload)
    write_json(path, payload)


def test_summarize_accepts_exact_fifteen_unit_matrix(tmp_path: Path) -> None:
    summary, _, sources = summarize_complete(tmp_path)

    assert summary["status"] == "verified"
    assert summary["profile"] == "v4-paper-k6"
    assert summary["units"] == 15
    assert summary["rounds"] == 240
    assert summary["warmup_rounds"] == 90
    assert summary["evaluation_rounds"] == 150
    assert summary["proof_generated"] == 225_000
    assert summary["proof_verified"] == 225_000
    assert summary["proof_failed"] == 0
    assert summary["route_received_a"] == 150_000
    assert summary["route_received_r"] == 150_000
    assert summary["reconstruction_passed"] == 150
    assert summary["dp_release_passed"] == 150
    assert summary["timing_units"] == 15
    assert summary["timing_excluded_units"] == 0
    assert set(summary["by_dataset"]) == set(MODULE.DATASETS)
    assert len(summary["unit_receipts"]) == 15
    assert len({row["receipt_sha256"] for row in summary["unit_receipts"]}) == 15
    assert summary["source_receipts"]["manifest_sha256"] == MODULE.sha256(
        sources["manifest"]
    )
    assert summary["source_receipts"]["launch_plan_sha256"] == MODULE.sha256(
        sources["launch_plan"]
    )
    assert summary["source_receipts"]["launch_sha256"] == MODULE.sha256(
        sources["launch_status"]
    )


def test_write_outputs_is_deterministic_and_paper_ready(tmp_path: Path) -> None:
    summary, _, _ = summarize_complete(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"

    MODULE.write_outputs(
        summary,
        out_json=first / "summary.json",
        out_csv=first / "by_dataset.csv",
        out_tex=first / "table.tex",
    )
    MODULE.write_outputs(
        summary,
        out_json=second / "summary.json",
        out_csv=second / "by_dataset.csv",
        out_tex=second / "table.tex",
    )

    for name in ("summary.json", "by_dataset.csv", "table.tex"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    with (first / "by_dataset.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["dataset"] for row in rows] == list(MODULE.DATASETS)
    table = (first / "table.tex").read_text(encoding="utf-8")
    assert "Generated by script/summarize_v4_n1000_scale.py" in table
    assert "T-Drive" in table
    assert "45{,}000" in table
    assert "do not edit" in table
    assert "Groth16 protocol execution" in table
    assert "timing-eligible units" in table
    assert "Manifest-bound" not in table
    assert "receipts" not in table


def test_host_suspension_keeps_functional_receipt_but_excludes_timing(
    tmp_path: Path,
) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "rome/seed_101/clean/status.json"

    def add_gap(payload: dict) -> None:
        for row in payload["rounds"][4:]:
            row["round_id"] += 8_000_000

    mutate(path, add_gap)
    summary = MODULE.summarize(
        repo=repo,
        root=root,
        manifest=sources["manifest"],
        launch_plan=sources["launch_plan"],
        launch_status=sources["launch_status"],
    )

    assert summary["status"] == "verified"
    assert summary["proof_verified"] == 225_000
    assert summary["timing_units"] == 14
    assert summary["timing_excluded_units"] == 1
    assert summary["by_dataset"]["rome"]["units"] == 3
    assert summary["by_dataset"]["rome"]["timing_units"] == 2
    excluded = next(
        row
        for row in summary["unit_receipts"]
        if row["dataset"] == "rome" and row["seed"] == 101
    )
    assert excluded["timing_status"] == "excluded_host_suspension"
    assert excluded["proofs_per_second"] is None
    assert excluded["timing_wall_seconds"] is None
    assert excluded["max_inter_round_gap_seconds"] > 7200


def test_fewer_than_two_timing_units_per_dataset_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)

    for seed in (101, 202):
        path = root / "rome" / f"seed_{seed}" / "clean" / "status.json"

        def add_gap(payload: dict) -> None:
            for row in payload["rounds"][4:]:
                row["round_id"] += 8_000_000

        mutate(path, add_gap)

    with pytest.raises(MODULE.ScaleReceiptError, match="insufficient timing receipts"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_missing_unit_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    (root / "rome/seed_303/clean/status.json").unlink()

    with pytest.raises(MODULE.ScaleReceiptError, match="missing unit receipt"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_partial_unit_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    write_unit(root, "synthetic", 303, state="running")

    with pytest.raises(MODULE.ScaleReceiptError, match="unit not pass"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("clients", 999),
        ("warmup_rounds", 5),
        ("eval_rounds", 11),
        ("condition", "attack"),
        ("profile", "v4-paper-k30"),
        ("malicious_rate", 0.1),
    ],
)
def test_unit_config_mismatch_is_rejected(
    tmp_path: Path, key: str, value: object
) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "tdrive/seed_101/clean/status.json"
    mutate(path, lambda payload: payload["config"].__setitem__(key, value))

    with pytest.raises(MODULE.ScaleReceiptError, match="unit config mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_unit_gate_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "tdrive/seed_101/clean/status.json"
    mutate(path, lambda payload: payload["gate"].__setitem__("dp_release", "fail"))

    with pytest.raises(MODULE.ScaleReceiptError, match="unit gate mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_unit_artifact_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "geolife/seed_202/clean/status.json"
    mutate(
        path,
        lambda payload: payload["artifacts"]["zkey"].__setitem__(
            "sha256", digest("stale-zkey")
        ),
    )

    with pytest.raises(MODULE.ScaleReceiptError, match="artifact mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rounds: rounds.pop(), "round count mismatch"),
        (
            lambda rounds: rounds[6].__setitem__("logical_round", 7),
            "logical round mismatch",
        ),
        (
            lambda rounds: rounds[6].__setitem__("phase", "warmup"),
            "round phase mismatch",
        ),
    ],
)
def test_round_shape_mismatch_is_rejected(
    tmp_path: Path, mutation, message: str
) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "porto/seed_303/clean/status.json"
    mutate(path, lambda payload: mutation(payload["rounds"]))

    with pytest.raises(MODULE.ScaleReceiptError, match=message):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_route_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "tdrive/seed_101/clean/status.json"
    mutate(path, lambda payload: payload["rounds"][6].__setitem__("received_a", 999))

    with pytest.raises(MODULE.ScaleReceiptError, match="route count mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


@pytest.mark.parametrize("key", ["reconstruction_ok", "dp_ok"])
def test_release_gate_mismatch_is_rejected(tmp_path: Path, key: str) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "rome/seed_202/clean/status.json"
    mutate(path, lambda payload: payload["rounds"][8].__setitem__(key, False))

    with pytest.raises(MODULE.ScaleReceiptError, match="release gate mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("client_proof_generated", 999),
        ("shuffler_proof_verified", 999),
        ("shuffler_proof_failed", 1),
    ],
)
def test_proof_accounting_mismatch_is_rejected(
    tmp_path: Path, key: str, value: int
) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "geolife/seed_202/clean/status.json"
    mutate(path, lambda payload: payload["rounds"][7].__setitem__(key, value))

    with pytest.raises(MODULE.ScaleReceiptError, match="proof accounting mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_clean_round_invariant_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "synthetic/seed_101/clean/status.json"
    mutate(path, lambda payload: payload["rounds"][9].__setitem__("rejected", 1))

    with pytest.raises(MODULE.ScaleReceiptError, match="clean round mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_nonpositive_unit_duration_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    path = root / "synthetic/seed_101/clean/status.json"
    mutate(
        path,
        lambda payload: payload.__setitem__("finished_at", payload["started_at"]),
    )

    with pytest.raises(MODULE.ScaleReceiptError, match="non-positive unit duration"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_manifest_profile_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    mutate(sources["manifest"], lambda payload: payload.__setitem__("profile", "old"))

    with pytest.raises(MODULE.ScaleReceiptError, match="manifest profile mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_launch_plan_gate_failure_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    mutate(
        sources["launch_plan"],
        lambda payload: payload["gates"].__setitem__("ports_free", False),
    )

    with pytest.raises(MODULE.ScaleReceiptError, match="launch plan gate mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_launch_plan_matrix_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    mutate(sources["launch_plan"], lambda payload: payload["units"].pop())

    with pytest.raises(MODULE.ScaleReceiptError, match="launch plan matrix mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("state", "running"),
        ("completed_units", 14),
        ("failed_units", 1),
        ("total_units", 14),
    ],
)
def test_launch_status_mismatch_is_rejected(
    tmp_path: Path, key: str, value: object
) -> None:
    repo, root, sources = complete_tree(tmp_path)
    mutate(sources["launch_status"], lambda payload: payload.__setitem__(key, value))

    with pytest.raises(MODULE.ScaleReceiptError, match="launch status mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )


def test_launch_status_matrix_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, root, sources = complete_tree(tmp_path)
    mutate(sources["launch_status"], lambda payload: payload["results"].pop())

    with pytest.raises(MODULE.ScaleReceiptError, match="launch result matrix mismatch"):
        MODULE.summarize(
            repo=repo,
            root=root,
            manifest=sources["manifest"],
            launch_plan=sources["launch_plan"],
            launch_status=sources["launch_status"],
        )
