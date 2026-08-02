r"""Durable, accountable state transitions for the Shuffler.

This module is deliberately separate from the ZK admission relation.  It
implements the concrete interface used for the paper's \(\mathcal F_STATE\): a
durable compare-and-swap transition, a signed receipt, a sparse-Merkle root,
and periodically signed hash-chained checkpoints.  It provides accountability
after conflicting evidence is compared; it is not a replicated state machine
and makes no availability or censorship-resistance claim.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        h.update(len(encoded).to_bytes(4, "big"))
        h.update(encoded)
    return h.hexdigest()


def _key_index(user_id: str, epoch: int, depth: int) -> int:
    digest = hashlib.sha256(f"shtpc-state-leaf:{user_id}:{epoch}".encode("utf-8")).digest()
    return int.from_bytes(digest, "big") >> (256 - depth)


class StateTransitionError(ValueError):
    """A requested state transition violates the durable CAS contract."""


@dataclass(frozen=True)
class StateCommit:
    receipt: dict[str, Any]
    inclusion_proof: dict[str, Any]
    checkpoint: dict[str, Any] | None


class AccountableStateStore:
    """SQLite-backed state service with signed, externally verifiable evidence."""

    def __init__(
        self,
        db_path: str,
        signing_key_b64: str,
        service_id: str,
        checkpoint_interval: int = 100,
        merkle_depth: int = 32,
    ) -> None:
        if not signing_key_b64:
            raise ValueError("SHUFFLER_STATE_SIGNING_KEY is required when accountability is enabled")
        if not 1 <= merkle_depth <= 56:
            raise ValueError("merkle_depth must be between 1 and 56")
        if checkpoint_interval <= 0:
            raise ValueError("checkpoint_interval must be positive")

        raw_key = base64.b64decode(signing_key_b64.encode("ascii"), validate=True)
        if len(raw_key) != 32:
            raise ValueError("SHUFFLER_STATE_SIGNING_KEY must encode a 32-byte Ed25519 seed")
        self._private_key = Ed25519PrivateKey.from_private_bytes(raw_key)
        self._public_key_b64 = base64.b64encode(
            self._private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")
        self.service_id = service_id.strip() or "shuffler-1"
        self.checkpoint_interval = checkpoint_interval
        self.depth = merkle_depth
        self.defaults = self._default_hashes(merkle_depth)

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self._init_schema()

    @staticmethod
    def _default_hashes(depth: int) -> list[str]:
        defaults = [_hash("shtpc-smt-empty-leaf")]
        for _ in range(depth):
            defaults.append(_hash("shtpc-smt-node", defaults[-1], defaults[-1]))
        return defaults

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS state_records (
                user_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                state_round INTEGER NOT NULL,
                commitment TEXT NOT NULL,
                report_digest TEXT NOT NULL,
                state_json TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, epoch)
            );
            CREATE TABLE IF NOT EXISTS merkle_nodes (
                level INTEGER NOT NULL,
                node_index INTEGER NOT NULL,
                node_hash TEXT NOT NULL,
                PRIMARY KEY (level, node_index)
            );
            CREATE TABLE IF NOT EXISTS receipts (
                receipt_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                state_round INTEGER NOT NULL,
                receipt_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                sequence INTEGER PRIMARY KEY,
                checkpoint_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        columns = {str(row[1]) for row in self.conn.execute("PRAGMA table_info(state_records)")}
        if "state_json" not in columns:
            self.conn.execute("ALTER TABLE state_records ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}'")

    def close(self) -> None:
        self.conn.close()

    def _metadata(self, name: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM metadata WHERE name = ?", (name,)).fetchone()
        return str(row[0]) if row else default

    def _set_metadata(self, name: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO metadata(name, value) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
            (name, value),
        )

    def _node(self, level: int, node_index: int) -> str:
        row = self.conn.execute(
            "SELECT node_hash FROM merkle_nodes WHERE level = ? AND node_index = ?",
            (level, node_index),
        ).fetchone()
        return str(row[0]) if row else self.defaults[level]

    def _set_node(self, level: int, node_index: int, node_hash: str) -> None:
        if node_hash == self.defaults[level]:
            self.conn.execute(
                "DELETE FROM merkle_nodes WHERE level = ? AND node_index = ?",
                (level, node_index),
            )
            return
        self.conn.execute(
            "INSERT INTO merkle_nodes(level, node_index, node_hash) VALUES (?, ?, ?) "
            "ON CONFLICT(level, node_index) DO UPDATE SET node_hash = excluded.node_hash",
            (level, node_index, node_hash),
        )

    def _root(self) -> str:
        return self._node(self.depth, 0)

    def _leaf_hash(self, user_id: str, epoch: int, state_round: int, commitment: str, report_digest: str) -> str:
        return _hash(
            "shtpc-state-leaf",
            user_id,
            str(epoch),
            str(state_round),
            commitment,
            report_digest,
        )

    def _update_leaf(self, leaf_index: int, leaf_hash: str) -> tuple[str, list[str]]:
        self._set_node(0, leaf_index, leaf_hash)
        siblings: list[str] = []
        node_index = leaf_index
        current = leaf_hash
        for level in range(self.depth):
            sibling_index = node_index ^ 1
            sibling = self._node(level, sibling_index)
            siblings.append(sibling)
            if node_index & 1:
                parent = _hash("shtpc-smt-node", sibling, current)
            else:
                parent = _hash("shtpc-smt-node", current, sibling)
            node_index //= 2
            current = parent
            self._set_node(level + 1, node_index, current)
        return current, siblings

    def _sign(self, body: dict[str, Any]) -> dict[str, Any]:
        signed = dict(body)
        signed["service_id"] = self.service_id
        signed["public_key"] = self._public_key_b64
        signed["signature"] = base64.b64encode(self._private_key.sign(_canonical(signed))).decode("ascii")
        return signed

    @staticmethod
    def verify_signed(document: dict[str, Any]) -> bool:
        try:
            signature = base64.b64decode(str(document["signature"]).encode("ascii"), validate=True)
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(str(document["public_key"]).encode("ascii"), validate=True)
            )
            body = dict(document)
            body.pop("signature")
            public_key.verify(signature, _canonical(body))
            return True
        except Exception:
            return False

    def commit(
        self,
        *,
        user_id: str,
        epoch: int,
        state_round: int,
        previous_commitment: str,
        current_commitment: str,
        report_digest: str,
        timing_token_digest: str,
        state_snapshot: dict[str, Any] | None = None,
        reset: bool = False,
    ) -> StateCommit:
        """Atomically commit a unique successor and emit durable signed evidence."""
        if not user_id or not current_commitment or not report_digest:
            raise StateTransitionError("incomplete state transition")
        now = int(time.time())
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT state_round, commitment FROM state_records WHERE user_id = ? AND epoch = ?",
                (user_id, epoch),
            ).fetchone()
            if row is None:
                if previous_commitment:
                    raise StateTransitionError("unknown predecessor")
                if state_round != 1:
                    raise StateTransitionError("first state round must be 1")
            else:
                stored_round, stored_commitment = int(row[0]), str(row[1])
                if reset:
                    raise StateTransitionError("reset must use a fresh epoch")
                if previous_commitment != stored_commitment:
                    raise StateTransitionError("stale or conflicting predecessor")
                if state_round != stored_round + 1:
                    raise StateTransitionError("round is not the unique successor")

            previous_root = self._root()
            leaf_hash = self._leaf_hash(user_id, epoch, state_round, current_commitment, report_digest)
            leaf_index = _key_index(user_id, epoch, self.depth)
            current_root, siblings = self._update_leaf(leaf_index, leaf_hash)
            self.conn.execute(
                "INSERT INTO state_records(user_id, epoch, state_round, commitment, report_digest, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, epoch) DO UPDATE SET "
                "state_round=excluded.state_round, commitment=excluded.commitment, "
                "report_digest=excluded.report_digest, state_json=excluded.state_json, "
                "updated_at=excluded.updated_at",
                (
                    user_id,
                    epoch,
                    state_round,
                    current_commitment,
                    report_digest,
                    json.dumps(state_snapshot or {}, sort_keys=True, separators=(",", ":")),
                    now,
                ),
            )
            transition_id = _hash(
                "shtpc-transition", user_id, str(epoch), str(state_round), previous_commitment,
                current_commitment, report_digest, previous_root, current_root,
            )
            receipt = self._sign(
                {
                    "kind": "state-transition-receipt-v1",
                    "transition_id": transition_id,
                    "user_id": user_id,
                    "epoch": epoch,
                    "state_round": state_round,
                    "previous_commitment": previous_commitment,
                    "current_commitment": current_commitment,
                    "report_digest": report_digest,
                    "timing_token_digest": timing_token_digest,
                    "previous_root": previous_root,
                    "state_root": current_root,
                    "issued_at": now,
                }
            )
            self.conn.execute(
                "INSERT INTO receipts(receipt_id, user_id, epoch, state_round, receipt_json) VALUES (?, ?, ?, ?, ?)",
                (transition_id, user_id, epoch, state_round, json.dumps(receipt, sort_keys=True)),
            )
            accepted = int(self._metadata("accepted_transitions", "0")) + 1
            self._set_metadata("accepted_transitions", str(accepted))
            checkpoint = self._checkpoint(now, current_root) if accepted % self.checkpoint_interval == 0 else None
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

        inclusion_proof = {
            "kind": "sparse-merkle-inclusion-v1",
            "depth": self.depth,
            "leaf_index": leaf_index,
            "leaf_hash": leaf_hash,
            "siblings": siblings,
            "state_root": current_root,
        }
        return StateCommit(receipt=receipt, inclusion_proof=inclusion_proof, checkpoint=checkpoint)

    def _checkpoint(self, now: int, state_root: str) -> dict[str, Any]:
        sequence = int(self._metadata("checkpoint_sequence", "0")) + 1
        previous_hash = self._metadata("checkpoint_hash", "")
        checkpoint = self._sign(
            {
                "kind": "state-checkpoint-v1",
                "sequence": sequence,
                "state_root": state_root,
                "previous_checkpoint_hash": previous_hash,
                "issued_at": now,
            }
        )
        checkpoint_hash = _hash("shtpc-checkpoint", _canonical(checkpoint).decode("utf-8"))
        self.conn.execute(
            "INSERT INTO checkpoints(sequence, checkpoint_json) VALUES (?, ?)",
            (sequence, json.dumps(checkpoint, sort_keys=True)),
        )
        self._set_metadata("checkpoint_sequence", str(sequence))
        self._set_metadata("checkpoint_hash", checkpoint_hash)
        return checkpoint

    def latest_receipt(self, user_id: str, epoch: int | None = None) -> dict[str, Any] | None:
        if epoch is None:
            row = self.conn.execute(
                "SELECT receipt_json FROM receipts WHERE user_id = ? ORDER BY epoch DESC, state_round DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT receipt_json FROM receipts WHERE user_id = ? AND epoch = ? "
                "ORDER BY state_round DESC LIMIT 1",
                (user_id, epoch),
            ).fetchone()
        return json.loads(str(row[0])) if row else None

    def latest_state_snapshot(self, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT state_json FROM state_records WHERE user_id = ? "
            "ORDER BY epoch DESC, state_round DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        snapshot = json.loads(str(row[0]))
        return snapshot if isinstance(snapshot, dict) and snapshot else None

    def latest_checkpoint(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT checkpoint_json FROM checkpoints ORDER BY sequence DESC LIMIT 1").fetchone()
        return json.loads(str(row[0])) if row else None

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "service_id": self.service_id,
            "merkle_depth": self.depth,
            "state_root": self._root(),
            "accepted_transitions": int(self._metadata("accepted_transitions", "0")),
            "latest_checkpoint": self.latest_checkpoint(),
        }


def verify_inclusion_proof(proof: dict[str, Any]) -> bool:
    """Verify a proof emitted by :meth:`AccountableStateStore.commit`."""
    try:
        depth = int(proof["depth"])
        node_index = int(proof["leaf_index"])
        siblings = list(proof["siblings"])
        if len(siblings) != depth:
            return False
        current = str(proof["leaf_hash"])
        for sibling in siblings:
            if node_index & 1:
                current = _hash("shtpc-smt-node", str(sibling), current)
            else:
                current = _hash("shtpc-smt-node", current, str(sibling))
            node_index //= 2
        return current == str(proof["state_root"])
    except Exception:
        return False


def detect_equivocation(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any] | None:
    """Return public evidence when two valid signed state documents conflict.

    Detection deliberately requires both documents to be compared.  It does
    not claim that an isolated client discovers a fork on its own.
    """
    if not (AccountableStateStore.verify_signed(first) and AccountableStateStore.verify_signed(second)):
        return None
    if first.get("service_id") != second.get("service_id") or first.get("kind") != second.get("kind"):
        return None
    kind = str(first.get("kind"))
    conflict = False
    if kind == "state-transition-receipt-v1":
        same_slot = all(
            first.get(field) == second.get(field)
            for field in ("user_id", "epoch", "state_round", "previous_commitment")
        )
        conflict = same_slot and (
            first.get("current_commitment") != second.get("current_commitment")
            or first.get("state_root") != second.get("state_root")
        )
    elif kind == "state-checkpoint-v1":
        conflict = first.get("sequence") == second.get("sequence") and (
            first.get("state_root") != second.get("state_root")
            or first.get("previous_checkpoint_hash") != second.get("previous_checkpoint_hash")
        )
    if not conflict:
        return None
    return {
        "kind": "shuffler-equivocation-evidence-v1",
        "service_id": first["service_id"],
        "document_a": first,
        "document_b": second,
    }
