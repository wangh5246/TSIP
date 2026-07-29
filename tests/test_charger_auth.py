from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from common.settlement import sign_monthly_odometer_attestation
from services.charger.app import (
    MAX_CHARGER_REQUEST_BYTES,
    ChargerSettings,
    create_app,
)


ADMIN_TOKEN = "admin-credential-with-more-than-32-characters"
TOKEN_A = "device-a-credential-with-more-than-32-characters"
TOKEN_B = "device-b-credential-with-more-than-32-characters"
DOMAIN = "ruc-demo.charger-auth-test"


def _settings(tmp_path: Path, *, enable_reset: bool = False) -> ChargerSettings:
    return ChargerSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'auth.sqlite'}",
        charger_domain=DOMAIN,
        admin_token=ADMIN_TOKEN,
        token_pepper="token-pepper-with-more-than-32-characters",
        test_mode=False,
        allow_transparent_endpoints=False,
        enable_reset=enable_reset,
        allow_sqlite_backend_for_tests=True,
    )


def _admin() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _device(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_production_settings_fail_closed_when_secrets_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "WAYBILL_CHARGER_DATABASE_URL",
        "WAYBILL_CHARGER_DOMAIN",
        "WAYBILL_CHARGER_ADMIN_TOKEN",
        "WAYBILL_CHARGER_TOKEN_PEPPER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("WAYBILL_CHARGER_TEST_MODE", raising=False)
    with pytest.raises(RuntimeError, match="are required"):
        ChargerSettings.from_environment()


def test_production_settings_cannot_enable_destructive_reset(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="destructive reset endpoint"):
        _settings(tmp_path, enable_reset=True)


def test_production_settings_require_postgresql_and_independent_secrets(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="requires a PostgreSQL"):
        ChargerSettings(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'forbidden.sqlite'}",
            charger_domain=DOMAIN,
            admin_token=ADMIN_TOKEN,
            token_pepper="independent-token-pepper-with-more-than-32-characters",
        )
    with pytest.raises(ValueError, match="must be independent"):
        ChargerSettings(
            database_url="postgresql+psycopg://waybill:test@127.0.0.1/waybill",
            charger_domain=DOMAIN,
            admin_token=ADMIN_TOKEN,
            token_pepper=ADMIN_TOKEN,
        )


def test_admin_and_device_authorization_matrix_and_domain_binding(tmp_path: Path) -> None:
    seed_a = hashlib.sha256(b"charger-auth-device-a").digest()
    seed_b = hashlib.sha256(b"charger-auth-device-b").digest()
    public_a = Ed25519PrivateKey.from_private_bytes(seed_a).public_key().public_bytes_raw()
    public_b = Ed25519PrivateKey.from_private_bytes(seed_b).public_key().public_bytes_raw()
    application = create_app(_settings(tmp_path))
    with TestClient(application) as client:
        duplicate = client.post(
            "/settlement/devices/register",
            content=b'{"device_id":"a","device_id":"b"}',
            headers={**_admin(), "Content-Type": "application/json"},
        )
        assert duplicate.status_code == 400
        assert duplicate.json() == {"detail": "invalid JSON request body"}
        oversized = client.post(
            "/settlement/devices/register",
            content=b"x" * (MAX_CHARGER_REQUEST_BYTES + 1),
            headers={**_admin(), "Content-Type": "application/json"},
        )
        assert oversized.status_code == 413
        assert client.get("/health").json() == {
            "ok": True,
            "service": "charger",
            "storage": "available",
        }
        registration_a = {
            "device_id": "device-a",
            "public_key_hex": public_a.hex(),
            "jurisdiction_id": "ruc-demo",
            "device_token": TOKEN_A,
        }
        assert client.post("/settlement/devices/register", json=registration_a).status_code == 401
        assert client.post(
            "/settlement/devices/register", json=registration_a, headers=_admin()
        ).status_code == 200
        assert client.post(
            "/settlement/devices/register",
            json={
                "device_id": "device-b",
                "public_key_hex": public_b.hex(),
                "jurisdiction_id": "ruc-demo",
                "device_token": TOKEN_B,
            },
            headers=_admin(),
        ).status_code == 200
        reused_token = client.post(
            "/settlement/devices/register",
            json={
                "device_id": "device-c",
                "public_key_hex": public_b.hex(),
                "jurisdiction_id": "ruc-demo",
                "device_token": TOKEN_A,
            },
            headers=_admin(),
        )
        assert reused_token.status_code == 409

        admin_reuse = client.post(
            "/settlement/devices/register",
            json={
                "device_id": "device-d",
                "public_key_hex": public_b.hex(),
                "jurisdiction_id": "ruc-demo",
                "device_token": ADMIN_TOKEN,
            },
            headers=_admin(),
        )
        assert admin_reuse.status_code == 400

        attestation = sign_monthly_odometer_attestation(
            charger_domain=DOMAIN,
            device_id="device-a",
            month_id="2026-05",
            odometer_start_m=0,
            odometer_end_m=100,
            private_key_bytes=seed_a,
        )
        assert client.post("/settlement/month/attest", json=attestation).status_code == 401
        assert client.post(
            "/settlement/month/attest", json=attestation, headers=_device(TOKEN_B)
        ).status_code == 403
        assert client.post(
            "/settlement/month/attest", json=attestation, headers=_device(TOKEN_A)
        ).status_code == 200

        cross_domain = sign_monthly_odometer_attestation(
            charger_domain="ruc-demo.charger-other",
            device_id="device-b",
            month_id="2026-05",
            odometer_start_m=0,
            odometer_end_m=100,
            private_key_bytes=seed_b,
        )
        rejected = client.post(
            "/settlement/month/attest", json=cross_domain, headers=_device(TOKEN_B)
        )
        assert rejected.status_code == 400
        assert "attestation rejected" in rejected.json()["detail"]

        assert client.get("/settlement/month/2026-05").status_code == 401
        assert client.get(
            "/settlement/month/2026-05", headers=_admin()
        ).status_code == 200
        assert client.post("/settlement/reset", headers=_admin()).status_code == 404
        assert client.post("/settlement/v6/period", json={}).status_code == 404
    application.state.charger_store.close()


def test_unexpected_database_error_is_redacted_and_maps_to_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(_settings(tmp_path))

    def fail_ping() -> None:
        raise SQLAlchemyError("sensitive database detail")

    monkeypatch.setattr(application.state.charger_store, "ping", fail_ping)
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Charger persistence is unavailable"}
    assert "sensitive" not in response.text
    application.state.charger_store.close()
