#!/usr/bin/env python3
"""Compile and benchmark the WayBill V6 circuit scalability matrix.

The runner is deliberately receipt-first: every requested configuration gets
an immutable JSON receipt even when compilation, setup, witness generation, or
proving exceeds the declared local resource envelope.  A successful proof is
counted only after snarkjs verification, an exact public-signal comparison, and
an explicit check that public signal 1 is the checked-in 10,000-cell Rome
tariff root.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams  # noqa: E402
from common.policy_profile import PolicyProfile  # noqa: E402
from common.resource_probe import (  # noqa: E402
    collect_host_evidence,
    measured_command,
    parse_time_evidence,
)
from common.settlement import ReceiverFix, TariffTable, merkle_parent, verify_merkle_path  # noqa: E402
from common.settlement_v6 import PUBLIC_SIGNAL_ORDER_V6  # noqa: E402
from script import build_waybill_m2_tariff as tariff_builder  # noqa: E402
from script import prove_settlement_period_v6 as v6_prover  # noqa: E402


DEPTHS = (8, 12, 14, 16)
FIX_COUNTS = (25, 50, 100, 200)
K_WINDOW = 6
GRID_W = 100
CELL_SIZE_M = 100
CADENCE_SEC = 60
MAX_DT_SEC = 600
TIER_VMAX_MPS = 33
M2_CAP_POLICY_SQ = 100_000_000
SNARKJS_NODE_OPTIONS = "--max-old-space-size=12288"

M2_DIR = ROOT_DIR / "experiments" / "waybill_m2"
DEFAULT_OUTPUT_DIR = M2_DIR / "circuit_matrix"
TARIFF_PATH = M2_DIR / "tariff_rome_medium_10000_cells.json"
TARIFF_MANIFEST_PATH = M2_DIR / "tariff_manifest_depth14.json"
BASE_CIRCUIT = ROOT_DIR / "experiments-heatmap" / "circuits" / "settlement_period_v6_base.circom"

PTAU_FILENAME = "powersOfTau28_hez_final_22.ptau"
PTAU_URL = f"https://storage.googleapis.com/zkevm/ptau/{PTAU_FILENAME}"
PTAU_BLAKE2B = (
    "0d64f63dba1a6f11139df765cb690da69d9b2f469a1ddd0de5e4aa628abb28f7"
    "87f04c6a5fb84a235ec5ea7f41d0548746653ecab0559add658a83502d1cb21b"
)
PTAU_BYTES = 4_831_921_304
PTAU_DOWNLOAD_WORKERS = 6
PTAU_SOURCE = "https://github.com/iden3/snarkjs#7-prepare-phase-2"
SETUP_MIN_FREE_BYTES = 8 * 1024**3

PUBLIC_BLOCK = ",\n    ".join(PUBLIC_SIGNAL_ORDER_V6)
R1CS_PATTERNS = {
    "wires": re.compile(r"# of Wires:\s*([\d,]+)"),
    "constraints": re.compile(r"# of Constraints:\s*([\d,]+)"),
    "private_inputs": re.compile(r"# of Private Inputs:\s*([\d,]+)"),
    "public_inputs": re.compile(r"# of Public Inputs:\s*([\d,]+)"),
    "labels": re.compile(r"# of Labels:\s*([\d,]+)"),
    "outputs": re.compile(r"# of Outputs:\s*([\d,]+)"),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def blake2b_file(path: Path) -> str:
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def wrapper_name(depth: int, fixes: int) -> str:
    return f"settlement_period_v6_d{depth}_n{fixes}_k{K_WINDOW}"


def wrapper_text(depth: int, fixes: int) -> str:
    if depth not in DEPTHS or fixes not in FIX_COUNTS:
        raise ValueError("wrapper configuration is outside the pre-registered matrix")
    return f'''pragma circom 2.1.9;
include "../settlement_period_v6_base.circom";

// Generated deterministically by script/run_waybill_m2_circuit_matrix.py.
// Public order is frozen by common.settlement_v6.PUBLIC_SIGNAL_ORDER_V6.
component main {{public [
    {PUBLIC_BLOCK}
]}} = SettlementPeriodV6({fixes}, {depth}, {K_WINDOW});
'''


def generate_wrapper(output_dir: Path, depth: int, fixes: int) -> tuple[Path, Path]:
    source_dir = output_dir / "circuit-sources"
    wrapper_dir = source_dir / "generated_v6_matrix"
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    frozen_base = source_dir / BASE_CIRCUIT.name
    base_bytes = BASE_CIRCUIT.read_bytes()
    if not frozen_base.exists() or frozen_base.read_bytes() != base_bytes:
        frozen_base.write_bytes(base_bytes)
    path = wrapper_dir / f"{wrapper_name(depth, fixes)}.circom"
    expected = wrapper_text(depth, fixes)
    if not path.exists() or path.read_text(encoding="utf-8") != expected:
        path.write_text(expected, encoding="utf-8")
    return frozen_base, path


def find_circomlib() -> Path:
    candidates = (
        ROOT_DIR / "node_modules",
        Path("/opt/waybill/node_modules"),
        ROOT_DIR / "TSIP_heatmap_version" / "runtime" / "experiments-heatmap" / "node_modules",
        Path.home() / "node_modules",
    )
    for candidate in candidates:
        if (candidate / "circomlib").is_dir():
            return candidate.resolve()
    raise FileNotFoundError("circomlib include directory was not found")


@dataclass
class CommandReceipt:
    status: str
    command: list[str]
    started_at: str
    elapsed_ms: float
    max_rss_bytes: int | None
    user_cpu_sec: float | None
    system_cpu_sec: float | None
    measurement_backend: str
    returncode: int | None
    timed_out: bool
    stdout_tail: str
    stderr_tail: str
    error: str | None
    environment_overrides: dict[str, str]


def run_measured(
    command: Sequence[str],
    *,
    timeout_sec: int,
    cwd: Path = ROOT_DIR,
    environment_overrides: dict[str, str] | None = None,
) -> CommandReceipt:
    """Run one command with portable resource evidence and timeout isolation."""

    started_at = utc_now()
    started = time.perf_counter()
    timed_out = False
    returncode: int | None = None
    stdout = ""
    stderr = ""
    error: str | None = None
    wrapped, measurement_backend = measured_command(list(map(str, command)))
    overrides = dict(environment_overrides or {})
    environment = os.environ.copy()
    environment.update(overrides)
    process = subprocess.Popen(
        wrapped,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=environment,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_sec)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        error = f"timeout after {timeout_sec}s"
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        returncode = process.returncode
    except Exception as exc:  # pragma: no cover - OS/tool failure
        error = f"{type(exc).__name__}: {exc}"
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        returncode = process.returncode

    elapsed_ms = (time.perf_counter() - started) * 1000
    time_evidence = parse_time_evidence(stderr, measurement_backend)
    if returncode and error is None:
        error = f"command exited with status {returncode}"
    status = "ok" if returncode == 0 and not timed_out else "failed"
    return CommandReceipt(
        status=status,
        command=list(map(str, command)),
        started_at=started_at,
        elapsed_ms=round(elapsed_ms, 3),
        max_rss_bytes=time_evidence["max_rss_bytes"],
        user_cpu_sec=time_evidence["user_cpu_sec"],
        system_cpu_sec=time_evidence["system_cpu_sec"],
        measurement_backend=str(time_evidence["measurement_backend"]),
        returncode=returncode,
        timed_out=timed_out,
        stdout_tail=stdout[-8000:],
        stderr_tail=stderr[-8000:],
        error=error,
        environment_overrides=overrides,
    )


def parse_r1cs_info(output: str) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for name, pattern in R1CS_PATTERNS.items():
        match = pattern.search(output)
        if match:
            parsed[name] = int(match.group(1).replace(",", ""))
    if "constraints" not in parsed:
        raise ValueError("snarkjs r1cs info did not report a constraint count")
    return parsed


def parse_circom_compile_info(output: str) -> dict[str, int]:
    patterns = {
        "non_linear_constraints": re.compile(r"(?m)^\s*non-linear constraints:\s*([\d,]+)"),
        "linear_constraints": re.compile(r"(?m)^\s*linear constraints:\s*([\d,]+)"),
        "public_inputs": re.compile(r"(?m)^\s*public inputs:\s*([\d,]+)"),
        "private_inputs": re.compile(r"(?m)^\s*private inputs:\s*([\d,]+)"),
        "outputs": re.compile(r"(?m)^\s*public outputs:\s*([\d,]+)"),
        "wires": re.compile(r"(?m)^\s*wires:\s*([\d,]+)"),
        "labels": re.compile(r"(?m)^\s*labels:\s*([\d,]+)"),
    }
    parsed: dict[str, int] = {}
    for name, pattern in patterns.items():
        match = pattern.search(output)
        if match:
            parsed[name] = int(match.group(1).replace(",", ""))
    if "non_linear_constraints" not in parsed or "linear_constraints" not in parsed:
        raise ValueError("circom output did not report constraint counts")
    parsed["constraints"] = parsed["non_linear_constraints"] + parsed["linear_constraints"]
    return parsed


def artifact_record(path: Path) -> dict[str, Any]:
    try:
        display_path = str(path.relative_to(ROOT_DIR))
    except ValueError:
        display_path = str(path)
    if not path.exists():
        return {"path": display_path, "exists": False}
    return {
        "path": display_path,
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def config_paths(output_dir: Path, depth: int, fixes: int) -> dict[str, Path]:
    name = wrapper_name(depth, fixes)
    directory = output_dir / "build" / name
    return {
        "directory": directory,
        "r1cs": directory / f"{name}.r1cs",
        "sym": directory / f"{name}.sym",
        "wasm": directory / f"{name}_js" / f"{name}.wasm",
        "zkey": directory / f"{name}_test_only.zkey",
        "vkey": directory / "verification_key.json",
    }


def compile_one(output_dir: Path, depth: int, fixes: int, *, timeout_sec: int) -> dict[str, Any]:
    name = wrapper_name(depth, fixes)
    frozen_base, wrapper = generate_wrapper(output_dir, depth, fixes)
    paths = config_paths(output_dir, depth, fixes)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    command = [
        "circom",
        str(wrapper),
        "--r1cs",
        "--wasm",
        "--sym",
        "-o",
        str(paths["directory"]),
        "-l",
        str(find_circomlib()),
    ]
    measured = run_measured(command, timeout_sec=timeout_sec)
    receipt: dict[str, Any] = {
        "schema": "waybill-m2-circuit-compile-receipt-v1",
        "config_id": name,
        "depth": depth,
        "fixes": fixes,
        "intervals": fixes - 1,
        "template": f"SettlementPeriodV6({fixes},{depth},{K_WINDOW})",
        "compile": asdict(measured),
        "source": {
            "base": artifact_record(frozen_base),
            "wrapper": artifact_record(wrapper),
        },
        "artifacts": {
            "r1cs": artifact_record(paths["r1cs"]),
            "wasm": artifact_record(paths["wasm"]),
            "sym": artifact_record(paths["sym"]),
        },
    }
    if measured.status == "ok" and paths["r1cs"].exists():
        try:
            compiler_info = parse_circom_compile_info(measured.stdout_tail)
        except ValueError as exc:
            receipt["status"] = "constraint_parse_failed"
            receipt["failure"] = {"stage": "constraint_parse", "reason": str(exc)}
        else:
            # Circom emits the constraint/wire counts while writing the exact
            # R1CS.  This avoids loading multi-gigabyte R1CS files into the
            # default Node heap merely to repeat those counts.
            receipt["compiler_info"] = compiler_info
            receipt["r1cs_info"] = compiler_info
            receipt["constraint_count_source"] = "circom compiler stdout"
            receipt["status"] = "compiled"
    else:
        receipt["status"] = "compile_failed"
        receipt["failure"] = {
            "stage": "compile",
            "resource_envelope": {"timeout_sec": timeout_sec},
            "reason": measured.error,
        }
    write_json(output_dir / "receipts" / "compile" / f"{name}.json", receipt)
    return receipt


def repair_compile_receipts(output_dir: Path) -> None:
    """Promote successful compiles whose secondary snarkjs info hit Node OOM."""

    receipt_dir = output_dir / "receipts" / "compile"
    for path in receipt_dir.glob("*.json"):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        compile_record = receipt.get("compile", {})
        if compile_record.get("status") != "ok":
            continue
        try:
            compiler_info = parse_circom_compile_info(str(compile_record.get("stdout_tail", "")))
        except ValueError:
            continue
        receipt["compiler_info"] = compiler_info
        receipt["r1cs_info"] = compiler_info
        receipt["constraint_count_source"] = "circom compiler stdout"
        if receipt.get("r1cs_info_command", {}).get("status") == "failed":
            receipt["secondary_diagnostic"] = {
                "stage": "snarkjs_r1cs_info",
                "status": "failed_non_gating",
                "reason": receipt["r1cs_info_command"].get("error"),
                "stderr_tail": receipt["r1cs_info_command"].get("stderr_tail", "")[-2000:],
            }
        receipt.pop("failure", None)
        receipt["status"] = "compiled"
        write_json(path, receipt)


class CachedTariffTable:
    """TariffTable-compatible view with one precomputed fixed-depth tree.

    ``TariffTable.path_for_cell`` intentionally favors a tiny reference
    implementation and rebuilds the complete tree per call.  Matrix witnesses
    need up to 199 paths, so this benchmark view computes the identical leaves
    and levels once; this changes no commitment semantics.
    """

    def __init__(self, table: TariffTable, *, depth: int) -> None:
        self.tariff_version = table.tariff_version
        self.grid_w = table.grid_w
        self.cell_zones = table.cell_zones
        self.zone_rates_cents_per_m = table.zone_rates_cents_per_m
        self._table = table
        self._depth = depth
        leaves = table.leaves()
        capacity = 1 << depth
        if len(leaves) > capacity:
            raise ValueError("tariff has more leaves than the cached tree capacity")
        if not leaves:
            leaves = [0]
        leaves.extend([leaves[-1]] * (capacity - len(leaves)))
        self._levels = [leaves]
        level = leaves
        while len(level) > 1:
            level = [merkle_parent(level[index], level[index + 1]) for index in range(0, len(level), 2)]
            self._levels.append(level)

    @property
    def max_zone_rate_cents_per_m(self) -> int:
        return self._table.max_zone_rate_cents_per_m

    def zone_for_cell(self, cell_idx: int) -> int:
        return self._table.zone_for_cell(cell_idx)

    def rate_for_zone(self, zone_id: int) -> int:
        return self._table.rate_for_zone(zone_id)

    def cell_index(self, cell_x: int, cell_y: int) -> int:
        return self._table.cell_index(cell_x, cell_y)

    def leaf_for_cell(self, cell_idx: int) -> int:
        return self._table.leaf_for_cell(cell_idx)

    def root(self, depth: int | None = None) -> int:
        if depth is not None and int(depth) != self._depth:
            raise ValueError(f"cached tariff is available only at depth {self._depth}")
        return self._levels[-1][0]

    def path_for_cell(self, cell_idx: int, depth: int | None = None) -> list[dict[str, int]]:
        if depth is not None and int(depth) != self._depth:
            raise ValueError(f"cached tariff is available only at depth {self._depth}")
        if int(cell_idx) not in self.cell_zones:
            raise ValueError(f"missing tariff zone for cell {cell_idx}")
        index = int(cell_idx)
        path: list[dict[str, int]] = []
        for level_number, level in enumerate(self._levels[:-1]):
            path.append(
                {
                    "level": level_number,
                    "sibling": int(level[index ^ 1]),
                    "is_right": int(index & 1),
                }
            )
            index //= 2
        return path


_CITY_TARIFF_CACHE: dict[int, tuple[CachedTariffTable, dict[str, Any]]] = {}


def load_city_tariff(
    depth: int = 14,
    *,
    fresh: bool = False,
) -> tuple[CachedTariffTable, dict[str, Any]]:
    if depth not in DEPTHS:
        raise ValueError("tariff depth is outside the pre-registered matrix")
    if not fresh and depth in _CITY_TARIFF_CACHE:
        return _CITY_TARIFF_CACHE[depth]
    payload = json.loads(TARIFF_PATH.read_text(encoding="utf-8"))
    source_manifest = json.loads(TARIFF_MANIFEST_PATH.read_text(encoding="utf-8"))
    capacity = 1 << depth
    source_zones = {int(key): int(value) for key, value in payload["cell_zones"].items()}
    selected_zones = {
        index: zone for index, zone in source_zones.items() if index < capacity
    }
    reference = TariffTable(
        tariff_version=int(payload["tariff_version"]),
        grid_w=int(payload["grid_w"]),
        cell_zones=selected_zones,
        zone_rates_cents_per_m={
            int(key): int(value) for key, value in payload["zone_rates_cents_per_m"].items()
        },
    )
    table = CachedTariffTable(reference, depth=depth)
    actual_root = str(table.root(depth))
    if depth == 14:
        if actual_root != str(source_manifest["tariff_root"]):
            raise RuntimeError("checked-in 10,000-cell tariff root mismatch")
        if len(table.cell_zones) != 10_000:
            raise RuntimeError("depth-14 M2 proof input requires exactly 10,000 real tariff cells")
        manifest = source_manifest
    else:
        manifest = {
            "schema": "waybill_m2_capacity_matched_tariff_manifest_v1",
            "artifact_id": f"waybill-m2-rome-medium-capacity-d{depth}-v1",
            "tariff_root": actual_root,
            "source": {
                "artifact_id": source_manifest["artifact_id"],
                "tariff_cells_sha256": sha256_file(TARIFF_PATH),
                "tariff_manifest_sha256": sha256_file(TARIFF_MANIFEST_PATH),
                "selection_rule": (
                    f"retain source cells with ascending cell_idx < {capacity}; "
                    "for depth 16 retain all 10,000 cells and repeat-last pad to capacity"
                ),
                "economic_semantics": "none; computational capacity comparison only",
            },
            "tree": {
                "depth": depth,
                "capacity": capacity,
                "real_leaf_count": len(selected_zones),
                "padding_rule": "repeat-last-real-leaf",
            },
            "tariff": {
                "grid_w": int(payload["grid_w"]),
                "normalized_unit": "dimensionless_relative_tier",
                "maximum_value": max(reference.zone_rates_cents_per_m.values()),
            },
        }
    result = (table, manifest)
    if not fresh:
        _CITY_TARIFF_CACHE[depth] = result
    return result


def snake_cell(seq: int) -> tuple[int, int]:
    row, offset = divmod(seq, GRID_W)
    x = offset if row % 2 == 0 else GRID_W - 1 - offset
    return x, row


def _cap_policy_hash() -> str:
    payload = json.dumps(
        {"cap_policy_sq": M2_CAP_POLICY_SQ, "domain_sep": "waybill-v6-cap-policy-v1"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_policy_profile_for_config(
    *,
    output_dir: Path,
    depth: int,
    fixes_count: int,
    verification_key_path: Path,
) -> PolicyProfile:
    expected_vkey_path = config_paths(output_dir, depth, fixes_count)["vkey"].resolve()
    if verification_key_path.resolve() != expected_vkey_path:
        raise ValueError("verification key path does not match the circuit config")
    if not verification_key_path.is_file():
        raise FileNotFoundError(f"missing verification key: {verification_key_path}")
    tariff, manifest = load_city_tariff(depth)
    name = wrapper_name(depth, fixes_count)
    profile_version = depth * 1_000_000 + fixes_count
    profile = PolicyProfile(
        authority_id="waybill-ruc-v6-m2-benchmark-authority",
        jurisdiction_id=f"rome-capacity-m2-d{depth}-n{fixes_count}",
        profile_version=profile_version,
        valid_from=1_777_593_600,
        valid_to=1_809_129_600,
        revoked_at=None,
        min_accepted_version=profile_version,
        tariff_version=int(tariff.tariff_version),
        tariff_root=int(manifest["tariff_root"]),
        tariff_tree_depth=depth,
        max_fixes=fixes_count,
        max_zone_rate_cents_per_m=int(tariff.max_zone_rate_cents_per_m),
        cadence_sec=CADENCE_SEC,
        max_dt_sec=MAX_DT_SEC,
        tier_vmax_mps=TIER_VMAX_MPS,
        tier_vmax_sq=TIER_VMAX_MPS**2,
        mode_vmax_sq=v6_prover.MODE_VMAX_SQ,
        cap_policy_sq=M2_CAP_POLICY_SQ,
        cap_policy_hash=_cap_policy_hash(),
        circuit_id=name,
        verification_key_hash=sha256_file(verification_key_path),
        currency="EUR",
        fixed_point_scale=1,
        rounding_mode="exact-integer",
        overflow_policy="reject-u96",
        monthly_reconciliation_rate_cents_per_m=int(tariff.max_zone_rate_cents_per_m),
        fallback_semantics_version="odometer-max-rate-v6",
        verification_key_path=(
            str(verification_key_path.relative_to(ROOT_DIR))
            if verification_key_path.is_relative_to(ROOT_DIR)
            else str(verification_key_path.resolve())
        ),
        tariff_artifact_path=str(TARIFF_PATH.relative_to(ROOT_DIR)),
    )
    profile.assert_tariff_matches(tariff)  # type: ignore[arg-type]
    profile_path = output_dir / "policy_profiles" / f"{name}.json"
    write_json(profile_path, profile.to_dict())
    return profile


def create_policy_profile(
    *,
    output_dir: Path,
    fixes_count: int,
    verification_key_path: Path,
) -> PolicyProfile:
    """Backward-compatible depth-14 profile builder used by the M0-M3 gate."""

    return create_policy_profile_for_config(
        output_dir=output_dir,
        depth=14,
        fixes_count=fixes_count,
        verification_key_path=verification_key_path,
    )


def validate_profile_for_city_input(
    profile: PolicyProfile,
    *,
    depth: int,
    fixes_count: int,
    tariff: CachedTariffTable,
) -> None:
    if int(profile.commitment) == 0:
        raise ValueError("zero policy profile commitment is forbidden")
    expected = {
        "tariff_tree_depth": depth,
        "max_fixes": fixes_count,
        "max_zone_rate_cents_per_m": tariff.max_zone_rate_cents_per_m,
        "cadence_sec": CADENCE_SEC,
        "max_dt_sec": MAX_DT_SEC,
        "tier_vmax_mps": TIER_VMAX_MPS,
        "mode_vmax_sq": v6_prover.MODE_VMAX_SQ,
        "cap_policy_sq": M2_CAP_POLICY_SQ,
        "circuit_id": wrapper_name(depth, fixes_count),
        "fallback_semantics_version": "odometer-max-rate-v6",
    }
    for field, expected_value in expected.items():
        if getattr(profile, field) != expected_value:
            raise ValueError(f"M2 policy profile mismatch: {field}")
    profile.assert_tariff_matches(tariff)  # type: ignore[arg-type]
    vkey = ROOT_DIR / profile.verification_key_path
    if not vkey.is_file() or sha256_file(vkey) != profile.verification_key_hash:
        raise ValueError("M2 policy profile verification-key hash mismatch")


def build_city_input_for_config(
    depth: int,
    fixes_count: int,
    *,
    policy_profile: PolicyProfile,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if depth not in DEPTHS:
        raise ValueError("depth is outside the pre-registered matrix")
    if fixes_count not in FIX_COUNTS:
        raise ValueError("fix count is outside the pre-registered matrix")
    tariff, manifest = load_city_tariff(depth)
    validate_profile_for_city_input(
        policy_profile,
        depth=depth,
        fixes_count=fixes_count,
        tariff=tariff,
    )
    period_id = f"2026-05-waybill-m2-d{depth}-n{fixes_count}"
    start_time = 1_777_593_600
    fixes: list[ReceiverFix] = []
    odometer = 50_000
    previous_xy: tuple[int, int] | None = None
    for seq in range(fixes_count):
        x, y = snake_cell(seq)
        if previous_xy is not None:
            odometer += CELL_SIZE_M
        previous_xy = (x, y)
        fixes.append(
            ReceiverFix(
                device_id="waybill-m2-benchmark-device",
                period_id=period_id,
                fix_seq=seq,
                auth_gnss_time=start_time + seq * CADENCE_SEC,
                cell_x=x,
                cell_y=y,
                osnma_status="authenticated",
                odometer_reading_m=odometer,
                nonce=f"waybill-m2-d{depth}-n{fixes_count}-fix-{seq}",
            )
        )
    position_valid = [index % 11 != 5 for index in range(fixes_count - 1)]
    params = HarnessParams(
        cadence_sec=CADENCE_SEC,
        max_dt_sec=MAX_DT_SEC,
        tier_vmax_mps=TIER_VMAX_MPS,
        cell_size_m=CELL_SIZE_M,
    )

    # The frozen M1 builder is parameterized through its module constants.
    # Restore them even on failure so importing this runner cannot pollute M1.
    old_n = v6_prover.N_FIXES
    old_depth = v6_prover.TREE_DEPTH
    old_cap_policy_sq = v6_prover.CAP_POLICY_SQ
    try:
        v6_prover.N_FIXES = fixes_count
        v6_prover.TREE_DEPTH = depth
        v6_prover.CAP_POLICY_SQ = M2_CAP_POLICY_SQ
        circuit_input = v6_prover.build_raw_witness_input_for_fixes(
            fixes,
            tariff,
            position_valid=position_valid,
            params=params,
            policy_profile_commitment=int(policy_profile.commitment),
        )
    finally:
        v6_prover.N_FIXES = old_n
        v6_prover.TREE_DEPTH = old_depth
        v6_prover.CAP_POLICY_SQ = old_cap_policy_sq

    expected_root = str(manifest["tariff_root"])
    if circuit_input["tariff_root"] != expected_root:
        raise RuntimeError("proof input does not reference the M2 10,000-cell tariff root")
    if circuit_input["policy_profile_commitment"] != str(policy_profile.commitment):
        raise RuntimeError("proof input does not reference the canonical M2 policy profile")
    if len(circuit_input["zone_path_sibling"]) != fixes_count - 1:
        raise RuntimeError("proof input path count mismatch")
    if any(len(path) != depth for path in circuit_input["zone_path_sibling"]):
        raise RuntimeError(f"proof input does not use depth-{depth} membership paths")
    metadata = {
        "tariff_artifact_id": manifest["artifact_id"],
        "tariff_root": expected_root,
        "real_tariff_cells": int(manifest["tree"]["real_leaf_count"]),
        "tariff_tree_depth": depth,
        "tariff_manifest_sha256": sha256_file(TARIFF_MANIFEST_PATH),
        "tariff_cells_sha256": sha256_file(TARIFF_PATH),
        "policy_profile_commitment": str(policy_profile.commitment),
        "policy_profile_sha256": policy_profile.profile_sha256,
        "policy_profile_fields": policy_profile.public_statement_fields(),
        "verification_key_hash": policy_profile.verification_key_hash,
        "visited_cell_indices": [
            tariff.cell_index(fix.cell_x, fix.cell_y) for fix in fixes[:-1]
        ],
        "position_valid_intervals": sum(position_valid),
        "outage_intervals": len(position_valid) - sum(position_valid),
        "public_signals": [circuit_input[name] for name in PUBLIC_SIGNAL_ORDER_V6],
    }
    return circuit_input, metadata


def build_city_input(
    fixes_count: int,
    *,
    policy_profile: PolicyProfile,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Backward-compatible depth-14 input builder."""

    return build_city_input_for_config(14, fixes_count, policy_profile=policy_profile)


def ensure_ptau(ptau: Path, *, allow_download: bool, timeout_sec: int) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": "waybill-m2-ptau-receipt-v1",
        "path": str(ptau),
        "source_url": PTAU_URL,
        "source_documentation": PTAU_SOURCE,
        "expected_blake2b": PTAU_BLAKE2B,
        "required_power": 22,
        "max_constraints": 1 << 22,
    }
    if not ptau.exists() and allow_download:
        ptau.parent.mkdir(parents=True, exist_ok=True)
        single_partial = ptau.with_suffix(ptau.suffix + ".partial")
        if single_partial.exists():
            receipt["abandoned_single_stream_attempt"] = {
                "bytes_before_prune": single_partial.stat().st_size,
                "reason": "manual stop after measured single-stream throughput implied an hour-scale download",
            }
            single_partial.unlink()
        part_dir = ptau.parent / f"{ptau.name}.parts"
        part_dir.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(ptau.parent)
        if disk.free < PTAU_BYTES + 8 * 1024**3:
            receipt["download"] = {
                "status": "failed",
                "failure": {
                    "stage": "disk_preflight",
                    "free_bytes": disk.free,
                    "required_bytes_including_safety_margin": PTAU_BYTES + 8 * 1024**3,
                },
            }
        else:
            ranges: list[tuple[int, int, Path]] = []
            chunk_size = math.ceil(PTAU_BYTES / PTAU_DOWNLOAD_WORKERS)
            for index in range(PTAU_DOWNLOAD_WORKERS):
                start = index * chunk_size
                end = min(PTAU_BYTES, (index + 1) * chunk_size) - 1
                ranges.append((start, end, part_dir / f"part-{index:02d}.bin"))

            def download_part(item: tuple[int, int, Path]) -> tuple[int, dict[str, Any]]:
                start, end, path = item
                expected_bytes = end - start + 1
                if path.exists() and path.stat().st_size == expected_bytes:
                    return start, {
                        "status": "reused_complete_part",
                        "range": [start, end],
                        "path": str(path),
                        "bytes": expected_bytes,
                    }
                path.unlink(missing_ok=True)
                measured = run_measured(
                    [
                        "curl",
                        "-fL",
                        "--http1.1",
                        "--retry",
                        "3",
                        "--retry-all-errors",
                        "--range",
                        f"{start}-{end}",
                        "-o",
                        str(path),
                        PTAU_URL,
                    ],
                    timeout_sec=timeout_sec,
                )
                record = asdict(measured)
                record.update(
                    {
                        "range": [start, end],
                        "path": str(path),
                        "expected_bytes": expected_bytes,
                        "actual_bytes": path.stat().st_size if path.exists() else 0,
                    }
                )
                if measured.status == "ok" and record["actual_bytes"] != expected_bytes:
                    record["status"] = "failed"
                    record["error"] = "range response byte count mismatch"
                return start, record

            part_receipts: list[tuple[int, dict[str, Any]]] = []
            with ThreadPoolExecutor(max_workers=PTAU_DOWNLOAD_WORKERS) as executor:
                futures = [executor.submit(download_part, item) for item in ranges]
                for future in as_completed(futures):
                    part_receipts.append(future.result())
            ordered_parts = [record for _start, record in sorted(part_receipts)]
            part_ok = all(record["status"] in {"ok", "reused_complete_part"} for record in ordered_parts)
            receipt["download"] = {
                "status": "parts_complete" if part_ok else "failed",
                "strategy": "six concurrent HTTP byte ranges from the official iden3/Hermez URL",
                "workers": PTAU_DOWNLOAD_WORKERS,
                "expected_total_bytes": PTAU_BYTES,
                "parts": ordered_parts,
            }
            if part_ok:
                with ptau.open("wb") as destination:
                    for _start, _end, part_path in ranges:
                        with part_path.open("rb") as source:
                            shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
                receipt["download"]["assembled_bytes"] = ptau.stat().st_size
    if not ptau.exists():
        receipt.update({"status": "missing", "error": "power-22 phase-2 ptau is unavailable"})
        return receipt
    actual = blake2b_file(ptau)
    receipt.update(
        {
            "bytes": ptau.stat().st_size,
            "actual_blake2b": actual,
            "status": "verified" if actual == PTAU_BLAKE2B else "checksum_mismatch",
        }
    )
    if actual != PTAU_BLAKE2B:
        receipt["error"] = "downloaded ptau failed the official iden3 blake2b checksum"
    else:
        part_dir = ptau.parent / f"{ptau.name}.parts"
        if part_dir.exists():
            shutil.rmtree(part_dir)
            receipt["download_parts_pruned_after_checksum"] = True
    return receipt


def setup_one(
    output_dir: Path,
    depth: int,
    fixes: int,
    *,
    ptau: Path,
    timeout_sec: int,
    formal_all_depths: bool = False,
) -> dict[str, Any]:
    name = wrapper_name(depth, fixes)
    paths = config_paths(output_dir, depth, fixes)
    receipt: dict[str, Any] = {
        "schema": "waybill-m2-groth16-setup-receipt-v1",
        "config_id": name,
        "depth": depth,
        "fixes": fixes,
        "trusted_setup_security_note": (
            "Benchmark-only phase-2 output from the official iden3/Hermez powers-of-tau; "
            "no circuit-specific contribution, not production deployment material."
        ),
        "ptau": {"path": str(ptau), "blake2b": blake2b_file(ptau) if ptau.exists() else None},
        "execution_runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    disk = shutil.disk_usage(output_dir)
    receipt["disk_preflight"] = {
        "free_bytes": disk.free,
        "minimum_free_bytes": SETUP_MIN_FREE_BYTES,
        "passed": disk.free >= SETUP_MIN_FREE_BYTES,
    }
    if disk.free < SETUP_MIN_FREE_BYTES:
        receipt.update(
            {
                "status": "failed",
                "failure": {
                    "stage": "disk_preflight",
                    "reason": (
                        f"free space {disk.free} bytes is below the conservative "
                        f"{SETUP_MIN_FREE_BYTES}-byte setup floor"
                    ),
                },
            }
        )
        write_json(output_dir / "receipts" / "setup" / f"{name}.json", receipt)
        return receipt
    if not paths["r1cs"].exists():
        receipt.update({"status": "failed", "failure": {"stage": "setup", "reason": "missing R1CS"}})
        write_json(output_dir / "receipts" / "setup" / f"{name}.json", receipt)
        return receipt
    setup = run_measured(
        ["snarkjs", "groth16", "setup", str(paths["r1cs"]), str(ptau), str(paths["zkey"])],
        timeout_sec=timeout_sec,
        environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
    )
    receipt["setup"] = asdict(setup)
    if setup.status != "ok":
        receipt.update(
            {
                "status": "failed",
                "failure": {
                    "stage": "groth16_setup",
                    "reason": setup.error,
                    "resource_envelope": {"timeout_sec": timeout_sec},
                },
            }
        )
    else:
        export = run_measured(
            ["snarkjs", "zkey", "export", "verificationkey", str(paths["zkey"]), str(paths["vkey"])],
            timeout_sec=600,
            environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
        )
        receipt["vkey_export"] = asdict(export)
        require_full_zkey_verify = depth == 14 or formal_all_depths
        if require_full_zkey_verify:
            zkey_verify = run_measured(
                [
                    "snarkjs",
                    "zkey",
                    "verify",
                    str(paths["r1cs"]),
                    str(ptau),
                    str(paths["zkey"]),
                ],
                timeout_sec=timeout_sec,
                environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
            )
            receipt["zkey_verify"] = asdict(zkey_verify)
            receipt["zkey_matches_r1cs_and_ptau"] = (
                zkey_verify.status == "ok" and "ZKey Ok" in zkey_verify.stdout_tail
            )
            receipt["zkey_verification_scope"] = (
                "full snarkjs zkey verify for every formal proof configuration"
                if formal_all_depths
                else "full snarkjs zkey verify for depth-14 proof gate"
            )
        else:
            receipt["zkey_matches_r1cs_and_ptau"] = None
            receipt["zkey_verification_scope"] = (
                "not repeated for compile/setup-only stress cells; successful key generation and vkey export "
                "are recorded, while all four depth-14 proof-gating keys receive full zkey verification"
            )
        receipt["status"] = (
            "ready"
            if export.status == "ok"
            and (not require_full_zkey_verify or receipt["zkey_matches_r1cs_and_ptau"])
            else "failed"
        )
        if export.status != "ok":
            receipt["failure"] = {"stage": "vkey_export", "reason": export.error}
        elif require_full_zkey_verify and not receipt["zkey_matches_r1cs_and_ptau"]:
            receipt["failure"] = {"stage": "zkey_verify", "reason": zkey_verify.error}
    receipt["artifacts"] = {
        "zkey": artifact_record(paths["zkey"]),
        "verification_key": artifact_record(paths["vkey"]),
    }
    if receipt["status"] == "ready" and (depth == 14 or formal_all_depths):
        profile = create_policy_profile_for_config(
            output_dir=output_dir,
            depth=depth,
            fixes_count=fixes,
            verification_key_path=paths["vkey"],
        )
        profile_path = output_dir / "policy_profiles" / f"{name}.json"
        receipt["policy_profile"] = {
            **artifact_record(profile_path),
            "commitment": str(profile.commitment),
            "profile_sha256": profile.profile_sha256,
            "verification_key_hash": profile.verification_key_hash,
            "tariff_root": str(profile.tariff_root),
        }
    if depth != 14 and paths["zkey"].exists() and not formal_all_depths:
        # The receipt above retains zkey hash/bytes plus successful setup and
        # vkey-export resource records. Non-gating zkeys are then pruned one at
        # a time; full zkey verification is restricted to depth-14 proof keys.
        paths["zkey"].unlink()
        receipt["artifact_pruned_after_receipt"] = True
        receipt["pruned_artifact"] = "zkey"
        receipt["zkey_exists_after_prune"] = False
    else:
        receipt["artifact_pruned_after_receipt"] = False
    write_json(output_dir / "receipts" / "setup" / f"{name}.json", receipt)
    return receipt


def run_trial(
    *,
    output_dir: Path,
    depth: int,
    fixes: int,
    trial_label: str,
    circuit_input_path: Path,
    expected_public: Sequence[str],
    expected_tariff_root: str,
    expected_policy_commitment: str,
    timeout_sec: int,
    keep_proof: bool,
) -> dict[str, Any]:
    name = wrapper_name(depth, fixes)
    paths = config_paths(output_dir, depth, fixes)
    trial_dir = output_dir / "trials" / name / trial_label
    trial_dir.mkdir(parents=True, exist_ok=True)
    witness = trial_dir / "witness.wtns"
    proof = trial_dir / "proof.json"
    public = trial_dir / "public.json"
    receipt: dict[str, Any] = {
        "schema": "waybill-m2-groth16-trial-receipt-v1",
        "config_id": name,
        "trial": trial_label,
        "depth": depth,
        "fixes": fixes,
        "started_at": utc_now(),
    }
    witness_run = run_measured(
        ["snarkjs", "wtns", "calculate", str(paths["wasm"]), str(circuit_input_path), str(witness)],
        timeout_sec=timeout_sec,
        environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
    )
    receipt["witness"] = asdict(witness_run)
    if witness_run.status != "ok":
        receipt.update({"status": "failed", "failure": {"stage": "witness", "reason": witness_run.error}})
        write_json(trial_dir / "receipt.json", receipt)
        return receipt
    prove_run = run_measured(
        ["snarkjs", "groth16", "prove", str(paths["zkey"]), str(witness), str(proof), str(public)],
        timeout_sec=timeout_sec,
        environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
    )
    receipt["prove"] = asdict(prove_run)
    witness.unlink(missing_ok=True)
    if prove_run.status != "ok":
        receipt.update({"status": "failed", "failure": {"stage": "prove", "reason": prove_run.error}})
        write_json(trial_dir / "receipt.json", receipt)
        return receipt
    verify_run = run_measured(
        ["snarkjs", "groth16", "verify", str(paths["vkey"]), str(public), str(proof)],
        timeout_sec=min(timeout_sec, 600),
        environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
    )
    receipt["verify"] = asdict(verify_run)
    public_values = json.loads(public.read_text(encoding="utf-8"))
    proof_verified = verify_run.status == "ok" and "OK" in verify_run.stdout_tail
    public_match = list(public_values) == list(expected_public)
    tariff_root_match = len(public_values) > 1 and str(public_values[1]) == expected_tariff_root
    policy_commitment_match = (
        len(public_values) > 3 and str(public_values[3]) == expected_policy_commitment
    )
    receipt.update(
        {
            "proof_verified": proof_verified,
            "public_signal_count": len(public_values),
            "public_signals_match_reference": public_match,
            "public_tariff_root": str(public_values[1]) if len(public_values) > 1 else None,
            "tariff_root_matches_10000_cell_artifact": tariff_root_match,
            "public_policy_profile_commitment": str(public_values[3]) if len(public_values) > 3 else None,
            "policy_profile_commitment_matches_canonical_profile": policy_commitment_match,
            "proof_json_bytes": proof.stat().st_size,
            "proof_json_sha256": sha256_file(proof),
            "public_json_sha256": sha256_file(public),
        }
    )
    ok = proof_verified and public_match and tariff_root_match and policy_commitment_match
    receipt["status"] = "verified" if ok else "failed"
    if not ok:
        receipt["failure"] = {
            "stage": "post_verify_gate",
            "reason": "proof/public-signal/tariff-root gate failed",
        }
    if not keep_proof:
        proof.unlink(missing_ok=True)
        public.unlink(missing_ok=True)
    write_json(trial_dir / "receipt.json", receipt)
    return receipt


def nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def stage_summary(trials: Sequence[dict[str, Any]], stage: str) -> dict[str, Any]:
    elapsed = [float(trial[stage]["elapsed_ms"]) for trial in trials if trial.get("status") == "verified"]
    rss = [
        int(trial[stage]["max_rss_bytes"])
        for trial in trials
        if trial.get("status") == "verified" and trial[stage].get("max_rss_bytes") is not None
    ]
    return {
        "samples": len(elapsed),
        "elapsed_ms_p50": nearest_rank(elapsed, 0.50),
        "elapsed_ms_p95_nearest_rank": nearest_rank(elapsed, 0.95),
        "max_rss_bytes_p50": nearest_rank(rss, 0.50),
        "max_rss_bytes_p95_nearest_rank": nearest_rank(rss, 0.95),
    }


def run_negative_gates(
    *,
    output_dir: Path,
    depth: int = 14,
    fixes: int,
    circuit_input_path: Path,
    timeout_sec: int,
) -> dict[str, Any]:
    """Reject public tariff/profile/bill edits and a private Merkle-path edit."""

    name = wrapper_name(depth, fixes)
    paths = config_paths(output_dir, depth, fixes)
    source_trial = output_dir / "trials" / name / "measured-1"
    proof_path = source_trial / "proof.json"
    public_path = source_trial / "public.json"
    gate_dir = output_dir / "negative_gates" / name
    gate_dir.mkdir(parents=True, exist_ok=True)
    receipt: dict[str, Any] = {
        "schema": "waybill-m2-negative-proof-gates-v1",
        "config_id": name,
        "public_tamper_cases": [],
    }
    if not proof_path.exists() or not public_path.exists():
        receipt.update({"status": "failed", "reason": "missing measured proof for negative gates"})
        write_json(gate_dir / "receipt.json", receipt)
        return receipt
    original_public = json.loads(public_path.read_text(encoding="utf-8"))
    for label, signal_index in (
        ("tariff_root", 1),
        ("policy_profile_commitment", 3),
        ("total_fee_cents", 7),
    ):
        tampered_public = list(original_public)
        tampered_public[signal_index] = str(int(tampered_public[signal_index]) + 1)
        tampered_path = gate_dir / f"public-{label}.json"
        write_json(tampered_path, tampered_public)
        verification = run_measured(
            ["snarkjs", "groth16", "verify", str(paths["vkey"]), str(tampered_path), str(proof_path)],
            timeout_sec=min(timeout_sec, 600),
            environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
        )
        rejected = verification.status != "ok" or "OK" not in verification.stdout_tail
        receipt["public_tamper_cases"].append(
            {
                "field": label,
                "public_signal_index": signal_index,
                "rejected": rejected,
                "verification": asdict(verification),
            }
        )

    tampered_input = json.loads(circuit_input_path.read_text(encoding="utf-8"))
    tampered_input["zone_path_sibling"][0][0] = str(
        int(tampered_input["zone_path_sibling"][0][0]) + 1
    )
    path_input = gate_dir / "input-tampered-merkle-path.json"
    path_witness = gate_dir / "tampered-merkle-path.wtns"
    write_json(path_input, tampered_input)
    witness = run_measured(
        ["snarkjs", "wtns", "calculate", str(paths["wasm"]), str(path_input), str(path_witness)],
        timeout_sec=timeout_sec,
        environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
    )
    path_witness.unlink(missing_ok=True)
    receipt["private_merkle_path_tamper"] = {
        "rejected_during_witness": witness.status != "ok",
        "witness": asdict(witness),
    }
    all_rejected = all(case["rejected"] for case in receipt["public_tamper_cases"]) and bool(
        receipt["private_merkle_path_tamper"]["rejected_during_witness"]
    )
    receipt["status"] = "passed" if all_rejected else "failed"
    write_json(gate_dir / "receipt.json", receipt)
    return receipt


def prove_one(
    output_dir: Path,
    depth: int,
    fixes: int,
    *,
    timeout_sec: int,
    measured_trials: int,
) -> dict[str, Any]:
    name = wrapper_name(depth, fixes)
    paths = config_paths(output_dir, depth, fixes)
    receipt_path = output_dir / "receipts" / "proof" / f"{name}.json"
    proof_schema = (
        "waybill-m2-depth14-proof-summary-v1"
        if depth == 14
        else "waybill-m2-proof-summary-v2"
    )
    if not paths["zkey"].exists() or not paths["vkey"].exists():
        receipt = {
            "schema": proof_schema,
            "config_id": name,
            "status": "failed",
            "failure": {"stage": "preflight", "reason": "missing zkey or verification key"},
        }
        write_json(receipt_path, receipt)
        return receipt
    profile_path = output_dir / "policy_profiles" / f"{name}.json"
    # Reconstruct from the actual current vkey on every proof run so stale
    # profiles cannot survive a setup rerun or parameter change.
    policy_profile = create_policy_profile_for_config(
        output_dir=output_dir,
        depth=depth,
        fixes_count=fixes,
        verification_key_path=paths["vkey"],
    )
    setup_receipt_path = output_dir / "receipts" / "setup" / f"{name}.json"
    if setup_receipt_path.exists():
        setup_receipt = json.loads(setup_receipt_path.read_text(encoding="utf-8"))
        setup_receipt["policy_profile"] = {
            **artifact_record(profile_path),
            "commitment": str(policy_profile.commitment),
            "profile_sha256": policy_profile.profile_sha256,
            "verification_key_hash": policy_profile.verification_key_hash,
            "tariff_root": str(policy_profile.tariff_root),
        }
        write_json(setup_receipt_path, setup_receipt)
    circuit_input, metadata = build_city_input_for_config(
        depth,
        fixes,
        policy_profile=policy_profile,
    )
    input_dir = output_dir / "inputs"
    input_path = input_dir / f"{name}.json"
    write_json(input_path, circuit_input)
    input_record = artifact_record(input_path)
    expected_public = [circuit_input[name] for name in PUBLIC_SIGNAL_ORDER_V6]

    warmup = run_trial(
        output_dir=output_dir,
        depth=depth,
        fixes=fixes,
        trial_label="warmup",
        circuit_input_path=input_path,
        expected_public=expected_public,
        expected_tariff_root=metadata["tariff_root"],
        expected_policy_commitment=metadata["policy_profile_commitment"],
        timeout_sec=timeout_sec,
        keep_proof=False,
    )
    trials: list[dict[str, Any]] = []
    if warmup["status"] == "verified":
        for index in range(measured_trials):
            trial = run_trial(
                output_dir=output_dir,
                depth=depth,
                fixes=fixes,
                trial_label=f"measured-{index + 1}",
                circuit_input_path=input_path,
                expected_public=expected_public,
                expected_tariff_root=metadata["tariff_root"],
                expected_policy_commitment=metadata["policy_profile_commitment"],
                timeout_sec=timeout_sec,
                keep_proof=True,
            )
            trials.append(trial)
            if trial["status"] != "verified":
                break
    verified = [trial for trial in trials if trial["status"] == "verified"]
    total_ms = [
        sum(float(trial[stage]["elapsed_ms"]) for stage in ("witness", "prove", "verify"))
        for trial in verified
    ]
    p50_total = nearest_rank(total_ms, 0.50)
    proof_hashes = [str(trial.get("proof_json_sha256")) for trial in verified]
    independent_proof_randomness_observed = (
        len(proof_hashes) == measured_trials and len(set(proof_hashes)) == measured_trials
    )
    negative_gates = (
        run_negative_gates(
            output_dir=output_dir,
            depth=depth,
            fixes=fixes,
            circuit_input_path=input_path,
            timeout_sec=timeout_sec,
        )
        if verified
        else {"status": "not_run", "reason": "no verified measured proof"}
    )
    receipt = {
        "schema": proof_schema,
        "config_id": name,
        "depth": depth,
        "fixes": fixes,
        "execution_runner_sha256": sha256_file(Path(__file__).resolve()),
        "warmup_status": warmup["status"],
        "measured_trials_required": measured_trials,
        "measured_trials_completed": len(trials),
        "verified_trials": len(verified),
        "verification_failures": len(trials) - len(verified),
        "independent_proof_hashes": proof_hashes,
        "independent_proof_randomness_observed": independent_proof_randomness_observed,
        "negative_correctness_gates": negative_gates,
        "status": (
            "verified"
            if len(verified) == measured_trials
            and independent_proof_randomness_observed
            and negative_gates.get("status") == "passed"
            else "failed"
        ),
        "input": input_record,
        "policy_profile": artifact_record(profile_path),
        "city_tariff_binding": metadata,
        "metrics": {
            "percentile_method": (
                f"nearest-rank; measured n={measured_trials}, "
                "P95 is the nearest-rank order statistic"
            ),
            "witness": stage_summary(trials, "witness"),
            "prove": stage_summary(trials, "prove"),
            "verify": stage_summary(trials, "verify"),
            "end_to_end_ms_p50": p50_total,
            "end_to_end_ms_p95_nearest_rank": nearest_rank(total_ms, 0.95),
            "proofs_per_hour_at_p50": None if not p50_total else 3_600_000 / p50_total,
            "proof_json_bytes": [trial.get("proof_json_bytes") for trial in verified],
        },
        "trial_receipts": [
            str((output_dir / "trials" / name / f"measured-{index + 1}" / "receipt.json").relative_to(ROOT_DIR))
            for index in range(len(trials))
        ],
    }
    if receipt["status"] != "verified":
        if warmup["status"] != "verified":
            stage = warmup.get("failure", {}).get("stage", "warmup")
            reason = warmup.get("failure", {}).get("reason", "warmup failed")
        elif len(verified) != measured_trials:
            stage = trials[-1].get("failure", {}).get("stage", "measured_trials") if trials else "measured_trials"
            reason = (
                trials[-1].get("failure", {}).get("reason", "insufficient verified trials")
                if trials
                else "no measured trials completed"
            )
        elif not independent_proof_randomness_observed:
            stage = "proof_randomness"
            reason = "measured Groth16 proof hashes were not all distinct"
        else:
            stage = "negative_correctness_gates"
            reason = "one or more tariff/profile/bill/path tamper cases were not rejected"
        receipt["failure"] = {
            "stage": stage,
            "reason": reason,
            "resource_envelope": {"timeout_sec_per_stage": timeout_sec},
        }
    write_json(receipt_path, receipt)
    return receipt


def prove_depth14_one(
    output_dir: Path,
    fixes: int,
    *,
    timeout_sec: int,
    measured_trials: int,
) -> dict[str, Any]:
    """Backward-compatible depth-14 proof gate."""

    return prove_one(
        output_dir,
        14,
        fixes,
        timeout_sec=timeout_sec,
        measured_trials=measured_trials,
    )


def git_output(*args: str) -> str | None:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT_DIR, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    return proc.stdout.strip() if proc.returncode == 0 else None


def environment_manifest(
    output_dir: Path,
    *,
    ptau: Path,
    measured_trials: int | None = None,
) -> dict[str, Any]:
    host = collect_host_evidence(ROOT_DIR)
    versions = {}
    for name, command in {
        "python": [sys.executable, "--version"],
        "node": ["node", "--version"],
        "circom": ["circom", "--version"],
        "snarkjs": ["snarkjs", "--version"],
    }.items():
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        versions[name] = proc.stdout.splitlines()[0].strip() if proc.stdout else None
    manifest = {
        "schema": "waybill-m2-environment-manifest-v1",
        "generated_at": utc_now(),
        **host,
        "gpu_or_vram": "N/A: snarkjs Groth16 benchmark executed on CPU",
        "versions": versions,
        "git_head": git_output("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(git_output("status", "--porcelain")),
        "source_artifacts": {
            "base_circuit": artifact_record(BASE_CIRCUIT),
            "runner": artifact_record(Path(__file__).resolve()),
            "tariff_manifest": artifact_record(TARIFF_MANIFEST_PATH),
            "tariff_cells": artifact_record(TARIFF_PATH),
        },
        "trusted_setup": {
            "path": str(ptau),
            "official_source": PTAU_SOURCE,
            "download_url": PTAU_URL,
            "expected_blake2b": PTAU_BLAKE2B,
        },
        "execution_policy": {
            "sequential": True,
            "phase_order": ["compile", "prune-sym", "setup", "prove", "aggregate"],
            "clean_rerun_command": (
                "python script/run_waybill_m2_circuit_matrix.py --phase all --download-ptau"
            ),
            "artifact_retention": (
                "retain R1CS/WASM and depth-14 zkeys; hash then prune debug-only .sym files and "
                "non-depth-14 zkeys"
            ),
            "warmup_trials": 1,
            "measured_trials": measured_trials,
            "percentile_method": "nearest-rank",
            "proof_backend": "snarkjs Groth16 / bn128",
            "trusted_setup_scope": "benchmark-only, no circuit-specific contribution",
            "snarkjs_node_options": SNARKJS_NODE_OPTIONS,
        },
        "reproducibility_scope": (
            "This manifest records the local environment and deterministic commands needed for a clean "
            "rerun; it is not evidence that an independent machine has reproduced the measurements."
        ),
    }
    write_json(output_dir / "environment_manifest.json", manifest)
    return manifest


def selected_configs(raw: str) -> list[tuple[int, int]]:
    if not raw:
        return [(depth, fixes) for depth in DEPTHS for fixes in FIX_COUNTS]
    result = []
    for item in raw.split(","):
        match = re.fullmatch(r"d(8|12|14|16)n(25|50|100|200)", item.strip())
        if not match:
            raise ValueError(f"invalid config selector: {item}")
        result.append((int(match.group(1)), int(match.group(2))))
    return result


def _artifact_path(record: dict[str, Any]) -> Path:
    raw = Path(str(record.get("path", "")))
    return raw if raw.is_absolute() else ROOT_DIR / raw


def validate_depth14_proof_evidence(
    *,
    output_dir: Path,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Re-open and independently re-verify one depth-14 measured evidence bundle."""

    fixes = int(receipt.get("fixes", 0))
    name = wrapper_name(14, fixes) if fixes in FIX_COUNTS else str(receipt.get("config_id"))
    result: dict[str, Any] = {"config_id": name, "checks": {}, "trial_checks": []}
    checks = result["checks"]
    metrics = receipt.get("metrics", {})
    required_trials = int(receipt.get("measured_trials_required", 0))
    checks["strict_trial_cardinality"] = (
        receipt.get("warmup_status") == "verified"
        and required_trials > 0
        and receipt.get("measured_trials_completed") == required_trials
        and receipt.get("verified_trials") == required_trials
        and receipt.get("verification_failures") == 0
    )
    proof_hashes = receipt.get("independent_proof_hashes", [])
    checks["distinct_measured_proofs"] = (
        receipt.get("independent_proof_randomness_observed") is True
        and len(proof_hashes) == required_trials
        and len(set(proof_hashes)) == required_trials
    )
    checks["negative_gates_passed"] = receipt.get("negative_correctness_gates", {}).get("status") == "passed"
    checks["required_samples_per_stage"] = all(
        metrics.get(stage, {}).get("samples") == required_trials
        for stage in ("witness", "prove", "verify")
    )

    input_record = receipt.get("input", {})
    profile_record = receipt.get("policy_profile", {})
    input_path = _artifact_path(input_record)
    profile_path = _artifact_path(profile_record)
    checks["input_hash_matches"] = (
        input_path.is_file()
        and input_record.get("sha256") == sha256_file(input_path)
        and input_record.get("bytes") == input_path.stat().st_size
    )
    checks["profile_hash_matches"] = (
        profile_path.is_file()
        and profile_record.get("sha256") == sha256_file(profile_path)
        and profile_record.get("bytes") == profile_path.stat().st_size
    )
    binding = receipt.get("city_tariff_binding", {})
    paths = config_paths(output_dir, 14, fixes)
    setup_receipt_path = output_dir / "receipts" / "setup" / f"{name}.json"
    compile_receipt_path = output_dir / "receipts" / "compile" / f"{name}.json"
    setup_receipt = (
        json.loads(setup_receipt_path.read_text(encoding="utf-8"))
        if setup_receipt_path.is_file()
        else {}
    )
    compile_receipt = (
        json.loads(compile_receipt_path.read_text(encoding="utf-8"))
        if compile_receipt_path.is_file()
        else {}
    )
    checks["setup_preflight_ready"] = (
        setup_receipt.get("schema") == "waybill-m2-groth16-setup-receipt-v1"
        and setup_receipt.get("config_id") == name
        and setup_receipt.get("depth") == 14
        and setup_receipt.get("fixes") == fixes
        and setup_receipt.get("status") == "ready"
        and setup_receipt.get("zkey_matches_r1cs_and_ptau") is True
    )
    checks["compile_receipt_bound"] = (
        compile_receipt.get("schema") == "waybill-m2-circuit-compile-receipt-v1"
        and compile_receipt.get("config_id") == name
        and compile_receipt.get("depth") == 14
        and compile_receipt.get("fixes") == fixes
        and compile_receipt.get("status") == "compiled"
        and paths["r1cs"].is_file()
        and compile_receipt.get("artifacts", {}).get("r1cs", {}).get("sha256")
        == sha256_file(paths["r1cs"])
    )
    checks["setup_artifact_hashes_current"] = (
        paths["zkey"].is_file()
        and paths["vkey"].is_file()
        and setup_receipt.get("artifacts", {}).get("zkey", {}).get("sha256")
        == sha256_file(paths["zkey"])
        and setup_receipt.get("artifacts", {}).get("verification_key", {}).get("sha256")
        == sha256_file(paths["vkey"])
    )
    checks["setup_ptau_hash_bound"] = (
        setup_receipt.get("ptau", {}).get("blake2b") == PTAU_BLAKE2B
    )
    try:
        circuit_input = json.loads(input_path.read_text(encoding="utf-8"))
        profile = PolicyProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    except Exception as exc:
        result["load_error"] = f"{type(exc).__name__}: {exc}"
        circuit_input = {}
        profile = None
    checks["input_binding_matches"] = bool(circuit_input) and (
        circuit_input.get("tariff_root") == binding.get("tariff_root")
        and circuit_input.get("policy_profile_commitment") == binding.get("policy_profile_commitment")
        and [circuit_input.get(signal) for signal in PUBLIC_SIGNAL_ORDER_V6] == binding.get("public_signals")
    )
    checks["profile_binding_matches"] = profile is not None and (
        str(profile.commitment) == binding.get("policy_profile_commitment")
        and profile.profile_sha256 == binding.get("policy_profile_sha256")
        and profile.verification_key_hash == binding.get("verification_key_hash")
        and str(profile.tariff_root) == binding.get("tariff_root")
        and profile.circuit_id == name
        and profile.max_fixes == fixes
    )
    checks["vkey_hash_matches"] = (
        paths["vkey"].is_file()
        and binding.get("verification_key_hash") == sha256_file(paths["vkey"])
    )

    expected_public = [circuit_input.get(signal) for signal in PUBLIC_SIGNAL_ORDER_V6]
    trial_receipt_paths = receipt.get("trial_receipts", [])
    for trial_receipt_raw in trial_receipt_paths:
        trial_receipt_path = ROOT_DIR / str(trial_receipt_raw)
        trial_result: dict[str, Any] = {"receipt_path": str(trial_receipt_raw)}
        if not trial_receipt_path.is_file():
            trial_result["ok"] = False
            trial_result["error"] = "trial receipt missing"
            result["trial_checks"].append(trial_result)
            continue
        trial = json.loads(trial_receipt_path.read_text(encoding="utf-8"))
        trial_dir = trial_receipt_path.parent
        proof_path = trial_dir / "proof.json"
        public_path = trial_dir / "public.json"
        hashes_match = (
            proof_path.is_file()
            and public_path.is_file()
            and trial.get("proof_json_sha256") == sha256_file(proof_path)
            and trial.get("public_json_sha256") == sha256_file(public_path)
        )
        public_values = json.loads(public_path.read_text(encoding="utf-8")) if public_path.is_file() else []
        public_match = public_values == expected_public
        final_verify = (
            run_measured(
                [
                    "snarkjs",
                    "groth16",
                    "verify",
                    str(paths["vkey"]),
                    str(public_path),
                    str(proof_path),
                ],
                timeout_sec=600,
                environment_overrides={"NODE_OPTIONS": SNARKJS_NODE_OPTIONS},
            )
            if hashes_match
            else None
        )
        independently_verified = bool(
            final_verify and final_verify.status == "ok" and "OK" in final_verify.stdout_tail
        )
        trial_result.update(
            {
                "actual_proof_sha256": sha256_file(proof_path) if proof_path.is_file() else None,
                "hashes_match": hashes_match,
                "public_signals_match_input": public_match,
                "receipt_status_verified": trial.get("status") == "verified",
                "independent_final_verify": independently_verified,
                "verify_command": asdict(final_verify) if final_verify else None,
                "ok": (
                    hashes_match
                    and public_match
                    and trial.get("status") == "verified"
                    and independently_verified
                ),
            }
        )
        result["trial_checks"].append(trial_result)
    checks["measured_artifacts_reverified"] = (
        len(result["trial_checks"]) == required_trials
        and all(trial["ok"] for trial in result["trial_checks"])
    )
    checks["receipt_proof_hash_set_matches_artifacts"] = (
        set(proof_hashes)
        == {trial.get("actual_proof_sha256") for trial in result["trial_checks"]}
        and len(proof_hashes) == required_trials
    )
    result["passed"] = all(bool(value) for value in checks.values())
    return result


def artifact_record_matches_current(record: dict[str, Any]) -> bool:
    path = _artifact_path(record)
    return (
        path.is_file()
        and record.get("bytes") == path.stat().st_size
        and record.get("sha256") == sha256_file(path)
    )


def prune_compile_symbol_artifacts(output_dir: Path) -> dict[str, Any]:
    """Free non-gating Circom symbol files after preserving hash/size receipts."""

    receipt_path = output_dir / "receipts" / "prune" / "compile_symbols.json"
    prior = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}
    prior_by_config = {item.get("config_id"): item for item in prior.get("items", [])}
    disk_before = shutil.disk_usage(output_dir).free
    items: list[dict[str, Any]] = []
    for depth in DEPTHS:
        for fixes in FIX_COUNTS:
            name = wrapper_name(depth, fixes)
            compile_path = output_dir / "receipts" / "compile" / f"{name}.json"
            if not compile_path.is_file():
                items.append({"config_id": name, "status": "failed", "reason": "missing compile receipt"})
                continue
            compile_receipt = json.loads(compile_path.read_text(encoding="utf-8"))
            sym_record = compile_receipt.get("artifacts", {}).get("sym", {})
            sym_path = _artifact_path(sym_record)
            original_record = {
                "path": sym_record.get("path"),
                "bytes": sym_record.get("bytes"),
                "sha256": sym_record.get("sha256"),
            }
            prior_item = prior_by_config.get(name, {})
            if sym_path.is_file():
                if not artifact_record_matches_current(sym_record):
                    items.append(
                        {
                            "config_id": name,
                            "status": "failed",
                            "reason": "symbol file does not match the compile receipt; not deleted",
                            "original_artifact": original_record,
                        }
                    )
                    continue
                sym_path.unlink()
                status = "pruned"
            elif (
                compile_receipt.get("sym_pruned_after_receipt") is True
                and prior_item.get("original_artifact") == original_record
                and prior_item.get("status") in {"pruned", "already_pruned"}
            ):
                status = "already_pruned"
            else:
                items.append(
                    {
                        "config_id": name,
                        "status": "failed",
                        "reason": "symbol file is absent without a matching prior prune receipt",
                        "original_artifact": original_record,
                    }
                )
                continue
            compile_receipt.update(
                {
                    "sym_pruned_after_receipt": True,
                    "sym_prune_reason": "non-gating debug symbol; retain R1CS and WASM for setup/proof",
                    "sym_exists_after_prune": False,
                }
            )
            write_json(compile_path, compile_receipt)
            items.append(
                {
                    "config_id": name,
                    "depth": depth,
                    "fixes": fixes,
                    "status": status,
                    "original_artifact": original_record,
                    "exists_after_prune": sym_path.exists(),
                }
            )
    receipt = {
        "schema": "waybill-m2-compile-symbol-prune-receipt-v1",
        "generated_at": utc_now(),
        "execution_runner_sha256": sha256_file(Path(__file__).resolve()),
        "reason": (
            "Circom .sym files are debug-only and are not inputs to Groth16 setup, witness generation, "
            "proving, or verification; original hashes and byte sizes remain in compile receipts."
        ),
        "disk_free_bytes_before": disk_before,
        "disk_free_bytes_after": shutil.disk_usage(output_dir).free,
        "items": items,
        "status": (
            "passed"
            if len(items) == 16
            and all(item["status"] in {"pruned", "already_pruned"} for item in items)
            else "failed"
        ),
    }
    write_json(receipt_path, receipt)
    return receipt


def compile_symbol_prune_gate_passed(
    output_dir: Path, compile_receipts: Sequence[dict[str, Any]]
) -> bool:
    path = output_dir / "receipts" / "prune" / "compile_symbols.json"
    if not path.is_file():
        return False
    receipt = json.loads(path.read_text(encoding="utf-8"))
    expected = {wrapper_name(depth, fixes) for depth in DEPTHS for fixes in FIX_COUNTS}
    items = receipt.get("items", [])
    by_config = {item.get("config_id"): item for item in items}
    compile_by_config = {item.get("config_id"): item for item in compile_receipts}
    return (
        receipt.get("schema") == "waybill-m2-compile-symbol-prune-receipt-v1"
        and receipt.get("status") == "passed"
        and len(items) == 16
        and set(by_config) == expected
        and set(compile_by_config) == expected
        and all(
            compile_by_config[name].get("sym_pruned_after_receipt") is True
            and compile_by_config[name].get("sym_exists_after_prune") is False
            and by_config[name].get("status") in {"pruned", "already_pruned"}
            and by_config[name].get("original_artifact")
            == {
                "path": compile_by_config[name].get("artifacts", {}).get("sym", {}).get("path"),
                "bytes": compile_by_config[name].get("artifacts", {}).get("sym", {}).get("bytes"),
                "sha256": compile_by_config[name].get("artifacts", {}).get("sym", {}).get("sha256"),
            }
            and not _artifact_path(compile_by_config[name]["artifacts"]["sym"]).exists()
            for name in expected
        )
    )


def compile_receipt_matrix_shape_passed(receipts: Sequence[dict[str, Any]]) -> bool:
    expected = {
        wrapper_name(depth, fixes): (depth, fixes) for depth in DEPTHS for fixes in FIX_COUNTS
    }
    return (
        len(receipts) == 16
        and {receipt.get("config_id") for receipt in receipts} == set(expected)
        and all(
            receipt.get("schema") == "waybill-m2-circuit-compile-receipt-v1"
            and (receipt.get("depth"), receipt.get("fixes")) == expected.get(receipt.get("config_id"))
            and receipt.get("status") == "compiled"
            and "constraints" in receipt.get("r1cs_info", {})
            for receipt in receipts
        )
    )


def setup_receipt_matrix_real_attempts(receipts: Sequence[dict[str, Any]]) -> bool:
    expected = {
        wrapper_name(depth, fixes): (depth, fixes) for depth in DEPTHS for fixes in FIX_COUNTS
    }

    def setup_command_matches_config(receipt: dict[str, Any]) -> bool:
        config_id = receipt.get("config_id")
        command = receipt.get("setup", {}).get("command", [])
        return (
            isinstance(command, list)
            and len(command) >= 6
            and command[:3] == ["snarkjs", "groth16", "setup"]
            and Path(str(command[3])).name == f"{config_id}.r1cs"
            and Path(str(command[-1])).name == f"{config_id}_test_only.zkey"
        )

    return (
        len(receipts) == 16
        and {receipt.get("config_id") for receipt in receipts} == set(expected)
        and all(
            receipt.get("schema") == "waybill-m2-groth16-setup-receipt-v1"
            and (receipt.get("depth"), receipt.get("fixes"))
            == expected.get(receipt.get("config_id"))
            and setup_command_matches_config(receipt)
            and receipt.get("setup", {}).get("status") in {"ok", "failed"}
            for receipt in receipts
        )
    )


def depth14_proof_receipt_shape_passed(receipts: Sequence[dict[str, Any]]) -> bool:
    expected = {wrapper_name(14, fixes): fixes for fixes in FIX_COUNTS}
    return (
        len(receipts) == 4
        and {receipt.get("config_id") for receipt in receipts} == set(expected)
        and all(
            receipt.get("schema") == "waybill-m2-depth14-proof-summary-v1"
            and receipt.get("depth") == 14
            and receipt.get("fixes") == expected.get(receipt.get("config_id"))
            and receipt.get("status") == "verified"
            and receipt.get("warmup_status") == "verified"
            and int(receipt.get("measured_trials_required", 0)) > 0
            and receipt.get("measured_trials_completed")
            == receipt.get("measured_trials_required")
            and receipt.get("verified_trials") == receipt.get("measured_trials_required")
            and receipt.get("verification_failures") == 0
            and receipt.get("independent_proof_randomness_observed") is True
            and receipt.get("negative_correctness_gates", {}).get("status") == "passed"
            and all(
                receipt.get("metrics", {}).get(stage, {}).get("samples")
                == receipt.get("measured_trials_required")
                for stage in ("witness", "prove", "verify")
            )
            for receipt in receipts
        )
    )


def ptau_metadata_gate_passed(
    *,
    ptau_path: Path,
    receipt: dict[str, Any],
    setup_receipts: Sequence[dict[str, Any]],
    actual_blake2b: str | None,
) -> bool:
    depth14 = [item for item in setup_receipts if item.get("depth") == 14]
    depth14_bound = len(depth14) == 4 and all(
        item.get("ptau", {}).get("blake2b") == PTAU_BLAKE2B for item in depth14
    )
    return (
        ptau_path.is_file()
        and ptau_path.stat().st_size == PTAU_BYTES
        and actual_blake2b == PTAU_BLAKE2B
        and receipt.get("status") == "verified"
        and receipt.get("bytes") == PTAU_BYTES
        and receipt.get("actual_blake2b") == PTAU_BLAKE2B
        and receipt.get("expected_blake2b") == PTAU_BLAKE2B
        and depth14_bound
    )


def aggregate_matrix(output_dir: Path) -> dict[str, Any]:
    repair_compile_receipts(output_dir)
    d14_start_manifest_path = output_dir / "environment_manifest_d14_setup_start.json"
    if d14_start_manifest_path.exists():
        d14_start_manifest = json.loads(d14_start_manifest_path.read_text(encoding="utf-8"))
        d14_start_runner_sha = (
            d14_start_manifest.get("source_artifacts", {}).get("runner", {}).get("sha256")
        )
        current_runner_sha = sha256_file(Path(__file__).resolve())
        if d14_start_runner_sha:
            for setup_path in (output_dir / "receipts" / "setup").glob(
                "settlement_period_v6_d14_*.json"
            ):
                setup_receipt = json.loads(setup_path.read_text(encoding="utf-8"))
                if setup_receipt.get("setup", {}).get("command"):
                    setup_receipt["execution_lineage"] = {
                        "execution_runner_sha256": d14_start_runner_sha,
                        "current_runner_sha256_at_aggregation": current_runner_sha,
                        "delta_scope": (
                            "Post-start changes affect M2 cap/profile proof input, negative proof gates, "
                            "aggregate validation, and non-depth14 setup verification/pruning scope; "
                            "they do not retroactively claim to have generated depth14 setup artifacts."
                        ),
                    }
                    write_json(setup_path, setup_receipt)
    compile_receipts: list[dict[str, Any]] = []
    setup_receipts: list[dict[str, Any]] = []
    proof_receipts: list[dict[str, Any]] = []
    for path in sorted((output_dir / "receipts" / "compile").glob("*.json")):
        compile_receipts.append(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted((output_dir / "receipts" / "setup").glob("*.json")):
        setup_receipts.append(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted((output_dir / "receipts" / "proof").glob("*.json")):
        proof_receipts.append(json.loads(path.read_text(encoding="utf-8")))
    compile_r1cs_wasm_artifacts_current = all(
        all(
            artifact_record_matches_current(receipt.get("artifacts", {}).get(name, {}))
            for name in ("r1cs", "wasm")
        )
        for receipt in compile_receipts
    )
    compile_symbols_pruned_with_receipts = compile_symbol_prune_gate_passed(
        output_dir, compile_receipts
    )
    all_compile = (
        compile_receipt_matrix_shape_passed(compile_receipts)
        and compile_r1cs_wasm_artifacts_current
        and compile_symbols_pruned_with_receipts
    )
    depth14_receipt_shape_passed = depth14_proof_receipt_shape_passed(proof_receipts)
    tariff_manifest = json.loads(TARIFF_MANIFEST_PATH.read_text(encoding="utf-8"))
    membership_path = M2_DIR / "membership_samples_depth14.json"
    membership = json.loads(membership_path.read_text(encoding="utf-8"))
    canonical_tariff_root = str(tariff_manifest.get("tariff_root"))
    actual_tariff, _loaded_manifest = load_city_tariff(fresh=True)
    actual_tariff_root = str(actual_tariff.root(14))
    source_path = ROOT_DIR / "dataset" / "osm" / "zones" / "rome_medium.geojson"
    generator_path = ROOT_DIR / "script" / "build_waybill_m2_tariff.py"
    expanded_source = tariff_builder.expand_source_geojson(source_path)
    independent_fresh_root = str(
        tariff_builder.independent_root(
            expanded_source.cells,
            tariff_version=expanded_source.tariff_version,
            depth=14,
        )
    )
    declared_artifacts = tariff_manifest.get("artifacts", {})
    declared_tariff_record = declared_artifacts.get("tariff_cells", {})
    declared_membership_record = declared_artifacts.get("membership_samples", {})
    tariff_hash_matches_manifest = (
        declared_tariff_record.get("path") == TARIFF_PATH.name
        and declared_tariff_record.get("sha256") == sha256_file(TARIFF_PATH)
    )
    membership_hash_matches_manifest = (
        declared_membership_record.get("path") == membership_path.name
        and declared_membership_record.get("sha256") == sha256_file(membership_path)
    )
    source_hash_matches_manifest = (
        tariff_manifest.get("source", {}).get("path")
        == str(source_path.relative_to(ROOT_DIR))
        and tariff_manifest.get("source", {}).get("sha256") == sha256_file(source_path)
    )
    generator_hash_matches_manifest = (
        tariff_manifest.get("generator", {}).get("path")
        == str(generator_path.relative_to(ROOT_DIR))
        and tariff_manifest.get("generator", {}).get("sha256") == sha256_file(generator_path)
    )
    membership_sample_checks: list[dict[str, Any]] = []
    for sample in membership.get("samples", []):
        cell_idx = int(sample.get("cell_idx", -1))
        try:
            actual_zone = actual_tariff.zone_for_cell(cell_idx)
            actual_rate = actual_tariff.rate_for_zone(actual_zone)
            actual_leaf = actual_tariff.leaf_for_cell(cell_idx)
            common_verified = verify_merkle_path(
                int(sample["leaf"]), sample["path"], int(canonical_tariff_root)
            )
            independent_verified = tariff_builder.independent_verify_path(
                int(sample["leaf"]), sample["path"], int(canonical_tariff_root)
            )
            check = {
                "cell_idx": cell_idx,
                "zone_matches": actual_zone == int(sample["zone_id"]),
                "rate_matches": actual_rate == int(sample["normalized_rate"]),
                "leaf_matches": actual_leaf == int(sample["leaf"]),
                "common_path_verified": common_verified,
                "independent_path_verified": independent_verified,
            }
            check["passed"] = all(value for key, value in check.items() if key != "cell_idx")
        except Exception as exc:
            check = {"cell_idx": cell_idx, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        membership_sample_checks.append(check)
    membership_samples_reverified = (
        len(membership_sample_checks) >= 12 and all(check["passed"] for check in membership_sample_checks)
    )
    artifact_intrinsic_gate = all(
        (
            int(tariff_manifest.get("tariff", {}).get("real_valid_cell_count", 0)) == 10_000,
            int(tariff_manifest.get("tree", {}).get("depth", 0)) == 14,
            tariff_manifest.get("root_recomputation", {}).get("roots_match") is True,
            tariff_manifest.get("membership_validation", {}).get(
                "all_samples_verified_by_common_and_independent_implementations"
            )
            is True,
            str(membership.get("tariff_root")) == canonical_tariff_root,
            int(membership.get("tree_depth", 0)) == 14,
            len(membership.get("samples", [])) >= 12,
            all(len(sample.get("path", [])) == 14 for sample in membership.get("samples", [])),
            tariff_hash_matches_manifest,
            membership_hash_matches_manifest,
            source_hash_matches_manifest,
            generator_hash_matches_manifest,
            membership_samples_reverified,
            len(actual_tariff.cell_zones) == 10_000,
            actual_tariff_root == canonical_tariff_root,
            independent_fresh_root == canonical_tariff_root,
        )
    )
    all_four_proofs_bind_tariff = len(proof_receipts) == 4 and all(
        receipt.get("city_tariff_binding", {}).get("tariff_root") == canonical_tariff_root
        and int(receipt.get("city_tariff_binding", {}).get("real_tariff_cells", 0)) == 10_000
        for receipt in proof_receipts
    )
    tariff_artifact_gate = artifact_intrinsic_gate and all_four_proofs_bind_tariff
    terminal_proof_validation = [
        validate_depth14_proof_evidence(output_dir=output_dir, receipt=receipt)
        for receipt in proof_receipts
    ]
    terminal_proof_validation_passed = (
        len(terminal_proof_validation) == 4
        and all(result.get("passed") is True for result in terminal_proof_validation)
    )
    depth14_proof = depth14_receipt_shape_passed and terminal_proof_validation_passed
    setup_attempted = setup_receipt_matrix_real_attempts(setup_receipts)
    ptau_path = output_dir / "ptau" / PTAU_FILENAME
    ptau_receipt_path = output_dir / "ptau_receipt.json"
    ptau_receipt = (
        json.loads(ptau_receipt_path.read_text(encoding="utf-8"))
        if ptau_receipt_path.is_file()
        else {}
    )
    actual_ptau_blake2b = blake2b_file(ptau_path) if ptau_path.is_file() else None
    depth14_setups_bind_ptau = all(
        receipt.get("ptau", {}).get("blake2b") == PTAU_BLAKE2B
        for receipt in setup_receipts
        if receipt.get("depth") == 14
    ) and sum(receipt.get("depth") == 14 for receipt in setup_receipts) == 4
    ptau_gate_passed = ptau_metadata_gate_passed(
        ptau_path=ptau_path,
        receipt=ptau_receipt,
        setup_receipts=setup_receipts,
        actual_blake2b=actual_ptau_blake2b,
    )
    setup_by_config = {receipt["config_id"]: receipt for receipt in setup_receipts}
    aggregate_dir = output_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    compile_csv = aggregate_dir / "compile_setup_matrix.csv"
    compile_fields = [
        "config_id",
        "depth",
        "fixes",
        "constraints",
        "non_linear_constraints",
        "linear_constraints",
        "compile_ms",
        "compile_max_rss_bytes",
        "r1cs_bytes",
        "wasm_bytes",
        "sym_bytes",
        "setup_status",
        "setup_ms",
        "setup_max_rss_bytes",
        "zkey_verify_status",
        "zkey_bytes_before_prune",
        "vkey_bytes",
        "zkey_pruned_after_receipt",
    ]
    with compile_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=compile_fields)
        writer.writeheader()
        for compile_receipt in sorted(compile_receipts, key=lambda row: (row["depth"], row["fixes"])):
            setup_receipt = setup_by_config.get(compile_receipt["config_id"], {})
            compiler_info = compile_receipt.get("compiler_info", {})
            writer.writerow(
                {
                    "config_id": compile_receipt["config_id"],
                    "depth": compile_receipt["depth"],
                    "fixes": compile_receipt["fixes"],
                    "constraints": compile_receipt.get("r1cs_info", {}).get("constraints"),
                    "non_linear_constraints": compiler_info.get("non_linear_constraints"),
                    "linear_constraints": compiler_info.get("linear_constraints"),
                    "compile_ms": compile_receipt.get("compile", {}).get("elapsed_ms"),
                    "compile_max_rss_bytes": compile_receipt.get("compile", {}).get("max_rss_bytes"),
                    "r1cs_bytes": compile_receipt.get("artifacts", {}).get("r1cs", {}).get("bytes"),
                    "wasm_bytes": compile_receipt.get("artifacts", {}).get("wasm", {}).get("bytes"),
                    "sym_bytes": compile_receipt.get("artifacts", {}).get("sym", {}).get("bytes"),
                    "setup_status": setup_receipt.get("status", "missing"),
                    "setup_ms": setup_receipt.get("setup", {}).get("elapsed_ms"),
                    "setup_max_rss_bytes": setup_receipt.get("setup", {}).get("max_rss_bytes"),
                    "zkey_verify_status": setup_receipt.get("zkey_matches_r1cs_and_ptau"),
                    "zkey_bytes_before_prune": setup_receipt.get("artifacts", {}).get("zkey", {}).get("bytes"),
                    "vkey_bytes": setup_receipt.get("artifacts", {}).get("verification_key", {}).get("bytes"),
                    "zkey_pruned_after_receipt": setup_receipt.get("artifact_pruned_after_receipt"),
                }
            )
    proof_csv = aggregate_dir / "depth14_proof_metrics.csv"
    proof_fields = [
        "config_id",
        "fixes",
        "status",
        "verified_trials",
        "witness_p50_ms",
        "witness_p95_ms",
        "prove_p50_ms",
        "prove_p95_ms",
        "verify_p50_ms",
        "verify_p95_ms",
        "end_to_end_p50_ms",
        "end_to_end_p95_ms",
        "proofs_per_hour_p50",
        "proof_json_bytes",
        "tariff_root",
        "policy_profile_commitment",
        "verification_key_hash",
    ]
    with proof_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=proof_fields)
        writer.writeheader()
        for proof_receipt in sorted(proof_receipts, key=lambda row: row.get("fixes", 0)):
            metrics = proof_receipt.get("metrics", {})
            binding = proof_receipt.get("city_tariff_binding", {})
            writer.writerow(
                {
                    "config_id": proof_receipt.get("config_id"),
                    "fixes": proof_receipt.get("fixes"),
                    "status": proof_receipt.get("status"),
                    "verified_trials": proof_receipt.get("verified_trials"),
                    "witness_p50_ms": metrics.get("witness", {}).get("elapsed_ms_p50"),
                    "witness_p95_ms": metrics.get("witness", {}).get("elapsed_ms_p95_nearest_rank"),
                    "prove_p50_ms": metrics.get("prove", {}).get("elapsed_ms_p50"),
                    "prove_p95_ms": metrics.get("prove", {}).get("elapsed_ms_p95_nearest_rank"),
                    "verify_p50_ms": metrics.get("verify", {}).get("elapsed_ms_p50"),
                    "verify_p95_ms": metrics.get("verify", {}).get("elapsed_ms_p95_nearest_rank"),
                    "end_to_end_p50_ms": metrics.get("end_to_end_ms_p50"),
                    "end_to_end_p95_ms": metrics.get("end_to_end_ms_p95_nearest_rank"),
                    "proofs_per_hour_p50": metrics.get("proofs_per_hour_at_p50"),
                    "proof_json_bytes": json.dumps(metrics.get("proof_json_bytes", []), separators=(",", ":")),
                    "tariff_root": binding.get("tariff_root"),
                    "policy_profile_commitment": binding.get("policy_profile_commitment"),
                    "verification_key_hash": binding.get("verification_key_hash"),
                }
            )

    # Deterministic SVG plots are regenerated from receipts; no GUI or
    # external plotting service is involved.
    import matplotlib  # noqa: PLC0415

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    for depth in DEPTHS:
        rows = sorted(
            (receipt for receipt in compile_receipts if receipt["depth"] == depth),
            key=lambda receipt: receipt["fixes"],
        )
        axis.plot(
            [receipt["fixes"] for receipt in rows],
            [receipt.get("r1cs_info", {}).get("constraints") for receipt in rows],
            marker="o",
            label=f"depth {depth}",
        )
    axis.set_xlabel("Fixes per proof")
    axis.set_ylabel("R1CS constraints")
    axis.set_title("WayBill V6 circuit scaling")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    constraints_plot = aggregate_dir / "constraints_scaling.svg"
    figure.savefig(constraints_plot, format="svg", metadata={"Date": None})
    plt.close(figure)

    latency_plot = aggregate_dir / "depth14_proof_latency.svg"
    if proof_receipts:
        figure, axis = plt.subplots(figsize=(7.2, 4.4))
        ordered_proofs = sorted(proof_receipts, key=lambda receipt: receipt.get("fixes", 0))
        for stage, label in (("witness", "witness"), ("prove", "prove"), ("verify", "verify")):
            axis.plot(
                [receipt.get("fixes") for receipt in ordered_proofs],
                [receipt.get("metrics", {}).get(stage, {}).get("elapsed_ms_p50") for receipt in ordered_proofs],
                marker="o",
                label=f"{label} p50",
            )
        axis.set_xlabel("Fixes per proof (depth 14)")
        axis.set_ylabel("Latency (ms, log scale)")
        axis.set_yscale("log")
        axis.set_title("Depth-14 Groth16 latency")
        axis.grid(True, alpha=0.25)
        axis.legend()
        figure.tight_layout()
        figure.savefig(latency_plot, format="svg", metadata={"Date": None})
        plt.close(figure)
    terminal_validation_receipt = {
        "schema": "waybill-m2-terminal-evidence-validation-v1",
        "generated_at": utc_now(),
        "execution_runner_sha256": sha256_file(Path(__file__).resolve()),
        "environment_manifest": artifact_record(output_dir / "environment_manifest.json"),
        "membership_samples_reverified": membership_samples_reverified,
        "membership_sample_checks": membership_sample_checks,
        "compile_expected_configs_r1cs_wasm_current_and_symbols_pruned_passed": all_compile,
        "compile_r1cs_wasm_artifacts_current": compile_r1cs_wasm_artifacts_current,
        "compile_symbols_pruned_with_receipts": compile_symbols_pruned_with_receipts,
        "all_16_real_setup_attempts_present": setup_attempted,
        "ptau_gate_passed": ptau_gate_passed,
        "ptau": {
            "path": str(ptau_path.relative_to(ROOT_DIR)),
            "bytes": ptau_path.stat().st_size if ptau_path.is_file() else None,
            "actual_blake2b": actual_ptau_blake2b,
            "official_blake2b": PTAU_BLAKE2B,
            "depth14_setups_bind_same_hash": depth14_setups_bind_ptau,
        },
        "tariff_artifact_gate_passed": tariff_artifact_gate,
        "depth14_receipt_shape_passed": depth14_receipt_shape_passed,
        "terminal_proof_validation_passed": terminal_proof_validation_passed,
        "proof_bundles": terminal_proof_validation,
        "passed": (
            all_compile
            and setup_attempted
            and ptau_gate_passed
            and tariff_artifact_gate
            and membership_samples_reverified
            and terminal_proof_validation_passed
        ),
    }
    terminal_validation_receipt["run_id"] = hashlib.sha256(
        json.dumps(terminal_validation_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    final_validation_path = output_dir / "receipts" / "final_validation.json"
    write_json(final_validation_path, terminal_validation_receipt)
    m2_hard_gate_passed = (
        all_compile
        and depth14_proof
        and tariff_artifact_gate
        and setup_attempted
        and ptau_gate_passed
        and terminal_validation_receipt["passed"]
    )
    summary = {
        "schema": "waybill-m2-circuit-matrix-summary-v1",
        "generated_at": utc_now(),
        "compile_receipts": len(compile_receipts),
        "all_16_compile_constraint_receipts_pass": all_compile,
        "compile_r1cs_wasm_artifacts_current": compile_r1cs_wasm_artifacts_current,
        "compile_symbols_pruned_with_receipts": compile_symbols_pruned_with_receipts,
        "compile_symbol_prune_receipt": artifact_record(
            output_dir / "receipts" / "prune" / "compile_symbols.json"
        ),
        "setup_receipts": len(setup_receipts),
        "all_16_setup_attempted": setup_attempted,
        "ptau_gate_passed": ptau_gate_passed,
        "ptau_gate": {
            "official_source": PTAU_SOURCE,
            "expected_bytes": PTAU_BYTES,
            "actual_bytes": ptau_path.stat().st_size if ptau_path.is_file() else None,
            "official_blake2b": PTAU_BLAKE2B,
            "actual_blake2b": actual_ptau_blake2b,
            "receipt_status": ptau_receipt.get("status"),
            "depth14_setups_bind_same_hash": depth14_setups_bind_ptau,
        },
        "setup_ready": sum(receipt.get("status") == "ready" for receipt in setup_receipts),
        "setup_failed": sum(receipt.get("status") != "ready" for receipt in setup_receipts),
        "setup_zkeys_pruned_after_receipt": sum(
            bool(receipt.get("artifact_pruned_after_receipt")) for receipt in setup_receipts
        ),
        "aggregate_artifacts": {
            "compile_setup_csv": artifact_record(compile_csv),
            "depth14_proof_csv": artifact_record(proof_csv),
            "constraints_scaling_plot": artifact_record(constraints_plot),
            "depth14_latency_plot": artifact_record(latency_plot),
        },
        "depth14_proof_receipts": len(proof_receipts),
        "all_depth14_warmup_plus_measured_verified_pass": depth14_proof,
        "depth14_receipt_shape_passed": depth14_receipt_shape_passed,
        "terminal_proof_validation_passed": terminal_proof_validation_passed,
        "terminal_validation_receipt": artifact_record(final_validation_path),
        "current_runner_sha256": sha256_file(Path(__file__).resolve()),
        "environment_manifest": artifact_record(output_dir / "environment_manifest.json"),
        "tariff_artifact_gate_passed": tariff_artifact_gate,
        "tariff_artifact_gate": {
            "intrinsic_manifest_and_membership_passed": artifact_intrinsic_gate,
            "real_valid_cell_count": tariff_manifest.get("tariff", {}).get("real_valid_cell_count"),
            "tree_depth": tariff_manifest.get("tree", {}).get("depth"),
            "primary_and_independent_roots_match": tariff_manifest.get("root_recomputation", {}).get(
                "roots_match"
            ),
            "all_membership_samples_verified": tariff_manifest.get("membership_validation", {}).get(
                "all_samples_verified_by_common_and_independent_implementations"
            ),
            "membership_sample_count": len(membership.get("samples", [])),
            "canonical_tariff_root": canonical_tariff_root,
            "all_four_depth14_proofs_bind_same_root": all_four_proofs_bind_tariff,
            "tariff_file_sha_matches_manifest": tariff_hash_matches_manifest,
            "membership_file_sha_matches_manifest": membership_hash_matches_manifest,
            "source_file_sha_matches_manifest": source_hash_matches_manifest,
            "generator_file_sha_matches_manifest": generator_hash_matches_manifest,
            "actual_tariff_cell_count": len(actual_tariff.cell_zones),
            "actual_recomputed_tariff_root": actual_tariff_root,
            "independent_fresh_tariff_root": independent_fresh_root,
            "membership_samples_reverified": membership_samples_reverified,
            "membership_sample_checks": membership_sample_checks,
        },
        "m2_hard_gate_passed": m2_hard_gate_passed,
        "claim_boundary": (
            "M2 normalized-test-unit capacity benchmark passed through depth 14 x 200 fixes; "
            "this is not a real Rome billing tariff or a production-security certification"
            if m2_hard_gate_passed
            else "M2 capacity benchmark is incomplete or failed; no real-billing or production deployment claim"
        ),
        "compile_matrix": [
            {
                "config_id": receipt["config_id"],
                "depth": receipt["depth"],
                "fixes": receipt["fixes"],
                "status": receipt["status"],
                "constraints": receipt.get("r1cs_info", {}).get("constraints"),
                "compile_ms": receipt.get("compile", {}).get("elapsed_ms"),
                "compile_max_rss_bytes": receipt.get("compile", {}).get("max_rss_bytes"),
                "r1cs_bytes": receipt.get("artifacts", {}).get("r1cs", {}).get("bytes"),
                "wasm_bytes": receipt.get("artifacts", {}).get("wasm", {}).get("bytes"),
            }
            for receipt in compile_receipts
        ],
        "depth14_proof_matrix": [
            {
                "config_id": receipt.get("config_id"),
                "fixes": receipt.get("fixes"),
                "status": receipt.get("status"),
                "verified_trials": receipt.get("verified_trials", 0),
                "metrics": receipt.get("metrics"),
                "failure": receipt.get("failure"),
            }
            for receipt in proof_receipts
        ],
        "setup_matrix": [
            {
                "config_id": receipt.get("config_id"),
                "depth": receipt.get("depth"),
                "fixes": receipt.get("fixes"),
                "status": receipt.get("status"),
                "setup_ms": receipt.get("setup", {}).get("elapsed_ms"),
                "setup_max_rss_bytes": receipt.get("setup", {}).get("max_rss_bytes"),
                "zkey_matches_r1cs_and_ptau": receipt.get("zkey_matches_r1cs_and_ptau"),
                "zkey_bytes_before_prune": receipt.get("artifacts", {}).get("zkey", {}).get("bytes"),
                "vkey_bytes": receipt.get("artifacts", {}).get("verification_key", {}).get("bytes"),
                "artifact_pruned_after_receipt": receipt.get("artifact_pruned_after_receipt", False),
                "failure": receipt.get("failure"),
            }
            for receipt in sorted(setup_receipts, key=lambda row: (row.get("depth", 0), row.get("fixes", 0)))
        ],
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("compile", "prune-sym", "setup", "prove", "aggregate", "all"),
        default="all",
    )
    parser.add_argument("--configs", default="", help="comma-separated selectors such as d14n25,d14n50")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR.relative_to(ROOT_DIR)))
    parser.add_argument("--ptau", default=str((DEFAULT_OUTPUT_DIR / "ptau" / PTAU_FILENAME).relative_to(ROOT_DIR)))
    parser.add_argument("--download-ptau", action="store_true")
    parser.add_argument("--compile-timeout-sec", type=int, default=3600)
    parser.add_argument("--setup-timeout-sec", type=int, default=7200)
    parser.add_argument("--proof-stage-timeout-sec", type=int, default=3600)
    parser.add_argument("--download-timeout-sec", type=int, default=7200)
    parser.add_argument("--measured-trials", type=int, default=3)
    args = parser.parse_args()
    output_dir = (ROOT_DIR / args.output_dir).resolve()
    ptau = (ROOT_DIR / args.ptau).resolve()
    configs = selected_configs(args.configs)
    output_dir.mkdir(parents=True, exist_ok=True)
    environment_manifest(output_dir, ptau=ptau, measured_trials=args.measured_trials)
    if args.phase == "prune-sym":
        print(json.dumps(prune_compile_symbol_artifacts(output_dir), indent=2, sort_keys=True))
        return

    phases = (
        ("compile", "prune-sym", "setup", "prove", "aggregate")
        if args.phase == "all"
        else (args.phase,)
    )
    if "compile" in phases:
        for depth, fixes in configs:
            compile_one(output_dir, depth, fixes, timeout_sec=args.compile_timeout_sec)
    if "prune-sym" in phases:
        prune_compile_symbol_artifacts(output_dir)
    if "setup" in phases or "prove" in phases:
        ptau_receipt = ensure_ptau(
            ptau,
            allow_download=args.download_ptau,
            timeout_sec=args.download_timeout_sec,
        )
        write_json(output_dir / "ptau_receipt.json", ptau_receipt)
        if ptau_receipt["status"] != "verified":
            if "setup" in phases:
                for depth, fixes in configs:
                    receipt = {
                        "schema": "waybill-m2-groth16-setup-receipt-v1",
                        "config_id": wrapper_name(depth, fixes),
                        "depth": depth,
                        "fixes": fixes,
                        "status": "failed",
                        "failure": {"stage": "ptau_preflight", "reason": ptau_receipt.get("error")},
                    }
                    write_json(
                        output_dir / "receipts" / "setup" / f"{wrapper_name(depth, fixes)}.json",
                        receipt,
                    )
            print(json.dumps(ptau_receipt, indent=2, sort_keys=True))
            raise SystemExit(2)
    if "setup" in phases:
        # Proof-gating depth 14 goes first.  If later stress setups exhaust the
        # resource envelope, the city-scale proof evidence remains runnable.
        setup_order = sorted(configs, key=lambda item: (item[0] != 14, item[0], item[1]))
        for depth, fixes in setup_order:
            setup_one(
                output_dir,
                depth,
                fixes,
                ptau=ptau,
                timeout_sec=args.setup_timeout_sec,
            )
    if "prove" in phases:
        depth14_fixes = [fixes for depth, fixes in configs if depth == 14]
        for fixes in depth14_fixes:
            prove_depth14_one(
                output_dir,
                fixes,
                timeout_sec=args.proof_stage_timeout_sec,
                measured_trials=args.measured_trials,
            )
    summary = aggregate_matrix(output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
