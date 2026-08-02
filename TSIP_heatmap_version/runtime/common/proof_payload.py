from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Mapping, Sequence

from common.poseidon2_py import _poseidon2


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617
PROTOCOL_VERSION = "shtpc-proof-payload"
POLICY_VERSION = "onehot-pre-dp-2026-07"
SHARE_FIELD_ID = "z2^32-balanced"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def digest_hex(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def digest_field(value: Any) -> int:
    return int.from_bytes(hashlib.sha256(_canonical_bytes(value)).digest(), "big") % SNARK_FIELD


def domain_field(label: str) -> int:
    return digest_field({"domain": str(label)})


DOMAIN_PRIMARY = domain_field("shtpc/primary")
DOMAIN_LOCATION = domain_field("shtpc/location")
DOMAIN_FINGERPRINT = domain_field("shtpc/fingerprint")
DOMAIN_CHANNEL_A = domain_field("shtpc/channel/A")
DOMAIN_CHANNEL_R = domain_field("shtpc/channel/R")
DOMAIN_PAYLOAD = domain_field("shtpc/payload")
DOMAIN_BLOB = domain_field("shtpc/transport")


def poseidon_chain(domain: int, *values: int) -> int:
    state = int(domain) % SNARK_FIELD
    for value in values:
        state = int(_poseidon2(state, int(value) % SNARK_FIELD))
    return state


def validate_sparse_package(
    *,
    idx: Sequence[int],
    val: Sequence[int],
    dimension: int,
    mask_bits: int,
    expected_length: int | None = None,
) -> None:
    if len(idx) != len(val):
        raise ValueError("idx/val length mismatch")
    if expected_length is not None and len(idx) != int(expected_length):
        raise ValueError("unexpected sparse package length")
    indices = [int(item) for item in idx]
    if indices != sorted(indices) or len(indices) != len(set(indices)):
        raise ValueError("sparse package indices must be strictly increasing")
    if any(item < 0 or item >= int(dimension) for item in indices):
        raise ValueError("sparse package index out of range")
    share_modulus = 1 << int(mask_bits)
    if any(int(item) < 0 or int(item) >= share_modulus for item in val):
        raise ValueError("sparse package share out of range")


def package_digest_field(
    *,
    channel: str,
    context: Mapping[str, Any],
    idx: Sequence[int],
    val: Sequence[int],
    dimension: int,
    mask_bits: int,
    expected_length: int | None = None,
) -> int:
    route = str(channel).upper()
    if route not in {"A", "R"}:
        raise ValueError("invalid channel")
    validate_sparse_package(
        idx=idx,
        val=val,
        dimension=dimension,
        mask_bits=mask_bits,
        expected_length=expected_length,
    )
    return digest_field(
        {
            "channel": route,
            "context": dict(context),
            "dimension": int(dimension),
            "field": SHARE_FIELD_ID,
            "idx": [int(item) for item in idx],
            "mask_bits": int(mask_bits),
            "protocol": PROTOCOL_VERSION,
            "val": [int(item) for item in val],
        }
    )


def fingerprint_challenge(
    *,
    context_commitment: int,
    primary_commitment: int,
    package_digest_a: int,
    package_digest_r: int,
) -> int:
    return poseidon_chain(
        DOMAIN_FINGERPRINT,
        context_commitment,
        primary_commitment,
        package_digest_a,
        package_digest_r,
    )


def balanced_share_to_field(value: int, mask_bits: int) -> int:
    share_modulus = 1 << int(mask_bits)
    item = int(value)
    if item < 0 or item >= share_modulus:
        raise ValueError("share out of range")
    signed = item - share_modulus if item >= share_modulus // 2 else item
    return signed % SNARK_FIELD


def share_pair_reconstructs_in_field(
    *, clear_value: int, share_a: int, share_r: int, mask_bits: int
) -> bool:
    share_modulus = 1 << int(mask_bits)
    clear = int(clear_value)
    if clear < 0 or clear >= share_modulus:
        raise ValueError("clear value out of range")
    if (int(share_a) + int(share_r)) % share_modulus != clear:
        return False
    embedded_sum = (
        balanced_share_to_field(share_a, mask_bits)
        + balanced_share_to_field(share_r, mask_bits)
    ) % SNARK_FIELD
    return embedded_sum == balanced_share_to_field(clear, mask_bits)


def sample_reconstructible_share_pair(
    *, clear_value: int, mask_bits: int, randbelow=None
) -> tuple[int, int]:
    """Sample ring shares whose balanced embeddings preserve reconstruction."""
    share_modulus = 1 << int(mask_bits)
    clear = int(clear_value)
    if clear < 0 or clear >= share_modulus:
        raise ValueError("clear value out of range")
    sample = secrets.randbelow if randbelow is None else randbelow
    while True:
        share_a = int(sample(share_modulus))
        if share_a < 0 or share_a >= share_modulus:
            raise ValueError("share sampler returned an out-of-range value")
        share_r = (clear - share_a) % share_modulus
        if share_pair_reconstructs_in_field(
            clear_value=clear,
            share_a=share_a,
            share_r=share_r,
            mask_bits=mask_bits,
        ):
            return share_a, share_r


def _share_to_field(channel: str, value: int, mask_bits: int) -> int:
    route = str(channel).upper()
    if route not in {"A", "R"}:
        raise ValueError("invalid channel")
    return balanced_share_to_field(value, mask_bits)


def sparse_fingerprint(
    *,
    channel: str,
    idx: Sequence[int],
    val: Sequence[int],
    alpha: int,
    dimension: int,
    mask_bits: int,
    expected_length: int | None = None,
) -> int:
    validate_sparse_package(
        idx=idx,
        val=val,
        dimension=dimension,
        mask_bits=mask_bits,
        expected_length=expected_length,
    )
    total = 0
    for position, share in zip(idx, val):
        coefficient = _share_to_field(channel, int(share), mask_bits)
        total = (total + coefficient * pow(int(alpha), int(position), SNARK_FIELD)) % SNARK_FIELD
    return total


def derive_binding_fields(
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
    bit = int(contribution_bit)
    if bit not in {0, 1}:
        raise ValueError("contribution_bit must be boolean")
    primary = poseidon_chain(
        DOMAIN_PRIMARY, context_commitment, int(primary_idx), int(primary_salt)
    )
    alpha = fingerprint_challenge(
        context_commitment=context_commitment,
        primary_commitment=primary,
        package_digest_a=package_digest_a,
        package_digest_r=package_digest_r,
    )
    share_a = poseidon_chain(
        DOMAIN_CHANNEL_A,
        primary,
        context_commitment,
        package_digest_a,
        fingerprint_a,
    )
    share_r = poseidon_chain(
        DOMAIN_CHANNEL_R,
        primary,
        context_commitment,
        package_digest_r,
        fingerprint_r,
    )
    payload = poseidon_chain(
        DOMAIN_PAYLOAD,
        context_commitment,
        primary,
        share_a,
        share_r,
        bit,
    )
    blob_hash = poseidon_chain(
        DOMAIN_BLOB,
        context_commitment,
        package_digest_a,
        package_digest_r,
        payload,
    )
    return {
        "blob_hash": blob_hash,
        "fingerprint_challenge": alpha,
        "payload_commitment_v2": payload,
        "primary_commitment": primary,
        "share_content_commitment_a": share_a,
        "share_content_commitment_r": share_r,
    }


def validate_fingerprint_relation(
    *,
    fingerprint_a: int,
    fingerprint_r: int,
    alpha: int,
    primary_idx: int,
    contribution_bit: int,
) -> bool:
    lhs = (int(fingerprint_a) + int(fingerprint_r)) % SNARK_FIELD
    rhs = int(contribution_bit) * pow(int(alpha), int(primary_idx), SNARK_FIELD)
    return lhs == rhs % SNARK_FIELD


def report_identifier(*, round_id: int, tsip: Mapping[str, Any]) -> str:
    context = tsip.get("context")
    if not isinstance(context, Mapping):
        raise ValueError("missing report context")
    return digest_hex(
        {
            "blob_hash": str(tsip.get("blob_hash", "")),
            "context": dict(context),
            "domain": "shtpc/report-id",
            "package_digest_a": str(tsip.get("package_digest_a", "")),
            "package_digest_r": str(tsip.get("package_digest_r", "")),
            "payload_commitment": str(tsip.get("payload_commitment_v2", "")),
            "round_id": int(round_id),
            "share_commitment_a": str(tsip.get("share_content_commitment_a", "")),
            "share_commitment_r": str(tsip.get("share_content_commitment_r", "")),
        }
    )


def canonical_batch_digest(
    *,
    window_id: int,
    report_ids: Sequence[str],
    policy_version: str = POLICY_VERSION,
) -> str:
    canonical_ids = sorted(str(item) for item in report_ids)
    if len(canonical_ids) != len(set(canonical_ids)):
        raise ValueError("duplicate report identifier")
    return digest_hex(
        {
            "count": len(canonical_ids),
            "domain": "shtpc/batch",
            "policy_version": str(policy_version),
            "report_ids": canonical_ids,
            "window_id": int(window_id),
        }
    )


def aggregate_share_hash(aggregate: Mapping[int | str, int]) -> str:
    items = sorted((int(key), int(value)) for key, value in aggregate.items())
    return digest_hex({"domain": "shtpc/aggregate-share", "items": items})


def transcript_message(transcript: Mapping[str, Any]) -> bytes:
    return _canonical_bytes(
        {
            "aggregate_share_hash": str(transcript["aggregate_share_hash"]),
            "batch_digest": str(transcript["batch_digest"]),
            "channel": str(transcript["channel"]),
            "count": int(transcript["count"]),
            "domain": "shtpc/aggregate-transcript",
            "policy_version": str(transcript["policy_version"]),
            "window_id": int(transcript["window_id"]),
        }
    )


def sign_transcript(transcript: Mapping[str, Any], private_key_hex: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(str(private_key_hex)))
    return key.sign(transcript_message(transcript)).hex()


def verify_transcript_signature(
    transcript: Mapping[str, Any], signature_hex: str, public_key_hex: str
) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(str(public_key_hex)))
        key.verify(bytes.fromhex(str(signature_hex)), transcript_message(transcript))
        return True
    except (InvalidSignature, ValueError):
        return False


def build_aggregate_transcript(
    *,
    channel: str,
    window_id: int,
    report_ids: Sequence[str],
    aggregate: Mapping[int | str, int],
    private_key_hex: str,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    route = str(channel).upper()
    if route not in {"A", "R"}:
        raise ValueError("invalid transcript channel")
    transcript: dict[str, Any] = {
        "aggregate_share_hash": aggregate_share_hash(aggregate),
        "batch_digest": canonical_batch_digest(
            window_id=window_id,
            report_ids=report_ids,
            policy_version=policy_version,
        ),
        "channel": route,
        "count": len(report_ids),
        "policy_version": str(policy_version),
        "window_id": int(window_id),
    }
    transcript["signature"] = sign_transcript(transcript, private_key_hex)
    return transcript
