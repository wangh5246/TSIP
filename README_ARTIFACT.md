# TSIP-RUC Artifact Guide

> 2026-06-11。本文件回答三个问题:哪些测试是默认/扩展/需要 proof 工具链的;k6 电路 artifact 的权威指纹是什么;哪些实验目录是当前可引用的权威输出。设计与实验口径见 `TSIP_RUC_完整设计文档_2026-06-10.md`。

## 1. 测试分层

### 1.1 默认 pytest(纯 Python,无外部工具链)

```bash
python -m pytest
```

`pytest.ini` 的 `python_files` 限定默认只收集:

- `tests/test_charger_service.py` — charger API、proof-only 提交路径、负例
- `tests/test_settlement_architecture.py` — settlement 数据模型、commitment、billing、public statement
- `tests/test_dispute_opening.py` — 争议仲裁选择性披露 opening builder/verifier

### 1.2 扩展评估测试(纯 Python,需显式指定文件)

```bash
python -m pytest tests/test_eval_harness.py tests/test_eval_experiments.py \
  tests/test_run_e1_forensic.py tests/test_run_e4_e5_ruc_experiments.py \
  tests/test_run_e4_baseline_comparison.py tests/test_run_baseline_r_simulator.py \
  tests/test_build_rome_parking_tariff_geojson.py tests/test_trajectory_preprocess.py
```

这些覆盖 E1/E3 RCSPP solver、E2 fallback frontier、E4/E5 proxy runner 和数据管线。不在默认集是为了让默认 `pytest` 保持秒级。

### 1.3 Proof 工具链测试(需要 node / snarkjs / 已编译 artifact)

```bash
python -m pytest tests/test_prove_settlement_period_v5.py
```

依赖 `node` + `snarkjs` 和 `zk/settlement_period_v5_k6/` 下的编译产物。其中包含 wrapper public list / prover 输入前缀 / artifact `.sym` / vkey / charger `_TIME_SIGNAL_LAYOUT` 的三方一致性回归——**改动 public signal 顺序前必须先跑它**。

端到端 witness/prove/verify 实测:

```bash
python script/prove_settlement_period_v5.py
```

## 2. k6 电路 artifact 指纹(协议接口,不允许无测试漂移)

| 项 | 值 |
|---|---|
| circuit wrapper | `circuits/settlement_period_v5_k6.circom`(21 项 public list) |
| R1CS SHA-256 | `227782fe4208af6c85889bd6367b267ff139149d1498736c36a87e81356e9257` |
| SYM SHA-256 | `d0cdd919958c3af7e598f728d4e02cb4f060114acda0f41a1e15dd87c41739d7` |
| vkey `nPublic` | `21` |
| profile | `N_FIXES=25`, intervals=24, `max_dt_sec=600`, tariff depth 8 |

Public signal 顺序(= `script/prove_settlement_period_v5.py` 的 `PUBLIC_SIGNAL_ORDER`,charger `_TIME_SIGNAL_LAYOUT` 依赖 index 15-20):

```text
 0 receiver_fix_root        7 total_distance_m       14 max_zone_rate_cents_per_m
 1 tariff_root              8 fallback_intervals     15 max_dt_sec
 2 interval_commitment_root 9 cadence_sec            16 period_start_time
 3 period_id_field         10 tier_vmax_mps          17 period_end_time
 4 tariff_version          11 tier_vmax_sq           18 month_id
 5 device_attestation_…    12 mode_vmax_sq           19 month_start_time
 6 total_fee_cents         13 cap_policy_sq          20 month_end_time
```

体量:`zk/settlement_period_v5_k6/` 共约 257MB(`.zkey` 124MB、`.r1cs` 94MB)。这些是 trusted-setup 产物,默认不应直接进普通 git 历史;归档策略见设计文档 §21.4 #16(LFS / 外部 artifact 存储 / `script/setup_settlement_period_v5.sh` 重现)。

## 3. 权威实验输出目录

| 目录 | 实验 | 状态 |
|---|---|---|
| `experiments/e1_objective_fix/` | E1 | 权威(objective/billing drift 修复后) |
| `experiments/e1_rome_real_tariff_ratio_fix/` | E1 Rome 官方 tariff | 权威 |
| `experiments/e1_E1_FINAL_README.md` | E1 memo | 可引用数字清单 |
| `experiments/e2_fallback_frontier/` | E2 anchor(GeoLife/Rome) | 权威 |
| `experiments/e2_fallback_frontier_all4/` | E2 四数据集覆盖(+Porto/T-Drive) | 权威(2026-06-11) |
| `experiments/e3_relay_residual_all4/` | E3 四数据集全量 sweep | 权威(2026-06-11) |
| `experiments/e3_relay_residual_full/` | E3 GeoLife+Rome 全量 | 被 all4 取代,保留 |
| `experiments/e3_relay_residual/` | E3 首版 | 保留为 first-version 样本 |
| `experiments/e4_e5_ruc/` | E4/E5(proxy + 真实 drivable graph + GeoLife) | 权威(2026-06-11) |
| `experiments/e6_rapidsnark/` | E6 rapidsnark 实测 | 权威(2026-06-11,median 1.389s/proof) |

**不要引用**:`experiments/e1_sweeps/` 的 pre-fix Rome `0.94` 诊断、`experiments/e1_rome_real_tariff_smoke/` 的旧 `3/5/6` mapping;`TSIP_Baseline实验详细方案.md` 适用于 pivot 前聚合版 TSIP(已加 archived banner)。

## 4. 主要 runner

| 命令 | 输出 |
|---|---|
| `python script/run_e1_forensic.py` | E1 约束消融 + receipts |
| `python script/run_e2_fallback_frontier.py` | E2 alpha/break-even/incentive 表 |
| `python script/run_e3_relay_residual.py --output-dir … --workers 8` | E3 residual sweep(默认即全量口径) |
| `python script/run_e4_e5_ruc_experiments.py` | E4 spot-check proxy + E5 anonymity set |
| `python script/prove_settlement_period_v5.py` | E6 单 period witness/prove/verify 实测 |
| `python script/build_e4_drivable_graph.py` | E4 真实路网宇宙(需 osmium-tool + pyrosm) |
| `python script/run_e4_baseline_comparison.py` | E4 检出曲线 / 等检出工作点 / R-T-Z head-to-head |
| `python script/run_baseline_r_simulator.py` | Baseline R 经验 spot-check 仿真 + E5 泄漏光谱 |
| `python script/bench_rapidsnark.py` | E6 rapidsnark prover 实测(需先编译 rapidsnark) |

性能口径提醒(2026-06-11 更新):`snarkjs` 与 `rapidsnark` 均为 measured;rapidsnark median 1.389s/proof(5 runs,arm64 本机编译),receipt 见 `experiments/e6_rapidsnark/receipt.json`。
