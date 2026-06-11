from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from common.poseidon2_py import _poseidon2


SNARK_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617


SETTLEMENT_FIX_DOMAIN = "tsip_settlement_receiver_fix_v1"
SETTLEMENT_PUBLIC_DOMAIN = "tsip_settlement_public_v1"
SETTLEMENT_ROOT_ATTESTATION_DOMAIN = "tsip_settlement_receiver_root_attestation_v1"
SETTLEMENT_MAX_DT_SEC = 600
SETTLEMENT_PERIOD_MAX_SEC = 14_400
SETTLEMENT_CAP_POLICY_SQ = 3_000_000_000


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def field_from_bytes(data: bytes) -> int:
    return int.from_bytes(hashlib.sha256(data).digest(), "big") % SNARK_FIELD


def field_from_text(value: str) -> int:
    return field_from_bytes(str(value).encode("utf-8"))


def canonical_month_window(month_id: str | int) -> dict[str, int]:
    raw = str(month_id)
    if len(raw) == 7 and raw[4] == "-":
        year = int(raw[:4])
        month = int(raw[5:])
    elif len(raw) == 6:
        year = int(raw[:4])
        month = int(raw[4:])
    else:
        raise ValueError("month_id must use YYYY-MM or YYYYMM format")
    if not 1 <= month <= 12:
        raise ValueError("month_id month must be between 01 and 12")
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    start = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime(next_year, next_month, 1, tzinfo=timezone.utc).timestamp())
    return {
        "month_id": year * 100 + month,
        "month_start_time": start,
        "month_end_time": end,
    }


def month_window_from_period_start(period_start_unix: int) -> tuple[int, int, int]:
    """Return the UTC billing month and its half-open window for a period start."""

    dt = datetime.fromtimestamp(int(period_start_unix), tz=timezone.utc)
    month = canonical_month_window(dt.year * 100 + dt.month)
    return int(month["month_id"]), int(month["month_start_time"]), int(month["month_end_time"])


def poseidon_chain(values: list[int]) -> int:
    state = 0
    for value in values:
        state = int(_poseidon2(int(state), int(value) % SNARK_FIELD))
    return int(state)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "==")


def make_device_attestation_commitment(public_key_bytes: bytes) -> str:
    """Return the attestation commitment string for a given Ed25519 public key.

    This string is stored verbatim in the public statement and fed into
    field_from_text() to produce the dac_field value bound into every fixCommit.
    The charger must independently compute the same value from its device registry
    and reject any submission whose device_attestation_commitment does not match.
    """
    return _b64url(public_key_bytes)


def compute_public_statement_commitment(public_statement: dict[str, Any]) -> str:
    """Return the canonical commitment over a public statement body."""

    body = dict(public_statement)
    body.pop("statement_commitment", None)
    return str(field_from_text(canonical_json(body)))


def verify_public_statement_commitment(public_statement: dict[str, Any]) -> bool:
    return str(public_statement.get("statement_commitment", "")) == compute_public_statement_commitment(public_statement)


def receiver_root_attestation_payload(*, public_statement: dict[str, Any], device_id: str) -> dict[str, Any]:
    return {
        "domain_sep": SETTLEMENT_ROOT_ATTESTATION_DOMAIN,
        "device_id": str(device_id),
        "period_id": str(public_statement["period_id"]),
        "receiver_fix_root": str(public_statement["receiver_fix_root"]),
        "device_attestation_commitment": str(public_statement["device_attestation_commitment"]),
        "statement_commitment": str(public_statement["statement_commitment"]),
    }


def sign_receiver_root_attestation(
    *,
    public_statement: dict[str, Any],
    device_id: str,
    private_key_bytes: bytes,
) -> dict[str, str]:
    """Sign the receiver root and public-statement commitment.

    This is the proof-only submission gate: the charger verifies this signature
    against the registered device key instead of receiving every raw fix.
    """

    payload = receiver_root_attestation_payload(public_statement=public_statement, device_id=device_id)
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    sig = private_key.sign(canonical_json(payload).encode("utf-8"))
    return {"device_id": str(device_id), "signature": _b64url(sig)}


def verify_receiver_root_attestation(
    *,
    public_statement: dict[str, Any],
    attestation: dict[str, Any],
    public_key_bytes: bytes,
) -> bool:
    try:
        device_id = str(attestation["device_id"])
        sig = _b64url_decode(str(attestation["signature"]))
        payload = receiver_root_attestation_payload(public_statement=public_statement, device_id=device_id)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        public_key.verify(sig, canonical_json(payload).encode("utf-8"))
        return True
    except (InvalidSignature, Exception):
        return False


@dataclass(frozen=True)
class ReceiverFix:
    device_id: str
    period_id: str
    fix_seq: int
    auth_gnss_time: int
    cell_x: int
    cell_y: int
    osnma_status: str
    odometer_reading_m: int
    nonce: str
    receiver_sig: str = ""

    def signed_payload(self) -> dict[str, Any]:
        return {
            "domain_sep": SETTLEMENT_FIX_DOMAIN,
            "device_id": self.device_id,
            "period_id": self.period_id,
            "fix_seq": int(self.fix_seq),
            "auth_gnss_time": int(self.auth_gnss_time),
            "cell_x": int(self.cell_x),
            "cell_y": int(self.cell_y),
            "osnma_status": str(self.osnma_status),
            "odometer_reading_m": int(self.odometer_reading_m),
            "nonce": str(self.nonce),
        }

    def to_dict(self) -> dict[str, Any]:
        out = self.signed_payload()
        out["receiver_sig"] = self.receiver_sig
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReceiverFix":
        return cls(
            device_id=str(data["device_id"]),
            period_id=str(data["period_id"]),
            fix_seq=int(data["fix_seq"]),
            auth_gnss_time=int(data["auth_gnss_time"]),
            cell_x=int(data["cell_x"]),
            cell_y=int(data["cell_y"]),
            osnma_status=str(data["osnma_status"]),
            odometer_reading_m=int(data["odometer_reading_m"]),
            nonce=str(data["nonce"]),
            receiver_sig=str(data.get("receiver_sig", "")),
        )


def sign_receiver_fix(fix: ReceiverFix, private_key_bytes: bytes) -> ReceiverFix:
    """Sign a ReceiverFix with an Ed25519 private key (raw 32-byte seed)."""
    body = canonical_json(fix.signed_payload()).encode("utf-8")
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    sig = private_key.sign(body)
    return ReceiverFix(**{**fix.__dict__, "receiver_sig": _b64url(sig)})


def verify_receiver_fix_signature(fix: ReceiverFix, public_key_bytes: bytes) -> bool:
    """Verify a ReceiverFix Ed25519 signature against the device's public key (raw 32 bytes)."""
    if not fix.receiver_sig:
        return False
    try:
        sig = _b64url_decode(fix.receiver_sig)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        body = canonical_json(fix.signed_payload()).encode("utf-8")
        public_key.verify(sig, body)
        return True
    except (InvalidSignature, Exception):
        return False


def compute_fix_commitment(fix: ReceiverFix, *, dac_field: int = 0) -> int:
    return poseidon_chain(
        [
            dac_field,
            field_from_text(fix.period_id),
            int(fix.fix_seq),
            int(fix.auth_gnss_time),
            int(fix.cell_x),
            int(fix.cell_y),
            int(fix.odometer_reading_m),
            field_from_text(fix.nonce),
        ]
    )


def compute_receiver_fix_root_for_circuit(fixes: list[ReceiverFix], *, dac_field: int = 0) -> int:
    """Return the root bound by the circuit's signature-free fix commitments."""

    return commitment_chain_root([compute_fix_commitment(fix, dac_field=dac_field) for fix in fixes])


def compute_receiver_fix_root_for_submission(fixes: list[ReceiverFix], *, dac_field: int = 0) -> int:
    """Return the submission root after signatures are verified separately."""

    return compute_receiver_fix_root_for_circuit(fixes, dac_field=dac_field)


def merkle_parent(left: int, right: int) -> int:
    return int(_poseidon2(int(left) % SNARK_FIELD, int(right) % SNARK_FIELD))


def merkleize(leaves: list[int]) -> int:
    if not leaves:
        return 0
    level = [int(x) % SNARK_FIELD for x in leaves]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [merkle_parent(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return int(level[0])


def merkleize_fixed_depth(leaves: list[int], depth: int) -> int:
    if depth < 0:
        raise ValueError("merkle depth must be non-negative")
    target = 1 << int(depth)
    if len(leaves) > target:
        raise ValueError("too many leaves for fixed Merkle depth")
    padded = [int(x) % SNARK_FIELD for x in leaves]
    if not padded:
        padded = [0]
    while len(padded) < target:
        padded.append(padded[-1])
    return merkleize(padded)


def commitment_chain_root(leaves: list[int]) -> int:
    state = 0
    for leaf in leaves:
        state = int(_poseidon2(int(state), int(leaf) % SNARK_FIELD))
    return int(state)


def merkle_path(leaves: list[int], index: int) -> list[dict[str, int]]:
    if index < 0 or index >= len(leaves):
        raise ValueError("merkle path index out of range")
    path: list[dict[str, int]] = []
    idx = int(index)
    level = [int(x) % SNARK_FIELD for x in leaves]
    while len(level) > 1:
        original_len = len(level)
        if len(level) % 2:
            level.append(level[-1])
        sibling = idx ^ 1
        if sibling >= original_len:
            sibling = idx
        path.append({"sibling": int(level[sibling]), "is_right": int(idx % 2 == 1)})
        idx //= 2
        level = [merkle_parent(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return path


def merkle_path_fixed_depth(leaves: list[int], index: int, depth: int) -> list[dict[str, int]]:
    target = 1 << int(depth)
    if len(leaves) > target:
        raise ValueError("too many leaves for fixed Merkle depth")
    padded = [int(x) % SNARK_FIELD for x in leaves]
    if not padded:
        padded = [0]
    while len(padded) < target:
        padded.append(padded[-1])
    return merkle_path(padded, index)


def verify_merkle_path(leaf: int, path: list[dict[str, int]], root: int) -> bool:
    acc = int(leaf) % SNARK_FIELD
    for step in path:
        sibling = int(step["sibling"]) % SNARK_FIELD
        if int(step.get("is_right", 0)):
            acc = merkle_parent(sibling, acc)
        else:
            acc = merkle_parent(acc, sibling)
    return int(acc) == int(root) % SNARK_FIELD


@dataclass(frozen=True)
class TariffTable:
    tariff_version: int
    grid_w: int
    cell_zones: dict[int, int]
    zone_rates_cents_per_m: dict[int, int]

    def zone_for_cell(self, cell_idx: int) -> int:
        try:
            return int(self.cell_zones[int(cell_idx)])
        except KeyError as e:
            raise ValueError(f"missing tariff zone for cell {cell_idx}") from e

    def rate_for_zone(self, zone_id: int) -> int:
        try:
            return int(self.zone_rates_cents_per_m[int(zone_id)])
        except KeyError as e:
            raise ValueError(f"missing tariff rate for zone {zone_id}") from e

    @property
    def max_zone_rate_cents_per_m(self) -> int:
        if not self.zone_rates_cents_per_m:
            raise ValueError("tariff has no zone rates")
        return max(int(v) for v in self.zone_rates_cents_per_m.values())

    def cell_index(self, cell_x: int, cell_y: int) -> int:
        return int(cell_y) * int(self.grid_w) + int(cell_x)

    def leaf_for_cell(self, cell_idx: int) -> int:
        zone_id = self.zone_for_cell(cell_idx)
        return poseidon_chain(
            [
                int(self.tariff_version),
                int(cell_idx),
                int(zone_id),
                self.rate_for_zone(zone_id),
            ]
        )

    def leaves(self) -> list[int]:
        return [self.leaf_for_cell(cell_idx) for cell_idx in sorted(self.cell_zones)]

    def root(self, depth: int | None = None) -> int:
        leaves = self.leaves()
        return merkleize(leaves) if depth is None else merkleize_fixed_depth(leaves, depth)

    def path_for_cell(self, cell_idx: int, depth: int | None = None) -> list[dict[str, int]]:
        ordered = sorted(self.cell_zones)
        idx = ordered.index(int(cell_idx))
        leaves = self.leaves()
        return merkle_path(leaves, idx) if depth is None else merkle_path_fixed_depth(leaves, idx, depth)


def verify_fix_sequence(
    fixes: list[ReceiverFix],
    *,
    public_key_bytes: bytes,
    period_id: str,
) -> None:
    if len(fixes) < 2:
        raise ValueError("at least two receiver fixes are required")
    seen_nonce: set[str] = set()
    prev_seq: int | None = None
    prev_time: int | None = None
    prev_odo: int | None = None
    for fix in fixes:
        if fix.period_id != period_id:
            raise ValueError("fix period mismatch")
        if str(fix.osnma_status).lower() != "authenticated":
            raise ValueError("fix is not OSNMA-authenticated")
        if fix.nonce in seen_nonce:
            raise ValueError("duplicate receiver nonce")
        if not verify_receiver_fix_signature(fix, public_key_bytes):
            raise ValueError("invalid receiver signature")
        if prev_seq is not None and int(fix.fix_seq) <= prev_seq:
            raise ValueError("fix sequence must be strictly increasing")
        if prev_time is not None and int(fix.auth_gnss_time) <= prev_time:
            raise ValueError("authenticated GNSS time must be strictly increasing")
        if prev_odo is not None and int(fix.odometer_reading_m) < prev_odo:
            raise ValueError("odometer readings must be monotonic")
        seen_nonce.add(fix.nonce)
        prev_seq = int(fix.fix_seq)
        prev_time = int(fix.auth_gnss_time)
        prev_odo = int(fix.odometer_reading_m)


def fee_for_period(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int = SETTLEMENT_MAX_DT_SEC,
    fallback_rate_cents_per_m: int | None = None,
    dac_field: int = 0,
) -> dict[str, Any]:
    if len(fixes) < 2:
        raise ValueError("at least two receiver fixes are required")
    total_fee = 0
    total_distance = 0
    fallback_distance = 0
    fallback_intervals = 0
    private_zone_distance: dict[int, int] = {}
    interval_commitments: list[int] = []
    for prev, curr in zip(fixes, fixes[1:]):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        cell_idx = tariff.cell_index(prev.cell_x, prev.cell_y)
        interval = fee_for_interval_values(
            dt_sec=dt,
            odo_delta_m=odo_delta,
            cell_idx=cell_idx,
            tariff=tariff,
            cadence_sec=cadence_sec,
            tier_vmax_mps=tier_vmax_mps,
            max_dt_sec=max_dt_sec,
            fallback_rate_cents_per_m=fallback_rate_cents_per_m,
        )
        zone_id = int(interval["zone_id"])
        zone_rate = int(interval["zone_rate_cents_per_m"])
        fee = int(interval["fee_cents"])
        if bool(interval["fallback"]):
            fallback_distance += int(interval["charged_distance_m"])
            fallback_intervals += 1
        else:
            private_zone_distance[zone_id] = private_zone_distance.get(zone_id, 0) + odo_delta
        total_distance += odo_delta
        total_fee += fee
        interval_commitments.append(
            poseidon_chain(
                [
                    compute_fix_commitment(prev, dac_field=dac_field),
                    compute_fix_commitment(curr, dac_field=dac_field),
                    int(odo_delta),
                    int(zone_id),
                    int(zone_rate),
                    int(fee),
                    int(dt > int(cadence_sec)),
                ]
            )
        )
    return {
        "total_fee_cents": int(total_fee),
        "total_distance_m": int(total_distance),
        "fallback_distance_m": int(fallback_distance),
        "fallback_intervals": int(fallback_intervals),
        "private_zone_distance_m": dict(sorted(private_zone_distance.items())),
        "interval_commitment_root": commitment_chain_root(interval_commitments),
    }


def fee_for_interval_values(
    *,
    dt_sec: int,
    odo_delta_m: int,
    cell_idx: int,
    tariff: TariffTable,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int | None = SETTLEMENT_MAX_DT_SEC,
    fallback_rate_cents_per_m: int | None = None,
    fallback_override: bool | None = None,
) -> dict[str, int | bool]:
    dt = int(dt_sec)
    odo_delta = int(odo_delta_m)
    if dt <= 0:
        raise ValueError("non-positive authenticated time delta")
    if max_dt_sec is not None and dt > int(max_dt_sec):
        raise ValueError("authenticated time delta exceeds maximum")
    if odo_delta < 0:
        raise ValueError("negative odometer delta")
    if odo_delta > dt * int(tier_vmax_mps):
        raise ValueError("odometer delta exceeds tier speed budget")
    zone_id = tariff.zone_for_cell(int(cell_idx))
    zone_rate = tariff.rate_for_zone(zone_id)
    fallback = bool(dt > int(cadence_sec) if fallback_override is None else fallback_override)
    if fallback:
        charged_distance = int(math.ceil(dt * int(tier_vmax_mps)))
        rate = tariff.max_zone_rate_cents_per_m if fallback_rate_cents_per_m is None else int(fallback_rate_cents_per_m)
        fee = charged_distance * rate
    else:
        charged_distance = odo_delta
        fee = odo_delta * zone_rate
    return {
        "fee_cents": int(fee),
        "charged_distance_m": int(charged_distance),
        "fallback": bool(fallback),
        "zone_id": int(zone_id),
        "zone_rate_cents_per_m": int(zone_rate),
        "fallback_rate_cents_per_m": int(
            tariff.max_zone_rate_cents_per_m if fallback_rate_cents_per_m is None else fallback_rate_cents_per_m
        ),
    }


def build_period_public_statement(
    *,
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    period_id: str,
    month_id: str,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int = SETTLEMENT_MAX_DT_SEC,
    mode_vmax_sq: int | None = None,
    cap_policy_sq: int = SETTLEMENT_CAP_POLICY_SQ,
    device_attestation_commitment: str,
    reveal_total_miles: bool = True,
    tariff_tree_depth: int | None = None,
) -> dict[str, Any]:
    dac_field = field_from_text(str(device_attestation_commitment))
    period_start_time = int(fixes[0].auth_gnss_time)
    period_end_time = int(fixes[-1].auth_gnss_time)
    period_span = period_end_time - period_start_time
    if not 0 < period_span <= SETTLEMENT_PERIOD_MAX_SEC:
        raise ValueError("period span must be positive and at most 14400 seconds")
    month_id_field, month_start_time, month_end_time = month_window_from_period_start(period_start_time)
    requested_month = canonical_month_window(month_id)
    if int(requested_month["month_id"]) != month_id_field:
        raise ValueError("month_id does not match period start")
    fee = fee_for_period(
        fixes,
        tariff,
        cadence_sec=cadence_sec,
        tier_vmax_mps=tier_vmax_mps,
        max_dt_sec=max_dt_sec,
        dac_field=dac_field,
    )
    fix_root = compute_receiver_fix_root_for_submission(fixes, dac_field=dac_field)
    public = {
        "domain_sep": SETTLEMENT_PUBLIC_DOMAIN,
        "period_id": str(period_id),
        "period_id_field": field_from_text(str(period_id)),
        "month_id": str(month_id),
        "month_id_field": month_id_field,
        "month_start_time": month_start_time,
        "month_end_time": month_end_time,
        "period_start_time": period_start_time,
        "period_end_time": period_end_time,
        "max_dt_sec": int(max_dt_sec),
        "tariff_version": int(tariff.tariff_version),
        "cadence_sec": int(cadence_sec),
        "tier_vmax_mps": int(tier_vmax_mps),
        "tier_vmax_sq": int(tier_vmax_mps) * int(tier_vmax_mps),
        "mode_vmax_sq": int(mode_vmax_sq) if mode_vmax_sq is not None else int(tier_vmax_mps) * int(tier_vmax_mps),
        "cap_policy_sq": int(cap_policy_sq),
        "max_zone_rate_cents_per_m": int(tariff.max_zone_rate_cents_per_m),
        "receiver_fix_root": str(fix_root),
        "tariff_root": str(tariff.root(tariff_tree_depth)),
        "interval_commitment_root": str(fee["interval_commitment_root"]),
        "device_attestation_commitment": str(device_attestation_commitment),
        "total_fee_cents": int(fee["total_fee_cents"]),
        "fallback_intervals": int(fee["fallback_intervals"]),
    }
    if reveal_total_miles:
        public["total_distance_m"] = int(fee["total_distance_m"])
    public["statement_commitment"] = compute_public_statement_commitment(public)
    return public


def verify_period_submission(
    *,
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    public_statement: dict[str, Any],
    public_key_bytes: bytes,
    cadence_sec: int,
    tier_vmax_mps: int,
    max_dt_sec: int = SETTLEMENT_MAX_DT_SEC,
    tariff_tree_depth: int | None = None,
) -> dict[str, Any]:
    period_id = str(public_statement["period_id"])
    verify_fix_sequence(fixes, public_key_bytes=public_key_bytes, period_id=period_id)
    expected = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id=period_id,
        month_id=str(public_statement["month_id"]),
        cadence_sec=cadence_sec,
        tier_vmax_mps=tier_vmax_mps,
        max_dt_sec=max_dt_sec,
        device_attestation_commitment=str(public_statement["device_attestation_commitment"]),
        reveal_total_miles="total_distance_m" in public_statement,
        tariff_tree_depth=tariff_tree_depth,
    )
    for key, value in expected.items():
        if public_statement.get(key) != value:
            raise ValueError(f"public statement mismatch: {key}")
    return expected
