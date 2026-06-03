"""
Parallel Groth16 verifier benchmark using k in-process Node.js workers.
Each worker runs snarkjs.groth16.verify() in-process (no CLI startup overhead).
Usage: python experiments/verifier_bench/parallel_verifier_bench.py
"""
import subprocess, time, json, csv, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parents[2]
WORKER_MJS  = str(Path(__file__).parent / "parallel_worker.mjs")
VKEY        = str(REPO_ROOT / "zk/tsip_main_v3_k6/verification_key.json")
PROOF       = "/tmp/tsip_k6_proof.json"
PUBLIC      = "/tmp/tsip_k6_public.json"
OUT_DIR     = REPO_ROOT / "experiments/verifier_bench/20260424_parallel"

WORKER_COUNTS  = [1, 2, 4, 8, 16]
CLIENT_COUNTS  = [100, 1000, 5000, 10000]
PROOFS_PER_WORKER_WARMUP = 5   # keep small so experiment finishes fast


def run_worker(n_proofs):
    """Spawn one Node.js in-process worker that verifies n_proofs. Returns elapsed_ms."""
    r = subprocess.run(
        ["node", WORKER_MJS, VKEY, PROOF, PUBLIC, str(n_proofs)],
        capture_output=True, text=True, timeout=300
    )
    if r.returncode != 0:
        raise RuntimeError(f"Worker failed: {r.stderr[:200]}")
    data = json.loads(r.stdout.strip())
    return data["elapsed_ms"]


def benchmark_parallel(N, k):
    """
    Distribute N proof verifications across k Node.js processes.
    Each process handles ceil(N/k) proofs in-process.
    Returns wall-clock seconds.
    """
    base  = N // k
    extra = N % k
    loads = [base + (1 if i < extra else 0) for i in range(k)]

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=k) as ex:
        futures = [ex.submit(run_worker, load) for load in loads]
        # wait for all workers to finish
        for f in as_completed(futures):
            f.result()  # raise if worker failed
    return time.perf_counter() - t0


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: single-worker microbench ──────────────────────────
    print("[1/2] Single-worker in-process microbench (k=1, N=20 proofs, 3 repeats)...")
    single_times = []
    for trial in range(3):
        elapsed = run_worker(20)
        per_ms  = elapsed / 20
        single_times.append(per_ms)
        print(f"  trial {trial+1}: total={elapsed:.0f}ms  per_proof={per_ms:.2f}ms")
    mean_single = sum(single_times) / len(single_times)
    print(f"  => mean per-proof: {mean_single:.2f} ms (in-process, no startup)\n")

    with open(OUT_DIR / "inprocess_microbench.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["path","iterations","mean_ms","std_ms","p50_ms","p99_ms","notes"])
        w.writeheader()
        w.writerow({
            "path": "snarkjs_inprocess_api",
            "iterations": 20 * 3,
            "mean_ms": round(mean_single, 3),
            "std_ms": "",
            "p50_ms": "",
            "p99_ms": "",
            "notes": "In-process snarkjs.groth16.verify() via Node.js fork; pure BN254 pairing; no startup overhead",
        })

    # ── Phase 2: parallel scaling ───────────────────────────────────
    print("[2/2] Parallel scaling (k workers × N proofs)...")
    print("  Note: using N=100 for real measurement; larger N projected from measured per-proof latency.\n")

    rows = []
    REAL_N = 100   # cap real measurement to keep runtime reasonable

    for N in CLIENT_COUNTS:
        for k in WORKER_COUNTS:
            if N <= REAL_N:
                wall_s = benchmark_parallel(N, k)
                method = "measured"
            else:
                # analytical: each worker handles ceil(N/k) proofs at mean_single ms each
                # plus ~200ms Node.js startup per worker (one-time, amortized)
                proofs_per_worker = (N + k - 1) // k
                wall_s = (proofs_per_worker * mean_single / 1000) + 0.200
                method = "projected"

            within = wall_s <= 60
            rows.append({"clients": N, "workers": k,
                         "wall_s": round(wall_s, 3),
                         "within_60s": within, "method": method})
            print(f"  N={N:6d} k={k:2d}  wall={wall_s:.3f}s  within_60s={within}  [{method}]")

    with open(OUT_DIR / "inprocess_parallel_scaling.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["clients","workers","wall_s","within_60s","method"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nDone. All results in {OUT_DIR}/")


if __name__ == "__main__":
    main()
