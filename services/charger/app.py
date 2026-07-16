from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from common.settlement import (
    SETTLEMENT_CAP_POLICY_SQ,
    SETTLEMENT_MAX_DT_SEC,
    SETTLEMENT_PERIOD_MAX_SEC,
    ReceiverFix,
    TariffTable,
    canonical_month_window,
    compute_public_statement_commitment,
    field_from_text,
    make_device_attestation_commitment,
    month_window_from_period_start,
    verify_monthly_odometer_attestation,
    verify_public_statement_commitment,
    verify_receiver_root_attestation,
    verify_period_submission,
)
from common.policy_profile import (
    PolicyProfile,
    PolicyRegistry,
    load_policy_profiles,
    validate_profile_local_artifacts,
)
from common.settlement_v6 import (
    PUBLIC_SIGNAL_ORDER_V6,
    SETTLEMENT_PUBLIC_V6_DOMAIN,
    reconcile_month_v6,
    verify_period_submission_v6,
)


app = FastAPI(title="TSIP Settlement Charger")

ROOT_DIR = Path(__file__).resolve().parents[2]
POLICY_PROFILE_DIR = Path(
    os.getenv(
        "SETTLEMENT_POLICY_PROFILE_DIR",
        str(ROOT_DIR / "configs" / "settlement_policy_profiles"),
    )
)
policy_registry: PolicyRegistry = load_policy_profiles(POLICY_PROFILE_DIR)

PERIOD_FIX_CAP = int(os.getenv("SETTLEMENT_PERIOD_FIX_CAP", "25"))
PERIOD_MAX_HOURS = int(os.getenv("SETTLEMENT_PERIOD_MAX_HOURS", "2"))
CADENCE_SEC = int(os.getenv("SETTLEMENT_CADENCE_SEC", "300"))
TIER_VMAX_MPS = int(os.getenv("SETTLEMENT_TIER_VMAX_MPS", "33"))
# Path to the snarkjs verification key for the settlement period circuit.
# When set, every submission must include a valid Groth16 proof.
SETTLEMENT_VKEY_PATH = os.getenv("SETTLEMENT_VKEY_PATH", "")

# Device enrollment registry: device_id → raw 32-byte Ed25519 public key.
# Pre-loaded from SETTLEMENT_DEVICE_REGISTRY_JSON (JSON: {"device_id": "hex_pubkey"}).
# Devices can also be registered at runtime via POST /settlement/devices/register.
device_registry: dict[str, bytes] = {}
device_jurisdiction_registry: dict[str, str] = {}

_registry_json = os.getenv("SETTLEMENT_DEVICE_REGISTRY_JSON", "")
if _registry_json:
    for _dev_id, _hex_key in json.loads(_registry_json).items():
        device_registry[str(_dev_id)] = bytes.fromhex(str(_hex_key))
        device_jurisdiction_registry[str(_dev_id)] = "ruc-demo"

# Reconciliation rate for kilometres not covered by any accepted period.
# Must satisfy rate >= alpha * max_zone_rate with alpha >= 1 so that whole-period
# withholding is never cheaper than exact settlement (monthly extension of the
# E2 monotone-degradation rule).
RECONCILIATION_RATE_CENTS_PER_M = int(os.getenv("SETTLEMENT_RECONCILIATION_RATE_CENTS_PER_M", "5"))

# Keyed by (device_id, period_id) / (device_id, month_id): a device must not be
# able to block another device's submissions by colliding on a bare period_id,
# and bills are per-device.
accepted_periods: dict[tuple[str, str], dict[str, Any]] = {}
monthly_ledger: dict[tuple[str, str], dict[str, int]] = {}
# Accepted [period_start_time, period_end_time) windows per device. Overlapping
# windows would double-count odometer distance and eat into the reconciliation
# margin, so they are rejected at submission time.
device_period_windows: dict[str, list[tuple[int, int]]] = {}
# (device_id, month_id) -> verified month-boundary odometer attestation.
monthly_odometer_attestations: dict[tuple[str, str], dict[str, Any]] = {}
# Canonical month-close rate inherited from accepted period profiles.  If a
# profile rolls over inside a month, the maximum canonical rate is retained so
# completeness reconciliation cannot become cheaper through profile timing.
monthly_reconciliation_rates: dict[tuple[str, str], int] = {}
# Immutable month-close receipts and durable administrative exceptions.  Keys
# normalize month spelling (YYYY-MM vs YYYYMM) to the same integer identity.
closed_months: dict[tuple[str, int], dict[str, Any]] = {}
administrative_months: dict[tuple[str, int], dict[str, Any]] = {}


def _month_number(month_id: str) -> int:
    return int(canonical_month_window(month_id)["month_id"])


def _prev_month_number(month_number: int) -> int:
    year, month = divmod(int(month_number), 100)
    if month == 1:
        return (year - 1) * 100 + 12
    return year * 100 + (month - 1)


def _next_month_number(month_number: int) -> int:
    year, month = divmod(int(month_number), 100)
    if month == 12:
        return (year + 1) * 100 + 1
    return year * 100 + (month + 1)


def _find_month_attestation(device_id: str, month_id: str) -> tuple[tuple[str, str], dict[str, Any]] | None:
    target_month = _month_number(month_id)
    for key, attestation in monthly_odometer_attestations.items():
        dev_id, existing_month_id = key
        if dev_id == device_id and _month_number(existing_month_id) == target_month:
            return key, attestation
    return None


def _month_ledger_for_device(device_id: str, month_id: str) -> dict[str, int]:
    target_month = _month_number(month_id)
    totals = {"periods": 0, "total_fee_cents": 0, "total_distance_m": 0, "fallback_intervals": 0}
    for (dev_id, existing_month_id), month in monthly_ledger.items():
        if dev_id == device_id and _month_number(existing_month_id) == target_month:
            for key in totals:
                totals[key] += int(month[key])
    return totals


def _month_reconciliation_rate(device_id: str, month_id: str) -> int:
    target_month = _month_number(month_id)
    rates = [
        int(rate)
        for (dev_id, existing_month_id), rate in monthly_reconciliation_rates.items()
        if dev_id == device_id and _month_number(existing_month_id) == target_month
    ]
    if rates:
        return max(rates)
    jurisdiction_id = device_jurisdiction_registry.get(device_id)
    if jurisdiction_id is None:
        raise ValueError(f"device {device_id!r} has no canonical jurisdiction binding")
    month_start = canonical_month_window(month_id)["month_start_time"]
    profile = policy_registry.resolve(
        jurisdiction_id=jurisdiction_id,
        period_start_time=int(month_start),
    )
    return int(profile.monthly_reconciliation_rate_cents_per_m)


def _enforce_odometer_month_chain(
    *,
    device_id: str,
    month_id: str,
    odometer_start_m: int,
    odometer_end_m: int,
) -> None:
    month_number = _month_number(month_id)
    prev_month = _prev_month_number(month_number)
    next_month = _next_month_number(month_number)
    for (dev_id, existing_month_id), existing in monthly_odometer_attestations.items():
        if dev_id != device_id:
            continue
        existing_month = _month_number(existing_month_id)
        if existing_month == month_number:
            continue
        if existing_month == prev_month and int(existing["odometer_end_m"]) != int(odometer_start_m):
            raise HTTPException(
                status_code=409,
                detail="odometer month chain mismatch with previous month",
            )
        if existing_month == next_month and int(existing["odometer_start_m"]) != int(odometer_end_m):
            raise HTTPException(
                status_code=409,
                detail="odometer month chain mismatch with next month",
            )


def _profile_vkey_path(profile: PolicyProfile) -> Path:
    """Resolve and re-hash the pinned key on every proof acceptance path."""

    validate_profile_local_artifacts(profile, base_dir=POLICY_PROFILE_DIR)
    path = Path(profile.verification_key_path)
    return path if path.is_absolute() else POLICY_PROFILE_DIR / path


def _resolve_expected_profile(device_id: str, public: dict[str, Any]) -> PolicyProfile:
    jurisdiction_id = device_jurisdiction_registry.get(str(device_id))
    if jurisdiction_id is None:
        raise ValueError(f"device {device_id!r} has no canonical jurisdiction binding")
    try:
        period_start = int(public["period_start_time"])
        period_end = int(public["period_end_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("period time fields missing or malformed") from exc
    profile = policy_registry.resolve(
        jurisdiction_id=jurisdiction_id,
        period_start_time=period_start,
    )
    if period_end <= period_start or period_end > int(profile.valid_to):
        raise ValueError("billing period is not wholly covered by the canonical profile")
    profile.assert_statement_matches(public)
    # Key presence/hash is part of profile validity even for the transparent
    # reference endpoint.  The proof-only endpoint additionally invokes Groth16.
    _profile_vkey_path(profile)
    return profile


def _verify_zk_proof(proof: dict[str, Any], public_signals: list[str], vkey_path: str) -> None:
    with tempfile.TemporaryDirectory(prefix="charger-zk-") as td:
        tdp = Path(td)
        (tdp / "proof.json").write_text(json.dumps(proof), encoding="utf-8")
        (tdp / "public.json").write_text(json.dumps(public_signals), encoding="utf-8")
        proc = subprocess.run(
            ["snarkjs", "groth16", "verify", vkey_path, str(tdp / "public.json"), str(tdp / "proof.json")],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or "OK!" not in proc.stdout:
            raise ValueError(f"Groth16 proof rejected: {proc.stdout.strip()}")


# Public-signal layout for the settlement period circuit (21 signals). Indices
# 15..20 carry the proof's time-window binding; the charger pins them to the
# accepted public statement so a prover cannot present a valid proof for one
# period while settling against a different (cheaper) time window.
_TIME_SIGNAL_LAYOUT: list[tuple[int, str]] = [
    (16, "period_start_time"),
    (17, "period_end_time"),
    (18, "month_id_field"),
    (19, "month_start_time"),
    (20, "month_end_time"),
]

_PUBLIC_SIGNAL_LAYOUT: list[tuple[int, str]] = [
    (0, "receiver_fix_root"),
    (1, "tariff_root"),
    (2, "interval_commitment_root"),
    (3, "period_id_field"),
    (4, "tariff_version"),
    (5, "device_attestation_commitment_field"),
    (6, "total_fee_cents"),
    (7, "total_distance_m"),
    (8, "fallback_intervals"),
    (9, "cadence_sec"),
    (10, "tier_vmax_mps"),
    (11, "tier_vmax_sq"),
    (12, "mode_vmax_sq"),
    (13, "cap_policy_sq"),
    (14, "max_zone_rate_cents_per_m"),
    (15, "max_dt_sec"),
    (16, "period_start_time"),
    (17, "period_end_time"),
    (18, "month_id_field"),
    (19, "month_start_time"),
    (20, "month_end_time"),
]


def _validate_zk_time_signals(public: dict[str, Any], signals: list[str]) -> None:
    """Bind the proof's time-window public signals to the accepted statement.

    ``signals`` is the snarkjs public-signal vector. Index 15 is ``max_dt_sec``
    and indices 16..20 are the period/month time window. Each must equal the
    corresponding field of the verified public statement; any mismatch means the
    proof does not attest to the period the charger is about to settle.
    """
    if len(signals) < 21:
        raise ValueError(
            f"time-window public signals: expected at least 21 signals, got {len(signals)}"
        )

    def _as_int(value: Any, name: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"time-window public signals: {name} is not an integer") from exc

    expected_max_dt = int(public.get("max_dt_sec", SETTLEMENT_MAX_DT_SEC))
    if _as_int(signals[15], "max_dt_sec") != expected_max_dt:
        raise ValueError(
            "time-window public signals: max_dt_sec mismatch "
            f"(signal={signals[15]}, statement={expected_max_dt})"
        )
    for idx, key in _TIME_SIGNAL_LAYOUT:
        expected = _as_int(public[key], key)
        got = _as_int(signals[idx], key)
        if got != expected:
            raise ValueError(
                f"time-window public signals: {key} mismatch (signal={got}, statement={expected})"
            )


def _expected_public_signal_values(public: dict[str, Any]) -> list[int]:
    tier_vmax_mps = int(public.get("tier_vmax_mps", TIER_VMAX_MPS))
    tier_vmax_sq = int(public.get("tier_vmax_sq", tier_vmax_mps * tier_vmax_mps))
    mode_vmax_sq = int(public.get("mode_vmax_sq", tier_vmax_sq))
    cap_policy_sq = int(public.get("cap_policy_sq", SETTLEMENT_CAP_POLICY_SQ))
    return [
        int(public["receiver_fix_root"]),
        int(public["tariff_root"]),
        int(public["interval_commitment_root"]),
        int(public.get("period_id_field", field_from_text(str(public["period_id"])))),
        int(public["tariff_version"]),
        int(field_from_text(str(public["device_attestation_commitment"]))),
        int(public["total_fee_cents"]),
        int(public["total_distance_m"]),
        int(public["fallback_intervals"]),
        int(public.get("cadence_sec", CADENCE_SEC)),
        tier_vmax_mps,
        tier_vmax_sq,
        mode_vmax_sq,
        cap_policy_sq,
        int(public["max_zone_rate_cents_per_m"]),
        int(public.get("max_dt_sec", SETTLEMENT_MAX_DT_SEC)),
        int(public["period_start_time"]),
        int(public["period_end_time"]),
        int(public["month_id_field"]),
        int(public["month_start_time"]),
        int(public["month_end_time"]),
    ]


def _validate_zk_public_signals(public: dict[str, Any], signals: list[str]) -> None:
    if len(signals) < len(_PUBLIC_SIGNAL_LAYOUT):
        raise ValueError(
            f"proof public signals: expected at least {len(_PUBLIC_SIGNAL_LAYOUT)} signals, got {len(signals)}"
        )
    expected = _expected_public_signal_values(public)
    for idx, name in _PUBLIC_SIGNAL_LAYOUT:
        try:
            got = int(signals[idx])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"proof public signals: {name} is not an integer") from exc
        if got != expected[idx]:
            raise ValueError(f"proof public signals: {name} mismatch (signal={got}, statement={expected[idx]})")


def _expected_public_signal_values_v6(public: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for name in PUBLIC_SIGNAL_ORDER_V6:
        if name == "device_attestation_commitment":
            values.append(field_from_text(str(public["device_attestation_commitment"])))
        elif name == "month_id":
            values.append(int(public["month_id_field"]))
        else:
            values.append(int(public[name]))
    return values


def _validate_zk_public_signals_v6(public: dict[str, Any], signals: list[str]) -> None:
    if len(signals) != len(PUBLIC_SIGNAL_ORDER_V6):
        raise ValueError(
            "V6 proof public signals: expected exactly "
            f"{len(PUBLIC_SIGNAL_ORDER_V6)} signals, got {len(signals)}"
        )
    expected = _expected_public_signal_values_v6(public)
    for index, name in enumerate(PUBLIC_SIGNAL_ORDER_V6):
        try:
            got = int(signals[index])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"V6 proof public signals: {name} is not an integer") from exc
        if got != expected[index]:
            raise ValueError(
                f"V6 proof public signals: {name} mismatch "
                f"(signal={got}, statement={expected[index]})"
            )


def _validate_public_statement_shape(public: dict[str, Any]) -> None:
    if not verify_public_statement_commitment(public):
        raise ValueError(
            "public statement commitment mismatch "
            f"(expected={compute_public_statement_commitment(public)})"
        )
    period_start = int(public["period_start_time"])
    period_end = int(public["period_end_time"])
    period_span = period_end - period_start
    if not 0 < period_span <= SETTLEMENT_PERIOD_MAX_SEC:
        raise ValueError("period span must be positive and at most 14400 seconds")

    canon_month_id, canon_month_start, canon_month_end = month_window_from_period_start(period_start)
    if (
        int(public["month_id_field"]) != canon_month_id
        or int(public["month_start_time"]) != canon_month_start
        or int(public["month_end_time"]) != canon_month_end
    ):
        raise ValueError("month window does not match month_id for the period start")
    if period_start < canon_month_start or period_end > canon_month_end:
        raise ValueError("settlement period must be wholly contained in one canonical month")


def _accept_period(
    device_id: str,
    public: dict[str, Any],
    profile: PolicyProfile,
) -> tuple[str, str]:
    """Dedup, overlap-check, and accumulate an accepted period into the ledger."""

    period_id = str(public["period_id"])
    month_id = str(public["month_id"])
    normalized_month = _month_number(month_id)
    month_state_key = (device_id, normalized_month)
    if month_state_key in closed_months or month_state_key in administrative_months:
        raise HTTPException(status_code=409, detail="billing month no longer accepts period submissions")
    if "total_distance_m" not in public:
        raise HTTPException(status_code=400, detail="total_distance_m is required for monthly reconciliation")
    max_zone_rate = int(public.get("max_zone_rate_cents_per_m", 0))
    reconciliation_rate = int(profile.monthly_reconciliation_rate_cents_per_m)
    if max_zone_rate != int(profile.max_zone_rate_cents_per_m):
        raise HTTPException(status_code=400, detail="accepted tariff max is not canonical")
    if reconciliation_rate != max_zone_rate:
        raise HTTPException(status_code=500, detail="canonical reconciliation arithmetic is inconsistent")
    if (device_id, period_id) in accepted_periods:
        raise HTTPException(status_code=409, detail="period already accepted")

    start = int(public["period_start_time"])
    end = int(public["period_end_time"])
    for prev_start, prev_end in device_period_windows.get(device_id, []):
        if start < prev_end and prev_start < end:
            raise HTTPException(
                status_code=409,
                detail="period time window overlaps an accepted period for this device",
            )

    accepted_periods[(device_id, period_id)] = public
    device_period_windows.setdefault(device_id, []).append((start, end))
    month = monthly_ledger.setdefault(
        (device_id, month_id),
        {"periods": 0, "total_fee_cents": 0, "total_distance_m": 0, "fallback_intervals": 0},
    )
    month["periods"] += 1
    month["total_fee_cents"] += int(public["total_fee_cents"])
    month["fallback_intervals"] += int(public.get("fallback_intervals", 0))
    if "total_distance_m" in public:
        month["total_distance_m"] += int(public["total_distance_m"])
    rate_key = (device_id, month_id)
    monthly_reconciliation_rates[rate_key] = max(
        reconciliation_rate,
        int(monthly_reconciliation_rates.get(rate_key, 0)),
    )
    return period_id, month_id


class TariffPayload(BaseModel):
    tariff_version: int
    grid_w: int
    cell_zones: dict[int, int]
    zone_rates_cents_per_m: dict[int, int]


class DeviceRegistration(BaseModel):
    device_id: str
    public_key_hex: str
    jurisdiction_id: str = "ruc-demo"


class PeriodSubmission(BaseModel):
    fixes: list[dict[str, Any]] = Field(min_length=2)
    tariff: TariffPayload
    public_statement: dict[str, Any]
    proof: dict[str, Any] | None = None
    public_signals: list[str] | None = None


class V6PeriodSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixes: list[dict[str, Any]] = Field(min_length=2)
    position_valid: list[StrictBool] = Field(min_length=1)
    tariff: TariffPayload
    public_statement: dict[str, Any]
    proof: dict[str, Any] | None = None
    public_signals: list[str] | None = None


class RootAttestation(BaseModel):
    device_id: str
    signature: str


class ProofOnlyPeriodSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_statement: dict[str, Any]
    proof: dict[str, Any]
    public_signals: list[str]
    root_attestation: RootAttestation


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "charger",
        "accepted_periods": len(accepted_periods),
        "months": len(monthly_ledger),
        "core": "settlement",
        "period_fix_cap": PERIOD_FIX_CAP,
        "period_max_hours": PERIOD_MAX_HOURS,
        "cadence_sec": CADENCE_SEC,
        "registered_devices": len(device_registry),
        "canonical_policy_profiles": len(policy_registry.profiles),
    }


@app.post("/settlement/devices/register")
def register_device(req: DeviceRegistration) -> dict[str, Any]:
    """Register a device's Ed25519 public key. Not authenticated — intended for
    operator provisioning and artifact-evaluation use only."""
    try:
        pubkey_bytes = bytes.fromhex(req.public_key_hex)
        if len(pubkey_bytes) != 32:
            raise ValueError("public key must be 32 bytes (raw Ed25519)")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    device_registry[req.device_id] = pubkey_bytes
    device_jurisdiction_registry[req.device_id] = str(req.jurisdiction_id)
    expected_dac = make_device_attestation_commitment(pubkey_bytes)
    return {
        "ok": True,
        "device_id": req.device_id,
        "jurisdiction_id": req.jurisdiction_id,
        "device_attestation_commitment": expected_dac,
    }


def _tariff_from_payload(payload: TariffPayload) -> TariffTable:
    return TariffTable(
        tariff_version=int(payload.tariff_version),
        grid_w=int(payload.grid_w),
        cell_zones={int(k): int(v) for k, v in payload.cell_zones.items()},
        zone_rates_cents_per_m={int(k): int(v) for k, v in payload.zone_rates_cents_per_m.items()},
    )


def _is_v6_settlement_circuit(circuit_id: str) -> bool:
    return str(circuit_id).startswith(
        ("settlement-period-v6-", "settlement_period_v6_")
    )


@app.post("/settlement/period")
def submit_period(req: PeriodSubmission) -> dict[str, Any]:
    fixes = [ReceiverFix.from_dict(x) for x in req.fixes]

    # Resolve the device's public key from the enrollment registry.
    device_id = str(fixes[0].device_id)
    if device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = device_registry[device_id]

    # Cross-check: the device_attestation_commitment in the public statement must
    # equal the commitment derived from the registered public key.  An adversary
    # who does not possess the device's private key cannot produce fixes that
    # verify against the registered public key, so the commitment is non-forgeable.
    expected_dac = make_device_attestation_commitment(device_pubkey)
    submitted_dac = str(req.public_statement.get("device_attestation_commitment", ""))
    if submitted_dac != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )

    try:
        profile = _resolve_expected_profile(device_id, req.public_statement)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if len(fixes) > min(PERIOD_FIX_CAP, int(profile.max_fixes)):
        raise HTTPException(status_code=400, detail="period exceeds canonical settlement fix cap")

    # Submission gate: the charger pins the canonical calendar. The month window
    # carried in the public statement must match the canonical window for the
    # month containing the period's start, so a prover cannot settle a period
    # against an attacker-chosen (e.g. cheaper or out-of-range) month.
    period_start = int(fixes[0].auth_gnss_time)
    canon_month_id, canon_month_start, canon_month_end = month_window_from_period_start(period_start)
    ps = req.public_statement
    try:
        ps_month_id = int(ps.get("month_id_field"))
        ps_month_start = int(ps.get("month_start_time"))
        ps_month_end = int(ps.get("month_end_time"))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail="month window fields missing or malformed") from e
    if (
        ps_month_id != canon_month_id
        or ps_month_start != canon_month_start
        or ps_month_end != canon_month_end
    ):
        raise HTTPException(
            status_code=400,
            detail="month window does not match month_id for the period start",
        )

    tariff = _tariff_from_payload(req.tariff)
    try:
        profile.assert_tariff_matches(tariff)
        public = verify_period_submission(
            fixes=fixes,
            tariff=tariff,
            public_statement=req.public_statement,
            public_key_bytes=device_pubkey,
            cadence_sec=int(profile.cadence_sec),
            tier_vmax_mps=int(profile.tier_vmax_mps),
            max_dt_sec=int(profile.max_dt_sec),
            tariff_tree_depth=int(profile.tariff_tree_depth),
            policy_profile=profile,
        )
        _validate_public_statement_shape(public)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if (req.proof is None) != (req.public_signals is None):
        raise HTTPException(status_code=400, detail="proof and public_signals must be supplied together")
    # The transparent endpoint recomputes the whole relation from authenticated
    # fixes.  If a proof is additionally supplied, it is verified only with the
    # profile-pinned key and all public signals are compared.
    if req.proof is not None and req.public_signals is not None:
        try:
            _verify_zk_proof(req.proof, req.public_signals, str(_profile_vkey_path(profile)))
            _validate_zk_public_signals(public, req.public_signals)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    period_id, month_id = _accept_period(device_id, public, profile)

    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@app.post("/settlement/v6/period")
def submit_period_v6(req: V6PeriodSubmission) -> dict[str, Any]:
    """Recompute and accept the odometer-backed V6 relation.

    The availability bits are private witness material in proof-only mode.  The
    transparent evaluation endpoint receives them solely so it can recompute
    the same interval commitment root and bill as the circuit.
    """

    fixes = [ReceiverFix.from_dict(item) for item in req.fixes]
    device_id = str(fixes[0].device_id)
    if any(str(fix.device_id) != device_id for fix in fixes):
        raise HTTPException(status_code=400, detail="all fixes must belong to the enrolled device")
    if device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = device_registry[device_id]
    expected_dac = make_device_attestation_commitment(device_pubkey)
    if str(req.public_statement.get("device_attestation_commitment", "")) != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )

    try:
        profile = _resolve_expected_profile(device_id, req.public_statement)
        if str(req.public_statement.get("domain_sep")) != SETTLEMENT_PUBLIC_V6_DOMAIN:
            raise ValueError("V6 endpoint requires a V6 public statement")
        if str(profile.fallback_semantics_version) != "odometer-max-rate-v6":
            raise ValueError("canonical profile does not authorize V6 odometer fallback")
        if not _is_v6_settlement_circuit(profile.circuit_id):
            raise ValueError("canonical profile does not pin a V6 settlement circuit")
        if len(fixes) > min(PERIOD_FIX_CAP, int(profile.max_fixes)):
            raise ValueError("period exceeds canonical settlement fix cap")
        tariff = _tariff_from_payload(req.tariff)
        profile.assert_tariff_matches(tariff)
        public = verify_period_submission_v6(
            fixes=fixes,
            tariff=tariff,
            position_valid=list(req.position_valid),
            public_statement=req.public_statement,
            public_key_bytes=device_pubkey,
            cadence_sec=int(profile.cadence_sec),
            tier_vmax_mps=int(profile.tier_vmax_mps),
            max_dt_sec=int(profile.max_dt_sec),
            r_max_cents_per_m=int(profile.max_zone_rate_cents_per_m),
            tariff_tree_depth=int(profile.tariff_tree_depth),
            mode_vmax_sq=int(profile.mode_vmax_sq),
            cap_policy_sq=int(profile.cap_policy_sq),
            policy_profile=profile,
        )
        _validate_public_statement_shape(public)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if (req.proof is None) != (req.public_signals is None):
        raise HTTPException(status_code=400, detail="proof and public_signals must be supplied together")
    if req.proof is not None and req.public_signals is not None:
        try:
            _validate_zk_public_signals_v6(public, req.public_signals)
            _verify_zk_proof(req.proof, req.public_signals, str(_profile_vkey_path(profile)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    period_id, month_id = _accept_period(device_id, public, profile)
    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@app.post("/settlement/period/proof-only")
def submit_period_proof_only(req: ProofOnlyPeriodSubmission) -> dict[str, Any]:
    public = dict(req.public_statement)

    device_id = str(req.root_attestation.device_id)
    if device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = device_registry[device_id]

    expected_dac = make_device_attestation_commitment(device_pubkey)
    submitted_dac = str(public.get("device_attestation_commitment", ""))
    if submitted_dac != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )

    try:
        profile = _resolve_expected_profile(device_id, public)
        _validate_public_statement_shape(public)
        _validate_zk_public_signals(public, req.public_signals)
        _verify_zk_proof(req.proof, req.public_signals, str(_profile_vkey_path(profile)))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not verify_receiver_root_attestation(
        public_statement=public,
        attestation=req.root_attestation.model_dump(),
        public_key_bytes=device_pubkey,
    ):
        raise HTTPException(status_code=400, detail="root attestation rejected")

    period_id, month_id = _accept_period(device_id, public, profile)

    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@app.post("/settlement/v6/period/proof-only")
def submit_period_proof_only_v6(req: ProofOnlyPeriodSubmission) -> dict[str, Any]:
    """Accept only a profile-pinned V6 proof and receiver root attestation."""

    public = dict(req.public_statement)
    device_id = str(req.root_attestation.device_id)
    if device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = device_registry[device_id]
    expected_dac = make_device_attestation_commitment(device_pubkey)
    if str(public.get("device_attestation_commitment", "")) != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )
    try:
        profile = _resolve_expected_profile(device_id, public)
        if str(public.get("domain_sep")) != SETTLEMENT_PUBLIC_V6_DOMAIN:
            raise ValueError("V6 endpoint requires a V6 public statement")
        if str(profile.fallback_semantics_version) != "odometer-max-rate-v6":
            raise ValueError("canonical profile does not authorize V6 odometer fallback")
        if not _is_v6_settlement_circuit(profile.circuit_id):
            raise ValueError("canonical profile does not pin a V6 settlement circuit")
        _validate_public_statement_shape(public)
        _validate_zk_public_signals_v6(public, req.public_signals)
        _verify_zk_proof(req.proof, req.public_signals, str(_profile_vkey_path(profile)))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not verify_receiver_root_attestation(
        public_statement=public,
        attestation=req.root_attestation.model_dump(),
        public_key_bytes=device_pubkey,
    ):
        raise HTTPException(status_code=400, detail="root attestation rejected")

    period_id, month_id = _accept_period(device_id, public, profile)
    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


class MonthlyOdometerAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    month_id: str
    odometer_start_m: int
    odometer_end_m: int
    signature: str


class MonthCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    month_id: str


@app.post("/settlement/month/attest")
def attest_month_odometer(req: MonthlyOdometerAttestation) -> dict[str, Any]:
    """Record receiver-signed month-boundary odometer readings for reconciliation."""

    if req.device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {req.device_id!r} not registered")
    if int(req.odometer_end_m) < int(req.odometer_start_m):
        raise HTTPException(status_code=400, detail="monthly odometer readings must be monotonic")
    try:
        _month_number(req.month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    attestation = req.model_dump()
    if not verify_monthly_odometer_attestation(
        attestation=attestation, public_key_bytes=device_registry[req.device_id]
    ):
        raise HTTPException(status_code=400, detail="monthly odometer attestation rejected")
    existing_match = _find_month_attestation(req.device_id, req.month_id)
    existing = existing_match[1] if existing_match is not None else None
    if existing is not None and (
        int(existing["odometer_start_m"]) != int(req.odometer_start_m)
        or int(existing["odometer_end_m"]) != int(req.odometer_end_m)
    ):
        raise HTTPException(status_code=409, detail="conflicting odometer attestation already recorded")
    if existing is None:
        _enforce_odometer_month_chain(
            device_id=req.device_id,
            month_id=req.month_id,
            odometer_start_m=req.odometer_start_m,
            odometer_end_m=req.odometer_end_m,
        )
        monthly_odometer_attestations[(req.device_id, req.month_id)] = attestation
    return {"ok": True, "device_id": req.device_id, "month_id": req.month_id}


@app.post("/settlement/v6/month/close")
def close_month_v6(req: MonthCloseRequest) -> dict[str, Any]:
    """Finalize a device-month exactly once or enter a durable admin path."""

    if req.device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {req.device_id!r} not registered")
    try:
        month_number = _month_number(req.month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state_key = (req.device_id, month_number)
    if state_key in closed_months:
        return {**closed_months[state_key], "idempotent": True}

    attestation_match = _find_month_attestation(req.device_id, req.month_id)
    month = _month_ledger_for_device(req.device_id, req.month_id)
    if attestation_match is None:
        receipt = {
            "ok": False,
            "status": "administrative-exception",
            "device_id": req.device_id,
            "month_id": req.month_id,
            "month_id_field": month_number,
            "reason": "missing_monthly_odometer_attestation",
            "periods": int(month["periods"]),
            "accounted_distance_m": int(month["total_distance_m"]),
            "accepted_period_fee_cents": int(month["total_fee_cents"]),
            "immutable": True,
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        administrative_months.setdefault(state_key, receipt)
        return administrative_months[state_key]

    attestation = attestation_match[1]
    try:
        reconciliation_rate = _month_reconciliation_rate(req.device_id, req.month_id)
        result = reconcile_month_v6(
            monthly_odometer_start_m=int(attestation["odometer_start_m"]),
            monthly_odometer_end_m=int(attestation["odometer_end_m"]),
            accounted_distance_m=int(month["total_distance_m"]),
            accepted_period_fee_cents=int(month["total_fee_cents"]),
            r_max_cents_per_m=reconciliation_rate,
            tolerance_m=0,
        )
    except (TypeError, ValueError, OverflowError) as e:
        receipt = {
            "ok": False,
            "status": "administrative-exception",
            "device_id": req.device_id,
            "month_id": req.month_id,
            "month_id_field": month_number,
            "reason": "inconsistent_monthly_odometer_accounting",
            "detail": str(e),
            "immutable": True,
        }
        receipt["receipt_sha256"] = hashlib.sha256(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        administrative_months[state_key] = receipt
        return receipt

    profile_commitments = sorted(
        {
            str(public.get("policy_profile_commitment", ""))
            for (device_id, _period_id), public in accepted_periods.items()
            if device_id == req.device_id and _month_number(str(public["month_id"])) == month_number
        }
    )
    receipt = {
        "ok": True,
        "status": "closed",
        "device_id": req.device_id,
        "month_id": req.month_id,
        "month_id_field": month_number,
        "reconciliation_rate_cents_per_m": reconciliation_rate,
        "profile_commitments": profile_commitments,
        "periods": int(month["periods"]),
        **result,
        "immutable": True,
        "idempotent": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    closed_months[state_key] = receipt
    administrative_months.pop(state_key, None)
    return receipt


@app.get("/settlement/month/{month_id}/reconcile")
def reconcile_month(month_id: str, device_id: str) -> dict[str, Any]:
    """Monthly completeness reconciliation: bill unaccounted kilometres at the fallback rate.

    unaccounted_m = attested odometer delta - sum of accepted period distances.
    Disjoint period time windows and the in-circuit odometer binding make the
    period sum a lower bound on real driving, so unaccounted_m >= 0 for honest
    devices; a negative value indicates inconsistent submissions and is flagged.
    """

    try:
        _month_number(month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    attestation_match = _find_month_attestation(device_id, month_id)
    if attestation_match is None:
        raise HTTPException(status_code=400, detail="no odometer attestation for this device and month")
    attestation = attestation_match[1]
    month = _month_ledger_for_device(device_id, month_id)
    attested_delta_m = int(attestation["odometer_end_m"]) - int(attestation["odometer_start_m"])
    covered_m = int(month["total_distance_m"])
    unaccounted_m = attested_delta_m - covered_m
    consistent = unaccounted_m >= 0
    try:
        reconciliation_rate = _month_reconciliation_rate(device_id, month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    unaccounted_fee = max(0, unaccounted_m) * reconciliation_rate
    return {
        "ok": consistent,
        "device_id": device_id,
        "month_id": month_id,
        "attested_odometer_delta_m": attested_delta_m,
        "covered_distance_m": covered_m,
        "unaccounted_distance_m": unaccounted_m,
        "reconciliation_rate_cents_per_m": reconciliation_rate,
        "unaccounted_fee_cents": unaccounted_fee,
        "period_fee_cents": int(month["total_fee_cents"]),
        "total_month_bill_cents": int(month["total_fee_cents"]) + unaccounted_fee,
        "periods": int(month["periods"]),
        **({} if consistent else {"error": "covered distance exceeds attested odometer delta"}),
    }


@app.get("/settlement/month/{month_id}/missing-attestations")
def missing_month_attestations(month_id: str) -> dict[str, Any]:
    """Operator view: enrolled devices that still need month-boundary attestation.

    This is the protocol-level handle for the base case of no-free-kilometre
    reconciliation: not submitting the monthly odometer attestation does not
    make a device disappear, it moves the device-month to the administrative
    penalty path.
    """

    try:
        _month_number(month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    missing: list[dict[str, Any]] = []
    for device_id in sorted(device_registry):
        if _find_month_attestation(device_id, month_id) is not None:
            continue
        month = _month_ledger_for_device(device_id, month_id)
        missing.append(
            {
                "device_id": device_id,
                "month_id": month_id,
                "periods": int(month["periods"]),
                "covered_distance_m": int(month["total_distance_m"]),
                "period_fee_cents": int(month["total_fee_cents"]),
                "reason": "missing_monthly_odometer_attestation",
                "administrative_path": True,
            }
        )
    return {"ok": True, "month_id": month_id, "missing_count": len(missing), "missing": missing}


@app.get("/settlement/month/{month_id}")
def month_status(month_id: str, device_id: str | None = None) -> dict[str, Any]:
    try:
        _month_number(month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if device_id is not None:
        month = _month_ledger_for_device(device_id, month_id)
        if not any(int(month[key]) for key in month):
            return {"ok": False, "error": "unknown month", "month_id": month_id, "device_id": device_id}
        return {"ok": True, "month_id": month_id, "device_id": device_id, **month}
    # Aggregate across devices (operator view / backwards compatibility).
    totals = {"periods": 0, "total_fee_cents": 0, "total_distance_m": 0, "fallback_intervals": 0}
    found = False
    for (dev, mid), month in monthly_ledger.items():
        if _month_number(mid) == _month_number(month_id):
            found = True
            for k in totals:
                totals[k] += int(month[k])
    if not found:
        return {"ok": False, "error": "unknown month", "month_id": month_id}
    return {"ok": True, "month_id": month_id, **totals}


@app.post("/settlement/reset")
def reset() -> dict[str, Any]:
    accepted_periods.clear()
    monthly_ledger.clear()
    device_registry.clear()
    device_jurisdiction_registry.clear()
    device_period_windows.clear()
    monthly_odometer_attestations.clear()
    monthly_reconciliation_rates.clear()
    closed_months.clear()
    administrative_months.clear()
    return {"ok": True}
