#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.settlement import (  # noqa: E402
    ReceiverFix,
    TariffTable,
    build_period_public_statement,
    compute_fix_commitment,
    compute_receiver_fix_root_for_circuit,
    commitment_chain_root,
    field_from_text,
    make_device_attestation_commitment,
    month_window_from_period_start,
    poseidon_chain,
    sign_receiver_fix,
    verify_period_submission,
)
from common.eval_harness import HarnessParams  # noqa: E402


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

# Deterministic test device key (fixed seed for reproducible benchmarks).
_DEVICE_SEED = hashlib.sha256(b"tsip-prove-v5-device-key").digest()
_DEVICE_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(_DEVICE_SEED)
_DEVICE_PUBLIC_KEY_BYTES = _DEVICE_PRIVATE_KEY.public_key().public_bytes_raw()
_DEVICE_DAC = make_device_attestation_commitment(_DEVICE_PUBLIC_KEY_BYTES)


def field_str(value: Any) -> str:
    return str(int(value))


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


def build_tariff() -> TariffTable:
    cells = {idx: (10 if idx < 128 else 20) for idx in range(1 << TREE_DEPTH)}
    return TariffTable(
        tariff_version=7,
        grid_w=GRID_W,
        cell_zones=cells,
        zone_rates_cents_per_m={10: 1, 20: 5},
    )


def build_fixes(period_id: str) -> list[ReceiverFix]:
    fixes: list[ReceiverFix] = []
    for seq in range(N_FIXES):
        raw = ReceiverFix(
            device_id="dev-1",
            period_id=period_id,
            fix_seq=seq,
            auth_gnss_time=1_777_593_600 + seq * CADENCE_SEC,
            cell_x=seq,
            cell_y=0,
            osnma_status="authenticated",
            odometer_reading_m=10_000 + seq * CELL_SIZE,
            # 128-bit random nonce provides hiding entropy for the commitment chain.
            nonce=secrets.token_hex(16),
        )
        fixes.append(sign_receiver_fix(raw, _DEVICE_SEED))
    return fixes


SETTLEMENT_PROFILE = "k6"


def aggregate_intervals_for_witness(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    params: HarnessParams,
    dac_field: int,
) -> dict[str, Any]:
    """Aggregate circuit public values without rejecting invalid trajectories."""

    total_fee = 0
    total_distance = 0
    fallback_intervals = 0
    interval_commitments: list[int] = []
    for prev, curr in zip(fixes, fixes[1:]):
        dt = int(curr.auth_gnss_time) - int(prev.auth_gnss_time)
        odo_delta = int(curr.odometer_reading_m) - int(prev.odometer_reading_m)
        cell_idx = tariff.cell_index(prev.cell_x, prev.cell_y)
        zone_id = tariff.zone_for_cell(cell_idx)
        zone_rate = tariff.rate_for_zone(zone_id)
        fallback_flag = int(dt > int(params.cadence_sec))
        charged_distance = dt * int(params.tier_vmax_mps) if fallback_flag else odo_delta
        fee = charged_distance * (tariff.max_zone_rate_cents_per_m if fallback_flag else zone_rate)
        total_distance += odo_delta
        total_fee += fee
        fallback_intervals += fallback_flag
        interval_commitments.append(
            poseidon_chain(
                [
                    compute_fix_commitment(prev, dac_field=dac_field),
                    compute_fix_commitment(curr, dac_field=dac_field),
                    odo_delta,
                    zone_id,
                    zone_rate,
                    fee,
                    fallback_flag,
                ]
            )
        )
    return {
        "total_fee_cents": int(total_fee),
        "total_distance_m": int(total_distance),
        "fallback_intervals": int(fallback_intervals),
        "interval_commitment_root": commitment_chain_root(interval_commitments),
    }


def build_raw_witness_input_for_fixes(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    params: HarnessParams,
    payload_rem_zero: bool = True,
) -> dict[str, Any]:
    """Build a cell-level circuit input without Python-side constraint rejection."""

    if len(fixes) != N_FIXES:
        raise ValueError(f"expected exactly {N_FIXES} fixes")
    if not payload_rem_zero:
        raise NotImplementedError("non-zero payload remainders are reserved for the E3 builder")
    if int(params.cell_size_m) != CELL_SIZE:
        raise ValueError(f"compiled circuit requires cell_size_m={CELL_SIZE}")

    period_id = str(fixes[0].period_id)
    dac_field = field_from_text(_DEVICE_DAC)
    month_id, month_start_time, month_end_time = month_window_from_period_start(fixes[0].auth_gnss_time)
    aggregate = aggregate_intervals_for_witness(fixes, tariff, params=params, dac_field=dac_field)
    input_json: dict[str, Any] = {
        "receiver_fix_root": field_str(compute_receiver_fix_root_for_circuit(fixes, dac_field=dac_field)),
        "tariff_root": field_str(tariff.root(TREE_DEPTH)),
        "interval_commitment_root": field_str(aggregate["interval_commitment_root"]),
        "period_id_field": str(field_from_text(period_id)),
        "tariff_version": field_str(tariff.tariff_version),
        "device_attestation_commitment": field_str(dac_field),
        "total_fee_cents": field_str(aggregate["total_fee_cents"]),
        "total_distance_m": field_str(aggregate["total_distance_m"]),
        "fallback_intervals": field_str(aggregate["fallback_intervals"]),
        "cadence_sec": field_str(params.cadence_sec),
        "tier_vmax_mps": field_str(params.tier_vmax_mps),
        "tier_vmax_sq": field_str(int(params.tier_vmax_mps) * int(params.tier_vmax_mps)),
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
        "fix_nonce_field": [str(field_from_text(fix.nonce)) for fix in fixes],
        "fix_cell_x": [field_str(fix.cell_x) for fix in fixes],
        "fix_cell_y": [field_str(fix.cell_y) for fix in fixes],
        "payload_cell_x": [field_str(fix.cell_x) for fix in fixes[:-1]],
        "payload_cell_y": [field_str(fix.cell_y) for fix in fixes[:-1]],
        "payload_rem_x": [field_str(0) for _ in fixes[:-1]],
        "payload_rem_y": [field_str(0) for _ in fixes[:-1]],
        "payload_cell_idx": [field_str(tariff.cell_index(fix.cell_x, fix.cell_y)) for fix in fixes[:-1]],
        "zone_id": [],
        "zone_rate_cents_per_m": [],
        "zone_path_sibling": [],
        "zone_path_is_right": [],
    }
    for fix in fixes[:-1]:
        cell_idx = tariff.cell_index(fix.cell_x, fix.cell_y)
        zone_id = tariff.zone_for_cell(cell_idx)
        path = tariff.path_for_cell(cell_idx, TREE_DEPTH)
        input_json["zone_id"].append(field_str(zone_id))
        input_json["zone_rate_cents_per_m"].append(field_str(tariff.rate_for_zone(zone_id)))
        input_json["zone_path_sibling"].append([field_str(step["sibling"]) for step in path])
        input_json["zone_path_is_right"].append([field_str(step["is_right"]) for step in path])
    return input_json


def build_input_for_fixes(
    fixes: list[ReceiverFix],
    tariff: TariffTable,
    *,
    params: HarnessParams,
    validate_submission: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(fixes) != N_FIXES:
        raise ValueError(f"expected exactly {N_FIXES} fixes")
    period_id = str(fixes[0].period_id)
    month_id, _month_start, _month_end = month_window_from_period_start(fixes[0].auth_gnss_time)
    public = build_period_public_statement(
        fixes=fixes,
        tariff=tariff,
        period_id=period_id,
        month_id=str(month_id),
        cadence_sec=params.cadence_sec,
        tier_vmax_mps=params.tier_vmax_mps,
        max_dt_sec=params.max_dt_sec,
        device_attestation_commitment=_DEVICE_DAC,
        tariff_tree_depth=TREE_DEPTH,
    )
    if validate_submission:
        verify_period_submission(
            fixes=fixes,
            tariff=tariff,
            public_statement=public,
            public_key_bytes=_DEVICE_PUBLIC_KEY_BYTES,
            cadence_sec=params.cadence_sec,
            tier_vmax_mps=params.tier_vmax_mps,
            max_dt_sec=params.max_dt_sec,
            tariff_tree_depth=TREE_DEPTH,
        )

    input_json = build_raw_witness_input_for_fixes(fixes, tariff, params=params)
    if input_json["interval_commitment_root"] != str(public["interval_commitment_root"]):
        raise RuntimeError("interval commitment root mismatch before proving")

    submission = {
        "fixes": [fix.to_dict() for fix in fixes],
        "tariff": {
            "tariff_version": tariff.tariff_version,
            "grid_w": tariff.grid_w,
            "cell_zones": tariff.cell_zones,
            "zone_rates_cents_per_m": tariff.zone_rates_cents_per_m,
        },
        "public_statement": public,
    }
    return input_json, submission


def build_input() -> tuple[dict[str, Any], dict[str, Any]]:
    period_id = f"2026-05-v5-{SETTLEMENT_PROFILE}"
    tariff = build_tariff()
    fixes = build_fixes(period_id)
    params = HarnessParams(cadence_sec=CADENCE_SEC, max_dt_sec=MAX_DT_SEC, tier_vmax_mps=TIER_VMAX_MPS)
    return build_input_for_fixes(fixes, tariff, params=params)


def ensure_setup(ptau: Path) -> tuple[Path, Path]:
    zk_dir = ROOT_DIR / "zk" / f"settlement_period_v5_{SETTLEMENT_PROFILE}"
    r1cs = zk_dir / f"settlement_period_v5_{SETTLEMENT_PROFILE}.r1cs"
    zkey = zk_dir / f"settlement_period_v5_{SETTLEMENT_PROFILE}_final.zkey"
    vkey = zk_dir / "verification_key.json"
    if not r1cs.exists():
        raise FileNotFoundError(f"missing R1CS: {r1cs}")
    if not zkey.exists():
        run(["snarkjs", "groth16", "setup", str(r1cs), str(ptau), str(zkey)], timeout=1200)
    if not vkey.exists():
        run(["snarkjs", "zkey", "export", "verificationkey", str(zkey), str(vkey)], timeout=600)
    return zkey, vkey


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a real settlement v5 witness, proof, verify, and charger check.")
    parser.add_argument("--ptau", default="zk/hello/pot18_final_phase2.ptau")
    parser.add_argument("--write-input", default="")
    args = parser.parse_args()

    ptau = (ROOT_DIR / args.ptau).resolve()
    zkey, vkey = ensure_setup(ptau)
    wasm = ROOT_DIR / "zk" / f"settlement_period_v5_{SETTLEMENT_PROFILE}" / f"settlement_period_v5_{SETTLEMENT_PROFILE}_js" / f"settlement_period_v5_{SETTLEMENT_PROFILE}.wasm"
    input_json, submission = build_input()

    if args.write_input:
        Path(args.write_input).write_text(json.dumps(input_json, indent=2, sort_keys=True), encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix=f"settlement-v5-{SETTLEMENT_PROFILE}-") as td:
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
        run(["snarkjs", "groth16", "prove", str(zkey), str(witness_path), str(proof_path), str(public_path)], timeout=1200)
        prove_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        verify_out = run(["snarkjs", "groth16", "verify", str(vkey), str(public_path), str(proof_path)], timeout=600).stdout
        verify_ms = (time.perf_counter() - t0) * 1000

        accepted_public = verify_period_submission(
            fixes=[ReceiverFix.from_dict(x) for x in submission["fixes"]],
            tariff=TariffTable(
                tariff_version=submission["tariff"]["tariff_version"],
                grid_w=submission["tariff"]["grid_w"],
                cell_zones={int(k): int(v) for k, v in submission["tariff"]["cell_zones"].items()},
                zone_rates_cents_per_m={
                    int(k): int(v) for k, v in submission["tariff"]["zone_rates_cents_per_m"].items()
                },
            ),
            public_statement=submission["public_statement"],
            public_key_bytes=_DEVICE_PUBLIC_KEY_BYTES,
            cadence_sec=CADENCE_SEC,
            tier_vmax_mps=TIER_VMAX_MPS,
            max_dt_sec=MAX_DT_SEC,
            tariff_tree_depth=TREE_DEPTH,
        )

        public_signals = json.loads(public_path.read_text(encoding="utf-8"))
        proof_size = len(proof_path.read_bytes())

    print(
        json.dumps(
            {
                "ok": "OK" in verify_out,
                "profile": SETTLEMENT_PROFILE,
                "n_fixes": N_FIXES,
                "intervals": N_FIXES - 1,
                "period_hours": (N_FIXES - 1) * CADENCE_SEC / 3600,
                "witness_ms": round(witness_ms, 2),
                "prove_ms": round(prove_ms, 2),
                "verify_ms": round(verify_ms, 2),
                "proof_json_bytes": proof_size,
                "public_signal_count": len(public_signals),
                "total_fee_cents": accepted_public["total_fee_cents"],
                "total_distance_m": accepted_public["total_distance_m"],
                "fallback_intervals": accepted_public["fallback_intervals"],
                "receiver_fix_root": accepted_public["receiver_fix_root"],
                "tariff_root": accepted_public["tariff_root"],
                "interval_commitment_root": accepted_public["interval_commitment_root"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
