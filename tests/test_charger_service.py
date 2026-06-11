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

from common.settlement import (
    ReceiverFix,
    TariffTable,
    build_period_public_statement,
    field_from_text,
    make_device_attestation_commitment,
    sign_receiver_root_attestation,
    sign_receiver_fix,
)
from services.charger import app as charger_app

# Same deterministic test key used across settlement tests.
_TEST_SEED = hashlib.sha256(b"tsip-test-device-key-v1").digest()
_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_TEST_SEED)
_TEST_PUBLIC_KEY_BYTES = _TEST_PRIVATE_KEY.public_key().public_bytes_raw()
_TEST_DAC = make_device_attestation_commitment(_TEST_PUBLIC_KEY_BYTES)
_MAY_2026_START = 1_777_593_600


def _fix(seq: int, ts: int, odo: int, x: int, y: int) -> ReceiverFix:
    if ts < _MAY_2026_START:
        ts += _MAY_2026_START
    return sign_receiver_fix(
        ReceiverFix(
            device_id="dev-1",
            period_id="2026-05-p01",
            fix_seq=seq,
            auth_gnss_time=ts,
            cell_x=x,
            cell_y=y,
            osnma_status="authenticated",
            odometer_reading_m=odo,
            nonce=f"nonce-{seq}",
        ),
        _TEST_SEED,
    )


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=7,
        grid_w=2,
        cell_zones={0: 10, 1: 10, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def _register_device(client: TestClient) -> None:
    resp = client.post(
        "/settlement/devices/register",
        json={"device_id": "dev-1", "public_key_hex": _TEST_PUBLIC_KEY_BYTES.hex()},
    )
    assert resp.status_code == 200
    assert resp.json()["device_attestation_commitment"] == _TEST_DAC


def _public_signals(public: dict[str, object]) -> list[str]:
    return [
        str(public["receiver_fix_root"]),
        str(public["tariff_root"]),
        str(public["interval_commitment_root"]),
        str(public["period_id_field"]),
        str(public["tariff_version"]),
        str(field_from_text(str(public["device_attestation_commitment"]))),
        str(public["total_fee_cents"]),
        str(public["total_distance_m"]),
        str(public["fallback_intervals"]),
        str(public["cadence_sec"]),
        str(public["tier_vmax_mps"]),
        str(public["tier_vmax_sq"]),
        str(public["mode_vmax_sq"]),
        str(public["cap_policy_sq"]),
        str(public["max_zone_rate_cents_per_m"]),
        str(public["max_dt_sec"]),
        str(public["period_start_time"]),
        str(public["period_end_time"]),
        str(public["month_id_field"]),
        str(public["month_start_time"]),
        str(public["month_end_time"]),
    ]


def _proof_only_payload(public: dict[str, object]) -> dict[str, object]:
    return {
        "public_statement": public,
        "proof": {},
        "public_signals": _public_signals(public),
        "root_attestation": sign_receiver_root_attestation(
            public_statement=public,
            device_id="dev-1",
            private_key_bytes=_TEST_SEED,
        ),
    }


def test_charger_accepts_period_and_aggregates_month():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    resp = client.post(
        "/settlement/period",
        json={
            "fixes": [f.to_dict() for f in fixes],
            "tariff": {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
            },
            "public_statement": public,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["accepted_public"]["total_fee_cents"] == 70

    month = client.get("/settlement/month/2026-05").json()
    assert month["ok"] is True
    assert month["periods"] == 1
    assert month["total_fee_cents"] == 70
    assert month["total_distance_m"] == 70


def test_charger_rejects_tampered_fee_statement():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    public["total_fee_cents"] = 1
    resp = client.post(
        "/settlement/period",
        json={
            "fixes": [f.to_dict() for f in fixes],
            "tariff": {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
            },
            "public_statement": public,
        },
    )
    assert resp.status_code == 400
    assert "total_fee_cents" in resp.json()["detail"]


def test_charger_rejects_month_window_that_does_not_match_month_id():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_610, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    public["month_start_time"] = 1_774_915_200
    public["month_end_time"] = 1_777_593_600

    resp = client.post(
        "/settlement/period",
        json={
            "fixes": [f.to_dict() for f in fixes],
            "tariff": {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
            },
            "public_statement": public,
        },
    )

    assert resp.status_code == 400
    assert "month window" in resp.json()["detail"]


def test_charger_binds_proof_time_window_public_signals_to_statement():
    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_610, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    signals = ["0"] * 15 + [
        "600",
        str(public["period_start_time"]),
        str(public["period_end_time"]),
        str(public["month_id_field"]),
        str(public["month_start_time"]),
        str(public["month_end_time"]),
    ]

    charger_app._validate_zk_time_signals(public, signals)
    signals[-1] = str(int(signals[-1]) - 1)
    with pytest.raises(ValueError, match="time-window public signals"):
        charger_app._validate_zk_time_signals(public, signals)


def test_charger_accepts_proof_only_period_without_raw_fixes():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_900, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )

    resp = client.post("/settlement/period/proof-only", json=_proof_only_payload(public))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted_public"]["receiver_fix_root"] == public["receiver_fix_root"]
    assert body["accepted_public"]["total_fee_cents"] == public["total_fee_cents"]
    month = client.get("/settlement/month/2026-05").json()
    assert month["periods"] == 1
    assert month["total_fee_cents"] == public["total_fee_cents"]


def test_charger_rejects_proof_only_payload_with_raw_fixes_field():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_900, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    payload = {**_proof_only_payload(public), "fixes": [fix.to_dict() for fix in fixes]}

    resp = client.post("/settlement/period/proof-only", json=payload)

    assert resp.status_code == 422


def test_charger_rejects_proof_only_public_signal_drift():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_900, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    payload = _proof_only_payload(public)
    signals = list(payload["public_signals"])
    signals[0] = str(int(signals[0]) + 1)
    payload["public_signals"] = signals

    resp = client.post("/settlement/period/proof-only", json=payload)

    assert resp.status_code == 400
    assert "public signals" in resp.json()["detail"]


def test_charger_rejects_proof_only_bad_root_attestation():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_900, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=300,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    payload = _proof_only_payload(public)
    payload["root_attestation"] = {**payload["root_attestation"], "signature": "invalid"}

    resp = client.post("/settlement/period/proof-only", json=payload)

    assert resp.status_code == 400
    assert "root attestation" in resp.json()["detail"]


def test_charger_rejects_unregistered_device():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    # Deliberately do NOT register the device.

    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    resp = client.post(
        "/settlement/period",
        json={
            "fixes": [f.to_dict() for f in fixes],
            "tariff": {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
            },
            "public_statement": public,
        },
    )
    assert resp.status_code == 400
    assert "not registered" in resp.json()["detail"]


def test_charger_rejects_wrong_device_attestation_commitment():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    tariff = _tariff()
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id="2026-05-p01",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        # Submit a different (wrong) attestation commitment.
        device_attestation_commitment="wrong-attestation-value",
    )
    resp = client.post(
        "/settlement/period",
        json={
            "fixes": [f.to_dict() for f in fixes],
            "tariff": {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
            },
            "public_statement": public,
        },
    )
    assert resp.status_code == 400
    assert "device_attestation_commitment" in resp.json()["detail"]
