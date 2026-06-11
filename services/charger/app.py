from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from common.settlement import (
    SETTLEMENT_CAP_POLICY_SQ,
    SETTLEMENT_MAX_DT_SEC,
    SETTLEMENT_PERIOD_MAX_SEC,
    ReceiverFix,
    TariffTable,
    compute_public_statement_commitment,
    field_from_text,
    make_device_attestation_commitment,
    month_window_from_period_start,
    verify_monthly_odometer_attestation,
    verify_public_statement_commitment,
    verify_receiver_root_attestation,
    verify_period_submission,
)


app = FastAPI(title="TSIP Settlement Charger")

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

_registry_json = os.getenv("SETTLEMENT_DEVICE_REGISTRY_JSON", "")
if _registry_json:
    for _dev_id, _hex_key in json.loads(_registry_json).items():
        device_registry[str(_dev_id)] = bytes.fromhex(str(_hex_key))

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


def _accept_period(device_id: str, public: dict[str, Any]) -> tuple[str, str]:
    """Dedup, overlap-check, and accumulate an accepted period into the ledger."""

    period_id = str(public["period_id"])
    month_id = str(public["month_id"])
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
    return period_id, month_id


class TariffPayload(BaseModel):
    tariff_version: int
    grid_w: int
    cell_zones: dict[int, int]
    zone_rates_cents_per_m: dict[int, int]


class DeviceRegistration(BaseModel):
    device_id: str
    public_key_hex: str


class PeriodSubmission(BaseModel):
    fixes: list[dict[str, Any]] = Field(min_length=2)
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
    expected_dac = make_device_attestation_commitment(pubkey_bytes)
    return {"ok": True, "device_id": req.device_id, "device_attestation_commitment": expected_dac}


def _tariff_from_payload(payload: TariffPayload) -> TariffTable:
    return TariffTable(
        tariff_version=int(payload.tariff_version),
        grid_w=int(payload.grid_w),
        cell_zones={int(k): int(v) for k, v in payload.cell_zones.items()},
        zone_rates_cents_per_m={int(k): int(v) for k, v in payload.zone_rates_cents_per_m.items()},
    )


@app.post("/settlement/period")
def submit_period(req: PeriodSubmission) -> dict[str, Any]:
    if SETTLEMENT_VKEY_PATH:
        if req.proof is None or req.public_signals is None:
            raise HTTPException(status_code=400, detail="proof and public_signals required when vkey is configured")
        try:
            _verify_zk_proof(req.proof, req.public_signals, SETTLEMENT_VKEY_PATH)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    fixes = [ReceiverFix.from_dict(x) for x in req.fixes]
    if len(fixes) > PERIOD_FIX_CAP:
        raise HTTPException(status_code=400, detail="period exceeds settlement fix cap")

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
        public = verify_period_submission(
            fixes=fixes,
            tariff=tariff,
            public_statement=req.public_statement,
            public_key_bytes=device_pubkey,
            cadence_sec=int(req.public_statement.get("cadence_sec", CADENCE_SEC)),
            tier_vmax_mps=int(req.public_statement.get("tier_vmax_mps", TIER_VMAX_MPS)),
            max_dt_sec=int(req.public_statement.get("max_dt_sec", SETTLEMENT_MAX_DT_SEC)),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # If the prover supplied the raw public-signal vector, bind its time-window
    # signals (indices 15..20) to the statement the charger just verified.
    if req.public_signals is not None:
        try:
            _validate_zk_time_signals(public, req.public_signals)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    period_id, month_id = _accept_period(device_id, public)

    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@app.post("/settlement/period/proof-only")
def submit_period_proof_only(req: ProofOnlyPeriodSubmission) -> dict[str, Any]:
    public = dict(req.public_statement)

    if SETTLEMENT_VKEY_PATH:
        try:
            _verify_zk_proof(req.proof, req.public_signals, SETTLEMENT_VKEY_PATH)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

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
        _validate_public_statement_shape(public)
        _validate_zk_public_signals(public, req.public_signals)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not verify_receiver_root_attestation(
        public_statement=public,
        attestation=req.root_attestation.model_dump(),
        public_key_bytes=device_pubkey,
    ):
        raise HTTPException(status_code=400, detail="root attestation rejected")

    period_id, month_id = _accept_period(device_id, public)

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


@app.post("/settlement/month/attest")
def attest_month_odometer(req: MonthlyOdometerAttestation) -> dict[str, Any]:
    """Record receiver-signed month-boundary odometer readings for reconciliation."""

    if req.device_id not in device_registry:
        raise HTTPException(status_code=400, detail=f"device {req.device_id!r} not registered")
    attestation = req.model_dump()
    if not verify_monthly_odometer_attestation(
        attestation=attestation, public_key_bytes=device_registry[req.device_id]
    ):
        raise HTTPException(status_code=400, detail="monthly odometer attestation rejected")
    key = (req.device_id, req.month_id)
    existing = monthly_odometer_attestations.get(key)
    if existing is not None and (
        int(existing["odometer_start_m"]) != int(req.odometer_start_m)
        or int(existing["odometer_end_m"]) != int(req.odometer_end_m)
    ):
        raise HTTPException(status_code=409, detail="conflicting odometer attestation already recorded")
    monthly_odometer_attestations[key] = attestation
    return {"ok": True, "device_id": req.device_id, "month_id": req.month_id}


@app.get("/settlement/month/{month_id}/reconcile")
def reconcile_month(month_id: str, device_id: str) -> dict[str, Any]:
    """Monthly completeness reconciliation: bill unaccounted kilometres at the fallback rate.

    unaccounted_m = attested odometer delta - sum of accepted period distances.
    Disjoint period time windows and the in-circuit odometer binding make the
    period sum a lower bound on real driving, so unaccounted_m >= 0 for honest
    devices; a negative value indicates inconsistent submissions and is flagged.
    """

    attestation = monthly_odometer_attestations.get((device_id, month_id))
    if attestation is None:
        raise HTTPException(status_code=400, detail="no odometer attestation for this device and month")
    month = monthly_ledger.get((device_id, month_id), {
        "periods": 0, "total_fee_cents": 0, "total_distance_m": 0, "fallback_intervals": 0,
    })
    attested_delta_m = int(attestation["odometer_end_m"]) - int(attestation["odometer_start_m"])
    covered_m = int(month["total_distance_m"])
    unaccounted_m = attested_delta_m - covered_m
    consistent = unaccounted_m >= 0
    unaccounted_fee = max(0, unaccounted_m) * RECONCILIATION_RATE_CENTS_PER_M
    return {
        "ok": consistent,
        "device_id": device_id,
        "month_id": month_id,
        "attested_odometer_delta_m": attested_delta_m,
        "covered_distance_m": covered_m,
        "unaccounted_distance_m": unaccounted_m,
        "reconciliation_rate_cents_per_m": RECONCILIATION_RATE_CENTS_PER_M,
        "unaccounted_fee_cents": unaccounted_fee,
        "period_fee_cents": int(month["total_fee_cents"]),
        "total_month_bill_cents": int(month["total_fee_cents"]) + unaccounted_fee,
        "periods": int(month["periods"]),
        **({} if consistent else {"error": "covered distance exceeds attested odometer delta"}),
    }


@app.get("/settlement/month/{month_id}")
def month_status(month_id: str, device_id: str | None = None) -> dict[str, Any]:
    if device_id is not None:
        month = monthly_ledger.get((device_id, month_id))
        if not month:
            return {"ok": False, "error": "unknown month", "month_id": month_id, "device_id": device_id}
        return {"ok": True, "month_id": month_id, "device_id": device_id, **month}
    # Aggregate across devices (operator view / backwards compatibility).
    totals = {"periods": 0, "total_fee_cents": 0, "total_distance_m": 0, "fallback_intervals": 0}
    found = False
    for (dev, mid), month in monthly_ledger.items():
        if mid == month_id:
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
    device_period_windows.clear()
    monthly_odometer_attestations.clear()
    return {"ok": True}
