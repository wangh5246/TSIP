from __future__ import annotations

import hashlib
import hmac
import json
import os
import ssl
import stat
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Mapping, Protocol
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from common.policy_profile import PolicyProfile
from common.http_security import StrictJSONBodyMiddleware, decode_strict_json
from common.receiver_signer import ReceiverSignerError, ReceiverSignerStore
from common.settlement import (
    SETTLEMENT_POSITION_VALIDITY_RULE,
    SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
    SETTLEMENT_ROOT_ATTESTATION_SCHEMA,
    ReceiverFix,
    canonical_json,
    receiver_attestation_sha256,
)


MAX_ANCHOR_RESPONSE_BYTES = 64 * 1024
MAX_POLICY_PROFILE_BYTES = 1024 * 1024
RECEIVER_PERIOD_FIX_CAP = 25
MAX_RECEIVER_REQUEST_BYTES = 1024 * 1024


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    """Never forward a device bearer token across an HTTP redirect."""

    def redirect_request(
        self,
        req: urllib_request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class ReceiverAnchor(Protocol):
    def head(self) -> Mapping[str, Any]: ...

    def anchor(self, attestation: dict[str, Any]) -> Mapping[str, Any]: ...

    def anchor_month(self, attestation: dict[str, Any]) -> Mapping[str, Any]: ...


def _head_from_response(value: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = value.get("head")
    return nested if isinstance(nested, Mapping) else value


class ChargerReceiverAnchorClient:
    """Authenticated online anchor used to detect local signer DB rollback."""

    def __init__(
        self,
        *,
        base_url: str,
        device_id: str,
        device_token: str,
        timeout_sec: float,
        ca_file: Path | None = None,
    ) -> None:
        parsed = urllib_parse.urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ReceiverSignerError("production Charger anchor URL must use HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ReceiverSignerError("Charger anchor URL must not contain credentials or query data")
        if parsed.path not in {"", "/"}:
            raise ReceiverSignerError("Charger anchor URL must not contain a path prefix")
        if not 0 < float(timeout_sec) <= 30:
            raise ReceiverSignerError("Charger anchor timeout must be between 0 and 30 seconds")
        self.base_url = base_url.rstrip("/")
        self.device_id = str(device_id)
        self.device_token = str(device_token)
        self.timeout_sec = float(timeout_sec)
        try:
            tls_context = ssl.create_default_context(
                cafile=None if ca_file is None else str(ca_file)
            )
        except (OSError, ssl.SSLError) as exc:
            raise ReceiverSignerError(f"cannot load Charger anchor trust store: {exc}") from exc
        tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._opener = urllib_request.build_opener(
            urllib_request.ProxyHandler({}),
            _NoRedirectHandler(),
            urllib_request.HTTPSHandler(context=tls_context),
        )

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Mapping[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.device_token}",
                "Accept": "application/json",
                **({} if data is None else {"Content-Type": "application/json"}),
            },
        )
        try:
            with self._opener.open(request, timeout=self.timeout_sec) as response:
                declared_length = response.headers.get("Content-Length")
                if declared_length is not None and int(declared_length) > MAX_ANCHOR_RESPONSE_BYTES:
                    raise ReceiverSignerError("Charger receiver anchor response is too large")
                body = response.read(MAX_ANCHOR_RESPONSE_BYTES + 1)
                if len(body) > MAX_ANCHOR_RESPONSE_BYTES:
                    raise ReceiverSignerError("Charger receiver anchor response is too large")
                decoded = decode_strict_json(body)
        except (
            urllib_error.URLError,
            TimeoutError,
            OSError,
            UnicodeDecodeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise ReceiverSignerError(f"Charger receiver anchor is unavailable: {exc}") from exc
        if not isinstance(decoded, dict):
            raise ReceiverSignerError("Charger receiver anchor returned a malformed response")
        return decoded

    def head(self) -> Mapping[str, Any]:
        device = urllib_parse.quote(self.device_id, safe="")
        return _head_from_response(
            self._request("GET", f"/settlement/devices/{device}/receiver-head")
        )

    def anchor(self, attestation: dict[str, Any]) -> Mapping[str, Any]:
        return _head_from_response(
            self._request(
                "POST",
                "/settlement/receiver-chain/anchor",
                {"root_attestation": attestation},
            )
        )

    def anchor_month(self, attestation: dict[str, Any]) -> Mapping[str, Any]:
        return self._request("POST", "/settlement/month/attest", attestation)


class InMemoryReceiverAnchor:
    """Single-process anchor permitted only in explicit test mode."""

    def __init__(self, *, device_id: str) -> None:
        self._head: dict[str, Any] = {
            "schema": "waybill.charger.receiver-head/v1",
            "receiver_id": "",
            "device_id": str(device_id),
            "period_id": "",
            "log_epoch": 0,
            "attestation_sha256": SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
            "previous_attestation_sha256": SETTLEMENT_ROOT_ATTESTATION_GENESIS_SHA256,
        }
        self._months: dict[str, dict[str, Any]] = {}

    def head(self) -> Mapping[str, Any]:
        return dict(self._head)

    def anchor(self, attestation: dict[str, Any]) -> Mapping[str, Any]:
        digest = receiver_attestation_sha256(attestation)
        if (
            int(attestation["log_epoch"]) == int(self._head["log_epoch"])
            and digest == self._head["attestation_sha256"]
        ):
            return self.head()
        if (
            int(attestation["log_epoch"]) != int(self._head["log_epoch"]) + 1
            or str(attestation["previous_attestation_sha256"])
            != str(self._head["attestation_sha256"])
        ):
            raise ReceiverSignerError("test receiver anchor rejected a fork or epoch gap")
        self._head = {
            "schema": "waybill.charger.receiver-head/v1",
            "receiver_id": str(attestation["receiver_id"]),
            "device_id": str(attestation["device_id"]),
            "period_id": str(attestation["period_id"]),
            "log_epoch": int(attestation["log_epoch"]),
            "attestation_sha256": digest,
            "previous_attestation_sha256": str(
                attestation["previous_attestation_sha256"]
            ),
        }
        return self.head()

    @staticmethod
    def _next_month(month_number: int) -> int:
        year, month = divmod(int(month_number), 100)
        return (year + 1) * 100 + 1 if month == 12 else year * 100 + month + 1

    def anchor_month(self, attestation: dict[str, Any]) -> Mapping[str, Any]:
        month_id = str(attestation.get("month_id", ""))
        if len(month_id) != 6 or not month_id.isdigit():
            raise ReceiverSignerError("test month anchor requires YYYYMM")
        if str(attestation.get("device_id", "")) != str(self._head["device_id"]):
            raise ReceiverSignerError("test month anchor rejected another device")
        digest = hashlib.sha256(canonical_json(attestation).encode("utf-8")).hexdigest()
        existing = self._months.get(month_id)
        if existing is not None:
            if existing["attestation_sha256"] != digest:
                raise ReceiverSignerError("test month anchor rejected conflicting bytes")
            return {**existing, "created": False, "idempotent": True}
        if self._months:
            previous_id = max(self._months)
            previous = self._months[previous_id]
            if int(month_id) != self._next_month(int(previous_id)):
                raise ReceiverSignerError("test month anchor rejected a month gap")
            if int(attestation["odometer_start_m"]) != int(previous["odometer_end_m"]):
                raise ReceiverSignerError("test month anchor rejected odometer discontinuity")
        confirmed = {
            "schema": "waybill.charger.month-attestation/v1",
            "ok": True,
            "device_id": self._head["device_id"],
            "month_id": month_id,
            "odometer_end_m": int(attestation["odometer_end_m"]),
            "attestation_sha256": digest,
            "created": True,
            "idempotent": False,
        }
        self._months[month_id] = confirmed
        return dict(confirmed)


@dataclass(frozen=True)
class ReceiverSignerSettings:
    database_path: Path
    key_path: Path
    acquisition_token: str
    prover_token: str
    receiver_id: str
    device_id: str
    charger_domain: str
    policy_profile_path: Path
    charger_base_url: str | None
    charger_device_token: str | None
    charger_ca_file: Path | None = None
    test_mode: bool = False
    anchor_timeout_sec: float = 5.0

    def __post_init__(self) -> None:
        if not self.database_path.is_absolute() or not self.key_path.is_absolute():
            raise ReceiverSignerError("receiver database and key paths must be absolute")
        if self.database_path.parent != self.key_path.parent:
            raise ReceiverSignerError("receiver database and key must share one private state directory")
        if not self.policy_profile_path.is_absolute():
            raise ReceiverSignerError("receiver policy profile path must be absolute")
        if len(self.acquisition_token) < 32:
            raise ReceiverSignerError(
                "receiver acquisition token must contain at least 32 characters"
            )
        if len(self.prover_token) < 32:
            raise ReceiverSignerError(
                "receiver prover token must contain at least 32 characters"
            )
        if hmac.compare_digest(self.acquisition_token, self.prover_token):
            raise ReceiverSignerError(
                "receiver acquisition and prover tokens must be independent"
            )
        if self.test_mode:
            return
        if not self.charger_base_url or not self.charger_device_token:
            raise ReceiverSignerError(
                "production receiver signer requires a Charger anchor URL and device token"
            )
        if len(self.charger_device_token) < 32:
            raise ReceiverSignerError("Charger device token must contain at least 32 characters")
        if any(
            hmac.compare_digest(self.charger_device_token, token)
            for token in (self.acquisition_token, self.prover_token)
        ):
            raise ReceiverSignerError("Charger, acquisition, and prover tokens must be independent")
        if self.charger_ca_file is None:
            raise ReceiverSignerError("production receiver signer requires an explicit Charger CA file")
        if not self.charger_ca_file.is_absolute():
            raise ReceiverSignerError("Charger CA file path must be absolute")
        try:
            ca_stat = os.lstat(self.charger_ca_file)
        except OSError as exc:
            raise ReceiverSignerError(f"cannot inspect Charger CA file: {exc}") from exc
        if not stat.S_ISREG(ca_stat.st_mode):
            raise ReceiverSignerError("Charger CA file must be a regular file")
        if ca_stat.st_uid not in {0, os.geteuid()}:
            raise ReceiverSignerError("Charger CA file owner mismatch")
        if stat.S_IMODE(ca_stat.st_mode) & 0o022:
            raise ReceiverSignerError("Charger CA file must not be group/world writable")
        ChargerReceiverAnchorClient(
            base_url=self.charger_base_url,
            device_id=self.device_id,
            device_token=self.charger_device_token,
            timeout_sec=self.anchor_timeout_sec,
            ca_file=self.charger_ca_file,
        )

    @classmethod
    def from_environment(cls) -> "ReceiverSignerSettings":
        database = os.getenv("WAYBILL_RECEIVER_DB", "")
        key_path = os.getenv("WAYBILL_RECEIVER_KEY_FILE", "")
        acquisition_token = os.getenv("WAYBILL_RECEIVER_ACQUISITION_TOKEN", "")
        prover_token = os.getenv("WAYBILL_RECEIVER_PROVER_TOKEN", "")
        receiver_id = os.getenv("WAYBILL_RECEIVER_ID", "")
        device_id = os.getenv("WAYBILL_RECEIVER_DEVICE_ID", "")
        charger_domain = os.getenv("WAYBILL_CHARGER_DOMAIN", "")
        policy_profile_path = os.getenv("WAYBILL_RECEIVER_POLICY_PROFILE", "")
        test_mode = os.getenv("WAYBILL_RECEIVER_TEST_MODE", "") == "1"
        charger_base_url = os.getenv("WAYBILL_RECEIVER_CHARGER_URL", "") or None
        charger_device_token = os.getenv("WAYBILL_RECEIVER_CHARGER_DEVICE_TOKEN", "") or None
        charger_ca_file_raw = os.getenv("WAYBILL_RECEIVER_CHARGER_CA_FILE", "")
        if not all(
            (
                database,
                key_path,
                acquisition_token,
                prover_token,
                receiver_id,
                device_id,
                charger_domain,
                policy_profile_path,
            )
        ):
            raise ReceiverSignerError(
                "WAYBILL_RECEIVER_DB, WAYBILL_RECEIVER_KEY_FILE, "
                "WAYBILL_RECEIVER_ACQUISITION_TOKEN, WAYBILL_RECEIVER_PROVER_TOKEN, "
                "WAYBILL_RECEIVER_ID, WAYBILL_RECEIVER_DEVICE_ID, and "
                "WAYBILL_CHARGER_DOMAIN and WAYBILL_RECEIVER_POLICY_PROFILE are required"
            )
        return cls(
            database_path=Path(database),
            key_path=Path(key_path),
            acquisition_token=acquisition_token,
            prover_token=prover_token,
            receiver_id=receiver_id,
            device_id=device_id,
            charger_domain=charger_domain,
            policy_profile_path=Path(policy_profile_path),
            charger_base_url=charger_base_url,
            charger_device_token=charger_device_token,
            charger_ca_file=(Path(charger_ca_file_raw) if charger_ca_file_raw else None),
            test_mode=test_mode,
        )

    def load_policy_profile(self) -> PolicyProfile:
        """Load and structurally pin the signer-owned canonical V6 policy."""

        profile_descriptor: int | None = None
        try:
            profile_descriptor = os.open(
                self.policy_profile_path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            profile_stat = os.fstat(profile_descriptor)
            if not stat.S_ISREG(profile_stat.st_mode):
                raise ReceiverSignerError("receiver policy profile must be a regular file")
            if profile_stat.st_uid not in {0, os.geteuid()}:
                raise ReceiverSignerError("receiver policy profile owner mismatch")
            if stat.S_IMODE(profile_stat.st_mode) & 0o022:
                raise ReceiverSignerError("receiver policy profile must not be group/world writable")
            if not 0 < profile_stat.st_size <= MAX_POLICY_PROFILE_BYTES:
                raise ReceiverSignerError("receiver policy profile size is invalid")
            profile_bytes = os.read(profile_descriptor, profile_stat.st_size + 1)
            if len(profile_bytes) != profile_stat.st_size:
                raise ReceiverSignerError("receiver policy profile changed while it was read")
            profile = PolicyProfile.from_dict(json.loads(profile_bytes))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ReceiverSignerError):
                raise
            raise ReceiverSignerError(
                f"cannot load canonical receiver policy profile: {exc}"
            ) from exc
        finally:
            if profile_descriptor is not None:
                os.close(profile_descriptor)
        if not profile.circuit_id.startswith("settlement-period-v6-"):
            raise ReceiverSignerError("receiver signer requires an active V6 policy profile")
        if profile.receiver_attestation_schema != SETTLEMENT_ROOT_ATTESTATION_SCHEMA:
            raise ReceiverSignerError("receiver policy pins another root-attestation schema")
        if profile.position_validity_rule != SETTLEMENT_POSITION_VALIDITY_RULE:
            raise ReceiverSignerError("receiver policy pins another position-validity rule")
        if not 2 <= int(profile.max_fixes) <= RECEIVER_PERIOD_FIX_CAP:
            raise ReceiverSignerError("receiver policy fix cap is unsupported")
        if profile.overflow_policy != "reject-u96":
            raise ReceiverSignerError("receiver V6 policy must use reject-u96 overflow handling")
        if not profile.fallback_semantics_version.startswith("odometer-max-rate"):
            raise ReceiverSignerError("receiver V6 policy must use odometer-backed fallback")
        return profile

    def build_store(
        self, *, policy_profile: PolicyProfile | None = None
    ) -> ReceiverSignerStore:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.key_path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            key_stat = os.fstat(descriptor)
            if not stat.S_ISREG(key_stat.st_mode):
                raise ReceiverSignerError("receiver key must be a regular file")
            if key_stat.st_uid != os.geteuid():
                raise ReceiverSignerError("receiver key owner mismatch")
            if stat.S_IMODE(key_stat.st_mode) != 0o600:
                raise ReceiverSignerError("receiver key file must be mode 0600")
            if key_stat.st_nlink != 1:
                raise ReceiverSignerError("receiver key must not have hard links")
            seed = os.read(descriptor, 33)
            if len(seed) != 32:
                raise ReceiverSignerError("receiver key must be exactly 32 bytes")
        except OSError as exc:
            raise ReceiverSignerError(f"cannot read receiver key file: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        profile = policy_profile or self.load_policy_profile()
        return ReceiverSignerStore(
            database_path=self.database_path,
            private_key_bytes=seed,
            receiver_id=self.receiver_id,
            device_id=self.device_id,
            charger_domain=self.charger_domain,
            policy_profile_commitment=profile.commitment,
        )

    def build_anchor(self) -> ReceiverAnchor:
        if self.test_mode:
            return InMemoryReceiverAnchor(device_id=self.device_id)
        assert self.charger_base_url is not None
        assert self.charger_device_token is not None
        return ChargerReceiverAnchorClient(
            base_url=self.charger_base_url,
            device_id=self.device_id,
            device_token=self.charger_device_token,
            timeout_sec=self.anchor_timeout_sec,
            ca_file=self.charger_ca_file,
        )


class ReceiverLogRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixes: list["ReceiverFixRequest"] = Field(
        min_length=2, max_length=RECEIVER_PERIOD_FIX_CAP
    )


class ReceiverFixRequest(BaseModel):
    """Unsigned measurement accepted only from the trusted acquisition path."""

    model_config = ConfigDict(extra="forbid")

    domain_sep: str = Field(pattern=r"^tsip_settlement_receiver_fix_v1$")
    device_id: str = Field(min_length=1, max_length=128)
    period_id: str = Field(min_length=1, max_length=128)
    fix_seq: StrictInt = Field(ge=0, le=RECEIVER_PERIOD_FIX_CAP - 1)
    auth_gnss_time: StrictInt = Field(ge=0, le=(1 << 64) - 1)
    cell_x: StrictInt = Field(ge=0, le=(1 << 31) - 1)
    cell_y: StrictInt = Field(ge=0, le=(1 << 31) - 1)
    osnma_status: Literal["authenticated", "unavailable"]
    odometer_reading_m: StrictInt = Field(ge=0, le=(1 << 64) - 1)
    nonce: str = Field(min_length=1, max_length=128)


class ReceiverMonthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=128)
    month_id: str = Field(pattern=r"^[0-9]{6}$")
    odometer_start_m: StrictInt = Field(ge=0, le=(1 << 64) - 1)
    odometer_end_m: StrictInt = Field(ge=0, le=(1 << 64) - 1)


def create_app(settings: ReceiverSignerSettings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        resolved = settings or ReceiverSignerSettings.from_environment()
        application.state.receiver_settings = resolved
        application.state.receiver_profile = resolved.load_policy_profile()
        application.state.receiver_store = resolved.build_store(
            policy_profile=application.state.receiver_profile
        )
        application.state.receiver_anchor = resolved.build_anchor()
        yield

    application = FastAPI(title="WayBill Independent Receiver Signer", lifespan=lifespan)
    application.add_middleware(
        StrictJSONBodyMiddleware,
        max_body_bytes=MAX_RECEIVER_REQUEST_BYTES,
    )

    def store() -> ReceiverSignerStore:
        result = getattr(application.state, "receiver_store", None)
        if not isinstance(result, ReceiverSignerStore):
            raise HTTPException(status_code=503, detail="receiver signer is not initialized")
        return result

    def anchor() -> ReceiverAnchor:
        result = getattr(application.state, "receiver_anchor", None)
        if (
            result is None
            or not callable(getattr(result, "head", None))
            or not callable(getattr(result, "anchor", None))
            or not callable(getattr(result, "anchor_month", None))
        ):
            raise HTTPException(status_code=503, detail="receiver anchor is not initialized")
        return result

    def policy_profile() -> PolicyProfile:
        result = getattr(application.state, "receiver_profile", None)
        if not isinstance(result, PolicyProfile):
            raise HTTPException(status_code=503, detail="receiver policy is not initialized")
        return result

    def require_token(authorization: str | None, *, token: str, scope: str) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail=f"invalid receiver {scope} credential")

    @application.get("/health")
    def health() -> dict[str, Any]:
        store()
        return {
            "ok": True,
            "service": "receiver-signer",
            "storage": "sqlite-charger-anchored",
        }

    @application.post("/v2/receiver/logs", status_code=201)
    def seal_log(
        request: ReceiverLogRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_token(
            authorization,
            token=application.state.receiver_settings.acquisition_token,
            scope="acquisition",
        )
        try:
            fixes = [ReceiverFix.from_dict(item.model_dump()) for item in request.fixes]
            profile = policy_profile()
            if len(fixes) > int(profile.max_fixes):
                raise ReceiverSignerError("receiver period exceeds the canonical policy fix cap")
            for previous, current in zip(fixes, fixes[1:]):
                if int(current.auth_gnss_time) - int(previous.auth_gnss_time) > int(
                    profile.max_dt_sec
                ):
                    raise ReceiverSignerError("receiver period exceeds the canonical maximum fix gap")
            if not application.state.receiver_settings.test_mode:
                try:
                    profile.assert_active_for(
                        jurisdiction_id=profile.jurisdiction_id,
                        period_start_time=int(fixes[0].auth_gnss_time),
                    )
                except ValueError as exc:
                    raise ReceiverSignerError(str(exc)) from exc
                if int(fixes[-1].auth_gnss_time) >= int(profile.valid_to):
                    raise ReceiverSignerError("receiver period crosses the canonical policy expiry")
            live_head = anchor().head()
            sealed = store().seal_period(
                fixes=fixes,
                charger_head=live_head,
                anchor_attestation=anchor().anchor,
            )
        except (KeyError, TypeError, ValueError, ReceiverSignerError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "schema": "waybill.receiver.sealed-log/v2",
            **sealed,
        }

    @application.get("/v2/receiver/logs/{device_id}/{period_id}/attestation")
    def get_attestation(
        device_id: str,
        period_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_token(
            authorization,
            token=application.state.receiver_settings.prover_token,
            scope="prover",
        )
        try:
            material = store().period_material(device_id=device_id, period_id=period_id)
        except ReceiverSignerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "schema": "waybill.receiver.period-material/v2",
            "fixes": material["fixes"],
            "position_valid": material["position_valid"],
            "position_validity_rule": material["position_validity_rule"],
            "policy_profile_commitment": material["policy_profile_commitment"],
            "receiver_public_key_hex": store().public_key_bytes.hex(),
            "attestation": material["attestation"],
        }

    @application.post("/v2/receiver/months", status_code=201)
    def seal_month(
        request: ReceiverMonthRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_token(
            authorization,
            token=application.state.receiver_settings.acquisition_token,
            scope="acquisition",
        )
        try:
            attestation = store().seal_month(
                device_id=request.device_id,
                month_id=request.month_id,
                odometer_start_m=int(request.odometer_start_m),
                odometer_end_m=int(request.odometer_end_m),
                anchor_attestation=anchor().anchor_month,
            )
        except ReceiverSignerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"schema": "waybill.receiver.sealed-month/v2", **attestation}

    @application.get("/v2/receiver/months/{device_id}/{month_id}/attestation")
    def get_month_attestation(
        device_id: str,
        month_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_token(
            authorization,
            token=application.state.receiver_settings.prover_token,
            scope="prover",
        )
        try:
            material = store().month_attestation(device_id=device_id, month_id=month_id)
        except ReceiverSignerError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        attestation = {key: value for key, value in material.items() if key != "month_epoch"}
        return {
            "schema": "waybill.receiver.month-material/v2",
            "month_epoch": material["month_epoch"],
            "receiver_public_key_hex": store().public_key_bytes.hex(),
            "attestation": attestation,
        }

    return application


app = create_app()
