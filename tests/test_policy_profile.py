from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from common.policy_profile import (
    POLICY_PROFILE_DOMAIN,
    PolicyProfile,
    PolicyRegistry,
    load_policy_profiles,
    sha256_file,
    validate_profile_local_artifacts,
)
from common.settlement import (
    ReceiverFix,
    TariffTable,
    build_period_public_statement,
    canonical_json,
    compute_public_statement_commitment,
    make_device_attestation_commitment,
    sign_receiver_fix,
    sign_receiver_root_attestation,
)
from services.charger import app as charger_app


ROOT_DIR = Path(__file__).resolve().parents[1]
_SEED = hashlib.sha256(b"waybill-m0-policy-test-device").digest()
_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_SEED)
_PUBLIC_KEY = _PRIVATE_KEY.public_key().public_bytes_raw()
_DAC = make_device_attestation_commitment(_PUBLIC_KEY)
_PERIOD_START = 1_777_593_600


def _tariff(*, low_rate: int = 1) -> TariffTable:
    return TariffTable(
        tariff_version=7,
        grid_w=2,
        cell_zones={0: 10, 1: 10, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: low_rate, 20: 5},
    )


def _profile(
    vkey: Path,
    *,
    tariff: TariffTable | None = None,
    jurisdiction_id: str = "test-jurisdiction",
    profile_version: int = 7,
    min_accepted_version: int | None = None,
    valid_from: int = _PERIOD_START,
    valid_to: int = _PERIOD_START + 2_678_400,
    revoked_at: int | None = None,
) -> PolicyProfile:
    table = tariff or _tariff()
    return PolicyProfile(
        authority_id="test-policy-authority",
        jurisdiction_id=jurisdiction_id,
        profile_version=profile_version,
        valid_from=valid_from,
        valid_to=valid_to,
        revoked_at=revoked_at,
        min_accepted_version=(profile_version if min_accepted_version is None else min_accepted_version),
        tariff_version=table.tariff_version,
        tariff_root=table.root(2),
        tariff_tree_depth=2,
        max_fixes=25,
        max_zone_rate_cents_per_m=table.max_zone_rate_cents_per_m,
        cadence_sec=60,
        max_dt_sec=600,
        tier_vmax_mps=33,
        tier_vmax_sq=33 * 33,
        mode_vmax_sq=33 * 33,
        cap_policy_sq=3_000_000_000,
        cap_policy_hash="cap-policy-v1",
        circuit_id="settlement-period-v5-test",
        verification_key_hash=sha256_file(vkey),
        currency="EUR",
        fixed_point_scale=1,
        rounding_mode="exact-integer",
        overflow_policy="reject-u96",
        monthly_reconciliation_rate_cents_per_m=table.max_zone_rate_cents_per_m,
        fallback_semantics_version="time-speed-max-rate-v5",
        verification_key_path=str(vkey),
    )


def _fixes(period_id: str = "2026-05-m0-p01") -> list[ReceiverFix]:
    fixes: list[ReceiverFix] = []
    for seq, (dt, odo, x) in enumerate(((0, 1_000, 0), (10, 1_070, 1))):
        raw = ReceiverFix(
            device_id="dev-m0",
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=_PERIOD_START + dt,
            cell_x=x,
            cell_y=0,
            osnma_status="authenticated",
            odometer_reading_m=odo,
            nonce=f"m0-nonce-{seq}",
        )
        fixes.append(sign_receiver_fix(raw, _SEED))
    return fixes


def _statement(profile: PolicyProfile, *, period_id: str = "2026-05-m0-p01") -> dict[str, object]:
    return build_period_public_statement(
        fixes=_fixes(period_id),
        tariff=_tariff(),
        period_id=period_id,
        month_id="2026-05",
        cadence_sec=profile.cadence_sec,
        tier_vmax_mps=profile.tier_vmax_mps,
        max_dt_sec=profile.max_dt_sec,
        device_attestation_commitment=_DAC,
        tariff_tree_depth=profile.tariff_tree_depth,
        policy_profile=profile,
    )


def _proof_payload(public: dict[str, object]) -> dict[str, object]:
    return {
        "public_statement": public,
        "proof": {"protocol": "groth16", "test_valid": True},
        "public_signals": [str(value) for value in charger_app._expected_public_signal_values(public)],
        "root_attestation": sign_receiver_root_attestation(
            receiver_id="test-receiver",
            charger_domain="ruc-demo.charger-test",
            device_id="dev-m0",
            period_id=str(public["period_id"]),
            log_epoch=1,
            fix_count=2,
            receiver_fix_root=str(public["receiver_fix_root"]),
            device_attestation_commitment=str(public["device_attestation_commitment"]),
            log_sha256=hashlib.sha256(canonical_json(public).encode()).hexdigest(),
            private_key_bytes=_SEED,
        ),
    }


def _anchor(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post(
        "/settlement/receiver-chain/anchor",
        json={"root_attestation": payload["root_attestation"]},
    )
    assert response.status_code == 200, response.text


def _configure_charger(
    monkeypatch: pytest.MonkeyPatch,
    profiles: list[PolicyProfile],
    *,
    jurisdiction_id: str = "test-jurisdiction",
) -> TestClient:
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry(profiles))
    monkeypatch.setattr(charger_app, "_verify_zk_proof", lambda *_args, **_kwargs: None)
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    response = client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-m0",
            "public_key_hex": _PUBLIC_KEY.hex(),
            "jurisdiction_id": jurisdiction_id,
        },
    )
    assert response.status_code == 200
    return client


def test_checked_in_profile_schema_commitment_and_tariff_are_self_consistent() -> None:
    directory = ROOT_DIR / "configs" / "settlement_policy_profiles"
    registry = load_policy_profiles(directory)
    assert len(registry.profiles) == 2
    profile = max(registry.profiles, key=lambda item: item.profile_version)
    assert profile.profile_version == 9
    assert profile.circuit_id == "settlement-period-v6-validity-bound-k25-d8"
    assert profile.receiver_attestation_schema == "waybill.receiver.root-attestation/v5"
    assert profile.position_validity_rule == "origin-osnma-authenticated-v1"
    assert profile.semantic_payload()["domain_sep"] == POLICY_PROFILE_DOMAIN
    validate_profile_local_artifacts(profile, base_dir=directory)

    vectors = json.loads(
        (directory / "policy-profile-v1-test-vectors.json").read_text(encoding="utf-8")
    )["vectors"]
    assert vectors == [
        {
            "name": "ruc-demo-v9",
            "canonical_serialization": profile.canonical_serialization,
            "profile_sha256": profile.profile_sha256,
            "policy_profile_commitment": str(profile.commitment),
        }
    ]
    with pytest.raises(ValueError, match="position-validity rule"):
        replace(profile, position_validity_rule="caller-supplied-legacy")
    with pytest.raises(ValueError, match="attestation schema"):
        replace(profile, receiver_attestation_schema="waybill.receiver.root-attestation/v3")


def test_local_tariff_artifact_rejects_stale_declared_root(tmp_path: Path) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    tariff = _tariff()
    tariff_path = tmp_path / "tariff.json"
    tariff_path.write_text(
        json.dumps(
            {
                "tariff_version": tariff.tariff_version,
                "grid_w": tariff.grid_w,
                "cell_zones": tariff.cell_zones,
                "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
                "tree_depth": 2,
                "tariff_root": str(tariff.root(2) + 1),
                "max_zone_rate_cents_per_m": tariff.max_zone_rate_cents_per_m,
            }
        ),
        encoding="utf-8",
    )
    profile = replace(_profile(vkey, tariff=tariff), tariff_artifact_path=str(tariff_path))

    with pytest.raises(ValueError, match="declared root mismatch"):
        validate_profile_local_artifacts(profile, base_dir=tmp_path)


def test_profile_commitment_changes_for_every_authority_semantic_field(tmp_path: Path) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    profile = _profile(vkey)
    mutations = {
        "jurisdiction_id": "other-jurisdiction",
        "tariff_root": profile.tariff_root + 1,
        "max_zone_rate_cents_per_m": 6,
        "cadence_sec": 61,
        "max_dt_sec": 601,
        "mode_vmax_sq": profile.mode_vmax_sq + 1,
        "cap_policy_hash": "cap-policy-v2",
        "circuit_id": "settlement-period-v5-other",
        "currency": "USD",
        "fixed_point_scale": 100,
        "rounding_mode": "floor",
        "overflow_policy": "reject-u128",
        "fallback_semantics_version": "odometer-max-rate-v1",
    }
    for field, value in mutations.items():
        kwargs: dict[str, object] = {field: value}
        if field == "max_zone_rate_cents_per_m":
            kwargs["monthly_reconciliation_rate_cents_per_m"] = value
        changed = replace(profile, **kwargs)
        assert changed.commitment != profile.commitment, field


def test_canonical_profile_accepts_and_profile_pinned_vkey_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text('{"nPublic":21}\n', encoding="utf-8")
    profile = _profile(vkey)
    calls: list[Path] = []
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry([profile]))
    monkeypatch.setattr(
        charger_app,
        "_verify_zk_proof",
        lambda _proof, _signals, path: calls.append(Path(path).resolve()),
    )
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    client.post(
        "/settlement/devices/register",
        json={
            "device_id": "dev-m0",
            "public_key_hex": _PUBLIC_KEY.hex(),
            "jurisdiction_id": profile.jurisdiction_id,
        },
    )

    payload = _proof_payload(_statement(profile))
    _anchor(client, payload)
    response = client.post("/settlement/period/proof-only", json=payload)
    assert response.status_code == 200, response.text
    assert calls == [vkey.resolve()]


@pytest.mark.parametrize(
    ("attack_id", "field", "mutated"),
    [
        ("P-ROOT", "tariff_root", "1"),
        ("P-RMAX", "max_zone_rate_cents_per_m", 1),
        ("P-CAD", "cadence_sec", 120),
        ("P-SPEED", "tier_vmax_mps", 40),
        ("P-CAP", "cap_policy_sq", 4_000_000_000),
        ("P-ARITH", "rounding_mode", "floor"),
        ("P-VKEY", "verification_key_hash", "0" * 64),
    ],
)
def test_internally_consistent_policy_mutations_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack_id: str,
    field: str,
    mutated: object,
) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    profile = _profile(vkey)
    client = _configure_charger(monkeypatch, [profile])
    public = copy.deepcopy(_statement(profile))
    public[field] = mutated
    if field == "tier_vmax_mps":
        public["tier_vmax_sq"] = int(mutated) ** 2
        public["mode_vmax_sq"] = int(mutated) ** 2
    public["statement_commitment"] = compute_public_statement_commitment(public)

    response = client.post("/settlement/period/proof-only", json=_proof_payload(public))
    assert response.status_code == 400, attack_id
    assert "canonical policy mismatch" in response.json()["detail"], attack_id


@pytest.mark.parametrize(
    "field",
    [
        "authority_id",
        "jurisdiction_id",
        "profile_version",
        "policy_profile_commitment",
        "tariff_version",
        "tariff_root",
        "tariff_tree_depth",
        "max_fixes",
        "max_zone_rate_cents_per_m",
        "cadence_sec",
        "max_dt_sec",
        "tier_vmax_mps",
        "tier_vmax_sq",
        "mode_vmax_sq",
        "cap_policy_sq",
        "cap_policy_hash",
        "circuit_id",
        "verification_key_hash",
        "currency",
        "fixed_point_scale",
        "rounding_mode",
        "overflow_policy",
        "monthly_reconciliation_rate_cents_per_m",
        "fallback_semantics_version",
    ],
)
def test_every_policy_derived_statement_field_has_single_mutation_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    profile = _profile(vkey)
    client = _configure_charger(monkeypatch, [profile])
    public = copy.deepcopy(_statement(profile))
    original = public[field]
    public[field] = int(original) + 1 if str(original).isdigit() else f"{original}-mutated"
    public["statement_commitment"] = compute_public_statement_commitment(public)

    response = client.post("/settlement/period/proof-only", json=_proof_payload(public))
    assert response.status_code == 400, field
    assert f"canonical policy mismatch: {field}" in response.json()["detail"], field


def test_missing_or_hash_mismatched_vkey_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    profile = _profile(vkey)
    public = _statement(profile)

    missing = replace(profile, verification_key_path=str(tmp_path / "missing.json"))
    client = _configure_charger(monkeypatch, [missing])
    response = client.post("/settlement/period/proof-only", json=_proof_payload(public))
    assert response.status_code == 400
    assert "verification key is missing" in response.json()["detail"]

    bad_hash = replace(profile, verification_key_hash="0" * 64)
    client = _configure_charger(monkeypatch, [bad_hash])
    bad_public = _statement(bad_hash)
    response = client.post("/settlement/period/proof-only", json=_proof_payload(bad_public))
    assert response.status_code == 400
    assert "verification key hash mismatch" in response.json()["detail"]


def test_rollback_revocation_cross_jurisdiction_and_replay_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    old = _profile(vkey, profile_version=6, min_accepted_version=6)
    floor = _profile(
        vkey,
        profile_version=7,
        min_accepted_version=7,
        valid_from=old.valid_to,
        valid_to=old.valid_to + 2_678_400,
    )
    client = _configure_charger(monkeypatch, [old, floor])
    response = client.post("/settlement/period/proof-only", json=_proof_payload(_statement(old)))
    assert response.status_code == 400
    assert "no active canonical policy" in response.json()["detail"]

    revoked = replace(old, revoked_at=_PERIOD_START + 1)
    client = _configure_charger(monkeypatch, [revoked])
    response = client.post("/settlement/period/proof-only", json=_proof_payload(_statement(revoked)))
    assert response.status_code == 400
    assert "no active canonical policy" in response.json()["detail"]

    current = _profile(vkey)
    client = _configure_charger(monkeypatch, [current], jurisdiction_id="other-jurisdiction")
    response = client.post("/settlement/period/proof-only", json=_proof_payload(_statement(current)))
    assert response.status_code == 400
    assert "unknown policy jurisdiction" in response.json()["detail"]

    client = _configure_charger(monkeypatch, [current])
    payload = _proof_payload(_statement(current))
    _anchor(client, payload)
    assert client.post("/settlement/period/proof-only", json=payload).status_code == 200
    replay = client.post("/settlement/period/proof-only", json=payload)
    assert replay.status_code == 409
    assert "already been settled" in replay.json()["detail"]


def test_profile_rollover_selects_the_unique_active_version(tmp_path: Path) -> None:
    vkey = tmp_path / "verification_key.json"
    vkey.write_text("{}\n", encoding="utf-8")
    cutover = _PERIOD_START + 1_000
    v7 = _profile(vkey, valid_to=cutover, min_accepted_version=7)
    v8 = _profile(
        vkey,
        profile_version=8,
        min_accepted_version=7,
        valid_from=cutover,
        valid_to=cutover + 10_000,
    )
    registry = PolicyRegistry([v7, v8])
    assert registry.resolve(jurisdiction_id=v7.jurisdiction_id, period_start_time=cutover - 1) == v7
    assert registry.resolve(jurisdiction_id=v7.jurisdiction_id, period_start_time=cutover) == v8


def test_v6_circuit_identifier_accepts_canonical_and_registered_formal_ids() -> None:
    assert charger_app._is_v6_settlement_circuit("settlement-period-v6-canonical")
    assert charger_app._is_v6_settlement_circuit("settlement_period_v6_d14_n100_k6")
    assert charger_app._is_v6_settlement_circuit("settlement_period_v6_d16_n200_k6")
    assert not charger_app._is_v6_settlement_circuit("settlement_period_v6_legacy")
    assert not charger_app._is_v6_settlement_circuit("settlement_period_v6_d15_n100_k6")
    assert not charger_app._is_v6_settlement_circuit("settlement_period_v6_d14_n101_k6")
