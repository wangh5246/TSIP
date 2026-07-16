from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from common.settlement import (
    TariffTable,
    canonical_json,
    field_from_text,
    poseidon_chain,
)


POLICY_PROFILE_DOMAIN = "waybill_policy_profile_v1"
POLICY_PROFILE_COMMITMENT_VERSION = 1


@dataclass(frozen=True)
class PolicyProfile:
    """Authority-controlled settlement policy selected by jurisdiction and time.

    Paths are local deployment metadata.  They are deliberately excluded from
    the canonical commitment; the verification-key and tariff *hashes/roots*
    are the authority-facing values that travel between deployments.
    """

    authority_id: str
    jurisdiction_id: str
    profile_version: int
    valid_from: int
    valid_to: int
    revoked_at: int | None
    min_accepted_version: int
    tariff_version: int
    tariff_root: int
    tariff_tree_depth: int
    max_fixes: int
    max_zone_rate_cents_per_m: int
    cadence_sec: int
    max_dt_sec: int
    tier_vmax_mps: int
    tier_vmax_sq: int
    mode_vmax_sq: int
    cap_policy_sq: int
    cap_policy_hash: str
    circuit_id: str
    verification_key_hash: str
    currency: str
    fixed_point_scale: int
    rounding_mode: str
    overflow_policy: str
    monthly_reconciliation_rate_cents_per_m: int
    fallback_semantics_version: str
    verification_key_path: str = ""
    tariff_artifact_path: str = ""

    def __post_init__(self) -> None:
        if not self.authority_id:
            raise ValueError("authority_id must not be empty")
        if not self.jurisdiction_id:
            raise ValueError("jurisdiction_id must not be empty")
        if int(self.profile_version) < 1:
            raise ValueError("profile_version must be positive")
        if int(self.min_accepted_version) < 1:
            raise ValueError("min_accepted_version must be positive")
        if int(self.profile_version) < int(self.min_accepted_version):
            raise ValueError("profile_version is below min_accepted_version")
        if int(self.valid_from) >= int(self.valid_to):
            raise ValueError("valid_from must be before valid_to")
        if self.revoked_at is not None and int(self.revoked_at) < 0:
            raise ValueError("revoked_at must be null or non-negative")
        for name in (
            "tariff_version",
            "tariff_root",
            "tariff_tree_depth",
            "max_fixes",
            "max_zone_rate_cents_per_m",
            "cadence_sec",
            "max_dt_sec",
            "tier_vmax_mps",
            "tier_vmax_sq",
            "mode_vmax_sq",
            "cap_policy_sq",
            "fixed_point_scale",
            "monthly_reconciliation_rate_cents_per_m",
        ):
            if int(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if int(self.tier_vmax_sq) != int(self.tier_vmax_mps) ** 2:
            raise ValueError("tier_vmax_sq must equal tier_vmax_mps squared")
        if int(self.monthly_reconciliation_rate_cents_per_m) != int(
            self.max_zone_rate_cents_per_m
        ):
            raise ValueError("monthly reconciliation rate must equal canonical max zone rate")
        if self.currency not in {"CNY", "EUR", "USD"}:
            raise ValueError("currency must be an explicitly supported ISO-4217 code")
        if self.rounding_mode not in {"exact-integer", "floor", "ceil", "half-up"}:
            raise ValueError("unsupported rounding_mode")
        if self.overflow_policy not in {"reject-u96", "reject-u128"}:
            raise ValueError("unsupported overflow_policy")
        if len(self.verification_key_hash) != 64:
            raise ValueError("verification_key_hash must be a lowercase SHA-256 hex digest")
        try:
            int(self.verification_key_hash, 16)
        except ValueError as exc:
            raise ValueError("verification_key_hash must be hexadecimal") from exc
        if self.verification_key_hash.lower() != self.verification_key_hash:
            raise ValueError("verification_key_hash must be lowercase")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PolicyProfile":
        data = dict(raw)
        data.pop("domain_sep", None)
        data.pop("commitment_version", None)
        declared_commitment = data.pop("policy_profile_commitment", None)
        declared_sha256 = data.pop("profile_sha256", None)
        profile = cls(**data)
        if declared_commitment is not None and int(declared_commitment) != profile.commitment:
            raise ValueError("policy_profile_commitment does not match canonical profile")
        if declared_sha256 is not None and str(declared_sha256) != profile.profile_sha256:
            raise ValueError("profile_sha256 does not match canonical profile")
        return profile

    def semantic_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("verification_key_path", None)
        data.pop("tariff_artifact_path", None)
        return {
            "domain_sep": POLICY_PROFILE_DOMAIN,
            "commitment_version": POLICY_PROFILE_COMMITMENT_VERSION,
            **data,
        }

    @property
    def canonical_serialization(self) -> str:
        return canonical_json(self.semantic_payload())

    @property
    def profile_sha256(self) -> str:
        return hashlib.sha256(self.canonical_serialization.encode("utf-8")).hexdigest()

    @property
    def commitment(self) -> int:
        payload = self.semantic_payload()
        values: list[int] = [
            field_from_text(str(payload["domain_sep"])),
            int(payload["commitment_version"]),
            field_from_text(self.authority_id),
            field_from_text(self.jurisdiction_id),
            int(self.profile_version),
            int(self.valid_from),
            int(self.valid_to),
            0 if self.revoked_at is None else int(self.revoked_at),
            int(self.min_accepted_version),
            int(self.tariff_version),
            int(self.tariff_root),
            int(self.tariff_tree_depth),
            int(self.max_fixes),
            int(self.max_zone_rate_cents_per_m),
            int(self.cadence_sec),
            int(self.max_dt_sec),
            int(self.tier_vmax_mps),
            int(self.tier_vmax_sq),
            int(self.mode_vmax_sq),
            int(self.cap_policy_sq),
            field_from_text(self.cap_policy_hash),
            field_from_text(self.circuit_id),
            field_from_text(self.verification_key_hash),
            field_from_text(self.currency),
            int(self.fixed_point_scale),
            field_from_text(self.rounding_mode),
            field_from_text(self.overflow_policy),
            int(self.monthly_reconciliation_rate_cents_per_m),
            field_from_text(self.fallback_semantics_version),
        ]
        return poseidon_chain(values)

    def to_dict(self, *, include_local_paths: bool = True) -> dict[str, Any]:
        data = self.semantic_payload()
        if include_local_paths:
            data["verification_key_path"] = self.verification_key_path
            data["tariff_artifact_path"] = self.tariff_artifact_path
        data["policy_profile_commitment"] = str(self.commitment)
        data["profile_sha256"] = self.profile_sha256
        return data

    def public_statement_fields(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "jurisdiction_id": self.jurisdiction_id,
            "profile_version": int(self.profile_version),
            "policy_profile_commitment": str(self.commitment),
            "tariff_version": int(self.tariff_version),
            "tariff_root": str(self.tariff_root),
            "tariff_tree_depth": int(self.tariff_tree_depth),
            "max_fixes": int(self.max_fixes),
            "max_zone_rate_cents_per_m": int(self.max_zone_rate_cents_per_m),
            "cadence_sec": int(self.cadence_sec),
            "max_dt_sec": int(self.max_dt_sec),
            "tier_vmax_mps": int(self.tier_vmax_mps),
            "tier_vmax_sq": int(self.tier_vmax_sq),
            "mode_vmax_sq": int(self.mode_vmax_sq),
            "cap_policy_sq": int(self.cap_policy_sq),
            "cap_policy_hash": self.cap_policy_hash,
            "circuit_id": self.circuit_id,
            "verification_key_hash": self.verification_key_hash,
            "currency": self.currency,
            "fixed_point_scale": int(self.fixed_point_scale),
            "rounding_mode": self.rounding_mode,
            "overflow_policy": self.overflow_policy,
            "monthly_reconciliation_rate_cents_per_m": int(
                self.monthly_reconciliation_rate_cents_per_m
            ),
            "fallback_semantics_version": self.fallback_semantics_version,
        }

    def assert_active_for(self, *, jurisdiction_id: str, period_start_time: int) -> None:
        if str(jurisdiction_id) != self.jurisdiction_id:
            raise ValueError("policy jurisdiction mismatch")
        if self.revoked_at is not None:
            raise ValueError("policy profile is revoked")
        if not int(self.valid_from) <= int(period_start_time) < int(self.valid_to):
            raise ValueError("policy profile is not active for the billing period")
        if int(self.profile_version) < int(self.min_accepted_version):
            raise ValueError("policy profile is below anti-rollback floor")

    def assert_statement_matches(self, public_statement: dict[str, Any]) -> None:
        for key, expected in self.public_statement_fields().items():
            got = public_statement.get(key)
            if isinstance(expected, int):
                try:
                    got = int(got)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"policy field missing or malformed: {key}") from exc
            else:
                got = str(got) if got is not None else None
            if got != expected:
                raise ValueError(f"canonical policy mismatch: {key}")

    def assert_tariff_matches(self, tariff: TariffTable) -> None:
        if int(tariff.tariff_version) != int(self.tariff_version):
            raise ValueError("canonical policy mismatch: tariff_version")
        if int(tariff.root(self.tariff_tree_depth)) != int(self.tariff_root):
            raise ValueError("canonical policy mismatch: tariff_root")
        if int(tariff.max_zone_rate_cents_per_m) != int(self.max_zone_rate_cents_per_m):
            raise ValueError("canonical policy mismatch: max_zone_rate_cents_per_m")


class PolicyRegistry:
    def __init__(self, profiles: Iterable[PolicyProfile] = ()) -> None:
        self._profiles = list(profiles)
        self._validate_unique()

    @property
    def profiles(self) -> tuple[PolicyProfile, ...]:
        return tuple(self._profiles)

    def replace(self, profiles: Iterable[PolicyProfile]) -> None:
        self._profiles = list(profiles)
        self._validate_unique()

    def _validate_unique(self) -> None:
        seen: set[tuple[str, int]] = set()
        for profile in self._profiles:
            key = (profile.jurisdiction_id, int(profile.profile_version))
            if key in seen:
                raise ValueError(f"duplicate canonical policy profile: {key}")
            seen.add(key)

    def resolve(self, *, jurisdiction_id: str, period_start_time: int) -> PolicyProfile:
        jurisdiction_profiles = [
            profile for profile in self._profiles if profile.jurisdiction_id == str(jurisdiction_id)
        ]
        if not jurisdiction_profiles:
            raise ValueError(f"unknown policy jurisdiction: {jurisdiction_id}")

        floor = max(int(profile.min_accepted_version) for profile in jurisdiction_profiles)
        candidates = [
            profile
            for profile in jurisdiction_profiles
            if profile.revoked_at is None
            and int(profile.profile_version) >= floor
            and int(profile.valid_from) <= int(period_start_time) < int(profile.valid_to)
        ]
        if not candidates:
            raise ValueError("no active canonical policy profile for billing period")
        profile = max(candidates, key=lambda item: int(item.profile_version))
        profile.assert_active_for(
            jurisdiction_id=str(jurisdiction_id), period_start_time=int(period_start_time)
        )
        return profile


def _load_tariff_artifact(path: Path) -> TariffTable:
    raw = json.loads(path.read_text(encoding="utf-8"))
    tariff = TariffTable(
        tariff_version=int(raw["tariff_version"]),
        grid_w=int(raw["grid_w"]),
        cell_zones={int(key): int(value) for key, value in raw["cell_zones"].items()},
        zone_rates_cents_per_m={
            int(key): int(value) for key, value in raw["zone_rates_cents_per_m"].items()
        },
    )
    declared_tree_fields = {"tree_depth", "tariff_root"}
    present_tree_fields = declared_tree_fields.intersection(raw)
    if present_tree_fields and present_tree_fields != declared_tree_fields:
        raise ValueError("canonical tariff artifact must declare tree_depth and tariff_root together")
    if present_tree_fields:
        declared_root = int(raw["tariff_root"])
        computed_root = int(tariff.root(int(raw["tree_depth"])))
        if declared_root != computed_root:
            raise ValueError("canonical tariff artifact declared root mismatch")
    if "max_zone_rate_cents_per_m" in raw and int(raw["max_zone_rate_cents_per_m"]) != int(
        tariff.max_zone_rate_cents_per_m
    ):
        raise ValueError("canonical tariff artifact declared maximum rate mismatch")
    return tariff


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_profile_local_artifacts(profile: PolicyProfile, *, base_dir: Path) -> None:
    vkey_path = Path(profile.verification_key_path)
    if not vkey_path.is_absolute():
        vkey_path = base_dir / vkey_path
    if not vkey_path.is_file():
        raise ValueError(f"canonical verification key is missing: {vkey_path}")
    if sha256_file(vkey_path) != profile.verification_key_hash:
        raise ValueError("canonical verification key hash mismatch")

    if profile.tariff_artifact_path:
        tariff_path = Path(profile.tariff_artifact_path)
        if not tariff_path.is_absolute():
            tariff_path = base_dir / tariff_path
        if not tariff_path.is_file():
            raise ValueError(f"canonical tariff artifact is missing: {tariff_path}")
        profile.assert_tariff_matches(_load_tariff_artifact(tariff_path))


def load_policy_profiles(directory: Path) -> PolicyRegistry:
    profiles: list[PolicyProfile] = []
    if not directory.is_dir():
        return PolicyRegistry()
    for path in sorted(directory.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("domain_sep") != POLICY_PROFILE_DOMAIN:
            continue
        profile = PolicyProfile.from_dict(raw)
        validate_profile_local_artifacts(profile, base_dir=directory)
        profiles.append(profile)
    return PolicyRegistry(profiles)
