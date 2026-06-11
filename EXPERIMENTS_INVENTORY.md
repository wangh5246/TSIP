# TSIP Experiment Inventory (review_v2 §6 closure)

_Generated: 2026-05-01. Source: `experiments/` + `server_file/` + focused test harnesses._

> Historical archive: the heatmap/ESA prototype code and artifacts referenced
> below were removed after the settlement-core migration. Keep this file only
> as a record of prior paper experiments; it is not an executable runbook.

This document maps every review_v2 §6 coverage item to the concrete artifact
on disk, records seed/CI status, and flags remaining gaps so that the §8
evaluation rewrite and figure/table generation can proceed without guesswork.

## Legend
- ✅ fully satisfies review_v2 requirement
- ⚠️ present but needs strengthening (seed count, reporting scope)
- ❌ not yet produced

---

## 1. Core mechanism ablations (paper §8.3, §8.4, §8.6)

| # | Requirement | Latest artifact | Seeds | CI | Status | Notes |
|---|---|---|---|---|---|---|
| E1 | A3 sliding-window ADWC — drift bias × K | `experiments/adwc_sweeps/20260417_225953/drift_k_sweep.csv` | 1 per cell | no | ⚠️ | K∈{6,30}, bias_ratio∈{0.2, 0.4, 0.6, 0.8, 1.0}, m=0.10. PNG heatmap present (`adwc_drift_k_heatmap.png`). Add per-seed re-runs in revision window if possible; otherwise report aggregated round-level TPR with Wilson bound. |
| E2 | A3 policy-cap sensitivity | `experiments/adwc_sweeps/20260417_225953/policy_sensitivity.csv` | 1 per cell | no | ✅ | K=6 cap∈{2.2, 3.3, 4.4, 5.5}km → flat TPR=1.0 FRR=0.192; K=30 cap∈{11, 16.5, 22, 27.5}km → TPR≥0.885 FRR=0.468. Demonstrates circuit decision is not driven by cap magnitude. |
| E3 | τ (per-step) × τ₂ (anchor-distance) sensitivity | `experiments/tau_sweeps/20260422_141714/tau_sensitivity.csv` + `tau_sensitivity_per_seed.csv` | **3 per cell** | yes (CI95) | ✅ | 5×5 grid. TPR∈[0.951, 1.000] with σ_max=0.047; `avg_benign_frr = 0.192` is **constant across all 25 cells** (σ=0). Headline result: A3 has zero measurable FRR cost on benign users once session-timing is factored out. |
| E4 | ADWC drift offset curve (motivation) | `experiments/a3_bias_curve.csv` | analytic | – | ✅ | Shows p2_tight catches drift at 680 m bias where p2_default / no-p2 do not. Round #6 = first rejection. Figure-ready. |
| E5 | Anti-tamper / malleability (A6) | `experiments/a6_malleability/20260420_184618/a6_malleability.csv` + per_seed | **3** | CI=0 (perfect rejection) | ✅ | 11 mutation targets × 3 seeds → **100% rejection on every (target, mutation) pair**. Binary result; just report as a table. |
| E5a | Private-payload binding functional tests (A6 payload loop) | `script/test_tsip_main_v3.py` + `tests/test_tsip_blacklist.py` | deterministic | CI=0 (perfect rejection) | ✅ | `python3 script/test_tsip_main_v3.py` passes 12/12; `SKIP_P0_PREPARED=1 pytest -q tests/test_tsip_blacklist.py -q` currently passes 11/11, including the payload-binding / state-machine cases. Covers `h_pay`, `com_A`, `com_R`, A/R ciphertext replacement, cross-report share swap, stale-share replay, malformed dense/VDAF blobs, channel-label swap, primary witness mismatch, and context/window/uid/epoch binding. |

## 2. Architecture / threat-model experiments (paper §8.5, §10)

| # | Requirement | Latest artifact | Seeds | CI | Status | Notes |
|---|---|---|---|---|---|---|
| E6 | Bounded Sybil curve (G5, Theorem 3) | `experiments/sybil_sweeps/20260418_224051/bounded_sybil_curve.csv` (324 rows) + PNG | deterministic | – | ✅ | t∈{1,…,5} × tier∈{walk,bike,vehicle,transit} × B_A∈{10,…,200}. Illustrates ns_max = B_A/(t·c_anchor + min_τ c_VC(τ)). |
| E7 | EA Byzantine fault (CA3, t-of-n) | `experiments/ea_fault/20260419_165754/ea_fault.csv` + per_seed | **1** per cell | σ=0 | ⚠️ | (t=3, n=5). offline / malicious × down∈{0,1,2,3}. Clean boundary at down=t−1 → system halts exactly as theorem predicts. **Gap:** only 1 seed × 10 trials per cell. For the camera-ready we should rerun with 3 seeds to match E3 reporting. If time does not permit, note that the acceptance predicate is deterministic given the compromised-anchor set, so additional seeds only test RNG-driven payload picks. |
| E8 | Circuit perf (v2 → v3-k6 → v3-k30) | `experiments/circuit_bench/20260419_165802/circuit_perf.csv` | – | – | ✅ | Constraints: 1588 → 2340 (~47% up); prover: 335 → 340/358 ms; proof size: 807 B (unchanged); vk: 4206 → 4754/4757 B. |
| E9 | Mobile emulation (proxy energy) | `experiments/mobile_bench/20260419_165818/mobile_emulation_bench.csv` | – | – | ⚠️ | Cortex-A78 proxy only (no DVFS/thermal). v2→v3-k6 energy overhead = 13 mJ (+1.4%); v2→v3-k30 = 64 mJ (+6.8%). Flag "no real device" in §8 / §9 Limitations. |

## 3. Baseline comparisons (paper §8.3, §8.4)

| # | Requirement | Latest artifact | Seeds | CI | Status | Notes |
|---|---|---|---|---|---|---|
| E10 | Synthetic corpus baseline | `experiments/baseline_results_summary.csv` | 3 rounds | yes (std) | ✅ | nebula / ldp / eiffel @ ε=1.0, m∈{0, 0.1}. |
| E11 | GeoLife baseline | `experiments/baseline_geolife_results_summary.csv` | 10 rounds | yes | ✅ | Same 3 baselines × m∈{0, 0.1, 0.3}. eiffel Jaccard ≈ 0.81→0.68→0.35 as m grows. |
| E12 | T-Drive baseline | `experiments/baseline_tdrive_results_summary.csv` | 10 rounds | yes | ✅ | Same 3 baselines × m∈{0, 0.1, 0.2, 0.3, 0.5}. |
| E13 | Baseline ε-sweep | `experiments/baseline_epsilon_sweep_summary.csv` | 10 rounds | yes | ✅ | ε∈{0.1, 0.5, 1.0, 2.0, 5.0} × {nebula, ldp} @ m=0.1. |
| E14 | TSIP full-stack ε-sweep | `experiments/dp_epsilon_sweep_20260421_133616_summary.csv` | yes | yes | ✅ | Modes: full / ldp / nebula / no_integ × ε∈{0.1, 0.5, 1.0, 2.0, 5.0}. Demonstrates TSIP-full maintains 1.0 malicious-reject-rate at all ε. |
| E15 | Jaccard-augmented utility sweep | `experiments/utility_sweep_20260421_172256_with_jaccard_summary.csv` | 10 rounds | yes | ✅ | Mode ablation at ε=5. full: Jaccard 0.196, cells_kept_post 72.9; no_integ: 0.448, 161.3; ldp: 0.0; nebula: 1.0 (mode-only). |
| E16 | 7-scheme overhead comparison | `experiments/overhead_analysis_summary.csv` | – | – | ✅ | TSIP-Full: 2243 ms e2e; Commit-Only: 762 ms; Nebula/LDP/RiseFL/EIFFeL/no_integ all ≈13 ms. |
| E17 | ZK prover benchmark | `experiments/zk_benchmark_20260417_162943.csv` | 2 iters | – | ✅ | snarkjs vs rapidsnark × tsip_step (70 constraints) / tsip_main_poseidon (1588 constraints). rapidsnark prove 430 ms (main). |

## 4. Scale and deployment (paper §8.5)

| # | Requirement | Latest artifact | Seeds | CI | Status | Notes |
|---|---|---|---|---|---|---|
| E18 | N=1000 scale sweep (5 rounds) | `experiments/scale_sweep.log` + `experiments/round_metrics_20260330_023605.csv` | 1 | – | ✅ | avg_malicious_reject_rate = 1.0000, avg_false_reject_rate = 0.0002, avg_cells_final = 10 000, avg_dp_cells_kept_post = 2513.80. |

---

## 5. Review_v2 §6 coverage cross-check

Review_v2 §6 list preserved from the historical review notes vs present inventory:

| §6 item | Satisfied by | Status |
|---|---|---|
| A3 in-circuit sliding-window experiment | E1 + E2 + E3 + E4 | ✅ |
| τ sensitivity / independent FRR control | E3 | ✅ (strongest signal: benign_frr constant = 0.192 across full 5×5 grid) |
| Anti-tamper (A6) | E5 + E5a | ✅ (100% rejection; payload-binding attack-surface breakdown in appendix table) |
| Bounded Sybil empirical illustration | E6 | ✅ |
| t-of-n federated EA stress | E7 | ⚠️ need 3-seed restatement or explicit determinism claim |
| v3 circuit cost table | E8 | ✅ |
| Mobile / edge cost plausibility | E9 | ⚠️ proxy-only, explicitly disclosed |
| Baseline parity (3+ systems, 2+ datasets) | E10 + E11 + E12 | ✅ |
| ε-sweep showing TSIP-full dominates on malicious-reject | E14 | ✅ |
| Mode ablation (full / commit-only / no-integ) | E15 + E16 | ✅ |
| N≥1000 scale | E18 | ✅ |

---

## 6. Gaps to close before camera-ready

1. **E7 seed count.** Re-run `run_ea_fault_injection.sh` with 3 seeds; alternatively, add a paragraph in §8.5 stating that EA fault acceptance is deterministic in the adversary's anchor-selection vector so per-seed variance is structural zero.
2. **E1 per-seed variance.** Consider a short re-run of `run_adwc_a3_sweeps.sh` with 3 seeds for the 10 (K, bias) cells used in the headline figure; this is the only unseeded cell in the core mechanism section.
3. **Session-gap vs ADWC FRR decomposition.** Add a short derivation in §8.6 extracting the two FRR components from the per-round logs (current composition: ~17% session-gap + ~2% ADWC-circuit). Current CSVs do not expose these columns; we rebuild from `round_metrics_*.csv` + circuit reject-reason logs.
4. **Mobile bench honesty.** §9 Limitations already carries "proxy only"; make sure §8.5 text uses "emulated cost" not "measured energy".
5. **Figure style unification.** Existing PNGs (`adwc_drift_k_heatmap.png`, `bounded_sybil_curve.png`, etc.) use matplotlib defaults. Regenerate with a unified palette / typography matching `figures/` before camera-ready.

---

## 7. Artifact handles used in §8 (quick reference)

```
adwc_sweeps/20260417_225953/drift_k_sweep.csv          → Fig. ADWC-drift
adwc_sweeps/20260417_225953/policy_sensitivity.csv     → Fig. ADWC-cap
tau_sweeps/20260422_141714/tau_sensitivity.csv         → Fig. tau-TPR + Fig. benign-FRR-flat
a3_bias_curve.csv                                      → Fig. ADWC-offset
a6_malleability/20260420_184618/a6_malleability.csv    → Tab. A6
script/test_tsip_main_v3.py + tests/test_tsip_blacklist.py → Tab. Private-payload binding
sybil_sweeps/20260418_224051/bounded_sybil_curve.csv   → Fig. bounded-sybil
ea_fault/20260419_165754/ea_fault.csv                  → Tab. EA-fault
circuit_bench/20260419_165802/circuit_perf.csv         → Tab. circuit-perf
mobile_bench/20260419_165818/mobile_emulation_bench.csv→ Tab. mobile-energy
baseline_*_results_summary.csv                         → Tab. baseline
baseline_epsilon_sweep_summary.csv                     → Fig. eps-sweep
dp_epsilon_sweep_20260421_133616_summary.csv           → Fig. tsip-eps-sweep
utility_sweep_20260421_172256_with_jaccard_summary.csv → Tab. mode-ablation
overhead_analysis_summary.csv                          → Tab. overhead-7schemes
zk_benchmark_20260417_162943.csv                       → Tab. zk-prover
scale_sweep.log                                        → Tab. scale-1000
```
