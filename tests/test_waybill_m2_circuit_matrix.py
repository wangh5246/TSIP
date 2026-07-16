from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement_v6 import PUBLIC_SIGNAL_ORDER_V6
from script import run_waybill_m2_circuit_matrix as matrix


def test_all_16_wrappers_are_deterministic_and_bind_the_frozen_public_order(tmp_path: Path) -> None:
    wrappers = []
    for depth in matrix.DEPTHS:
        for fixes in matrix.FIX_COUNTS:
            text = matrix.wrapper_text(depth, fixes)
            wrappers.append(text)
            assert f"SettlementPeriodV6({fixes}, {depth}, 6)" in text
            assert text.index("receiver_fix_root") < text.index("policy_profile_commitment")
            assert text.index("policy_profile_commitment") < text.index("period_id_field")
            for signal in PUBLIC_SIGNAL_ORDER_V6:
                assert text.count(signal) == 1
    assert len(set(wrappers)) == 16


def test_wrapper_rejects_unregistered_configuration() -> None:
    with pytest.raises(ValueError, match="pre-registered"):
        matrix.wrapper_text(15, 25)
    with pytest.raises(ValueError, match="pre-registered"):
        matrix.wrapper_text(14, 24)


def _profile(tmp_path: Path, fixes: int = 25):
    paths = matrix.config_paths(tmp_path, 14, fixes)
    paths["vkey"].parent.mkdir(parents=True, exist_ok=True)
    paths["vkey"].write_text('{"benchmark":"test-only"}\n', encoding="utf-8")
    return matrix.create_policy_profile(
        output_dir=tmp_path,
        fixes_count=fixes,
        verification_key_path=paths["vkey"],
    )


def test_city_input_uses_profile_real_10000_cell_root_and_depth14_membership(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    circuit_input, metadata = matrix.build_city_input(25, policy_profile=profile)
    manifest = json.loads(matrix.TARIFF_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert metadata["real_tariff_cells"] == 10_000
    assert metadata["tariff_root"] == manifest["tariff_root"]
    assert circuit_input["tariff_root"] == manifest["tariff_root"]
    assert circuit_input["policy_profile_commitment"] == str(profile.commitment)
    assert metadata["policy_profile_sha256"] == profile.profile_sha256
    assert metadata["verification_key_hash"] == profile.verification_key_hash
    assert len(circuit_input["zone_path_sibling"]) == 24
    assert all(len(path) == 14 for path in circuit_input["zone_path_sibling"])
    assert len(circuit_input["position_valid"]) == 24
    assert int(circuit_input["cap_policy_sq"]) == matrix.M2_CAP_POLICY_SQ
    assert matrix.M2_CAP_POLICY_SQ <= matrix.TIER_VMAX_MPS**2 * matrix.CADENCE_SEC**2 * matrix.K_WINDOW**2
    assert [circuit_input[name] for name in PUBLIC_SIGNAL_ORDER_V6] == metadata["public_signals"]


def test_city_input_rejects_zero_or_unmatched_policy_commitment(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="zero policy"):
        matrix.build_city_input(25, policy_profile=SimpleNamespace(commitment=0))  # type: ignore[arg-type]

    profile = _profile(tmp_path)
    mismatched = replace(profile, max_fixes=50)
    with pytest.raises(ValueError, match="max_fixes"):
        matrix.build_city_input(25, policy_profile=mismatched)


def test_snake_walk_has_no_row_wrap_jump_and_covers_200_fixes() -> None:
    cells = [matrix.snake_cell(index) for index in range(200)]
    assert len(set(cells)) == 200
    assert cells[99] == (99, 0)
    assert cells[100] == (99, 1)
    assert cells[199] == (0, 1)
    for previous, current in zip(cells, cells[1:]):
        assert abs(previous[0] - current[0]) + abs(previous[1] - current[1]) == 1


def test_r1cs_info_parser_and_nearest_rank_percentiles() -> None:
    parsed = matrix.parse_r1cs_info(
        """# of Wires: 1,234\n# of Constraints: 2,345\n# of Private Inputs: 12\n"
        "# of Public Inputs: 22\n# of Labels: 9,999\n# of Outputs: 0\n"""
    )
    assert parsed == {
        "wires": 1234,
        "constraints": 2345,
        "private_inputs": 12,
        "public_inputs": 22,
        "labels": 9999,
        "outputs": 0,
    }
    assert matrix.nearest_rank([10.0, 20.0, 30.0], 0.50) == 20.0
    assert matrix.nearest_rank([10.0, 20.0, 30.0], 0.95) == 30.0
    assert matrix.nearest_rank([], 0.95) is None


def test_measured_command_records_success_and_failure() -> None:
    success = matrix.run_measured(["/usr/bin/true"], timeout_sec=10)
    assert success.status == "ok"
    assert success.returncode == 0
    assert success.max_rss_bytes is not None

    failure = matrix.run_measured(["/usr/bin/false"], timeout_sec=10)
    assert failure.status == "failed"
    assert failure.returncode != 0
    assert failure.error is not None


def _compile_receipts() -> list[dict]:
    return [
        {
            "schema": "waybill-m2-circuit-compile-receipt-v1",
            "config_id": matrix.wrapper_name(depth, fixes),
            "depth": depth,
            "fixes": fixes,
            "status": "compiled",
            "r1cs_info": {"constraints": 1},
        }
        for depth in matrix.DEPTHS
        for fixes in matrix.FIX_COUNTS
    ]


def test_aggregate_shape_gates_reject_wrong_duplicate_or_stale_evidence(tmp_path: Path) -> None:
    compile_receipts = _compile_receipts()
    assert matrix.compile_receipt_matrix_shape_passed(compile_receipts)
    wrong = copy.deepcopy(compile_receipts)
    wrong[-1]["config_id"] = wrong[0]["config_id"]
    assert not matrix.compile_receipt_matrix_shape_passed(wrong)

    setup_receipts = [
        {
            "schema": "waybill-m2-groth16-setup-receipt-v1",
            "config_id": matrix.wrapper_name(depth, fixes),
            "depth": depth,
            "fixes": fixes,
            "setup": {
                "command": [
                    "snarkjs",
                    "groth16",
                    "setup",
                    f"/evidence/{matrix.wrapper_name(depth, fixes)}.r1cs",
                    "/evidence/powersOfTau28_hez_final_22.ptau",
                    f"/evidence/{matrix.wrapper_name(depth, fixes)}_test_only.zkey",
                ],
                "status": "ok",
            },
        }
        for depth in matrix.DEPTHS
        for fixes in matrix.FIX_COUNTS
    ]
    assert matrix.setup_receipt_matrix_real_attempts(setup_receipts)
    stale_preflight = copy.deepcopy(setup_receipts)
    stale_preflight[0].pop("setup")
    stale_preflight[0]["failure"] = {"stage": "ptau_preflight"}
    assert not matrix.setup_receipt_matrix_real_attempts(stale_preflight)
    wrong_dimensions = copy.deepcopy(setup_receipts)
    wrong_dimensions[0]["depth"] = 16
    assert not matrix.setup_receipt_matrix_real_attempts(wrong_dimensions)
    retargeted_command = copy.deepcopy(setup_receipts)
    retargeted_command[0]["setup"]["command"][3] = retargeted_command[1]["setup"]["command"][3]
    assert not matrix.setup_receipt_matrix_real_attempts(retargeted_command)

    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"current")
    record = {"path": str(artifact), "bytes": 7, "sha256": matrix.sha256_file(artifact)}
    assert matrix.artifact_record_matches_current(record)
    artifact.write_bytes(b"stale")
    assert not matrix.artifact_record_matches_current(record)


def test_symbol_prune_preserves_original_receipts_and_has_a_strict_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(matrix, "ROOT_DIR", tmp_path)
    compile_receipts = []
    for depth in matrix.DEPTHS:
        for fixes in matrix.FIX_COUNTS:
            name = matrix.wrapper_name(depth, fixes)
            paths = matrix.config_paths(tmp_path, depth, fixes)
            paths["sym"].parent.mkdir(parents=True, exist_ok=True)
            paths["sym"].write_bytes(name.encode("utf-8"))
            receipt = {
                "schema": "waybill-m2-circuit-compile-receipt-v1",
                "config_id": name,
                "depth": depth,
                "fixes": fixes,
                "artifacts": {"sym": matrix.artifact_record(paths["sym"])},
            }
            matrix.write_json(tmp_path / "receipts" / "compile" / f"{name}.json", receipt)
    prune = matrix.prune_compile_symbol_artifacts(tmp_path)
    assert prune["status"] == "passed"
    for depth in matrix.DEPTHS:
        for fixes in matrix.FIX_COUNTS:
            name = matrix.wrapper_name(depth, fixes)
            compile_receipts.append(
                json.loads(
                    (tmp_path / "receipts" / "compile" / f"{name}.json").read_text(
                        encoding="utf-8"
                    )
                )
            )
            assert not matrix.config_paths(tmp_path, depth, fixes)["sym"].exists()
    assert matrix.compile_symbol_prune_gate_passed(tmp_path, compile_receipts)
    compile_receipts[0]["artifacts"]["sym"]["sha256"] = "0" * 64
    assert not matrix.compile_symbol_prune_gate_passed(tmp_path, compile_receipts)


def test_ptau_gate_rejects_bad_receipt_or_depth14_binding(tmp_path: Path) -> None:
    ptau = tmp_path / matrix.PTAU_FILENAME
    with ptau.open("wb") as handle:
        handle.truncate(matrix.PTAU_BYTES)
    receipt = {
        "status": "verified",
        "bytes": matrix.PTAU_BYTES,
        "actual_blake2b": matrix.PTAU_BLAKE2B,
        "expected_blake2b": matrix.PTAU_BLAKE2B,
    }
    setups = [
        {"depth": 14, "ptau": {"blake2b": matrix.PTAU_BLAKE2B}}
        for _ in matrix.FIX_COUNTS
    ]
    assert matrix.ptau_metadata_gate_passed(
        ptau_path=ptau,
        receipt=receipt,
        setup_receipts=setups,
        actual_blake2b=matrix.PTAU_BLAKE2B,
    )
    bad_receipt = {**receipt, "actual_blake2b": "0" * 128}
    assert not matrix.ptau_metadata_gate_passed(
        ptau_path=ptau,
        receipt=bad_receipt,
        setup_receipts=setups,
        actual_blake2b=matrix.PTAU_BLAKE2B,
    )
    bad_setups = copy.deepcopy(setups)
    bad_setups[0]["ptau"]["blake2b"] = "0" * 128
    assert not matrix.ptau_metadata_gate_passed(
        ptau_path=ptau,
        receipt=receipt,
        setup_receipts=bad_setups,
        actual_blake2b=matrix.PTAU_BLAKE2B,
    )


def test_proof_shape_gate_rejects_missing_warmup_or_duplicate_config() -> None:
    receipts = [
        {
            "schema": "waybill-m2-depth14-proof-summary-v1",
            "config_id": matrix.wrapper_name(14, fixes),
            "depth": 14,
            "fixes": fixes,
            "status": "verified",
            "warmup_status": "verified",
            "measured_trials_required": 3,
            "measured_trials_completed": 3,
            "verified_trials": 3,
            "verification_failures": 0,
            "independent_proof_randomness_observed": True,
            "negative_correctness_gates": {"status": "passed"},
            "metrics": {stage: {"samples": 3} for stage in ("witness", "prove", "verify")},
        }
        for fixes in matrix.FIX_COUNTS
    ]
    assert matrix.depth14_proof_receipt_shape_passed(receipts)
    no_warmup = copy.deepcopy(receipts)
    no_warmup[0]["warmup_status"] = "failed"
    assert not matrix.depth14_proof_receipt_shape_passed(no_warmup)
    duplicate = copy.deepcopy(receipts)
    duplicate[-1]["config_id"] = duplicate[0]["config_id"]
    assert not matrix.depth14_proof_receipt_shape_passed(duplicate)
