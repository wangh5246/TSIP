#!/usr/bin/env python3
"""Build and prove the versioned V6 odometer-backed settlement relation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.eval_harness import HarnessParams  # noqa: E402
from common.policy_profile import PolicyProfile  # noqa: E402
from common.receiver_signer import receiver_log_body, receiver_log_sha256  # noqa: E402
from common.settlement import (  # noqa: E402
    SETTLEMENT_POSITION_VALIDITY_RULE,
    ReceiverFix,
    TariffTable,
    field_from_text,
    make_device_attestation_commitment,
    month_window_from_period_start,
    receiver_attestation_sha256,
    sign_receiver_root_attestation,
    sign_receiver_fix,
)
from common.settlement_v6 import (  # noqa: E402
    PUBLIC_SIGNAL_COUNT_V6,
    PUBLIC_SIGNAL_ORDER_V6,
    build_period_public_statement_v6,
    compute_receiver_fix_root_v6,
    fee_for_period_v6,
    verify_period_submission_v6,
)


N_FIXES = 25
TREE_DEPTH = 8
CADENCE_SEC = 300
MAX_DT_SEC = 600
TIER_VMAX_MPS = 33
TIER_VMAX_SQ = TIER_VMAX_MPS * TIER_VMAX_MPS
MODE_VMAX_SQ = TIER_VMAX_SQ
CAP_POLICY_SQ = 3_000_000_000
CELL_SIZE = 100
GRID_W = 100
SETTLEMENT_PROFILE = "k6"
DEFAULT_TEST_CHARGER_DOMAIN = "ruc-demo.charger-test"

# Short aliases retained for tooling that imports the prover module directly.
PUBLIC_SIGNAL_ORDER = PUBLIC_SIGNAL_ORDER_V6
PUBLIC_SIGNAL_COUNT = PUBLIC_SIGNAL_COUNT_V6

_DEVICE_SEED = hashlib.sha256(b"tsip-prove-v6-device-key").digest()
_DEVICE_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_DEVICE_SEED)
_DEVICE_PUBLIC_KEY_BYTES = _DEVICE_PRIVATE_KEY.public_key().public_bytes_raw()
_DEVICE_DAC = make_device_attestation_commitment(_DEVICE_PUBLIC_KEY_BYTES)
MAX_RECEIVER_RESPONSE_BYTES = 4 * 1024 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def receiver_url_context(
    receiver_url: str,
    *,
    ca_file: str = "",
    allow_insecure_http: bool = False,
) -> ssl.SSLContext | None:
    parsed = urlsplit(receiver_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("receiver URL must not contain credentials, query, or fragment")
    if not parsed.hostname:
        raise RuntimeError("receiver URL must contain a hostname")
    if parsed.scheme == "http":
        if allow_insecure_http:
            return None
        raise RuntimeError(
            "paper-facing receiver access requires HTTPS; insecure HTTP is test-only"
        )
    if parsed.scheme != "https":
        raise RuntimeError("receiver URL must use HTTPS")
    context = ssl.create_default_context()
    if ca_file:
        ca_path = Path(ca_file).expanduser()
        if not ca_path.is_absolute():
            ca_path = (ROOT_DIR / ca_path).resolve()
        if not ca_path.is_file() or ca_path.is_symlink():
            raise RuntimeError("receiver CA file is missing or unsafe")
        context = ssl.create_default_context(cafile=str(ca_path))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _strict_json_bytes(payload: bytes, *, label: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise RuntimeError(f"{label} contains a duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload,
            object_pairs_hook=pairs,
            parse_constant=lambda raw: (_ for _ in ()).throw(
                RuntimeError(f"{label} contains a non-finite JSON number: {raw}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def fetch_receiver_json(
    request: urllib.request.Request,
    *,
    ssl_context: ssl.SSLContext | None,
    timeout: int = 30,
) -> dict[str, Any]:
    handlers: list[Any] = [urllib.request.ProxyHandler({}), _NoRedirectHandler()]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(request, timeout=timeout) as response:
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_RECEIVER_RESPONSE_BYTES:
                    raise RuntimeError("receiver response exceeds the configured size limit")
            except ValueError as exc:
                raise RuntimeError("receiver returned an invalid Content-Length") from exc
        payload = response.read(MAX_RECEIVER_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RECEIVER_RESPONSE_BYTES:
        raise RuntimeError("receiver response exceeds the configured size limit")
    return _strict_json_bytes(payload, label="receiver response")


def field_str(value: Any) -> str:
    return str(int(value))


def build_test_root_attestation(
    *,
    fixes: Sequence[ReceiverFix],
    position_valid: Sequence[bool],
    policy_profile_commitment: int,
    receiver_fix_root: str | int,
    charger_domain: str = DEFAULT_TEST_CHARGER_DOMAIN,
) -> dict[str, Any]:
    """Build a clearly labeled in-process attestation for unit/artifact tests.

    The paper-facing CLI replaces this value with material fetched from the
    independent receiver process.  Keeping the primitive here allows circuit
    matrix tests to build deterministic endpoint bundles without claiming a
    process boundary.
    """

    body = receiver_log_body(
        receiver_id="waybill-test-receiver",
        charger_domain=charger_domain,
        device_id=str(fixes[0].device_id),
        period_id=str(fixes[0].period_id),
        fixes_payload=[fix.to_dict() for fix in fixes],
        position_valid=position_valid,
        policy_profile_commitment=policy_profile_commitment,
        receiver_fix_root=receiver_fix_root,
        device_attestation_commitment=_DEVICE_DAC,
    )
    return sign_receiver_root_attestation(
        receiver_id="waybill-test-receiver",
        charger_domain=charger_domain,
        device_id=str(fixes[0].device_id),
        period_id=str(fixes[0].period_id),
        log_epoch=1,
        fix_count=len(fixes),
        receiver_fix_root=receiver_fix_root,
        device_attestation_commitment=_DEVICE_DAC,
        log_sha256=receiver_log_sha256(body),
        private_key_bytes=_DEVICE_SEED,
    )


def fetch_receiver_period_material(
    *,
    receiver_url: str,
    device_id: str,
    period_id: str,
    prover_token: str,
    ssl_context: ssl.SSLContext | None = None,
) -> dict[str, Any]:
    endpoint = (
        f"{receiver_url.rstrip('/')}/v2/receiver/logs/"
        f"{quote(device_id, safe='')}/{quote(period_id, safe='')}/attestation"
    )
    try:
        request = urllib.request.Request(
            endpoint,
            headers={"Authorization": f"Bearer {prover_token}"},
        )
        payload = fetch_receiver_json(request, ssl_context=ssl_context)
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        raise RuntimeError(f"cannot fetch sealed receiver attestation: {exc}") from exc
    if payload.get("schema") != "waybill.receiver.period-material/v2":
        raise RuntimeError("receiver returned an unsupported period-material schema")
    if not isinstance(payload.get("position_valid"), list):
        raise RuntimeError("receiver period material lacks position_valid")
    if payload.get("position_validity_rule") != SETTLEMENT_POSITION_VALIDITY_RULE:
        raise RuntimeError("receiver period material uses an unsupported validity rule")
    if not isinstance(payload.get("fixes"), list):
        raise RuntimeError("receiver period material lacks signed fixes")
    public_key_hex = payload.get("receiver_public_key_hex")
    if not isinstance(public_key_hex, str) or len(public_key_hex) != 64:
        raise RuntimeError("receiver period material lacks a valid public key")
    if not isinstance(payload.get("attestation"), dict):
        raise RuntimeError("receiver period material lacks an attestation")
    return payload


def fetch_receiver_month_attestation(
    *,
    receiver_url: str,
    device_id: str,
    month_id: str,
    prover_token: str,
    ssl_context: ssl.SSLContext | None = None,
) -> dict[str, Any]:
    endpoint = (
        f"{receiver_url.rstrip('/')}/v2/receiver/months/"
        f"{quote(device_id, safe='')}/{quote(month_id, safe='')}/attestation"
    )
    try:
        request = urllib.request.Request(
            endpoint,
            headers={"Authorization": f"Bearer {prover_token}"},
        )
        payload = fetch_receiver_json(request, ssl_context=ssl_context)
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        raise RuntimeError(f"cannot fetch sealed receiver month attestation: {exc}") from exc
    if payload.get("schema") != "waybill.receiver.month-material/v2":
        raise RuntimeError("receiver returned an unsupported month-material schema")
    if not isinstance(payload.get("attestation"), dict):
        raise RuntimeError("receiver month material lacks an attestation")
    attestation = dict(payload["attestation"])
    attestation.pop("month_epoch", None)
    return attestation


def run(cmd: list[str], *, cwd: Path = ROOT_DIR, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stdout}")
    return proc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_circomlib_include(explicit: str = "") -> Path:
    candidates = [
        Path(explicit) if explicit else None,
        ROOT_DIR / "node_modules",
        ROOT_DIR / "TSIP_heatmap_version" / "runtime" / "experiments-heatmap" / "node_modules",
        Path.home() / "node_modules",
    ]
    for candidate in candidates:
        if candidate is not None and (candidate / "circomlib").is_dir():
            return candidate.resolve()
    raise FileNotFoundError("circomlib include directory was not found")


def compile_circuit(artifact_dir: Path, *, circomlib_include: str = "") -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    circuit_name = f"settlement_period_v6_{SETTLEMENT_PROFILE}"
    circuit_path = ROOT_DIR / "experiments-heatmap" / "circuits" / f"{circuit_name}.circom"
    include_path = find_circomlib_include(circomlib_include)
    run(
        [
            "circom",
            str(circuit_path),
            "--r1cs",
            "--wasm",
            "--sym",
            "-o",
            str(artifact_dir),
            "-l",
            str(include_path),
        ],
        timeout=1200,
    )
    return artifact_dir / f"{circuit_name}.r1cs"


def build_tariff() -> TariffTable:
    cells = {idx: (10 if idx < 128 else 20) for idx in range(1 << TREE_DEPTH)}
    return TariffTable(
        tariff_version=9,
        grid_w=GRID_W,
        cell_zones=cells,
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def build_fixes(period_id: str) -> list[ReceiverFix]:
    fixes: list[ReceiverFix] = []
    for seq in range(N_FIXES):
        raw = ReceiverFix(
            device_id="dev-v6",
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=1_777_593_600 + seq * CADENCE_SEC,
            cell_x=seq,
            cell_y=0,
            osnma_status=(
                "unavailable"
                if seq < N_FIXES - 1 and seq % 7 == 3
                else "authenticated"
            ),
            odometer_reading_m=10_000 + seq * CELL_SIZE,
            # Deterministic benchmark nonce; deployments use receiver entropy.
            nonce=f"v6-benchmark-nonce-{seq}",
        )
        fixes.append(sign_receiver_fix(raw, _DEVICE_SEED))
    return fixes


def build_position_valid() -> list[bool]:
    """Include explicit outage intervals even though every dt equals cadence."""

    return [i % 7 != 3 for i in range(N_FIXES - 1)]


def aggregate_intervals_for_witness(
    fixes: Sequence[ReceiverFix],
    tariff: TariffTable,
    *,
    position_valid: Sequence[bool],
    params: HarnessParams,
    dac_field: int,
    policy_profile_commitment: int = 0,
) -> dict[str, Any]:
    """Delegate all valid-input arithmetic to the V6 reference model."""

    return fee_for_period_v6(
        fixes,
        tariff,
        position_valid=position_valid,
        r_max_cents_per_m=tariff.max_zone_rate_cents_per_m,
        max_dt_sec=int(params.max_dt_sec),
        tier_vmax_mps=int(params.tier_vmax_mps),
        dac_field=dac_field,
        policy_profile_commitment=policy_profile_commitment,
    )


def build_raw_witness_input_for_fixes(
    fixes: Sequence[ReceiverFix],
    tariff: TariffTable,
    *,
    position_valid: Sequence[bool],
    params: HarnessParams,
    policy_profile_commitment: int = 0,
    payload_rem_zero: bool = True,
    device_attestation_commitment: str = _DEVICE_DAC,
) -> dict[str, Any]:
    if len(fixes) != N_FIXES:
        raise ValueError(f"expected exactly {N_FIXES} fixes")
    if len(position_valid) != N_FIXES - 1:
        raise ValueError(f"expected exactly {N_FIXES - 1} position_valid flags")
    if not payload_rem_zero:
        raise NotImplementedError("non-zero payload remainders are reserved for the E3 builder")
    if int(params.cell_size_m) != CELL_SIZE:
        raise ValueError(f"compiled circuit requires cell_size_m={CELL_SIZE}")

    period_id = str(fixes[0].period_id)
    dac_field = field_from_text(device_attestation_commitment)
    month_id, month_start_time, month_end_time = month_window_from_period_start(fixes[0].auth_gnss_time)
    aggregate = aggregate_intervals_for_witness(
        fixes,
        tariff,
        position_valid=position_valid,
        params=params,
        dac_field=dac_field,
        policy_profile_commitment=policy_profile_commitment,
    )
    input_json: dict[str, Any] = {
        "receiver_fix_root": field_str(
            compute_receiver_fix_root_v6(
                fixes,
                position_valid=position_valid,
                dac_field=dac_field,
                policy_profile_commitment=policy_profile_commitment,
            )
        ),
        "tariff_root": field_str(tariff.root(TREE_DEPTH)),
        "interval_commitment_root": field_str(aggregate["interval_commitment_root"]),
        "policy_profile_commitment": field_str(policy_profile_commitment),
        "period_id_field": field_str(field_from_text(period_id)),
        "tariff_version": field_str(tariff.tariff_version),
        "device_attestation_commitment": field_str(dac_field),
        "total_fee_cents": field_str(aggregate["total_fee_cents"]),
        "total_distance_m": field_str(aggregate["total_distance_m"]),
        "fallback_intervals": field_str(aggregate["fallback_intervals"]),
        "cadence_sec": field_str(params.cadence_sec),
        "tier_vmax_mps": field_str(params.tier_vmax_mps),
        "tier_vmax_sq": field_str(int(params.tier_vmax_mps) ** 2),
        "mode_vmax_sq": field_str(MODE_VMAX_SQ),
        "cap_policy_sq": field_str(CAP_POLICY_SQ),
        "max_zone_rate_cents_per_m": field_str(tariff.max_zone_rate_cents_per_m),
        "max_dt_sec": field_str(params.max_dt_sec),
        "period_start_time": field_str(fixes[0].auth_gnss_time),
        "period_end_time": field_str(fixes[-1].auth_gnss_time),
        "month_id": field_str(month_id),
        "month_start_time": field_str(month_start_time),
        "month_end_time": field_str(month_end_time),
        "x": [field_str(fix.cell_x * CELL_SIZE) for fix in fixes],
        "y": [field_str(fix.cell_y * CELL_SIZE) for fix in fixes],
        "loc_salt": [field_str(900_000 + i) for i in range(N_FIXES)],
        "auth_time": [field_str(fix.auth_gnss_time) for fix in fixes],
        "odometer_m": [field_str(fix.odometer_reading_m) for fix in fixes],
        "fix_nonce_field": [field_str(field_from_text(fix.nonce)) for fix in fixes],
        "fix_cell_x": [field_str(fix.cell_x) for fix in fixes],
        "fix_cell_y": [field_str(fix.cell_y) for fix in fixes],
        "payload_cell_x": [field_str(fix.cell_x) for fix in fixes[:-1]],
        "payload_cell_y": [field_str(fix.cell_y) for fix in fixes[:-1]],
        "payload_rem_x": ["0"] * (N_FIXES - 1),
        "payload_rem_y": ["0"] * (N_FIXES - 1),
        "payload_cell_idx": [
            field_str(tariff.cell_index(fix.cell_x, fix.cell_y)) for fix in fixes[:-1]
        ],
        "zone_id": [],
        "zone_rate_cents_per_m": [],
        "zone_path_sibling": [],
        "zone_path_is_right": [],
        "position_valid": [field_str(int(flag)) for flag in position_valid],
    }
    for fix in fixes[:-1]:
        cell_idx = tariff.cell_index(fix.cell_x, fix.cell_y)
        zone_id = tariff.zone_for_cell(cell_idx)
        path = tariff.path_for_cell(cell_idx, TREE_DEPTH)
        input_json["zone_id"].append(field_str(zone_id))
        input_json["zone_rate_cents_per_m"].append(field_str(tariff.rate_for_zone(zone_id)))
        input_json["zone_path_sibling"].append([field_str(step["sibling"]) for step in path])
        input_json["zone_path_is_right"].append([field_str(step["is_right"]) for step in path])
    if list(input_json)[:PUBLIC_SIGNAL_COUNT] != PUBLIC_SIGNAL_ORDER:
        raise RuntimeError("V6 public signal order drifted in witness input builder")
    return input_json


def build_input_for_fixes(
    fixes: Sequence[ReceiverFix],
    tariff: TariffTable,
    *,
    position_valid: Sequence[bool],
    params: HarnessParams,
    policy_profile: Any | None = None,
    validate_submission: bool = True,
    receiver_root_attestation: dict[str, Any] | None = None,
    device_public_key_bytes: bytes = _DEVICE_PUBLIC_KEY_BYTES,
    device_attestation_commitment: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(fixes) != N_FIXES:
        raise ValueError(f"expected exactly {N_FIXES} fixes")
    profile_commitment = 0 if policy_profile is None else int(policy_profile.commitment)
    period_id = str(fixes[0].period_id)
    device_dac = device_attestation_commitment or make_device_attestation_commitment(
        device_public_key_bytes
    )
    if make_device_attestation_commitment(device_public_key_bytes) != device_dac:
        raise ValueError("receiver public key does not match its device attestation commitment")
    month_id, _month_start, _month_end = month_window_from_period_start(fixes[0].auth_gnss_time)
    public = build_period_public_statement_v6(
        fixes=fixes,
        tariff=tariff,
        position_valid=position_valid,
        period_id=period_id,
        month_id=str(month_id),
        cadence_sec=int(params.cadence_sec),
        tier_vmax_mps=int(params.tier_vmax_mps),
        max_dt_sec=int(params.max_dt_sec),
        r_max_cents_per_m=tariff.max_zone_rate_cents_per_m,
        device_attestation_commitment=device_dac,
        tariff_tree_depth=TREE_DEPTH,
        mode_vmax_sq=MODE_VMAX_SQ,
        cap_policy_sq=CAP_POLICY_SQ,
        policy_profile=policy_profile,
    )
    if validate_submission:
        verify_period_submission_v6(
            fixes=fixes,
            tariff=tariff,
            position_valid=position_valid,
            public_statement=public,
            public_key_bytes=device_public_key_bytes,
            cadence_sec=int(params.cadence_sec),
            tier_vmax_mps=int(params.tier_vmax_mps),
            max_dt_sec=int(params.max_dt_sec),
            r_max_cents_per_m=tariff.max_zone_rate_cents_per_m,
            tariff_tree_depth=TREE_DEPTH,
            mode_vmax_sq=MODE_VMAX_SQ,
            cap_policy_sq=CAP_POLICY_SQ,
            policy_profile=policy_profile,
        )

    input_json = build_raw_witness_input_for_fixes(
        fixes,
        tariff,
        position_valid=position_valid,
        params=params,
        policy_profile_commitment=profile_commitment,
        device_attestation_commitment=device_dac,
    )
    statement_to_signal = {
        "month_id": "month_id_field",
        "device_attestation_commitment": None,
    }
    for signal in PUBLIC_SIGNAL_ORDER:
        if signal == "device_attestation_commitment":
            expected = field_str(field_from_text(str(public["device_attestation_commitment"])))
        else:
            statement_key = statement_to_signal.get(signal, signal)
            if statement_key is None:
                raise RuntimeError(f"missing public-statement mapping for {signal}")
            expected = field_str(public[statement_key])
        if input_json[signal] != expected:
            raise RuntimeError(f"V6 public signal mismatch before proving: {signal}")

    root_attestation = receiver_root_attestation or build_test_root_attestation(
        fixes=fixes,
        position_valid=position_valid,
        policy_profile_commitment=profile_commitment,
        receiver_fix_root=public["receiver_fix_root"],
    )
    if str(root_attestation.get("receiver_fix_root")) != str(public["receiver_fix_root"]):
        raise ValueError("sealed receiver root does not match the witness root")
    if str(root_attestation.get("period_id")) != period_id:
        raise ValueError("sealed receiver period does not match the witness period")
    if str(root_attestation.get("device_attestation_commitment")) != device_dac:
        raise ValueError("sealed receiver identity does not match the witness identity")

    submission = {
        "fixes": [fix.to_dict() for fix in fixes],
        "position_valid": [bool(flag) for flag in position_valid],
        "tariff": {
            "tariff_version": tariff.tariff_version,
            "grid_w": tariff.grid_w,
            "cell_zones": tariff.cell_zones,
            "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
        },
        "public_statement": public,
        "receiver_root_attestation": root_attestation,
        "receiver_attestation_mode": (
            "independent-receiver-process"
            if receiver_root_attestation is not None
            else "test-only-in-process"
        ),
    }
    if policy_profile is not None:
        submission["policy_profile"] = policy_profile.to_dict(include_local_paths=True)
    return input_json, submission


def build_input(
    policy_profile: PolicyProfile | None = None,
    *,
    position_valid: Sequence[bool] | None = None,
    receiver_root_attestation: dict[str, Any] | None = None,
    fixes: Sequence[ReceiverFix] | None = None,
    device_public_key_bytes: bytes = _DEVICE_PUBLIC_KEY_BYTES,
    device_attestation_commitment: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    period_id = f"2026-05-v6-{SETTLEMENT_PROFILE}"
    params = HarnessParams(
        cadence_sec=CADENCE_SEC,
        max_dt_sec=MAX_DT_SEC,
        tier_vmax_mps=TIER_VMAX_MPS,
    )
    return build_input_for_fixes(
        list(fixes) if fixes is not None else build_fixes(period_id),
        build_tariff(),
        position_valid=list(position_valid) if position_valid is not None else build_position_valid(),
        params=params,
        policy_profile=policy_profile,
        receiver_root_attestation=receiver_root_attestation,
        device_public_key_bytes=device_public_key_bytes,
        device_attestation_commitment=device_attestation_commitment,
    )


def ensure_setup(ptau: Path, *, artifact_dir: Path | None = None) -> tuple[Path, Path]:
    zk_dir = artifact_dir or (ROOT_DIR / "zk" / f"settlement_period_v6_{SETTLEMENT_PROFILE}")
    r1cs = zk_dir / f"settlement_period_v6_{SETTLEMENT_PROFILE}.r1cs"
    zkey = zk_dir / f"settlement_period_v6_{SETTLEMENT_PROFILE}_final.zkey"
    vkey = zk_dir / "verification_key.json"
    if not r1cs.exists():
        raise FileNotFoundError(
            f"missing V6 R1CS: {r1cs}; compile experiments-heatmap/circuits/"
            f"settlement_period_v6_{SETTLEMENT_PROFILE}.circom first"
        )
    if not zkey.exists():
        run(["snarkjs", "groth16", "setup", str(r1cs), str(ptau), str(zkey)], timeout=1200)
    if not vkey.exists():
        run(["snarkjs", "zkey", "export", "verificationkey", str(zkey), str(vkey)], timeout=600)
    return zkey, vkey


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a V6 witness, Groth16 proof, and differential check.")
    parser.add_argument("--ptau", default="zk/hello/pot18_final_phase2.ptau")
    parser.add_argument("--artifacts-dir", default=f"zk/settlement_period_v6_{SETTLEMENT_PROFILE}")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--circomlib-include", default="")
    parser.add_argument(
        "--policy-profile",
        default="",
        help="Bind the proof to a canonical PolicyProfile JSON (production gate).",
    )
    parser.add_argument("--write-input", default="")
    parser.add_argument("--receipt", default="")
    parser.add_argument(
        "--receiver-url",
        default="",
        help="Independent receiver signer base URL; required for paper-facing proofs.",
    )
    parser.add_argument(
        "--receiver-prover-token",
        default=os.getenv("WAYBILL_RECEIVER_PROVER_TOKEN", ""),
        help=(
            "Read-scope receiver credential; defaults to "
            "WAYBILL_RECEIVER_PROVER_TOKEN."
        ),
    )
    parser.add_argument(
        "--receiver-ca-file",
        default=os.getenv("WAYBILL_RECEIVER_API_CA_FILE", ""),
        help="CA certificate used to authenticate the independent receiver HTTPS endpoint.",
    )
    parser.add_argument(
        "--allow-insecure-receiver-http",
        action="store_true",
        help="Permit HTTP only for explicit local tests; never use for paper-facing evidence.",
    )
    parser.add_argument(
        "--allow-test-signer",
        action="store_true",
        help="Use the deterministic in-process signer only for unit/artifact tests.",
    )
    parser.add_argument(
        "--proof-output-dir",
        default="",
        help="Persist input/proof/public/submission JSON for endpoint tests.",
    )
    args = parser.parse_args()

    ptau = (ROOT_DIR / args.ptau).resolve()
    artifact_dir = (ROOT_DIR / args.artifacts_dir).resolve()
    if args.compile:
        compile_circuit(artifact_dir, circomlib_include=args.circomlib_include)
    zkey, vkey = ensure_setup(ptau, artifact_dir=artifact_dir)
    r1cs = artifact_dir / f"settlement_period_v6_{SETTLEMENT_PROFILE}.r1cs"
    wasm = (
        artifact_dir
        / f"settlement_period_v6_{SETTLEMENT_PROFILE}_js"
        / f"settlement_period_v6_{SETTLEMENT_PROFILE}.wasm"
    )
    policy_profile: PolicyProfile | None = None
    if args.policy_profile:
        profile_path = (ROOT_DIR / args.policy_profile).resolve()
        policy_profile = PolicyProfile.from_dict(json.loads(profile_path.read_text(encoding="utf-8")))
    period_id = f"2026-05-v6-{SETTLEMENT_PROFILE}"
    receiver_attestation: dict[str, Any] | None = None
    receiver_position_valid: Sequence[bool] | None = None
    receiver_fixes: Sequence[ReceiverFix] | None = None
    receiver_public_key_bytes = _DEVICE_PUBLIC_KEY_BYTES
    receiver_device_dac: str | None = None
    receiver_month_attestation: dict[str, Any] | None = None
    if args.receiver_url:
        if not args.receiver_prover_token:
            raise RuntimeError(
                "--receiver-url requires WAYBILL_RECEIVER_PROVER_TOKEN or "
                "--receiver-prover-token"
            )
        receiver_ssl_context = receiver_url_context(
            args.receiver_url,
            ca_file=args.receiver_ca_file,
            allow_insecure_http=args.allow_insecure_receiver_http,
        )
        material = fetch_receiver_period_material(
            receiver_url=args.receiver_url,
            device_id="dev-v6",
            period_id=period_id,
            prover_token=args.receiver_prover_token,
            ssl_context=receiver_ssl_context,
        )
        expected_profile_commitment = 0 if policy_profile is None else int(policy_profile.commitment)
        if int(material["policy_profile_commitment"]) != expected_profile_commitment:
            raise RuntimeError("receiver log is bound to a different policy profile")
        receiver_position_valid = list(material["position_valid"])
        receiver_attestation = dict(material["attestation"])
        receiver_fixes = [
            ReceiverFix.from_dict(dict(item))
            for item in material["fixes"]
        ]
        try:
            receiver_public_key_bytes = bytes.fromhex(str(material["receiver_public_key_hex"]))
        except ValueError as exc:
            raise RuntimeError("receiver public key is not valid hexadecimal") from exc
        if len(receiver_public_key_bytes) != 32:
            raise RuntimeError("receiver public key must be exactly 32 bytes")
        receiver_device_dac = str(receiver_attestation["device_attestation_commitment"])
        receiver_month_attestation = fetch_receiver_month_attestation(
            receiver_url=args.receiver_url,
            device_id="dev-v6",
            month_id="202605",
            prover_token=args.receiver_prover_token,
            ssl_context=receiver_ssl_context,
        )
    elif not args.allow_test_signer:
        raise RuntimeError(
            "paper-facing V6 proving requires --receiver-url; "
            "use --allow-test-signer only for deterministic tests"
        )
    input_json, submission = build_input(
        policy_profile=policy_profile,
        position_valid=receiver_position_valid,
        receiver_root_attestation=receiver_attestation,
        fixes=receiver_fixes,
        device_public_key_bytes=receiver_public_key_bytes,
        device_attestation_commitment=receiver_device_dac,
    )
    submission["receiver_public_key_hex"] = receiver_public_key_bytes.hex()
    if receiver_month_attestation is not None:
        submission["receiver_monthly_odometer_attestation"] = receiver_month_attestation
    if args.write_input:
        Path(args.write_input).write_text(json.dumps(input_json, indent=2, sort_keys=True), encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix=f"settlement-v6-{SETTLEMENT_PROFILE}-") as td:
        tdp = Path(td)
        input_path = tdp / "input.json"
        witness_path = tdp / "witness.wtns"
        proof_path = tdp / "proof.json"
        public_path = tdp / "public.json"
        input_path.write_text(json.dumps(input_json, sort_keys=True), encoding="utf-8")

        t0 = time.perf_counter()
        run(["snarkjs", "wtns", "calculate", str(wasm), str(input_path), str(witness_path)], timeout=1200)
        witness_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        run(
            [
                "snarkjs",
                "groth16",
                "prove",
                str(zkey),
                str(witness_path),
                str(proof_path),
                str(public_path),
            ],
            timeout=1200,
        )
        prove_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        verify_out = run(
            ["snarkjs", "groth16", "verify", str(vkey), str(public_path), str(proof_path)],
            timeout=600,
        ).stdout
        verify_ms = (time.perf_counter() - t0) * 1000
        public_signals = json.loads(public_path.read_text(encoding="utf-8"))
        proof_sha256 = sha256_file(proof_path)
        public_sha256 = sha256_file(public_path)
        if args.proof_output_dir:
            proof_output_dir = (ROOT_DIR / args.proof_output_dir).resolve()
            proof_output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(input_path, proof_output_dir / "input.json")
            shutil.copy2(proof_path, proof_output_dir / "proof.json")
            shutil.copy2(public_path, proof_output_dir / "public.json")
            shutil.copy2(vkey, proof_output_dir / "verification_key.json")
            (proof_output_dir / "submission.json").write_text(
                json.dumps(submission, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    expected_signals = [input_json[name] for name in PUBLIC_SIGNAL_ORDER]
    if public_signals != expected_signals:
        raise RuntimeError("Groth16 public signals differ from the V6 reference input")
    r1cs_info = run(["snarkjs", "r1cs", "info", str(r1cs)]).stdout
    constraints_match = re.search(r"# of Constraints:\s*(\d+)", r1cs_info)
    constraints = int(constraints_match.group(1)) if constraints_match else None
    root_attestation = submission["receiver_root_attestation"]
    receipt = {
        "schema": "waybill-settlement-v6-circuit-differential-receipt-v2",
        "ok": "OK" in verify_out,
        "commitment_semantics": "receiver-fix-validity-v2",
        "receiver_attestation_mode": submission["receiver_attestation_mode"],
        "receiver_attestation_schema": root_attestation["schema"],
        "position_validity_rule": root_attestation["position_validity_rule"],
        "receiver_id": root_attestation["receiver_id"],
        "receiver_log_sha256": root_attestation["log_sha256"],
        "receiver_log_epoch": root_attestation["log_epoch"],
        "receiver_attestation_sha256": receiver_attestation_sha256(
            dict(root_attestation)
        ),
        "previous_attestation_sha256": root_attestation[
            "previous_attestation_sha256"
        ],
        "receiver_chain_mode": "charger-online-cas-v1",
        "profile": SETTLEMENT_PROFILE,
        "circuit": f"SettlementPeriodV6({N_FIXES},{TREE_DEPTH},6)",
        "constraints": constraints,
        "n_fixes": N_FIXES,
        "position_valid_intervals": sum(submission["position_valid"]),
        "outage_intervals": len(submission["position_valid"]) - sum(submission["position_valid"]),
        "witness_ms": round(witness_ms, 2),
        "prove_ms": round(prove_ms, 2),
        "verify_ms": round(verify_ms, 2),
        "public_signal_count": len(public_signals),
        "public_signal_order": PUBLIC_SIGNAL_ORDER,
        "public_signals": public_signals,
        "python_reference_public_signals": expected_signals,
        "circuit_python_differential_match": public_signals == expected_signals,
        "total_fee_cents": int(input_json["total_fee_cents"]),
        "total_distance_m": int(input_json["total_distance_m"]),
        "fallback_intervals": int(input_json["fallback_intervals"]),
        "policy_profile_commitment": input_json["policy_profile_commitment"],
        "canonical_profile_bound": int(input_json["policy_profile_commitment"]) != 0,
        "policy_profile_sha256": None if policy_profile is None else policy_profile.profile_sha256,
        "artifact_sha256": {
            "r1cs": sha256_file(r1cs),
            "wasm": sha256_file(wasm),
            "zkey": sha256_file(zkey),
            "verification_key": sha256_file(vkey),
            "generate_witness_js": sha256_file(
                wasm.parent / "generate_witness.js"
            ),
            "witness_calculator_js": sha256_file(
                wasm.parent / "witness_calculator.js"
            ),
            "proof_json": proof_sha256,
            "public_json": public_sha256,
        },
        "code_sha256": {
            str(path.relative_to(ROOT_DIR)): sha256_file(path)
            for path in (
                ROOT_DIR / "common/policy_profile.py",
                ROOT_DIR / "common/http_security.py",
                ROOT_DIR / "common/receiver_signer.py",
                ROOT_DIR / "common/settlement.py",
                ROOT_DIR / "common/settlement_v6.py",
                ROOT_DIR / "experiments-heatmap/circuits/settlement_period_v6_base.circom",
                ROOT_DIR / "script/prove_settlement_period_v6.py",
                ROOT_DIR / "services/receiver_signer/app.py",
            )
        },
        "trusted_setup_note": "test-only direct Groth16 setup from an external pot18",
    }
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
