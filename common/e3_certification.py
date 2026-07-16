"""Independent certified core for the WayBill E3 attack experiment.

The frozen model is ``e3-v6-fixed-odo/v1``.  An attacker may choose only the
claimed position and tariff cell.  Device/period identity, sequence, time, and
every odometer reading are immutable.  In particular, a distance bucket is a
grid construction parameter; it is never an odometer or feasibility tolerance.

The module deliberately does not depend on ``eval_harness`` or its runner.  It
provides three separate pieces of evidence for a maximum-underpayment problem:

* a strictly checked feasible centre-path, optionally strengthened by other
  explicitly supplied and strictly checked feasible paths (a lower bound),
* an independent exhaustive oracle for small original integer-point instances, and
* a rectangle-projection relaxation (an upper bound).

All coordinates are integers in the profile's coordinate unit.  Monetary
quantities are integer cents and distances used for billing are integer metres.
This makes the binding and billing checks exact rather than epsilon based.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
import tracemalloc
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from math import isqrt
from pathlib import Path
from typing import Any, Mapping, Sequence


MODEL_ID = "e3-v6-fixed-odo/v1"
RECEIPT_SCHEMA = "waybill.e3.bound/v1"
RECT_RELAXATION_ID = "R_rect/v1"
INDEPENDENT_RELAXATION_ID = "R_ind/v1"


class ViolationCode(StrEnum):
    """Stable machine-readable strict-checker failure codes."""

    MODEL_BINDING = "MODEL_BINDING"
    INSTANCE_HASH = "INSTANCE_HASH"
    PROFILE_HASH = "PROFILE_HASH"
    TARIFF_HASH = "TARIFF_HASH"
    DATA_HASH = "DATA_HASH"
    CODE_HASH = "CODE_HASH"
    FIX_COUNT = "FIX_COUNT"
    SEGMENT_COUNT = "SEGMENT_COUNT"
    DEVICE_BINDING = "DEVICE_BINDING"
    PERIOD_BINDING = "PERIOD_BINDING"
    SEQ_BINDING = "SEQ_BINDING"
    TIME_BINDING = "TIME_BINDING"
    ODO_BINDING = "ODO_BINDING"
    POSITION_VALID = "POSITION_VALID"
    POSITION_TYPE = "POSITION_TYPE"
    CELL_UNKNOWN = "CELL_UNKNOWN"
    PAYLOAD_CELL_BINDING = "PAYLOAD_CELL_BINDING"
    RADIUS = "RADIUS"
    CONTINUITY = "CONTINUITY"
    CADENCE_BINDING = "CADENCE_BINDING"
    MAX_DT = "MAX_DT"
    ODO_DELTA_BINDING = "ODO_DELTA_BINDING"
    ODO_MONOTONIC = "ODO_MONOTONIC"
    SPEED_CAP = "SPEED_CAP"
    SEGMENT_CELL_BINDING = "SEGMENT_CELL_BINDING"
    RATE_BINDING = "RATE_BINDING"
    FEE_BINDING = "FEE_BINDING"
    OBJECTIVE_BINDING = "OBJECTIVE_BINDING"


def _require_int(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True, order=True)
class Point:
    """An exact point in integer profile coordinate units."""

    x: int
    y: int

    def to_dict(self) -> dict[str, int]:
        return {"x": int(self.x), "y": int(self.y)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Point":
        return cls(x=int(value["x"]), y=int(value["y"]))


@dataclass(frozen=True)
class Rectangle:
    """A closed axis-aligned tariff-cell rectangle."""

    x_min: int
    y_min: int
    x_max: int
    y_max: int

    @property
    def center(self) -> Point:
        # Integral centres keep centre witnesses and all geometry exact.  The
        # instance validator rejects cells for which this is not possible.
        return Point((int(self.x_min) + int(self.x_max)) // 2, (int(self.y_min) + int(self.y_max)) // 2)

    def contains(self, point: Point) -> bool:
        return (
            int(self.x_min) <= int(point.x) <= int(self.x_max)
            and int(self.y_min) <= int(point.y) <= int(self.y_max)
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "x_min": int(self.x_min),
            "y_min": int(self.y_min),
            "x_max": int(self.x_max),
            "y_max": int(self.y_max),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Rectangle":
        return cls(
            x_min=int(value["x_min"]),
            y_min=int(value["y_min"]),
            x_max=int(value["x_max"]),
            y_max=int(value["y_max"]),
        )


@dataclass(frozen=True)
class TariffCell:
    cell_id: str
    rectangle: Rectangle
    rate_cents_per_m: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": str(self.cell_id),
            "rectangle": self.rectangle.to_dict(),
            "rate_cents_per_m": int(self.rate_cents_per_m),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TariffCell":
        return cls(
            cell_id=str(value["cell_id"]),
            rectangle=Rectangle.from_dict(value["rectangle"]),
            rate_cents_per_m=int(value["rate_cents_per_m"]),
        )


@dataclass(frozen=True)
class E3Profile:
    cadence_sec: int
    max_dt_sec: int
    tier_vmax_mps: int
    relay_radius_units: int
    r_max_cents_per_m: int
    coordinate_scale_per_m: int = 1
    profile_id: str = "waybill-v6-fixed-odo"
    model_id: str = MODEL_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": str(self.profile_id),
            "model_id": str(self.model_id),
            "cadence_sec": int(self.cadence_sec),
            "max_dt_sec": int(self.max_dt_sec),
            "tier_vmax_mps": int(self.tier_vmax_mps),
            "relay_radius_units": int(self.relay_radius_units),
            "r_max_cents_per_m": int(self.r_max_cents_per_m),
            "coordinate_scale_per_m": int(self.coordinate_scale_per_m),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "E3Profile":
        return cls(
            profile_id=str(value.get("profile_id", "waybill-v6-fixed-odo")),
            model_id=str(value.get("model_id", MODEL_ID)),
            cadence_sec=int(value["cadence_sec"]),
            max_dt_sec=int(value["max_dt_sec"]),
            tier_vmax_mps=int(value["tier_vmax_mps"]),
            relay_radius_units=int(value["relay_radius_units"]),
            r_max_cents_per_m=int(value["r_max_cents_per_m"]),
            coordinate_scale_per_m=int(value.get("coordinate_scale_per_m", 1)),
        )


@dataclass(frozen=True)
class TrueFix:
    device_id: str
    period_id: str
    fix_seq: int
    auth_time_sec: int
    odometer_m: int
    true_point: Point
    true_cell_id: str

    def immutable_dict(self) -> dict[str, Any]:
        return {
            "device_id": str(self.device_id),
            "period_id": str(self.period_id),
            "fix_seq": int(self.fix_seq),
            "auth_time_sec": int(self.auth_time_sec),
            "odometer_m": int(self.odometer_m),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.immutable_dict(),
            "true_point": self.true_point.to_dict(),
            "true_cell_id": str(self.true_cell_id),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrueFix":
        return cls(
            device_id=str(value["device_id"]),
            period_id=str(value["period_id"]),
            fix_seq=int(value["fix_seq"]),
            auth_time_sec=int(value.get("auth_time_sec", value.get("auth_gnss_time"))),
            odometer_m=int(value.get("odometer_m", value.get("odometer_reading_m"))),
            true_point=Point.from_dict(value["true_point"]),
            true_cell_id=str(value["true_cell_id"]),
        )


@dataclass(frozen=True)
class ClaimedFix:
    device_id: str
    period_id: str
    fix_seq: int
    auth_time_sec: int
    odometer_m: int
    claimed_point: Point
    claimed_cell_id: str
    position_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": str(self.device_id),
            "period_id": str(self.period_id),
            "fix_seq": int(self.fix_seq),
            "auth_time_sec": int(self.auth_time_sec),
            "odometer_m": int(self.odometer_m),
            "claimed_point": self.claimed_point.to_dict(),
            "claimed_cell_id": str(self.claimed_cell_id),
            "position_valid": bool(self.position_valid),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimedFix":
        return cls(
            device_id=str(value["device_id"]),
            period_id=str(value["period_id"]),
            fix_seq=int(value["fix_seq"]),
            auth_time_sec=int(value.get("auth_time_sec", value.get("auth_gnss_time"))),
            odometer_m=int(value.get("odometer_m", value.get("odometer_reading_m"))),
            claimed_point=Point.from_dict(value["claimed_point"]),
            claimed_cell_id=str(value["claimed_cell_id"]),
            position_valid=value.get("position_valid", False),
        )


@dataclass(frozen=True)
class ClaimSegment:
    segment_index: int
    dt_sec: int
    delta_odometer_m: int
    source_cell_id: str
    outage: bool
    applied_rate_cents_per_m: int
    fee_cents: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_index": int(self.segment_index),
            "dt_sec": int(self.dt_sec),
            "delta_odometer_m": int(self.delta_odometer_m),
            "source_cell_id": str(self.source_cell_id),
            "outage": bool(self.outage),
            "applied_rate_cents_per_m": int(self.applied_rate_cents_per_m),
            "fee_cents": int(self.fee_cents),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClaimSegment":
        return cls(
            segment_index=int(value["segment_index"]),
            dt_sec=int(value["dt_sec"]),
            delta_odometer_m=int(value["delta_odometer_m"]),
            source_cell_id=str(value["source_cell_id"]),
            outage=value["outage"],
            applied_rate_cents_per_m=int(value["applied_rate_cents_per_m"]),
            fee_cents=int(value["fee_cents"]),
        )


@dataclass(frozen=True)
class E3Claim:
    model_id: str
    instance_hash: str
    profile_hash: str
    tariff_hash: str
    data_hash: str
    code_hash: str
    fixes: tuple[ClaimedFix, ...]
    segments: tuple[ClaimSegment, ...]
    fee_cents: int
    underpayment_cents: int
    solver: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": str(self.model_id),
            "instance_hash": str(self.instance_hash),
            "profile_hash": str(self.profile_hash),
            "tariff_hash": str(self.tariff_hash),
            "data_hash": str(self.data_hash),
            "code_hash": str(self.code_hash),
            "solver": str(self.solver),
            "fixes": [fix.to_dict() for fix in self.fixes],
            "segments": [segment.to_dict() for segment in self.segments],
            "fee_cents": int(self.fee_cents),
            "underpayment_cents": int(self.underpayment_cents),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "E3Claim":
        return cls(
            model_id=str(value["model_id"]),
            instance_hash=str(value["instance_hash"]),
            profile_hash=str(value["profile_hash"]),
            tariff_hash=str(value["tariff_hash"]),
            data_hash=str(value["data_hash"]),
            code_hash=str(value["code_hash"]),
            solver=str(value.get("solver", "external")),
            fixes=tuple(ClaimedFix.from_dict(item) for item in value.get("fixes", [])),
            segments=tuple(ClaimSegment.from_dict(item) for item in value.get("segments", [])),
            fee_cents=int(value["fee_cents"]),
            underpayment_cents=int(value["underpayment_cents"]),
        )


@dataclass(frozen=True)
class E3Instance:
    instance_id: str
    dataset: str
    profile: E3Profile
    tariff_cells: tuple[TariffCell, ...]
    fixes: tuple[TrueFix, ...]
    bucket_size_units: int | None = None

    @cached_property
    def cell_map(self) -> dict[str, TariffCell]:
        return {str(cell.cell_id): cell for cell in self.tariff_cells}

    def tariff_dict(self) -> dict[str, Any]:
        return {
            "cells": [cell.to_dict() for cell in sorted(self.tariff_cells, key=lambda item: str(item.cell_id))],
            "r_max_cents_per_m": int(self.profile.r_max_cents_per_m),
        }

    def data_dict(self) -> dict[str, Any]:
        return {
            "dataset": str(self.dataset),
            "fixes": [fix.to_dict() for fix in self.fixes],
        }

    @cached_property
    def profile_hash(self) -> str:
        return sha256_json(self.profile.to_dict())

    @cached_property
    def tariff_hash(self) -> str:
        return sha256_json(self.tariff_dict())

    @cached_property
    def data_hash(self) -> str:
        return sha256_json(self.data_dict())

    @cached_property
    def instance_hash(self) -> str:
        return sha256_json(
            {
                "instance_id": str(self.instance_id),
                "model_id": MODEL_ID,
                "profile_hash": self.profile_hash,
                "tariff_hash": self.tariff_hash,
                "data_hash": self.data_hash,
                "bucket_size_units": self.bucket_size_units,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": str(self.instance_id),
            "dataset": str(self.dataset),
            "model_id": MODEL_ID,
            "bucket_size_units": self.bucket_size_units,
            "profile": self.profile.to_dict(),
            "tariff_cells": [cell.to_dict() for cell in self.tariff_cells],
            "fixes": [fix.to_dict() for fix in self.fixes],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "E3Instance":
        if str(value.get("model_id", MODEL_ID)) != MODEL_ID:
            raise ValueError(f"unsupported model_id: {value.get('model_id')}")
        bucket = value.get("bucket_size_units")
        return cls(
            instance_id=str(value["instance_id"]),
            dataset=str(value.get("dataset", "unknown")),
            profile=E3Profile.from_dict(value["profile"]),
            tariff_cells=tuple(TariffCell.from_dict(item) for item in value["tariff_cells"]),
            fixes=tuple(TrueFix.from_dict(item) for item in value["fixes"]),
            bucket_size_units=None if bucket is None else int(bucket),
        )


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    message: str
    fix_index: int | None = None
    segment_index: int | None = None
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": str(self.code), "message": str(self.message)}
        if self.fix_index is not None:
            result["fix_index"] = int(self.fix_index)
        if self.segment_index is not None:
            result["segment_index"] = int(self.segment_index)
        if self.expected is not None:
            result["expected"] = self.expected
        if self.actual is not None:
            result["actual"] = self.actual
        return result


@dataclass(frozen=True)
class CheckResult:
    accepted: bool
    violations: tuple[Violation, ...]
    computed_fee_cents: int | None
    computed_underpayment_cents: int | None

    @property
    def violation_codes(self) -> tuple[str, ...]:
        return tuple(str(item.code) for item in self.violations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": bool(self.accepted),
            "violation_count": len(self.violations),
            "violation_codes": list(self.violation_codes),
            "violations": [item.to_dict() for item in self.violations],
            "computed_fee_cents": self.computed_fee_cents,
            "computed_underpayment_cents": self.computed_underpayment_cents,
        }


@dataclass(frozen=True)
class SolverStats:
    runtime_ns: int
    states: int
    transitions: int
    peak_memory_bytes: int
    timeout: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_ns": int(self.runtime_ns),
            "states": int(self.states),
            "transitions": int(self.transitions),
            "peak_memory_bytes": int(self.peak_memory_bytes),
            "timeout": bool(self.timeout),
        }


@dataclass(frozen=True)
class BoundSolution:
    domain: str
    fee_cents: int
    underpayment_cents: int
    cell_path: tuple[str, ...]
    stats: SolverStats
    claim: E3Claim | None = None

    def to_dict(self, *, include_claim: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "domain": str(self.domain),
            "fee_cents": int(self.fee_cents),
            "underpayment_cents": int(self.underpayment_cents),
            "cell_path": list(self.cell_path),
            "stats": self.stats.to_dict(),
        }
        if include_claim and self.claim is not None:
            result["claim"] = self.claim.to_dict()
        return result


@dataclass(frozen=True)
class OracleResult:
    domain: str
    complete: bool
    optimum_fee_cents: int | None
    optimum_underpayment_cents: int | None
    paths_checked: int
    candidate_paths: int
    claim: E3Claim | None
    stats: SolverStats
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": str(self.domain),
            "complete": bool(self.complete),
            "optimum_fee_cents": self.optimum_fee_cents,
            "optimum_underpayment_cents": self.optimum_underpayment_cents,
            "paths_checked": int(self.paths_checked),
            "candidate_paths": int(self.candidate_paths),
            "reason": str(self.reason),
            "witness_hash": None if self.claim is None else sha256_json(self.claim.to_dict()),
            "stats": self.stats.to_dict(),
        }


@dataclass(frozen=True)
class ContainmentReport:
    center_points_checked: int
    center_edges_checked: int
    center_to_continuous: bool
    continuous_to_rectangle: bool
    rectangle_to_independent: bool
    proof_hash: str

    @property
    def valid(self) -> bool:
        return self.center_to_continuous and self.continuous_to_rectangle and self.rectangle_to_independent

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": "F_center subseteq F_continuous subseteq R_rect subseteq R_ind",
            "valid": bool(self.valid),
            "center_points_checked": int(self.center_points_checked),
            "center_edges_checked": int(self.center_edges_checked),
            "center_to_continuous": bool(self.center_to_continuous),
            "continuous_to_rectangle": bool(self.continuous_to_rectangle),
            "rectangle_to_independent": bool(self.rectangle_to_independent),
            "proof_hash": str(self.proof_hash),
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def implementation_code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


_RECT_PROOF = {
    "relaxation_id": RECT_RELAXATION_ID,
    "model_id": MODEL_ID,
    "statement": "F_center subseteq F_continuous subseteq R_rect subseteq R_ind",
    "projection": {
        "node": "distance(true_point_i, rectangle(cell_i)) <= rho",
        "edge": "distance(rectangle(cell_i), rectangle(cell_i+1)) <= vmax * dt_i",
    },
    "relaxed_constraint": (
        "R_rect checks adjacent rectangle projections independently and removes the requirement that one "
        "payload point inside an intermediate cell simultaneously witnesses both adjacent edges."
    ),
}
RECT_RELAXATION_PROOF_HASH = sha256_json(_RECT_PROOF)


def squared_distance(left: Point, right: Point) -> int:
    dx = int(left.x) - int(right.x)
    dy = int(left.y) - int(right.y)
    return dx * dx + dy * dy


def point_rectangle_distance_sq(point: Point, rectangle: Rectangle) -> int:
    if int(point.x) < int(rectangle.x_min):
        dx = int(rectangle.x_min) - int(point.x)
    elif int(point.x) > int(rectangle.x_max):
        dx = int(point.x) - int(rectangle.x_max)
    else:
        dx = 0
    if int(point.y) < int(rectangle.y_min):
        dy = int(rectangle.y_min) - int(point.y)
    elif int(point.y) > int(rectangle.y_max):
        dy = int(point.y) - int(rectangle.y_max)
    else:
        dy = 0
    return dx * dx + dy * dy


def rectangle_distance_sq(left: Rectangle, right: Rectangle) -> int:
    if int(left.x_max) < int(right.x_min):
        dx = int(right.x_min) - int(left.x_max)
    elif int(right.x_max) < int(left.x_min):
        dx = int(left.x_min) - int(right.x_max)
    else:
        dx = 0
    if int(left.y_max) < int(right.y_min):
        dy = int(right.y_min) - int(left.y_max)
    elif int(right.y_max) < int(left.y_min):
        dy = int(left.y_min) - int(right.y_max)
    else:
        dy = 0
    return dx * dx + dy * dy


def validate_instance(instance: E3Instance) -> None:
    """Reject an ill-formed SSOT instance before any solver is run."""

    profile = instance.profile
    if profile.model_id != MODEL_ID:
        raise ValueError(f"profile model_id must be {MODEL_ID}")
    _require_int(profile.cadence_sec, "cadence_sec", minimum=1)
    _require_int(profile.max_dt_sec, "max_dt_sec", minimum=1)
    _require_int(profile.tier_vmax_mps, "tier_vmax_mps", minimum=0)
    _require_int(profile.relay_radius_units, "relay_radius_units", minimum=0)
    _require_int(profile.r_max_cents_per_m, "r_max_cents_per_m", minimum=0)
    _require_int(profile.coordinate_scale_per_m, "coordinate_scale_per_m", minimum=1)
    if instance.bucket_size_units is not None:
        _require_int(instance.bucket_size_units, "bucket_size_units", minimum=1)
    if len(instance.fixes) < 2:
        raise ValueError("an E3 instance requires at least two fixes")
    if not instance.tariff_cells:
        raise ValueError("an E3 instance requires tariff cells")

    seen_cells: set[str] = set()
    maximum_rate = -1
    for cell in instance.tariff_cells:
        cell_id = str(cell.cell_id)
        if not cell_id or cell_id in seen_cells:
            raise ValueError(f"duplicate or empty tariff cell id: {cell_id!r}")
        seen_cells.add(cell_id)
        rectangle = cell.rectangle
        for name, value in rectangle.to_dict().items():
            _require_int(value, f"cell {cell_id} {name}")
        if rectangle.x_min >= rectangle.x_max or rectangle.y_min >= rectangle.y_max:
            raise ValueError(f"cell {cell_id} has an empty rectangle")
        if (rectangle.x_min + rectangle.x_max) % 2 or (rectangle.y_min + rectangle.y_max) % 2:
            raise ValueError(f"cell {cell_id} does not have an integral centre")
        _require_int(cell.rate_cents_per_m, f"cell {cell_id} rate", minimum=0)
        maximum_rate = max(maximum_rate, int(cell.rate_cents_per_m))
    if int(profile.r_max_cents_per_m) != maximum_rate:
        raise ValueError("r_max_cents_per_m must equal the maximum bound tariff rate")

    cells = instance.cell_map
    first = instance.fixes[0]
    device_id = str(first.device_id)
    period_id = str(first.period_id)
    previous: TrueFix | None = None
    for index, fix in enumerate(instance.fixes):
        if not str(fix.device_id) or str(fix.device_id) != device_id:
            raise ValueError(f"fix {index} device_id is not period-consistent")
        if not str(fix.period_id) or str(fix.period_id) != period_id:
            raise ValueError(f"fix {index} period_id is not period-consistent")
        _require_int(fix.fix_seq, f"fix {index} fix_seq", minimum=0)
        _require_int(fix.auth_time_sec, f"fix {index} auth_time_sec")
        _require_int(fix.odometer_m, f"fix {index} odometer_m", minimum=0)
        _require_int(fix.true_point.x, f"fix {index} true_point.x")
        _require_int(fix.true_point.y, f"fix {index} true_point.y")
        cell = cells.get(str(fix.true_cell_id))
        if cell is None:
            raise ValueError(f"fix {index} refers to an unknown true cell")
        if not cell.rectangle.contains(fix.true_point):
            raise ValueError(f"fix {index} true point is outside its tariff cell")
        if previous is not None:
            if int(fix.fix_seq) != int(previous.fix_seq) + 1:
                raise ValueError("fix_seq must be contiguous in the frozen cadence model")
            dt_sec = int(fix.auth_time_sec) - int(previous.auth_time_sec)
            if dt_sec <= 0:
                raise ValueError("authenticated times must be strictly increasing")
            if dt_sec > int(profile.max_dt_sec):
                raise ValueError("authenticated time delta exceeds max_dt_sec")
            delta_odo = int(fix.odometer_m) - int(previous.odometer_m)
            if delta_odo < 0:
                raise ValueError("odometer readings must be monotonic")
            if delta_odo > int(profile.tier_vmax_mps) * dt_sec:
                raise ValueError("odometer delta exceeds the per-segment speed cap")
            cap_units = _continuity_cap_units(instance, dt_sec)
            if squared_distance(previous.true_point, fix.true_point) > cap_units * cap_units:
                raise ValueError("true positions exceed the per-segment continuity cap")
        previous = fix


def _continuity_cap_units(instance: E3Instance, dt_sec: int) -> int:
    return (
        int(instance.profile.tier_vmax_mps)
        * int(instance.profile.coordinate_scale_per_m)
        * int(dt_sec)
    )


def _all_radius_candidates_pairwise_feasible(instance: E3Instance, segment_index: int) -> bool:
    """Return a sufficient exact test that every projected pair passes the edge cap."""

    left = instance.fixes[segment_index]
    right = instance.fixes[segment_index + 1]
    dt_sec = int(right.auth_time_sec) - int(left.auth_time_sec)
    cap_units = _continuity_cap_units(instance, dt_sec)
    radius = int(instance.profile.relay_radius_units)
    margin = cap_units - 2 * radius
    return margin >= 0 and squared_distance(left.true_point, right.true_point) <= margin * margin


def _segment_values(instance: E3Instance, index: int, source_cell_id: str) -> tuple[int, int, bool, int, int]:
    previous = instance.fixes[index]
    current = instance.fixes[index + 1]
    dt_sec = int(current.auth_time_sec) - int(previous.auth_time_sec)
    delta_odo = int(current.odometer_m) - int(previous.odometer_m)
    outage = dt_sec > int(instance.profile.cadence_sec)
    cell = instance.cell_map[str(source_cell_id)]
    rate = (
        int(instance.profile.r_max_cents_per_m)
        if outage
        else int(cell.rate_cents_per_m)
    )
    fee_cents = delta_odo * rate
    return dt_sec, delta_odo, outage, rate, fee_cents


def honest_fee_cents(instance: E3Instance) -> int:
    validate_instance(instance)
    return sum(
        _segment_values(instance, index, instance.fixes[index].true_cell_id)[4]
        for index in range(len(instance.fixes) - 1)
    )


def _make_claim(
    instance: E3Instance,
    path: Sequence[tuple[str, Point]],
    *,
    solver: str,
) -> E3Claim:
    if len(path) != len(instance.fixes):
        raise ValueError("claim path length must match the instance")
    claimed_fixes = tuple(
        ClaimedFix(
            device_id=true.device_id,
            period_id=true.period_id,
            fix_seq=int(true.fix_seq),
            auth_time_sec=int(true.auth_time_sec),
            odometer_m=int(true.odometer_m),
            claimed_point=point,
            claimed_cell_id=str(cell_id),
            position_valid=True,
        )
        for true, (cell_id, point) in zip(instance.fixes, path)
    )
    segments: list[ClaimSegment] = []
    for index in range(len(claimed_fixes) - 1):
        dt_sec, delta_odo, outage, rate, fee = _segment_values(
            instance, index, claimed_fixes[index].claimed_cell_id
        )
        segments.append(
            ClaimSegment(
                segment_index=index,
                dt_sec=dt_sec,
                delta_odometer_m=delta_odo,
                source_cell_id=claimed_fixes[index].claimed_cell_id,
                outage=outage,
                applied_rate_cents_per_m=rate,
                fee_cents=fee,
            )
        )
    fee_cents = sum(segment.fee_cents for segment in segments)
    return E3Claim(
        model_id=MODEL_ID,
        instance_hash=instance.instance_hash,
        profile_hash=instance.profile_hash,
        tariff_hash=instance.tariff_hash,
        data_hash=instance.data_hash,
        code_hash=implementation_code_hash(),
        fixes=claimed_fixes,
        segments=tuple(segments),
        fee_cents=int(fee_cents),
        underpayment_cents=int(honest_fee_cents(instance) - fee_cents),
        solver=str(solver),
    )


def truthful_claim(instance: E3Instance) -> E3Claim:
    """Return the always-feasible zero-attack witness for a valid instance."""

    validate_instance(instance)
    return _make_claim(
        instance,
        [(fix.true_cell_id, fix.true_point) for fix in instance.fixes],
        solver="truthful",
    )


def strict_check(instance: E3Instance, claim: E3Claim) -> CheckResult:
    """Check a claimed attack against every frozen-model binding.

    The result is structured and intentionally accumulates violations.  There
    is no distance-bucket tolerance: each odometer reading and each derived
    segment delta must match exactly.
    """

    validate_instance(instance)
    violations: list[Violation] = []

    def add(
        code: ViolationCode,
        message: str,
        *,
        fix_index: int | None = None,
        segment_index: int | None = None,
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        violations.append(
            Violation(
                code=code,
                message=message,
                fix_index=fix_index,
                segment_index=segment_index,
                expected=expected,
                actual=actual,
            )
        )

    header_checks = (
        (ViolationCode.MODEL_BINDING, claim.model_id, MODEL_ID),
        (ViolationCode.INSTANCE_HASH, claim.instance_hash, instance.instance_hash),
        (ViolationCode.PROFILE_HASH, claim.profile_hash, instance.profile_hash),
        (ViolationCode.TARIFF_HASH, claim.tariff_hash, instance.tariff_hash),
        (ViolationCode.DATA_HASH, claim.data_hash, instance.data_hash),
        (ViolationCode.CODE_HASH, claim.code_hash, implementation_code_hash()),
    )
    for code, actual, expected in header_checks:
        if actual != expected:
            add(code, f"{code} mismatch", expected=expected, actual=actual)

    if len(claim.fixes) != len(instance.fixes):
        add(
            ViolationCode.FIX_COUNT,
            "claim fix count does not match the frozen period",
            expected=len(instance.fixes),
            actual=len(claim.fixes),
        )
    if len(claim.segments) != len(instance.fixes) - 1:
        add(
            ViolationCode.SEGMENT_COUNT,
            "claim segment count does not match the frozen period",
            expected=len(instance.fixes) - 1,
            actual=len(claim.segments),
        )

    cells = instance.cell_map
    valid_claimed_points: dict[int, bool] = {}
    for index, (true, claimed) in enumerate(zip(instance.fixes, claim.fixes)):
        bindings = (
            (ViolationCode.DEVICE_BINDING, claimed.device_id, true.device_id),
            (ViolationCode.PERIOD_BINDING, claimed.period_id, true.period_id),
            (ViolationCode.SEQ_BINDING, claimed.fix_seq, true.fix_seq),
            (ViolationCode.TIME_BINDING, claimed.auth_time_sec, true.auth_time_sec),
            (ViolationCode.ODO_BINDING, claimed.odometer_m, true.odometer_m),
        )
        for code, actual, expected in bindings:
            if actual != expected or (code in {ViolationCode.SEQ_BINDING, ViolationCode.TIME_BINDING, ViolationCode.ODO_BINDING} and (isinstance(actual, bool) or not isinstance(actual, int))):
                add(code, f"{code} mismatch", fix_index=index, expected=expected, actual=actual)
        if claimed.position_valid is not True:
            add(
                ViolationCode.POSITION_VALID,
                "claimed payload position is not explicitly valid",
                fix_index=index,
                expected=True,
                actual=claimed.position_valid,
            )
        point_is_exact = not (
            isinstance(claimed.claimed_point.x, bool)
            or not isinstance(claimed.claimed_point.x, int)
            or isinstance(claimed.claimed_point.y, bool)
            or not isinstance(claimed.claimed_point.y, int)
        )
        valid_claimed_points[index] = point_is_exact
        if not point_is_exact:
            add(
                ViolationCode.POSITION_TYPE,
                "claimed point coordinates must be exact integers",
                fix_index=index,
                actual={"x": claimed.claimed_point.x, "y": claimed.claimed_point.y},
            )
        cell = cells.get(str(claimed.claimed_cell_id))
        if cell is None:
            add(
                ViolationCode.CELL_UNKNOWN,
                "claimed tariff cell is not bound by the tariff hash",
                fix_index=index,
                actual=str(claimed.claimed_cell_id),
            )
        elif point_is_exact and not cell.rectangle.contains(claimed.claimed_point):
            add(
                ViolationCode.PAYLOAD_CELL_BINDING,
                "claimed payload point is outside the claimed cell",
                fix_index=index,
                expected=cell.rectangle.to_dict(),
                actual=claimed.claimed_point.to_dict(),
            )
        radius = int(instance.profile.relay_radius_units)
        if point_is_exact and squared_distance(claimed.claimed_point, true.true_point) > radius * radius:
            add(
                ViolationCode.RADIUS,
                "claimed payload point exceeds the relay displacement radius",
                fix_index=index,
            )

    computed_fees: list[int] = []
    for index in range(len(instance.fixes) - 1):
        true_previous = instance.fixes[index]
        true_current = instance.fixes[index + 1]
        dt_sec = int(true_current.auth_time_sec) - int(true_previous.auth_time_sec)
        delta_odo = int(true_current.odometer_m) - int(true_previous.odometer_m)
        if dt_sec > int(instance.profile.max_dt_sec):
            add(ViolationCode.MAX_DT, "authenticated delta exceeds max_dt_sec", segment_index=index)
        if delta_odo < 0:
            add(ViolationCode.ODO_MONOTONIC, "odometer delta is negative", segment_index=index)
        if delta_odo > int(instance.profile.tier_vmax_mps) * dt_sec:
            add(ViolationCode.SPEED_CAP, "odometer delta exceeds the speed cap", segment_index=index)

        if (
            index + 1 < len(claim.fixes)
            and valid_claimed_points.get(index, False)
            and valid_claimed_points.get(index + 1, False)
        ):
            left = claim.fixes[index].claimed_point
            right = claim.fixes[index + 1].claimed_point
            cap_units = _continuity_cap_units(instance, dt_sec)
            if squared_distance(left, right) > cap_units * cap_units:
                add(
                    ViolationCode.CONTINUITY,
                    "claimed payload points exceed the continuity cap",
                    segment_index=index,
                )
        if index + 1 < len(claim.fixes):
            claimed_previous = claim.fixes[index]
            claimed_current = claim.fixes[index + 1]
            claimed_times_are_int = (
                isinstance(claimed_previous.auth_time_sec, int)
                and not isinstance(claimed_previous.auth_time_sec, bool)
                and isinstance(claimed_current.auth_time_sec, int)
                and not isinstance(claimed_current.auth_time_sec, bool)
            )
            claimed_odos_are_int = (
                isinstance(claimed_previous.odometer_m, int)
                and not isinstance(claimed_previous.odometer_m, bool)
                and isinstance(claimed_current.odometer_m, int)
                and not isinstance(claimed_current.odometer_m, bool)
            )
            if claimed_times_are_int:
                claimed_dt = claimed_current.auth_time_sec - claimed_previous.auth_time_sec
                if claimed_dt > int(instance.profile.max_dt_sec):
                    add(
                        ViolationCode.MAX_DT,
                        "claimed authenticated delta exceeds max_dt_sec",
                        segment_index=index,
                        expected=int(instance.profile.max_dt_sec),
                        actual=claimed_dt,
                    )
                if claimed_odos_are_int:
                    claimed_delta = claimed_current.odometer_m - claimed_previous.odometer_m
                    if claimed_delta < 0:
                        add(
                            ViolationCode.ODO_MONOTONIC,
                            "claimed odometer delta is negative",
                            segment_index=index,
                            actual=claimed_delta,
                        )
                    if claimed_dt > 0 and claimed_delta > int(instance.profile.tier_vmax_mps) * claimed_dt:
                        add(
                            ViolationCode.SPEED_CAP,
                            "claimed odometer delta exceeds the speed cap",
                            segment_index=index,
                            actual=claimed_delta,
                        )

        if index >= len(claim.fixes):
            continue
        source_cell_id = str(claim.fixes[index].claimed_cell_id)
        source_cell = cells.get(source_cell_id)
        if source_cell is None:
            continue
        outage = dt_sec > int(instance.profile.cadence_sec)
        rate = int(instance.profile.r_max_cents_per_m) if outage else int(source_cell.rate_cents_per_m)
        fee = delta_odo * rate
        computed_fees.append(fee)
        if index >= len(claim.segments):
            continue
        segment = claim.segments[index]
        if isinstance(segment.segment_index, bool) or not isinstance(segment.segment_index, int) or segment.segment_index != index:
            add(
                ViolationCode.SEQ_BINDING,
                "segment index is not bound to the frozen sequence",
                segment_index=index,
                expected=index,
                actual=segment.segment_index,
            )
        if isinstance(segment.dt_sec, bool) or not isinstance(segment.dt_sec, int) or segment.dt_sec != dt_sec:
            add(
                ViolationCode.TIME_BINDING,
                "segment dt is not derived from frozen times",
                segment_index=index,
                expected=dt_sec,
                actual=segment.dt_sec,
            )
        if (
            isinstance(segment.delta_odometer_m, bool)
            or not isinstance(segment.delta_odometer_m, int)
            or segment.delta_odometer_m != delta_odo
        ):
            add(
                ViolationCode.ODO_DELTA_BINDING,
                "segment odometer delta is not exactly frozen",
                segment_index=index,
                expected=delta_odo,
                actual=segment.delta_odometer_m,
            )
        if isinstance(segment.dt_sec, int) and not isinstance(segment.dt_sec, bool):
            if segment.dt_sec > int(instance.profile.max_dt_sec):
                add(
                    ViolationCode.MAX_DT,
                    "reported segment dt exceeds max_dt_sec",
                    segment_index=index,
                    expected=int(instance.profile.max_dt_sec),
                    actual=segment.dt_sec,
                )
            if (
                segment.dt_sec > 0
                and isinstance(segment.delta_odometer_m, int)
                and not isinstance(segment.delta_odometer_m, bool)
                and segment.delta_odometer_m > int(instance.profile.tier_vmax_mps) * segment.dt_sec
            ):
                add(
                    ViolationCode.SPEED_CAP,
                    "reported segment odometer delta exceeds the speed cap",
                    segment_index=index,
                    actual=segment.delta_odometer_m,
                )
        if str(segment.source_cell_id) != source_cell_id:
            add(
                ViolationCode.SEGMENT_CELL_BINDING,
                "segment source cell differs from the claimed fix",
                segment_index=index,
                expected=source_cell_id,
                actual=segment.source_cell_id,
            )
        if segment.outage is not outage:
            add(
                ViolationCode.CADENCE_BINDING,
                "outage flag is not the canonical cadence predicate",
                segment_index=index,
                expected=outage,
                actual=segment.outage,
            )
        if (
            isinstance(segment.applied_rate_cents_per_m, bool)
            or not isinstance(segment.applied_rate_cents_per_m, int)
            or segment.applied_rate_cents_per_m != rate
        ):
            add(
                ViolationCode.RATE_BINDING,
                "segment rate is not bound to the tariff/canonical r_max",
                segment_index=index,
                expected=rate,
                actual=segment.applied_rate_cents_per_m,
            )
        if isinstance(segment.fee_cents, bool) or not isinstance(segment.fee_cents, int) or segment.fee_cents != fee:
            add(
                ViolationCode.FEE_BINDING,
                "segment fee is not delta_odometer * applied_rate",
                segment_index=index,
                expected=fee,
                actual=segment.fee_cents,
            )

    computed_fee: int | None = None
    computed_underpayment: int | None = None
    if len(computed_fees) == len(instance.fixes) - 1:
        computed_fee = int(sum(computed_fees))
        computed_underpayment = int(honest_fee_cents(instance) - computed_fee)
        if isinstance(claim.fee_cents, bool) or not isinstance(claim.fee_cents, int) or claim.fee_cents != computed_fee:
            add(
                ViolationCode.FEE_BINDING,
                "reported total fee does not match recomputation",
                expected=computed_fee,
                actual=claim.fee_cents,
            )
        if (
            isinstance(claim.underpayment_cents, bool)
            or not isinstance(claim.underpayment_cents, int)
            or claim.underpayment_cents != computed_underpayment
        ):
            add(
                ViolationCode.OBJECTIVE_BINDING,
                "reported underpayment is not H - B",
                expected=computed_underpayment,
                actual=claim.underpayment_cents,
            )
    return CheckResult(
        accepted=not violations,
        violations=tuple(violations),
        computed_fee_cents=computed_fee,
        computed_underpayment_cents=computed_underpayment,
    )


# Descriptive alias for callers that prefer the full name.
strict_checker = strict_check


@dataclass(frozen=True, order=True)
class _CandidatePoint:
    cell_id: str
    point: Point
    kind: str


def center_candidates(instance: E3Instance) -> tuple[tuple[_CandidatePoint, ...], ...]:
    """Construct the exact feasible-point layers used by the centre solver.

    The truthful payload point is included in every layer so a valid instance
    always has at least the zero-underpayment witness.  Other candidates are
    canonical tariff-cell centres.  No bucket-derived odometer tolerance is
    introduced.
    """

    validate_instance(instance)
    radius_sq = int(instance.profile.relay_radius_units) ** 2
    layers: list[tuple[_CandidatePoint, ...]] = []
    for fix in instance.fixes:
        candidates: dict[tuple[str, int, int], _CandidatePoint] = {}
        truthful = _CandidatePoint(str(fix.true_cell_id), fix.true_point, "truthful")
        candidates[(truthful.cell_id, truthful.point.x, truthful.point.y)] = truthful
        for cell in instance.tariff_cells:
            point = cell.rectangle.center
            if squared_distance(point, fix.true_point) <= radius_sq:
                candidate = _CandidatePoint(str(cell.cell_id), point, "center")
                candidates[(candidate.cell_id, point.x, point.y)] = candidate
        ordered = tuple(
            sorted(candidates.values(), key=lambda item: (item.cell_id, item.point.x, item.point.y, item.kind))
        )
        layers.append(ordered)
    return tuple(layers)


def rectangle_candidates(instance: E3Instance) -> tuple[tuple[str, ...], ...]:
    """Return cells whose rectangle projection intersects each radius disk."""

    validate_instance(instance)
    radius_sq = int(instance.profile.relay_radius_units) ** 2
    layers: list[tuple[str, ...]] = []
    for fix in instance.fixes:
        cells = tuple(
            sorted(
                str(cell.cell_id)
                for cell in instance.tariff_cells
                if point_rectangle_distance_sq(fix.true_point, cell.rectangle) <= radius_sq
            )
        )
        if not cells:
            raise ValueError("rectangle relaxation has an empty candidate layer")
        layers.append(cells)
    return tuple(layers)


def _continuous_integer_layer(
    instance: E3Instance,
    fix_index: int,
    *,
    max_points: int | None,
    deadline_ns: int | None,
) -> tuple[tuple[_CandidatePoint, ...], str]:
    """Enumerate one exact integer-point layer; return ``exact/limit/timeout``."""

    fix = instance.fixes[fix_index]
    radius = int(instance.profile.relay_radius_units)
    radius_sq = radius * radius
    candidates: list[_CandidatePoint] = []
    for cell in sorted(instance.tariff_cells, key=lambda item: str(item.cell_id)):
        rectangle = cell.rectangle
        x_lower = max(int(rectangle.x_min), int(fix.true_point.x) - radius)
        x_upper = min(int(rectangle.x_max), int(fix.true_point.x) + radius)
        for x in range(x_lower, x_upper + 1):
            dx = x - int(fix.true_point.x)
            y_radius = isqrt(radius_sq - dx * dx)
            y_lower = max(int(rectangle.y_min), int(fix.true_point.y) - y_radius)
            y_upper = min(int(rectangle.y_max), int(fix.true_point.y) + y_radius)
            for y in range(y_lower, y_upper + 1):
                candidates.append(
                    _CandidatePoint(str(cell.cell_id), Point(x, y), "continuous-integer")
                )
                if max_points is not None and len(candidates) > max_points:
                    return tuple(candidates), "limit"
            if _timed_out(deadline_ns):
                return tuple(candidates), "timeout"
    return tuple(candidates), "exact"


def continuous_integer_candidates(instance: E3Instance) -> tuple[tuple[_CandidatePoint, ...], ...]:
    """Enumerate the original integer payload domain for a deliberately small instance.

    For every fix this is exactly every ``(claimed_cell, claimed_point)`` pair
    whose integer point lies in both the claimed cell and the displacement
    disk.  Inter-fix continuity remains a path constraint and is checked by
    :func:`strict_check` in the oracle.
    """

    validate_instance(instance)
    layers: list[tuple[_CandidatePoint, ...]] = []
    for index in range(len(instance.fixes)):
        layer, status = _continuous_integer_layer(
            instance, index, max_points=None, deadline_ns=None
        )
        if status != "exact" or not layer:
            raise ValueError("failed to enumerate a complete non-empty integer payload layer")
        layers.append(layer)
    return tuple(layers)


def _start_measurement() -> tuple[int, bool]:
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    return time.perf_counter_ns(), was_tracing


def _finish_measurement(start_ns: int, was_tracing: bool) -> tuple[int, int]:
    runtime_ns = time.perf_counter_ns() - start_ns
    _, peak = tracemalloc.get_traced_memory()
    if not was_tracing:
        tracemalloc.stop()
    return runtime_ns, peak


def _deadline(timeout_sec: float | None) -> int | None:
    if timeout_sec is None:
        return None
    if timeout_sec <= 0:
        return time.perf_counter_ns()
    return time.perf_counter_ns() + int(timeout_sec * 1_000_000_000)


def _timed_out(deadline_ns: int | None) -> bool:
    return deadline_ns is not None and time.perf_counter_ns() >= deadline_ns


def solve_center_feasible(instance: E3Instance, *, timeout_sec: float | None = None) -> BoundSolution:
    """Solve a layered shortest path over strict feasible payload points."""

    validate_instance(instance)
    start_ns, was_tracing = _start_measurement()
    deadline_ns = _deadline(timeout_sec)
    layers = center_candidates(instance)
    states = len(layers[0])
    transitions = 0
    costs: dict[int, int] = {index: 0 for index in range(len(layers[0]))}
    parents: list[dict[int, int]] = []
    timeout = False

    for layer_index in range(len(layers) - 1):
        next_costs: dict[int, int] = {}
        next_parents: dict[int, int] = {}
        dt_sec = int(instance.fixes[layer_index + 1].auth_time_sec) - int(
            instance.fixes[layer_index].auth_time_sec
        )
        cap_units = _continuity_cap_units(instance, dt_sec)
        cap_sq = cap_units * cap_units
        if _all_radius_candidates_pairwise_feasible(instance, layer_index):
            best_left = min(
                costs,
                key=lambda index: (
                    costs[index] + _segment_values(instance, layer_index, layers[layer_index][index].cell_id)[4],
                    index,
                ),
            )
            best_cost = costs[best_left] + _segment_values(
                instance, layer_index, layers[layer_index][best_left].cell_id
            )[4]
            next_costs = {index: best_cost for index in range(len(layers[layer_index + 1]))}
            next_parents = {index: best_left for index in range(len(layers[layer_index + 1]))}
            transitions += len(costs) * len(layers[layer_index + 1])
            parents.append(next_parents)
            costs = next_costs
            states += len(next_costs)
            if _timed_out(deadline_ns):
                timeout = True
                break
            continue
        for left_index in sorted(costs):
            left = layers[layer_index][left_index]
            edge_fee = _segment_values(instance, layer_index, left.cell_id)[4]
            base_cost = int(costs[left_index]) + edge_fee
            for right_index, right in enumerate(layers[layer_index + 1]):
                transitions += 1
                if squared_distance(left.point, right.point) > cap_sq:
                    continue
                if base_cost < next_costs.get(right_index, 1 << 120):
                    next_costs[right_index] = base_cost
                    next_parents[right_index] = left_index
            if _timed_out(deadline_ns):
                timeout = True
                break
        if timeout or not next_costs:
            break
        parents.append(next_parents)
        costs = next_costs
        states += len(next_costs)

    claim: E3Claim
    if not timeout and len(parents) == len(layers) - 1 and costs:
        final_index = min(costs, key=lambda index: (costs[index], index))
        indices = [final_index]
        for layer_index in range(len(parents) - 1, -1, -1):
            indices.append(parents[layer_index][indices[-1]])
        indices.reverse()
        path = [(layers[index][candidate].cell_id, layers[index][candidate].point) for index, candidate in enumerate(indices)]
        claim = _make_claim(instance, path, solver="center-layered-shortest-path/v1")
    else:
        # A timeout may only weaken the LB.  The truthful path remains a strict
        # feasible incumbent and therefore is always safe to report.
        claim = truthful_claim(instance)
    checked = strict_check(instance, claim)
    if not checked.accepted:
        raise AssertionError(f"center solver emitted an invalid witness: {checked.violation_codes}")
    runtime_ns, peak_memory = _finish_measurement(start_ns, was_tracing)
    return BoundSolution(
        domain="F_center",
        fee_cents=int(claim.fee_cents),
        underpayment_cents=int(claim.underpayment_cents),
        cell_path=tuple(fix.claimed_cell_id for fix in claim.fixes),
        claim=claim,
        stats=SolverStats(
            runtime_ns=runtime_ns,
            states=states,
            transitions=transitions,
            peak_memory_bytes=peak_memory,
            timeout=timeout,
        ),
    )


def solve_small_oracle(
    instance: E3Instance,
    *,
    max_paths: int = 1_000_000,
    timeout_sec: float | None = None,
) -> OracleResult:
    """Independently enumerate the exact small original integer domain.

    Every integer point in every ``cell intersect radius-disk`` is enumerated.
    The Cartesian-product paths are decided only by the public strict checker;
    neither centre candidates nor layered-solver transitions are reused.  If
    enumeration would exceed ``max_paths``, the result is explicitly
    incomplete and contains no claimed optimum.
    """

    validate_instance(instance)
    _require_int(max_paths, "max_paths", minimum=1)
    start_ns, was_tracing = _start_measurement()
    deadline_ns = _deadline(timeout_sec)
    layers: list[tuple[_CandidatePoint, ...]] = []
    candidate_paths = 1
    for index in range(len(instance.fixes)):
        remaining_points = max_paths // max(candidate_paths, 1)
        layer, status = _continuous_integer_layer(
            instance,
            index,
            max_points=remaining_points,
            deadline_ns=deadline_ns,
        )
        if status != "exact" or not layer:
            runtime_ns, peak_memory = _finish_measurement(start_ns, was_tracing)
            timed_out = status == "timeout"
            reason = (
                "oracle timeout during exact integer-domain enumeration"
                if timed_out
                else f"candidate path count exceeds max_paths {max_paths}"
            )
            return OracleResult(
                domain="F_continuous_integer",
                complete=False,
                optimum_fee_cents=None,
                optimum_underpayment_cents=None,
                paths_checked=0,
                candidate_paths=max_paths + 1 if status == "limit" else candidate_paths * len(layer),
                claim=None,
                reason=reason,
                stats=SolverStats(runtime_ns, len(layer), 0, peak_memory, timed_out),
            )
        layers.append(layer)
        candidate_paths *= len(layer)

    best: E3Claim | None = None
    checked_count = 0
    timeout = False
    for candidate_tuple in itertools.product(*layers):
        candidate_path = [(candidate.cell_id, candidate.point) for candidate in candidate_tuple]
        claim = _make_claim(instance, candidate_path, solver="small-original-integer-oracle/v1")
        result = strict_check(instance, claim)
        checked_count += 1
        if result.accepted and (best is None or claim.fee_cents < best.fee_cents):
            best = claim
        if _timed_out(deadline_ns):
            timeout = True
            break
    runtime_ns, peak_memory = _finish_measurement(start_ns, was_tracing)
    complete = not timeout and checked_count == candidate_paths
    if complete and best is None:
        raise AssertionError("valid instance has no truthful oracle witness")
    return OracleResult(
        domain="F_continuous_integer",
        complete=complete,
        optimum_fee_cents=int(best.fee_cents) if complete else None,
        optimum_underpayment_cents=int(best.underpayment_cents) if complete else None,
        paths_checked=checked_count,
        candidate_paths=candidate_paths,
        claim=best if complete else None,
        reason="" if complete else "oracle timeout",
        stats=SolverStats(
            runtime_ns=runtime_ns,
            states=checked_count,
            transitions=checked_count * max(0, len(instance.fixes) - 1),
            peak_memory_bytes=peak_memory,
            timeout=timeout,
        ),
    )


def solve_rectangle_relaxation(
    instance: E3Instance,
    *,
    timeout_sec: float | None = None,
) -> BoundSolution:
    """Optimize the certified rectangle-projection relaxation ``R_rect``."""

    validate_instance(instance)
    start_ns, was_tracing = _start_measurement()
    deadline_ns = _deadline(timeout_sec)
    layers = rectangle_candidates(instance)
    cells = instance.cell_map
    costs: dict[str, int] = {cell_id: 0 for cell_id in layers[0]}
    parents: list[dict[str, str]] = []
    states = len(costs)
    transitions = 0
    timeout = False

    for layer_index in range(len(layers) - 1):
        dt_sec = int(instance.fixes[layer_index + 1].auth_time_sec) - int(
            instance.fixes[layer_index].auth_time_sec
        )
        cap_units = _continuity_cap_units(instance, dt_sec)
        cap_sq = cap_units * cap_units
        next_costs: dict[str, int] = {}
        next_parents: dict[str, str] = {}
        if _all_radius_candidates_pairwise_feasible(instance, layer_index):
            best_left = min(
                costs,
                key=lambda cell_id: (
                    costs[cell_id] + _segment_values(instance, layer_index, cell_id)[4],
                    cell_id,
                ),
            )
            best_cost = costs[best_left] + _segment_values(instance, layer_index, best_left)[4]
            next_costs = {cell_id: best_cost for cell_id in layers[layer_index + 1]}
            next_parents = {cell_id: best_left for cell_id in layers[layer_index + 1]}
            transitions += len(costs) * len(layers[layer_index + 1])
            parents.append(next_parents)
            costs = next_costs
            states += len(costs)
            if _timed_out(deadline_ns):
                timeout = True
                break
            continue
        for left_id in sorted(costs):
            edge_fee = _segment_values(instance, layer_index, left_id)[4]
            base_cost = costs[left_id] + edge_fee
            for right_id in layers[layer_index + 1]:
                transitions += 1
                if rectangle_distance_sq(cells[left_id].rectangle, cells[right_id].rectangle) > cap_sq:
                    continue
                if base_cost < next_costs.get(right_id, 1 << 120):
                    next_costs[right_id] = base_cost
                    next_parents[right_id] = left_id
            if _timed_out(deadline_ns):
                timeout = True
                break
        if timeout:
            break
        if not next_costs:
            raise ValueError("rectangle relaxation unexpectedly has no complete path")
        parents.append(next_parents)
        costs = next_costs
        states += len(costs)

    runtime_ns, peak_memory = _finish_measurement(start_ns, was_tracing)
    if timeout:
        raise TimeoutError("R_rect must finish before its optimum can be reported as a certified upper bound")
    final_id = min(costs, key=lambda cell_id: (costs[cell_id], cell_id))
    path = [final_id]
    for layer_index in range(len(parents) - 1, -1, -1):
        path.append(parents[layer_index][path[-1]])
    path.reverse()
    fee_cents = int(costs[final_id])
    return BoundSolution(
        domain=RECT_RELAXATION_ID,
        fee_cents=fee_cents,
        underpayment_cents=int(honest_fee_cents(instance) - fee_cents),
        cell_path=tuple(path),
        claim=None,
        stats=SolverStats(runtime_ns, states, transitions, peak_memory, False),
    )


def solve_independent_relaxation(instance: E3Instance) -> BoundSolution:
    """Optimize ``R_ind``, which drops every inter-fix continuity edge."""

    validate_instance(instance)
    start_ns, was_tracing = _start_measurement()
    layers = rectangle_candidates(instance)
    path: list[str] = []
    fee_cents = 0
    states = 0
    for index, layer in enumerate(layers):
        states += len(layer)
        if index < len(instance.fixes) - 1:
            chosen = min(layer, key=lambda cell_id: (_segment_values(instance, index, cell_id)[4], cell_id))
            fee_cents += _segment_values(instance, index, chosen)[4]
        else:
            chosen = min(layer)
        path.append(chosen)
    runtime_ns, peak_memory = _finish_measurement(start_ns, was_tracing)
    return BoundSolution(
        domain=INDEPENDENT_RELAXATION_ID,
        fee_cents=int(fee_cents),
        underpayment_cents=int(honest_fee_cents(instance) - fee_cents),
        cell_path=tuple(path),
        claim=None,
        stats=SolverStats(runtime_ns, states, 0, peak_memory, False),
    )


def verify_projection_containment(instance: E3Instance) -> ContainmentReport:
    """Machine-check the finite obligations behind the relaxation chain."""

    validate_instance(instance)
    center_layers = center_candidates(instance)
    rectangle_layers = rectangle_candidates(instance)
    rectangle_sets = [set(layer) for layer in rectangle_layers]
    cells = instance.cell_map
    center_points_checked = 0
    center_edges_checked = 0
    center_ok = True

    for index, layer in enumerate(center_layers):
        radius_sq = int(instance.profile.relay_radius_units) ** 2
        for candidate in layer:
            center_points_checked += 1
            cell = cells[candidate.cell_id]
            if (
                candidate.cell_id not in rectangle_sets[index]
                or not cell.rectangle.contains(candidate.point)
                or squared_distance(candidate.point, instance.fixes[index].true_point) > radius_sq
                or point_rectangle_distance_sq(instance.fixes[index].true_point, cell.rectangle) > radius_sq
            ):
                center_ok = False

    for index in range(len(center_layers) - 1):
        dt_sec = int(instance.fixes[index + 1].auth_time_sec) - int(instance.fixes[index].auth_time_sec)
        cap_units = _continuity_cap_units(instance, dt_sec)
        cap_sq = cap_units * cap_units
        if _all_radius_candidates_pairwise_feasible(instance, index):
            center_edges_checked += len(center_layers[index]) * len(center_layers[index + 1])
            continue
        for left in center_layers[index]:
            for right in center_layers[index + 1]:
                if squared_distance(left.point, right.point) <= cap_sq:
                    center_edges_checked += 1
                    if rectangle_distance_sq(
                        cells[left.cell_id].rectangle, cells[right.cell_id].rectangle
                    ) > cap_sq:
                        center_ok = False

    # The two remaining implications are the exact projection inequalities:
    # a point in a rectangle witnesses point-to-rectangle distance, and two
    # points in adjacent rectangles witness rectangle-to-rectangle distance.
    # R_ind then deletes those edge predicates entirely.
    return ContainmentReport(
        center_points_checked=center_points_checked,
        center_edges_checked=center_edges_checked,
        center_to_continuous=center_ok,
        continuous_to_rectangle=True,
        rectangle_to_independent=True,
        proof_hash=RECT_RELAXATION_PROOF_HASH,
    )


def bucket_center_coordinates(
    *,
    lower: int,
    upper: int,
    bucket_size: int,
    origin: int = 0,
) -> tuple[int, ...]:
    """Return integral grid centres, useful for auditing bucket non-nesting.

    Refining a grid is not generally a set refinement: for example, 100-unit
    centres are 50,150,... while 50-unit centres are 25,75,125,... .  This
    utility makes that property explicit; no solver treats bucket results as a
    convergence sequence without a separate containment proof.
    """

    _require_int(lower, "lower")
    _require_int(upper, "upper")
    _require_int(bucket_size, "bucket_size", minimum=1)
    _require_int(origin, "origin")
    if upper <= lower:
        return ()
    if bucket_size % 2:
        raise ValueError("bucket_size must be even for integral centres")
    first_index = (lower - origin) // bucket_size
    while origin + first_index * bucket_size + bucket_size // 2 < lower:
        first_index += 1
    centers: list[int] = []
    index = first_index
    while True:
        center = origin + index * bucket_size + bucket_size // 2
        if center >= upper:
            break
        centers.append(center)
        index += 1
    return tuple(centers)


def certify_instance(
    instance: E3Instance,
    *,
    run_oracle: bool = False,
    oracle_max_paths: int = 1_000_000,
    timeout_sec: float | None = None,
    feasible_incumbents: Sequence[
        tuple[str, Sequence[tuple[str, Point]]]
    ] = (),
) -> dict[str, Any]:
    """Produce an auditable LB/UB/gap receipt for one frozen E3 instance.

    ``feasible_incumbents`` can strengthen the centre-only search without
    changing the certified direction.  Every item is a ``(source, path)``
    pair, is rebound to this exact instance, and must pass :func:`strict_check`
    before it can compete with the centre witness.  This is used by the
    experiment runner to lift a finer-grid feasible point path into its
    containing coarser cells when rates are inherited.  The points themselves
    are not rounded or moved, so continuity and relay-radius predicates remain
    exact.
    """

    validate_instance(instance)
    honest = int(honest_fee_cents(instance))
    center_lower = solve_center_feasible(instance, timeout_sec=timeout_sec)
    if center_lower.claim is None:
        raise AssertionError("the feasible solver did not emit a witness")
    center_checker = strict_check(instance, center_lower.claim)
    if not center_checker.accepted:
        raise AssertionError(
            f"LB witness failed strict checking: {center_checker.violation_codes}"
        )

    incumbent_audit: list[dict[str, Any]] = [
        {
            "source": "center-layered-shortest-path/v1",
            "search_domain": center_lower.domain,
            "fee_cents": int(center_lower.fee_cents),
            "underpayment_cents": int(center_lower.underpayment_cents),
            "witness_hash": sha256_json(center_lower.claim.to_dict()),
            "checker_accepted": True,
        }
    ]
    selected_source = "center-layered-shortest-path/v1"
    selected_search_domain = center_lower.domain
    selected_claim = center_lower.claim
    selected_checker = center_checker
    for incumbent_index, incumbent in enumerate(feasible_incumbents):
        if not isinstance(incumbent, Sequence) or len(incumbent) != 2:
            raise ValueError(
                f"feasible incumbent {incumbent_index} must be a (source, path) pair"
            )
        source, path = incumbent
        if not isinstance(source, str) or not source:
            raise ValueError(
                f"feasible incumbent {incumbent_index} source must be a non-empty string"
            )
        rebound = _make_claim(
            instance,
            path,
            solver=f"strict-feasible-incumbent:{source}",
        )
        rebound_checker = strict_check(instance, rebound)
        incumbent_audit.append(
            {
                "source": source,
                "search_domain": "F_strict-feasible/v1",
                "fee_cents": int(rebound.fee_cents),
                "underpayment_cents": int(rebound.underpayment_cents),
                "witness_hash": sha256_json(rebound.to_dict()),
                "checker_accepted": bool(rebound_checker.accepted),
                "violation_codes": list(rebound_checker.violation_codes),
            }
        )
        if not rebound_checker.accepted:
            raise ValueError(
                f"feasible incumbent {source!r} failed strict checking: "
                f"{rebound_checker.violation_codes}"
            )
        if int(rebound.underpayment_cents) > int(selected_claim.underpayment_cents):
            selected_source = source
            selected_search_domain = "F_strict-feasible/v1"
            selected_claim = rebound
            selected_checker = rebound_checker

    lower = BoundSolution(
        domain=selected_search_domain,
        fee_cents=int(selected_claim.fee_cents),
        underpayment_cents=int(selected_claim.underpayment_cents),
        cell_path=tuple(fix.claimed_cell_id for fix in selected_claim.fixes),
        claim=selected_claim,
        # The centre search is the measured baseline.  Rebinding supplied
        # integer points is deterministic linear-time bookkeeping and its full
        # candidate/checker audit is recorded below.
        stats=center_lower.stats,
    )
    checker = selected_checker
    independent = solve_independent_relaxation(instance)
    rectangle_timed_out = False
    try:
        upper = solve_rectangle_relaxation(instance, timeout_sec=timeout_sec)
    except TimeoutError:
        # R_ind is a proven superset of R_rect.  Its exact optimum is therefore
        # a safe (although weaker) UB when the tighter relaxation times out.
        upper = independent
        rectangle_timed_out = True
    containment = verify_projection_containment(instance)
    if not containment.valid:
        raise AssertionError("projection containment proof obligations failed")
    if lower.underpayment_cents > upper.underpayment_cents:
        raise AssertionError("bound direction failure: LB > R_rect UB")
    if upper.domain == RECT_RELAXATION_ID and upper.underpayment_cents > independent.underpayment_cents:
        raise AssertionError("relaxation direction failure: R_rect UB > R_ind UB")

    oracle = (
        solve_small_oracle(instance, max_paths=oracle_max_paths, timeout_sec=timeout_sec)
        if run_oracle
        else None
    )
    if oracle is not None and oracle.complete:
        optimum = int(oracle.optimum_underpayment_cents)
        if not lower.underpayment_cents <= optimum <= upper.underpayment_cents:
            raise AssertionError("small-oracle optimum lies outside the certified interval")

    gap = int(upper.underpayment_cents - lower.underpayment_cents)
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "certified",
        "instance": {
            "instance_id": str(instance.instance_id),
            "dataset": str(instance.dataset),
            "instance_hash": instance.instance_hash,
            "bucket_size_units": instance.bucket_size_units,
        },
        "bindings": {
            "model_id": MODEL_ID,
            "profile_hash": instance.profile_hash,
            "tariff_hash": instance.tariff_hash,
            "data_hash": instance.data_hash,
            "code_hash": implementation_code_hash(),
        },
        "H_cents": honest,
        "LB_cents": int(lower.underpayment_cents),
        "UB_cents": int(upper.underpayment_cents),
        "gap_cents": gap,
        "relative_gap_ppm": gap * 1_000_000 // max(abs(int(lower.underpayment_cents)), 1),
        "lower_bound": {
            "domain": "F_strict-feasible/v1",
            "selected_search_domain": lower.domain,
            "selected_source": selected_source,
            "fee_cents": int(lower.fee_cents),
            "underpayment_cents": int(lower.underpayment_cents),
            "witness_hash": sha256_json(lower.claim.to_dict()),
            "witness": lower.claim.to_dict(),
            "checker": checker.to_dict(),
            "solver": lower.stats.to_dict(),
            "incumbent_selection": {
                "rule": "maximum strictly checked feasible underpayment; stable first-on-tie",
                "candidate_count": len(incumbent_audit),
                "all_candidates_strictly_accepted": all(
                    bool(item["checker_accepted"]) for item in incumbent_audit
                ),
                "candidates": incumbent_audit,
            },
        },
        "upper_bound": {
            "relaxation_id": upper.domain,
            "fee_cents": int(upper.fee_cents),
            "underpayment_cents": int(upper.underpayment_cents),
            "cell_path": list(upper.cell_path),
            "proof_hash": RECT_RELAXATION_PROOF_HASH,
            "proof": dict(_RECT_PROOF),
            "containment": containment.to_dict(),
            "solver": upper.stats.to_dict(),
            "rectangle_attempt": {
                "relaxation_id": RECT_RELAXATION_ID,
                "timeout": rectangle_timed_out,
                "used_for_bound": upper.domain == RECT_RELAXATION_ID,
            },
            "independent_cross_check": {
                "relaxation_id": INDEPENDENT_RELAXATION_ID,
                "fee_cents": int(independent.fee_cents),
                "underpayment_cents": int(independent.underpayment_cents),
                "direction_ok": upper.underpayment_cents <= independent.underpayment_cents,
                "solver": independent.stats.to_dict(),
            },
        },
        "oracle": None if oracle is None else oracle.to_dict(),
        "timeout": bool(
            lower.stats.timeout
            or rectangle_timed_out
            or upper.stats.timeout
            or (oracle is not None and oracle.stats.timeout)
        ),
    }
    receipt["receipt_hash"] = sha256_json(receipt)
    return receipt


# Short aliases retained for experiment scripts and external audit notebooks.
certify_e3 = certify_instance
rectangle_relaxation_upper_bound = solve_rectangle_relaxation
independent_relaxation_upper_bound = solve_independent_relaxation
small_oracle = solve_small_oracle


__all__ = [
    "MODEL_ID",
    "RECEIPT_SCHEMA",
    "RECT_RELAXATION_ID",
    "INDEPENDENT_RELAXATION_ID",
    "RECT_RELAXATION_PROOF_HASH",
    "ViolationCode",
    "Point",
    "Rectangle",
    "TariffCell",
    "E3Profile",
    "TrueFix",
    "ClaimedFix",
    "ClaimSegment",
    "E3Claim",
    "E3Instance",
    "Violation",
    "CheckResult",
    "SolverStats",
    "BoundSolution",
    "OracleResult",
    "ContainmentReport",
    "canonical_json",
    "sha256_json",
    "implementation_code_hash",
    "squared_distance",
    "point_rectangle_distance_sq",
    "rectangle_distance_sq",
    "validate_instance",
    "honest_fee_cents",
    "truthful_claim",
    "strict_check",
    "strict_checker",
    "center_candidates",
    "rectangle_candidates",
    "continuous_integer_candidates",
    "solve_center_feasible",
    "solve_small_oracle",
    "small_oracle",
    "solve_rectangle_relaxation",
    "rectangle_relaxation_upper_bound",
    "solve_independent_relaxation",
    "independent_relaxation_upper_bound",
    "verify_projection_containment",
    "bucket_center_coordinates",
    "certify_instance",
    "certify_e3",
]
