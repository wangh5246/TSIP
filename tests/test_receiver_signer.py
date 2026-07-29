from __future__ import annotations

import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

import common.receiver_signer as receiver_signer_module
from common.receiver_signer import (
    ReceiverSignerError,
    ReceiverSignerStore,
    derive_receiver_position_valid,
)
from common.settlement import (
    ReceiverFix,
    verify_monthly_odometer_attestation,
    verify_receiver_fix_signature,
    verify_receiver_root_attestation,
)
from services.receiver_signer.app import (
    InMemoryReceiverAnchor,
    MAX_RECEIVER_REQUEST_BYTES,
    ReceiverSignerSettings,
    create_app,
)


SEED = bytes(range(32))
CHARGER_DOMAIN = "ruc-demo.charger-test"
PROFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "configs/settlement_policy_profiles/ruc-demo-v9.json"
)


def _fixes(
    *,
    period_id: str = "period-1",
    start_time: int = 1000,
    statuses: tuple[str, str, str] = ("authenticated", "authenticated", "authenticated"),
) -> list[ReceiverFix]:
    return [
        ReceiverFix(
            device_id="device-1",
            period_id=period_id,
            fix_seq=index,
            auth_gnss_time=start_time + index * 60,
            cell_x=index,
            cell_y=0,
            osnma_status=statuses[index],
            odometer_reading_m=1000 + index * 100,
            nonce=f"nonce-{period_id}-{index}",
        )
        for index in range(3)
    ]


def _shifted_fixes(
    *, period_id: str, start_time: int, odometer_start_m: int
) -> list[ReceiverFix]:
    return [
        ReceiverFix(
            **{
                **fix.__dict__,
                "odometer_reading_m": odometer_start_m + index * 100,
            }
        )
        for index, fix in enumerate(
            _fixes(period_id=period_id, start_time=start_time)
        )
    ]


class _AnchoredTestStore(ReceiverSignerStore):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.test_anchor = InMemoryReceiverAnchor(device_id=self.device_id)

    def seal_period(  # type: ignore[override]
        self,
        *,
        fixes: list[ReceiverFix],
        policy_profile_commitment: int,
    ) -> dict[str, object]:
        return super().seal_period(
            fixes=fixes,
            policy_profile_commitment=policy_profile_commitment,
            charger_head=self.test_anchor.head(),
            anchor_attestation=self.test_anchor.anchor,
        )

    def seal_month(  # type: ignore[override]
        self,
        *,
        device_id: str,
        month_id: str,
        odometer_start_m: int,
        odometer_end_m: int,
    ) -> dict[str, object]:
        return super().seal_month(
            device_id=device_id,
            month_id=month_id,
            odometer_start_m=odometer_start_m,
            odometer_end_m=odometer_end_m,
            anchor_attestation=self.test_anchor.anchor_month,
        )


def _store(tmp_path: Path, name: str = "receiver.sqlite") -> _AnchoredTestStore:
    return _AnchoredTestStore(
        database_path=tmp_path / name,
        private_key_bytes=SEED,
        receiver_id="receiver-1",
        device_id="device-1",
        charger_domain=CHARGER_DOMAIN,
        policy_profile_commitment=17,
    )


def _write_test_ca(tmp_path: Path) -> Path:
    private_key = Ed25519PrivateKey.generate()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WayBill test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(private_key, algorithm=None)
    )
    path = tmp_path / "charger-ca.pem"
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    os.chmod(path, 0o644)
    return path


def test_receiver_derives_validity_and_attests_only_a_sealed_log(tmp_path: Path) -> None:
    store = _store(tmp_path)
    fixes = _fixes(statuses=("unavailable", "unavailable", "authenticated"))
    sealed = store.seal_period(
        fixes=fixes,
        policy_profile_commitment=17,
    )
    attestation = store.attest_period(device_id="device-1", period_id="period-1")

    assert sealed["position_valid"] == [False, False]
    assert attestation["receiver_fix_root"] == sealed["receiver_fix_root"]
    signed_fixes = [ReceiverFix.from_dict(item) for item in sealed["fixes"]]
    assert all(verify_receiver_fix_signature(fix, store.public_key_bytes) for fix in signed_fixes)
    assert "statement_commitment" not in attestation
    public = {
        "period_id": "period-1",
        "receiver_fix_root": sealed["receiver_fix_root"],
        "device_attestation_commitment": sealed["device_attestation_commitment"],
    }
    assert verify_receiver_root_attestation(
        public_statement=public,
        attestation=attestation,
        public_key_bytes=store.public_key_bytes,
        expected_charger_domain=CHARGER_DOMAIN,
    )


def test_validity_change_changes_receiver_root(tmp_path: Path) -> None:
    authenticated = _fixes()
    first = _store(tmp_path, "first.sqlite").seal_period(
        fixes=authenticated,
        policy_profile_commitment=17,
    )
    unavailable = _fixes(
        statuses=("unavailable", "unavailable", "authenticated")
    )
    second = _store(tmp_path, "second.sqlite").seal_period(
        fixes=unavailable,
        policy_profile_commitment=17,
    )

    assert first["position_valid"] == [True, True]
    assert second["position_valid"] == [False, False]
    assert first["receiver_fix_root"] != second["receiver_fix_root"]


def test_receiver_store_rejects_duplicate_and_rollback(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.seal_period(fixes=_fixes(), policy_profile_commitment=17)

    with pytest.raises(ReceiverSignerError, match="already sealed"):
        store.seal_period(fixes=_fixes(), policy_profile_commitment=17)

    rollback = _fixes(period_id="period-2", start_time=900)
    with pytest.raises(ReceiverSignerError, match="time rolls back"):
        store.seal_period(fixes=rollback, policy_profile_commitment=17)


def test_receiver_api_requires_acquisition_credential_and_forbids_caller_root(
    tmp_path: Path,
) -> None:
    key_path = tmp_path / "receiver.key"
    key_path.write_bytes(SEED)
    os.chmod(key_path, 0o600)
    app = create_app(
        ReceiverSignerSettings(
            database_path=tmp_path / "api.sqlite",
            key_path=key_path,
            acquisition_token="acquisition-token-0000000000000001",
            prover_token="prover-token-0000000000000000000001",
            receiver_id="receiver-1",
            device_id="device-1",
            charger_domain=CHARGER_DOMAIN,
            policy_profile_path=PROFILE_PATH,
            charger_base_url=None,
            charger_device_token=None,
            test_mode=True,
        )
    )
    unsigned_fixes = []
    for fix in _fixes():
        item = fix.to_dict()
        item.pop("receiver_sig")
        unsigned_fixes.append(item)
    payload = {"fixes": unsigned_fixes}
    with TestClient(app) as client:
        assert client.post("/v2/receiver/logs", json=payload).status_code == 401
        duplicate = client.post(
            "/v2/receiver/logs",
            content=b'{"fixes":[],"fixes":[]}',
            headers={
                "Authorization": "Bearer acquisition-token-0000000000000001",
                "Content-Type": "application/json",
            },
        )
        assert duplicate.status_code == 400
        assert duplicate.json() == {"detail": "invalid JSON request body"}
        oversized = client.post(
            "/v2/receiver/logs",
            content=b"x" * (MAX_RECEIVER_REQUEST_BYTES + 1),
            headers={
                "Authorization": "Bearer acquisition-token-0000000000000001",
                "Content-Type": "application/json",
            },
        )
        assert oversized.status_code == 413
        injected = {**payload, "receiver_fix_root": "123"}
        assert (
            client.post(
                "/v2/receiver/logs",
                json=injected,
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 422
        )
        for invalid_status in ("Authenticated", " authenticated", "invalid", ""):
            bad_status = {**payload, "fixes": [dict(item) for item in unsigned_fixes]}
            bad_status["fixes"][0]["osnma_status"] = invalid_status
            assert (
                client.post(
                    "/v2/receiver/logs",
                    json=bad_status,
                    headers={
                        "Authorization": "Bearer acquisition-token-0000000000000001"
                    },
                ).status_code
                == 422
            )
        caller_validity = {**payload, "position_valid": [False, False]}
        assert (
            client.post(
                "/v2/receiver/logs",
                json=caller_validity,
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 422
        )
        caller_profile = {**payload, "policy_profile_commitment": 17}
        assert (
            client.post(
                "/v2/receiver/logs",
                json=caller_profile,
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 422
        )
        oversized_fixes = []
        for index in range(26):
            item = dict(unsigned_fixes[0])
            item["fix_seq"] = index
            item["auth_gnss_time"] = 1000 + index * 60
            item["odometer_reading_m"] = 1000 + index
            item["nonce"] = f"oversized-{index}"
            oversized_fixes.append(item)
        assert (
            client.post(
                "/v2/receiver/logs",
                json={"fixes": oversized_fixes},
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 422
        )

        month_payload = {
            "device_id": "device-1",
            "month_id": "202601",
            "odometer_start_m": 1000,
            "odometer_end_m": 1600,
        }
        assert client.post("/v2/receiver/months", json=month_payload).status_code == 401
        sealed_month = client.post(
            "/v2/receiver/months",
            json=month_payload,
            headers={
                "Authorization": "Bearer acquisition-token-0000000000000001"
            },
        )
        assert sealed_month.status_code == 201
        month_path = "/v2/receiver/months/device-1/202601/attestation"
        assert client.get(month_path).status_code == 401
        assert (
            client.get(
                month_path,
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 401
        )
        month_material = client.get(
            month_path,
            headers={"Authorization": "Bearer prover-token-0000000000000000000001"},
        )
        assert month_material.status_code == 200
        assert "month_epoch" not in month_material.json()["attestation"]
        assert month_material.json()["attestation"]["charger_domain"] == CHARGER_DOMAIN
        accepted = client.post(
            "/v2/receiver/logs",
            json=payload,
            headers={
                "Authorization": "Bearer acquisition-token-0000000000000001"
            },
        )
        assert accepted.status_code == 201
        period_path = "/v2/receiver/logs/device-1/period-1/attestation"
        assert client.get(period_path).status_code == 401
        assert (
            client.get(
                period_path,
                headers={"Authorization": "Bearer wrong-prover-token-000000000000000"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                period_path,
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 401
        )
        material = client.get(
            period_path,
            headers={"Authorization": "Bearer prover-token-0000000000000000000001"},
        )
        assert material.status_code == 200
        body = material.json()
        assert body["position_valid"] == [True, True]
        assert all(item["receiver_sig"] for item in body["fixes"])
        assert len(body["receiver_public_key_hex"]) == 64
        assert body["attestation"]["receiver_fix_root"] == accepted.json()[
            "receiver_fix_root"
        ]
        assert body["attestation"]["schema"] == "waybill.receiver.root-attestation/v5"
        assert (
            body["attestation"]["position_validity_rule"]
            == "origin-osnma-authenticated-v1"
        )
        assert (
            client.get(
                "/v2/receiver/logs/device-2/period-1/attestation",
                headers={
                    "Authorization": "Bearer prover-token-0000000000000000000001"
                },
            ).status_code
            == 404
        )

        caller_signed = {**payload, "fixes": [dict(item) for item in unsigned_fixes]}
        caller_signed["fixes"][0]["receiver_sig"] = "caller-controlled"
        assert (
            client.post(
                "/v2/receiver/logs",
                json=caller_signed,
                headers={
                    "Authorization": "Bearer acquisition-token-0000000000000001"
                },
            ).status_code
            == 422
        )


def test_receiver_persists_and_authenticates_month_boundary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sealed = store.seal_month(
        device_id="device-1",
        month_id="202601",
        odometer_start_m=1000,
        odometer_end_m=1600,
    )
    persisted = store.month_attestation(device_id="device-1", month_id="202601")

    assert persisted == sealed
    assert verify_monthly_odometer_attestation(
        attestation=persisted,
        public_key_bytes=store.public_key_bytes,
        expected_charger_domain=CHARGER_DOMAIN,
    )
    with pytest.raises(ReceiverSignerError, match="duplicate|already sealed"):
        store.seal_month(
            device_id="device-1",
            month_id="202601",
            odometer_start_m=1000,
            odometer_end_m=1600,
        )
    with pytest.raises(ReceiverSignerError, match="rolls back"):
        store.seal_month(
            device_id="device-1",
            month_id="202602",
            odometer_start_m=1500,
            odometer_end_m=1700,
        )


def test_attestation_cannot_be_rebound_to_another_root(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sealed = store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    attestation = store.attest_period(device_id="device-1", period_id="period-1")
    public = {
        "period_id": "period-1",
        "receiver_fix_root": str(int(sealed["receiver_fix_root"]) + 1),
        "device_attestation_commitment": sealed["device_attestation_commitment"],
    }
    assert not verify_receiver_root_attestation(
        public_statement=public,
        attestation=attestation,
        public_key_bytes=store.public_key_bytes,
        expected_charger_domain=CHARGER_DOMAIN,
    )


def test_attestation_is_bound_to_one_charger_domain(tmp_path: Path) -> None:
    store = _store(tmp_path)
    sealed = store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    attestation = store.attest_period(device_id="device-1", period_id="period-1")
    public = {
        "period_id": "period-1",
        "receiver_fix_root": sealed["receiver_fix_root"],
        "device_attestation_commitment": sealed["device_attestation_commitment"],
    }

    assert attestation["charger_domain"] == CHARGER_DOMAIN
    assert not verify_receiver_root_attestation(
        public_statement=public,
        attestation=attestation,
        public_key_bytes=store.public_key_bytes,
        expected_charger_domain="ruc-demo.charger-other",
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (("authenticated", "authenticated", "authenticated"), [True, True]),
        (("authenticated", "unavailable", "authenticated"), [True, False]),
        (("unavailable", "authenticated", "authenticated"), [False, True]),
        (("unavailable", "unavailable", "authenticated"), [False, False]),
        (("authenticated", "authenticated", "unavailable"), [True, True]),
    ],
)
def test_origin_status_rule_is_exact_and_terminal_has_no_flag(
    statuses: tuple[str, str, str], expected: list[bool]
) -> None:
    assert derive_receiver_position_valid(_fixes(statuses=statuses)) == expected


def test_receiver_rejects_unknown_status_and_cross_device_writes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ReceiverSignerError, match="unsupported receiver availability"):
        store.seal_period(
            fixes=_fixes(statuses=("AUTHENTICATED", "authenticated", "authenticated")),
            policy_profile_commitment=17,
        )
    other_device = [
        ReceiverFix(**{**fix.__dict__, "device_id": "device-2"})
        for fix in _fixes()
    ]
    with pytest.raises(ReceiverSignerError, match="bound to another device"):
        store.seal_period(fixes=other_device, policy_profile_commitment=17)
    with pytest.raises(ReceiverSignerError, match="bound to another device"):
        store.seal_month(
            device_id="device-2",
            month_id="202601",
            odometer_start_m=1000,
            odometer_end_m=1600,
        )


def test_period_attestation_is_immutable_across_restart_and_tamper_fails(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "immutable.sqlite"
    store = _store(tmp_path, database_path.name)
    sealed = store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    original = store.attest_period(device_id="device-1", period_id="period-1")

    restarted = _store(tmp_path, database_path.name)
    assert restarted.attest_period(device_id="device-1", period_id="period-1") == original
    assert original == sealed["attestation"]

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE receiver_logs SET attestation_json = ? WHERE period_id = ?",
            ('{"schema":"waybill.receiver.root-attestation/v5"}', "period-1"),
        )
    with pytest.raises(ReceiverSignerError, match="attestation"):
        restarted.attest_period(device_id="device-1", period_id="period-1")


def test_period_seal_rolls_back_if_attestation_signing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, "rollback.sqlite")

    def fail_signing(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("injected signing failure")

    monkeypatch.setattr(
        receiver_signer_module,
        "sign_receiver_root_attestation",
        fail_signing,
    )
    with pytest.raises(RuntimeError, match="injected signing failure"):
        store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM receiver_logs").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("column", "tampered"),
    [
        ("period_start_time", 0),
        ("period_end_time", 0),
        ("odometer_start_m", 0),
        ("odometer_end_m", 0),
        ("fix_count", 99),
    ],
)
def test_tampered_redundant_period_boundary_blocks_next_seal(
    tmp_path: Path, column: str, tampered: int
) -> None:
    store = _store(tmp_path, f"tampered-{column}.sqlite")
    store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            f"UPDATE receiver_logs SET {column} = ? WHERE period_id = ?",
            (tampered, "period-1"),
        )

    with pytest.raises(ReceiverSignerError, match="redundant boundary"):
        store.seal_period(
            fixes=_shifted_fixes(
                period_id="period-2", start_time=1300, odometer_start_m=1300
            ),
            policy_profile_commitment=17,
        )


def test_deleted_tail_cannot_create_a_conflicting_charger_anchored_epoch(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "deleted-tail.sqlite")
    first = store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DELETE FROM receiver_logs WHERE period_id = ?", ("period-1",))

    with pytest.raises(ReceiverSignerError, match="cannot be recovered"):
        store.seal_period(
            fixes=_shifted_fixes(
                period_id="fork-period", start_time=1300, odometer_start_m=1300
            ),
            policy_profile_commitment=17,
        )
    assert store.test_anchor.head()["attestation_sha256"] == receiver_signer_module.receiver_attestation_sha256(
        first["attestation"]  # type: ignore[arg-type,index]
    )
    with sqlite3.connect(store.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM receiver_logs").fetchone()[0] == 0


def test_exact_retry_recovers_after_remote_anchor_commit_and_local_row_loss(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "anchor-recovery.sqlite")
    first = store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DELETE FROM receiver_logs WHERE period_id = ?", ("period-1",))

    recovered = store.seal_period(fixes=_fixes(), policy_profile_commitment=17)
    assert recovered["attestation"] == first["attestation"]


def test_exact_retry_recovers_month_after_remote_commit_and_local_row_loss(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "month-anchor-recovery.sqlite")
    first = store.seal_month(
        device_id="device-1",
        month_id="202601",
        odometer_start_m=1_000,
        odometer_end_m=1_600,
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DELETE FROM receiver_months WHERE month_id = ?", ("202601",))

    recovered = store.seal_month(
        device_id="device-1",
        month_id="202601",
        odometer_start_m=1_000,
        odometer_end_m=1_600,
    )
    assert recovered["signature"] == first["signature"]


def test_remote_month_anchor_rejects_conflicting_rollback_and_month_gap(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "month-anchor-conflict.sqlite")
    store.seal_month(
        device_id="device-1",
        month_id="202601",
        odometer_start_m=1_000,
        odometer_end_m=1_600,
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DELETE FROM receiver_months WHERE month_id = ?", ("202601",))
    with pytest.raises(ReceiverSignerError, match="conflicting bytes"):
        store.seal_month(
            device_id="device-1",
            month_id="202601",
            odometer_start_m=1_000,
            odometer_end_m=1_500,
        )

    with pytest.raises(ReceiverSignerError, match="month gap"):
        store.seal_month(
            device_id="device-1",
            month_id="202603",
            odometer_start_m=1_600,
            odometer_end_m=1_700,
        )


def test_receiver_rejects_month_boundary_before_the_month_has_ended(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, "future-month.sqlite")
    with pytest.raises(ReceiverSignerError, match="month has not ended"):
        store.seal_month(
            device_id="device-1",
            month_id="209901",
            odometer_start_m=1_000,
            odometer_end_m=1_600,
        )


def test_tampered_month_boundary_blocks_next_month(tmp_path: Path) -> None:
    store = _store(tmp_path, "tampered-month.sqlite")
    store.seal_month(
        device_id="device-1",
        month_id="202601",
        odometer_start_m=1000,
        odometer_end_m=1600,
    )
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE receiver_months SET odometer_end_m = 0 WHERE month_id = ?",
            ("202601",),
        )
    with pytest.raises(ReceiverSignerError, match="boundary is inconsistent"):
        store.seal_month(
            device_id="device-1",
            month_id="202602",
            odometer_start_m=1600,
            odometer_end_m=1700,
        )


def test_receiver_secret_files_require_owner_only_permissions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.database_path.stat().st_mode & 0o077 == 0

    key_path = tmp_path / "insecure.key"
    key_path.write_bytes(SEED)
    os.chmod(key_path, 0o644)
    settings = ReceiverSignerSettings(
        database_path=tmp_path / "insecure.sqlite",
        key_path=key_path,
        acquisition_token="acquisition-token-0000000000000001",
        prover_token="prover-token-0000000000000000000001",
        receiver_id="receiver-1",
        device_id="device-1",
        charger_domain=CHARGER_DOMAIN,
        policy_profile_path=PROFILE_PATH,
        charger_base_url=None,
        charger_device_token=None,
        test_mode=True,
    )
    with pytest.raises(ReceiverSignerError, match="mode 0600"):
        settings.build_store()

    secure_key = tmp_path / "secure.key"
    secure_key.write_bytes(SEED)
    os.chmod(secure_key, 0o600)
    key_link = tmp_path / "linked.key"
    key_link.symlink_to(secure_key)
    linked_settings = ReceiverSignerSettings(
        database_path=tmp_path / "linked.sqlite",
        key_path=key_link,
        acquisition_token="acquisition-token-0000000000000001",
        prover_token="prover-token-0000000000000000000001",
        receiver_id="receiver-1",
        device_id="device-1",
        charger_domain=CHARGER_DOMAIN,
        policy_profile_path=PROFILE_PATH,
        charger_base_url=None,
        charger_device_token=None,
        test_mode=True,
    )
    with pytest.raises(ReceiverSignerError, match="cannot read receiver key"):
        linked_settings.build_store()

    insecure_state = tmp_path / "insecure-state"
    insecure_state.mkdir(mode=0o700)
    os.chmod(insecure_state, 0o755)
    with pytest.raises(ReceiverSignerError, match="state directory must be mode 0700"):
        ReceiverSignerStore(
            database_path=insecure_state / "receiver.sqlite",
            private_key_bytes=SEED,
            receiver_id="receiver-1",
            device_id="device-1",
            charger_domain=CHARGER_DOMAIN,
            policy_profile_commitment=17,
        )

    with pytest.raises(ReceiverSignerError, match="must be independent"):
        ReceiverSignerSettings(
            database_path=tmp_path / "same-token.sqlite",
            key_path=key_path,
            acquisition_token="same-token-0000000000000000000000",
            prover_token="same-token-0000000000000000000000",
            receiver_id="receiver-1",
            device_id="device-1",
            charger_domain=CHARGER_DOMAIN,
            policy_profile_path=PROFILE_PATH,
            charger_base_url=None,
            charger_device_token=None,
            test_mode=True,
        )


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("PRAGMA application_id = 1", "application_id"),
        ("PRAGMA user_version = 999", "schema version"),
        (
            "CREATE TRIGGER poison AFTER INSERT ON receiver_logs "
            "BEGIN DELETE FROM receiver_logs; END",
            "forbidden trigger",
        ),
        ("CREATE TABLE injected(value TEXT)", "schema objects"),
    ],
)
def test_receiver_database_rejects_schema_confusion_before_use(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    database_path = tmp_path / "schema.sqlite"
    _store(tmp_path, database_path.name)
    with sqlite3.connect(database_path) as connection:
        connection.execute(mutation)

    with pytest.raises(ReceiverSignerError, match=expected_error):
        _store(tmp_path, database_path.name)


def test_receiver_database_rejects_symlink_and_unknown_existing_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.sqlite"
    _store(tmp_path, target.name)
    linked = tmp_path / "linked.sqlite"
    linked.symlink_to(target)
    with pytest.raises(ReceiverSignerError, match="securely open receiver database"):
        _store(tmp_path, linked.name)

    unknown = tmp_path / "unknown.sqlite"
    with sqlite3.connect(unknown) as connection:
        connection.execute("CREATE TABLE legacy(value TEXT)")
    os.chmod(unknown, 0o600)
    with pytest.raises(ReceiverSignerError, match="application_id"):
        _store(tmp_path, unknown.name)


def test_production_receiver_enforces_profile_window_and_fix_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_path = tmp_path / "receiver.key"
    key_path.write_bytes(SEED)
    os.chmod(key_path, 0o600)
    ca_path = _write_test_ca(tmp_path)
    settings = ReceiverSignerSettings(
        database_path=tmp_path / "profile.sqlite",
        key_path=key_path,
        acquisition_token="acquisition-token-0000000000000001",
        prover_token="prover-token-0000000000000000000001",
        receiver_id="receiver-1",
        device_id="device-1",
        charger_domain=CHARGER_DOMAIN,
        policy_profile_path=PROFILE_PATH,
        charger_base_url="https://127.0.0.1:8443",
        charger_device_token="charger-device-token-000000000000001",
        charger_ca_file=ca_path,
        test_mode=False,
    )
    with pytest.raises(ReceiverSignerError, match="explicit Charger CA"):
        replace(settings, charger_ca_file=None)
    with pytest.raises(ReceiverSignerError, match="must use HTTPS"):
        replace(settings, charger_base_url="http://127.0.0.1:8020")
    monkeypatch.setattr(
        ReceiverSignerSettings,
        "build_anchor",
        lambda self: InMemoryReceiverAnchor(device_id=self.device_id),
    )
    application = create_app(settings)
    headers = {"Authorization": "Bearer acquisition-token-0000000000000001"}
    stale = []
    for fix in _fixes():
        item = fix.to_dict()
        item.pop("receiver_sig")
        stale.append(item)
    with TestClient(application) as client:
        response = client.post(
            "/v2/receiver/logs", json={"fixes": stale}, headers=headers
        )
        assert response.status_code == 400
        assert "not active" in response.json()["detail"]

        valid_start = 1_777_593_600
        excessive_gap = []
        for fix in _fixes(start_time=valid_start):
            item = fix.to_dict()
            item.pop("receiver_sig")
            excessive_gap.append(item)
        excessive_gap[1]["auth_gnss_time"] = valid_start + 601
        excessive_gap[2]["auth_gnss_time"] = valid_start + 602
        response = client.post(
            "/v2/receiver/logs", json={"fixes": excessive_gap}, headers=headers
        )
        assert response.status_code == 400
        assert "maximum fix gap" in response.json()["detail"]
