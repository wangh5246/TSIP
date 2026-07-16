#!/usr/bin/env python3
"""Submit the canonical-profile V6 proof through the production charger gates."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT_DIR / "experiments/waybill_m1/v1/circuit_differential"
PROFILE_REGISTRY_DIR = ROOT_DIR / "experiments/waybill_m1/v1/profile_registry"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# The charger loads its authority registry during module import.  Point it at
# the frozen M1 profile directory before importing the app.
os.environ["SETTLEMENT_POLICY_PROFILE_DIR"] = str(PROFILE_REGISTRY_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from common.settlement import sign_monthly_odometer_attestation  # noqa: E402
from script.prove_settlement_period_v6 import (  # noqa: E402
    _DEVICE_PUBLIC_KEY_BYTES,
    _DEVICE_SEED,
)
from services.charger import app as charger_app  # noqa: E402


def _load(name: str) -> object:
    return json.loads((ARTIFACT_DIR / name).read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> dict[str, object]:
    submission = dict(_load("submission.json"))
    proof = dict(_load("proof.json"))
    public_signals = list(_load("public.json"))
    profile = json.loads(
        (PROFILE_REGISTRY_DIR / "policy-profile-v6-k6.json").read_text(encoding="utf-8")
    )
    public = dict(submission["public_statement"])

    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    registration = client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-v6",
            "public_key_hex": _DEVICE_PUBLIC_KEY_BYTES.hex(),
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
    accepted = client.post("/settlement/v6/period/proof-only", json=payload)
    if accepted.status_code != 200:
        raise RuntimeError(f"canonical proof was rejected: {accepted.text}")

    replay = client.post("/settlement/v6/period/proof-only", json=payload)
    tampered_payload = dict(payload)
    tampered_signals = list(public_signals)
    tampered_signals[7] = str(int(tampered_signals[7]) + 1)
    tampered_payload["public_signals"] = tampered_signals
    tampered = client.post("/settlement/v6/period/proof-only", json=tampered_payload)

    fixes = list(submission["fixes"])
    month_attestation = sign_monthly_odometer_attestation(
        device_id="dev-v6",
        month_id=str(public["month_id"]),
        odometer_start_m=int(fixes[0]["odometer_reading_m"]),
        odometer_end_m=int(fixes[-1]["odometer_reading_m"]) + 600,
        private_key_bytes=_DEVICE_SEED,
    )
    attested = client.post("/settlement/month/attest", json=month_attestation)
    closed = client.post(
        "/settlement/v6/month/close",
        json={"device_id": "dev-v6", "month_id": str(public["month_id"])},
    )

    accepted_body = accepted.json()
    close_body = closed.json()
    gates = {
        "canonical_proof_accepted": accepted.status_code == 200,
        "accepted_public_exactly_matches": accepted_body.get("accepted_public") == public,
        "replay_rejected": replay.status_code == 409,
        "tampered_public_signal_rejected": tampered.status_code == 400,
        "month_attestation_accepted": attested.status_code == 200,
        "month_close_completed": closed.status_code == 200 and close_body.get("status") == "closed",
        "only_unaccounted_distance_reconciled": (
            close_body.get("accounted_distance_m") == int(public["total_distance_m"])
            and close_body.get("unaccounted_distance_m") == 600
            and close_body.get("reconciliation_fee_cents") == 600
            * int(profile["max_zone_rate_cents_per_m"])
        ),
        "nonzero_profile_commitment": int(public["policy_profile_commitment"]) != 0,
    }
    result: dict[str, object] = {
        "schema": "waybill-m1-v6-charger-endpoint-gate-v1",
        "status": "verified" if all(gates.values()) else "failed",
        "hard_gate_passed": all(gates.values()),
        "gates": gates,
        "http_status": {
            "accepted": accepted.status_code,
            "replay": replay.status_code,
            "tampered_signal": tampered.status_code,
            "month_attestation": attested.status_code,
            "month_close": closed.status_code,
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
                "policy-profile-v6-k6.json",
                "tariff-v8-d8.json",
                "verification_key.json",
                "proof.json",
                "public.json",
                "submission.json",
            )
        },
        "code_sha256": {
            str(path.relative_to(ROOT_DIR)): _sha256(path)
            for path in (
                ROOT_DIR / "common/policy_profile.py",
                ROOT_DIR / "common/settlement_v6.py",
                ROOT_DIR / "script/run_waybill_m1_endpoint_gate.py",
                ROOT_DIR / "services/charger/app.py",
            )
        },
    }
    output = ARTIFACT_DIR / "charger_endpoint_receipt.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data_gate = json.loads((ARTIFACT_DIR.parent / "summary.json").read_text(encoding="utf-8"))
    circuit_gate = json.loads((ARTIFACT_DIR / "receipt.json").read_text(encoding="utf-8"))
    combined_gates = {
        "data_and_property_gate": data_gate.get("hard_gate_passed") is True,
        "canonical_profile_bound_circuit": (
            circuit_gate.get("ok") is True
            and circuit_gate.get("canonical_profile_bound") is True
            and circuit_gate.get("circuit_python_differential_match") is True
        ),
        "production_charger_endpoint_gate": result["hard_gate_passed"] is True,
        "formal_property_note_present": (ARTIFACT_DIR.parent / "formal_properties.md").is_file(),
    }
    combined = {
        "schema": "waybill-m1-combined-gate/v1",
        "status": "verified" if all(combined_gates.values()) else "failed",
        "hard_gate_passed": all(combined_gates.values()),
        "gates": combined_gates,
        "evidence": {
            "data": "summary.json",
            "formal_properties": "formal_properties.md",
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
