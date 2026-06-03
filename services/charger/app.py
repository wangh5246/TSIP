from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from common.settlement import (
    SETTLEMENT_MAX_DT_SEC,
    ReceiverFix,
    TariffTable,
    make_device_attestation_commitment,
    month_window_from_period_start,
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

accepted_periods: dict[str, dict[str, Any]] = {}
monthly_ledger: dict[str, dict[str, int]] = {}


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
            cadence_sec=CADENCE_SEC,
            tier_vmax_mps=TIER_VMAX_MPS,
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

    period_id = str(public["period_id"])
    month_id = str(public["month_id"])
    if period_id in accepted_periods:
        raise HTTPException(status_code=409, detail="period already accepted")
    accepted_periods[period_id] = public

    month = monthly_ledger.setdefault(
        month_id,
        {"periods": 0, "total_fee_cents": 0, "total_distance_m": 0, "fallback_intervals": 0},
    )
    month["periods"] += 1
    month["total_fee_cents"] += int(public["total_fee_cents"])
    month["fallback_intervals"] += int(public.get("fallback_intervals", 0))
    if "total_distance_m" in public:
        month["total_distance_m"] += int(public["total_distance_m"])

    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@app.get("/settlement/month/{month_id}")
def month_status(month_id: str) -> dict[str, Any]:
    month = monthly_ledger.get(month_id)
    if not month:
        return {"ok": False, "error": "unknown month", "month_id": month_id}
    return {"ok": True, "month_id": month_id, **month}


@app.post("/settlement/reset")
def reset() -> dict[str, Any]:
    accepted_periods.clear()
    monthly_ledger.clear()
    device_registry.clear()
    return {"ok": True}
