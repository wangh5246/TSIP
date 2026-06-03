"""
Subprocess-parallel Groth16 verification benchmark (snarkjs CLI path).
Tests actual wall-clock time for k concurrent snarkjs processes.
Usage: python experiments/verifier_bench/subprocess_parallel_bench.py
"""
import subprocess, time, tempfile, shutil, os, csv, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT  = Path(__file__).resolve().parents[2]
VKEY       = str(REPO_ROOT / "zk/tsip_main_v3_k6/verification_key.json")
PROOF_SRC  = "/tmp/tsip_k6_proof.json"
PUBLIC_SRC = "/tmp/tsip_k6_public.json"
OUT_DIR    = REPO_ROOT / "experiments/verifier_bench/20260424_parallel"
OUT_DIR.mkdir(parents=True, exist_ok=True)

WORKER_COUNTS  = [1, 2, 4, 8, 16]
CLIENT_COUNTS  = [50, 100, 1000]   # 50/100 for real measurement; 1000 extrapolated
WARMUP         = 2
TIMED_SINGLE   = 10


def _verify_one(args):
    vkey, proof, public = args
    t0 = time.perf_counter()
    r = subprocess.run(
        ["snarkjs", "groth16", "verify", vkey, public, proof],
        capture_output=True, timeout=30
    )
    return time.perf_counter() - t0, r.returncode == 0


def single_thread_microbench():
    print("[1/2] Subprocess single-thread microbench...")
    for _ in range(WARMUP):
        subprocess.run(["snarkjs", "groth16", "verify", VKEY, PUBLIC_SRC, PROOF_SRC],
                       capture_output=True, timeout=30)
    times = []
    for i in range(TIMED_SINGLE):
        t, ok = _verify_one((VKEY, PROOF_SRC, PUBLIC_SRC))
        times.append(t * 1000)
        print(f"  run {i+1}/{TIMED_SINGLE}: {t*1000:.1f} ms  ok={ok}")
    mean = sum(times) / len(times)
    std  = (sum((t - mean)**2 for t in times) / len(times)) ** 0.5
    p99  = sorted(times)[int(len(times) * 0.99)]
    print(f"  => mean={mean:.1f} ms  std={std:.1f} ms  p99={p99:.1f} ms")
    return mean, std, p99


def parallel_bench(mean_single_ms):
    print("[2/2] Subprocess parallel scaling (real measurement up to N=100)...")
    rows = []

    for N in CLIENT_COUNTS:
        for k in WORKER_COUNTS:
            if N <= 100:
                # real measurement
                args = [(VKEY, PROOF_SRC, PUBLIC_SRC)] * N
                t0 = time.perf_counter()
                with ThreadPoolExecutor(max_workers=k) as ex:
                    list(as_completed([ex.submit(_verify_one, a) for a in args]))
                wall_s = time.perf_counter() - t0
                method = "measured"
            else:
                # analytical projection from measured single-thread latency
                wall_s = (mean_single_ms / 1000) * (N / k)
                method = "projected"
            within = wall_s <= 60
            rows.append({
                "clients": N, "workers": k,
                "wall_s": round(wall_s, 3),
                "within_60s": within,
                "method": method,
            })
            print(f"  N={N:5d} k={k:2d}  wall={wall_s:.2f}s  60s_ok={within}  [{method}]")

    return rows


def main():
    mean_ms, std_ms, p99_ms = single_thread_microbench()

    # write single-thread CSV
    with open(OUT_DIR / "subprocess_microbench.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["path","iterations","mean_ms","std_ms","p99_ms","notes"])
        w.writeheader()
        w.writerow({
            "path": "snarkjs_node_cli",
            "iterations": TIMED_SINGLE,
            "mean_ms": round(mean_ms, 3),
            "std_ms": round(std_ms, 3),
            "p99_ms": round(p99_ms, 3),
            "notes": "Subprocess snarkjs CLI; includes Node.js startup and JSON parsing overhead",
        })

    rows = parallel_bench(mean_ms)

    with open(OUT_DIR / "subprocess_parallel_scaling.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["clients","workers","wall_s","within_60s","method"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nDone. Results in {OUT_DIR}/")


if __name__ == "__main__":
    main()
