#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams  # noqa: E402
from common.policy_profile import PolicyProfile, PolicyRegistry, load_policy_profiles, sha256_file  # noqa: E402
from common.settlement import (  # noqa: E402
    ReceiverFix,
    TariffTable,
    compute_public_statement_commitment,
    sign_receiver_fix,
    sign_receiver_root_attestation,
)
from script.prove_settlement_period_v5 import (  # noqa: E402
    MAX_DT_SEC,
    N_FIXES,
    PUBLIC_SIGNAL_COUNT,
    SETTLEMENT_PROFILE,
    TIER_VMAX_MPS,
    TREE_DEPTH,
    _DEVICE_PUBLIC_KEY_BYTES,
    _DEVICE_SEED,
    build_input_for_fixes,
    build_tariff,
)
from services.charger import app as charger_app  # noqa: E402


DEFAULT_OUTPUT = ROOT_DIR / "experiments" / "waybill_m0" / "v1"
ZK_DIR = ROOT_DIR / "zk" / f"settlement_period_v5_{SETTLEMENT_PROFILE}"
WASM = ZK_DIR / f"settlement_period_v5_{SETTLEMENT_PROFILE}_js" / f"settlement_period_v5_{SETTLEMENT_PROFILE}.wasm"
R1CS = ZK_DIR / f"settlement_period_v5_{SETTLEMENT_PROFILE}.r1cs"
ZKEY = ZK_DIR / f"settlement_period_v5_{SETTLEMENT_PROFILE}_final.zkey"
VKEY = ZK_DIR / "verification_key.json"
PTAU = ROOT_DIR / "zk" / "hello" / "pot18_final_phase2.ptau"
PROFILE_DIR = ROOT_DIR / "configs" / "settlement_policy_profiles"


def _run(command: list[str], *, timeout: int = 1_200) -> tuple[str, float]:
    start = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    elapsed_ms = (time.perf_counter() - start) * 1_000
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(command)}\n{proc.stdout}")
    return proc.stdout, elapsed_ms


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _hash_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _build_expensive_route_fixes(period_id: str) -> list[ReceiverFix]:
    fixes: list[ReceiverFix] = []
    for seq in range(N_FIXES):
        # grid_w=100: (x=28..52,y=1) maps to cells 128..152, which
        # are expensive in the canonical tariff and cheap in P-ROOT.
        raw = ReceiverFix(
            device_id="dev-m0-real-proof",
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=1_777_593_600 + seq * 300,
            cell_x=28 + seq,
            cell_y=1,
            osnma_status="authenticated",
            odometer_reading_m=10_000 + seq * 100,
            nonce=f"m0-real-proof-{seq:02d}",
        )
        fixes.append(sign_receiver_fix(raw, _DEVICE_SEED))
    return fixes


def _private_low_root_tariff() -> TariffTable:
    # Keep one expensive leaf so r_max remains 5.  Only the route's cells are
    # remapped to the cheap zone, isolating P-ROOT from P-RMAX.
    cells = {idx: (20 if idx == 255 else 10) for idx in range(1 << TREE_DEPTH)}
    return TariffTable(
        tariff_version=7,
        grid_w=100,
        cell_zones=cells,
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def _attach_profile(public: dict[str, Any], profile: PolicyProfile) -> dict[str, Any]:
    result = copy.deepcopy(public)
    result.update(profile.public_statement_fields())
    result["statement_commitment"] = compute_public_statement_commitment(result)
    return result


def _prove(
    *,
    name: str,
    input_json: dict[str, Any],
    output_dir: Path,
    zkey: Path = ZKEY,
    vkey: Path = VKEY,
) -> dict[str, Any]:
    case_dir = output_dir / "proofs" / name
    case_dir.mkdir(parents=True, exist_ok=True)
    input_path = case_dir / "input.json"
    proof_path = case_dir / "proof.json"
    public_path = case_dir / "public.json"
    input_path.write_text(json.dumps(input_json, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix=f"waybill-m0-{name}-") as td:
        witness = Path(td) / "witness.wtns"
        _witness_out, witness_ms = _run(
            ["snarkjs", "wtns", "calculate", str(WASM), str(input_path), str(witness)]
        )
        _prove_out, prove_ms = _run(
            ["snarkjs", "groth16", "prove", str(zkey), str(witness), str(proof_path), str(public_path)]
        )
    verify_out, verify_ms = _run(
        ["snarkjs", "groth16", "verify", str(vkey), str(public_path), str(proof_path)]
    )
    signals = json.loads(public_path.read_text(encoding="utf-8"))
    if len(signals) != PUBLIC_SIGNAL_COUNT:
        raise RuntimeError(f"{name}: unexpected public signal count {len(signals)}")
    if "OK" not in verify_out:
        raise RuntimeError(f"{name}: independent Groth16 verification did not report OK")
    return {
        "name": name,
        "input_path": str(input_path.relative_to(ROOT_DIR)),
        "proof_path": str(proof_path.relative_to(ROOT_DIR)),
        "public_path": str(public_path.relative_to(ROOT_DIR)),
        "proof": json.loads(proof_path.read_text(encoding="utf-8")),
        "public_signals": signals,
        "proof_sha256": sha256_file(proof_path),
        "public_sha256": sha256_file(public_path),
        "vkey_sha256": sha256_file(vkey),
        "witness_ms": round(witness_ms, 3),
        "prove_ms": round(prove_ms, 3),
        "verify_ms": round(verify_ms, 3),
        "cryptographically_valid": True,
    }


def _payload(public: dict[str, Any], proof_artifact: dict[str, Any]) -> dict[str, Any]:
    expected = [str(value) for value in charger_app._expected_public_signal_values(public)]
    actual = [str(value) for value in proof_artifact["public_signals"]]
    if actual != expected:
        raise RuntimeError("proof public signals do not match the internally consistent attack statement")
    return {
        "public_statement": public,
        "proof": proof_artifact["proof"],
        "public_signals": actual,
        "root_attestation": sign_receiver_root_attestation(
            public_statement=public,
            device_id="dev-m0-real-proof",
            private_key_bytes=_DEVICE_SEED,
        ),
    }


def _fresh_client(profiles: list[PolicyProfile]) -> TestClient:
    charger_app.policy_registry = PolicyRegistry(profiles)
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    response = client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-m0-real-proof",
            "public_key_hex": _DEVICE_PUBLIC_KEY_BYTES.hex(),
            "jurisdiction_id": "ruc-demo",
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"device registration failed: {response.text}")
    return client


def _service_receipt(
    *,
    attack_id: str,
    profile: PolicyProfile,
    public: dict[str, Any],
    proof_artifact: dict[str, Any],
    expected_status: int = 400,
) -> dict[str, Any]:
    client = _fresh_client([profile])
    start = time.perf_counter()
    response = client.post("/settlement/period/proof-only", json=_payload(public, proof_artifact))
    latency_ms = (time.perf_counter() - start) * 1_000
    if response.status_code != expected_status:
        raise RuntimeError(
            f"{attack_id}: expected HTTP {expected_status}, got {response.status_code}: {response.text}"
        )
    return {
        "attack_id": attack_id,
        "expected": "accept" if expected_status == 200 else "reject",
        "http_status": response.status_code,
        "accepted": response.status_code == 200,
        "detail": response.json().get("detail", "accepted"),
        "request_latency_ms": round(latency_ms, 3),
        "proof_case": proof_artifact["name"],
        "proof_sha256": proof_artifact["proof_sha256"],
        "public_sha256": proof_artifact["public_sha256"],
        "proof_valid_under_submitted_vkey": proof_artifact["cryptographically_valid"],
        "submitted_profile_commitment": str(public["policy_profile_commitment"]),
        "canonical_profile_commitment": str(profile.commitment),
    }


def run_gate(output_dir: Path) -> dict[str, Any]:
    for required in (WASM, R1CS, ZKEY, VKEY, PTAU):
        if not required.is_file():
            raise FileNotFoundError(required)
    output_dir.mkdir(parents=True, exist_ok=True)

    registry = load_policy_profiles(PROFILE_DIR)
    if len(registry.profiles) != 1:
        raise RuntimeError("M0 runner expects exactly one checked-in canonical demo profile")
    canonical_profile = registry.profiles[0]
    canonical_tariff = build_tariff()
    canonical_profile.assert_tariff_matches(canonical_tariff)
    fixes = _build_expensive_route_fixes("2026-05-m0-real-proof")
    params = HarnessParams(cadence_sec=300, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)

    canonical_input, canonical_submission = build_input_for_fixes(
        fixes,
        canonical_tariff,
        params=params,
    )
    canonical_public = _attach_profile(canonical_submission["public_statement"], canonical_profile)
    canonical_proof = _prove(
        name="canonical",
        input_json=canonical_input,
        output_dir=output_dir,
    )

    receipts: list[dict[str, Any]] = [
        _service_receipt(
            attack_id="POS-CANONICAL",
            profile=canonical_profile,
            public=canonical_public,
            proof_artifact=canonical_proof,
            expected_status=200,
        )
    ]

    proof_cases: dict[str, tuple[PolicyProfile, dict[str, Any], dict[str, Any]]] = {}

    private_tariff = _private_low_root_tariff()
    root_input, root_submission = build_input_for_fixes(fixes, private_tariff, params=params)
    root_profile = replace(canonical_profile, tariff_root=private_tariff.root(TREE_DEPTH))
    proof_cases["P-ROOT"] = (
        root_profile,
        _attach_profile(root_submission["public_statement"], root_profile),
        _prove(name="p-root", input_json=root_input, output_dir=output_dir),
    )

    mutations: dict[str, tuple[dict[str, Any], PolicyProfile]] = {
        "P-RMAX": (
            {"max_zone_rate_cents_per_m": "1"},
            replace(
                canonical_profile,
                max_zone_rate_cents_per_m=1,
                monthly_reconciliation_rate_cents_per_m=1,
            ),
        ),
        "P-CAD": (
            {"cadence_sec": "600"},
            replace(canonical_profile, cadence_sec=600),
        ),
        "P-SPEED": (
            {"tier_vmax_mps": "40", "tier_vmax_sq": "1600", "mode_vmax_sq": "1600"},
            replace(
                canonical_profile,
                tier_vmax_mps=40,
                tier_vmax_sq=1600,
                mode_vmax_sq=1600,
            ),
        ),
        "P-CAP": (
            {"cap_policy_sq": "3200000000"},
            replace(
                canonical_profile,
                cap_policy_sq=3_200_000_000,
                cap_policy_hash=hashlib.sha256(b"attacker-cap-policy-v2").hexdigest(),
            ),
        ),
    }
    for attack_id, (input_changes, attacker_profile) in mutations.items():
        attacked_input = copy.deepcopy(canonical_input)
        attacked_input.update(input_changes)
        attacked_public = _attach_profile(canonical_submission["public_statement"], attacker_profile)
        proof_cases[attack_id] = (
            attacker_profile,
            attacked_public,
            _prove(name=attack_id.lower(), input_json=attacked_input, output_dir=output_dir),
        )

    for attack_id in ("P-ROOT", "P-RMAX", "P-CAD", "P-SPEED", "P-CAP"):
        _attacker_profile, public, proof = proof_cases[attack_id]
        receipts.append(
            _service_receipt(
                attack_id=attack_id,
                profile=canonical_profile,
                public=public,
                proof_artifact=proof,
            )
        )

    arithmetic_profile = replace(
        canonical_profile,
        currency="USD",
        fixed_point_scale=100,
        rounding_mode="floor",
    )
    receipts.append(
        _service_receipt(
            attack_id="P-ARITH",
            profile=canonical_profile,
            public=_attach_profile(canonical_submission["public_statement"], arithmetic_profile),
            proof_artifact=canonical_proof,
        )
    )

    with tempfile.TemporaryDirectory(prefix="waybill-m0-alt-key-") as td:
        alt_zkey = Path(td) / "alternative.zkey"
        _run(["snarkjs", "groth16", "setup", str(R1CS), str(PTAU), str(alt_zkey)])
        alt_vkey = output_dir / "alternative_verification_key.json"
        _run(["snarkjs", "zkey", "export", "verificationkey", str(alt_zkey), str(alt_vkey)])
        alt_proof = _prove(
            name="p-vkey",
            input_json=canonical_input,
            output_dir=output_dir,
            zkey=alt_zkey,
            vkey=alt_vkey,
        )
    alt_profile = replace(
        canonical_profile,
        circuit_id="settlement-period-v5-unapproved-key",
        verification_key_hash=sha256_file(output_dir / "alternative_verification_key.json"),
    )
    receipts.append(
        _service_receipt(
            attack_id="P-VKEY",
            profile=canonical_profile,
            public=_attach_profile(canonical_submission["public_statement"], alt_profile),
            proof_artifact=alt_proof,
        )
    )

    missing_key_profile = replace(
        canonical_profile,
        verification_key_path=str(output_dir / "does-not-exist-vkey.json"),
    )
    receipts.append(
        _service_receipt(
            attack_id="P-NOKEY",
            profile=missing_key_profile,
            public=canonical_public,
            proof_artifact=canonical_proof,
        )
    )

    metadata_attacks = {
        "P-OLD": replace(canonical_profile, profile_version=6, min_accepted_version=6),
        "P-REVOKE": replace(canonical_profile, revoked_at=1_777_593_601),
        "P-XJUR": replace(canonical_profile, jurisdiction_id="attacker-jurisdiction"),
    }
    for attack_id, attacker_profile in metadata_attacks.items():
        receipts.append(
            _service_receipt(
                attack_id=attack_id,
                profile=canonical_profile,
                public=_attach_profile(canonical_submission["public_statement"], attacker_profile),
                proof_artifact=canonical_proof,
            )
        )

    replay_client = _fresh_client([canonical_profile])
    replay_payload = _payload(canonical_public, canonical_proof)
    first = replay_client.post("/settlement/period/proof-only", json=replay_payload)
    second = replay_client.post("/settlement/period/proof-only", json=replay_payload)
    if first.status_code != 200 or second.status_code != 409:
        raise RuntimeError(f"P-REPLAY unexpected statuses: {first.status_code}, {second.status_code}")
    receipts.append(
        {
            "attack_id": "P-REPLAY",
            "expected": "reject/idempotent-without-double-credit",
            "http_status": second.status_code,
            "accepted": False,
            "detail": second.json().get("detail"),
            "first_http_status": first.status_code,
            "ledger_periods_after_replay": len(charger_app.accepted_periods),
            "proof_case": canonical_proof["name"],
            "proof_sha256": canonical_proof["proof_sha256"],
            "proof_valid_under_submitted_vkey": True,
            "submitted_profile_commitment": str(canonical_profile.commitment),
            "canonical_profile_commitment": str(canonical_profile.commitment),
        }
    )

    attack_receipts = [row for row in receipts if row["attack_id"].startswith("P-")]
    attack_ids = {row["attack_id"] for row in attack_receipts}
    expected_attack_ids = {
        "P-ROOT",
        "P-RMAX",
        "P-CAD",
        "P-SPEED",
        "P-CAP",
        "P-ARITH",
        "P-VKEY",
        "P-NOKEY",
        "P-OLD",
        "P-REVOKE",
        "P-XJUR",
        "P-REPLAY",
    }
    if attack_ids != expected_attack_ids:
        raise RuntimeError(f"attack matrix drift: {sorted(attack_ids)}")
    if any(row["accepted"] for row in attack_receipts):
        raise RuntimeError("M0 failed: at least one policy attack was accepted")

    _write_jsonl(output_dir / "acceptance_receipts.jsonl", receipts)
    manifest = {
        "schema": "waybill.m0.environment/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "snarkjs": subprocess.run(
            ["snarkjs", "--version"], cwd=ROOT_DIR, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "canonical_profile_path": str((PROFILE_DIR / "ruc-demo-v7.json").relative_to(ROOT_DIR)),
        "canonical_profile_sha256": canonical_profile.profile_sha256,
        "canonical_profile_commitment": str(canonical_profile.commitment),
        "canonical_vkey_sha256": sha256_file(VKEY),
        "circuit_r1cs_sha256": sha256_file(R1CS),
        "circuit_wasm_sha256": sha256_file(WASM),
        "code_hashes": {
            str(path.relative_to(ROOT_DIR)): sha256_file(path)
            for path in (
                ROOT_DIR / "common" / "policy_profile.py",
                ROOT_DIR / "common" / "settlement.py",
                ROOT_DIR / "services" / "charger" / "app.py",
                ROOT_DIR / "script" / "run_waybill_m0_policy_gate.py",
            )
        },
        "command": "python script/run_waybill_m0_policy_gate.py",
    }
    _write_json(output_dir / "environment_manifest.json", manifest)

    summary = {
        "schema": "waybill.m0.summary/v1",
        "gate": "M0-canonical-policy-binding",
        "status": "verified",
        "positive_cases": 1,
        "positive_accepts": 1,
        "attack_cases": len(attack_receipts),
        "attack_rejections": sum(not row["accepted"] for row in attack_receipts),
        "fail_open_count": sum(bool(row["accepted"]) for row in attack_receipts),
        "all_submitted_proofs_independently_valid": all(
            bool(row["proof_valid_under_submitted_vkey"]) for row in receipts
        ),
        "canonical_bill_cents": canonical_public["total_fee_cents"],
        "private_root_bill_cents": proof_cases["P-ROOT"][1]["total_fee_cents"],
        "canonical_profile_commitment": str(canonical_profile.commitment),
        "receipt_sha256": _hash_json(receipts),
        "hard_gate_passed": True,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WayBill M0 canonical-policy proof gate.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run_gate(args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
