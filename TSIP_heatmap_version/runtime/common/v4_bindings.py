from __future__ import annotations

import atexit
import hashlib
import json
import os
import secrets
import subprocess
import threading
from pathlib import Path
from typing import Any, Iterable

from common.proof_payload import (
    DOMAIN_LOCATION,
    derive_binding_fields,
    package_digest_field,
    sparse_fingerprint,
    validate_fingerprint_relation,
)


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
PAPER_PUBLIC_SIGNAL_ORDER = (
    "hash_prev",
    "hash_curr",
    "hash_anchor",
    "step_dt_sq",
    "tier_vmax_sq",
    "tier_anchor_cap_sq",
    "cap_policy_sq",
    "primary_commitment",
    "payload_commitment_v2",
    "share_content_commitment_a",
    "share_content_commitment_r",
    "context_commitment",
    "blob_hash",
    "package_digest_a",
    "package_digest_r",
    "fingerprint_challenge",
    "secret_commitment",
    "modeset_commitment",
    "mode_tag",
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def canonical_digest_field(value: Any) -> int:
    return int.from_bytes(hashlib.sha256(_canonical_bytes(value)).digest(), "big") % SNARK_FIELD


def deterministic_field(*parts: object) -> int:
    material = "||".join(str(part) for part in parts).encode("utf-8")
    value = int.from_bytes(hashlib.sha256(material).digest(), "big") % SNARK_FIELD
    return value if value != 0 else 1


def random_field() -> int:
    """Sample a nonzero BN254 scalar with the operating-system CSPRNG."""
    return secrets.randbelow(SNARK_FIELD - 1) + 1


def report_context(
    *, user_id: str, round_id: int, submission_id: str, epoch: int
) -> dict[str, object]:
    return {
        "domain": "tsip-v4-paper",
        "epoch": int(epoch),
        "round_id": int(round_id),
        "submission_id": str(submission_id),
        "user_id": str(user_id),
    }


def share_digest_field(
    *, channel: str, round_id: int, submission_id: str, idx: list[int], val: list[int]
) -> int:
    return canonical_digest_field(
        {
            "channel": str(channel),
            "domain": "tsip-v4-paper-share",
            "idx": [int(item) for item in idx],
            "round_id": int(round_id),
            "submission_id": str(submission_id),
            "val": [int(item) for item in val],
        }
    )


class PoseidonWorker:
    def __init__(self, script: str | os.PathLike[str] | None = None) -> None:
        default_script = Path(__file__).resolve().parents[1] / "js" / "poseidon_worker.js"
        self._script = Path(script or os.getenv("TSIP_V4_POSEIDON_WORKER", str(default_script)))
        self._node = os.getenv("TSIP_V4_NODE", "node")
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _start(self) -> subprocess.Popen[str]:
        if not self._script.is_file():
            raise RuntimeError(f"missing Poseidon worker: {self._script}")
        process = subprocess.Popen(
            [self._node, str(self._script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._process = process
        return process

    def _get_process(self) -> subprocess.Popen[str]:
        process = self._process
        if process is None or process.poll() is not None:
            process = self._start()
        return process

    def hash(self, values: Iterable[int | str]) -> int:
        request = {"op": "hash", "values": [str(value) for value in values]}
        with self._lock:
            process = self._get_process()
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Poseidon worker pipes unavailable")
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                stderr = process.stderr.read() if process.stderr is not None else ""
                self.close()
                raise RuntimeError(f"Poseidon worker stopped: {stderr.strip()}")
            response = json.loads(line)
            if not response.get("ok"):
                raise RuntimeError(f"Poseidon worker error: {response.get('error', 'unknown error')}")
            return int(response["value"])

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()


_WORKER = PoseidonWorker()
atexit.register(_WORKER.close)


def poseidon_hash(*values: int | str) -> int:
    return _WORKER.hash(values)


def location_opening(
    *, user_id: str, secret_hex: str, x: int, y: int, timestamp: int
) -> tuple[int, int]:
    # The compatibility parameters identify the opening call but never seed it:
    # predictable coordinates, identifiers, or timestamps must not determine a salt.
    del user_id, secret_hex, timestamp
    salt = random_field()
    from common.proof_payload import poseidon_chain

    return salt, poseidon_chain(DOMAIN_LOCATION, int(x), int(y), salt)


def derive_paper_binding_fields(
    *,
    primary_idx: int,
    primary_salt: int,
    context_commitment: int,
    package_digest_a: int,
    package_digest_r: int,
    fingerprint_a: int,
    fingerprint_r: int,
    contribution_bit: int,
) -> dict[str, int]:
    return derive_binding_fields(
        primary_idx=primary_idx,
        primary_salt=primary_salt,
        context_commitment=context_commitment,
        package_digest_a=package_digest_a,
        package_digest_r=package_digest_r,
        fingerprint_a=fingerprint_a,
        fingerprint_r=fingerprint_r,
        contribution_bit=contribution_bit,
    )


def expected_public_signals(values: dict[str, object]) -> list[str]:
    missing = [name for name in PAPER_PUBLIC_SIGNAL_ORDER if name not in values]
    if missing:
        raise ValueError(f"missing V4 paper public fields: {', '.join(missing)}")
    return [str(values[name]) for name in PAPER_PUBLIC_SIGNAL_ORDER]
