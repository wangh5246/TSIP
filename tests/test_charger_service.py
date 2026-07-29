from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from common.policy_profile import PolicyProfile, PolicyRegistry, sha256_file
from common.settlement import (
    ReceiverFix,
    TariffTable,
    build_period_public_statement as _build_period_public_statement,
    canonical_json,
    field_from_text,
    make_device_attestation_commitment,
    sign_receiver_root_attestation,
    sign_receiver_fix,
)
from services.charger import app as charger_app

ROOT_DIR = Path(__file__).resolve().parents[1]

# Same deterministic test key used across settlement tests.
_TEST_SEED = hashlib.sha256(b"tsip-test-device-key-v1").digest()
_TEST_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_TEST_SEED)
_TEST_PUBLIC_KEY_BYTES = _TEST_PRIVATE_KEY.public_key().public_bytes_raw()
_TEST_DAC = make_device_attestation_commitment(_TEST_PUBLIC_KEY_BYTES)
_CHARGER_DOMAIN = "ruc-demo.charger-test"
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


def _test_profile() -> PolicyProfile:
    vkey = ROOT_DIR / "zk" / "settlement_period_v5_k6" / "verification_key.json"
    tariff = _tariff()
    return PolicyProfile(
        authority_id="test-policy-authority",
        jurisdiction_id="ruc-demo",
        profile_version=7,
        valid_from=_MAY_2026_START,
        valid_to=1_780_272_000,
        revoked_at=None,
        min_accepted_version=7,
        tariff_version=tariff.tariff_version,
        tariff_root=tariff.root(2),
        tariff_tree_depth=2,
        max_fixes=25,
        max_zone_rate_cents_per_m=tariff.max_zone_rate_cents_per_m,
        cadence_sec=60,
        max_dt_sec=600,
        tier_vmax_mps=33,
        tier_vmax_sq=33 * 33,
        mode_vmax_sq=33 * 33,
        cap_policy_sq=3_000_000_000,
        cap_policy_hash="test-cap-policy-v1",
        circuit_id="settlement-period-v5-test",
        verification_key_hash=sha256_file(vkey),
        currency="EUR",
        fixed_point_scale=1,
        rounding_mode="exact-integer",
        overflow_policy="reject-u96",
        monthly_reconciliation_rate_cents_per_m=tariff.max_zone_rate_cents_per_m,
        fallback_semantics_version="time-speed-max-rate-v5",
        verification_key_path=str(vkey),
    )


def build_period_public_statement(**kwargs: object) -> dict[str, object]:
    profile = _test_profile()
    return _build_period_public_statement(
        **kwargs,
        tariff_tree_depth=profile.tariff_tree_depth,
        policy_profile=profile,
    )


@pytest.fixture(autouse=True)
def _canonical_policy_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(charger_app, "policy_registry", PolicyRegistry([_test_profile()]))
    # These service tests exercise acceptance semantics.  M0's dedicated tests
    # separately verify missing/hash-mismatched keys fail closed; the legacy
    # dummy proof objects here represent already-valid Groth16 proofs.
    monkeypatch.setattr(charger_app, "_verify_zk_proof", lambda *_args, **_kwargs: None)


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
            receiver_id="test-receiver",
            charger_domain=_CHARGER_DOMAIN,
            device_id="dev-1",
            period_id=str(public["period_id"]),
            log_epoch=1,
            fix_count=2,
            receiver_fix_root=str(public["receiver_fix_root"]),
            device_attestation_commitment=str(public["device_attestation_commitment"]),
            log_sha256=hashlib.sha256(canonical_json(public).encode()).hexdigest(),
            private_key_bytes=_TEST_SEED,
        ),
    }


def _anchor(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post(
        "/settlement/receiver-chain/anchor",
        json={"root_attestation": payload["root_attestation"]},
    )
    assert response.status_code == 200, response.text


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
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )

    payload = _proof_only_payload(public)
    _anchor(client, payload)
    resp = client.post("/settlement/period/proof-only", json=payload)

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
        cadence_sec=60,
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
        cadence_sec=60,
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
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    payload = _proof_only_payload(public)
    payload["root_attestation"] = {**payload["root_attestation"], "signature": "invalid"}

    resp = client.post("/settlement/period/proof-only", json=payload)

    assert resp.status_code == 400
    assert "root attestation" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "waybill.receiver.root-attestation/v3"),
        ("position_validity_rule", "caller-supplied-legacy"),
    ],
)
def test_charger_rejects_receiver_attestation_downgrade(field: str, value: str):
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)
    fixes = [
        _fix(0, 1_777_593_600, 1_000, 0, 0),
        _fix(1, 1_777_593_900, 1_070, 1, 0),
    ]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id=f"2026-05-downgrade-{field}",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    payload = _proof_only_payload(public)
    payload["root_attestation"] = {
        **payload["root_attestation"],
        field: value,
    }

    response = client.post("/settlement/period/proof-only", json=payload)
    assert response.status_code == 400
    assert "root attestation" in response.json()["detail"]


def test_charger_rejects_root_attestation_from_another_charger_domain():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 1_777_593_600, 1_000, 0, 0), _fix(1, 1_777_593_900, 1_070, 1, 0)]
    public = build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id="2026-05-cross-domain",
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=_TEST_DAC,
    )
    payload = _proof_only_payload(public)
    payload["root_attestation"] = sign_receiver_root_attestation(
        receiver_id="test-receiver",
        charger_domain="ruc-demo.charger-other",
        device_id="dev-1",
        period_id=str(public["period_id"]),
        log_epoch=1,
        fix_count=2,
        receiver_fix_root=str(public["receiver_fix_root"]),
        device_attestation_commitment=str(public["device_attestation_commitment"]),
        log_sha256=hashlib.sha256(canonical_json(public).encode()).hexdigest(),
        private_key_bytes=_TEST_SEED,
    )

    response = client.post("/settlement/period/proof-only", json=payload)
    assert response.status_code == 400
    assert "root attestation rejected" in response.json()["detail"]


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


# --- GAP-1/2/3 regressions: monthly reconciliation, per-device keys, overlap ---

_TEST_SEED_2 = hashlib.sha256(b"tsip-test-device-key-v2").digest()
_TEST_PUBLIC_KEY_BYTES_2 = Ed25519PrivateKey.from_private_bytes(_TEST_SEED_2).public_key().public_bytes_raw()
_TEST_DAC_2 = make_device_attestation_commitment(_TEST_PUBLIC_KEY_BYTES_2)


def _fix_for(device_id: str, period_id: str, seed: bytes, seq: int, ts: int, odo: int, x: int, y: int) -> ReceiverFix:
    if ts < _MAY_2026_START:
        ts += _MAY_2026_START
    return sign_receiver_fix(
        ReceiverFix(
            device_id=device_id,
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=ts,
            cell_x=x,
            cell_y=y,
            osnma_status="authenticated",
            odometer_reading_m=odo,
            nonce=f"nonce-{seq}",
        ),
        seed,
    )


def _submit(client: TestClient, fixes: list[ReceiverFix], public: dict) -> object:
    tariff = _tariff()
    return client.post(
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


def _statement(fixes: list[ReceiverFix], period_id: str, dac: str) -> dict:
    return build_period_public_statement(
        fixes=fixes,
        tariff=_tariff(),
        period_id=period_id,
        month_id="2026-05",
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment=dac,
    )


def test_monthly_reconciliation_bills_withheld_kilometres():
    from common.settlement import sign_monthly_odometer_attestation

    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    assert _submit(client, fixes, _statement(fixes, "2026-05-p01", _TEST_DAC)).status_code == 200

    # The receiver attests 2000m driven this month; only 70m were settled.
    att = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1", month_id="2026-05",
        odometer_start_m=0, odometer_end_m=2_000,
        private_key_bytes=_TEST_SEED,
    )
    assert client.post("/settlement/month/attest", json=att).status_code == 200

    rec = client.get("/settlement/month/2026-05/reconcile", params={"device_id": "dev-1"}).json()
    assert rec["ok"] is True
    assert rec["covered_distance_m"] == 70
    assert rec["unaccounted_distance_m"] == 1_930
    # Withheld kilometres are billed at the reconciliation rate (>= max zone rate),
    # so withholding can never beat exact settlement: 1930 * 5 = 9650.
    assert rec["unaccounted_fee_cents"] == 9_650
    assert rec["total_month_bill_cents"] == 70 + 9_650


def test_reconciliation_rate_must_equal_canonical_tariff_max():
    # M0 freezes this invariant at profile construction, before a service can
    # accept any period under an unsafe monthly rate.
    with pytest.raises(ValueError, match="reconciliation rate"):
        replace(_test_profile(), monthly_reconciliation_rate_cents_per_m=4)


def test_overlapping_period_window_rejected():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    fixes1 = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    assert _submit(client, fixes1, _statement(fixes1, "2026-05-p01", _TEST_DAC)).status_code == 200

    fixes2 = [
        _fix_for("dev-1", "2026-05-p02", _TEST_SEED, 0, 105, 2_000, 0, 0),
        _fix_for("dev-1", "2026-05-p02", _TEST_SEED, 1, 115, 2_070, 1, 0),
    ]
    resp = _submit(client, fixes2, _statement(fixes2, "2026-05-p02", _TEST_DAC))
    assert resp.status_code == 409
    assert "overlaps" in resp.json()["detail"]

    # A disjoint window for the same device is fine.
    fixes3 = [
        _fix_for("dev-1", "2026-05-p03", _TEST_SEED, 0, 200, 3_000, 0, 0),
        _fix_for("dev-1", "2026-05-p03", _TEST_SEED, 1, 210, 3_070, 1, 0),
    ]
    assert _submit(client, fixes3, _statement(fixes3, "2026-05-p03", _TEST_DAC)).status_code == 200


def test_same_period_id_on_different_devices_is_not_a_collision():
    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)
    assert client.post(
        "/settlement/devices/register",
        json={"device_id": "dev-2", "public_key_hex": _TEST_PUBLIC_KEY_BYTES_2.hex()},
    ).status_code == 200

    fixes1 = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    assert _submit(client, fixes1, _statement(fixes1, "2026-05-p01", _TEST_DAC)).status_code == 200

    # Device B reuses the same bare period_id; with (device_id, period_id)
    # keying this must not be blocked (no cross-device DoS).
    fixes2 = [
        _fix_for("dev-2", "2026-05-p01", _TEST_SEED_2, 0, 100, 5_000, 0, 0),
        _fix_for("dev-2", "2026-05-p01", _TEST_SEED_2, 1, 110, 5_070, 1, 0),
    ]
    assert _submit(client, fixes2, _statement(fixes2, "2026-05-p01", _TEST_DAC_2)).status_code == 200

    # Per-device ledgers stay separate; the aggregate view sums them.
    dev1 = client.get("/settlement/month/2026-05", params={"device_id": "dev-1"}).json()
    dev2 = client.get("/settlement/month/2026-05", params={"device_id": "dev-2"}).json()
    both = client.get("/settlement/month/2026-05").json()
    assert dev1["periods"] == dev2["periods"] == 1
    assert both["periods"] == 2


def test_bad_or_conflicting_odometer_attestation_rejected():
    from common.settlement import sign_monthly_odometer_attestation

    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    # Signed by the wrong key.
    bad = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1", month_id="2026-05",
        odometer_start_m=0, odometer_end_m=100,
        private_key_bytes=_TEST_SEED_2,
    )
    assert client.post("/settlement/month/attest", json=bad).status_code == 400

    # Reconciliation requires an attestation.
    assert client.get("/settlement/month/2026-05/reconcile", params={"device_id": "dev-1"}).status_code == 400

    good = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1", month_id="2026-05",
        odometer_start_m=0, odometer_end_m=100,
        private_key_bytes=_TEST_SEED,
    )
    assert client.post("/settlement/month/attest", json=good).status_code == 200
    # Conflicting re-attestation is rejected; identical replay is idempotent.
    conflicting = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1", month_id="2026-05",
        odometer_start_m=0, odometer_end_m=999,
        private_key_bytes=_TEST_SEED,
    )
    assert client.post("/settlement/month/attest", json=conflicting).status_code == 409
    assert client.post("/settlement/month/attest", json=good).status_code == 200


def test_missing_monthly_attestation_report_flags_enrolled_devices():
    from common.settlement import sign_monthly_odometer_attestation

    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)
    assert client.post(
        "/settlement/devices/register",
        json={"device_id": "dev-2", "public_key_hex": _TEST_PUBLIC_KEY_BYTES_2.hex()},
    ).status_code == 200

    # Device 1 submits and attests. Device 2 is enrolled but withholds both
    # period proofs and the month-boundary odometer attestation, so it must
    # appear in the operator's administrative-path queue.
    fixes = [_fix(0, 100, 1_000, 0, 0), _fix(1, 110, 1_070, 1, 0)]
    assert _submit(client, fixes, _statement(fixes, "2026-05-p01", _TEST_DAC)).status_code == 200
    att = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1",
        month_id="2026-05",
        odometer_start_m=1_000,
        odometer_end_m=1_070,
        private_key_bytes=_TEST_SEED,
    )
    assert client.post("/settlement/month/attest", json=att).status_code == 200

    report = client.get("/settlement/month/2026-05/missing-attestations").json()
    assert report["ok"] is True
    assert report["missing_count"] == 1
    assert report["missing"][0]["device_id"] == "dev-2"
    assert report["missing"][0]["periods"] == 0
    assert report["missing"][0]["administrative_path"] is True


def test_monthly_odometer_attestations_must_chain_across_adjacent_months():
    from common.settlement import sign_monthly_odometer_attestation

    client = TestClient(charger_app.app)
    client.post("/settlement/reset")
    _register_device(client)

    may = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1",
        month_id="2026-05",
        odometer_start_m=0,
        odometer_end_m=100,
        private_key_bytes=_TEST_SEED,
    )
    assert client.post("/settlement/month/attest", json=may).status_code == 200

    june_bad = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1",
        month_id="2026-06",
        odometer_start_m=90,
        odometer_end_m=200,
        private_key_bytes=_TEST_SEED,
    )
    resp = client.post("/settlement/month/attest", json=june_bad)
    assert resp.status_code == 409
    assert "odometer month chain" in resp.json()["detail"]

    june_good = sign_monthly_odometer_attestation(
        charger_domain=_CHARGER_DOMAIN,
        device_id="dev-1",
        month_id="2026-06",
        odometer_start_m=100,
        odometer_end_m=200,
        private_key_bytes=_TEST_SEED,
    )
    assert client.post("/settlement/month/attest", json=june_good).status_code == 200
