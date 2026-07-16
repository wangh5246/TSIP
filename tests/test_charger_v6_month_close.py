from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.policy_profile import load_policy_profiles
from common.settlement import (
    ReceiverFix,
    build_period_public_statement,
    make_device_attestation_commitment,
    sign_monthly_odometer_attestation,
    sign_receiver_fix,
)
from script.prove_settlement_period_v5 import build_tariff
from services.charger import app as charger_app


_SEED = hashlib.sha256(b"waybill-v6-month-close-test").digest()
_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_SEED)
_PUBLIC_KEY = _PRIVATE_KEY.public_key().public_bytes_raw()
_DAC = make_device_attestation_commitment(_PUBLIC_KEY)
_MAY_START = 1_777_593_600


@pytest.fixture(autouse=True)
def _canonical_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = load_policy_profiles(ROOT_DIR / "configs" / "settlement_policy_profiles")
    monkeypatch.setattr(charger_app, "policy_registry", registry)


def _client() -> TestClient:
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    response = client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-v6-close",
            "public_key_hex": _PUBLIC_KEY.hex(),
            "jurisdiction_id": "ruc-demo",
        },
    )
    assert response.status_code == 200
    return client


def _fixes(
    period_id: str,
    *,
    start_time: int = _MAY_START + 300,
    odometer_start_m: int = 1_000,
    odometer_end_m: int = 1_070,
) -> list[ReceiverFix]:
    result: list[ReceiverFix] = []
    for seq, (ts, odo, x) in enumerate(
        ((start_time, odometer_start_m, 0), (start_time + 300, odometer_end_m, 1))
    ):
        raw = ReceiverFix(
            device_id="dev-v6-close",
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=ts,
            cell_x=x,
            cell_y=0,
            osnma_status="authenticated",
            odometer_reading_m=odo,
            nonce=f"{period_id}-{seq}",
        )
        result.append(sign_receiver_fix(raw, _SEED))
    return result


def _public(fixes: list[ReceiverFix], *, reveal_total_miles: bool = True) -> dict[str, object]:
    profile = charger_app.policy_registry.profiles[0]
    return build_period_public_statement(
        fixes=fixes,
        tariff=build_tariff(),
        period_id=fixes[0].period_id,
        month_id="2026-05",
        cadence_sec=profile.cadence_sec,
        tier_vmax_mps=profile.tier_vmax_mps,
        max_dt_sec=profile.max_dt_sec,
        device_attestation_commitment=_DAC,
        reveal_total_miles=reveal_total_miles,
        tariff_tree_depth=profile.tariff_tree_depth,
        policy_profile=profile,
    )


def _submit(client: TestClient, fixes: list[ReceiverFix], public: dict[str, object]) -> object:
    tariff = build_tariff()
    return client.post(
        "/settlement/period",
        json={
            "fixes": [fix.to_dict() for fix in fixes],
            "tariff": {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
            },
            "public_statement": public,
        },
    )


def _attest(client: TestClient, *, start_m: int, end_m: int) -> object:
    attestation = sign_monthly_odometer_attestation(
        device_id="dev-v6-close",
        month_id="2026-05",
        odometer_start_m=start_m,
        odometer_end_m=end_m,
        private_key_bytes=_SEED,
    )
    return client.post("/settlement/month/attest", json=attestation)


def test_month_close_is_immutable_idempotent_and_rejects_late_periods() -> None:
    client = _client()
    fixes = _fixes("2026-05-close-p01")
    response = _submit(client, fixes, _public(fixes))
    assert response.status_code == 200, response.text
    assert _attest(client, start_m=1_000, end_m=2_000).status_code == 200

    close = client.post(
        "/settlement/v6/month/close",
        json={"device_id": "dev-v6-close", "month_id": "2026-05"},
    )
    assert close.status_code == 200
    receipt = close.json()
    assert receipt["status"] == "closed"
    assert receipt["accounted_distance_m"] == 70
    assert receipt["unaccounted_distance_m"] == 930
    assert receipt["reconciliation_fee_cents"] == 4_650
    assert receipt["total_month_bill_cents"] == 4_720
    assert receipt["immutable"] is True

    retry = client.post(
        "/settlement/v6/month/close",
        json={"device_id": "dev-v6-close", "month_id": "202605"},
    ).json()
    assert retry["idempotent"] is True
    assert retry["receipt_sha256"] == receipt["receipt_sha256"]

    late = _fixes("2026-05-close-p02", start_time=_MAY_START + 900, odometer_start_m=2_000, odometer_end_m=2_050)
    response = _submit(client, late, _public(late))
    assert response.status_code == 409
    assert "no longer accepts" in response.json()["detail"]


def test_missing_attestation_enters_durable_administrative_path() -> None:
    client = _client()
    response = client.post(
        "/settlement/v6/month/close",
        json={"device_id": "dev-v6-close", "month_id": "2026-05"},
    )
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["status"] == "administrative-exception"
    assert receipt["reason"] == "missing_monthly_odometer_attestation"
    assert receipt["immutable"] is True

    late = _fixes("2026-05-admin-late")
    response = _submit(client, late, _public(late))
    assert response.status_code == 409


def test_hidden_covered_distance_and_cross_month_period_fail_closed() -> None:
    client = _client()
    fixes = _fixes("2026-05-hidden-distance")
    response = _submit(client, fixes, _public(fixes, reveal_total_miles=False))
    assert response.status_code == 400
    assert "total_distance_m is required" in response.json()["detail"]

    crossing = _fixes("2026-05-crossing", start_time=1_780_271_940)
    response = _submit(client, crossing, _public(crossing))
    assert response.status_code == 400
    assert "wholly contained" in response.json()["detail"]


def test_month_close_rejects_accounted_distance_above_attested_delta() -> None:
    client = _client()
    fixes = _fixes("2026-05-over-accounted")
    assert _submit(client, fixes, _public(fixes)).status_code == 200
    assert _attest(client, start_m=1_000, end_m=1_050).status_code == 200

    receipt = client.post(
        "/settlement/v6/month/close",
        json={"device_id": "dev-v6-close", "month_id": "2026-05"},
    ).json()
    assert receipt["status"] == "administrative-exception"
    assert receipt["reason"] == "inconsistent_monthly_odometer_accounting"
    assert "exceeds" in receipt["detail"]
