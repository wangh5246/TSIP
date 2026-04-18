from __future__ import annotations

import json
import time
from typing import Dict, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


ATTESTATION_FIELDS = (
    "uid",
    "tier_vmax_sq",
    "com_sec",
    "com_modeset",
    "exp",
    "kid",
)


def parse_kid_pubkeys(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not raw:
        return out
    for item in str(raw).split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        kid, pk = item.split(":", 1)
        kid = kid.strip()
        pk = pk.strip().lower()
        if kid and pk:
            out[kid] = pk
    return out


def canonical_payload(attestation: dict) -> bytes:
    data = {}
    for k in ATTESTATION_FIELDS:
        if k not in attestation:
            raise ValueError(f"missing attestation field: {k}")
        data[k] = attestation[k]
    raw = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return raw.encode("utf-8")


def sign_attestation(private_key_hex: str, payload: dict) -> dict:
    sk_hex = str(private_key_hex or "").strip().lower()
    if sk_hex.startswith("0x"):
        sk_hex = sk_hex[2:]
    if len(sk_hex) != 64:
        raise ValueError("private key must be 32-byte hex")
    sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sk_hex))
    msg = canonical_payload(payload)
    sig = sk.sign(msg).hex()
    out = dict(payload)
    out["sig"] = sig
    return out


def _public_key_from_hex(pk_hex: str) -> Ed25519PublicKey:
    s = str(pk_hex or "").strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 64:
        raise ValueError("public key must be 32-byte hex")
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(s))


def verify_attestation(attestation: dict, pubkeys_by_kid: Dict[str, str], now_ts: int | None = None) -> Tuple[bool, str]:
    if not isinstance(attestation, dict):
        return False, "attestation must be object"
    sig = str(attestation.get("sig", "")).strip().lower()
    if not sig:
        return False, "missing attestation signature"
    if len(sig) != 128:
        return False, "invalid attestation signature length"
    kid = str(attestation.get("kid", "")).strip()
    if not kid:
        return False, "missing attestation kid"
    pk_hex = pubkeys_by_kid.get(kid, "")
    if not pk_hex:
        return False, f"unknown attestation kid: {kid}"

    try:
        exp = int(attestation.get("exp", 0) or 0)
    except Exception:
        return False, "invalid attestation exp"
    now = int(time.time()) if now_ts is None else int(now_ts)
    if exp <= now:
        return False, "attestation expired"

    try:
        msg = canonical_payload(attestation)
        pk = _public_key_from_hex(pk_hex)
        pk.verify(bytes.fromhex(sig), msg)
    except Exception as e:
        return False, f"attestation signature verify failed: {e}"
    return True, ""
