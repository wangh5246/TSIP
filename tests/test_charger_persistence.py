from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import event

from services.charger.store import ChargerConflict, ChargerStore, ChargerStoreError


DOMAIN = "ruc-demo.charger-persistence-test"


def _url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path}"


def _store(path: Path) -> ChargerStore:
    store = ChargerStore(database_url=_url(path), charger_domain=DOMAIN)
    if store.get_device("device-1") is None:
        store.register_device(
            device_id="device-1",
            public_key=bytes(range(32)),
            jurisdiction_id="ruc-demo",
            token_digest="a" * 64,
        )
    return store


def _public(period_id: str, *, start: int = 1_777_593_600, end: int = 1_777_593_900) -> dict[str, object]:
    return {
        "period_id": period_id,
        "month_id": "2026-05",
        "period_start_time": start,
        "period_end_time": end,
        "total_fee_cents": 70,
        "total_distance_m": 70,
        "fallback_intervals": 0,
        "policy_profile_commitment": "17",
    }


def _month_attestation(month_id: str, *, start_m: int, end_m: int) -> dict[str, object]:
    return {
        "schema": "waybill.receiver.month-attestation/v1",
        "charger_domain": DOMAIN,
        "device_id": "device-1",
        "month_id": month_id,
        "odometer_start_m": start_m,
        "odometer_end_m": end_m,
        "signature": f"signature-{month_id}-{start_m}-{end_m}",
    }


def test_restart_preserves_replay_ledger_attestation_and_close_receipt(tmp_path: Path) -> None:
    database = tmp_path / "charger.sqlite"
    first = _store(database)
    first.accept_period(
        device_id="device-1",
        public=_public("period-1"),
        month_number=202605,
        reconciliation_rate_cents_per_m=5,
        allow_unanchored=True,
    )
    first.put_attestation(
        device_id="device-1",
        month_number=202605,
        attestation={
            "schema": "test",
            "charger_domain": DOMAIN,
            "device_id": "device-1",
            "month_id": "2026-05",
            "odometer_start_m": 1_000,
            "odometer_end_m": 2_000,
            "signature": "test",
        },
    )
    receipt = first.close_month(
        device_id="device-1",
        month_id="2026-05",
        month_number=202605,
        default_reconciliation_rate=5,
    )
    first.close()

    restarted = _store(database)
    assert restarted.counts() == {
        "registered_devices": 1,
        "accepted_periods": 1,
        "months": 1,
    }
    assert restarted.month_totals(device_id="device-1", month_number=202605)[
        "total_fee_cents"
    ] == 70
    assert restarted.get_attestation(device_id="device-1", month_number=202605) is not None
    replayed_close = restarted.close_month(
        device_id="device-1",
        month_id="202605",
        month_number=202605,
        default_reconciliation_rate=5,
    )
    assert replayed_close["idempotent"] is True
    assert replayed_close["receipt_sha256"] == receipt["receipt_sha256"]
    with pytest.raises(ChargerConflict, match="no longer accepts"):
        restarted.accept_period(
            device_id="device-1",
            public=_public("period-1"),
            month_number=202605,
            reconciliation_rate_cents_per_m=5,
            allow_unanchored=True,
        )
    restarted.close()


def test_month_attestation_anchor_is_append_only_exact_and_continuous(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "month-chain.sqlite")
    january = _month_attestation("202601", start_m=1_000, end_m=1_600)
    assert store.put_attestation(
        device_id="device-1", month_number=202601, attestation=january
    )
    assert not store.put_attestation(
        device_id="device-1", month_number=202601, attestation=january
    )

    with pytest.raises(ChargerConflict, match="conflicting"):
        store.put_attestation(
            device_id="device-1",
            month_number=202601,
            attestation=_month_attestation("202601", start_m=1_000, end_m=1_500),
        )
    with pytest.raises(ChargerConflict, match="next calendar month"):
        store.put_attestation(
            device_id="device-1",
            month_number=202603,
            attestation=_month_attestation("202603", start_m=1_600, end_m=1_900),
        )
    with pytest.raises(ChargerConflict, match="continue the previous boundary"):
        store.put_attestation(
            device_id="device-1",
            month_number=202602,
            attestation=_month_attestation("202602", start_m=1_599, end_m=1_900),
        )
    assert store.put_attestation(
        device_id="device-1",
        month_number=202602,
        attestation=_month_attestation("202602", start_m=1_600, end_m=1_900),
    )
    store.close()


def test_database_is_cryptographically_scoped_to_one_charger_domain(tmp_path: Path) -> None:
    database = tmp_path / "domain.sqlite"
    ChargerStore(database_url=_url(database), charger_domain=DOMAIN).close()
    with pytest.raises(ChargerStoreError, match="different Charger domain"):
        ChargerStore(
            database_url=_url(database),
            charger_domain="ruc-demo.charger-other",
        )


def test_concurrent_duplicate_period_has_exactly_one_winner(tmp_path: Path) -> None:
    store = _store(tmp_path / "duplicate.sqlite")

    def submit() -> str:
        try:
            store.accept_period(
                device_id="device-1",
                public=_public("period-race"),
                month_number=202605,
                reconciliation_rate_cents_per_m=5,
                allow_unanchored=True,
            )
            return "accepted"
        except ChargerConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: submit(), range(8)))
    assert results.count("accepted") == 1
    assert results.count("conflict") == 7
    assert store.counts()["accepted_periods"] == 1
    assert store.month_totals(device_id="device-1", month_number=202605)["periods"] == 1
    store.close()


def test_concurrent_overlapping_periods_have_at_most_one_winner(tmp_path: Path) -> None:
    store = _store(tmp_path / "overlap.sqlite")

    def submit(index: int) -> str:
        try:
            store.accept_period(
                device_id="device-1",
                public=_public(f"period-{index}", start=1_777_593_600 + index),
                month_number=202605,
                reconciliation_rate_cents_per_m=5,
                allow_unanchored=True,
            )
            return "accepted"
        except ChargerConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(submit, range(8)))
    assert results.count("accepted") == 1
    assert store.counts()["accepted_periods"] == 1
    store.close()


def test_failure_between_period_insert_and_month_update_rolls_back(tmp_path: Path) -> None:
    store = _store(tmp_path / "rollback.sqlite")

    def fail_month_update(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("UPDATE MONTH_STATES"):
            raise RuntimeError("injected failure before commit")

    event.listen(store.engine, "before_cursor_execute", fail_month_update)
    try:
        with pytest.raises(RuntimeError, match="injected failure"):
            store.accept_period(
                device_id="device-1",
                public=_public("period-fail"),
                month_number=202605,
                reconciliation_rate_cents_per_m=5,
                allow_unanchored=True,
            )
    finally:
        event.remove(store.engine, "before_cursor_execute", fail_month_update)
    assert store.counts()["accepted_periods"] == 0
    assert store.month_totals(device_id="device-1", month_number=202605)["periods"] == 0
    store.close()


@pytest.mark.skipif(
    not os.getenv("WAYBILL_TEST_POSTGRES_URL"),
    reason="WAYBILL_TEST_POSTGRES_URL is not configured",
)
def test_postgresql_backend_obeys_the_same_replay_contract() -> None:
    store = ChargerStore(
        database_url=str(os.environ["WAYBILL_TEST_POSTGRES_URL"]),
        charger_domain=str(os.getenv("WAYBILL_TEST_POSTGRES_DOMAIN", DOMAIN)),
    )
    store.reset()
    store.register_device(
        device_id="device-1",
        public_key=bytes(range(32)),
        jurisdiction_id="ruc-demo",
        token_digest="a" * 64,
    )
    store.accept_period(
        device_id="device-1",
        public=_public("postgres-period"),
        month_number=202605,
        reconciliation_rate_cents_per_m=5,
        allow_unanchored=True,
    )
    with pytest.raises(ChargerConflict, match="already accepted"):
        store.accept_period(
            device_id="device-1",
            public=_public("postgres-period"),
            month_number=202605,
            reconciliation_rate_cents_per_m=5,
            allow_unanchored=True,
        )
    assert store.counts()["accepted_periods"] == 1
    store.close()
