from __future__ import annotations

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from common.settlement import (
    SETTLEMENT_FIX_COMMITMENT_SEMANTICS,
    SETTLEMENT_POSITION_VALIDITY_RULE,
    SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    canonical_json,
    make_device_attestation_commitment,
    receiver_root_attestation_payload,
)
from services.charger import app as charger_app
from services.charger.app import ChargerSettings, create_app
from services.charger.store import (
    ChargerConflict,
    ChargerStore,
)


DOMAIN = "ruc-demo.receiver-chain-test"
ADMIN_TOKEN = "receiver-chain-admin-token-0000000000000000"
DEVICE_TOKEN = "receiver-chain-device-token-000000000000000"
TOKEN_PEPPER = "receiver-chain-pepper-0000000000000000000"
SEED = hashlib.sha256(b"receiver-chain-anchor-test-key").digest()
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(SEED)
PUBLIC_KEY = PRIVATE_KEY.public_key().public_bytes_raw()
DAC = make_device_attestation_commitment(PUBLIC_KEY)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _settings(tmp_path: Path) -> ChargerSettings:
    return ChargerSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'receiver-chain.sqlite'}",
        charger_domain=DOMAIN,
        admin_token=ADMIN_TOKEN,
        token_pepper=TOKEN_PEPPER,
        test_mode=False,
        allow_transparent_endpoints=False,
        enable_reset=False,
        allow_sqlite_backend_for_tests=True,
    )


def test_production_settings_cannot_enable_transparent_endpoints(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="require explicit Charger test mode"):
        ChargerSettings(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'forbidden.sqlite'}",
            charger_domain=DOMAIN,
            admin_token=ADMIN_TOKEN,
            token_pepper=TOKEN_PEPPER,
            test_mode=False,
            allow_transparent_endpoints=True,
            enable_reset=False,
            allow_sqlite_backend_for_tests=True,
        )


def test_production_environment_toggle_cannot_enable_transparent_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "WAYBILL_CHARGER_DATABASE_URL",
        "postgresql+psycopg://waybill:test@127.0.0.1/waybill",
    )
    monkeypatch.setenv("WAYBILL_CHARGER_DOMAIN", DOMAIN)
    monkeypatch.setenv("WAYBILL_CHARGER_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("WAYBILL_CHARGER_TOKEN_PEPPER", TOKEN_PEPPER)
    monkeypatch.setenv("WAYBILL_CHARGER_TEST_MODE", "0")
    monkeypatch.setenv("WAYBILL_CHARGER_ALLOW_TRANSPARENT_ENDPOINTS", "1")

    settings = ChargerSettings.from_environment()

    assert settings.test_mode is False
    assert settings.allow_transparent_endpoints is False


def _register(client: TestClient) -> None:
    response = client.post(
        "/settlement/devices/register",
        headers=_headers(ADMIN_TOKEN),
        json={
            "device_id": "device-1",
            "public_key_hex": PUBLIC_KEY.hex(),
            "jurisdiction_id": "ruc-demo",
            "device_token": DEVICE_TOKEN,
        },
    )
    assert response.status_code == 200, response.text


def _attestation(
    *,
    epoch: int,
    previous: str,
    period_id: str,
    receiver_fix_root: str | int,
    fix_count: int = 25,
) -> dict[str, object]:
    wire: dict[str, object] = {
        "schema": SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
        "receiver_id": "receiver-1",
        "charger_domain": DOMAIN,
        "device_id": "device-1",
        "period_id": period_id,
        "log_epoch": epoch,
        "fix_count": fix_count,
        "receiver_fix_root": str(receiver_fix_root),
        "device_attestation_commitment": DAC,
        "commitment_semantics": SETTLEMENT_FIX_COMMITMENT_SEMANTICS,
        "position_validity_rule": SETTLEMENT_POSITION_VALIDITY_RULE,
        "previous_attestation_sha256": previous,
        "log_sha256": hashlib.sha256(f"log:{period_id}".encode()).hexdigest(),
    }
    signature = PRIVATE_KEY.sign(
        canonical_json(
            receiver_root_attestation_payload(attestation=wire)
        ).encode("utf-8")
    )
    wire["signature"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return wire


def test_anchor_accepts_frozen_matrix_max_but_rejects_larger_attestation(
    tmp_path: Path,
) -> None:
    assert charger_app.PeriodSubmission.model_json_schema()["properties"]["fixes"][
        "maxItems"
    ] == 25
    assert charger_app.RootAttestation.model_json_schema()["properties"]["fix_count"][
        "maximum"
    ] == 200
    application = create_app(_settings(tmp_path))
    matrix_max = _attestation(
        epoch=1,
        previous=SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
        period_id="period-200-fixes",
        receiver_fix_root=200,
        fix_count=charger_app.ROOT_ATTESTATION_FIX_CAP,
    )
    above_matrix = _attestation(
        epoch=2,
        previous="1" * 64,
        period_id="period-201-fixes",
        receiver_fix_root=201,
        fix_count=charger_app.ROOT_ATTESTATION_FIX_CAP + 1,
    )

    with TestClient(application) as client:
        _register(client)
        accepted = client.post(
            "/settlement/receiver-chain/anchor",
            json={"root_attestation": matrix_max},
            headers=_headers(DEVICE_TOKEN),
        )
        assert accepted.status_code == 200, accepted.text

        rejected = client.post(
            "/settlement/receiver-chain/anchor",
            json={"root_attestation": above_matrix},
            headers=_headers(DEVICE_TOKEN),
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"][0]["loc"][-1] == "fix_count"

    application.state.charger_store.close()


def _public(period_id: str, receiver_fix_root: str | int) -> dict[str, object]:
    return {
        "period_id": period_id,
        "month_id": "2026-05",
        "period_start_time": 1_777_593_600,
        "period_end_time": 1_777_593_900,
        "receiver_fix_root": str(receiver_fix_root),
        "device_attestation_commitment": DAC,
        "total_fee_cents": 70,
        "total_distance_m": 70,
        "fallback_intervals": 0,
        "max_zone_rate_cents_per_m": 5,
        "policy_profile_commitment": "17",
    }


def test_device_authenticated_head_genesis_anchor_idempotency_and_fork(
    tmp_path: Path,
) -> None:
    application = create_app(_settings(tmp_path))
    with TestClient(application) as client:
        _register(client)
        head_path = "/settlement/devices/device-1/receiver-head"
        assert client.get(head_path).status_code == 401
        genesis = client.get(head_path, headers=_headers(DEVICE_TOKEN))
        assert genesis.status_code == 200
        assert genesis.json()["schema"] == "waybill.charger.receiver-head/v1"
        assert genesis.json()["log_epoch"] == 0
        assert (
            genesis.json()["previous_attestation_sha256"]
            == SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256
        )
        assert (
            genesis.json()["attestation_sha256"]
            == SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256
        )

        first = _attestation(
            epoch=1,
            previous=SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
            period_id="period-1",
            receiver_fix_root=101,
        )
        anchor_path = "/settlement/receiver-chain/anchor"
        body = {"root_attestation": first}
        assert client.post(anchor_path, json=body).status_code == 401
        anchored = client.post(
            anchor_path, json=body, headers=_headers(DEVICE_TOKEN)
        )
        assert anchored.status_code == 200, anchored.text
        assert anchored.json()["schema"] == "waybill.charger.receiver-head/v1"
        assert anchored.json()["idempotent"] is False
        assert (
            anchored.json()["previous_attestation_sha256"]
            == SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256
        )

        replay = client.post(
            anchor_path, json=body, headers=_headers(DEVICE_TOKEN)
        )
        assert replay.status_code == 200
        assert replay.json()["idempotent"] is True
        assert replay.json()["attestation_sha256"] == anchored.json()[
            "attestation_sha256"
        ]

        current = client.get(head_path, headers=_headers(DEVICE_TOKEN)).json()
        assert current["log_epoch"] == 1
        assert current["attestation_sha256"] == anchored.json()[
            "attestation_sha256"
        ]

        fork = _attestation(
            epoch=2,
            previous="1" * 64,
            period_id="period-fork",
            receiver_fix_root=202,
        )
        rejected = client.post(
            anchor_path,
            json={"root_attestation": fork},
            headers=_headers(DEVICE_TOKEN),
        )
        assert rejected.status_code == 409
        assert "head hash" in rejected.json()["detail"]
    application.state.charger_store.close()


def test_concurrent_children_use_compare_and_swap_and_exact_winner_retries(
    tmp_path: Path,
) -> None:
    store = ChargerStore(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cas.sqlite'}",
        charger_domain=DOMAIN,
    )
    store.register_device(
        device_id="device-1",
        public_key=PUBLIC_KEY,
        jurisdiction_id="ruc-demo",
        token_digest="a" * 64,
    )
    first = store.anchor_receiver_attestation(
        attestation=_attestation(
            epoch=1,
            previous=SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
            period_id="period-1",
            receiver_fix_root=101,
        )
    )
    children = [
        _attestation(
            epoch=2,
            previous=str(first["attestation_sha256"]),
            period_id=f"period-child-{index}",
            receiver_fix_root=200 + index,
        )
        for index in range(2)
    ]

    def anchor(child: dict[str, object]) -> tuple[str, dict[str, object]]:
        try:
            return "accepted", store.anchor_receiver_attestation(attestation=child)
        except ChargerConflict:
            return "conflict", child

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(anchor, children))
    assert [status for status, _result in results].count("accepted") == 1
    assert [status for status, _result in results].count("conflict") == 1
    winner = next(result for status, result in results if status == "accepted")
    replay = store.anchor_receiver_attestation(
        attestation=next(
            child
            for child in children
            if child["period_id"] == winner["period_id"]
        )
    )
    assert replay["idempotent"] is True
    assert store.receiver_head(device_id="device-1")["attestation_sha256"] == winner[
        "attestation_sha256"
    ]
    store.close()


def test_proof_only_rejects_unanchored_attestation_and_atomically_settles_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(_settings(tmp_path))
    root = _attestation(
        epoch=1,
        previous=SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
        period_id="period-proof",
        receiver_fix_root=303,
        fix_count=charger_app.ROOT_ATTESTATION_FIX_CAP,
    )
    public = _public("period-proof", 303)
    profile = SimpleNamespace(
        monthly_reconciliation_rate_cents_per_m=5,
        max_zone_rate_cents_per_m=5,
        max_fixes=charger_app.ROOT_ATTESTATION_FIX_CAP,
        fallback_semantics_version="odometer-max-rate-v6",
        circuit_id="settlement-period-v6-chain-test",
    )
    monkeypatch.setattr(
        charger_app,
        "_resolve_expected_profile",
        lambda _store, _device_id, _public: profile,
    )
    monkeypatch.setattr(
        charger_app, "_validate_public_statement_shape", lambda _public: None
    )
    monkeypatch.setattr(
        charger_app,
        "_validate_zk_public_signals",
        lambda _public, _signals: None,
    )
    monkeypatch.setattr(
        charger_app,
        "_validate_zk_public_signals_v6",
        lambda _public, _signals: None,
    )
    proof_calls: list[str] = []
    monkeypatch.setattr(
        charger_app,
        "_verify_zk_proof",
        lambda _proof, _signals, _path: proof_calls.append("verified"),
    )
    monkeypatch.setattr(charger_app, "_profile_vkey_path", lambda _profile: Path("unused"))

    payload = {
        "public_statement": public,
        "proof": {},
        "public_signals": [],
        "root_attestation": root,
    }
    with TestClient(application) as client:
        _register(client)
        unanchored = client.post(
            "/settlement/period/proof-only",
            json=payload,
            headers=_headers(DEVICE_TOKEN),
        )
        assert unanchored.status_code == 409
        assert "not anchored" in unanchored.json()["detail"]
        assert proof_calls == []

        v6_payload = {
            **payload,
            "public_statement": {
                **public,
                "domain_sep": charger_app.SETTLEMENT_PUBLIC_V6_DOMAIN,
            },
        }
        v6_unanchored = client.post(
            "/settlement/v6/period/proof-only",
            json=v6_payload,
            headers=_headers(DEVICE_TOKEN),
        )
        assert v6_unanchored.status_code == 409
        assert "not anchored" in v6_unanchored.json()["detail"]
        assert proof_calls == []

        anchored = client.post(
            "/settlement/receiver-chain/anchor",
            json={"root_attestation": root},
            headers=_headers(DEVICE_TOKEN),
        )
        assert anchored.status_code == 200, anchored.text
        accepted = client.post(
            "/settlement/v6/period/proof-only",
            json=v6_payload,
            headers=_headers(DEVICE_TOKEN),
        )
        assert accepted.status_code == 200, accepted.text
        assert proof_calls == ["verified"]
        settled = client.post(
            "/settlement/v6/period/proof-only",
            json=v6_payload,
            headers=_headers(DEVICE_TOKEN),
        )
        assert settled.status_code == 409
        assert "already been settled" in settled.json()["detail"]
        assert proof_calls == ["verified"]
        replay = client.post(
            "/settlement/receiver-chain/anchor",
            json={"root_attestation": root},
            headers=_headers(DEVICE_TOKEN),
        )
        assert replay.status_code == 200
        assert replay.json()["settled"] is True
    application.state.charger_store.close()


def test_final_acceptance_rechecks_anchor_after_preflight_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(_settings(tmp_path))
    root = _attestation(
        epoch=1,
        previous=SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
        period_id="period-race",
        receiver_fix_root=404,
    )
    public = _public("period-race", 404)
    profile = SimpleNamespace(
        monthly_reconciliation_rate_cents_per_m=5,
        max_zone_rate_cents_per_m=5,
        max_fixes=25,
        fallback_semantics_version="odometer-max-rate-v6",
        circuit_id="settlement-period-v6-chain-test",
    )
    monkeypatch.setattr(
        charger_app,
        "_resolve_expected_profile",
        lambda _store, _device_id, _public: profile,
    )
    monkeypatch.setattr(
        charger_app, "_validate_public_statement_shape", lambda _public: None
    )
    monkeypatch.setattr(
        charger_app,
        "_validate_zk_public_signals",
        lambda _public, _signals: None,
    )
    monkeypatch.setattr(
        charger_app, "_profile_vkey_path", lambda _profile: Path("unused")
    )
    proof_calls: list[str] = []

    def settle_between_preflight_and_final_accept(
        _proof: dict[str, object], _signals: list[str], _path: str
    ) -> None:
        proof_calls.append("verified")
        application.state.charger_store.accept_period(
            device_id="device-1",
            public=public,
            month_number=202605,
            reconciliation_rate_cents_per_m=5,
            root_attestation=root,
        )

    monkeypatch.setattr(
        charger_app,
        "_verify_zk_proof",
        settle_between_preflight_and_final_accept,
    )
    payload = {
        "public_statement": public,
        "proof": {},
        "public_signals": [],
        "root_attestation": root,
    }

    with TestClient(application) as client:
        _register(client)
        anchored = client.post(
            "/settlement/receiver-chain/anchor",
            json={"root_attestation": root},
            headers=_headers(DEVICE_TOKEN),
        )
        assert anchored.status_code == 200, anchored.text

        response = client.post(
            "/settlement/period/proof-only",
            json=payload,
            headers=_headers(DEVICE_TOKEN),
        )

        assert response.status_code == 409
        assert "already been settled" in response.json()["detail"]
        assert proof_calls == ["verified"]
    application.state.charger_store.close()
