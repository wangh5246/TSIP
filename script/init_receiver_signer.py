#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.settlement import make_device_attestation_commitment  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an independent receiver signer identity.")
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    path = args.key_file
    if not path.is_absolute():
        raise SystemExit("--key-file must be an absolute path")
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_stat = os.lstat(path.parent)
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.geteuid()
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
    ):
        raise SystemExit("receiver state directory must be owned by this user and mode 0700")
    private_key = Ed25519PrivateKey.generate()
    seed = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(seed)
        handle.flush()
        os.fsync(handle.fileno())
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print(
        json.dumps(
            {
                "key_file": str(path),
                "public_key_hex": public_key.hex(),
                "device_attestation_commitment": make_device_attestation_commitment(public_key),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
