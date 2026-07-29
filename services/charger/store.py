"""Transactional persistence for the WayBill settlement Charger."""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.pool import StaticPool

from common.settlement import (
    SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    canonical_json,
)
from common.settlement_v6 import reconcile_month_v6


CHARGER_SCHEMA_VERSION = 3


class ChargerStoreError(RuntimeError):
    """Base class for persistence failures that must fail closed."""


class ChargerConflict(ChargerStoreError):
    """A replay, overlap, or immutable-state conflict."""


class ChargerNotFound(ChargerStoreError):
    """The requested enrolled device or statement does not exist."""


metadata = MetaData()

charger_meta = Table(
    "charger_meta",
    metadata,
    Column("singleton_id", Integer, primary_key=True),
    Column("schema_version", Integer, nullable=False),
    Column("charger_domain_sha256", String(64), nullable=False),
    Column("created_at_ns", BigInteger, nullable=False),
    CheckConstraint("singleton_id = 1", name="ck_charger_meta_singleton"),
)

devices = Table(
    "devices",
    metadata,
    Column("device_id", String(255), primary_key=True),
    Column("public_key", LargeBinary(32), nullable=False),
    Column("jurisdiction_id", String(255), nullable=False),
    Column("token_digest", String(64), nullable=False),
    Column("created_at_ns", BigInteger, nullable=False),
    UniqueConstraint("token_digest", name="uq_device_token_digest"),
)

receiver_attestations = Table(
    "receiver_attestations",
    metadata,
    Column("device_id", String(255), nullable=False),
    Column("receiver_id", String(255), nullable=False),
    Column("charger_domain", String(255), nullable=False),
    Column("period_id", String(255), nullable=False),
    Column("log_epoch", BigInteger, nullable=False),
    Column("previous_attestation_sha256", String(64), nullable=False),
    Column("attestation_sha256", String(64), nullable=False),
    Column("attestation_json", Text, nullable=False),
    Column("settled", Boolean, nullable=False, default=False),
    Column("anchored_at_ns", BigInteger, nullable=False),
    Column("settled_at_ns", BigInteger, nullable=True),
    UniqueConstraint("device_id", "log_epoch", name="uq_receiver_attestation_device_epoch"),
    UniqueConstraint(
        "receiver_id",
        "charger_domain",
        "device_id",
        "period_id",
        name="uq_receiver_attestation_identity_period",
    ),
    UniqueConstraint("attestation_sha256", name="uq_receiver_attestation_sha256"),
    CheckConstraint("log_epoch >= 1", name="ck_receiver_attestation_positive_epoch"),
)

receiver_heads = Table(
    "receiver_heads",
    metadata,
    Column("device_id", String(255), primary_key=True),
    Column("receiver_id", String(255), nullable=False),
    Column("log_epoch", BigInteger, nullable=False),
    Column("previous_attestation_sha256", String(64), nullable=False),
    Column("attestation_sha256", String(64), nullable=False),
    Column("period_id", String(255), nullable=False),
    Column("updated_at_ns", BigInteger, nullable=False),
    CheckConstraint("log_epoch >= 1", name="ck_receiver_head_positive_epoch"),
)

periods = Table(
    "periods",
    metadata,
    Column("device_id", String(255), nullable=False),
    Column("period_id", String(255), nullable=False),
    Column("month_number", Integer, nullable=False),
    Column("period_start_time", BigInteger, nullable=False),
    Column("period_end_time", BigInteger, nullable=False),
    Column("total_fee_cents", BigInteger, nullable=False),
    Column("total_distance_m", BigInteger, nullable=False),
    Column("fallback_intervals", Integer, nullable=False),
    Column("reconciliation_rate_cents_per_m", BigInteger, nullable=False),
    Column("policy_profile_commitment", String(100), nullable=False),
    Column("receiver_attestation_sha256", String(64), nullable=True),
    Column("public_statement_json", Text, nullable=False),
    Column("public_statement_sha256", String(64), nullable=False),
    Column("accepted_at_ns", BigInteger, nullable=False),
    UniqueConstraint("device_id", "period_id", name="uq_period_device_id"),
    CheckConstraint("period_end_time > period_start_time", name="ck_period_positive_window"),
    CheckConstraint("total_fee_cents >= 0", name="ck_period_nonnegative_fee"),
    CheckConstraint("total_distance_m >= 0", name="ck_period_nonnegative_distance"),
    CheckConstraint("fallback_intervals >= 0", name="ck_period_nonnegative_fallback"),
)

month_states = Table(
    "month_states",
    metadata,
    Column("device_id", String(255), nullable=False),
    Column("month_number", Integer, nullable=False),
    Column("periods", Integer, nullable=False, default=0),
    Column("total_fee_cents", BigInteger, nullable=False, default=0),
    Column("total_distance_m", BigInteger, nullable=False, default=0),
    Column("fallback_intervals", Integer, nullable=False, default=0),
    Column("reconciliation_rate_cents_per_m", BigInteger, nullable=False, default=0),
    Column("lifecycle", String(40), nullable=False, default="open"),
    Column("receipt_json", Text, nullable=True),
    Column("receipt_sha256", String(64), nullable=True),
    Column("updated_at_ns", BigInteger, nullable=False),
    UniqueConstraint("device_id", "month_number", name="uq_month_state_device_month"),
    CheckConstraint("periods >= 0", name="ck_month_nonnegative_periods"),
    CheckConstraint("total_fee_cents >= 0", name="ck_month_nonnegative_fee"),
    CheckConstraint("total_distance_m >= 0", name="ck_month_nonnegative_distance"),
    CheckConstraint("fallback_intervals >= 0", name="ck_month_nonnegative_fallback"),
    CheckConstraint(
        "lifecycle IN ('open', 'closed', 'administrative-exception')",
        name="ck_month_lifecycle",
    ),
)

month_attestations = Table(
    "month_attestations",
    metadata,
    Column("device_id", String(255), nullable=False),
    Column("month_number", Integer, nullable=False),
    Column("odometer_start_m", BigInteger, nullable=False),
    Column("odometer_end_m", BigInteger, nullable=False),
    Column("attestation_json", Text, nullable=False),
    Column("attestation_sha256", String(64), nullable=False),
    Column("accepted_at_ns", BigInteger, nullable=False),
    UniqueConstraint("device_id", "month_number", name="uq_attestation_device_month"),
    CheckConstraint("odometer_start_m >= 0", name="ck_attestation_nonnegative_start"),
    CheckConstraint("odometer_end_m >= odometer_start_m", name="ck_attestation_monotonic"),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("event_type", String(80), nullable=False),
    Column("device_id", String(255), nullable=True),
    Column("month_number", Integer, nullable=True),
    Column("period_id", String(255), nullable=True),
    Column("details_json", Text, nullable=False),
    Column("created_at_ns", BigInteger, nullable=False),
)


def _sha256_json(value: dict[str, Any]) -> tuple[str, str]:
    encoded = canonical_json(value)
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


def _previous_month(month_number: int) -> int:
    year, month = divmod(int(month_number), 100)
    return (year - 1) * 100 + 12 if month == 1 else year * 100 + month - 1


def _next_month(month_number: int) -> int:
    year, month = divmod(int(month_number), 100)
    return (year + 1) * 100 + 1 if month == 12 else year * 100 + month + 1


class ChargerStore:
    """One relational state machine for SQLite evaluation and PostgreSQL servers."""

    def __init__(self, *, database_url: str, charger_domain: str) -> None:
        if not database_url:
            raise ChargerStoreError("database_url must not be empty")
        if not charger_domain:
            raise ChargerStoreError("charger_domain must not be empty")
        self.database_url = str(database_url)
        self.charger_domain = str(charger_domain)
        engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
        memory_urls = {
            "sqlite://",
            "sqlite+pysqlite://",
            "sqlite:///:memory:",
            "sqlite+pysqlite:///:memory:",
        }
        if self.database_url in memory_urls:
            engine_kwargs.update(
                {
                    "connect_args": {"check_same_thread": False},
                    "poolclass": StaticPool,
                }
            )
        self.engine: Engine = create_engine(self.database_url, **engine_kwargs)
        self.backend = str(self.engine.dialect.name)
        if self.backend not in {"sqlite", "postgresql"}:
            raise ChargerStoreError("Charger storage supports only SQLite and PostgreSQL")
        if self.backend == "sqlite":
            event.listen(self.engine, "connect", self._configure_sqlite)
        self._initialize()

    @staticmethod
    def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA busy_timeout = 30000")
        cursor.close()

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        connection = self.engine.connect()
        try:
            if self.backend == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        metadata.create_all(self.engine)
        domain_digest = hashlib.sha256(self.charger_domain.encode("utf-8")).hexdigest()
        with self._write() as connection:
            row = connection.execute(
                select(charger_meta).where(charger_meta.c.singleton_id == 1)
            ).first()
            if row is None:
                connection.execute(
                    insert(charger_meta).values(
                        singleton_id=1,
                        schema_version=CHARGER_SCHEMA_VERSION,
                        charger_domain_sha256=domain_digest,
                        created_at_ns=time.time_ns(),
                    )
                )
                return
            current = _row_dict(row)
            if int(current["schema_version"]) != CHARGER_SCHEMA_VERSION:
                raise ChargerStoreError("unsupported Charger database schema version")
            if str(current["charger_domain_sha256"]) != domain_digest:
                raise ChargerStoreError("database is bound to a different Charger domain")

    def close(self) -> None:
        self.engine.dispose()

    def ping(self) -> None:
        try:
            with self.engine.connect() as connection:
                connection.execute(select(charger_meta.c.singleton_id)).scalar_one()
        except SQLAlchemyError as exc:
            raise ChargerStoreError("Charger database is unavailable") from exc

    @property
    def schema_version(self) -> int:
        return CHARGER_SCHEMA_VERSION

    def _audit(
        self,
        connection: Connection,
        *,
        event_type: str,
        device_id: str | None = None,
        month_number: int | None = None,
        period_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            insert(audit_events).values(
                event_type=str(event_type),
                device_id=device_id,
                month_number=month_number,
                period_id=period_id,
                details_json=canonical_json(details or {}),
                created_at_ns=time.time_ns(),
            )
        )

    def _locked_device(self, connection: Connection, device_id: str) -> dict[str, Any]:
        statement = select(devices).where(devices.c.device_id == str(device_id))
        if self.backend == "postgresql":
            statement = statement.with_for_update()
        row = connection.execute(statement).first()
        if row is None:
            raise ChargerNotFound(f"device {device_id!r} not registered")
        return _row_dict(row)

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(devices).where(devices.c.device_id == str(device_id))
            ).first()
        return None if row is None else _row_dict(row)

    def list_device_ids(self) -> list[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(select(devices.c.device_id).order_by(devices.c.device_id)).all()
        return [str(row[0]) for row in rows]

    def register_device(
        self,
        *,
        device_id: str,
        public_key: bytes,
        jurisdiction_id: str,
        token_digest: str,
    ) -> bool:
        if not device_id or not jurisdiction_id:
            raise ChargerStoreError("device_id and jurisdiction_id must not be empty")
        if len(public_key) != 32:
            raise ChargerStoreError("public key must be 32 bytes (raw Ed25519)")
        try:
            with self._write() as connection:
                row = connection.execute(
                    select(devices).where(devices.c.device_id == str(device_id))
                ).first()
                if row is not None:
                    existing = _row_dict(row)
                    identical = (
                        bytes(existing["public_key"]) == bytes(public_key)
                        and str(existing["jurisdiction_id"]) == str(jurisdiction_id)
                        and str(existing["token_digest"]) == str(token_digest)
                    )
                    if not identical:
                        raise ChargerConflict("conflicting device enrollment already exists")
                    return False
                connection.execute(
                    insert(devices).values(
                        device_id=str(device_id),
                        public_key=bytes(public_key),
                        jurisdiction_id=str(jurisdiction_id),
                        token_digest=str(token_digest),
                        created_at_ns=time.time_ns(),
                    )
                )
                self._audit(
                    connection,
                    event_type="device-registered",
                    device_id=str(device_id),
                    details={"jurisdiction_id": str(jurisdiction_id)},
                )
                return True
        except IntegrityError as exc:
            raise ChargerConflict("conflicting device enrollment already exists") from exc

    @staticmethod
    def _validate_receiver_attestation_hash(value: Any, *, field: str) -> str:
        digest = str(value)
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ChargerStoreError(f"{field} must be a lowercase SHA-256 digest")
        return digest

    def _receiver_head_row(
        self, connection: Connection, *, device_id: str, lock: bool
    ) -> dict[str, Any] | None:
        statement = select(receiver_heads).where(
            receiver_heads.c.device_id == str(device_id)
        )
        if lock and self.backend == "postgresql":
            statement = statement.with_for_update()
        row = connection.execute(statement).first()
        return None if row is None else _row_dict(row)

    def receiver_head(self, *, device_id: str) -> dict[str, Any]:
        """Return the Charger-confirmed receiver head or the explicit genesis."""

        if self.get_device(device_id) is None:
            raise ChargerNotFound(f"device {device_id!r} not registered")
        with self.engine.connect() as connection:
            head = self._receiver_head_row(
                connection, device_id=str(device_id), lock=False
            )
        if head is None:
            return {
                "device_id": str(device_id),
                "receiver_id": None,
                "log_epoch": 0,
                "previous_attestation_sha256": SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
                "attestation_sha256": SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
                "period_id": None,
            }
        return {
            "device_id": str(head["device_id"]),
            "receiver_id": str(head["receiver_id"]),
            "log_epoch": int(head["log_epoch"]),
            "previous_attestation_sha256": str(
                head["previous_attestation_sha256"]
            ),
            "attestation_sha256": str(head["attestation_sha256"]),
            "period_id": str(head["period_id"]),
        }

    def anchor_receiver_attestation(
        self, *, attestation: dict[str, Any]
    ) -> dict[str, Any]:
        """Atomically append one exact V5 receiver attestation to its device chain."""

        if attestation.get("schema") != SETTLEMENT_ROOT_ATTESTATION_SCHEMA:
            raise ChargerStoreError("receiver attestation must use the V5 schema")
        device_id = str(attestation.get("device_id", ""))
        receiver_id = str(attestation.get("receiver_id", ""))
        charger_domain = str(attestation.get("charger_domain", ""))
        period_id = str(attestation.get("period_id", ""))
        if not device_id or not receiver_id or not period_id:
            raise ChargerStoreError(
                "receiver attestation device_id, receiver_id, and period_id are required"
            )
        if charger_domain != self.charger_domain:
            raise ChargerStoreError("receiver attestation is bound to another Charger domain")
        try:
            log_epoch = int(attestation["log_epoch"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ChargerStoreError("receiver attestation log_epoch is malformed") from exc
        if log_epoch < 1:
            raise ChargerStoreError("receiver attestation log_epoch must be positive")
        previous_sha256 = self._validate_receiver_attestation_hash(
            attestation.get("previous_attestation_sha256", ""),
            field="previous_attestation_sha256",
        )
        attestation_json, attestation_sha256 = _sha256_json(attestation)
        try:
            with self._write() as connection:
                self._locked_device(connection, device_id)
                exact = connection.execute(
                    select(receiver_attestations).where(
                        receiver_attestations.c.attestation_sha256
                        == attestation_sha256
                    )
                ).first()
                if exact is not None:
                    stored = _row_dict(exact)
                    if str(stored["attestation_json"]) != attestation_json:
                        raise ChargerConflict("receiver attestation hash collision")
                    return {
                        "device_id": str(stored["device_id"]),
                        "receiver_id": str(stored["receiver_id"]),
                        "period_id": str(stored["period_id"]),
                        "log_epoch": int(stored["log_epoch"]),
                        "previous_attestation_sha256": str(
                            stored["previous_attestation_sha256"]
                        ),
                        "attestation_sha256": str(stored["attestation_sha256"]),
                        "settled": bool(stored["settled"]),
                        "idempotent": True,
                    }

                identity_conflict = connection.execute(
                    select(receiver_attestations.c.attestation_sha256).where(
                        receiver_attestations.c.device_id == device_id,
                        receiver_attestations.c.period_id == period_id,
                    )
                ).first()
                if identity_conflict is not None:
                    raise ChargerConflict(
                        "receiver period is already anchored with another attestation"
                    )

                head = self._receiver_head_row(
                    connection, device_id=device_id, lock=True
                )
                if head is None:
                    if log_epoch != 1:
                        raise ChargerConflict("receiver genesis must use log_epoch 1")
                    if previous_sha256 != SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256:
                        raise ChargerConflict(
                            "receiver genesis has an invalid previous attestation hash"
                        )
                else:
                    if str(head["receiver_id"]) != receiver_id:
                        raise ChargerConflict(
                            "receiver device chain is bound to another receiver identity"
                        )
                    if log_epoch != int(head["log_epoch"]) + 1:
                        raise ChargerConflict(
                            "receiver attestation epoch does not extend the current head"
                        )
                    if previous_sha256 != str(head["attestation_sha256"]):
                        raise ChargerConflict(
                            "receiver attestation does not extend the current head hash"
                        )

                now = time.time_ns()
                connection.execute(
                    insert(receiver_attestations).values(
                        device_id=device_id,
                        receiver_id=receiver_id,
                        charger_domain=charger_domain,
                        period_id=period_id,
                        log_epoch=log_epoch,
                        previous_attestation_sha256=previous_sha256,
                        attestation_sha256=attestation_sha256,
                        attestation_json=attestation_json,
                        settled=False,
                        anchored_at_ns=now,
                        settled_at_ns=None,
                    )
                )
                if head is None:
                    connection.execute(
                        insert(receiver_heads).values(
                            device_id=device_id,
                            receiver_id=receiver_id,
                            log_epoch=log_epoch,
                            previous_attestation_sha256=previous_sha256,
                            attestation_sha256=attestation_sha256,
                            period_id=period_id,
                            updated_at_ns=now,
                        )
                    )
                else:
                    result = connection.execute(
                        update(receiver_heads)
                        .where(
                            receiver_heads.c.device_id == device_id,
                            receiver_heads.c.log_epoch == int(head["log_epoch"]),
                            receiver_heads.c.attestation_sha256
                            == str(head["attestation_sha256"]),
                        )
                        .values(
                            log_epoch=log_epoch,
                            previous_attestation_sha256=previous_sha256,
                            attestation_sha256=attestation_sha256,
                            period_id=period_id,
                            updated_at_ns=now,
                        )
                    )
                    if result.rowcount != 1:
                        raise ChargerConflict(
                            "receiver head changed during attestation anchoring"
                        )
                self._audit(
                    connection,
                    event_type="receiver-attestation-anchored",
                    device_id=device_id,
                    period_id=period_id,
                    details={
                        "receiver_id": receiver_id,
                        "log_epoch": log_epoch,
                        "attestation_sha256": attestation_sha256,
                    },
                )
        except IntegrityError as exc:
            raise ChargerConflict("receiver attestation conflicts with the current chain") from exc
        return {
            "device_id": device_id,
            "receiver_id": receiver_id,
            "period_id": period_id,
            "log_epoch": log_epoch,
            "previous_attestation_sha256": previous_sha256,
            "attestation_sha256": attestation_sha256,
            "settled": False,
            "idempotent": False,
        }

    def require_unsettled_receiver_attestation(
        self,
        *,
        device_id: str,
        period_id: str,
        attestation: dict[str, Any],
    ) -> None:
        """Read-only exact-anchor preflight before proof verification.

        ``accept_period`` repeats these checks under its write transaction. This
        method only rejects stale or missing anchors before expensive work; it
        is not the final authorization decision.
        """

        expected_device_id = str(device_id)
        expected_period_id = str(period_id)
        if str(attestation.get("device_id", "")) != expected_device_id:
            raise ChargerConflict(
                "receiver root attestation is bound to another device"
            )
        if str(attestation.get("period_id", "")) != expected_period_id:
            raise ChargerConflict(
                "receiver root attestation is bound to another period"
            )
        attestation_json, attestation_sha256 = _sha256_json(attestation)
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    select(
                        receiver_attestations.c.attestation_json,
                        receiver_attestations.c.settled,
                    ).where(
                        receiver_attestations.c.device_id == expected_device_id,
                        receiver_attestations.c.period_id == expected_period_id,
                        receiver_attestations.c.attestation_sha256
                        == attestation_sha256,
                    )
                ).first()
        except SQLAlchemyError as exc:
            raise ChargerStoreError(
                "receiver attestation preflight failed"
            ) from exc
        if row is None:
            raise ChargerConflict(
                "receiver root attestation is not anchored for this period"
            )
        anchored = _row_dict(row)
        if str(anchored["attestation_json"]) != attestation_json:
            raise ChargerConflict(
                "receiver root attestation does not match the anchored bytes"
            )
        if bool(anchored["settled"]):
            raise ChargerConflict(
                "receiver root attestation has already been settled"
            )

    def _month_state(
        self,
        connection: Connection,
        *,
        device_id: str,
        month_number: int,
        create: bool,
    ) -> dict[str, Any] | None:
        statement = select(month_states).where(
            month_states.c.device_id == str(device_id),
            month_states.c.month_number == int(month_number),
        )
        if self.backend == "postgresql":
            statement = statement.with_for_update()
        row = connection.execute(statement).first()
        if row is None and create:
            connection.execute(
                insert(month_states).values(
                    device_id=str(device_id),
                    month_number=int(month_number),
                    periods=0,
                    total_fee_cents=0,
                    total_distance_m=0,
                    fallback_intervals=0,
                    reconciliation_rate_cents_per_m=0,
                    lifecycle="open",
                    receipt_json=None,
                    receipt_sha256=None,
                    updated_at_ns=time.time_ns(),
                )
            )
            row = connection.execute(statement).first()
        return None if row is None else _row_dict(row)

    def accept_period(
        self,
        *,
        device_id: str,
        public: dict[str, Any],
        month_number: int,
        reconciliation_rate_cents_per_m: int,
        root_attestation: dict[str, Any] | None = None,
        allow_unanchored: bool = False,
    ) -> tuple[str, str]:
        period_id = str(public["period_id"])
        month_id = str(public["month_id"])
        start = int(public["period_start_time"])
        end = int(public["period_end_time"])
        public_json, public_sha256 = _sha256_json(public)
        anchored_sha256: str | None = None
        attestation_json: str | None = None
        if root_attestation is not None:
            attestation_json, anchored_sha256 = _sha256_json(root_attestation)
        try:
            with self._write() as connection:
                self._locked_device(connection, device_id)
                anchored: dict[str, Any] | None = None
                if root_attestation is None:
                    if not allow_unanchored:
                        raise ChargerConflict(
                            "period requires an anchored receiver root attestation"
                        )
                else:
                    statement = select(receiver_attestations).where(
                        receiver_attestations.c.device_id == str(device_id),
                        receiver_attestations.c.period_id == period_id,
                        receiver_attestations.c.attestation_sha256 == anchored_sha256,
                    )
                    if self.backend == "postgresql":
                        statement = statement.with_for_update()
                    anchored_row = connection.execute(statement).first()
                    if anchored_row is None:
                        raise ChargerConflict(
                            "receiver root attestation is not anchored for this period"
                        )
                    anchored = _row_dict(anchored_row)
                    if str(anchored["attestation_json"]) != attestation_json:
                        raise ChargerConflict(
                            "receiver root attestation does not match the anchored bytes"
                        )
                    if bool(anchored["settled"]):
                        raise ChargerConflict(
                            "receiver root attestation has already been settled"
                        )
                    if str(root_attestation.get("charger_domain", "")) != self.charger_domain:
                        raise ChargerConflict(
                            "receiver root attestation is bound to another Charger domain"
                        )
                    if str(root_attestation.get("device_id", "")) != str(device_id):
                        raise ChargerConflict(
                            "receiver root attestation is bound to another device"
                        )
                    if str(root_attestation.get("period_id", "")) != period_id:
                        raise ChargerConflict(
                            "receiver root attestation is bound to another period"
                        )
                    if str(root_attestation.get("receiver_fix_root", "")) != str(
                        public.get("receiver_fix_root", "")
                    ):
                        raise ChargerConflict(
                            "receiver root attestation does not match the public receiver root"
                        )
                    if str(
                        root_attestation.get("device_attestation_commitment", "")
                    ) != str(public.get("device_attestation_commitment", "")):
                        raise ChargerConflict(
                            "receiver root attestation does not match the public device commitment"
                        )
                month = self._month_state(
                    connection,
                    device_id=device_id,
                    month_number=month_number,
                    create=True,
                )
                assert month is not None
                if str(month["lifecycle"]) != "open":
                    raise ChargerConflict("billing month no longer accepts period submissions")
                replay = connection.execute(
                    select(periods.c.period_id).where(
                        periods.c.device_id == str(device_id),
                        periods.c.period_id == period_id,
                    )
                ).first()
                if replay is not None:
                    raise ChargerConflict("period already accepted")
                overlap = connection.execute(
                    select(periods.c.period_id).where(
                        periods.c.device_id == str(device_id),
                        periods.c.period_start_time < end,
                        periods.c.period_end_time > start,
                    ).limit(1)
                ).first()
                if overlap is not None:
                    raise ChargerConflict(
                        "period time window overlaps an accepted period for this device"
                    )
                connection.execute(
                    insert(periods).values(
                        device_id=str(device_id),
                        period_id=period_id,
                        month_number=int(month_number),
                        period_start_time=start,
                        period_end_time=end,
                        total_fee_cents=int(public["total_fee_cents"]),
                        total_distance_m=int(public["total_distance_m"]),
                        fallback_intervals=int(public.get("fallback_intervals", 0)),
                        reconciliation_rate_cents_per_m=int(
                            reconciliation_rate_cents_per_m
                        ),
                        policy_profile_commitment=str(
                            public.get("policy_profile_commitment", "")
                        ),
                        receiver_attestation_sha256=anchored_sha256,
                        public_statement_json=public_json,
                        public_statement_sha256=public_sha256,
                        accepted_at_ns=time.time_ns(),
                    )
                )
                connection.execute(
                    update(month_states)
                    .where(
                        month_states.c.device_id == str(device_id),
                        month_states.c.month_number == int(month_number),
                    )
                    .values(
                        periods=int(month["periods"]) + 1,
                        total_fee_cents=int(month["total_fee_cents"])
                        + int(public["total_fee_cents"]),
                        total_distance_m=int(month["total_distance_m"])
                        + int(public["total_distance_m"]),
                        fallback_intervals=int(month["fallback_intervals"])
                        + int(public.get("fallback_intervals", 0)),
                        reconciliation_rate_cents_per_m=max(
                            int(month["reconciliation_rate_cents_per_m"]),
                            int(reconciliation_rate_cents_per_m),
                        ),
                        updated_at_ns=time.time_ns(),
                    )
                )
                if anchored is not None:
                    settled = connection.execute(
                        update(receiver_attestations)
                        .where(
                            receiver_attestations.c.attestation_sha256
                            == anchored_sha256,
                            receiver_attestations.c.settled.is_(False),
                        )
                        .values(settled=True, settled_at_ns=time.time_ns())
                    )
                    if settled.rowcount != 1:
                        raise ChargerConflict(
                            "receiver root attestation settlement raced with another request"
                        )
                self._audit(
                    connection,
                    event_type="period-accepted",
                    device_id=str(device_id),
                    month_number=int(month_number),
                    period_id=period_id,
                    details={"public_statement_sha256": public_sha256},
                )
        except IntegrityError as exc:
            raise ChargerConflict("period already accepted") from exc
        return period_id, month_id

    def month_totals(self, *, device_id: str, month_number: int) -> dict[str, int]:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(month_states).where(
                    month_states.c.device_id == str(device_id),
                    month_states.c.month_number == int(month_number),
                )
            ).first()
        if row is None:
            return {
                "periods": 0,
                "total_fee_cents": 0,
                "total_distance_m": 0,
                "fallback_intervals": 0,
            }
        state = _row_dict(row)
        return {
            "periods": int(state["periods"]),
            "total_fee_cents": int(state["total_fee_cents"]),
            "total_distance_m": int(state["total_distance_m"]),
            "fallback_intervals": int(state["fallback_intervals"]),
        }

    def month_rate(self, *, device_id: str, month_number: int) -> int | None:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(month_states.c.reconciliation_rate_cents_per_m).where(
                    month_states.c.device_id == str(device_id),
                    month_states.c.month_number == int(month_number),
                )
            ).scalar_one_or_none()
        return None if value is None or int(value) <= 0 else int(value)

    def get_attestation(self, *, device_id: str, month_number: int) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(month_attestations.c.attestation_json).where(
                    month_attestations.c.device_id == str(device_id),
                    month_attestations.c.month_number == int(month_number),
                )
            ).scalar_one_or_none()
        return None if value is None else dict(json.loads(str(value)))

    def put_attestation(
        self,
        *,
        device_id: str,
        month_number: int,
        attestation: dict[str, Any],
    ) -> bool:
        encoded, digest = _sha256_json(attestation)
        start = int(attestation["odometer_start_m"])
        end = int(attestation["odometer_end_m"])
        try:
            with self._write() as connection:
                self._locked_device(connection, device_id)
                month = self._month_state(
                    connection,
                    device_id=device_id,
                    month_number=month_number,
                    create=True,
                )
                assert month is not None
                if str(month["lifecycle"]) != "open":
                    raise ChargerConflict("billing month no longer accepts odometer attestations")
                existing = connection.execute(
                    select(month_attestations).where(
                        month_attestations.c.device_id == str(device_id),
                        month_attestations.c.month_number == int(month_number),
                    )
                ).first()
                if existing is not None:
                    current = _row_dict(existing)
                    if str(current["attestation_sha256"]) != digest:
                        raise ChargerConflict(
                            "conflicting odometer attestation already recorded"
                        )
                    return False
                latest = connection.execute(
                    select(month_attestations)
                    .where(month_attestations.c.device_id == str(device_id))
                    .order_by(month_attestations.c.month_number.desc())
                    .limit(1)
                ).first()
                if latest is not None:
                    latest_month = int(latest._mapping["month_number"])
                    if int(month_number) != _next_month(latest_month):
                        raise ChargerConflict(
                            "odometer attestation must extend the next calendar month"
                        )
                    if int(latest._mapping["odometer_end_m"]) != start:
                        raise ChargerConflict(
                            "odometer month chain does not continue the previous boundary"
                        )
                connection.execute(
                    insert(month_attestations).values(
                        device_id=str(device_id),
                        month_number=int(month_number),
                        odometer_start_m=start,
                        odometer_end_m=end,
                        attestation_json=encoded,
                        attestation_sha256=digest,
                        accepted_at_ns=time.time_ns(),
                    )
                )
                self._audit(
                    connection,
                    event_type="month-attestation-accepted",
                    device_id=str(device_id),
                    month_number=int(month_number),
                    details={"attestation_sha256": digest},
                )
                return True
        except IntegrityError as exc:
            raise ChargerConflict("conflicting odometer attestation already recorded") from exc

    def close_month(
        self,
        *,
        device_id: str,
        month_id: str,
        month_number: int,
        default_reconciliation_rate: int,
    ) -> dict[str, Any]:
        with self._write() as connection:
            self._locked_device(connection, device_id)
            month = self._month_state(
                connection,
                device_id=device_id,
                month_number=month_number,
                create=True,
            )
            assert month is not None
            if month["receipt_json"] is not None:
                receipt = dict(json.loads(str(month["receipt_json"])))
                receipt["idempotent"] = True
                return receipt
            attestation_row = connection.execute(
                select(month_attestations).where(
                    month_attestations.c.device_id == str(device_id),
                    month_attestations.c.month_number == int(month_number),
                )
            ).first()
            if attestation_row is None:
                receipt = {
                    "ok": False,
                    "status": "administrative-exception",
                    "device_id": str(device_id),
                    "month_id": str(month_id),
                    "month_id_field": int(month_number),
                    "reason": "missing_monthly_odometer_attestation",
                    "periods": int(month["periods"]),
                    "accounted_distance_m": int(month["total_distance_m"]),
                    "accepted_period_fee_cents": int(month["total_fee_cents"]),
                    "immutable": True,
                }
                return self._store_receipt(
                    connection, month=month, receipt=receipt, lifecycle="administrative-exception"
                )
            attestation = _row_dict(attestation_row)
            rate = max(
                int(month["reconciliation_rate_cents_per_m"]),
                int(default_reconciliation_rate),
            )
            try:
                result = reconcile_month_v6(
                    monthly_odometer_start_m=int(attestation["odometer_start_m"]),
                    monthly_odometer_end_m=int(attestation["odometer_end_m"]),
                    accounted_distance_m=int(month["total_distance_m"]),
                    accepted_period_fee_cents=int(month["total_fee_cents"]),
                    r_max_cents_per_m=rate,
                    tolerance_m=0,
                )
            except (TypeError, ValueError, OverflowError) as exc:
                receipt = {
                    "ok": False,
                    "status": "administrative-exception",
                    "device_id": str(device_id),
                    "month_id": str(month_id),
                    "month_id_field": int(month_number),
                    "reason": "inconsistent_monthly_odometer_accounting",
                    "detail": str(exc),
                    "immutable": True,
                }
                return self._store_receipt(
                    connection, month=month, receipt=receipt, lifecycle="administrative-exception"
                )
            commitments = sorted(
                str(row[0])
                for row in connection.execute(
                    select(periods.c.policy_profile_commitment)
                    .where(
                        periods.c.device_id == str(device_id),
                        periods.c.month_number == int(month_number),
                    )
                    .distinct()
                ).all()
            )
            receipt = {
                "ok": True,
                "status": "closed",
                "device_id": str(device_id),
                "month_id": str(month_id),
                "month_id_field": int(month_number),
                "reconciliation_rate_cents_per_m": rate,
                "profile_commitments": commitments,
                "periods": int(month["periods"]),
                **result,
                "immutable": True,
                "idempotent": False,
            }
            return self._store_receipt(
                connection, month=month, receipt=receipt, lifecycle="closed"
            )

    def _store_receipt(
        self,
        connection: Connection,
        *,
        month: dict[str, Any],
        receipt: dict[str, Any],
        lifecycle: str,
    ) -> dict[str, Any]:
        body, digest = _sha256_json(receipt)
        stored = {**receipt, "receipt_sha256": digest}
        stored_json = canonical_json(stored)
        connection.execute(
            update(month_states)
            .where(
                month_states.c.device_id == str(month["device_id"]),
                month_states.c.month_number == int(month["month_number"]),
            )
            .values(
                lifecycle=str(lifecycle),
                receipt_json=stored_json,
                receipt_sha256=digest,
                updated_at_ns=time.time_ns(),
            )
        )
        self._audit(
            connection,
            event_type="month-closed" if lifecycle == "closed" else "month-administrative-exception",
            device_id=str(month["device_id"]),
            month_number=int(month["month_number"]),
            details={"receipt_sha256": digest, "receipt_body_sha256": hashlib.sha256(body.encode()).hexdigest()},
        )
        return stored

    def reconciliation_snapshot(
        self, *, device_id: str, month_number: int
    ) -> tuple[dict[str, Any], dict[str, int], int | None]:
        attestation = self.get_attestation(device_id=device_id, month_number=month_number)
        if attestation is None:
            raise ChargerNotFound("no odometer attestation for this device and month")
        return (
            attestation,
            self.month_totals(device_id=device_id, month_number=month_number),
            self.month_rate(device_id=device_id, month_number=month_number),
        )

    def missing_attestations(self, *, month_id: str, month_number: int) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for device_id in self.list_device_ids():
            if self.get_attestation(device_id=device_id, month_number=month_number) is not None:
                continue
            month = self.month_totals(device_id=device_id, month_number=month_number)
            missing.append(
                {
                    "device_id": device_id,
                    "month_id": month_id,
                    "periods": int(month["periods"]),
                    "covered_distance_m": int(month["total_distance_m"]),
                    "period_fee_cents": int(month["total_fee_cents"]),
                    "reason": "missing_monthly_odometer_attestation",
                    "administrative_path": True,
                }
            )
        return missing

    def aggregate_month(self, *, month_number: int) -> dict[str, int] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    func.sum(month_states.c.periods),
                    func.sum(month_states.c.total_fee_cents),
                    func.sum(month_states.c.total_distance_m),
                    func.sum(month_states.c.fallback_intervals),
                ).where(month_states.c.month_number == int(month_number))
            ).first()
        if row is None or row[0] is None or int(row[0]) == 0:
            return None
        return {
            "periods": int(row[0]),
            "total_fee_cents": int(row[1]),
            "total_distance_m": int(row[2]),
            "fallback_intervals": int(row[3]),
        }

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as connection:
            return {
                "registered_devices": int(
                    connection.execute(select(func.count()).select_from(devices)).scalar_one()
                ),
                "accepted_periods": int(
                    connection.execute(select(func.count()).select_from(periods)).scalar_one()
                ),
                "months": int(
                    connection.execute(select(func.count()).select_from(month_states)).scalar_one()
                ),
            }

    def reset(self) -> None:
        try:
            with self._write() as connection:
                for table in (
                    audit_events,
                    periods,
                    receiver_attestations,
                    receiver_heads,
                    month_attestations,
                    month_states,
                    devices,
                ):
                    connection.execute(delete(table))
                self._audit(connection, event_type="test-reset")
        except SQLAlchemyError as exc:
            raise ChargerStoreError(f"Charger reset failed: {exc}") from exc
