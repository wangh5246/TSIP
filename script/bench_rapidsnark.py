"""E6: measure rapidsnark prover time on the real k6 settlement witness.

Generates the same deterministic witness as prove_settlement_period_v5.py,
then times the native rapidsnark prover against it and cross-verifies the
proof with snarkjs. Turns the design doc's "rapidsnark extrapolated ~0.6s"
into a measured number.

Prereq: a built rapidsnark prover binary, e.g.
    cd /tmp/rapidsnark && ln -sfn package depends/gmp/package_macos_arm64 \
      && cd build_prover && cmake .. -DTARGET_PLATFORM=macos_arm64 \
         -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=../package_macos_arm64 \
      && make -j8 && make install
Pass the binary via --prover or RAPIDSNARK_PROVER.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from script.prove_settlement_period_v5 import (  # noqa: E402
    SETTLEMENT_PROFILE,
    build_input,
)

ZK_DIR = ROOT_DIR / "zk" / f"settlement_period_v5_{SETTLEMENT_PROFILE}"
DEFAULT_PROVER = "/tmp/rapidsnark/package_macos_arm64/bin/prover"


def run(cmd: list[str], *, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark rapidsnark prover on the k6 settlement circuit.")
    parser.add_argument("--prover", default=os.environ.get("RAPIDSNARK_PROVER", DEFAULT_PROVER))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out-dir", default=str(ROOT_DIR / "experiments" / "e6_rapidsnark"))
    args = parser.parse_args()

    prover = Path(args.prover)
    if not prover.exists():
        raise SystemExit(f"rapidsnark prover not found at {prover}; build it first (see module docstring)")

    zkey = ZK_DIR / f"settlement_period_v5_{SETTLEMENT_PROFILE}_final.zkey"
    vkey = ZK_DIR / "verification_key.json"
    wasm = ZK_DIR / f"settlement_period_v5_{SETTLEMENT_PROFILE}_js" / f"settlement_period_v5_{SETTLEMENT_PROFILE}.wasm"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    input_json, _submission = build_input()

    with tempfile.TemporaryDirectory(prefix="e6_rapidsnark_") as tmp:
        tdp = Path(tmp)
        input_path = tdp / "input.json"
        witness_path = tdp / "witness.wtns"
        input_path.write_text(json.dumps(input_json))

        t0 = time.perf_counter()
        run(["snarkjs", "wtns", "calculate", str(wasm), str(input_path), str(witness_path)])
        witness_ms = (time.perf_counter() - t0) * 1000.0

        prove_ms: list[float] = []
        proof_path = tdp / "proof.json"
        public_path = tdp / "public.json"
        for _ in range(int(args.runs)):
            t0 = time.perf_counter()
            run([str(prover), str(zkey), str(witness_path), str(proof_path), str(public_path)])
            prove_ms.append((time.perf_counter() - t0) * 1000.0)

        t0 = time.perf_counter()
        run(["snarkjs", "groth16", "verify", str(vkey), str(public_path), str(proof_path)])
        verify_ms = (time.perf_counter() - t0) * 1000.0

        public_signals = json.loads(public_path.read_text())
        proof_bytes = len(proof_path.read_text().encode())

    receipt = {
        "experiment": "E6 rapidsnark measured prover time",
        "profile": SETTLEMENT_PROFILE,
        "prover_binary": str(prover),
        "runs": int(args.runs),
        "witness_ms_snarkjs": round(witness_ms, 2),
        "rapidsnark_prove_ms": [round(v, 2) for v in prove_ms],
        "rapidsnark_prove_ms_median": round(statistics.median(prove_ms), 2),
        "rapidsnark_prove_ms_min": round(min(prove_ms), 2),
        "snarkjs_verify_ms": round(verify_ms, 2),
        "proof_json_bytes": proof_bytes,
        "public_signal_count": len(public_signals),
    }
    receipt_path = out_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=1, sort_keys=True))
    print(json.dumps(receipt, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
