#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.tsip import SNARK_FIELD, compute_policy_cap_sq, compute_tier_anchor_cap_sq

SNARKJS = os.environ.get("SNARKJS_BIN", "snarkjs")
RAPIDSNARK = os.environ.get(
    "RAPIDSNARK_BIN",
    str(Path.home() / ".local/bin/rapidsnark"),
)
TSIP_CIRCUIT_PROFILE = os.environ.get("TSIP_CIRCUIT_PROFILE", "k6").strip().lower()
if TSIP_CIRCUIT_PROFILE not in {"k6", "k30"}:
    TSIP_CIRCUIT_PROFILE = "k6"


@dataclass
class CircuitSpec:
    name: str
    r1cs: Path
    wasm: Path
    zkey: Path
    vkey: Path


def first_existing(paths: list[Path]) -> Path:
    for p in paths:
        if p.exists():
            return p
    return paths[0]


def run(cmd: list[str], timeout: int = 120) -> str:
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{out}")
    return out


def get_circomlib_include() -> Path:
    candidates = [
        ROOT / "node_modules",
        Path.home() / "node_modules",
        Path("/Users/wanghao/node_modules"),
    ]
    for p in candidates:
        if (p / "circomlib").exists():
            return p
    raise RuntimeError("circomlib not found under ./node_modules or $HOME/node_modules or /Users/wanghao/node_modules")


def ensure_poseidon2_compiled() -> Path:
    out_dir = ROOT / "build" / "poseidon2_bench"
    wasm = out_dir / "poseidon2_bench_js" / "poseidon2_bench.wasm"
    if wasm.exists():
        return wasm
    out_dir.mkdir(parents=True, exist_ok=True)
    include = str(get_circomlib_include())
    run(
        [
            "circom",
            str(ROOT / "circuits" / "poseidon2_bench.circom"),
            "--wasm",
            "--sym",
            "-o",
            str(out_dir),
            "-l",
            include,
        ]
    )
    if not wasm.exists():
        raise RuntimeError(f"poseidon2 wasm missing after compile: {wasm}")
    return wasm


def poseidon2_hash(a: int, b: int) -> int:
    wasm = ensure_poseidon2_compiled()
    with tempfile.TemporaryDirectory(prefix="poseidon2_") as td:
        td_path = Path(td)
        input_path = td_path / "input.json"
        witness_path = td_path / "witness.wtns"
        witness_json_path = td_path / "witness.json"
        input_path.write_text(json.dumps({"a": str(int(a)), "b": str(int(b))}), encoding="utf-8")
        run([SNARKJS, "wtns", "calculate", str(wasm), str(input_path), str(witness_path)], timeout=120)
        run([SNARKJS, "wtns", "export", "json", str(witness_path), str(witness_json_path)], timeout=120)
        witness = json.loads(witness_json_path.read_text(encoding="utf-8"))
        if not isinstance(witness, list) or len(witness) < 2:
            raise RuntimeError("unexpected witness format from poseidon2 helper")
        return int(witness[1])


def r1cs_constraints(r1cs_path: Path) -> int:
    out = run([SNARKJS, "r1cs", "info", str(r1cs_path)], timeout=60)
    m = re.search(r"# of Constraints:\s*([0-9]+)", out)
    if not m:
        raise RuntimeError(f"cannot parse constraints from:\n{out}")
    return int(m.group(1))


def prove_with_snarkjs(
    inputs: dict[str, int | str],
    spec: CircuitSpec,
    proof_path: Path,
    public_path: Path,
    timeout: int,
):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(inputs, f, ensure_ascii=True)
        input_path = Path(f.name)
    try:
        run(
            [
                SNARKJS,
                "groth16",
                "fullprove",
                str(input_path),
                str(spec.wasm),
                str(spec.zkey),
                str(proof_path),
                str(public_path),
            ],
            timeout=timeout,
        )
    finally:
        input_path.unlink(missing_ok=True)


def prove_with_rapidsnark(
    inputs: dict[str, int | str],
    spec: CircuitSpec,
    proof_path: Path,
    public_path: Path,
    timeout: int,
):
    with tempfile.TemporaryDirectory(prefix="rapidprove_") as td:
        td_path = Path(td)
        input_path = td_path / "input.json"
        witness_path = td_path / "witness.wtns"
        input_path.write_text(json.dumps(inputs, ensure_ascii=True), encoding="utf-8")
        run(
            [
                SNARKJS,
                "wtns",
                "calculate",
                str(spec.wasm),
                str(input_path),
                str(witness_path),
            ],
            timeout=timeout,
        )
        run(
            [
                RAPIDSNARK,
                str(spec.zkey),
                str(witness_path),
                str(proof_path),
                str(public_path),
            ],
            timeout=timeout,
        )


def verify_proof(spec: CircuitSpec, public_path: Path, proof_path: Path, timeout: int):
    out = run(
        [
            SNARKJS,
            "groth16",
            "verify",
            str(spec.vkey),
            str(public_path),
            str(proof_path),
        ],
        timeout=timeout,
    )
    if "OK!" not in out:
        raise RuntimeError(f"verify output missing OK: {out}")


def benchmark_one(
    spec: CircuitSpec,
    prover: str,
    inputs: dict[str, int | str],
    iterations: int,
    timeout: int,
) -> dict[str, float | int | str]:
    prove_times: list[float] = []
    verify_times: list[float] = []
    proof_size = 0
    with tempfile.TemporaryDirectory(prefix=f"bench_{spec.name}_{prover}_") as td:
        td_path = Path(td)
        for i in range(iterations):
            proof_path = td_path / f"proof_{i}.json"
            public_path = td_path / f"public_{i}.json"
            t0 = time.perf_counter()
            if prover == "snarkjs":
                prove_with_snarkjs(inputs, spec, proof_path, public_path, timeout)
            elif prover == "rapidsnark":
                prove_with_rapidsnark(inputs, spec, proof_path, public_path, timeout)
            else:
                raise RuntimeError(f"unknown prover: {prover}")
            t1 = time.perf_counter()
            verify_proof(spec, public_path, proof_path, timeout)
            t2 = time.perf_counter()
            prove_times.append((t1 - t0) * 1000.0)
            verify_times.append((t2 - t1) * 1000.0)
            if i == 0:
                proof_size = proof_path.stat().st_size
    return {
        "circuit": spec.name,
        "prover": prover,
        "constraints": r1cs_constraints(spec.r1cs),
        "iterations": iterations,
        "prove_ms_avg": round(sum(prove_times) / len(prove_times), 3),
        "verify_ms_avg": round(sum(verify_times) / len(verify_times), 3),
        "proof_bytes": proof_size,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark snarkjs vs rapidsnark on local circuits")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    if args.iterations <= 0:
        raise RuntimeError("--iterations must be > 0")
    if shutil.which(SNARKJS) is None and not Path(SNARKJS).exists():
        raise RuntimeError(f"snarkjs not found: {SNARKJS}")

    step = CircuitSpec(
        name="tsip_step",
        r1cs=first_existing(
            [
                ROOT / "zk/tsip_step/tsip_step.r1cs",
                ROOT / "build/tsip_step/tsip_step.r1cs",
            ]
        ),
        wasm=first_existing(
            [
                ROOT / "zk/tsip_step/tsip_step_js/tsip_step.wasm",
                ROOT / "build/tsip_step/tsip_step_js/tsip_step.wasm",
            ]
        ),
        zkey=first_existing(
            [
                ROOT / "zk/tsip_step/tsip_step_final.zkey",
                ROOT / "build/tsip_step/tsip_step_final.zkey",
            ]
        ),
        vkey=first_existing(
            [
                ROOT / "zk/tsip_step/verification_key.json",
                ROOT / "build/tsip_step/verification_key.json",
            ]
        ),
    )
    tsip_name = f"tsip_main_v3_{TSIP_CIRCUIT_PROFILE}"
    tsip = CircuitSpec(
        name=tsip_name,
        r1cs=first_existing(
            [
                ROOT / f"zk/{tsip_name}/{tsip_name}.r1cs",
                ROOT / f"build/{tsip_name}/{tsip_name}.r1cs",
            ]
        ),
        wasm=first_existing(
            [
                ROOT / f"zk/{tsip_name}/{tsip_name}_js/{tsip_name}.wasm",
                ROOT / f"build/{tsip_name}/{tsip_name}_js/{tsip_name}.wasm",
            ]
        ),
        zkey=first_existing(
            [
                ROOT / f"zk/{tsip_name}/{tsip_name}_final.zkey",
                ROOT / f"build/{tsip_name}/{tsip_name}_final.zkey",
            ]
        ),
        vkey=first_existing(
            [
                ROOT / f"zk/{tsip_name}/verification_key.json",
                ROOT / f"build/{tsip_name}/verification_key.json",
            ]
        ),
    )

    for spec in (step, tsip):
        for p in (spec.r1cs, spec.wasm, spec.zkey, spec.vkey):
            if not p.exists():
                raise RuntimeError(f"missing artifact for {spec.name}: {p}")

    step_inputs = {"dx": 30, "dy": 40, "dt": 1, "vmax": 60}
    x1, y1 = 100, 200
    x2, y2 = 180, 260
    xa, ya = 120, 220
    step_dt = 60
    step_dt_sq = int(step_dt * step_dt)
    tier_sq = 1600  # transit
    window_k = 30 if TSIP_CIRCUIT_PROFILE == "k30" else 6
    tier_anchor_cap_sq = int(compute_tier_anchor_cap_sq(tier_sq, window_k, step_dt_sq))
    cap_policy_sq = int(compute_policy_cap_sq(tier_anchor_cap_sq, 0.5))
    payload_digest = hashlib.sha256(json.dumps(sorted([0, 1, 2, 3]), separators=(",", ":")).encode()).hexdigest()
    payload_lo = int(payload_digest[:32], 16) % SNARK_FIELD
    payload_hi = int(payload_digest[32:], 16) % SNARK_FIELD
    payload_commitment = poseidon2_hash(payload_lo, payload_hi)
    secret = int(hashlib.sha256(b"benchmark_secret_u0").hexdigest(), 16) % SNARK_FIELD
    user_id_field = int(hashlib.sha256(b"benchmark_user_u0").hexdigest(), 16) % SNARK_FIELD
    secret_commitment = poseidon2_hash(secret, user_id_field)
    modeset_bitmap = 0b1111
    modeset_salt = int(hashlib.sha256(b"bench_modeset_salt").hexdigest(), 16) % SNARK_FIELD
    modeset_commitment = poseidon2_hash(modeset_bitmap, modeset_salt)
    selected_mode_id = 2  # vehicle
    mode_tag = poseidon2_hash(selected_mode_id, secret)
    tsip_inputs = {
        "x1": str(x1),
        "y1": str(y1),
        "x2": str(x2),
        "y2": str(y2),
        "x_anchor": str(xa),
        "y_anchor": str(ya),
        "hash_prev": str(poseidon2_hash(x1, y1)),
        "hash_curr": str(poseidon2_hash(x2, y2)),
        "hash_anchor": str(poseidon2_hash(xa, ya)),
        "step_dt_sq": str(step_dt_sq),
        "tier_vmax_sq": str(tier_sq),
        "tier_anchor_cap_sq": str(tier_anchor_cap_sq),
        "cap_policy_sq": str(cap_policy_sq),
        "payload_lo": str(payload_lo),
        "payload_hi": str(payload_hi),
        "payload_commitment": str(payload_commitment),
        "secret": str(secret),
        "user_id_field": str(user_id_field),
        "secret_commitment": str(secret_commitment),
        "modeset_bitmap": str(modeset_bitmap),
        "modeset_salt": str(modeset_salt),
        "mode_s0": "0",
        "mode_s1": "0",
        "mode_s2": "1",
        "mode_s3": "0",
        "modeset_commitment": str(modeset_commitment),
        "mode_tag": str(mode_tag),
    }

    provers = ["snarkjs"]
    if Path(RAPIDSNARK).exists() or shutil.which(RAPIDSNARK):
        provers.append("rapidsnark")
    else:
        print(f"[WARN] rapidsnark not found, skip rapidsnark benchmark: {RAPIDSNARK}")

    rows: list[dict[str, float | int | str]] = []
    for prover in provers:
        rows.append(benchmark_one(step, prover, step_inputs, args.iterations, args.timeout))
        rows.append(benchmark_one(tsip, prover, tsip_inputs, args.iterations, args.timeout))

    out_dir = ROOT / "experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = out_dir / f"zk_benchmark_{ts}.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "circuit",
                "prover",
                "constraints",
                "iterations",
                "prove_ms_avg",
                "verify_ms_avg",
                "proof_bytes",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print("== zk benchmark summary ==")
    for row in rows:
        print(
            f"{row['circuit']:18s} prover={row['prover']:10s} "
            f"constraints={row['constraints']:4d} proof_bytes={row['proof_bytes']:4d} "
            f"prove_ms_avg={row['prove_ms_avg']:8.3f} verify_ms_avg={row['verify_ms_avg']:8.3f}"
        )
    print(f"saved: {out_csv}")


if __name__ == "__main__":
    main()
