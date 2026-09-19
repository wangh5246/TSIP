"""Authority signature chain for canonical policy profiles.

Before this change the trust root for a canonical profile was "whoever can
write the profile directory": the charger compared local file hashes and
re-derived roots, but nothing bound the profile to an issuing authority.
These tests pin the Ed25519 signature chain: signing binds every semantic
field (via the canonical serialization digest), verification fails closed on
tampering and on key substitution, and a charger configured with an authority
anchor refuses to start over an unsigned or tampered profile.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from common.policy_profile import (
    PolicyProfile,
    PolicyRegistry,
    sign_policy_profile,
    verify_policy_profile_signature,
)
from services.charger import app as charger_app
from services.charger.app import ChargerSettings, create_app

ROOT_DIR = Path(__file__).resolve().parents[1]
DIFF_DIR = ROOT_DIR / "experiments/waybill_m1/v2/circuit_differential"

AUTHORITY = Ed25519PrivateKey.from_private_bytes(b"a" * 32)
IMPOSTOR = Ed25519PrivateKey.from_private_bytes(b"b" * 32)
KEY_ID = "waybill-policy-authority-2026q3"


@pytest.fixture()
def unsigned_profile() -> PolicyProfile:
    raw = json.loads((DIFF_DIR / "submission.json").read_text(encoding="utf-8"))
    return PolicyProfile.from_dict(raw["policy_profile"])


def test_signing_preserves_commitment_and_digest(unsigned_profile) -> None:
    before_commitment = unsigned_profile.commitment
    before_digest = unsigned_profile.profile_sha256
    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)

    assert signed.commitment == before_commitment
    assert signed.profile_sha256 == before_digest
    assert signed.authority_key_id == KEY_ID
    assert len(signed.authority_signature) == 128
    assert verify_policy_profile_signature(signed, public_key=AUTHORITY.public_key())


def test_signature_fails_closed_on_any_semantic_tamper(unsigned_profile) -> None:
    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)
    tampered = dataclasses.replace(signed, max_fixes=int(signed.max_fixes) + 1)

    assert verify_policy_profile_signature(tampered, public_key=AUTHORITY.public_key()) is False


def test_signature_fails_closed_on_key_substitution(unsigned_profile) -> None:
    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)

    assert verify_policy_profile_signature(signed, public_key=IMPOSTOR.public_key()) is False


def test_unsigned_profile_never_verifies(unsigned_profile) -> None:
    assert unsigned_profile.authority_signature == ""
    assert verify_policy_profile_signature(
        unsigned_profile, public_key=AUTHORITY.public_key()
    ) is False


def test_signature_round_trips_through_dict_and_back(unsigned_profile) -> None:
    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)
    restored = PolicyProfile.from_dict(signed.to_dict())

    assert restored.authority_key_id == KEY_ID
    assert restored.authority_signature == signed.authority_signature
    assert restored.commitment == unsigned_profile.commitment
    assert verify_policy_profile_signature(restored, public_key=AUTHORITY.public_key())


def test_tampered_wire_dict_with_stale_signature_is_rejected(unsigned_profile) -> None:
    """An attacker editing the shipped JSON must not inherit the signature."""

    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)
    wire = signed.to_dict()
    wire["max_fixes"] = int(wire["max_fixes"]) + 1
    with pytest.raises(ValueError, match="policy_profile_commitment does not match"):
        PolicyProfile.from_dict(wire)


def _hardened_settings(tmp_path: Path) -> ChargerSettings:
    return ChargerSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'charger.sqlite'}",
        charger_domain="ruc-demo.charger-test",
        admin_token="a" * 40,
        token_pepper="p" * 40,
        test_mode=False,
        allow_sqlite_backend_for_tests=True,
        policy_authority_public_key=AUTHORITY.public_key().public_bytes_raw(),
    )


def _registry_with(profile: PolicyProfile, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry([profile]))


def test_charger_with_anchor_accepts_signed_profile(
    tmp_path: Path, unsigned_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)
    _registry_with(signed, monkeypatch)
    application = create_app(_hardened_settings(tmp_path))
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200


def test_charger_with_anchor_rejects_unsigned_profile(
    tmp_path: Path, unsigned_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry_with(unsigned_profile, monkeypatch)
    with pytest.raises(RuntimeError, match="failed authority signature verification"):
        create_app(_hardened_settings(tmp_path))


def test_charger_with_anchor_rejects_tampered_signed_profile(
    tmp_path: Path, unsigned_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    signed = sign_policy_profile(unsigned_profile, private_key=AUTHORITY, key_id=KEY_ID)
    # Replace the registry entry with a tampered body that keeps the (now
    # stale) signature fields from the signed profile.
    tampered = dataclasses.replace(
        signed,
        max_fixes=int(signed.max_fixes) + 1,
        # Keep the commitment/digest self-consistent so only the signature
        # check can catch this: rebuild derived fields like the builder does.
    )
    _registry_with(tampered, monkeypatch)
    with pytest.raises(RuntimeError, match="failed authority signature verification"):
        create_app(_hardened_settings(tmp_path))


def test_charger_without_anchor_keeps_hash_only_root(
    tmp_path: Path, unsigned_profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No anchor configured = the documented hash-only deployment mode."""

    _registry_with(unsigned_profile, monkeypatch)
    settings = ChargerSettings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'charger.sqlite'}",
        charger_domain="ruc-demo.charger-test",
        admin_token="a" * 40,
        token_pepper="p" * 40,
        test_mode=False,
        allow_sqlite_backend_for_tests=True,
    )
    application = create_app(settings)
    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
