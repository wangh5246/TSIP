#!/usr/bin/env python3
"""Measure sustained ark-rs verifier throughput with multiple OS processes."""

import argparse
import csv
import math
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIN = ROOT / "experiments/verifier_bench/ark_verifier/target/release/ark_verifier"
DEFAULT_VK = ROOT / "zk/tsip_main_v3_k6/verification_key.json"
DEFAULT_PROOF = Path("/tmp/tsip_k6_proof.json")
DEFAULT_PUBLIC = Path("/tmp/tsip_k6_public.json")


def run_worker(binary: Path, vk: Path, proof: Path, public: Path, n: int) -> None:
    subprocess.run(
        [str(binary), str(vk), str(proof), str(public), "5", str(n)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=max(30, math.ceil(n * 0.02) + 60),
    )


def bench(binary: Path, vk: Path, proof: Path, public: Path, workers: int, total: int) -> dict:
    base = total // workers
    extra = total % workers
    loads = [base + (1 if i < extra else 0) for i in range(workers)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(run_worker, binary, vk, proof, public, n) for n in loads]
        for fut in as_completed(futs):
            fut.result()
    wall_s = time.perf_counter() - t0
    return {
        "workers": workers,
        "total_proofs": total,
        "wall_s": round(wall_s, 4),
        "qps": round(total / wall_s, 2),
        "ms_per_proof_effective": round(1000 * wall_s / total, 4),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, default=DEFAULT_BIN)
    p.add_argument("--vk", type=Path, default=DEFAULT_VK)
    p.add_argument("--proof", type=Path, default=DEFAULT_PROOF)
    p.add_argument("--public", type=Path, default=DEFAULT_PUBLIC)
    p.add_argument("--workers", default="1,2,4,8,16")
    p.add_argument("--total", type=int, default=10000)
    p.add_argument("--out", type=Path, default=ROOT / "experiments/verifier_bench/ark_parallel_process_scaling.csv")
    args = p.parse_args()

    rows = []
    for workers in [int(x) for x in args.workers.split(",") if x.strip()]:
        rows.append(bench(args.binary, args.vk, args.proof, args.public, workers, args.total))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["workers", "total_proofs", "wall_s", "qps", "ms_per_proof_effective"])
        w.writeheader()
        w.writerows(rows)

    for row in rows:
        print(row)
    print(f"[out] {args.out}")


if __name__ == "__main__":
    main()
