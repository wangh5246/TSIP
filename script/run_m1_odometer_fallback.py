#!/usr/bin/env python3
"""Run deterministic M1 safety/fairness checks for the V6 arithmetic core."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import TariffTable, fee_for_interval_values  # noqa: E402
from common.settlement_v6 import (  # noqa: E402
    UINT32_MAX,
    UINT64_MAX,
    UINT96_MAX,
    fee_for_interval_values_v6,
    reconcile_month_v6,
)


def _tariff() -> TariffTable:
    return TariffTable(
        tariff_version=8,
        grid_w=4,
        cell_zones={i: 10 + (i % 4) for i in range(16)},
        zone_rates_cents_per_m={10: 1, 11: 2, 12: 3, 13: 5},
    )


def _percentile(values: list[int], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = probability * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def validate_circuit_receipt(path: Path, *, require_profile_bound: bool = True) -> dict[str, Any]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema") != "waybill-settlement-v6-circuit-differential-receipt-v2":
        raise ValueError("unexpected V6 circuit receipt schema")
    if receipt.get("ok") is not True:
        raise ValueError("V6 Groth16 receipt is not verified")
    if receipt.get("circuit_python_differential_match") is not True:
        raise ValueError("V6 circuit/reference differential receipt failed")
    if receipt.get("public_signals") != receipt.get("python_reference_public_signals"):
        raise ValueError("V6 receipt public-signal vectors differ")
    if receipt.get("commitment_semantics") != "receiver-fix-validity-v2":
        raise ValueError("V6 receipt does not bind receiver-authenticated validity")
    if receipt.get("receiver_attestation_mode") != "independent-receiver-process":
        raise ValueError("V6 receipt was not produced from an independent receiver signer")
    if receipt.get("receiver_attestation_schema") != "waybill.receiver.root-attestation/v5":
        raise ValueError("V6 receipt uses an unexpected receiver attestation schema")
    if receipt.get("position_validity_rule") != "origin-osnma-authenticated-v1":
        raise ValueError("V6 receipt uses an unexpected position-validity rule")
    if len(str(receipt.get("receiver_log_sha256", ""))) != 64:
        raise ValueError("V6 receipt does not identify the sealed receiver log")
    if receipt.get("receiver_chain_mode") != "charger-online-cas-v1":
        raise ValueError("V6 receipt does not bind the Charger online confirmation chain")
    for field in (
        "receiver_attestation_sha256",
        "previous_attestation_sha256",
    ):
        digest = str(receipt.get(field, ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"V6 receipt has a malformed {field}")
    if int(receipt.get("receiver_log_epoch", 0)) < 1:
        raise ValueError("V6 receipt has an invalid receiver log epoch")
    if require_profile_bound:
        if receipt.get("canonical_profile_bound") is not True:
            raise ValueError("V6 circuit receipt is not bound to a canonical profile")
        if int(receipt.get("policy_profile_commitment", 0)) == 0:
            raise ValueError("V6 circuit receipt uses the reserved profileless commitment")
    return receipt


def run_m1_checks(*, trials: int = 2_000, seed: int = 20260713) -> dict[str, Any]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    tariff = _tariff()
    r_max = tariff.max_zone_rate_cents_per_m
    rng = random.Random(seed)

    parking_v5 = fee_for_interval_values(
        dt_sec=600,
        odo_delta_m=0,
        cell_idx=0,
        tariff=tariff,
        cadence_sec=300,
        tier_vmax_mps=33,
    )
    parking_v6 = fee_for_interval_values_v6(
        odometer_start_m=10_000,
        odometer_end_m=10_000,
        cell_idx=0,
        tariff=tariff,
        position_valid=False,
        r_max_cents_per_m=r_max,
    )

    max_withholding_advantage = 0
    outage_premiums: list[int] = []
    min_reconciled_margin = UINT96_MAX
    for _ in range(trials):
        distance = rng.randrange(0, 1_000_000)
        cell_idx = rng.randrange(0, 16)
        normal = fee_for_interval_values_v6(
            odometer_start_m=1_000,
            odometer_end_m=1_000 + distance,
            cell_idx=cell_idx,
            tariff=tariff,
            position_valid=True,
            r_max_cents_per_m=r_max,
        )
        outage = fee_for_interval_values_v6(
            odometer_start_m=1_000,
            odometer_end_m=1_000 + distance,
            cell_idx=cell_idx,
            tariff=tariff,
            position_valid=False,
            r_max_cents_per_m=r_max,
        )
        advantage = int(normal["fee_cents"]) - int(outage["fee_cents"])
        max_withholding_advantage = max(max_withholding_advantage, advantage)
        outage_premiums.append(int(outage["fee_cents"]) - int(normal["fee_cents"]))

        submitted_distance = rng.randrange(0, distance + 1) if distance else 0
        submitted_rate = rng.randrange(0, r_max + 1)
        full_rate = rng.randrange(0, r_max + 1)
        accepted_fee = submitted_distance * submitted_rate
        reconciled = reconcile_month_v6(
            monthly_odometer_start_m=0,
            monthly_odometer_end_m=distance,
            accounted_distance_m=submitted_distance,
            accepted_period_fee_cents=accepted_fee,
            r_max_cents_per_m=r_max,
        )
        # A submitted segment can itself have a lower true rate than the sampled
        # full-route rate, so compare against the exact decomposition bound.
        decomposed_true = accepted_fee + (distance - submitted_distance) * full_rate
        margin = int(reconciled["total_month_bill_cents"]) - decomposed_true
        min_reconciled_margin = min(min_reconciled_margin, margin)

    max_product = UINT64_MAX * UINT32_MAX
    return {
        "schema": "waybill-m1-odometer-fallback-check-v1",
        "seed": seed,
        "trials": trials,
        "formula": {
            "position_valid": "delta_odometer_m * zone_rate_cents_per_m",
            "outage": "delta_odometer_m * r_max_cents_per_m",
            "reconciliation": "max(0, monthly_delta_odometer_m - accounted_distance_m) * r_max",
        },
        "parking": {
            "delta_odometer_m": 0,
            "v5_time_fallback_fee_cents": int(parking_v5["fee_cents"]),
            "v6_odometer_fallback_fee_cents": int(parking_v6["fee_cents"]),
            "v6_exact_zero": int(parking_v6["fee_cents"]) == 0,
        },
        "withholding": {
            "max_advantage_cents": max_withholding_advantage,
            "no_benefit": max_withholding_advantage <= 0,
        },
        "honest_outage_premium_cents": {
            "mean": statistics.fmean(outage_premiums),
            "median": statistics.median(outage_premiums),
            "p95": _percentile(outage_premiums, 0.95),
            "max": max(outage_premiums),
        },
        "omission_reconciliation": {
            "minimum_margin_cents": min_reconciled_margin,
            "no_undercharge": min_reconciled_margin >= 0,
        },
        "integer_contract": {
            "odometer_bits": 64,
            "rate_bits": 32,
            "amount_bits": 96,
            "max_product": max_product,
            "max_product_within_uint96": max_product <= UINT96_MAX,
            "overflow_policy": "reject-u96",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run M1 V6 odometer fallback checks.")
    parser.add_argument("--trials", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=20260713)
    parser.add_argument(
        "--circuit-receipt",
        default="experiments/waybill_m1/v2/circuit_differential/receipt.json",
    )
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    result = run_m1_checks(trials=args.trials, seed=args.seed)
    receipt_path = (ROOT_DIR / args.circuit_receipt).resolve()
    if receipt_path.exists():
        receipt = validate_circuit_receipt(receipt_path)
        result["circuit_receipt"] = {
            "path": str(receipt_path),
            "ok": True,
            "constraints": receipt["constraints"],
            "public_signal_count": receipt["public_signal_count"],
            "differential_match": receipt["circuit_python_differential_match"],
            "canonical_profile_bound": receipt["canonical_profile_bound"],
            "policy_profile_commitment": receipt["policy_profile_commitment"],
        }
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
