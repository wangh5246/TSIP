#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import (  # noqa: E402
    ReceiverFix,
    TariffTable,
    build_period_public_statement,
    sign_receiver_fix,
)


def build_demo_submission(receiver_secret: str) -> dict:
    period_id = "2026-05-p01"
    month_id = "2026-05"
    month_start_time = 1_777_593_600
    raw_fixes = [
        ReceiverFix("dev-1", period_id, 0, month_start_time + 100, 0, 0, "authenticated", 1_000, "nonce-0"),
        ReceiverFix("dev-1", period_id, 1, month_start_time + 110, 1, 0, "authenticated", 1_070, "nonce-1"),
        ReceiverFix("dev-1", period_id, 2, month_start_time + 180, 1, 1, "authenticated", 1_120, "nonce-2"),
    ]
    receiver_seed = hashlib.sha256(receiver_secret.encode("utf-8")).digest()
    fixes = [sign_receiver_fix(fix, receiver_seed) for fix in raw_fixes]
    tariff = TariffTable(
        tariff_version=7,
        grid_w=2,
        cell_zones={0: 10, 1: 10, 2: 20, 3: 20},
        zone_rates_cents_per_m={10: 1, 20: 5},
    )
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id=period_id,
        month_id=month_id,
        cadence_sec=60,
        tier_vmax_mps=33,
        device_attestation_commitment="attested-device-v1",
    )
    return {
        "fixes": [fix.to_dict() for fix in fixes],
        "tariff": {
            "tariff_version": tariff.tariff_version,
            "grid_w": tariff.grid_w,
            "cell_zones": tariff.cell_zones,
            "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
        },
        "public_statement": public,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a demo settlement period submission.")
    parser.add_argument("--receiver-secret", default="receiver-dev-secret")
    args = parser.parse_args()
    print(json.dumps(build_demo_submission(args.receiver_secret), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
