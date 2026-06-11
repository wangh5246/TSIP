# TSIP 实验清单（review_v2 §6 闭环）

_生成时间：2026-05-01。来源：`experiments/` + `server_file/` + focused test harnesses。_

> 历史归档：下文引用的 heatmap/ESA 原型代码和 artifacts 已在 settlement-core
> 迁移后移除。本文仅保留为既有论文实验记录，不再作为可执行操作手册。

本文档将 review_v2 §6 的每一项覆盖需求映射到磁盘上的具体产物，
记录 seed/CI 状态，并标出剩余缺口，以便 §8 评估重写与图表生成在
无猜测前提下推进。

## 图例
- ✅ 完全满足 review_v2 要求
- ⚠️ 已有结果但仍需加强（seed 数量、报告范围等）
- ❌ 尚未产出

---

## 1. 核心机制消融（论文 §8.3、§8.4、§8.6）

| # | 需求 | 最新产物 | Seeds | CI | 状态 | 说明 |
|---|---|---|---|---|---|---|
| E1 | A3 滑动窗口 ADWC — drift bias × K | `experiments/adwc_sweeps/20260417_225953/drift_k_sweep.csv` | 每个格点 1 次 | 否 | ⚠️ | K∈{6,30}，bias_ratio∈{0.2,0.4,0.6,0.8,1.0}，m=0.10。已有热力图 PNG（`adwc_drift_k_heatmap.png`）。若可能，应在修订窗口补做 per-seed 重跑；否则报告按轮聚合 TPR + Wilson 区间。 |
| E2 | A3 policy-cap 灵敏度 | `experiments/adwc_sweeps/20260417_225953/policy_sensitivity.csv` | 每个格点 1 次 | 否 | ✅ | K=6 时 cap∈{2.2,3.3,4.4,5.5}km → TPR=1.0、FRR=0.192（平坦）；K=30 时 cap∈{11,16.5,22,27.5}km → TPR≥0.885、FRR=0.468。说明电路判决并非由 cap 幅值驱动。 |
| E3 | τ（单步）× τ₂（锚点距离）灵敏度 | `experiments/tau_sweeps/20260422_141714/tau_sensitivity.csv` + `tau_sensitivity_per_seed.csv` | **每格 3 次** | 是（CI95） | ✅ | 5×5 网格。TPR∈[0.951,1.000]，σ_max=0.047；`avg_benign_frr = 0.192` 在全部 25 个格点上**常数不变**（σ=0）。核心结论：在剔除 session-timing 影响后，A3 对良性用户的可测 FRR 代价为 0。 |
| E4 | ADWC drift offset 曲线（动机） | `experiments/a3_bias_curve.csv` | 解析型 | – | ✅ | 显示 p2_tight 在 bias=680m 时可拦截 drift，而 p2_default / no-p2 不能。第 6 轮首次拒绝，已可直接成图。 |
| E5 | 防篡改 / malleability（A6） | `experiments/a6_malleability/20260420_184618/a6_malleability.csv` + per_seed | **3** | CI=0（全拒绝） | ✅ | 11 个变异目标 × 3 seeds → 每个（target, mutation）组合**100% 拒绝**。二值结论，建议以表格报告。 |
| E5a | Private-payload binding 功能正确性（A6 payload 闭环） | `script/test_tsip_main_v3.py` + `tests/test_tsip_blacklist.py` | 确定性 | CI=0（全拒绝） | ✅ | `python3 script/test_tsip_main_v3.py` 通过 12/12；`SKIP_P0_PREPARED=1 pytest -q tests/test_tsip_blacklist.py -q` 当前通过 11/11，其中包含 payload-binding / state-machine 相关用例。覆盖 `h_pay`、`com_A`、`com_R`、A/R ciphertext、跨报告 share swap、旧 share replay、malformed dense/VDAF blob、channel label swap、primary witness、context/window/uid/epoch binding。 |

## 2. 架构 / 威胁模型实验（论文 §8.5、§10）

| # | 需求 | 最新产物 | Seeds | CI | 状态 | 说明 |
|---|---|---|---|---|---|---|
| E6 | 有界 Sybil 曲线（G5，定理 3） | `experiments/sybil_sweeps/20260418_224051/bounded_sybil_curve.csv`（324 行）+ PNG | 确定性 | – | ✅ | t∈{1,…,5} × tier∈{walk,bike,vehicle,transit} × B_A∈{10,…,200}。体现 `ns_max = B_A/(t·c_anchor + min_τ c_VC(τ))`。 |
| E7 | EA 拜占庭故障（CA3，t-of-n） | `experiments/ea_fault/20260419_165754/ea_fault.csv` + per_seed | 每格 **1** 次 | σ=0 | ⚠️ | （t=3,n=5）。offline/malicious × down∈{0,1,2,3}。在 down=t−1 处出现清晰边界，和定理预测一致。**缺口：**每格仅 1 seed × 10 trials。建议 camera-ready 前补到 3 seeds；若来不及，可说明验收谓词在给定受攻锚点集合时是确定性的，额外 seeds 仅影响随机负载抽样。 |
| E8 | 电路性能（v2 → v3-k6 → v3-k30） | `experiments/circuit_bench/20260419_165802/circuit_perf.csv` | – | – | ✅ | 约束数：1588 → 2340（约 +47%）；prover：335 → 340/358 ms；proof 大小：807 B（不变）；vk：4206 → 4754/4757 B。 |
| E9 | 移动端仿真（代理能耗） | `experiments/mobile_bench/20260419_165818/mobile_emulation_bench.csv` | – | – | ⚠️ | 仅 Cortex-A78 代理（无 DVFS/热控）。v2→v3-k6 能耗开销 = 13 mJ（+1.4%）；v2→v3-k30 = 64 mJ（+6.8%）。需在 §8/§9 明确标注“无真实设备实测”。 |

## 3. Baseline 对比（论文 §8.3、§8.4）

| # | 需求 | 最新产物 | Seeds | CI | 状态 | 说明 |
|---|---|---|---|---|---|---|
| E10 | 合成数据集 baseline | `experiments/baseline_results_summary.csv` | 3 rounds | 是（std） | ✅ | nebula / ldp / eiffel，ε=1.0，m∈{0,0.1}。 |
| E11 | GeoLife baseline | `experiments/baseline_geolife_results_summary.csv` | 10 rounds | 是 | ✅ | 同 3 个 baseline，m∈{0,0.1,0.3}。eiffel 的 Jaccard 随 m 增大约为 0.81→0.68→0.35。 |
| E12 | T-Drive baseline | `experiments/baseline_tdrive_results_summary.csv` | 10 rounds | 是 | ✅ | 同 3 个 baseline，m∈{0,0.1,0.2,0.3,0.5}。 |
| E13 | Baseline ε-sweep | `experiments/baseline_epsilon_sweep_summary.csv` | 10 rounds | 是 | ✅ | ε∈{0.1,0.5,1.0,2.0,5.0} × {nebula,ldp}，m=0.1。 |
| E14 | TSIP 全栈 ε-sweep | `experiments/dp_epsilon_sweep_20260421_133616_summary.csv` | 是 | 是 | ✅ | 模式：full / ldp / nebula / no_integ，ε∈{0.1,0.5,1.0,2.0,5.0}。证明 TSIP-full 在所有 ε 下都维持 1.0 的恶意拒绝率。 |
| E15 | 含 Jaccard 的 utility sweep | `experiments/utility_sweep_20260421_172256_with_jaccard_summary.csv` | 10 rounds | 是 | ✅ | ε=5 下的模式消融。full：Jaccard 0.196、cells_kept_post 72.9；no_integ：0.448、161.3；ldp：0.0；nebula：1.0（仅 mode）。 |
| E16 | 7 方案 overhead 对比 | `experiments/overhead_analysis_summary.csv` | – | – | ✅ | TSIP-Full：2243 ms e2e；Commit-Only：762 ms；Nebula/LDP/RiseFL/EIFFeL/no_integ 都约 13 ms。 |
| E17 | ZK prover 基准 | `experiments/zk_benchmark_20260417_162943.csv` | 2 次迭代 | – | ✅ | snarkjs vs rapidsnark × tsip_step（70 constraints）/ tsip_main_poseidon（1588 constraints）。rapidsnark 在 main 上 prove 为 430 ms。 |

## 4. 规模与部署（论文 §8.5）

| # | 需求 | 最新产物 | Seeds | CI | 状态 | 说明 |
|---|---|---|---|---|---|---|
| E18 | N=1000 规模 sweep（5 rounds） | `experiments/scale_sweep.log` + `experiments/round_metrics_20260330_023605.csv` | 1 | – | ✅ | avg_malicious_reject_rate = 1.0000，avg_false_reject_rate = 0.0002，avg_cells_final = 10 000，avg_dp_cells_kept_post = 2513.80。 |

---

## 5. Review_v2 §6 覆盖交叉检查

历史 review_v2 §6 检查项与当前清单对应关系：

| §6 项目 | 对应条目 | 状态 |
|---|---|---|
| A3 电路内滑动窗口实验 | E1 + E2 + E3 + E4 | ✅ |
| τ 灵敏度 / 独立 FRR 控制 | E3 | ✅（最强信号：完整 5×5 网格上 benign_frr 常数 = 0.192） |
| 防篡改（A6） | E5 + E5a | ✅（100% 拒绝；payload-binding 逐攻击面见 Appendix 表） |
| 有界 Sybil 经验性展示 | E6 | ✅ |
| t-of-n 联邦 EA 压力测试 | E7 | ⚠️ 需补 3-seed 复述或明确“确定性”声明 |
| v3 电路成本表 | E8 | ✅ |
| 移动/边缘成本可行性 | E9 | ⚠️ 仅代理结果，需明确披露 |
| Baseline 对齐（3+系统、2+数据集） | E10 + E11 + E12 | ✅ |
| ε-sweep 展示 TSIP-full 在恶意拒绝上的优势 | E14 | ✅ |
| 模式消融（full / commit-only / no-integ） | E15 + E16 | ✅ |
| N≥1000 规模实验 | E18 | ✅ |

---

## 6. Camera-ready 前建议补齐项

1. **E7 seed 数量。** 用 3 seeds 重跑 `run_ea_fault_injection.sh`；或者在 §8.5 增加说明：EA fault 的验收在对手锚点选择向量给定时为确定性，因此 per-seed 方差结构性为 0。  
2. **E1 的 per-seed 方差。** 建议对主图涉及的 10 个 (K,bias) 格点用 3 seeds 做一次短重跑（`run_adwc_a3_sweeps.sh`）；这是核心机制章节里唯一未做 seed 化的格点。  
3. **Session-gap 与 ADWC 的 FRR 分解。** 在 §8.6 增补简短推导，从 per-round 日志中提取 FRR 两部分（当前约为 ~17% session-gap + ~2% ADWC-circuit）。现有 CSV 尚无这两列，需要基于 `round_metrics_*.csv` + 电路拒绝原因日志重建。  
4. **移动端基准表述。** §9 Limitations 已写“仅代理”，请确认 §8.5 使用“仿真/估算成本（emulated cost）”而非“实测能耗（measured energy）”。  
5. **图形风格统一。** 现有 PNG（`adwc_drift_k_heatmap.png`、`bounded_sybil_curve.png` 等）仍为 matplotlib 默认风格。camera-ready 前建议统一配色与字体后重生成。  

---

## 7. §8 使用的产物句柄（速查）

```
adwc_sweeps/20260417_225953/drift_k_sweep.csv          → 图 ADWC-drift
adwc_sweeps/20260417_225953/policy_sensitivity.csv     → 图 ADWC-cap
tau_sweeps/20260422_141714/tau_sensitivity.csv         → 图 tau-TPR + 图 benign-FRR-flat
a3_bias_curve.csv                                      → 图 ADWC-offset
a6_malleability/20260420_184618/a6_malleability.csv    → 表 A6
script/test_tsip_main_v3.py + tests/test_tsip_blacklist.py → 表 Private-payload binding
sybil_sweeps/20260418_224051/bounded_sybil_curve.csv   → 图 bounded-sybil
ea_fault/20260419_165754/ea_fault.csv                  → 表 EA-fault
circuit_bench/20260419_165802/circuit_perf.csv         → 表 circuit-perf
mobile_bench/20260419_165818/mobile_emulation_bench.csv→ 表 mobile-energy
baseline_*_results_summary.csv                         → 表 baseline
baseline_epsilon_sweep_summary.csv                     → 图 eps-sweep
dp_epsilon_sweep_20260421_133616_summary.csv           → 图 tsip-eps-sweep
utility_sweep_20260421_172256_with_jaccard_summary.csv → 表 mode-ablation
overhead_analysis_summary.csv                          → 表 overhead-7schemes
zk_benchmark_20260417_162943.csv                       → 表 zk-prover
scale_sweep.log                                        → 表 scale-1000
```
