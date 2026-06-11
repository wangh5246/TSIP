# TSIP-RUC 对话总结

*整理自 2026-06-02 工作会话*

---

## 一、背景与起点

本轮对话基于 `tsip_ruc_session2_handoff.md` 接续。TSIP-RUC 是一个基于零知识证明的道路使用计费隐私保护系统，目标投稿 NDSS 2027 / USENIX Security 2027。系统核心思路：区域计费 ✓ + 强隐私 + 路侧基础设施零，代价是更强的设备信任假设。

桌面拒稿根因 B：**密码学被实验证明不起作用**。修复路径是 E1 消融表——每关一个组件，露出该组件独自挡的那块钱。

Handoff 时电路已完成 k6 最终配置：226,394 约束，21 个公开信号，rapidsnark 外推单 period 证明约 0.6s。

---

## 二、本轮核心成果

### 2.1 三个 Gate 框架的确立

本轮最重要的概念产出：**把"cross-check"拆成三个独立 gate**，各回答不同的 reviewer 质疑。

| Gate | 回答 | 关键断言 |
|---|---|---|
| **Constraint gate** | 密码学确实在约束某些东西 | controlled witness REJECT + 失败行 |
| **Submission gate** | 外部设备谎报被挡住 | charger `verify_period_submission` REJECT |
| **E1 forensic** | 经济消融的真实数字 | `savings_ratio` 记录表，0 是合法行 |

这个拆分来自真实 run 的取证结果（见 2.4），不是先验设计。

### 2.2 两层 Builder 拆分（已落地，commit a711cbd）

| 函数 | 用途 | 是否调用 charger 校验 |
|---|---|---|
| `build_input_for_fixes()` | 合法 fixture 回归 | ✓（签名验证、`fee_for_period` 守卫） |
| `build_raw_witness_input_for_fixes()` | Witness gate 负例构造 | ✗（跳过签名，直接绑定公开量） |

关键设计点：
- `N_FIXES = 25`，`payload_rem = 0`（cell-level abstraction）
- Roots 从 `claimed_fixes` 实算重建，不沿用 honest fixture 的 root
- `circuit_root_from_fixes()` 明确不绑定 `receiver_sig`
- 共享 `month_window_from_period_start()`（UTC，确认 `1777593600` = 2026-05-01，`month_id=202605`）

### 2.3 Fast-Path 修复

`eval_harness.py` 修复：**只有精确 `all_on` 可走 honest fast-path**，所有 ablation 进攻击构造路径。修复前 `no_continuity` 和 `no_max_dt` 在 OSNMA+CADENCE 开启时直接返回 honest fixes，导致后续任何 reject 断言都是假阳性。

### 2.4 真实 Witness 取证 Run（决定性）

使用真实 k6 fixture + `snarkjs wtns calculate` 的取证结果：

| 分支 | fixes 数 | savings | 电路结果 | 原因 |
|---|---:|---:|---|---|
| `all_on` | 25 | 0.0 | ACCEPT | — |
| `no_odometer` | 25 | 1.0 | **ACCEPT** | odometer 真实性在外部（签名层），不在电路 |
| `no_continuity` | 25 | 0.0 | 无攻击样本 | OSNMA cell-pinning 钉死，solver 造不出 teleport |
| `no_max_dt` | 25 | 0.0 | 无攻击样本 | cleaned trips 相邻间隔本就 ≤600s，天然为零 |
| `no_cadence` | 13 | 0.0 | 短轨迹（固定数组进不去） | deferred（需 active-mask 电路） |

**最重要推论**：`no_max_dt` 在 cleaned trips 上经济信号天然为零，不是 plumbing 问题——这与 handoff 的设计决策（max_dt 进 security analysis 不进消融表）完全吻合，run 给了它实测凭证。

### 2.5 Constraint Gate 两条证据（均已绿）

**Controlled `dt=601`**（已有）
- 电路结果：`returncode=1`，`Assert Failed`，**Circom 第 276 行 `dtMaxLE`**
- 归因干净：fee 等式用 `min_fee`（adversary 自己的声明）填，与电路重算一致，唯一失败源是 dtMaxLE

**Controlled continuity teleport**（本轮完成）

构造方法：在合法 tariff 叶子内枚举，找单侧越界最小候选。

关键参数：
```
CELL_SIZE = 100m, TIER_VMAX_SQ = MODE_VMAX_SQ = 1089
dt = 300s → cap_sq = 1089 × 300² = 98,010,000
tariff 有效 cell: 0..255（不能扫 100×100 整网格）
```

最小候选：`fix[1] 移至 (99,1)`（cell_idx=199）
- 前段：`dist_sq = 98,020,000 > cap_sq`（越界 10,000，唯一违例）
- 后段：`dist_sq = 94,100,000 < cap_sq`（合法）

电路结果：`returncode=1`，`Assert Failed`，**Circom 第 310 行 `stepTierLE`**，单点归因成立。

---

## 三、已修正的技术判断

### 3.1 Reject 分支应填 min_fee，不是 honest_fee

先前骨架里写"填 honest_fee 以隔离归因"——这是反的。

正确推论：电路约束是 `circuit_recomputed_fee === total_fee_cents`；电路从 claimed_fixes 重算费用 = `harness_fee(claimed_fixes)` = `min_fee_cents`（公式同源）。因此：

- 填 `min_fee`：fee 等式通过，唯一失败是 gating 约束，归因干净 ✓
- 填 `honest_fee`：`min_fee ≠ honest_fee`，fee 等式额外失败，两点失败，归因脏 ✗

统一规则：cross-check 里**始终填 `adv.min_fee_cents`**，accept 和 reject 分支均如此。

### 3.2 Precondition Skip-Gate

Reject 分支在运行前必须断言 `adv.savings_ratio > 0`，否则 skip 并提示"harness 未产生负例，先修 dispatch"。防止把"harness 没有造出攻击轨迹"误判为"电路有问题"。

### 3.3 stdout vs stderr

`Assert Failed` 出现在 stdout；stderr 只有简化错误行。verdict 唯一权威是 `returncode`，归因需合并扫：
```python
blob = f"{r.stdout}\n{r.stderr}"
```

---

## 四、当前各实验状态

### 已有真实可进论文的数字

| 实验 | 状态 | 数字 |
|---|---|---|
| E6 单 period 性能 | **终值** | prove 7.997–8.717s（snarkjs），verify 0.247–0.329s，226,394 constraints，21 public signals |
| 几何绑定 audit | **真实数据** | 10,498 段；60s p95=1.624，300s p95=3.443；120s 待补 |
| Constraint gate | **两条均绿** | dt=601→276行；teleport→310行 |
| 月度成本表 | **终值** | direct accumulation，cadence 300/120/60s 月度 prove 18.5/46/92s（rapidsnark） |

### 还只是脚手架 / 未跑

| 实验 | 状态 | 缺什么 |
|---|---|---|
| **E1** | harness 建模需修正 + gate 层近完工 | OSNMA+continuity 联合 ablate；四数据集未全量；无正式 CSV |
| **E2** | OSNMA 参数已校准 | 未跑 Pareto sweep，无图 |
| **E3** | harness 存在 | 未跑残余 sweep；`payload_rem` 余量路径未 exercise |
| **E4** | 最大内容洞 | 三决策未定，摄像头密度未算，无任何 head-to-head 数字 |
| **E5** | baseline 已选 | 泄漏数字未算 |
| Gate 层 | submission_gate + e1_forensic | 设计完成，未写代码 |
| 四数据集 | 仅 2 条 smoke | 未全量预处理为规范化 trip 集 |

---

## 五、进度诚实评估

| 层级 | 状态 | 完成度 |
|---|---|---|
| 信任根 / Gates | constraint gate 2/2；submission_gate + e1_forensic 设计完，未写 | ~90% |
| 实验本身（进论文的表/图） | E6 + 几何 audit 部分；E1-E5 多数是脚手架 | ~25–30% |
| 四数据集预处理 | 仅 2 条 smoke | ~10% |

**工期主体在两根长杆：数据集预处理（喂 E1/E2/E3/E5）+ E4（不等数据，可立刻并行）。**

---

## 六、两条并行长线设计

### 6.1 四数据集预处理 Pipeline

**核心判断：Tier-1 不做 map-matching**，先出第一张真实表；Tier-2（HMM 贴路网）只有几何 audit 数字看着噪时才加，且复用 E4 的路网 parse。

**Pipeline 分层：**

```
stage 0  per-source adapter      → RawPoint(device_id, t_unix, lat, lon)
stage 1  rebase_to_2026          → 平移到 2026 锚点，保持 intra-trip dt
stage 2  segment_trips(gap=30min)→ gap>600s 内部标记（E2 outage 料）
stage 3  resample(cadence)       → 仅 ≥ 原生采样率的 cadence 合法（见下表）
stage 4  project_quantize        → 等距投影→米→//100→cell_x/cell_y，裁 tariff 区
stage 5  odometer(原生轨迹)      → resample 前累加 great-circle，附到每帧
stage 6  window_periods(N=25)    → list[list[ReceiverFix]]
stage 7  manifest.csv            → 完成标志
```

**per-dataset cadence 可行性：**

| 数据集 | 城市/模式 | 原生采样 | 合法 cadence |
|---|---|---|---|
| T-Drive | 北京/出租车 | ~177s（极不规则） | **仅 300s** |
| GeoLife | 北京/多模 | 1–5s | 60 / 120 / 300 |
| Porto | Porto/出租车 | 15s（规整） | 60 / 120 / 300 |
| Rome | Rome/出租车 | ~7–15s | 60 / 120 / 300 |

**两个必须先定的约束：**
1. Timestamp rebase 到 2026（anchor `1777593600`，month_id `202605`）
2. Tariff tree capacity 是电路参数（现有 256 cell）——真实 zone overlay 必须裁到容量内，否则需 re-setup（新 zkey，E6 headline 要重测）

### 6.2 E4 — 三决策 + 摄像头密度

**基础设施机制已确认：** VPriv（USENIX Security 2009）、PrETP（USENIX Security 2010）、Milo（USENIX Security 2011）均依赖路侧抽查摄像头或巡逻警车执法；PrETP 审计时打开摄像头观察到的路段的同态承诺；Milo 建在 PrETP 上，用 blind IBE 修掉摄像头位置泄漏，但摄像头本身仍在。三者在路侧基础设施维上完全同质。

**三决策结论：**

| 决策 | 结论 |
|---|---|
| 对手成本口径 | "达到 TSIP 同等检出率所需摄像头数"，**必须先钉"少报/谎报更便宜路径"为共同欺诈类** |
| 哪城路网 | 三城全算（北京/Porto/Rome 均有 PBF），报 range；bbox 与 tariff overlay 一致 |
| 三系统合并还是分列 | 合并成 "spot-check 谱系（VPriv/PrETP/Milo）" 一列；related work 引全三篇 + 脚注差异 |

**E4 双轴叙事：**
- 数量轴：TSIP 0 路侧摄像头 vs 同等保证需 N 个
- 攻击面轴：摄像头布点泄漏 / 串谋避摄像头 → 对 TSIP 不适用（零摄像头，整类攻击面不存在）

**密度计算（不等数据，现在可起）：**
```
PBF → 可驾驶路网图（裁到 tolled 区）
  → 候选布点（路口/路段中点）
  → 检出模型：P(被观测) = 1 - (1-q)^K
  → 解 q 使 P ≥ TSIP 检出率
  → 输出 cameras/km²、cameras/km tolled road，三城各一
```

此路网 loader 同时是 Tier-2 map-matching 的前置，建了不浪费。

---

## 七、关键设计决策（已定，勿重开）

| 决策 | 结论 |
|---|---|
| max_dt_sec | 600s |
| PERIOD_MAX | 4h = 14400s = 24×600 |
| N_FIXES | 25（24 区间） |
| 月度聚合 | direct accumulation（主结果），recursive SNARK 为 future work |
| month 一致性 | charger 侧钉 canonical calendar，不在电路做除法 |
| 月份归属 | 按 `period_start` 所属月，跨月不拆 |
| month_id 编码 | YYYYMM 整数（202605 = 2026年5月） |
| 月窗区间 | 半开 `[start, end)`，`LessEqThan + LessThan` |
| E1 距离语义 | cell-level abstraction（`payload_rem=0`），保守下界 |
| max_dt soundness | security analysis 写二元 break，**不进 E1 消融表** |
| no_cadence | deferred，等 active-mask 电路 |
| Reject 分支 fee 填法 | **始终填 `adv.min_fee_cents`**（与电路重算一致） |
| Cross-check 层级 | 三 gate 分离（constraint / submission / e1_forensic） |
| Baseline 合并 | VPriv/PrETP/Milo → 一列"spot-check 谱系" |

---

## 八、已提交 Commit

```
a711cbd  feat: add E1 raw witness input builder
```

包含 6 个文件：`eval_harness.py`、`settlement.py`、`prove_settlement_period_v5.py`（含两层 builder）、`design.md`、相关测试。`34 passed`（扩展），`19 passed`（默认）。

---

## 九、下一步（按 unblock 顺序）

1. **立刻**：submission_gate + e1_forensic 写完，gate 层封顶，commit（小活，几小时级）
2. **并行起两条长线**：
   - 数据集预处理：stage 0–2（T-Drive adapter + 2026 rebase + trip 切分）先跑通，出第一版 300s T-Drive manifest
   - E4 密度计算：定三决策 + 写 PBF→路网→密度 driver（不等数据）
3. **数据落地后**：E1 真实消融表（含 OSNMA+continuity 联合 ablate 建模修正）→ E2 Pareto → E3 残余 sweep → E5 泄漏
4. **E4 数字**：摄像头密度三城 → head-to-head 表
