from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from common.policy_profile import PolicyProfile, PolicyRegistry, sha256_file
from common.settlement import ReceiverFix, TariffTable, make_device_attestation_commitment, sign_receiver_fix
from common.settlement_v6 import build_period_public_statement_v6
from services.charger import app as charger_app


ROOT_DIR = Path(__file__).resolve().parents[1]
SEED = hashlib.sha256(b"waybill-v6-charger-period-test").digest()
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(SEED)
PUBLIC_KEY = PRIVATE_KEY.public_key().public_bytes_raw()
DAC = make_device_attestation_commitment(PUBLIC_KEY)
VKEY = ROOT_DIR / "zk/settlement_period_v5_k6/verification_key.json"
MAY_START = 1_777_593_600


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=8,
        grid_w=2,
        cell_zones={0: 10, 1: 20, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def _profile(*, fallback: str = "odometer-max-rate-v6") -> PolicyProfile:
    tariff = _tariff()
    return PolicyProfile(
        authority_id="ruc-v6-test-authority",
        jurisdiction_id="ruc-v6-test",
        profile_version=8,
        valid_from=MAY_START,
        valid_to=MAY_START + 31 * 24 * 3600,
        revoked_at=None,
        min_accepted_version=8,
        tariff_version=tariff.tariff_version,
        tariff_root=tariff.root(2),
        tariff_tree_depth=2,
        max_fixes=25,
        max_zone_rate_cents_per_m=5,
        cadence_sec=300,
        max_dt_sec=600,
        tier_vmax_mps=33,
        tier_vmax_sq=33 * 33,
        mode_vmax_sq=33 * 33,
        cap_policy_sq=3_000_000_000,
        cap_policy_hash="0" * 64,
        circuit_id="settlement-period-v6-k6",
        verification_key_hash=sha256_file(VKEY),
        currency="EUR",
        fixed_point_scale=1,
        rounding_mode="exact-integer",
        overflow_policy="reject-u96",
        monthly_reconciliation_rate_cents_per_m=5,
        fallback_semantics_version=fallback,
        verification_key_path=str(VKEY),
    )


@pytest.fixture(autouse=True)
def _registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry([_profile()]))


def _fix(seq: int, timestamp: int, odometer: int) -> ReceiverFix:
    return sign_receiver_fix(
        ReceiverFix(
            device_id="dev-v6-period",
            period_id="2026-05-v6-period-p1",
            fix_seq=seq,
            auth_gnss_time=timestamp,
            cell_x=0,
            cell_y=0,
            osnma_status="authenticated",
            odometer_reading_m=odometer,
            nonce=f"v6-period-{seq}",
        ),
        SEED,
    )


def _payload(*, position_valid: list[bool], odometer_end: int = 1_070) -> dict[str, object]:
    fixes = [_fix(0, MAY_START + 300, 1_000), _fix(1, MAY_START + 600, odometer_end)]
    profile = charger_app.policy_registry.profiles[0]
    public = build_period_public_statement_v6(
        fixes=fixes,
        tariff=_tariff(),
        position_valid=position_valid,
        period_id=fixes[0].period_id,
        month_id="2026-05",
        cadence_sec=profile.cadence_sec,
        tier_vmax_mps=profile.tier_vmax_mps,
        max_dt_sec=profile.max_dt_sec,
        r_max_cents_per_m=profile.max_zone_rate_cents_per_m,
        device_attestation_commitment=DAC,
        tariff_tree_depth=profile.tariff_tree_depth,
        mode_vmax_sq=profile.mode_vmax_sq,
        cap_policy_sq=profile.cap_policy_sq,
        policy_profile=profile,
    )
    tariff = _tariff()
    return {
        "fixes": [fix.to_dict() for fix in fixes],
        "position_valid": position_valid,
        "tariff": {
            "tariff_version": tariff.tariff_version,
            "grid_w": tariff.grid_w,
            "cell_zones": tariff.cell_zones,
            "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
        },
        "public_statement": public,
    }


def _client() -> TestClient:
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    response = client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-v6-period",
            "public_key_hex": PUBLIC_KEY.hex(),
            "jurisdiction_id": "ruc-v6-test",
        },
    )
    assert response.status_code == 200
    return client


def test_v6_transparent_endpoint_recomputes_outage_bill_and_ledger() -> None:
    client = _client()
    response = client.post("/settlement/v6/period", json=_payload(position_valid=[False]))
    assert response.status_code == 200, response.text
    public = response.json()["accepted_public"]
    assert public["total_distance_m"] == 70
    assert public["total_fee_cents"] == 70 * 5
    assert public["fallback_intervals"] == 1
    month = client.get("/settlement/month/2026-05", params={"device_id": "dev-v6-period"}).json()
    assert month["total_fee_cents"] == 350
    assert month["total_distance_m"] == 70


def test_v6_endpoint_rejects_position_flag_tampering_and_non_boolean_wire_values() -> None:
    client = _client()
    payload = _payload(position_valid=[True])
    payload["position_valid"] = [False]
    response = client.post("/settlement/v6/period", json=payload)
    assert response.status_code == 400
    assert "public statement mismatch" in response.json()["detail"]

    payload = _payload(position_valid=[True])
    payload["position_valid"] = [1]
    response = client.post("/settlement/v6/period", json=payload)
    assert response.status_code == 422


def test_v6_parking_outage_is_zero_and_v5_profile_is_not_accepted() -> None:
    client = _client()
    response = client.post(
        "/settlement/v6/period",
        json=_payload(position_valid=[False], odometer_end=1_000),
    )
    assert response.status_code == 200, response.text
    assert response.json()["accepted_public"]["total_fee_cents"] == 0

    charger_app.policy_registry = PolicyRegistry([_profile(fallback="time-speed-max-rate-v5")])
    client = _client()
    # The statement itself is built with the V5 semantic label in this profile,
    # but the V6 builder and endpoint both fail closed on that mismatch.
    with pytest.raises(ValueError, match="odometer-backed fallback"):
        _payload(position_valid=[False])
