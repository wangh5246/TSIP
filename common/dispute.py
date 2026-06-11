"""Dispute-arbitration selective disclosure over interval_commitment_root.

A charger that rejects or questions a single interval should not force the
vehicle to reveal the whole period trajectory. This module lets the prover
open exactly one interval of the commitment chain bound by the circuit's
public ``interval_commitment_root`` and lets an arbiter verify the opening
offline, without touching the circuit or the proof.

The chain is the same one ``fee_for_period`` builds: state_0 = 0 and
state_{j+1} = Poseidon2(state_j, leaf_j), where each leaf commits to
(prev fixCommit, curr fixCommit, odo_delta, zone_id, zone_rate, fee,
fallback_flag). Opening interval i therefore discloses:

- level 1 (interval opening): the billing tuple of interval i plus the two
  opaque fix commitments, the chain prefix state, and the opaque suffix
  leaves;
- level 2 (fix opening, optional): the two raw fixes bounding interval i,
  which lets the arbiter recompute the fee via ``fee_for_interval_values``.

Positional binding comes from two independent sources: the suffix length
pins ``interval_index`` relative to the public interval count, and a level-2
opening additionally pins it through the committed ``fix_seq`` values.
"""

from __future__ import annotations

from typing import Any

from common.poseidon2_py import _poseidon2
from common.settlement import (
    SETTLEMENT_MAX_DT_SEC,
    SNARK_FIELD,
    ReceiverFix,
    TariffTable,
    compute_fix_commitment,
    fee_for_interval_values,
    field_from_text,
    poseidon_chain,
    verify_receiver_fix_signature,
)

DISPUTE_OPENING_DOMAIN = "tsip_settlement_dispute_opening_v1"

_LEAF_VALUE_KEYS = (
    "prev_fix_commitment",
    "curr_fix_commitment",
    "odo_delta_m",
    "zone_id",
    "zone_rate_cents_per_m",
    "fee_cents",
    "fallback_flag",
)


def interval_leaf(values: dict[str, Any]) -> int:
    """Recompute one interval commitment leaf from its disclosed values."""

    return poseidon_chain([int(values[key]) for key in _LEAF_VALUE_KEYS])


def build_interval_records(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int = SETTLEMENT_MAX_DT_SEC,
    fallback_rate_cents_per_m: int | None = None,
    dac_field: int = 0,
) -> list[dict[str, Any]]:
    """Return per-interval billing values and chain leaves for a period.

    Must stay value-identical to the commitment loop in ``fee_for_period``;
    tests/test_dispute_opening.py pins that equality.
    """

    if len(fixes) < 2:
        raise ValueError("at least two receiver fixes are required")
    records: list[dict[str, Any]] = []
    for index, (prev, curr) in enumerate(zip(fixes, fixes[1:])):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        interval = fee_for_interval_values(
            dt_sec=dt,
            odo_delta_m=odo_delta,
            cell_idx=tariff.cell_index(prev.cell_x, prev.cell_y),
            tariff=tariff,
            cadence_sec=cadence_sec,
            tier_vmax_mps=tier_vmax_mps,
            max_dt_sec=max_dt_sec,
            fallback_rate_cents_per_m=fallback_rate_cents_per_m,
        )
        values = {
            "prev_fix_commitment": compute_fix_commitment(prev, dac_field=dac_field),
            "curr_fix_commitment": compute_fix_commitment(curr, dac_field=dac_field),
            "odo_delta_m": odo_delta,
            "zone_id": int(interval["zone_id"]),
            "zone_rate_cents_per_m": int(interval["zone_rate_cents_per_m"]),
            "fee_cents": int(interval["fee_cents"]),
            "fallback_flag": int(dt > int(cadence_sec)),
        }
        records.append(
            {
                "interval_index": index,
                "dt_sec": dt,
                "values": values,
                "leaf": interval_leaf(values),
            }
        )
    return records


def build_interval_opening(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    interval_index: int,
    *,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int = SETTLEMENT_MAX_DT_SEC,
    fallback_rate_cents_per_m: int | None = None,
    device_attestation_commitment: str | None = None,
    include_fix_opening: bool = False,
) -> dict[str, Any]:
    """Build the selective-disclosure opening for one disputed interval."""

    dac_field = field_from_text(str(device_attestation_commitment)) if device_attestation_commitment else 0
    records = build_interval_records(
        fixes,
        tariff,
        cadence_sec=cadence_sec,
        tier_vmax_mps=tier_vmax_mps,
        max_dt_sec=max_dt_sec,
        fallback_rate_cents_per_m=fallback_rate_cents_per_m,
        dac_field=dac_field,
    )
    if not 0 <= interval_index < len(records):
        raise ValueError("interval_index out of range")
    prefix_state = 0
    for record in records[:interval_index]:
        prefix_state = int(_poseidon2(int(prefix_state), int(record["leaf"]) % SNARK_FIELD))
    opened = records[interval_index]
    opening: dict[str, Any] = {
        "domain_sep": DISPUTE_OPENING_DOMAIN,
        "period_id": str(fixes[0].period_id),
        "interval_index": int(interval_index),
        "interval_count": len(records),
        "prefix_state": str(prefix_state),
        "interval": {key: str(value) for key, value in opened["values"].items()},
        "suffix_leaves": [str(record["leaf"]) for record in records[interval_index + 1 :]],
    }
    if include_fix_opening:
        opening["fix_opening"] = {
            "prev": fixes[interval_index].to_dict(),
            "curr": fixes[interval_index + 1].to_dict(),
        }
    return opening


def verify_interval_opening(
    opening: dict[str, Any],
    *,
    interval_commitment_root: int | str,
    expected_interval_count: int | None = None,
    device_attestation_commitment: str | None = None,
    device_public_key_bytes: bytes | None = None,
    tariff: TariffTable | None = None,
    cadence_sec: int | None = None,
    tier_vmax_mps: int | None = None,
    max_dt_sec: int = SETTLEMENT_MAX_DT_SEC,
    fallback_rate_cents_per_m: int | None = None,
) -> dict[str, Any]:
    """Verify a disputed-interval opening against the public chain root.

    Always checks the chain reconstruction and positional binding. When a
    level-2 fix opening is present, additionally checks fix commitments,
    sequence adjacency, and (when tariff/policy parameters are supplied)
    recomputes the interval fee through ``fee_for_interval_values``.
    Returns ``{"ok": bool, "failed": [check names]}``.
    """

    failed: list[str] = []

    def check(name: str, ok: bool) -> None:
        if not ok:
            failed.append(name)

    try:
        check("domain_sep", str(opening.get("domain_sep")) == DISPUTE_OPENING_DOMAIN)
        interval_index = int(opening["interval_index"])
        interval_count = int(opening["interval_count"])
        suffix = [int(x) for x in opening.get("suffix_leaves", [])]
        values = {key: int(opening["interval"][key]) for key in _LEAF_VALUE_KEYS}

        check("position_binding", interval_index == interval_count - 1 - len(suffix))
        if expected_interval_count is not None:
            check("interval_count", interval_count == int(expected_interval_count))
        check("fallback_flag_range", values["fallback_flag"] in (0, 1))

        state = int(opening["prefix_state"]) % SNARK_FIELD
        if interval_index == 0:
            check("prefix_state_zero", state == 0)
        state = int(_poseidon2(state, interval_leaf(values) % SNARK_FIELD))
        for leaf in suffix:
            state = int(_poseidon2(state, leaf % SNARK_FIELD))
        check("chain_root", state == int(interval_commitment_root) % SNARK_FIELD)

        fix_opening = opening.get("fix_opening")
        if fix_opening is not None:
            prev = ReceiverFix.from_dict(fix_opening["prev"])
            curr = ReceiverFix.from_dict(fix_opening["curr"])
            dac_field = (
                field_from_text(str(device_attestation_commitment)) if device_attestation_commitment else 0
            )
            check(
                "prev_fix_commitment",
                compute_fix_commitment(prev, dac_field=dac_field) == values["prev_fix_commitment"],
            )
            check(
                "curr_fix_commitment",
                compute_fix_commitment(curr, dac_field=dac_field) == values["curr_fix_commitment"],
            )
            check("fix_seq_position", int(prev.fix_seq) == interval_index and int(curr.fix_seq) == interval_index + 1)
            check("period_id", prev.period_id == opening.get("period_id") == curr.period_id)
            dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
            odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
            check("time_monotonic", dt > 0)
            check("odo_delta", odo_delta == values["odo_delta_m"])
            if device_public_key_bytes is not None:
                check(
                    "fix_signatures",
                    verify_receiver_fix_signature(prev, device_public_key_bytes)
                    and verify_receiver_fix_signature(curr, device_public_key_bytes),
                )
            if tariff is not None and cadence_sec is not None and tier_vmax_mps is not None:
                billed = fee_for_interval_values(
                    dt_sec=dt,
                    odo_delta_m=odo_delta,
                    cell_idx=tariff.cell_index(prev.cell_x, prev.cell_y),
                    tariff=tariff,
                    cadence_sec=cadence_sec,
                    tier_vmax_mps=tier_vmax_mps,
                    max_dt_sec=max_dt_sec,
                    fallback_rate_cents_per_m=fallback_rate_cents_per_m,
                )
                check("fee_recompute", int(billed["fee_cents"]) == values["fee_cents"])
                check("zone_recompute", int(billed["zone_id"]) == values["zone_id"])
                check("rate_recompute", int(billed["zone_rate_cents_per_m"]) == values["zone_rate_cents_per_m"])
                check("fallback_recompute", int(billed["fallback"]) == values["fallback_flag"])
    except (KeyError, TypeError, ValueError):
        failed.append("malformed_opening")

    return {"ok": not failed, "failed": failed}


def opening_disclosure_profile(opening: dict[str, Any]) -> list[str]:
    """List the trajectory-level fields a single arbitration opening reveals.

    Feeds the E5 leakage accounting: one level-1 opening reveals one
    interval's billing tuple; a level-2 opening additionally reveals the two
    bounding fixes (cell, time, odometer) of that interval only.
    """

    disclosed = [f"interval[{opening['interval_index']}].{key}" for key in _LEAF_VALUE_KEYS]
    if opening.get("fix_opening") is not None:
        for side in ("prev", "curr"):
            disclosed += [
                f"fix[{side}].{field}"
                for field in ("auth_gnss_time", "cell_x", "cell_y", "odometer_reading_m", "fix_seq", "nonce")
            ]
    return disclosed
