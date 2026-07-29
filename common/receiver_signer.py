"""Persistent receiver-owned log and root-attestation service primitives.

The receiver process is the only component allowed to call ``seal_period``.
Ordinary provers can read attestations for already sealed logs, but cannot ask
the signer to endorse a caller-selected root or billing statement.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from common.settlement import (
    SNARK_FIELD,
    SETTLEMENT_POSITION_VALIDITY_RULE,
    SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    ReceiverFix,
    canonical_month_window,
    canonical_json,
    derive_position_valid,
    field_from_text,
    make_device_attestation_commitment,
    receiver_attestation_sha256,
    sign_monthly_odometer_attestation,
    sign_receiver_fix,
    sign_receiver_root_attestation,
    verify_monthly_odometer_attestation,
    verify_receiver_fix_signature,
    verify_receiver_root_attestation,
)
from common.settlement_v6 import compute_receiver_fix_root_v6


RECEIVER_SIGNER_APPLICATION_ID = 0x5742594C  # ASCII "WBYL"
RECEIVER_SIGNER_SCHEMA_VERSION = 2

_RECEIVER_SCHEMA_SQL = """
CREATE TABLE receiver_logs (
    log_epoch INTEGER PRIMARY KEY AUTOINCREMENT,
    receiver_id TEXT NOT NULL,
    charger_domain TEXT NOT NULL,
    device_id TEXT NOT NULL,
    period_id TEXT NOT NULL,
    period_start_time INTEGER NOT NULL,
    period_end_time INTEGER NOT NULL,
    odometer_start_m INTEGER NOT NULL,
    odometer_end_m INTEGER NOT NULL,
    fix_count INTEGER NOT NULL,
    policy_profile_commitment TEXT NOT NULL,
    receiver_fix_root TEXT NOT NULL,
    fixes_json TEXT NOT NULL,
    position_valid_json TEXT NOT NULL,
    position_validity_rule TEXT NOT NULL,
    previous_attestation_sha256 TEXT NOT NULL,
    attestation_sha256 TEXT NOT NULL,
    attestation_json TEXT NOT NULL,
    log_sha256 TEXT NOT NULL,
    UNIQUE(device_id, period_id)
);
CREATE INDEX receiver_logs_device_epoch
    ON receiver_logs(device_id, log_epoch);
CREATE TABLE receiver_months (
    month_epoch INTEGER PRIMARY KEY AUTOINCREMENT,
    receiver_id TEXT NOT NULL,
    charger_domain TEXT NOT NULL,
    device_id TEXT NOT NULL,
    month_id TEXT NOT NULL,
    odometer_start_m INTEGER NOT NULL,
    odometer_end_m INTEGER NOT NULL,
    attestation_json TEXT NOT NULL,
    UNIQUE(device_id, month_id)
);
CREATE INDEX receiver_months_device_epoch
    ON receiver_months(device_id, month_epoch);
CREATE TABLE receiver_meta (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    receiver_id TEXT NOT NULL,
    charger_domain TEXT NOT NULL,
    device_id TEXT NOT NULL,
    device_attestation_commitment TEXT NOT NULL,
    policy_profile_commitment TEXT NOT NULL,
    root_attestation_schema TEXT NOT NULL,
    position_validity_rule TEXT NOT NULL
);
"""

_EXPECTED_SCHEMA_OBJECTS = {
    ("table", "receiver_logs", "receiver_logs"),
    ("index", "receiver_logs_device_epoch", "receiver_logs"),
    ("table", "receiver_months", "receiver_months"),
    ("index", "receiver_months_device_epoch", "receiver_months"),
    ("table", "receiver_meta", "receiver_meta"),
}

_EXPECTED_COLUMNS: dict[str, tuple[tuple[str, str, int, int, int], ...]] = {
    "receiver_logs": (
        ("log_epoch", "INTEGER", 0, 1, 0),
        ("receiver_id", "TEXT", 1, 0, 0),
        ("charger_domain", "TEXT", 1, 0, 0),
        ("device_id", "TEXT", 1, 0, 0),
        ("period_id", "TEXT", 1, 0, 0),
        ("period_start_time", "INTEGER", 1, 0, 0),
        ("period_end_time", "INTEGER", 1, 0, 0),
        ("odometer_start_m", "INTEGER", 1, 0, 0),
        ("odometer_end_m", "INTEGER", 1, 0, 0),
        ("fix_count", "INTEGER", 1, 0, 0),
        ("policy_profile_commitment", "TEXT", 1, 0, 0),
        ("receiver_fix_root", "TEXT", 1, 0, 0),
        ("fixes_json", "TEXT", 1, 0, 0),
        ("position_valid_json", "TEXT", 1, 0, 0),
        ("position_validity_rule", "TEXT", 1, 0, 0),
        ("previous_attestation_sha256", "TEXT", 1, 0, 0),
        ("attestation_sha256", "TEXT", 1, 0, 0),
        ("attestation_json", "TEXT", 1, 0, 0),
        ("log_sha256", "TEXT", 1, 0, 0),
    ),
    "receiver_months": (
        ("month_epoch", "INTEGER", 0, 1, 0),
        ("receiver_id", "TEXT", 1, 0, 0),
        ("charger_domain", "TEXT", 1, 0, 0),
        ("device_id", "TEXT", 1, 0, 0),
        ("month_id", "TEXT", 1, 0, 0),
        ("odometer_start_m", "INTEGER", 1, 0, 0),
        ("odometer_end_m", "INTEGER", 1, 0, 0),
        ("attestation_json", "TEXT", 1, 0, 0),
    ),
    "receiver_meta": (
        ("singleton_id", "INTEGER", 0, 1, 0),
        ("receiver_id", "TEXT", 1, 0, 0),
        ("charger_domain", "TEXT", 1, 0, 0),
        ("device_id", "TEXT", 1, 0, 0),
        ("device_attestation_commitment", "TEXT", 1, 0, 0),
        ("policy_profile_commitment", "TEXT", 1, 0, 0),
        ("root_attestation_schema", "TEXT", 1, 0, 0),
        ("position_validity_rule", "TEXT", 1, 0, 0),
    ),
}


class ReceiverSignerError(RuntimeError):
    """Raised when a receiver log operation must fail closed."""


def validate_position_valid(
    fixes: Sequence[ReceiverFix], position_valid: Sequence[bool]
) -> list[bool]:
    """Validate stored flags against the canonical signed-status derivation."""

    if len(position_valid) != len(fixes) - 1:
        raise ReceiverSignerError("expected one position_valid flag per interval")
    flags: list[bool] = []
    for index, flag in enumerate(position_valid):
        if type(flag) is not bool:
            raise ReceiverSignerError(f"position_valid[{index}] must be bool")
        flags.append(flag)
    try:
        expected = derive_position_valid(list(fixes))
    except ValueError as exc:
        raise ReceiverSignerError(str(exc)) from exc
    if flags != expected:
        raise ReceiverSignerError(
            "position_valid is inconsistent with the signed receiver status"
        )
    return flags


def derive_receiver_position_valid(fixes: Sequence[ReceiverFix]) -> list[bool]:
    """Derive fail-closed V6 interval validity inside the signer boundary."""

    try:
        return derive_position_valid(list(fixes))
    except ValueError as exc:
        raise ReceiverSignerError(str(exc)) from exc


def receiver_log_body(
    *,
    receiver_id: str,
    charger_domain: str,
    device_id: str,
    period_id: str,
    fixes_payload: Sequence[dict[str, Any]],
    position_valid: Sequence[bool],
    policy_profile_commitment: int | str,
    receiver_fix_root: int | str,
    device_attestation_commitment: str,
    position_validity_rule: str = SETTLEMENT_POSITION_VALIDITY_RULE,
) -> dict[str, Any]:
    return {
        "receiver_id": str(receiver_id),
        "charger_domain": str(charger_domain),
        "device_id": str(device_id),
        "period_id": str(period_id),
        "fixes": list(fixes_payload),
        "position_valid": list(position_valid),
        "policy_profile_commitment": str(policy_profile_commitment),
        "receiver_fix_root": str(receiver_fix_root),
        "device_attestation_commitment": str(device_attestation_commitment),
        "position_validity_rule": str(position_validity_rule),
    }


def receiver_log_sha256(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


class ReceiverSignerStore:
    """Append-only SQLite receiver log backed by one Ed25519 identity."""

    def __init__(
        self,
        *,
        database_path: Path,
        private_key_bytes: bytes,
        receiver_id: str,
        device_id: str,
        charger_domain: str,
        policy_profile_commitment: int,
    ) -> None:
        if len(private_key_bytes) != 32:
            raise ReceiverSignerError("receiver Ed25519 seed must be exactly 32 bytes")
        if not receiver_id:
            raise ReceiverSignerError("receiver_id must not be empty")
        if not device_id:
            raise ReceiverSignerError("device_id must not be empty")
        if not charger_domain:
            raise ReceiverSignerError("charger_domain must not be empty")
        if not Path(database_path).is_absolute():
            raise ReceiverSignerError("receiver database path must be absolute")
        if not 0 <= int(policy_profile_commitment) < SNARK_FIELD:
            raise ReceiverSignerError(
                "canonical policy profile commitment is outside the SNARK field"
            )
        self.database_path = Path(database_path)
        self.private_key_bytes = bytes(private_key_bytes)
        self.receiver_id = str(receiver_id)
        self.device_id = str(device_id)
        self.charger_domain = str(charger_domain)
        self.policy_profile_commitment = int(policy_profile_commitment)
        os.umask(0o077)
        self.database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._database_was_empty = self._prepare_database_file()
        private_key = Ed25519PrivateKey.from_private_bytes(self.private_key_bytes)
        self.public_key_bytes = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.device_attestation_commitment = make_device_attestation_commitment(
            self.public_key_bytes
        )
        self._initialize()

    def _prepare_database_file(self) -> bool:
        """Create a guarded SQLite file inside an owner-only state directory."""

        parent_stat = os.lstat(self.database_path.parent)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ReceiverSignerError("receiver state parent must be a real directory")
        if parent_stat.st_uid != os.geteuid():
            raise ReceiverSignerError("receiver state directory owner mismatch")
        if stat.S_IMODE(parent_stat.st_mode) != 0o700:
            raise ReceiverSignerError("receiver state directory must be mode 0700")
        try:
            descriptor = os.open(
                self.database_path,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            was_empty = True
        except FileExistsError:
            try:
                descriptor = os.open(
                    self.database_path,
                    os.O_RDWR
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
            except OSError as exc:
                raise ReceiverSignerError(f"cannot securely open receiver database: {exc}") from exc
            database_stat = os.fstat(descriptor)
            if not stat.S_ISREG(database_stat.st_mode):
                os.close(descriptor)
                raise ReceiverSignerError("receiver database path must be a regular file")
            if database_stat.st_uid != os.geteuid():
                os.close(descriptor)
                raise ReceiverSignerError("receiver database owner mismatch")
            if stat.S_IMODE(database_stat.st_mode) != 0o600:
                os.close(descriptor)
                raise ReceiverSignerError(
                    "receiver database must be mode 0600"
                )
            if database_stat.st_nlink != 1:
                os.close(descriptor)
                raise ReceiverSignerError("receiver database must not have hard links")
            was_empty = database_stat.st_size == 0
        os.close(descriptor)
        self._verify_database_files()
        return was_empty

    def _verify_database_files(self) -> None:
        """Reject replaced or over-permissive SQLite main/sidecar files."""

        for path in (
            self.database_path,
            Path(str(self.database_path) + "-wal"),
            Path(str(self.database_path) + "-shm"),
            Path(str(self.database_path) + "-journal"),
        ):
            try:
                descriptor = os.open(
                    path,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                )
            except FileNotFoundError:
                if path == self.database_path:
                    raise ReceiverSignerError("receiver database disappeared")
                continue
            except OSError as exc:
                raise ReceiverSignerError(f"cannot securely inspect SQLite file {path.name}: {exc}") from exc
            try:
                file_stat = os.fstat(descriptor)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise ReceiverSignerError(f"SQLite file {path.name} is not regular")
                if file_stat.st_uid != os.geteuid():
                    raise ReceiverSignerError(f"SQLite file {path.name} owner mismatch")
                if stat.S_IMODE(file_stat.st_mode) != 0o600:
                    raise ReceiverSignerError(f"SQLite file {path.name} must be mode 0600")
                if file_stat.st_nlink != 1:
                    raise ReceiverSignerError(f"SQLite file {path.name} must not have hard links")
            finally:
                os.close(descriptor)

    def _connect(self) -> sqlite3.Connection:
        self._verify_database_files()
        database_uri = (
            "file:" + quote(str(self.database_path), safe="/") + "?mode=rw"
        )
        connection = sqlite3.connect(database_uri, uri=True, timeout=30.0)
        connection.row_factory = sqlite3.Row
        required_configs = (
            ("SQLITE_DBCONFIG_DEFENSIVE", True),
            ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", False),
            ("SQLITE_DBCONFIG_ENABLE_TRIGGER", False),
            ("SQLITE_DBCONFIG_ENABLE_VIEW", False),
            ("SQLITE_DBCONFIG_ENABLE_LOAD_EXTENSION", False),
            ("SQLITE_DBCONFIG_DQS_DDL", False),
            ("SQLITE_DBCONFIG_DQS_DML", False),
        )
        if not hasattr(connection, "setconfig"):
            connection.close()
            raise ReceiverSignerError("Python SQLite defensive configuration is unavailable")
        for name, enabled in required_configs:
            option = getattr(sqlite3, name, None)
            if option is None:
                connection.close()
                raise ReceiverSignerError(f"required SQLite option is unavailable: {name}")
            connection.setconfig(option, enabled)
            if bool(connection.getconfig(option)) is not enabled:
                connection.close()
                raise ReceiverSignerError(f"SQLite refused defensive option: {name}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA temp_store = MEMORY")
        journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
        if journal_mode.lower() != "wal":
            connection.close()
            raise ReceiverSignerError("receiver database must use SQLite WAL mode")
        self._verify_database_files()
        return connection

    def _assert_canonical_schema(self, connection: sqlite3.Connection) -> None:
        """Reject schema confusion, trigger injection, and unsupported migrations."""

        application_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if application_id != RECEIVER_SIGNER_APPLICATION_ID:
            raise ReceiverSignerError("receiver database application_id is unsupported")
        if user_version != RECEIVER_SIGNER_SCHEMA_VERSION:
            raise ReceiverSignerError("receiver database schema version is unsupported")

        databases = {
            str(row[1]): str(row[2])
            for row in connection.execute("PRAGMA database_list").fetchall()
        }
        if "main" not in databases or set(databases) - {"main", "temp"}:
            raise ReceiverSignerError("receiver database must not attach other databases")
        if databases.get("temp", ""):
            raise ReceiverSignerError("receiver temporary database must remain in memory")

        forbidden = connection.execute(
            "SELECT type, name FROM sqlite_schema "
            "WHERE type IN ('trigger', 'view') LIMIT 1"
        ).fetchone()
        if forbidden is not None:
            raise ReceiverSignerError(
                f"receiver database contains forbidden {forbidden['type']}: "
                f"{forbidden['name']}"
            )
        temp_forbidden = connection.execute(
            "SELECT type, name FROM temp.sqlite_schema "
            "WHERE type IN ('trigger', 'view') LIMIT 1"
        ).fetchone()
        if temp_forbidden is not None:
            raise ReceiverSignerError(
                f"receiver database contains forbidden temporary "
                f"{temp_forbidden['type']}: {temp_forbidden['name']}"
            )
        objects = {
            (str(row["type"]), str(row["name"]), str(row["tbl_name"]))
            for row in connection.execute(
                "SELECT type, name, tbl_name FROM sqlite_schema "
                "WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if objects != _EXPECTED_SCHEMA_OBJECTS:
            raise ReceiverSignerError("receiver database schema objects are not canonical")

        for table, expected in _EXPECTED_COLUMNS.items():
            actual = tuple(
                (
                    str(row["name"]),
                    str(row["type"]).upper(),
                    int(row["notnull"]),
                    int(row["pk"]),
                    int(row["hidden"]),
                )
                for row in connection.execute(
                    f"PRAGMA table_xinfo({table})"
                ).fetchall()
            )
            if actual != expected:
                raise ReceiverSignerError(
                    f"receiver database table schema is not canonical: {table}"
                )

        named_indexes = {
            "receiver_logs_device_epoch": ("receiver_logs", ("device_id", "log_epoch")),
            "receiver_months_device_epoch": ("receiver_months", ("device_id", "month_epoch")),
        }
        for index_name, (table, expected_columns) in named_indexes.items():
            indexes = {
                str(row["name"]): row
                for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
            }
            index = indexes.get(index_name)
            if index is None or int(index["unique"]) != 0:
                raise ReceiverSignerError(
                    f"receiver database index is not canonical: {index_name}"
                )
            actual_columns = tuple(
                str(row["name"])
                for row in connection.execute(
                    f"PRAGMA index_xinfo({index_name})"
                ).fetchall()
                if int(row["key"]) == 1
            )
            if actual_columns != expected_columns:
                raise ReceiverSignerError(
                    f"receiver database index columns are not canonical: {index_name}"
                )

        for table, expected_columns in (
            ("receiver_logs", ("device_id", "period_id")),
            ("receiver_months", ("device_id", "month_id")),
        ):
            unique_columns = {
                tuple(
                    str(column["name"])
                    for column in connection.execute(
                        f"PRAGMA index_xinfo({row['name']})"
                    ).fetchall()
                    if int(column["key"]) == 1
                )
                for row in connection.execute(f"PRAGMA index_list({table})").fetchall()
                if int(row["unique"]) == 1
            }
            if unique_columns != {expected_columns}:
                raise ReceiverSignerError(
                    f"receiver database uniqueness constraint is not canonical: {table}"
                )

        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ReceiverSignerError("receiver database foreign-key check failed")
        quick_check = [
            str(row[0]) for row in connection.execute("PRAGMA quick_check").fetchall()
        ]
        if quick_check != ["ok"]:
            raise ReceiverSignerError("receiver database quick_check failed")

    def _initialize(self) -> None:
        with self._connect() as connection:
            if self._database_was_empty:
                connection.executescript(_RECEIVER_SCHEMA_SQL)
                connection.execute(
                    f"PRAGMA application_id = {RECEIVER_SIGNER_APPLICATION_ID}"
                )
                connection.execute(
                    f"PRAGMA user_version = {RECEIVER_SIGNER_SCHEMA_VERSION}"
                )
            self._assert_canonical_schema(connection)
            meta = connection.execute(
                "SELECT * FROM receiver_meta WHERE singleton_id = 1"
            ).fetchone()
            expected_meta = {
                "receiver_id": self.receiver_id,
                "charger_domain": self.charger_domain,
                "device_id": self.device_id,
                "device_attestation_commitment": self.device_attestation_commitment,
                "policy_profile_commitment": str(self.policy_profile_commitment),
                "root_attestation_schema": SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
                "position_validity_rule": SETTLEMENT_POSITION_VALIDITY_RULE,
            }
            if meta is None:
                connection.execute(
                    """
                    INSERT INTO receiver_meta (
                        singleton_id, receiver_id, charger_domain, device_id,
                        device_attestation_commitment, policy_profile_commitment,
                        root_attestation_schema, position_validity_rule
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(expected_meta.values()),
                )
            else:
                for field, expected in expected_meta.items():
                    if str(meta[field]) != expected:
                        raise ReceiverSignerError(
                            f"receiver database metadata mismatch: {field}"
                        )
            if int(connection.execute("SELECT COUNT(*) FROM receiver_meta").fetchone()[0]) != 1:
                raise ReceiverSignerError("receiver database metadata cardinality is invalid")
            self._assert_canonical_schema(connection)

    def _validate_fixes(self, fixes: Sequence[ReceiverFix]) -> tuple[str, str]:
        if len(fixes) < 2:
            raise ReceiverSignerError("a receiver period requires at least two fixes")
        device_id = fixes[0].device_id
        period_id = fixes[0].period_id
        if not device_id or not period_id:
            raise ReceiverSignerError("device_id and period_id must not be empty")
        if str(device_id) != self.device_id:
            raise ReceiverSignerError("receiver signer is bound to another device")
        seen_nonces: set[str] = set()
        for index, fix in enumerate(fixes):
            if fix.device_id != device_id or fix.period_id != period_id:
                raise ReceiverSignerError("receiver log mixes device or period identities")
            if int(fix.fix_seq) != index:
                raise ReceiverSignerError("receiver fix_seq must equal its zero-based log index")
            if not fix.nonce or fix.nonce in seen_nonces:
                raise ReceiverSignerError("receiver nonces must be non-empty and unique")
            if not fix.osnma_status:
                raise ReceiverSignerError("receiver availability status must not be empty")
            seen_nonces.add(fix.nonce)
            if index:
                previous = fixes[index - 1]
                if int(fix.auth_gnss_time) <= int(previous.auth_gnss_time):
                    raise ReceiverSignerError("receiver time must be strictly increasing")
                if int(fix.odometer_reading_m) < int(previous.odometer_reading_m):
                    raise ReceiverSignerError("receiver odometer must be monotonic")
        return device_id, period_id

    def _validated_anchor_head(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        """Validate one Charger-owned live chain head before signing."""

        try:
            if raw.get("schema") != "waybill.charger.receiver-head/v1":
                raise ReceiverSignerError("unsupported Charger receiver-head schema")
            if str(raw["device_id"]) != self.device_id:
                raise ReceiverSignerError("Charger receiver head belongs to another device")
            epoch = int(raw["log_epoch"])
            attestation_sha256 = str(raw["attestation_sha256"])
            previous_sha256 = str(raw["previous_attestation_sha256"])
            receiver_id = str(raw.get("receiver_id") or "")
            period_id = str(raw.get("period_id") or "")
        except (KeyError, TypeError, ValueError) as exc:
            raise ReceiverSignerError("Charger receiver head is malformed") from exc
        for label, digest in (
            ("attestation", attestation_sha256),
            ("previous attestation", previous_sha256),
        ):
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ReceiverSignerError(
                    f"Charger receiver-head {label} hash is malformed"
                )
        if epoch < 0:
            raise ReceiverSignerError("Charger receiver-head epoch is negative")
        if epoch == 0:
            if (
                attestation_sha256 != SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256
                or previous_sha256 != SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256
                or receiver_id
                or period_id
            ):
                raise ReceiverSignerError("Charger genesis receiver head is inconsistent")
        else:
            if receiver_id != self.receiver_id or not period_id:
                raise ReceiverSignerError("Charger receiver head identity is inconsistent")
            if attestation_sha256 == SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256:
                raise ReceiverSignerError("non-genesis Charger receiver head has a genesis hash")
            if epoch == 1:
                if previous_sha256 != SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256:
                    raise ReceiverSignerError("first Charger receiver head has a non-genesis parent")
            elif previous_sha256 == SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256:
                raise ReceiverSignerError("Charger receiver head skips its predecessor")
        return {
            "schema": "waybill.charger.receiver-head/v1",
            "receiver_id": receiver_id,
            "device_id": self.device_id,
            "period_id": period_id,
            "log_epoch": epoch,
            "attestation_sha256": attestation_sha256,
            "previous_attestation_sha256": previous_sha256,
        }

    def seal_period(
        self,
        *,
        fixes: Sequence[ReceiverFix],
        policy_profile_commitment: int | None = None,
        charger_head: Mapping[str, Any],
        anchor_attestation: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Append a period only after the Charger atomically anchors its chain link."""

        device_id, period_id = self._validate_fixes(fixes)
        if policy_profile_commitment is not None and int(
            policy_profile_commitment
        ) != self.policy_profile_commitment:
            raise ReceiverSignerError("caller policy profile commitment is not canonical")
        policy_profile_commitment = self.policy_profile_commitment
        if any(fix.receiver_sig for fix in fixes):
            raise ReceiverSignerError(
                "trusted acquisition must submit unsigned fixes; the receiver signer owns signatures"
            )
        signed_fixes = [sign_receiver_fix(fix, self.private_key_bytes) for fix in fixes]
        flags = derive_receiver_position_valid(fixes)
        dac_field = field_from_text(self.device_attestation_commitment)
        receiver_fix_root = compute_receiver_fix_root_v6(
            signed_fixes,
            position_valid=flags,
            dac_field=dac_field,
            policy_profile_commitment=int(policy_profile_commitment),
        )
        fixes_payload = [fix.to_dict() for fix in signed_fixes]
        log_body = receiver_log_body(
            receiver_id=self.receiver_id,
            charger_domain=self.charger_domain,
            device_id=device_id,
            period_id=period_id,
            fixes_payload=fixes_payload,
            position_valid=flags,
            policy_profile_commitment=policy_profile_commitment,
            receiver_fix_root=receiver_fix_root,
            device_attestation_commitment=self.device_attestation_commitment,
            position_validity_rule=SETTLEMENT_POSITION_VALIDITY_RULE,
        )
        log_sha256 = receiver_log_sha256(log_body)
        fixes_json = canonical_json(fixes_payload)
        validity_json = canonical_json(flags)
        confirmed_head = self._validated_anchor_head(charger_head)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT 1 FROM receiver_logs WHERE device_id = ? AND period_id = ?",
                    (device_id, period_id),
                ).fetchone()
                if existing is not None:
                    raise ReceiverSignerError("receiver period is already sealed")
                previous = connection.execute(
                    """
                    SELECT *
                    FROM receiver_logs
                    WHERE device_id = ?
                    ORDER BY log_epoch DESC
                    LIMIT 1
                    """,
                    (device_id,),
                ).fetchone()
                if previous is not None:
                    previous_record = self._validated_row(previous)
                    previous_fixes = previous_record.get("fixes")
                    previous_attestation = previous_record.get("attestation")
                    if not isinstance(previous_fixes, list) or not isinstance(
                        previous_attestation, dict
                    ):
                        raise ReceiverSignerError("previous sealed receiver row is incomplete")
                    terminal = ReceiverFix.from_dict(previous_fixes[-1])
                    if int(fixes[0].auth_gnss_time) < int(terminal.auth_gnss_time):
                        raise ReceiverSignerError("receiver period time rolls back sealed state")
                    if int(fixes[0].odometer_reading_m) < int(
                        terminal.odometer_reading_m
                    ):
                        raise ReceiverSignerError("receiver period odometer rolls back sealed state")
                    local_epoch = int(previous_record["log_epoch"])
                    local_hash = receiver_attestation_sha256(previous_attestation)
                else:
                    local_epoch = 0
                    local_hash = SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256

                remote_epoch = int(confirmed_head["log_epoch"])
                remote_hash = str(confirmed_head["attestation_sha256"])
                if remote_epoch == local_epoch and remote_hash == local_hash:
                    log_epoch = local_epoch + 1
                    recovering_remote_commit = False
                elif (
                    remote_epoch == local_epoch + 1
                    and str(confirmed_head["previous_attestation_sha256"])
                    == local_hash
                ):
                    log_epoch = remote_epoch
                    recovering_remote_commit = True
                else:
                    raise ReceiverSignerError(
                        "receiver database does not match the live Charger chain head; "
                        "rollback or fork detected"
                    )
                attestation = sign_receiver_root_attestation(
                    receiver_id=self.receiver_id,
                    charger_domain=self.charger_domain,
                    device_id=device_id,
                    period_id=period_id,
                    log_epoch=log_epoch,
                    fix_count=len(signed_fixes),
                    receiver_fix_root=receiver_fix_root,
                    device_attestation_commitment=self.device_attestation_commitment,
                    log_sha256=log_sha256,
                    private_key_bytes=self.private_key_bytes,
                    previous_attestation_sha256=local_hash,
                    position_validity_rule=SETTLEMENT_POSITION_VALIDITY_RULE,
                )
                attestation_sha256 = receiver_attestation_sha256(attestation)
                if recovering_remote_commit and attestation_sha256 != remote_hash:
                    raise ReceiverSignerError(
                        "live Charger head cannot be recovered from the submitted receiver log"
                    )
                anchored_head = self._validated_anchor_head(
                    anchor_attestation(dict(attestation))
                )
                if (
                    int(anchored_head["log_epoch"]) != log_epoch
                    or str(anchored_head["attestation_sha256"])
                    != attestation_sha256
                    or str(anchored_head["previous_attestation_sha256"])
                    != local_hash
                    or str(anchored_head["period_id"]) != period_id
                ):
                    raise ReceiverSignerError(
                        "Charger did not confirm the exact receiver attestation"
                    )
                connection.execute(
                    """
                    INSERT INTO receiver_logs (
                        log_epoch, receiver_id, charger_domain, device_id, period_id,
                        period_start_time, period_end_time,
                        odometer_start_m, odometer_end_m,
                        fix_count, policy_profile_commitment,
                        receiver_fix_root, fixes_json,
                        position_valid_json, position_validity_rule,
                        previous_attestation_sha256, attestation_sha256,
                        attestation_json, log_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_epoch,
                        self.receiver_id,
                        self.charger_domain,
                        device_id,
                        period_id,
                        int(signed_fixes[0].auth_gnss_time),
                        int(signed_fixes[-1].auth_gnss_time),
                        int(signed_fixes[0].odometer_reading_m),
                        int(signed_fixes[-1].odometer_reading_m),
                        len(signed_fixes),
                        str(policy_profile_commitment),
                        str(receiver_fix_root),
                        fixes_json,
                        validity_json,
                        SETTLEMENT_POSITION_VALIDITY_RULE,
                        local_hash,
                        attestation_sha256,
                        canonical_json(attestation),
                        log_sha256,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ReceiverSignerError("receiver period is already sealed") from exc
        return self._wire_record(
            log_epoch=log_epoch,
            device_id=device_id,
            period_id=period_id,
            fix_count=len(signed_fixes),
            policy_profile_commitment=str(policy_profile_commitment),
            receiver_fix_root=str(receiver_fix_root),
            position_valid=flags,
            log_sha256=log_sha256,
            fixes=fixes_payload,
            attestation=attestation,
        )

    def _load_row(self, *, device_id: str, period_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM receiver_logs WHERE device_id = ? AND period_id = ?",
                (str(device_id), str(period_id)),
            ).fetchone()
        if row is None:
            raise ReceiverSignerError("receiver period is not sealed")
        return row

    def _validated_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """Revalidate every security-relevant field of one persisted log row."""

        try:
            fixes_payload = json.loads(str(row["fixes_json"]))
            position_valid = json.loads(str(row["position_valid_json"]))
            if not isinstance(fixes_payload, list):
                raise TypeError("fixes must be an array")
            fixes = [ReceiverFix.from_dict(item) for item in fixes_payload]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReceiverSignerError("sealed receiver fixes are malformed") from exc
        if len(fixes) < 2:
            raise ReceiverSignerError("sealed receiver log has too few fixes")
        try:
            row_device_id, row_period_id = self._validate_fixes(fixes)
        except ReceiverSignerError as exc:
            raise ReceiverSignerError(f"sealed receiver fix sequence is inconsistent: {exc}") from exc
        position_valid = validate_position_valid(fixes, position_valid)
        if str(row["receiver_id"]) != self.receiver_id:
            raise ReceiverSignerError("sealed receiver identity does not match this signer")
        if str(row["device_id"]) != self.device_id:
            raise ReceiverSignerError("sealed receiver log belongs to another device")
        if str(row["device_id"]) != str(row_device_id):
            raise ReceiverSignerError("sealed receiver row and fixes disagree on device")
        if str(row["period_id"]) != str(row_period_id):
            raise ReceiverSignerError("sealed receiver row and fixes disagree on period")
        if str(row["charger_domain"]) != self.charger_domain:
            raise ReceiverSignerError("sealed receiver log is bound to another Charger domain")
        if str(row["position_validity_rule"]) != SETTLEMENT_POSITION_VALIDITY_RULE:
            raise ReceiverSignerError("sealed receiver log uses another validity rule")
        if any(not verify_receiver_fix_signature(fix, self.public_key_bytes) for fix in fixes):
            raise ReceiverSignerError("sealed receiver fix signature is inconsistent")
        redundant_boundaries = {
            "period_start_time": int(fixes[0].auth_gnss_time),
            "period_end_time": int(fixes[-1].auth_gnss_time),
            "odometer_start_m": int(fixes[0].odometer_reading_m),
            "odometer_end_m": int(fixes[-1].odometer_reading_m),
            "fix_count": len(fixes),
        }
        for field, expected in redundant_boundaries.items():
            if int(row[field]) != expected:
                raise ReceiverSignerError(
                    f"sealed receiver redundant boundary is inconsistent: {field}"
                )
        recomputed_root = compute_receiver_fix_root_v6(
            fixes,
            position_valid=position_valid,
            dac_field=field_from_text(self.device_attestation_commitment),
            policy_profile_commitment=int(row["policy_profile_commitment"]),
        )
        if str(recomputed_root) != str(row["receiver_fix_root"]):
            raise ReceiverSignerError("sealed receiver root is inconsistent")
        log_body = receiver_log_body(
            receiver_id=str(row["receiver_id"]),
            charger_domain=str(row["charger_domain"]),
            device_id=str(row["device_id"]),
            period_id=str(row["period_id"]),
            fixes_payload=fixes_payload,
            position_valid=position_valid,
            policy_profile_commitment=str(row["policy_profile_commitment"]),
            receiver_fix_root=str(row["receiver_fix_root"]),
            device_attestation_commitment=self.device_attestation_commitment,
            position_validity_rule=str(row["position_validity_rule"]),
        )
        actual_sha256 = receiver_log_sha256(log_body)
        if actual_sha256 != str(row["log_sha256"]):
            raise ReceiverSignerError("sealed receiver log hash is inconsistent")
        try:
            attestation = json.loads(str(row["attestation_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReceiverSignerError("sealed receiver attestation is malformed") from exc
        if not isinstance(attestation, dict):
            raise ReceiverSignerError("sealed receiver attestation is malformed")
        expected_attestation_fields: dict[str, Any] = {
            "receiver_id": self.receiver_id,
            "charger_domain": self.charger_domain,
            "device_id": str(row["device_id"]),
            "period_id": str(row["period_id"]),
            "log_epoch": int(row["log_epoch"]),
            "fix_count": int(row["fix_count"]),
            "receiver_fix_root": str(row["receiver_fix_root"]),
            "device_attestation_commitment": self.device_attestation_commitment,
            "position_validity_rule": SETTLEMENT_POSITION_VALIDITY_RULE,
            "log_sha256": actual_sha256,
            "previous_attestation_sha256": str(
                row["previous_attestation_sha256"]
            ),
        }
        for field, expected in expected_attestation_fields.items():
            if attestation.get(field) != expected:
                raise ReceiverSignerError(
                    f"sealed receiver attestation field is inconsistent: {field}"
                )
        if not verify_receiver_root_attestation(
            public_statement={
                "period_id": str(row["period_id"]),
                "receiver_fix_root": str(row["receiver_fix_root"]),
                "device_attestation_commitment": self.device_attestation_commitment,
            },
            attestation=attestation,
            public_key_bytes=self.public_key_bytes,
            expected_charger_domain=self.charger_domain,
        ):
            raise ReceiverSignerError("sealed receiver attestation signature is inconsistent")
        actual_attestation_sha256 = receiver_attestation_sha256(attestation)
        if actual_attestation_sha256 != str(row["attestation_sha256"]):
            raise ReceiverSignerError("sealed receiver attestation hash is inconsistent")
        return self._wire_record(
            log_epoch=int(row["log_epoch"]),
            device_id=str(row["device_id"]),
            period_id=str(row["period_id"]),
            fix_count=int(row["fix_count"]),
            policy_profile_commitment=str(row["policy_profile_commitment"]),
            receiver_fix_root=str(row["receiver_fix_root"]),
            position_valid=[bool(item) for item in position_valid],
            log_sha256=actual_sha256,
            fixes=fixes_payload,
            attestation=attestation,
        )

    def _validated_record(self, *, device_id: str, period_id: str) -> dict[str, Any]:
        return self._validated_row(
            self._load_row(device_id=device_id, period_id=period_id)
        )

    def _wire_record(
        self,
        *,
        log_epoch: int,
        device_id: str,
        period_id: str,
        fix_count: int,
        policy_profile_commitment: str,
        receiver_fix_root: str,
        position_valid: list[bool],
        log_sha256: str,
        fixes: list[dict[str, Any]] | None = None,
        attestation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "receiver_id": self.receiver_id,
            "charger_domain": self.charger_domain,
            "device_id": device_id,
            "period_id": period_id,
            "log_epoch": int(log_epoch),
            "fix_count": int(fix_count),
            "policy_profile_commitment": str(policy_profile_commitment),
            "receiver_fix_root": str(receiver_fix_root),
            "device_attestation_commitment": self.device_attestation_commitment,
            "position_valid": list(position_valid),
            "position_validity_rule": SETTLEMENT_POSITION_VALIDITY_RULE,
            "log_sha256": log_sha256,
        }
        if fixes is not None:
            record["fixes"] = list(fixes)
        if attestation is not None:
            record["attestation"] = dict(attestation)
        return record

    def period_material(self, *, device_id: str, period_id: str) -> dict[str, Any]:
        """Return witness-side metadata from a sealed log without signing input."""

        return self._validated_record(device_id=device_id, period_id=period_id)

    def attest_period(self, *, device_id: str, period_id: str) -> dict[str, Any]:
        """Return the immutable seal-time attestation after full revalidation."""

        record = self._validated_record(device_id=device_id, period_id=period_id)
        attestation = record.get("attestation")
        if not isinstance(attestation, dict):
            raise ReceiverSignerError("sealed receiver attestation is missing")
        return dict(attestation)

    def _validated_month_row(self, row: sqlite3.Row) -> dict[str, Any]:
        """Verify a persisted monthly boundary solely from its signed attestation."""

        if str(row["receiver_id"]) != self.receiver_id:
            raise ReceiverSignerError("sealed month identity does not match this signer")
        if str(row["device_id"]) != self.device_id:
            raise ReceiverSignerError("sealed month belongs to another device")
        if str(row["charger_domain"]) != self.charger_domain:
            raise ReceiverSignerError("sealed month is bound to another Charger domain")
        try:
            attestation = json.loads(str(row["attestation_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ReceiverSignerError("sealed month attestation is malformed") from exc
        if not isinstance(attestation, dict) or not verify_monthly_odometer_attestation(
            attestation=attestation,
            public_key_bytes=self.public_key_bytes,
            expected_charger_domain=self.charger_domain,
        ):
            raise ReceiverSignerError("sealed month attestation is inconsistent")
        expected = {
            "charger_domain": str(row["charger_domain"]),
            "device_id": str(row["device_id"]),
            "month_id": str(row["month_id"]),
            "odometer_start_m": int(row["odometer_start_m"]),
            "odometer_end_m": int(row["odometer_end_m"]),
        }
        if any(attestation.get(key) != value for key, value in expected.items()):
            raise ReceiverSignerError("sealed month boundary is inconsistent")
        return {"month_epoch": int(row["month_epoch"]), **attestation}

    def seal_month(
        self,
        *,
        device_id: str,
        month_id: str,
        odometer_start_m: int,
        odometer_end_m: int,
        anchor_attestation: Callable[[dict[str, Any]], Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Anchor and persist one signer-owned monthly odometer boundary."""

        device_id = str(device_id)
        month_id = str(month_id)
        if not device_id or len(month_id) != 6 or not month_id.isdigit():
            raise ReceiverSignerError("device_id and YYYYMM month_id are required")
        if device_id != self.device_id:
            raise ReceiverSignerError("receiver signer is bound to another device")
        month_number = int(month_id)
        month = month_number % 100
        if month < 1 or month > 12:
            raise ReceiverSignerError("month_id must contain a valid calendar month")
        if time.time() < int(canonical_month_window(month_id)["month_end_time"]):
            raise ReceiverSignerError("receiver month has not ended")
        start_m = int(odometer_start_m)
        end_m = int(odometer_end_m)
        if start_m < 0 or end_m < start_m:
            raise ReceiverSignerError("monthly odometer boundaries must be non-negative and monotonic")
        attestation = sign_monthly_odometer_attestation(
            charger_domain=self.charger_domain,
            device_id=device_id,
            month_id=month_id,
            odometer_start_m=start_m,
            odometer_end_m=end_m,
            private_key_bytes=self.private_key_bytes,
        )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute(
                    """
                    SELECT *
                    FROM receiver_months
                    WHERE device_id = ?
                    ORDER BY month_id DESC
                    LIMIT 1
                    """,
                    (device_id,),
                ).fetchone()
                if previous is not None:
                    previous_month = self._validated_month_row(previous)
                    if month_number <= int(previous_month["month_id"]):
                        raise ReceiverSignerError("receiver month is duplicate or rolls back sealed state")
                    previous_number = int(previous_month["month_id"])
                    previous_year, previous_value = divmod(previous_number, 100)
                    expected_month = (
                        (previous_year + 1) * 100 + 1
                        if previous_value == 12
                        else previous_year * 100 + previous_value + 1
                    )
                    if month_number != expected_month:
                        raise ReceiverSignerError("receiver month must extend the next calendar month")
                    if start_m < int(previous_month["odometer_end_m"]):
                        raise ReceiverSignerError("monthly odometer rolls back sealed state")
                    if start_m != int(previous_month["odometer_end_m"]):
                        raise ReceiverSignerError("monthly odometer boundary is not continuous")
                attestation_sha256 = hashlib.sha256(
                    canonical_json(attestation).encode("utf-8")
                ).hexdigest()
                confirmed = anchor_attestation(dict(attestation))
                if (
                    confirmed.get("schema") != "waybill.charger.month-attestation/v1"
                    or confirmed.get("ok") is not True
                    or str(confirmed.get("device_id", "")) != device_id
                    or str(confirmed.get("month_id", "")) != month_id
                    or str(confirmed.get("attestation_sha256", ""))
                    != attestation_sha256
                ):
                    raise ReceiverSignerError(
                        "Charger did not confirm the exact monthly odometer attestation"
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO receiver_months (
                        receiver_id, charger_domain, device_id, month_id,
                        odometer_start_m, odometer_end_m, attestation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self.receiver_id,
                        self.charger_domain,
                        device_id,
                        month_id,
                        start_m,
                        end_m,
                        canonical_json(attestation),
                    ),
                )
                if cursor.lastrowid is None:
                    raise ReceiverSignerError("receiver month insertion returned no epoch")
                month_epoch = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ReceiverSignerError("receiver month is already sealed") from exc
        return {"month_epoch": month_epoch, **attestation}

    def month_attestation(self, *, device_id: str, month_id: str) -> dict[str, Any]:
        if str(device_id) != self.device_id:
            raise ReceiverSignerError("receiver signer is bound to another device")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM receiver_months WHERE device_id = ? AND month_id = ?",
                (str(device_id), str(month_id)),
            ).fetchone()
        if row is None:
            raise ReceiverSignerError("receiver month is not sealed")
        return self._validated_month_row(row)
