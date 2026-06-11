# TSIP-RUC 第二轮工作汇总
*供新对话继续使用*

---

## 本轮核心成果

### 1. 电路改动（已落地，终值）

`settlement_period_v5_base.circom` 完成以下改动，均已通过最终 phase-2 setup，`ZKey Ok!`：

**新增 6 个公开输入（public_signal_count: 15 → 21）：**
```
max_dt_sec, period_start_time, period_end_time,
month_id, month_start_time, month_end_time
```

**dt 硬上界（关闭 soundness 漏洞）：**
- `dtRange` 从 `Num2Bits(48)` 收紧到 `Num2Bits(16)`
- 新增 `dtMaxLE[i] = LessEqThan(16)`，断言 `dt[i] <= max_dt_sec`（= 600s）
- 组件声明区加 `component dtMaxLE[N_FIXES - 1]`

**continuity 操作数显式位宽断言（修复 soundness break）：**
- 新增 `capTierRange[i]`、`capModeRange[i]`、`distSqRange[i]`，均为 `Num2Bits(52)`
- `stepTierLE` / `stepModeLE` 比较位宽从 80 降到 52
- max_dt=600 后，cap_sq 上界从可能的 2^128 压至 ~2^51，`LessEqThan(52)` 操作数安全

**时间窗 + month 绑定：**
- 断言 `auth_time[0] == period_start_time`，`auth_time[N_FIXES-1] == period_end_time`
- `period_span <= 14400`（= PERIOD_MAX = 4h = 24×600s）
- 半开月窗：`month_start_time <= period_start_time < month_end_time`（`LessEqThan` + `LessThan`）
- month 一致性由 charger 侧查 canonical 日历表校验（不在电路做除法）

### 2. 电路终值指标

| 指标 | 结果 |
|---|---:|
| constraints | 226,394 |
| 旧 constraints | 224,234 |
| 新增 constraints | 2,160（≈90×24，per-interval range check） |
| public_signal_count | 21 |
| witness_ms | ~400–455 |
| prove_ms | ~7,997–8,717（snarkjs，macOS） |
| verify_ms | ~247–329 |

**说明：** prove/verify 抖动为正常测量噪声，Groth16 计时仅随机器负载浮动，与约束数无关。headline 数取多次中位数。

**rapidsnark 外推（13× 加速）：** 单 period prove ≈ **0.6s**，可作为客户端代表值。

### 3. 月度聚合策略（已定）

采用 **period-proof 直接累加**（direct accumulation）作为主结果，这是唯一有实测支撑的方案：
1. charger 验证 Groth16 period proof
2. 去重 `period_id`
3. 将公开的 `total_fee_cents`、`total_distance_m`、`fallback_intervals` 加入 `monthly_ledger[month_id]`

recursive SNARK 无实现无基准，放进 "modeled optimization / future work" 列，**不作为 60s 成本结论的前提**。

### 4. E6 月度成本表（终值，基于 direct accumulation）

按每天驾驶 2h × 30 天：

| cadence | proofs/月 | client prove snarkjs | client prove rapidsnark（外推） | server verify |
|---|---:|---:|---:|---:|
| 300s | 30 | ~240s | ~18.5s | ~7.4s |
| 120s | 75 | ~600s | ~46s | ~18.5s |
| 60s | 150 | ~1200s（20min） | ~92s（1.5min） | ~37s |

**Framing（去 hype）：** prove 是驾驶中增量后台产生（每 60s 约 0.6s），不是月底批量。verify 和带宽均可忽略。cadence 仅通过 period 数线性放大成本，每 period 成本是跨 cadence 的常数（电路结构固定 24 intervals）。

### 5. 共享日历函数（已落地）

`common/settlement.py` 中 `month_window_from_period_start(period_start_unix)` 返回 `(month_id, month_start_unix, month_end_unix)`：
- UTC 钉死（`datetime.timezone.utc`）
- 半开区间 `[month_start, month_end)`，相邻月 `month_end(本月) == month_start(下月)` 无缝衔接
- 闰年 / 月长由 `datetime` 日历逻辑处理，自动正确
- witness 生成器和 charger **共用同一函数**（放 `common/`，两端 import）
- 半开区间、月界秒、闰年 2 月均有回归测试
- 默认测试 19 passed，扩展测试 33 passed

**注意：** `period_start_time` 对应 2026 的 UNIX 时间戳约为 1780XXXXXX，不是 2025（1748XXXXXX）。

### 6. Harness 改动（已落地）

`common/eval_harness.py`：
- 新增 `Constraint.MAX_DT` 枚举
- `HarnessParams` 加 `max_dt_sec=600`
- 路径扩展加 `dt > max_dt_sec` 跳过（独立于 CADENCE：CADENCE 控制能否跳 fix，MAX_DT 控制段内 dt 大小）
- `e1_ablation_row()` 加 `no_max_dt` 行
- `_next_indices` 和 CADENCE 的语义不变

### 7. 已确认的负例

| 负例 | 结果 |
|---|---|
| `max_dt_sec=299`，dt=300 段 | witness 按预期失败 ✓ |
| `month_end_time == period_start_time` | witness 按预期失败（右开生效）✓ |

---

## 关键设计决策（已定，勿重开）

| 决策 | 结论 |
|---|---|
| max_dt_sec | **600s**（cap_sq 压至 ~2^51，给隧道 outage+TTFAF 留余量） |
| PERIOD_MAX | **4h**（= 14400s = 24×600，per-interval 与全局自洽，无需额外 sum 约束） |
| 月度聚合 | **direct accumulation**（主结果），recursive SNARK 为 future work |
| month 一致性 | **charger 侧钉**（查 canonical 日历表），不在电路做除法 |
| 月份归属 | **按 period_start（首个 auth_time）所属月**，跨月 period 不拆，文档写明 |
| month_id 编码 | **YYYYMM 整数**（202605 = 2026年5月） |
| 月窗区间 | **半开 `[start, end)`**，电路用 `LessEqThan` + `LessThan` |
| E1 距离语义 | **cell-level abstraction**（`payload_rem=0`），cell-level 是真实对手节省的保守下界 |
| E3 vs E1 精度 | E1 用 cell-level（保守 bound，够了）；E3 需纳入 payload_rem 余量（残余要真实量级） |

---

## Soundness 问题分析（已修复）

### 根因

`dt` 无有效上界（原 `Num2Bits(48)` ≈ 890 万年）→ `dt_sq` 可达 2^96 → `tier_step_cap_sq = tier_vmax_sq·dt_sq` 可达 2^128 → `LessEqThan(80)` 操作数超 2^80 → field 回绕 → `out` 可被对手任意设置 → **continuity 完全可绕过**（不是"放松"，是"消失"）。

### 修复路径

`max_dt=600` → `dt_sq ≤ 2^19.2` → `cap_sq ≤ 2^51` → `Num2Bits(52)` 显式断言 + `LessEqThan(52)` 比较安全。

### 论文处理方式

**两个后果必须分开写：**
1. **E1 行（经济）**：`no_max_dt` 行，可量化成"关闭后对手多省 X%"，进消融表。
2. **Soundness break（完整性）**：一旦触发是二元断裂（无界），写进 security analysis，**不进 E1 消融表**（消融表假设渐变，这里是断崖）。

---

## 实验状态（重要：区分"结果"与"脚手架"）

### 已有真实可进论文的数字

| 实验 | 状态 | 数字 |
|---|---|---|
| E6 单 period 性能 | **终值** | prove 7.997–8.717s（snarkjs），verify 0.247–0.329s，226,394 constraints |
| 几何绑定 audit | **真实数据跑出** | 10,498 段，60s p95=1.624，300s p95=3.443；120s 待补 |

### 还只是脚手架 / 环境

| 实验 | 状态 | 缺什么 |
|---|---|---|
| **E1** | harness 能跑 smoke | `cross_check_against_circuit()` 未接真实 witness；四数据集未全量跑；无正式 CSV |
| **E2** | OSNMA 参数已校准 | 未跑 Pareto sweep，无正式图 |
| **E3** | harness 存在 | 未跑残余 sweep；payload_rem 余量未纳入 |
| **E4** | 摄像头模型代码在 | 完全没跑对比，无数字 |
| **E5** | baseline 已选 | 无任何正式数字 |
| 四数据集 | 可出 2 条 smoke | 未全量预处理成可喂实验的 trip 集 |

---

## 外部 Baseline 设计（已定框架）

| 实验 | claim 类型 | 外部 baseline | 状态 |
|---|---|---|---|
| E1 | 内部组件边际 | 不需要（`all_on` 即对照） | ✓ 正确 |
| E2 | 内部 trade-off | 仅参数校准（OSNMA 文献） | ✓ 已校准 |
| E3 | 内部残余 | 需外部**标尺**（E4 摄像头漏报率给残余提供参照） | 待加锚定 |
| **E4** | **系统对比** | **必须（VPriv/PrETP/Milo）** | **✗ 没做** |
| E5 | 隐私对比 | 必须（GPS-upload 明文方案） | baseline 选好，数字没跑 |
| E6 | 内部成本 | 可选（RUC 系统开销量级对比） | 去 hype 完成 |

**关键结论：** 感觉"全在比内部"的根因是 E4 完全没做、E5 数字没跑。E1/E2/E3 本来就该是内部论断，硬加外部对比是错的。E4 一做完，整篇立刻有"和三个已发表 RUC 系统的 head-to-head"。

---

## 下一步：从脚手架转向第一张真实结果表

**最短路径（按 unblock 顺序）：**

### 第一步（优先级最高，E1 信任根）

**接 `cross_check_against_circuit()` 到真实 witness 生成器。**

现状：
- `cross_check_against_circuit()` 是空钩子，只对比 honest 轨迹的 `compute_bill == circuit_fee_fn`（stub lambda）
- `adversary_min_fee()` 的返回对象 `AdversaryResult`：**尚未确认是否暴露 `claimed_fixes`**（RCSPP `parent` 回溯出的对手轨迹）——**这是第一步唯一可能卡的点，先确认**
- `prove_settlement_period_v5.py` 的 `build_input()` 是固定 fixture，**需要拆成 `build_input_for_fixes(fixes, tariff, *, params, payload_rem_zero=True)`**
- cross-check 走 **subprocess**（调 `snarkjs wtns calculate`），不 import

Cross-check 要证的两个方向：
- **方向 A（正向）**：RCSPP `all_on` 最优对手轨迹 `claimed_fixes` → 构造 witness → 电路**接受** + 公开 `total_fee_cents == RCSPP.min_fee_cents`
- **方向 B（负向，关键）**：RCSPP `no_C` 的最优轨迹（利用约束 C 缺失）→ 全约束电路 → 电路**拒绝**。证明"harness 用约束 C 剪掉的轨迹，电路真的挡住了"

CADENCE 约束单独处理（`no_cadence` 轨迹在电路里表现为进 fallback，不是拒绝），先处理 `MAX_DT`、`CONTINUITY`、`ODOMETER` 三个。

**操作：先贴 `AdversaryResult` 定义和 `adversary_min_fee` 末尾返回值组装。**

### 第二步（可与第一步并行）

**四数据集全量预处理。**

目标：T-Drive / GeoLife / Porto / Rome 各出全量规范化 trip 集，补 120s 几何 audit（现有 60s 和 300s）。完成标志：各数据集 trip 数/点数统计。

### 第三步（前两步完成后）

**E1 第一张真实消融表。**

在四数据集上批量跑 `e1_ablation_row()`，出：
```
{all_on, no_odometer, no_continuity, no_cadence, no_max_dt} × 四数据集
```
这是打 desk reject 根因的那张表。

### 第四步（并行推进）

**E4 外部对比（最缺的 head-to-head）。**

需先定三件：
1. 对手成本口径：按"达到和 TSIP 同等检出率所需摄像头数"反解（推荐，直观：我们 0，他们 N 个）
2. 用哪个城市路网算摄像头密度 c（北京 / Porto / Rome 已有 PBF）
3. VPriv / PrETP / Milo 三个全列还是合并成"spot-check 谱系"一个 baseline

---

## 待补的工程项（汇总）

| 项目 | 优先级 | 说明 |
|---|---|---|
| `cross_check_against_circuit()` 接真实 witness | 最高 | E1 可信度根，先确认 `claimed_fixes` 暴露 |
| `build_input_for_fixes()` 拆分 | 高 | cross-check 前置 |
| 四数据集全量预处理 | 高 | 可并行 |
| 补 120s 几何 audit | 中 | cadence sweep 表需要 |
| cadence sweep driver（E2/E3 × {60,120,300}s 统一 CSV） | 中 | E2/E3 harness 已存在，加 driver |
| E3 纳入 payload_rem 余量 | 中 | E3 残余要真实量级，不能保守低估 |
| E4 外部对比正式数字 | 高 | 全篇 head-to-head，最缺 |
| E5 在实际公开信号集上算泄漏 | 中 | 注意 60s 下 150 条元组，非 2-bit |
| git commit（当前状态是干净里程碑） | 立即 | 源码 + `zk/settlement_period_v5_k6/` 仍未跟踪 |

**git commit 建议（现在就做）：**
```bash
git add circuits/ common/ services/ script/ zk/settlement_period_v5_k6/
git commit -m "v5_k6: add max_dt hard bound, explicit continuity bitwidth,
  [start,end] window + half-open month binding; re-setup; 226394 constraints,
  21 public signals; E1 no_max_dt row; shared UTC calendar"
```

注意：`.zkey` 建议 `.gitignore`（几十到上百 MB），只 commit 电路源码 + setup 脚本 + vkey。vkey 进库（verify 需要），zkey 靠脚本可重建。

---

## 论文 Framing 备忘

- **Thesis**：TSIP-RUC 是设计空间表最后一行：区域计费✓ + 隐私强 + 路侧基础设施零，代价是更强的设备信任假设。
- **Desk reject 根因（B）**：密码学被实验证明不起作用。**修复**：E1 消融表，每关一个组件露出该组件独自挡的那块钱。
- **Odometer 解耦 framing**：limitation 不是 vulnerability。放进 threat model 的 in/out-of-scope，不放末尾 limitations。三档加固（L1 已实现、L2 临界可行、L3 future work）写成 trade-off 表。
- **cadence 是统一旋钮**：贯穿成本（E6）/ 安全残余（E3）/ fallback penalty（E2）/ 隐私泄漏（E5），是"有真实张力的旋钮"（60s 更紧更可绑定，但披露更多 per-period 元组）。
- **E1 措辞**：cell-level abstraction 下的保守下界，真实电路余量只会让对手节省更多，故论断保守。
- **max_dt soundness break**：security analysis 里写二元 break，**不进 E1 消融表**。
- **跨月 period**：按起始月归属，period 不可分，billing model 段一句话写明。
- **月绑定信任根**：在 charger，charger 持有 canonical calendar，trusted for billing-correctness（本来就是）。
