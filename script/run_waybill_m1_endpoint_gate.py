#!/usr/bin/env python3
"""Submit the canonical-profile V6 proof through the production charger gates."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT_DIR / "experiments/waybill_m1/v2/circuit_differential"
PROFILE_REGISTRY_DIR = ROOT_DIR / "configs/settlement_policy_profiles"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# The charger loads its authority registry during module import.  Point it at
# the frozen M1 profile directory before importing the app.
os.environ["SETTLEMENT_POLICY_PROFILE_DIR"] = str(PROFILE_REGISTRY_DIR)
os.environ["WAYBILL_CHARGER_TEST_MODE"] = "1"
os.environ["WAYBILL_CHARGER_DATABASE_URL"] = "sqlite+pysqlite://"
os.environ["WAYBILL_CHARGER_DOMAIN"] = "ruc-demo.charger-test"
os.environ["WAYBILL_CHARGER_ADMIN_TOKEN"] = "waybill-test-admin-token"
os.environ["WAYBILL_CHARGER_TOKEN_PEPPER"] = "waybill-test-token-pepper"

from fastapi.testclient import TestClient  # noqa: E402

from common.settlement import (  # noqa: E402
    canonical_json,
    receiver_attestation_sha256,
    sign_monthly_odometer_attestation,
)
from script.prove_settlement_period_v6 import (  # noqa: E402
    _DEVICE_PUBLIC_KEY_BYTES,
    _DEVICE_SEED,
)
from services.charger import app as charger_app  # noqa: E402


def _load(name: str) -> Any:
    return json.loads((ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict[str, object]:
    submission = dict(_load("submission.json"))
    proof = dict(_load("proof.json"))
    public_signals = list(_load("public.json"))
    profile = json.loads(
        (PROFILE_REGISTRY_DIR / "ruc-demo-v9.json").read_text(encoding="utf-8")
    )
    public = dict(submission["public_statement"])
    receiver_public_key_hex = str(
        submission.get("receiver_public_key_hex", _DEVICE_PUBLIC_KEY_BYTES.hex())
    )

    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    registration = client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-v6",
            "public_key_hex": receiver_public_key_hex,
            "jurisdiction_id": str(profile["jurisdiction_id"]),
        },
    )
    if registration.status_code != 200:
        raise RuntimeError(f"device registration failed: {registration.text}")

    payload = {
        "public_statement": public,
        "proof": proof,
        "public_signals": public_signals,
        "root_attestation": submission["receiver_root_attestation"],
    }
    anchored = client.post(
        "/settlement/receiver-chain/anchor",
        json={"root_attestation": submission["receiver_root_attestation"]},
    )
    if anchored.status_code != 200:
        raise RuntimeError(f"receiver attestation anchoring failed: {anchored.text}")
    tampered_payload = dict(payload)
    tampered_signals = list(public_signals)
    tampered_signals[7] = str(int(tampered_signals[7]) + 1)
    tampered_payload["public_signals"] = tampered_signals
    tampered = client.post("/settlement/v6/period/proof-only", json=tampered_payload)
    accepted = client.post("/settlement/v6/period/proof-only", json=payload)
    if accepted.status_code != 200:
        raise RuntimeError(f"canonical proof was rejected: {accepted.text}")

    replay = client.post("/settlement/v6/period/proof-only", json=payload)

    fixes = list(submission["fixes"])
    month_attestation = submission.get("receiver_monthly_odometer_attestation")
    if not isinstance(month_attestation, dict):
        month_attestation = sign_monthly_odometer_attestation(
            charger_domain="ruc-demo.charger-test",
            device_id="dev-v6",
            month_id=str(public["month_id"]),
            odometer_start_m=int(fixes[0]["odometer_reading_m"]),
            odometer_end_m=int(fixes[-1]["odometer_reading_m"]) + 600,
            private_key_bytes=_DEVICE_SEED,
        )
    else:
        month_attestation = dict(month_attestation)
        month_attestation.pop("month_epoch", None)
    attested = client.post("/settlement/month/attest", json=month_attestation)
    attested_retry = client.post("/settlement/month/attest", json=month_attestation)
    conflict_probe_device_id = "dev-v6-month-conflict-probe"
    conflict_probe_registration = client.post(
        "/settlement/devices/register",
        json={
            "device_id": conflict_probe_device_id,
            "public_key_hex": _DEVICE_PUBLIC_KEY_BYTES.hex(),
            "jurisdiction_id": str(profile["jurisdiction_id"]),
        },
    )
    conflict_probe_attestation = sign_monthly_odometer_attestation(
        charger_domain="ruc-demo.charger-test",
        device_id=conflict_probe_device_id,
        month_id="202604",
        odometer_start_m=1_000,
        odometer_end_m=1_600,
        private_key_bytes=_DEVICE_SEED,
    )
    conflict_probe_anchor = client.post(
        "/settlement/month/attest", json=conflict_probe_attestation
    )
    conflicting_month_attestation = sign_monthly_odometer_attestation(
        charger_domain="ruc-demo.charger-test",
        device_id=conflict_probe_device_id,
        month_id="202604",
        odometer_start_m=1_000,
        odometer_end_m=1_601,
        private_key_bytes=_DEVICE_SEED,
    )
    conflict_probe_rejected = client.post(
        "/settlement/month/attest", json=conflicting_month_attestation
    )
    closed = client.post(
        "/settlement/v6/month/close",
        json={"device_id": "dev-v6", "month_id": str(public["month_id"])},
    )

    accepted_body = accepted.json()
    anchored_body = anchored.json()
    attested_body = attested.json()
    attested_retry_body = attested_retry.json()
    close_body = closed.json()
    month_attestation_sha256 = hashlib.sha256(
        canonical_json(month_attestation).encode("utf-8")
    ).hexdigest()
    gates = {
        "receiver_attestation_anchored": (
            anchored.status_code == 200
            and anchored_body.get("attestation_sha256")
            == receiver_attestation_sha256(
                dict(submission["receiver_root_attestation"])
            )
            and anchored_body.get("period_id") == public["period_id"]
        ),
        "canonical_proof_accepted": accepted.status_code == 200,
        "accepted_public_exactly_matches": accepted_body.get("accepted_public") == public,
        "replay_rejected": replay.status_code == 409,
        "tampered_public_signal_rejected": tampered.status_code == 400,
        "month_attestation_online_anchored": (
            attested.status_code == 200
            and attested_body.get("schema")
            == "waybill.charger.month-attestation/v1"
            and attested_body.get("attestation_sha256")
            == month_attestation_sha256
            and attested_body.get("created") is True
            and attested_body.get("idempotent") is False
        ),
        "month_attestation_exact_retry_idempotent": (
            attested_retry.status_code == 200
            and attested_retry_body.get("attestation_sha256")
            == month_attestation_sha256
            and attested_retry_body.get("created") is False
            and attested_retry_body.get("idempotent") is True
        ),
        "month_attestation_conflict_rejected": (
            conflict_probe_registration.status_code == 200
            and conflict_probe_anchor.status_code == 200
            and conflict_probe_rejected.status_code == 409
        ),
        "month_close_completed": closed.status_code == 200 and close_body.get("status") == "closed",
        "only_unaccounted_distance_reconciled": (
            close_body.get("accounted_distance_m") == int(public["total_distance_m"])
            and close_body.get("unaccounted_distance_m") == 600
            and close_body.get("reconciliation_fee_cents") == 600
            * int(profile["max_zone_rate_cents_per_m"])
        ),
        "nonzero_profile_commitment": int(public["policy_profile_commitment"]) != 0,
        "independent_receiver_attestation": (
            submission.get("receiver_attestation_mode") == "independent-receiver-process"
            and submission["receiver_root_attestation"].get("commitment_semantics")
            == "receiver-fix-validity-v2"
            and submission["receiver_root_attestation"].get("schema")
            == "waybill.receiver.root-attestation/v5"
            and submission["receiver_root_attestation"].get("position_validity_rule")
            == "origin-osnma-authenticated-v1"
            and submission["receiver_root_attestation"].get("charger_domain")
            == "ruc-demo.charger-test"
            and isinstance(submission.get("receiver_monthly_odometer_attestation"), dict)
        ),
    }
    result: dict[str, object] = {
        "schema": "waybill-m1-v6-charger-endpoint-gate-v3",
        "status": "verified" if all(gates.values()) else "failed",
        "hard_gate_passed": all(gates.values()),
        "gates": gates,
        "http_status": {
            "anchor": anchored.status_code,
            "accepted": accepted.status_code,
            "replay": replay.status_code,
            "tampered_signal": tampered.status_code,
            "month_attestation": attested.status_code,
            "month_attestation_retry": attested_retry.status_code,
            "month_attestation_conflict_probe_registration": (
                conflict_probe_registration.status_code
            ),
            "month_attestation_conflict_probe_anchor": conflict_probe_anchor.status_code,
            "month_attestation_conflict": conflict_probe_rejected.status_code,
            "month_close": closed.status_code,
        },
        "receiver_chain_head": {
            "log_epoch": anchored_body.get("log_epoch"),
            "attestation_sha256": anchored_body.get("attestation_sha256"),
            "previous_attestation_sha256": anchored_body.get(
                "previous_attestation_sha256"
            ),
        },
        "month_attestation_anchor": {
            "attestation_sha256": attested_body.get("attestation_sha256"),
            "created": attested_body.get("created"),
            "retry_idempotent": attested_retry_body.get("idempotent"),
            "conflict_probe_device_id": conflict_probe_device_id,
            "conflict_status": conflict_probe_rejected.status_code,
        },
        "accepted": {
            "period_id": accepted_body.get("period_id"),
            "total_fee_cents": public["total_fee_cents"],
            "total_distance_m": public["total_distance_m"],
            "fallback_intervals": public["fallback_intervals"],
            "policy_profile_commitment": public["policy_profile_commitment"],
        },
        "month_close": close_body,
        "artifact_sha256": {
            name: _sha256(ARTIFACT_DIR / name)
            for name in (
                "verification_key.json",
                "proof.json",
                "public.json",
                "submission.json",
            )
        },
        "policy_artifact_sha256": {
            name: _sha256(PROFILE_REGISTRY_DIR / name)
            for name in ("ruc-demo-v9.json", "ruc-demo-tariff-v9-d8.json")
        },
        "code_sha256": {
            str(path.relative_to(ROOT_DIR)): _sha256(path)
            for path in (
                ROOT_DIR / "common/policy_profile.py",
                ROOT_DIR / "common/http_security.py",
                ROOT_DIR / "common/receiver_signer.py",
                ROOT_DIR / "common/settlement.py",
                ROOT_DIR / "common/settlement_v6.py",
                ROOT_DIR / "script/prove_settlement_period_v6.py",
                ROOT_DIR / "script/run_waybill_m1_endpoint_gate.py",
                ROOT_DIR / "services/charger/app.py",
                ROOT_DIR / "services/charger/store.py",
                ROOT_DIR / "services/receiver_signer/app.py",
            )
        },
    }
    output = ARTIFACT_DIR / "charger_endpoint_receipt.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data_gate_path = ARTIFACT_DIR.parent / "summary.json"
    data_gate = (
        json.loads(data_gate_path.read_text(encoding="utf-8"))
        if data_gate_path.is_file()
        else None
    )
    circuit_gate = json.loads((ARTIFACT_DIR / "receipt.json").read_text(encoding="utf-8"))
    combined_gates = {
        "canonical_profile_bound_circuit": (
            circuit_gate.get("ok") is True
            and circuit_gate.get("canonical_profile_bound") is True
            and circuit_gate.get("circuit_python_differential_match") is True
            and circuit_gate.get("commitment_semantics") == "receiver-fix-validity-v2"
            and circuit_gate.get("receiver_attestation_schema")
            == "waybill.receiver.root-attestation/v5"
            and circuit_gate.get("position_validity_rule")
            == "origin-osnma-authenticated-v1"
            and circuit_gate.get("receiver_attestation_mode")
            == "independent-receiver-process"
            and circuit_gate.get("receiver_chain_mode")
            == "charger-online-cas-v1"
            and len(str(circuit_gate.get("receiver_attestation_sha256", "")))
            == 64
        ),
        "production_charger_endpoint_gate": result["hard_gate_passed"] is True,
    }
    combined = {
        "schema": "waybill-m1-combined-gate/v2",
        "status": "verified" if all(combined_gates.values()) else "failed",
        "hard_gate_passed": all(combined_gates.values()),
        "gates": combined_gates,
        "data_gate": {
            "available": data_gate is not None,
            "hard_gate_passed": None if data_gate is None else data_gate.get("hard_gate_passed"),
            "note": (
                "The restricted four-dataset gate is intentionally reported separately and "
                "is not inferred from the cryptographic endpoint artifact."
            ),
        },
        "evidence": {
            "data": "summary.json" if data_gate is not None else None,
            "circuit": "circuit_differential/receipt.json",
            "charger": "circuit_differential/charger_endpoint_receipt.json",
        },
        "conditional_claim": (
            "Verified as a protocol/model result under authenticated, monotone, calibrated "
            "odometer assumptions; this is not receiver/odometer field certification."
        ),
    }
    (ARTIFACT_DIR.parent / "gate_summary.json").write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["hard_gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
