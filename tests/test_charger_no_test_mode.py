"""Charger must enforce authentication and anchoring with test mode off.

The V14 S5 handler units ran with ``WAYBILL_CHARGER_TEST_MODE=1``, which
silently bypassed device authentication (the token was derivable from the
public device id) and disabled root-attestation anchoring, so the S5 evidence
could not support any authentication claim.  These tests pin the hardened
path: a production-mode ChargerSettings with the SQLite ledger explicitly
acknowledged, driven end-to-end with the real M1 circuit-differential fixture
and real snarkjs verification.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from common.policy_profile import PolicyProfile, PolicyRegistry
from services.charger import app as charger_app
from services.charger.app import ChargerSettings, create_app

ROOT_DIR = Path(__file__).resolve().parents[1]
DIFF_DIR = ROOT_DIR / "experiments/waybill_m1/v2/circuit_differential"
ADMIN_TOKEN = "a" * 40
TOKEN_PEPPER = "p" * 40
DEVICE_TOKEN = "d" * 40


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _device_headers(token: str = DEVICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def hardened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A production-mode charger app bound to the differential fixture profile."""

    submission = json.loads((DIFF_DIR / "submission.json").read_text(encoding="utf-8"))
    profile = PolicyProfile.from_dict(submission["policy_profile"])
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry([profile]))
    settings = ChargerSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'charger.sqlite'}",
        charger_domain="ruc-demo.charger-test",
        admin_token=ADMIN_TOKEN,
        token_pepper=TOKEN_PEPPER,
        test_mode=False,
        allow_sqlite_backend_for_tests=True,
    )
    return create_app(settings), submission


def _register(client: TestClient, submission: dict[str, Any], token: str) -> None:
    response = client.post(
        "/settlement/devices/register",
        headers=_admin_headers(),
        json={
            "device_id": submission["receiver_root_attestation"]["device_id"],
            "public_key_hex": submission["receiver_public_key_hex"],
            "jurisdiction_id": "ruc-demo",
            "device_token": token,
        },
    )
    assert response.status_code == 200, response.text


def _anchor(client: TestClient, submission: dict[str, Any], token: str) -> None:
    response = client.post(
        "/settlement/receiver-chain/anchor",
        headers=_device_headers(token),
        json={"root_attestation": submission["receiver_root_attestation"]},
    )
    assert response.status_code == 200, response.text


def _submission_body(submission: dict[str, Any]) -> dict[str, Any]:
    receipt = json.loads(
        (DIFF_DIR / "receipt.json").read_text(encoding="utf-8")
    )
    return {
        "public_statement": submission["public_statement"],
        "proof": json.loads((DIFF_DIR / "proof.json").read_text(encoding="utf-8")),
        "public_signals": receipt["public_signals"],
        "root_attestation": submission["receiver_root_attestation"],
    }


def test_proof_only_accepts_authenticated_anchored_submission(hardened) -> None:
    """The happy path: bearer token + enforced anchor + real Groth16 verify."""

    application, submission = hardened
    client = TestClient(application)
    _register(client, submission, DEVICE_TOKEN)
    _anchor(client, submission, DEVICE_TOKEN)

    response = client.post(
        "/settlement/v6/period/proof-only",
        headers=_device_headers(),
        json=_submission_body(submission),
    )
    assert response.status_code == 200, response.text
    accepted = response.json()["accepted_public"]
    assert accepted["period_id"] == submission["public_statement"]["period_id"]
    # The transparent/reset endpoints must not even exist without test mode.
    assert application.url_path_for  # sanity: app exists
    transparent = client.post(
        "/settlement/v6/period",
        json={"device_id": "x", "period": {}, "tariff": {}},
    )
    assert transparent.status_code in (401, 404)


def test_proof_only_rejects_missing_device_token(hardened) -> None:
    application, submission = hardened
    client = TestClient(application)
    _register(client, submission, DEVICE_TOKEN)
    _anchor(client, submission, DEVICE_TOKEN)

    response = client.post(
        "/settlement/v6/period/proof-only",
        json=_submission_body(submission),
    )
    assert response.status_code == 401, response.text
    assert "device credential" in response.json()["detail"]


def test_proof_only_rejects_wrong_device_token(hardened) -> None:
    application, submission = hardened
    client = TestClient(application)
    _register(client, submission, DEVICE_TOKEN)
    _anchor(client, submission, DEVICE_TOKEN)

    response = client.post(
        "/settlement/v6/period/proof-only",
        headers=_device_headers("e" * 40),
        json=_submission_body(submission),
    )
    assert response.status_code == 403, response.text


def test_proof_only_rejects_unanchored_submission(hardened) -> None:
    """The V14 test-mode hole: a valid proof with no anchor must be rejected."""

    application, submission = hardened
    client = TestClient(application)
    _register(client, submission, DEVICE_TOKEN)
    # No anchor call on purpose.

    response = client.post(
        "/settlement/v6/period/proof-only",
        headers=_device_headers(),
        json=_submission_body(submission),
    )
    # The anchor preflight rejects a missing attestation as a conflict before
    # any Groth16 work is spent.
    assert response.status_code == 409, response.text
    assert "not anchored" in response.json()["detail"]


def test_registration_rejects_weak_and_foreign_device_tokens(hardened) -> None:
    application, submission = hardened
    client = TestClient(application)
    device_id = submission["receiver_root_attestation"]["device_id"]
    base = {
        "device_id": device_id,
        "public_key_hex": submission["receiver_public_key_hex"],
        "jurisdiction_id": "ruc-demo",
    }

    # A token derived from public data (the V14 test-mode shape) must be
    # rejected even though it clears the length floor: a credential that is
    # derivable from the public registration body is not a credential.
    short = client.post(
        "/settlement/devices/register",
        headers=_admin_headers(),
        json={**base, "device_token": f"waybill-test-device-token:{device_id}"},
    )
    assert short.status_code == 400, short.text
    assert "derivable from the device id" in short.json()["detail"]

    # The device token must not reuse an administrator secret.
    admin_copy = client.post(
        "/settlement/devices/register",
        headers=_admin_headers(),
        json={**base, "device_token": ADMIN_TOKEN},
    )
    assert admin_copy.status_code == 400, admin_copy.text


def test_missing_token_is_only_rejected_outside_test_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Built-in falsification for the hardened tests above.

    The same request that earns a 401 under production mode must *not* earn a
    401 under test mode -- otherwise the 401 assertions above would pass for
    the wrong reason (e.g. a malformed body) and prove nothing.
    """

    submission = json.loads((DIFF_DIR / "submission.json").read_text(encoding="utf-8"))
    profile = PolicyProfile.from_dict(submission["policy_profile"])
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry([profile]))
    settings = ChargerSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'charger.sqlite'}",
        charger_domain="ruc-demo.charger-test",
        admin_token="a" * 40,
        token_pepper="p" * 40,
        test_mode=True,
    )
    client = TestClient(create_app(settings))
    register = client.post(
        "/settlement/devices/register",
        json={
            "device_id": submission["receiver_root_attestation"]["device_id"],
            "public_key_hex": submission["receiver_public_key_hex"],
            "jurisdiction_id": "ruc-demo",
        },
    )
    assert register.status_code == 200, register.text

    response = client.post(
        "/settlement/v6/period/proof-only",
        json=_submission_body(submission),
    )
    # Under test mode the missing credential is not the failure reason; the
    # request proceeds and fails (if at all) on anchoring/anti-replay grounds.
    assert response.status_code != 401, response.text
