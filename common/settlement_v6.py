"""Versioned WayBill V6 odometer-backed settlement reference model.

V5 remains in :mod:`common.settlement` as the time/speed fallback baseline.
This module freezes the V6 arithmetic contract used by the V6 circuit:

* ``position_valid=True``: ``delta_odometer * tariff_rate(zone)``;
* ``position_valid=False``: ``delta_odometer * canonical_r_max``;
* month close: only unaccounted odometer distance is billed at ``r_max``.

The widths are part of the protocol, not serialization hints.  Python's
unbounded integers are checked before every protocol multiplication/addition
so the reference cannot silently accept a value that the circuit rejects.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from common.settlement import (
    SETTLEMENT_CAP_POLICY_SQ,
    SETTLEMENT_MAX_DT_SEC,
    SETTLEMENT_PERIOD_MAX_SEC,
    SNARK_FIELD,
    ReceiverFix,
    TariffTable,
    canonical_month_window,
    commitment_chain_root,
    compute_public_statement_commitment,
    field_from_text,
    month_window_from_period_start,
    poseidon_chain,
    verify_fix_sequence,
)


ODOMETER_BITS = 64
RATE_BITS = 32
AMOUNT_BITS = 96
TIME_BITS = 48
SMALL_POLICY_BITS = 16

UINT16_MAX = (1 << SMALL_POLICY_BITS) - 1
UINT32_MAX = (1 << RATE_BITS) - 1
UINT48_MAX = (1 << TIME_BITS) - 1
UINT64_MAX = (1 << ODOMETER_BITS) - 1
UINT96_MAX = (1 << AMOUNT_BITS) - 1

SETTLEMENT_PUBLIC_V6_DOMAIN = "tsip_settlement_public_v6"

PUBLIC_SIGNAL_ORDER_V6 = [
    "receiver_fix_root",
    "tariff_root",
    "interval_commitment_root",
    "policy_profile_commitment",
    "period_id_field",
    "tariff_version",
    "device_attestation_commitment",
    "total_fee_cents",
    "total_distance_m",
    "fallback_intervals",
    "cadence_sec",
    "tier_vmax_mps",
    "tier_vmax_sq",
    "mode_vmax_sq",
    "cap_policy_sq",
    "max_zone_rate_cents_per_m",
    "max_dt_sec",
    "period_start_time",
    "period_end_time",
    "month_id",
    "month_start_time",
    "month_end_time",
]
PUBLIC_SIGNAL_COUNT_V6 = len(PUBLIC_SIGNAL_ORDER_V6)


def _require_int(name: str, value: object) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be int")
    return value


def _require_uint(name: str, value: object, bits: int) -> int:
    number = _require_int(name, value)
    if number < 0 or number > (1 << bits) - 1:
        raise OverflowError(f"{name} must fit uint{bits}")
    return number


def _require_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool")
    return value


def _require_field(name: str, value: object) -> int:
    number = _require_int(name, value)
    if number < 0 or number >= SNARK_FIELD:
        raise OverflowError(f"{name} must be a canonical SNARK field element")
    return number


def _checked_add(name: str, left: int, right: int, bits: int) -> int:
    result = left + right
    if result > (1 << bits) - 1:
        raise OverflowError(f"{name} must fit uint{bits}")
    return result


def _checked_mul(name: str, left: int, right: int, bits: int) -> int:
    result = left * right
    if result > (1 << bits) - 1:
        raise OverflowError(f"{name} must fit uint{bits}")
    return result


def _validate_tariff_and_rmax(tariff: TariffTable, r_max_cents_per_m: object) -> int:
    if not tariff.zone_rates_cents_per_m:
        raise ValueError("tariff has no zone rates")
    _require_uint("tariff_version", tariff.tariff_version, RATE_BITS)
    _require_uint("tariff grid_w", tariff.grid_w, RATE_BITS)
    if int(tariff.grid_w) == 0:
        raise ValueError("tariff grid_w must be positive")

    rates: list[int] = []
    for raw_zone, raw_rate in tariff.zone_rates_cents_per_m.items():
        _require_uint(f"tariff zone {raw_zone}", raw_zone, RATE_BITS)
        rates.append(_require_uint(f"tariff rate for zone {raw_zone}", raw_rate, RATE_BITS))
    for raw_cell, raw_zone in tariff.cell_zones.items():
        _require_uint(f"tariff cell {raw_cell}", raw_cell, RATE_BITS)
        zone = _require_uint(f"tariff cell {raw_cell} zone", raw_zone, RATE_BITS)
        if zone not in tariff.zone_rates_cents_per_m:
            raise ValueError(f"missing tariff rate for zone {zone}")

    r_max = _require_uint("r_max_cents_per_m", r_max_cents_per_m, RATE_BITS)
    if r_max != max(rates):
        raise ValueError("r_max_cents_per_m must equal tariff maximum rate")
    return r_max


def compute_fix_commitment_v6(
    fix: ReceiverFix,
    *,
    dac_field: int = 0,
    policy_profile_commitment: int = 0,
) -> int:
    """Commit a fix under the exact V6 policy profile used by the circuit."""

    dac = _require_field("dac_field", dac_field)
    policy_commitment = _require_field("policy_profile_commitment", policy_profile_commitment)
    return poseidon_chain(
        [
            dac,
            policy_commitment,
            field_from_text(fix.period_id),
            _require_uint("fix_seq", fix.fix_seq, RATE_BITS),
            _require_uint("auth_gnss_time", fix.auth_gnss_time, TIME_BITS),
            _require_uint("cell_x", fix.cell_x, RATE_BITS),
            _require_uint("cell_y", fix.cell_y, RATE_BITS),
            _require_uint("odometer_reading_m", fix.odometer_reading_m, ODOMETER_BITS),
            field_from_text(fix.nonce),
        ]
    )


def compute_receiver_fix_root_v6(
    fixes: Sequence[ReceiverFix],
    *,
    dac_field: int = 0,
    policy_profile_commitment: int = 0,
) -> int:
    return commitment_chain_root(
        [
            compute_fix_commitment_v6(
                fix,
                dac_field=dac_field,
                policy_profile_commitment=policy_profile_commitment,
            )
            for fix in fixes
        ]
    )


def _fee_for_interval_validated(
    *,
    odometer_start_m: int,
    odometer_end_m: int,
    cell_idx: int,
    tariff: TariffTable,
    position_valid: bool,
    r_max_cents_per_m: int,
) -> dict[str, int | bool]:
    start = _require_uint("odometer_start_m", odometer_start_m, ODOMETER_BITS)
    end = _require_uint("odometer_end_m", odometer_end_m, ODOMETER_BITS)
    valid = _require_bool("position_valid", position_valid)
    cell = _require_uint("cell_idx", cell_idx, RATE_BITS)
    if end < start:
        raise ValueError("odometer readings must be monotonic")

    delta = end - start
    zone_id = _require_uint("zone_id", tariff.zone_for_cell(cell), RATE_BITS)
    zone_rate = _require_uint(
        "zone_rate_cents_per_m",
        tariff.rate_for_zone(zone_id),
        RATE_BITS,
    )
    if zone_rate > r_max_cents_per_m:
        raise ValueError("zone rate exceeds canonical r_max")

    normal_fee = _checked_mul("normal_fee_cents", delta, zone_rate, AMOUNT_BITS)
    outage_fee = _checked_mul(
        "outage_fee_cents",
        delta,
        r_max_cents_per_m,
        AMOUNT_BITS,
    )
    fee = normal_fee if valid else outage_fee
    return {
        "odometer_delta_m": delta,
        "charged_distance_m": delta,
        "position_valid": valid,
        "fallback": not valid,
        "zone_id": zone_id,
        "zone_rate_cents_per_m": zone_rate,
        "r_max_cents_per_m": r_max_cents_per_m,
        "normal_fee_cents": normal_fee,
        "outage_fee_cents": outage_fee,
        "fee_cents": fee,
    }


def fee_for_interval_values_v6(
    *,
    odometer_start_m: int,
    odometer_end_m: int,
    cell_idx: int,
    tariff: TariffTable,
    position_valid: bool,
    r_max_cents_per_m: int,
) -> dict[str, int | bool]:
    """Compute one V6 interval after enforcing the canonical integer contract."""

    r_max = _validate_tariff_and_rmax(tariff, r_max_cents_per_m)
    return _fee_for_interval_validated(
        odometer_start_m=odometer_start_m,
        odometer_end_m=odometer_end_m,
        cell_idx=cell_idx,
        tariff=tariff,
        position_valid=position_valid,
        r_max_cents_per_m=r_max,
    )


def fee_for_period_v6(
    fixes: Sequence[ReceiverFix],
    tariff: TariffTable,
    *,
    position_valid: Sequence[bool],
    r_max_cents_per_m: int,
    max_dt_sec: int | None = SETTLEMENT_MAX_DT_SEC,
    tier_vmax_mps: int | None = None,
    dac_field: int = 0,
    policy_profile_commitment: int = 0,
) -> dict[str, Any]:
    """Compute a V6 period bill and its circuit-compatible commitment root.

    ``position_valid`` is deliberately mandatory and contains exactly one
    strict boolean per interval.  Time and speed constraints remain admission
    checks when supplied, but neither value enters the V6 billing formula.
    """

    if len(fixes) < 2:
        raise ValueError("at least two receiver fixes are required")
    if len(position_valid) != len(fixes) - 1:
        raise ValueError("expected one position_valid flag per interval")
    flags = [_require_bool(f"position_valid[{i}]", flag) for i, flag in enumerate(position_valid)]
    r_max = _validate_tariff_and_rmax(tariff, r_max_cents_per_m)
    dac = _require_field("dac_field", dac_field)
    profile_commitment = _require_field(
        "policy_profile_commitment",
        policy_profile_commitment,
    )

    max_dt: int | None = None
    if max_dt_sec is not None:
        max_dt = _require_uint("max_dt_sec", max_dt_sec, SMALL_POLICY_BITS)
        if max_dt == 0:
            raise ValueError("max_dt_sec must be positive")
    vmax: int | None = None
    if tier_vmax_mps is not None:
        vmax = _require_uint("tier_vmax_mps", tier_vmax_mps, SMALL_POLICY_BITS)

    total_fee = 0
    total_distance = 0
    fallback_distance = 0
    fallback_intervals = 0
    private_zone_distance: dict[int, int] = {}
    interval_commitments: list[int] = []

    for i, (prev, curr, valid) in enumerate(zip(fixes, fixes[1:], flags)):
        prev_time = _require_uint(f"auth_time[{i}]", prev.auth_gnss_time, TIME_BITS)
        curr_time = _require_uint(f"auth_time[{i + 1}]", curr.auth_gnss_time, TIME_BITS)
        if curr_time <= prev_time:
            raise ValueError("authenticated time must be strictly increasing")
        dt = curr_time - prev_time
        if max_dt is not None and dt > max_dt:
            raise ValueError("authenticated time delta exceeds maximum")

        prev_odometer = _require_uint(
            f"odometer_m[{i}]",
            prev.odometer_reading_m,
            ODOMETER_BITS,
        )
        curr_odometer = _require_uint(
            f"odometer_m[{i + 1}]",
            curr.odometer_reading_m,
            ODOMETER_BITS,
        )
        cell_idx = tariff.cell_index(
            _require_uint(f"cell_x[{i}]", prev.cell_x, RATE_BITS),
            _require_uint(f"cell_y[{i}]", prev.cell_y, RATE_BITS),
        )
        interval = _fee_for_interval_validated(
            odometer_start_m=prev_odometer,
            odometer_end_m=curr_odometer,
            cell_idx=cell_idx,
            tariff=tariff,
            position_valid=valid,
            r_max_cents_per_m=r_max,
        )
        delta = int(interval["odometer_delta_m"])
        if vmax is not None:
            speed_budget = _checked_mul("odometer speed budget", dt, vmax, ODOMETER_BITS)
            if delta > speed_budget:
                raise ValueError("odometer delta exceeds tier speed budget")

        fee = int(interval["fee_cents"])
        zone_id = int(interval["zone_id"])
        zone_rate = int(interval["zone_rate_cents_per_m"])
        fallback_flag = int(not valid)
        total_distance = _checked_add("total_distance_m", total_distance, delta, ODOMETER_BITS)
        total_fee = _checked_add("total_fee_cents", total_fee, fee, AMOUNT_BITS)
        if valid:
            private_zone_distance[zone_id] = _checked_add(
                f"private_zone_distance_m[{zone_id}]",
                private_zone_distance.get(zone_id, 0),
                delta,
                ODOMETER_BITS,
            )
        else:
            fallback_distance = _checked_add(
                "fallback_distance_m",
                fallback_distance,
                delta,
                ODOMETER_BITS,
            )
            fallback_intervals = _checked_add(
                "fallback_intervals",
                fallback_intervals,
                1,
                RATE_BITS,
            )

        interval_commitments.append(
            poseidon_chain(
                [
                    compute_fix_commitment_v6(
                        prev,
                        dac_field=dac,
                        policy_profile_commitment=profile_commitment,
                    ),
                    compute_fix_commitment_v6(
                        curr,
                        dac_field=dac,
                        policy_profile_commitment=profile_commitment,
                    ),
                    delta,
                    zone_id,
                    zone_rate,
                    fee,
                    fallback_flag,
                ]
            )
        )

    return {
        "settlement_semantics_version": "odometer-max-rate-v6",
        "total_fee_cents": total_fee,
        "total_distance_m": total_distance,
        "accounted_distance_m": total_distance,
        "fallback_distance_m": fallback_distance,
        "fallback_intervals": fallback_intervals,
        "position_valid_intervals": len(fixes) - 1 - fallback_intervals,
        "private_zone_distance_m": dict(sorted(private_zone_distance.items())),
        "interval_commitment_root": commitment_chain_root(interval_commitments),
    }


def build_period_public_statement_v6(
    *,
    fixes: Sequence[ReceiverFix],
    tariff: TariffTable,
    position_valid: Sequence[bool],
    period_id: str,
    month_id: str,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int,
    r_max_cents_per_m: int,
    device_attestation_commitment: str,
    tariff_tree_depth: int | None = None,
    mode_vmax_sq: int | None = None,
    cap_policy_sq: int = SETTLEMENT_CAP_POLICY_SQ,
    policy_profile: Any | None = None,
) -> dict[str, Any]:
    """Build the statement committed by the V6 proof and root attestation.

    Profileless construction is retained for isolated differential tests and
    uses the reserved commitment ``0``.  Production callers pass the canonical
    ``policy_profile``; its commitment is then embedded in every V6 fix
    commitment as well as exposed as a public signal.
    """

    if len(fixes) < 2:
        raise ValueError("at least two receiver fixes are required")
    cadence = _require_uint("cadence_sec", cadence_sec, SMALL_POLICY_BITS)
    tier_vmax = _require_uint("tier_vmax_mps", tier_vmax_mps, SMALL_POLICY_BITS)
    max_dt = _require_uint("max_dt_sec", max_dt_sec, SMALL_POLICY_BITS)
    if cadence == 0 or tier_vmax == 0 or max_dt == 0:
        raise ValueError("cadence_sec, tier_vmax_mps, and max_dt_sec must be positive")
    r_max = _validate_tariff_and_rmax(tariff, r_max_cents_per_m)
    tree_depth = tariff_tree_depth
    mode_vmax = tier_vmax * tier_vmax if mode_vmax_sq is None else _require_uint(
        "mode_vmax_sq",
        mode_vmax_sq,
        RATE_BITS,
    )
    cap_policy = _require_uint("cap_policy_sq", cap_policy_sq, 80)
    profile_commitment = 0

    if policy_profile is not None:
        policy_profile.assert_tariff_matches(tariff)
        profile_checks = {
            "cadence_sec": cadence,
            "tier_vmax_mps": tier_vmax,
            "max_dt_sec": max_dt,
            "max_zone_rate_cents_per_m": r_max,
            "mode_vmax_sq": mode_vmax,
            "cap_policy_sq": cap_policy,
        }
        for name, actual in profile_checks.items():
            if actual != int(getattr(policy_profile, name)):
                raise ValueError(f"{name} does not match canonical policy profile")
        if tree_depth is not None and int(tree_depth) != int(policy_profile.tariff_tree_depth):
            raise ValueError("tariff_tree_depth does not match canonical policy profile")
        tree_depth = int(policy_profile.tariff_tree_depth)
        if len(fixes) > int(policy_profile.max_fixes):
            raise ValueError("period exceeds canonical policy fix cap")
        if str(policy_profile.overflow_policy) != "reject-u96":
            raise ValueError("V6 circuit requires reject-u96 overflow policy")
        if not str(policy_profile.fallback_semantics_version).startswith("odometer-max-rate"):
            raise ValueError("policy profile does not select odometer-backed fallback")
        profile_commitment = _require_field(
            "policy_profile_commitment",
            int(policy_profile.commitment),
        )

    if tree_depth is not None:
        tree_depth = _require_uint("tariff_tree_depth", tree_depth, SMALL_POLICY_BITS)
    period_start_time = _require_uint("period_start_time", fixes[0].auth_gnss_time, TIME_BITS)
    period_end_time = _require_uint("period_end_time", fixes[-1].auth_gnss_time, TIME_BITS)
    period_span = period_end_time - period_start_time
    if not 0 < period_span <= SETTLEMENT_PERIOD_MAX_SEC:
        raise ValueError("period span must be positive and at most 14400 seconds")
    month_id_field, month_start_time, month_end_time = month_window_from_period_start(period_start_time)
    requested_month = canonical_month_window(month_id)
    if int(requested_month["month_id"]) != month_id_field:
        raise ValueError("month_id does not match period start")

    dac_field = field_from_text(str(device_attestation_commitment))
    fee = fee_for_period_v6(
        fixes,
        tariff,
        position_valid=position_valid,
        r_max_cents_per_m=r_max,
        max_dt_sec=max_dt,
        tier_vmax_mps=tier_vmax,
        dac_field=dac_field,
        policy_profile_commitment=profile_commitment,
    )
    public: dict[str, Any] = {
        "domain_sep": SETTLEMENT_PUBLIC_V6_DOMAIN,
        "period_id": str(period_id),
        "period_id_field": field_from_text(str(period_id)),
        "month_id": str(month_id),
        "month_id_field": month_id_field,
        "month_start_time": month_start_time,
        "month_end_time": month_end_time,
        "period_start_time": period_start_time,
        "period_end_time": period_end_time,
        "max_dt_sec": max_dt,
        "tariff_version": int(tariff.tariff_version),
        "cadence_sec": cadence,
        "tier_vmax_mps": tier_vmax,
        "tier_vmax_sq": tier_vmax * tier_vmax,
        "mode_vmax_sq": mode_vmax,
        "cap_policy_sq": cap_policy,
        "max_zone_rate_cents_per_m": r_max,
        "receiver_fix_root": str(
            compute_receiver_fix_root_v6(
                fixes,
                dac_field=dac_field,
                policy_profile_commitment=profile_commitment,
            )
        ),
        "tariff_root": str(tariff.root(tree_depth)),
        "interval_commitment_root": str(fee["interval_commitment_root"]),
        "policy_profile_commitment": str(profile_commitment),
        "device_attestation_commitment": str(device_attestation_commitment),
        "total_fee_cents": int(fee["total_fee_cents"]),
        "total_distance_m": int(fee["total_distance_m"]),
        "fallback_intervals": int(fee["fallback_intervals"]),
        "position_valid_intervals": int(fee["position_valid_intervals"]),
        "fallback_semantics_version": "odometer-max-rate-v6",
    }
    if policy_profile is not None:
        public.update(policy_profile.public_statement_fields())
    public["statement_commitment"] = compute_public_statement_commitment(public)
    return public


def verify_period_submission_v6(
    *,
    fixes: Sequence[ReceiverFix],
    tariff: TariffTable,
    position_valid: Sequence[bool],
    public_statement: dict[str, Any],
    public_key_bytes: bytes,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int,
    r_max_cents_per_m: int,
    tariff_tree_depth: int | None = None,
    mode_vmax_sq: int | None = None,
    cap_policy_sq: int = SETTLEMENT_CAP_POLICY_SQ,
    policy_profile: Any | None = None,
) -> dict[str, Any]:
    """Verify authenticated fixes and recompute the complete V6 statement."""

    period_id = str(public_statement["period_id"])
    verify_fix_sequence(list(fixes), public_key_bytes=public_key_bytes, period_id=period_id)
    expected = build_period_public_statement_v6(
        fixes=fixes,
        tariff=tariff,
        position_valid=position_valid,
        period_id=period_id,
        month_id=str(public_statement["month_id"]),
        cadence_sec=cadence_sec,
        tier_vmax_mps=tier_vmax_mps,
        max_dt_sec=max_dt_sec,
        r_max_cents_per_m=r_max_cents_per_m,
        device_attestation_commitment=str(public_statement["device_attestation_commitment"]),
        tariff_tree_depth=tariff_tree_depth,
        mode_vmax_sq=mode_vmax_sq,
        cap_policy_sq=cap_policy_sq,
        policy_profile=policy_profile,
    )
    for key, value in expected.items():
        if public_statement.get(key) != value:
            raise ValueError(f"public statement mismatch: {key}")
    return expected


def reconcile_month_v6(
    *,
    monthly_odometer_start_m: int,
    monthly_odometer_end_m: int,
    accounted_distance_m: int,
    accepted_period_fee_cents: int,
    r_max_cents_per_m: int,
    tolerance_m: int = 0,
) -> dict[str, int]:
    """Bill only monthly distance not covered by accepted period proofs."""

    start = _require_uint("monthly_odometer_start_m", monthly_odometer_start_m, ODOMETER_BITS)
    end = _require_uint("monthly_odometer_end_m", monthly_odometer_end_m, ODOMETER_BITS)
    accounted = _require_uint("accounted_distance_m", accounted_distance_m, ODOMETER_BITS)
    accepted_fee = _require_uint(
        "accepted_period_fee_cents",
        accepted_period_fee_cents,
        AMOUNT_BITS,
    )
    r_max = _require_uint("r_max_cents_per_m", r_max_cents_per_m, RATE_BITS)
    tolerance = _require_uint("tolerance_m", tolerance_m, ODOMETER_BITS)
    if end < start:
        raise ValueError("monthly odometer readings must be monotonic")

    monthly_distance = end - start
    excess = max(0, accounted - monthly_distance)
    if excess > tolerance:
        raise ValueError("accounted distance exceeds monthly odometer delta plus tolerance")
    unaccounted = max(0, monthly_distance - accounted)
    reconciliation_fee = _checked_mul(
        "reconciliation_fee_cents",
        unaccounted,
        r_max,
        AMOUNT_BITS,
    )
    total_bill = _checked_add(
        "total_month_bill_cents",
        accepted_fee,
        reconciliation_fee,
        AMOUNT_BITS,
    )
    return {
        "monthly_distance_m": monthly_distance,
        "accounted_distance_m": accounted,
        "unaccounted_distance_m": unaccounted,
        "reconciliation_fee_cents": reconciliation_fee,
        "accepted_period_fee_cents": accepted_fee,
        "total_month_bill_cents": total_bill,
    }


__all__ = [
    "AMOUNT_BITS",
    "ODOMETER_BITS",
    "PUBLIC_SIGNAL_COUNT_V6",
    "PUBLIC_SIGNAL_ORDER_V6",
    "RATE_BITS",
    "SETTLEMENT_PUBLIC_V6_DOMAIN",
    "UINT16_MAX",
    "UINT32_MAX",
    "UINT48_MAX",
    "UINT64_MAX",
    "UINT96_MAX",
    "build_period_public_statement_v6",
    "compute_fix_commitment_v6",
    "compute_receiver_fix_root_v6",
    "fee_for_interval_values_v6",
    "fee_for_period_v6",
    "reconcile_month_v6",
    "verify_period_submission_v6",
]
