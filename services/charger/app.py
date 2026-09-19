from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.exc import SQLAlchemyError

from common.settlement import (
    SETTLEMENT_CAP_POLICY_SQ,
    SETTLEMENT_MAX_DT_SEC,
    SETTLEMENT_PERIOD_MAX_SEC,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    ReceiverFix,
    TariffTable,
    canonical_json,
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
from common.http_security import StrictJSONBodyMiddleware
from common.policy_profile import (
    PolicyProfile,
    PolicyRegistry,
    load_policy_profiles,
    validate_profile_local_artifacts,
)
from common.settlement_v6 import (
    PUBLIC_SIGNAL_ORDER_V6,
    SETTLEMENT_PUBLIC_V6_DOMAIN,
    verify_period_submission_v6,
)
from services.charger.store import (
    ChargerConflict,
    ChargerNotFound,
    ChargerStore,
    ChargerStoreError,
)


router = APIRouter()
transparent_router = APIRouter()
MAX_CHARGER_REQUEST_BYTES = 1024 * 1024
PROOF_VERIFY_TIMEOUT_SEC = 30
_PROOF_VERIFY_SLOTS = threading.BoundedSemaphore(value=2)


@dataclass(frozen=True)
class ChargerSettings:
    database_url: str
    charger_domain: str
    admin_token: str
    token_pepper: str
    test_mode: bool = False
    allow_transparent_endpoints: bool = False
    enable_reset: bool = False
    allow_sqlite_backend_for_tests: bool = False

    def __post_init__(self) -> None:
        if self.allow_transparent_endpoints and not self.test_mode:
            raise ValueError(
                "transparent settlement endpoints require explicit Charger test mode"
            )
        if self.enable_reset and not self.test_mode:
            raise ValueError("the destructive reset endpoint requires explicit Charger test mode")
        if hmac.compare_digest(self.admin_token, self.token_pepper):
            raise ValueError("Charger administrator token and token pepper must be independent")
        if (
            not self.test_mode
            and not self.allow_sqlite_backend_for_tests
            and not self.database_url.startswith(("postgresql://", "postgresql+psycopg://"))
        ):
            raise ValueError("production Charger requires a PostgreSQL database URL")

    @classmethod
    def from_environment(cls) -> "ChargerSettings":
        test_mode = os.getenv("WAYBILL_CHARGER_TEST_MODE", "") == "1"
        database_url = os.getenv("WAYBILL_CHARGER_DATABASE_URL", "")
        charger_domain = os.getenv("WAYBILL_CHARGER_DOMAIN", "")
        admin_token = os.getenv("WAYBILL_CHARGER_ADMIN_TOKEN", "")
        token_pepper = os.getenv("WAYBILL_CHARGER_TOKEN_PEPPER", "")
        # Benchmarks that must run with authentication enforced but without a
        # production database set this flag to acknowledge the SQLite ledger
        # explicitly; it never relaxes authentication or anchoring.
        allow_sqlite_backend = os.getenv("WAYBILL_CHARGER_ALLOW_SQLITE_BACKEND", "") == "1"
        if not database_url or not charger_domain or not admin_token or not token_pepper:
            raise RuntimeError(
                "WAYBILL_CHARGER_DATABASE_URL, WAYBILL_CHARGER_DOMAIN, "
                "WAYBILL_CHARGER_ADMIN_TOKEN, and WAYBILL_CHARGER_TOKEN_PEPPER are required"
            )
        if not test_mode and (len(admin_token) < 32 or len(token_pepper) < 32):
            raise RuntimeError("production Charger credentials must contain at least 32 characters")
        return cls(
            database_url=database_url,
            charger_domain=charger_domain,
            admin_token=admin_token,
            token_pepper=token_pepper,
            test_mode=test_mode,
            allow_transparent_endpoints=test_mode,
            enable_reset=test_mode,
            allow_sqlite_backend_for_tests=allow_sqlite_backend,
        )


ROOT_DIR = Path(__file__).resolve().parents[2]
POLICY_PROFILE_DIR = Path(
    os.getenv(
        "SETTLEMENT_POLICY_PROFILE_DIR",
        str(ROOT_DIR / "configs" / "settlement_policy_profiles"),
    )
)
policy_registry: PolicyRegistry = load_policy_profiles(POLICY_PROFILE_DIR)

PERIOD_FIX_CAP = int(os.getenv("SETTLEMENT_PERIOD_FIX_CAP", "25"))
# Proof-only submissions carry a constant-size, signed receiver attestation
# rather than the raw fix list.  Its fix count must cover every registered
# circuit shape in the frozen formal matrix; the proof-only endpoint below
# still requires exact equality with the resolved canonical profile.
ROOT_ATTESTATION_FIX_CAP = 200
PERIOD_MAX_HOURS = int(os.getenv("SETTLEMENT_PERIOD_MAX_HOURS", "2"))
CADENCE_SEC = int(os.getenv("SETTLEMENT_CADENCE_SEC", "300"))
TIER_VMAX_MPS = int(os.getenv("SETTLEMENT_TIER_VMAX_MPS", "33"))
# Path to the snarkjs verification key for the settlement period circuit.
# When set, every submission must include a valid Groth16 proof.
SETTLEMENT_VKEY_PATH = os.getenv("SETTLEMENT_VKEY_PATH", "")
# Reconciliation rate for kilometres not covered by any accepted period.
# Must satisfy rate >= alpha * max_zone_rate with alpha >= 1 so that whole-period
# withholding is never cheaper than exact settlement (monthly extension of the
# E2 monotone-degradation rule).
RECONCILIATION_RATE_CENTS_PER_M = int(os.getenv("SETTLEMENT_RECONCILIATION_RATE_CENTS_PER_M", "5"))


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


def _store(request: Request) -> ChargerStore:
    result = getattr(request.app.state, "charger_store", None)
    if not isinstance(result, ChargerStore):
        raise HTTPException(status_code=503, detail="Charger persistence is unavailable")
    return result


def _settings(request: Request) -> ChargerSettings:
    result = getattr(request.app.state, "charger_settings", None)
    if not isinstance(result, ChargerSettings):
        raise HTTPException(status_code=503, detail="Charger settings are unavailable")
    return result


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    return token if token else None


def _device_token_digest(settings: ChargerSettings, token: str) -> str:
    return hmac.new(
        settings.token_pepper.encode("utf-8"),
        b"waybill-device-token-v1\x00" + str(token).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _require_admin(request: Request, authorization: str | None) -> None:
    settings = _settings(request)
    if settings.test_mode:
        return
    token = _bearer_token(authorization)
    if token is None or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(status_code=401, detail="invalid Charger administrator credential")


def _require_device(request: Request, authorization: str | None, device_id: str) -> None:
    settings = _settings(request)
    if settings.test_mode:
        return
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="missing device credential")
    device = _store(request).get_device(device_id)
    if device is None:
        raise HTTPException(status_code=401, detail="invalid device credential")
    digest = _device_token_digest(settings, token)
    if not hmac.compare_digest(digest, str(device["token_digest"])):
        raise HTTPException(status_code=403, detail="device credential does not authorize this device")


def _profile_vkey_path(profile: PolicyProfile) -> Path:
    """Resolve and re-hash the pinned key on every proof acceptance path."""

    validate_profile_local_artifacts(profile, base_dir=POLICY_PROFILE_DIR)
    path = Path(profile.verification_key_path)
    return path if path.is_absolute() else POLICY_PROFILE_DIR / path


def _resolve_expected_profile(
    store: ChargerStore, device_id: str, public: dict[str, Any]
) -> PolicyProfile:
    device = store.get_device(str(device_id))
    if device is None:
        raise ValueError(f"device {device_id!r} has no canonical jurisdiction binding")
    jurisdiction_id = str(device["jurisdiction_id"])
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
        try:
            with _PROOF_VERIFY_SLOTS:
                proc = subprocess.run(
                    [
                        "snarkjs",
                        "groth16",
                        "verify",
                        vkey_path,
                        str(tdp / "public.json"),
                        str(tdp / "proof.json"),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=PROOF_VERIFY_TIMEOUT_SEC,
                )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Groth16 verifier timed out") from exc
        if proc.returncode != 0 or "OK!" not in proc.stdout:
            raise ValueError("Groth16 proof rejected")


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
    store: ChargerStore,
    device_id: str,
    public: dict[str, Any],
    profile: PolicyProfile,
    root_attestation: dict[str, Any] | None = None,
    allow_unanchored: bool = False,
) -> tuple[str, str]:
    """Dedup, overlap-check, and accumulate an accepted period into the ledger."""

    month_id = str(public["month_id"])
    normalized_month = _month_number(month_id)
    if "total_distance_m" not in public:
        raise HTTPException(status_code=400, detail="total_distance_m is required for monthly reconciliation")
    max_zone_rate = int(public.get("max_zone_rate_cents_per_m", 0))
    reconciliation_rate = int(profile.monthly_reconciliation_rate_cents_per_m)
    if max_zone_rate != int(profile.max_zone_rate_cents_per_m):
        raise HTTPException(status_code=400, detail="accepted tariff max is not canonical")
    if reconciliation_rate != max_zone_rate:
        raise HTTPException(status_code=500, detail="canonical reconciliation arithmetic is inconsistent")
    try:
        return store.accept_period(
            device_id=device_id,
            public=public,
            month_number=normalized_month,
            reconciliation_rate_cents_per_m=reconciliation_rate,
            root_attestation=root_attestation,
            allow_unanchored=allow_unanchored,
        )
    except ChargerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChargerStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_receiver_anchor_preflight(
    store: ChargerStore,
    *,
    device_id: str,
    period_id: str,
    root_attestation: dict[str, Any],
) -> None:
    """Reject missing, altered, or consumed anchors before Groth16 work."""

    try:
        store.require_unsettled_receiver_attestation(
            device_id=device_id,
            period_id=period_id,
            attestation=root_attestation,
        )
    except ChargerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChargerStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class TariffPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tariff_version: int = Field(ge=0, le=(1 << 32) - 1)
    grid_w: int = Field(ge=1, le=(1 << 16) - 1)
    cell_zones: dict[int, int] = Field(min_length=1, max_length=65_536)
    zone_rates_cents_per_m: dict[int, int] = Field(min_length=1, max_length=65_536)


class DeviceRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=128)
    public_key_hex: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    jurisdiction_id: str = Field(default="ruc-demo", min_length=1, max_length=128)
    device_token: str | None = Field(default=None, max_length=512)


class PeriodSubmission(BaseModel):
    fixes: list[dict[str, Any]] = Field(min_length=2, max_length=PERIOD_FIX_CAP)
    tariff: TariffPayload
    public_statement: dict[str, Any]
    proof: dict[str, Any] | None = None
    public_signals: list[str] | None = Field(default=None, max_length=64)


class V6PeriodSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixes: list[dict[str, Any]] = Field(min_length=2, max_length=PERIOD_FIX_CAP)
    position_valid: list[StrictBool] = Field(min_length=1, max_length=PERIOD_FIX_CAP - 1)
    tariff: TariffPayload
    public_statement: dict[str, Any]
    proof: dict[str, Any] | None = None
    public_signals: list[str] | None = Field(default=None, max_length=64)


class RootAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str = Field(alias="schema")
    receiver_id: str = Field(min_length=1, max_length=128)
    charger_domain: str = Field(min_length=1, max_length=255)
    device_id: str = Field(min_length=1, max_length=128)
    period_id: str = Field(min_length=1, max_length=128)
    log_epoch: int = Field(ge=1, le=(1 << 63) - 1)
    fix_count: int = Field(ge=2, le=ROOT_ATTESTATION_FIX_CAP)
    receiver_fix_root: str = Field(min_length=1, max_length=80)
    device_attestation_commitment: str = Field(min_length=1, max_length=128)
    commitment_semantics: str = Field(min_length=1, max_length=128)
    position_validity_rule: str = Field(min_length=1, max_length=128)
    previous_attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(min_length=1, max_length=128)


class ProofOnlyPeriodSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_statement: dict[str, Any]
    proof: dict[str, Any]
    public_signals: list[str] = Field(max_length=64)
    root_attestation: RootAttestation


class ReceiverAnchorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_attestation: RootAttestation


@router.get("/settlement/devices/{device_id}/receiver-head")
def get_receiver_chain_head(
    device_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_device(request, authorization, device_id)
    try:
        head = _store(request).receiver_head(device_id=device_id)
    except ChargerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "schema": "waybill.charger.receiver-head/v1",
        "charger_domain": _settings(request).charger_domain,
        **head,
    }


@router.post("/settlement/receiver-chain/anchor")
def anchor_receiver_chain_attestation(
    submission: ReceiverAnchorRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    root_attestation = submission.root_attestation
    attestation = root_attestation.model_dump(by_alias=True)
    device_id = str(root_attestation.device_id)
    _require_device(request, authorization, device_id)
    device = _store(request).get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="registered device is unavailable")
    public_key_bytes = bytes(device["public_key"])
    expected_dac = make_device_attestation_commitment(public_key_bytes)
    if str(root_attestation.device_attestation_commitment) != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="receiver attestation device commitment does not match enrollment",
        )
    if not verify_receiver_root_attestation(
        public_statement={
            "period_id": root_attestation.period_id,
            "receiver_fix_root": root_attestation.receiver_fix_root,
            "device_attestation_commitment": (
                root_attestation.device_attestation_commitment
            ),
        },
        attestation=attestation,
        public_key_bytes=public_key_bytes,
        expected_charger_domain=_settings(request).charger_domain,
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "receiver attestation rejected; required schema is "
                f"{SETTLEMENT_ROOT_ATTESTATION_SCHEMA}"
            ),
        )
    try:
        anchored = _store(request).anchor_receiver_attestation(
            attestation=attestation
        )
    except ChargerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChargerStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "schema": "waybill.charger.receiver-head/v1",
        "charger_domain": _settings(request).charger_domain,
        **anchored,
    }


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    store = _store(request)
    try:
        store.ping()
    except ChargerStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "service": "charger",
        "storage": "available",
    }


@router.post("/settlement/devices/register")
def register_device(
    req: DeviceRegistration,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create one authenticated, immutable device enrollment."""

    _require_admin(request, authorization)
    settings = _settings(request)
    try:
        pubkey_bytes = bytes.fromhex(req.public_key_hex)
        if len(pubkey_bytes) != 32:
            raise ValueError("public key must be 32 bytes (raw Ed25519)")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    device_token = req.device_token
    if device_token is None and settings.test_mode:
        device_token = f"waybill-test-device-token:{req.device_id}"
    if device_token is None or (not settings.test_mode and len(device_token) < 32):
        raise HTTPException(status_code=400, detail="device_token must contain at least 32 characters")
    if any(
        hmac.compare_digest(device_token, secret)
        for secret in (settings.admin_token, settings.token_pepper)
    ):
        raise HTTPException(
            status_code=400,
            detail="device_token must be independent from Charger administrator secrets",
        )
    if not settings.test_mode and req.device_id and req.device_id in device_token:
        # The test-mode fallback below is exactly this shape; outside test mode
        # a credential derivable from public registration data is not a
        # credential, however long it is.
        raise HTTPException(
            status_code=400,
            detail="device_token must not be derivable from the device id",
        )
    try:
        created = _store(request).register_device(
            device_id=req.device_id,
            public_key=pubkey_bytes,
            jurisdiction_id=str(req.jurisdiction_id),
            token_digest=_device_token_digest(settings, device_token),
        )
    except ChargerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChargerStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    expected_dac = make_device_attestation_commitment(pubkey_bytes)
    return {
        "ok": True,
        "created": created,
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
    value = str(circuit_id)
    if value.startswith("settlement-period-v6-"):
        return True
    # Formal M2 profiles are generated only for this pre-registered wrapper
    # matrix.  Accept those exact deterministic identifiers without treating
    # arbitrary underscore-prefixed names as canonical V6 circuits.
    return re.fullmatch(
        r"settlement_period_v6_d(?:8|12|14|16)_n(?:25|50|100|200)_k6",
        value,
    ) is not None


@transparent_router.post("/settlement/period")
def submit_period(
    req: PeriodSubmission,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if not _settings(request).allow_transparent_endpoints:
        raise HTTPException(status_code=404, detail="transparent settlement endpoint is disabled")
    store = _store(request)
    fixes = [ReceiverFix.from_dict(x) for x in req.fixes]

    # Resolve the device's public key from the enrollment registry.
    device_id = str(fixes[0].device_id)
    _require_device(request, authorization, device_id)
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = bytes(device["public_key"])

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
        profile = _resolve_expected_profile(store, device_id, req.public_statement)
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
        ps_month_id = int(ps["month_id_field"])
        ps_month_start = int(ps["month_start_time"])
        ps_month_end = int(ps["month_end_time"])
    except (KeyError, TypeError, ValueError) as e:
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

    period_id, month_id = _accept_period(
        store,
        device_id,
        public,
        profile,
        allow_unanchored=_settings(request).test_mode,
    )

    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@transparent_router.post("/settlement/v6/period")
def submit_period_v6(
    req: V6PeriodSubmission,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Recompute and accept the odometer-backed V6 relation.

    The availability bits are private witness material in proof-only mode.  The
    transparent evaluation endpoint receives them solely so it can recompute
    the same interval commitment root and bill as the circuit.
    """

    if not _settings(request).allow_transparent_endpoints:
        raise HTTPException(status_code=404, detail="transparent settlement endpoint is disabled")
    store = _store(request)
    fixes = [ReceiverFix.from_dict(item) for item in req.fixes]
    device_id = str(fixes[0].device_id)
    if any(str(fix.device_id) != device_id for fix in fixes):
        raise HTTPException(status_code=400, detail="all fixes must belong to the enrolled device")
    _require_device(request, authorization, device_id)
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = bytes(device["public_key"])
    expected_dac = make_device_attestation_commitment(device_pubkey)
    if str(req.public_statement.get("device_attestation_commitment", "")) != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )

    try:
        profile = _resolve_expected_profile(store, device_id, req.public_statement)
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
        if "total_distance_m" not in req.public_statement:
            raise ValueError("total_distance_m is required for monthly reconciliation")
        _validate_public_statement_shape(req.public_statement)
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

    period_id, month_id = _accept_period(
        store,
        device_id,
        public,
        profile,
        allow_unanchored=_settings(request).test_mode,
    )
    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@router.post("/settlement/period/proof-only")
def submit_period_proof_only(
    req: ProofOnlyPeriodSubmission,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    store = _store(request)
    public = dict(req.public_statement)

    device_id = str(req.root_attestation.device_id)
    _require_device(request, authorization, device_id)
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = bytes(device["public_key"])

    expected_dac = make_device_attestation_commitment(device_pubkey)
    submitted_dac = str(public.get("device_attestation_commitment", ""))
    if submitted_dac != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )

    root_attestation = req.root_attestation.model_dump(by_alias=True)
    if not verify_receiver_root_attestation(
        public_statement=public,
        attestation=root_attestation,
        public_key_bytes=device_pubkey,
        expected_charger_domain=_settings(request).charger_domain,
    ):
        raise HTTPException(status_code=400, detail="root attestation rejected")

    try:
        profile = _resolve_expected_profile(store, device_id, public)
        _validate_public_statement_shape(public)
        _validate_zk_public_signals(public, req.public_signals)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    _require_receiver_anchor_preflight(
        store,
        device_id=device_id,
        period_id=str(public["period_id"]),
        root_attestation=root_attestation,
    )
    try:
        _verify_zk_proof(
            req.proof,
            req.public_signals,
            str(_profile_vkey_path(profile)),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    period_id, month_id = _accept_period(
        store,
        device_id,
        public,
        profile,
        root_attestation=root_attestation,
    )

    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


@router.post("/settlement/v6/period/proof-only")
def submit_period_proof_only_v6(
    req: ProofOnlyPeriodSubmission,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Accept only a profile-pinned V6 proof and receiver root attestation."""

    store = _store(request)
    public = dict(req.public_statement)
    device_id = str(req.root_attestation.device_id)
    _require_device(request, authorization, device_id)
    device = store.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=400, detail=f"device {device_id!r} not registered")
    device_pubkey = bytes(device["public_key"])
    expected_dac = make_device_attestation_commitment(device_pubkey)
    if str(public.get("device_attestation_commitment", "")) != expected_dac:
        raise HTTPException(
            status_code=400,
            detail="device_attestation_commitment does not match registered device public key",
        )

    root_attestation = req.root_attestation.model_dump(by_alias=True)
    if not verify_receiver_root_attestation(
        public_statement=public,
        attestation=root_attestation,
        public_key_bytes=device_pubkey,
        expected_charger_domain=_settings(request).charger_domain,
    ):
        raise HTTPException(status_code=400, detail="root attestation rejected")

    try:
        profile = _resolve_expected_profile(store, device_id, public)
        if str(public.get("domain_sep")) != SETTLEMENT_PUBLIC_V6_DOMAIN:
            raise ValueError("V6 endpoint requires a V6 public statement")
        if str(profile.fallback_semantics_version) != "odometer-max-rate-v6":
            raise ValueError("canonical profile does not authorize V6 odometer fallback")
        if not _is_v6_settlement_circuit(profile.circuit_id):
            raise ValueError("canonical profile does not pin a V6 settlement circuit")
        if int(req.root_attestation.fix_count) != int(profile.max_fixes):
            raise ValueError("receiver attestation fix count does not match canonical circuit profile")
        if "total_distance_m" not in public:
            raise ValueError("total_distance_m is required for monthly reconciliation")
        _validate_public_statement_shape(public)
        _validate_zk_public_signals_v6(public, req.public_signals)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _require_receiver_anchor_preflight(
        store,
        device_id=device_id,
        period_id=str(public["period_id"]),
        root_attestation=root_attestation,
    )
    try:
        _verify_zk_proof(
            req.proof,
            req.public_signals,
            str(_profile_vkey_path(profile)),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    period_id, month_id = _accept_period(
        store,
        device_id,
        public,
        profile,
        root_attestation=root_attestation,
    )
    return {
        "ok": True,
        "period_id": period_id,
        "month_id": month_id,
        "accepted_public": public,
    }


class MonthlyOdometerAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: str = Field(alias="schema")
    charger_domain: str = Field(min_length=1, max_length=255)
    device_id: str = Field(min_length=1, max_length=128)
    month_id: str = Field(pattern=r"^(?:[0-9]{6}|[0-9]{4}-[0-9]{2})$")
    odometer_start_m: int = Field(ge=0, le=(1 << 64) - 1)
    odometer_end_m: int = Field(ge=0, le=(1 << 64) - 1)
    signature: str = Field(min_length=1, max_length=128)


class MonthCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=128)
    month_id: str = Field(pattern=r"^(?:[0-9]{6}|[0-9]{4}-[0-9]{2})$")


@router.post("/settlement/month/attest")
def attest_month_odometer(
    req: MonthlyOdometerAttestation,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Record receiver-signed month-boundary odometer readings for reconciliation."""

    _require_device(request, authorization, req.device_id)
    store = _store(request)
    device = store.get_device(req.device_id)
    if device is None:
        raise HTTPException(status_code=400, detail=f"device {req.device_id!r} not registered")
    if int(req.odometer_end_m) < int(req.odometer_start_m):
        raise HTTPException(status_code=400, detail="monthly odometer readings must be monotonic")
    try:
        _month_number(req.month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if time.time() < int(canonical_month_window(req.month_id)["month_end_time"]):
        raise HTTPException(status_code=409, detail="billing month has not ended")
    attestation = req.model_dump(by_alias=True)
    if not verify_monthly_odometer_attestation(
        attestation=attestation,
        public_key_bytes=bytes(device["public_key"]),
        expected_charger_domain=_settings(request).charger_domain,
    ):
        raise HTTPException(status_code=400, detail="monthly odometer attestation rejected")
    try:
        created = store.put_attestation(
            device_id=req.device_id,
            month_number=_month_number(req.month_id),
            attestation=attestation,
        )
    except ChargerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChargerStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    attestation_sha256 = hashlib.sha256(
        canonical_json(attestation).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "waybill.charger.month-attestation/v1",
        "ok": True,
        "device_id": req.device_id,
        "month_id": req.month_id.replace("-", ""),
        "attestation_sha256": attestation_sha256,
        "created": created,
        "idempotent": not created,
    }


def _month_reconciliation_rate(
    store: ChargerStore, device_id: str, month_id: str
) -> int:
    month_number = _month_number(month_id)
    rate = store.month_rate(device_id=device_id, month_number=month_number)
    if rate is not None:
        return rate
    device = store.get_device(device_id)
    if device is None:
        raise ValueError(f"device {device_id!r} has no canonical jurisdiction binding")
    month_start = canonical_month_window(month_id)["month_start_time"]
    profile = policy_registry.resolve(
        jurisdiction_id=str(device["jurisdiction_id"]),
        period_start_time=int(month_start),
    )
    return int(profile.monthly_reconciliation_rate_cents_per_m)


@router.post("/settlement/v6/month/close")
def close_month_v6(
    req: MonthCloseRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Finalize a device-month exactly once or enter a durable admin path."""

    _require_admin(request, authorization)
    store = _store(request)
    if store.get_device(req.device_id) is None:
        raise HTTPException(status_code=400, detail=f"device {req.device_id!r} not registered")
    try:
        month_number = _month_number(req.month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if time.time() < int(canonical_month_window(req.month_id)["month_end_time"]):
        raise HTTPException(status_code=409, detail="billing month has not ended")
    try:
        reconciliation_rate = _month_reconciliation_rate(store, req.device_id, req.month_id)
        return store.close_month(
            device_id=req.device_id,
            month_id=req.month_id,
            month_number=month_number,
            default_reconciliation_rate=reconciliation_rate,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChargerConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChargerStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/settlement/month/{month_id}/reconcile")
def reconcile_month(
    month_id: str,
    device_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Monthly completeness reconciliation: bill unaccounted kilometres at the fallback rate.

    unaccounted_m = attested odometer delta - sum of accepted period distances.
    Disjoint period time windows and the in-circuit odometer binding make the
    period sum a lower bound on real driving, so unaccounted_m >= 0 for honest
    devices; a negative value indicates inconsistent submissions and is flagged.
    """

    _require_admin(request, authorization)
    store = _store(request)
    try:
        month_number = _month_number(month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        attestation, month, stored_rate = store.reconciliation_snapshot(
            device_id=device_id, month_number=month_number
        )
    except ChargerNotFound as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    attested_delta_m = int(attestation["odometer_end_m"]) - int(attestation["odometer_start_m"])
    covered_m = int(month["total_distance_m"])
    unaccounted_m = attested_delta_m - covered_m
    consistent = unaccounted_m >= 0
    try:
        reconciliation_rate = stored_rate or _month_reconciliation_rate(
            store, device_id, month_id
        )
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


@router.get("/settlement/month/{month_id}/missing-attestations")
def missing_month_attestations(
    month_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Operator view: enrolled devices that still need month-boundary attestation.

    This is the protocol-level handle for the base case of no-free-kilometre
    reconciliation: not submitting the monthly odometer attestation does not
    make a device disappear, it moves the device-month to the administrative
    penalty path.
    """

    _require_admin(request, authorization)
    try:
        month_number = _month_number(month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    missing = _store(request).missing_attestations(
        month_id=month_id, month_number=month_number
    )
    return {"ok": True, "month_id": month_id, "missing_count": len(missing), "missing": missing}


@router.get("/settlement/month/{month_id}")
def month_status(
    month_id: str,
    request: Request,
    device_id: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin(request, authorization)
    try:
        month_number = _month_number(month_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if device_id is not None:
        month = _store(request).month_totals(
            device_id=device_id, month_number=month_number
        )
        if not any(int(month[key]) for key in month):
            return {"ok": False, "error": "unknown month", "month_id": month_id, "device_id": device_id}
        return {"ok": True, "month_id": month_id, "device_id": device_id, **month}
    totals = _store(request).aggregate_month(month_number=month_number)
    if totals is None:
        return {"ok": False, "error": "unknown month", "month_id": month_id}
    return {"ok": True, "month_id": month_id, **totals}


@router.post("/settlement/reset")
def reset(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin(request, authorization)
    if not _settings(request).enable_reset:
        raise HTTPException(status_code=404, detail="reset endpoint is disabled")
    _store(request).reset()
    return {"ok": True}


def create_app(settings: ChargerSettings | None = None) -> FastAPI:
    resolved = settings or ChargerSettings.from_environment()
    application = FastAPI(title="WayBill Settlement Charger")
    application.add_middleware(
        StrictJSONBodyMiddleware,
        max_body_bytes=MAX_CHARGER_REQUEST_BYTES,
    )

    @application.exception_handler(ChargerStoreError)
    async def handle_store_error(_request: Request, _exc: ChargerStoreError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Charger persistence is unavailable"},
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(_request: Request, _exc: SQLAlchemyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Charger persistence is unavailable"},
        )

    application.state.charger_settings = resolved
    application.state.charger_store = ChargerStore(
        database_url=resolved.database_url,
        charger_domain=resolved.charger_domain,
    )
    application.include_router(router)
    if resolved.allow_transparent_endpoints:
        application.include_router(transparent_router)
    return application


app = create_app()
