# TSIP — E1 & Tier-1 Pipeline Handoff
> 生成时间：2026-06-10（接续 2026-06-09 版，反映 objective-fix / 四数据集真实结果 / Rome 官方 tariff / sweep 诊断定论）
> 用途：新会话上下文重建，接上所有决策与当前真实状态

> **Superseded Baseline Note（2026-06-11）**  
> 本 handoff 中仍出现的“攻击防御 / utility / 7 baseline（RiseFL、Nebula、EIFFeL、Pure LDP 等）”属于 RUC pivot 前的位置聚合版 TSIP 评估计划，不适用于 TSIP-RUC 道路使用计费论文。TSIP-RUC baseline 与后续执行顺序以 `TSIP_RUC_完整设计文档_2026-06-10.md` 的 §18、§19、§21 为准。

---

## 0. 项目背景（一句话）

TSIP（Temporal-Spatial Integrity Proof）是一套结合 zk-SNARK 与差分隐私的隐私保护位置数据聚合系统，论文目标投稿 NDSS 2027 Cycle 2 或 PETS 2027（论文**尚未开始撰写**）。E1 工作核心：**把经济消融从 fixture 常量换成真实数据上、真实 solver 输出、可追溯 receipt 的结果**（直击上次 desk-reject 根因 B）。

---

## 1. 电路参数（已确认，不可随意改动）

| 参数 | 值 | 说明 |
|---|---|---|
| `N_FIXES` | 25 | 每个 period 固定 25 个 fix |
| `TREE_DEPTH` | 8 | depth-8 Merkle tree → 256 leaves capacity |
| `GRID_SIDE` (k6 artifact) | **6** | 编进 WASM 的 grid side，`cell_idx = y*6 + x` |
| `cell_x/cell_y` 有效范围 | 0..5 | 超出则 WASM 拒收 |
| tariff leaf capacity | 256 | 256 个有效 tariff cell |

**关键纠错**：`16×16=256` ≠ proof-compatible。`grid_side=6` 是独立 bake 进电路的常数，与 256-leaf capacity 无关。仓库里**只有** `settlement_period_v5_k6` 一个 compiled artifact。N_FIXES / grid 不可随意改（要重 compile），**不要**在新会话重开 N_FIXES sweep（历史弯路，见第 10 节）。

---

## 2. Tier-1 预处理 Pipeline（已实现，未变）

### 2.1 核心文件

- `common/trajectory_preprocess.py` — raw adapters、rebase、trip segmentation、non-interpolating cadence selection、16×16 密度峰值 placement、local tariff table、period JSONL builder、rejects
- `script/prepare_tier1_datasets.py` — CLI
- `script/diagnose_tier1_grid_yield.py` — 一次性诊断脚本（已用，不需重跑）
- `tests/test_trajectory_preprocess.py` — 10 passed

### 2.2 输出契约（每个合法 dataset×cadence）

```
data/processed/
  manifest.csv
  {dataset}/
    raw_points.parquet
    trips_native.parquet
    fixes_{cadence}s.parquet
    periods_{cadence}s.jsonl      ← 核心产物，每行25个cell-level ReceiverFix
    rejects_{cadence}s.csv
```

### 2.3 合法 cadence 表

| 数据集 | 合法 cadence |
|---|---|
| T-Drive | 仅 300s |
| GeoLife | 60 / 120 / 300s |
| Porto | 60 / 120 / 300s |
| Rome | 60 / 120 / 300s |

### 2.4 关键约束（Tier-1 不做的事）

- **不做 map-matching**（Tier-2）
- 不插值造点（只 downsample）
- 不突破 256-cell tariff tree capacity
- Timestamp 全部 rebase 到 2026-05（锚点 `1777593600`）

### 2.5 16×16 tariff block 的真实角色

`16×16` 是**逻辑 tariff footprint**（密度峰值居中的 1.6km 收费区），不是电路 grid。`cell_idx` 按 `GRID_W=100` 展平（`cell_idx = cell_y*100 + cell_x`），匹配 k6 电路坐标语义。**block placement 由活动密度峰值驱动，不为吃到特定 rate 区而挪 block**（那是 cherry-picking，与拒绝 per-device cap 同性质）。

---

## 3. Grid Yield 诊断结论（已跑完，不需重跑）

- **T-Drive（出租车）**：proof-compatible 边界（1.6km / 256-leaf）内 `n_periods` 极少；3.2km 爆 capacity。出租车在边界内基本无 period，需 sparse-tariff 电路解锁（future work）。
- **GeoLife（个人移动，dwell-heavy）**：`g16/60s` 是唯一非平凡 yield 配置；N=14 是 max run 天花板，14 period 是真实上限不是 cap 卡住。
- **Rome**：60s cadence 下有大量 period（162 个进入 E1），是四数据集里 period 体量最大的。
- **N_FIXES sweep / per-device cap 分析**：历史弯路，已终止（见第 10 节决策 7）。

---

## 4. E1 的正确定义

### 4.1 savings ratio 的实际计算（已修，见 4.3）

```python
honest_bill = compute_bill(honest_claims(intervals))
claims = attack(honest, ...)
if check_constraints(claims, enabled, ...).passed:
    savings = honest_fee - attack_fee
else:
    savings = 0.0
pct = savings / honest_bill.total_fee_cents   # 分母是 fee
```

**savings ratio 是经济量（fee saved / honest fee），分母是 fee，不是 device 数。** device 集中度是 representativeness 注脚，不是 gate。

### 4.2 E1 是机制演示，不是统计总体估计

E1 量化的是**每条约束的边际经济攻击面**，不是跨设备总体统计。inv-Simpson / per-arm device 存活 / ≥5 设备门槛等框架是历史误配，已弃。

### 4.3 **objective/billing drift bug（本轮重大发现 + 已修）**

**病因**：`adversary_min_fee` 的内部 objective 用 `dist_m * rate` 算 edge cost，而真实账单 `compute_bill/fee_for_period` 在 `dt > cadence_sec` 时走 fallback：`ceil(dt * tier_vmax_mps) * max_zone_rate`。两份计费逻辑 drift，导致 fallback-heavy 的 period reported savings 被严重高估。

**暴露过程**：Rome bucket/radius sweep 跑出 lifted mean 0.92–0.95，逼近上次 checkerboard 假阳性（0.93）同区间。拆开 receipt 的真实 `attack_fee/honest_fee` 发现 actual signed savings 只有 ~0.004–0.006，reported 0.94 是假的。根因定位到 objective 漏了 cadence fallback 分支。

**污染面排查结果**：

| dataset | periods | fallback_periods | fallback_edges/total | affected landed rows |
|---|---|---|---|---|
| GeoLife main | 14 | **0** | 0/336 | **0/56** |
| T-Drive | 1 | 1 | 5/24 | 4/4 |
| Porto | 10 | 1 | 1/240 | 4/40 |
| Rome | 162 | 162 | 1088/3888 | 648/648 |

→ **GeoLife 主表行（economic anchor）未被污染**；污染全在 baseline/robustness 侧。

**修复**：
- `common/settlement.py` 新增 `fee_for_interval_values(...)`，作为 **edge-level billing single source of truth**。
- `fee_for_period` 和 `adversary_min_fee` 的 DP edge cost **都改走这一个函数**；`min_fee_cents` 再用 `compute_bill(claimed)` 同口径复核。
- `tests/test_eval_harness.py` 加 fallback drift 回归 + no_cadence 语义测试（跳点触发 fallback 时不再按旧距离目标低估）。

**修后 null check（实证封印，不是推断）**：GeoLife 主表核心行**逐位不变**：
- lifted `mean=0.083653535012519`
- zone-binding `mean=0.2695731652974051`
- pinned 仍全 0；只有 no_cadence 从 `0.0018018` 修为 `0.0`

**修后其他数据集真实量级**（reported → fixed）：
- T-Drive lifted `0.9918 → 0.005769`
- Porto lifted `0.126439 → 0.057569`
- Rome lifted `0.941496 → 0.039343`（此为同心圆代理 tariff；官方 tariff 见第 5 节）
- Rome no_cadence `0.958828 → 0.000143`

重跑产物：`experiments/e1_objective_fix/`。

---

## 5. Rome tariff：同心圆代理 → 官方 ATAC 分层（本轮重构）

### 5.1 旧 tariff 的问题

旧 Rome medium tariff 是 `common/osm_vectors.py` 内置**同心圆代理**（3km 内 zone1 rate5、7km 内 zone2 rate3、default rate1）。`dataset/osm/zones/` 当时不存在，所以 pipeline 走 fallback。结果 working block 256 cell **全落 zone1 → all-rate-5**，无 rate 异质性、无套利空间，lifted 修后贴 0（0.039）。**不是 checkerboard、不是 receipt fallback，但也不是现实分区。**

### 5.2 重构：官方 ATAC blue-stripe layer

- importer：`script/build_rome_parking_tariff_geojson.py`，从 Roma Mobilità/ATAC 官方 `strisce_blu_strade` polyline layer（字段 `TARIFFA`）生成 pipeline 可读 GeoJSON。
- 输出：`dataset/osm/zones/rome_medium.geojson`（`_load_tariff()` 优先用 GeoJSON，tariff source 进 receipt）。
- 原始官方 GeoJSON 缓存：`dataset/osm/zones/raw/`。
- 方法学说明：`dataset/osm/zones/README_rome_tariff.md`。
- **保比例 normalize**：官方 `0.50 / 1.00 / 1.20 €/h` → 整数 tier **5 / 10 / 12**（精确保比 1:2:2.4）。注意：上一版误用 `3/5/6`（比例被压成 1:1.67:2），已弃。
- polyline→cell 赋值：每 100m cell 取最近官方蓝线街道的 tier；同行连续同 rate cell 合并成 polygon（390 个，避免万级碎 polygon）。
- full grid rate hist：`5:800, 10:8755, 12:445`。

### 5.3 Rome 官方 tariff E1 结果（保比例版，`experiments/e1_rome_real_tariff_ratio_fix/`）

- working block 覆盖：`10:63, 12:193`（**tier-5 / 0.50€ 未进 block**）。
- `no_continuity`: mean `0.0`, n=162，pinned 全 0。
- `no_continuity_osnma_lifted`: mean `0.037685`, median `0.025465`, p95 `0.116618`, n=132, skip=30。
- `no_zone_binding`: mean `0.005622`。
- honest fee min/median/mean/p95/max: `27180 / 172327 / 173125.5 / 278094 / 330084` cents（spread 正常，无塌缩）。
- lifted saved cents mean: `5023.8`。

### 5.4 关键自洽点（ratio invariance）

`3/5/6` → `5/10/12` 后 savings ratio 差异 `0.0`。原因：current block 只覆盖 1.00/1.20 两档，该档真实比例 1.2 在 `6/5` 和 `12/10` 下都等于 1.2；绝对 fee/saved cents 翻倍但 ratio 不变。**savings ratio 对 tier 绝对缩放免疫，只对相对比例敏感** —— 这是 economic surface 定义的一致性检验。

⚠️ 表述边界：此 invariance **只在当前单档比例 block 成立**。若未来 block 同时覆盖 5 和 10（比例 2.0），旧 `5/3≈1.67` 与新 `10/5=2.0` 才会给出不同 ratio。所以保比例修复的意义是「任何覆盖多档的 block 都将正确反映官方比例」，**不能**写成「映射修复无数值影响」。

---

## 6. E1 当前真实状态与角色分工（核心）

### 6.1 主 economic anchor：GeoLife（唯一有真实 rate 异质性 + 已封印）

| Branch | n | mean | median | p95 |
|---|---|---|---|---|
| `no_zone_binding` | 14 | 0.26957 | 0.2765 | 0.4000 |
| `no_continuity` (pinned) | 14 | 0.0000 | 0.0000 | 0.0000 |
| `no_continuity_osnma_lifted` (25m) | 14 | 0.08365 | 0.0849 | 0.1417 |

- tariff：真实 Beijing medium overlay，rate ∈ [3,5]（1.67 倍异质）。
- 14 period 是 GeoLife 在 proof-compatible 边界内真实上限（不是 cap）。
- 已过 degenerate 核查 + objective-fix null check **逐位封死**。
- A1 receipt：14/14 pinned `chk.passed=false`，violation 含 OSNMA pinned-cell mismatch + odometer mismatch（lifted replay 改路径距离 → odometer 独立 catch，证明双防线不耦合），`receipt_savings_ratio=0.0`。

### 6.2 robustness 主力：四数据集 pinned 恒 0

| dataset | n | pinned no_continuity | 角色 |
|---|---|---|---|
| GeoLife | 14 | 全 0 | economic + robustness |
| Rome | 162 | 全 0 | robustness 主力 + 官方 tariff economic 辅证 |
| Porto | 10 | 全 0 | robustness 覆盖（n 小，旁证） |
| T-Drive | 1 | 全 0 | robustness 覆盖（n=1，旁证） |

**pinned 恒 0 不依赖 savings 量级**，只依赖「攻击被 OSNMA 挡下」的布尔结果，因此即便 lifted reported 曾被 bug 污染，robustness 半边从未塌。

### 6.3 Rome 官方 tariff economic 辅证

lifted 0.0377（真实但小，符合 1.2 倍费率差物理预期）。**Rome 不替代 GeoLife 当 economic anchor**，定位为「官方真实 tariff 下仍可见非平凡 surface 且被挡 0」的辅证。

### 6.4 E1 主 claim（措辞已定）

> **constraint ablation exposes marginal economic attack surface; pinned OSNMA blocks it across datasets.**

- "exposes ... surface" 需 rate 异质性 → 主要在 **GeoLife** exposed（magnitude）；Rome 官方 tariff 加入辅证。
- "blocks it across datasets" 需广度 + pinned 恒 0 → **四数据集**成立，不需 savings 量级。
- ⚠️ 写作时把两半物理分成两句，各带各自 dataset scope。**不要**让 "across datasets" 同时修饰 economic magnitude（那只在 GeoLife/Rome 两点，不是四点全有非平凡 magnitude）。

### 6.5 移出主表的行（未变）

| Branch | 去向 | 原因 |
|---|---|---|
| `no_odometer` (1.0) | submission gate / threat-model | 防线在 attestation 层，deliberate boundary 非漏洞 |
| `no_cadence` | security analysis | cleaned trips 结构性零信号；修后 GeoLife=0.0 |
| `max_dt` | security analysis | 预处理抹平 >600s gap，经济暴露为零 |

---

## 7. sweep（bucket/radius）定论：诊断工具，不进论文

- `run_e1_forensic.py` 已支持 `--distance-bucket-ms`、`--neighbor-radius-cells-list`（笛卡尔展开，维度进 rows/summary/receipt schema）；`common/eval_harness.py` schema 扩列 + solver 候选 cell/rate/distance 缓存。
- Rome 两条一维切片产物：`experiments/e1_sweeps/`。
- **sweep 的真正价值是它暴露了 objective/billing drift bug**（reported 0.94 vs actual 0.005）。
- 修 objective 后 Rome 因 tariff 结构（当前 block 单档比例 1.2）无漂亮响应曲线；GeoLife 14 period 体量撑不起 sweep 统计说服力。
- **结论：sweep 这条线作为诊断完成使命，不进论文当结果。** E1 不做 economic 响应曲线，只做 GeoLife economic 单点 + 四数据集 robustness 一致性 + Rome 官方 tariff 辅证。

---

## 8. 两个待写 framing finding（加分项，论文撰写时落）

1. **Rome tier-5 未覆盖 = 保守下界**：full grid 有 800 个 0.50€ (tier-5) cell，但活动密度峰值 working block 一个没吃到，所以 Rome 0.0377 只 exercise 了 1.2 倍那一档，2.4 倍最大差价未用上。如实写「Rome economic signal 是该数据集 proof-compatible block 内的**下界**」（低估非高估，方向安全）。block 不为吃低价区而挪。
2. **`no_zone_binding` 跨数据集差异 = 约束价值依赖 tariff 拓扑**：GeoLife 0.27 vs Rome 0.0056。同样攻击在 GeoLife 大块 zone 分层下能整体搬移获 0.27，在 Rome 街道级细碎分层下只得 0.0056。这是真实结论：**约束的边际经济价值是 tariff 空间结构的函数**，给 E1 加分析深度。

---

## 9. E1 Done 判定（当前 proof-compatible 边界内）

- [x] A1：GeoLife 14-period pinned 逐行 receipt 在库（chk.passed=False ×14）
- [x] B：forensic CSV 在可跟踪位置，表数字可重现
- [x] C：`main.tex` + `tab_e1_mechanism_ablation.tex` 进版本控制
- [x] A2：cadence 行选甲，写进表注
- [x] GeoLife 三行真数过 degenerate 核查 **+ objective-fix null check 逐位封印**
- [x] odometer 移出主表归 submission gate
- [x] tariff 硬失败（找不到真 tariff 报错退出）
- [x] objective/billing drift bug 修复（`fee_for_interval_values` single source of truth + 回归）
- [x] 四数据集 pinned 恒 0（robustness）
- [x] Rome tariff 同心圆代理 → 官方 ATAC 分层（保比例 5/10/12，可追溯）
- [x] sweep 定论（诊断完成，不进论文）

**E1 在当前 proof-compatible 边界内 done。** 真实状态：economic anchor=GeoLife 单点；robustness=四数据集；Rome=官方 tariff 辅证 + 162-period robustness 主力。剩两个 framing finding（第 8 节）在论文撰写时落，非阻塞。

---

## 10. E1 之外的实验状态

| 实验 | 状态 |
|---|---|
| E1 经济消融 | **done**（见上） |
| E2 fallback/outage sweep | Scaffolding，`outage_candidate` interval 是输入料，未正式跑 |
| E3 relay/forensic | Scaffolding |
| E4 道路几何 | 未开始，需路网 parse（Tier-2 map-matching 依赖） |
| E5 | Scaffolding |
| E6 single-period 性能 | 已有真实数据：rapidsnark ~320ms，3056 constraints，128-byte proof |

**E1 通了不等于 evaluation 通了。** 记忆里五个计划实验组（攻击防御 A1/A2/A5、utility Jaccard/RMSE、overhead/latency、scalability、ablation toggle）+ 7 baseline（Full TSIP / RiseFL / Nebula / EIFFeL / Pure LDP / Commitment-Only / No-Integrity）仍待做。utility 对比（Jaccard/RMSE vs ground-truth heatmap）是最高优先级缺失实验。

---

## 11. 代码 / 数据文件索引

| 文件 | 角色 |
|---|---|
| `common/trajectory_preprocess.py` | Tier-1 pipeline 主体 |
| `common/settlement.py` | **新增 `fee_for_interval_values` edge-level billing single source of truth** |
| `common/eval_harness.py` | E1 harness；`adversary_min_fee` 走共用计费 + sweep schema 扩列 |
| `script/prepare_tier1_datasets.py` | Tier-1 CLI |
| `script/run_e1_forensic.py` | E1 runner（真 tariff、audit receipt、branch filter、bucket/radius sweep） |
| `script/build_rome_parking_tariff_geojson.py` | **新增：官方 ATAC blue-stripe → tariff GeoJSON importer** |
| `dataset/osm/zones/rome_medium.geojson` | **新增：Rome 官方分层 tariff** |
| `dataset/osm/zones/raw/` | **官方原始 GeoJSON 缓存** |
| `dataset/osm/zones/README_rome_tariff.md` | **tariff 来源 + 保比例口径 + polyline→cell 赋值说明** |
| `tables/tab_e1_mechanism_ablation.tex` | E1 主表 LaTeX |
| `TSIP/main.tex` | 论文正文（已纳入版本控制，commit d1ea6d5b；论文尚未开写正文） |
| `tests/test_trajectory_preprocess.py` | 10 passed |
| `tests/test_eval_harness.py` | E1 harness + fallback drift 回归 + no_cadence 语义 |
| `tests/test_run_e1_forensic.py` | sweep schema / summary grouping / receipt dims / 旧单值回归 |
| `tests/test_build_rome_parking_tariff_geojson.py` | importer 测试 |

**关键 experiments 目录**：
- `experiments/e1_receipts/` — GeoLife 14-period + 四数据集 pinned receipt
- `experiments/e1_other_datasets/` — 四数据集 baseline summary（注意 lifted 量级为 objective-fix **前**，已被 `e1_objective_fix/` 取代）
- `experiments/e1_objective_fix/` — **修后四数据集真实结果（当前权威）**
- `experiments/e1_sweeps/` — Rome bucket/radius 切片（诊断用，不进论文）
- `experiments/e1_rome_real_tariff_smoke/` — Rome 官方 tariff 单 period smoke（`3/5/6` 旧映射）
- `experiments/e1_rome_real_tariff_ratio_fix/` — **Rome 官方 tariff 保比例 `5/10/12`（当前权威）**

**已 commit**（节选）：`f3bb2f7` E1 audit / `ee9f5ec9` GeoLife receipt / `d1ea6d5b` track main.tex / `cc7131a7` other-dataset receipts（注：其 lifted 量级为 objective-fix 前，解读以 `e1_objective_fix/` 为准）。objective-fix、Rome 官方 tariff、sweep 三批改动按本地工作树状态，commit hash 以实际仓库为准。

---

## 12. 关键决策备忘（别在新会话重开）

1. **map-matching = Tier-2**，不进 Tier-1 critical path。
2. **出租车（T-Drive/Porto/Rome 的出租车性质）在 proof-compatible 边界内 period 稀少**，需 3.2km+ cordon（爆 256-leaf）。sparse-tariff 电路 = future work。
3. **E1 是机制演示，savings ratio 分母是 fee 不是 device 数**。device 集中度写 limitation，不做 per-device cap。
4. **`no_odometer=1.0` 不进 E1 主表**，归 submission-layer / attestation-boundary，配 `verify_period_submission` REJECT receipt 一起讲。
5. **`no_cadence` 选甲**：结构性零信号，security analysis 证存在性，不进经济表。
6. **`no_continuity` pinned=0.000 是 OSNMA 在干活的证据**，必须和 lifted 成对呈现 + 表注讲因果。
7. **N_FIXES sweep / per-device cap 是历史弯路，已终止**，不要重开。
8. **tariff 硬失败强制**：runner 找不到真 `tariff_block.json` 必须报错退出，不许 fallback checkerboard。
9. **【新】objective 与 billing 必须共用 edge-level 计费**（`fee_for_interval_values`），禁止两份计费逻辑 drift。这是 Rome 0.94 假象的根因；drift 回归测试已钉死。任何改 attack objective 的人必须保证它和 `compute_bill` 同口径（含 cadence fallback 分支）。
10. **【新】tariff normalize 必须保真实费率比例**，绝对 tier 值随意（savings ratio 对绝对缩放免疫）。Rome 官方档 `0.50:1.00:1.20` → `5:10:12`。**不要**为凑某区间（如旧 `3/5/6` 凑 GeoLife [3,5]）牺牲比例——两城市 tier 无需可比。
11. **【新】block placement 由密度峰值驱动，不为吃到特定 rate 区而挪**。Rome tier-5 未进 block → 如实写「保守下界」，不挪 block 去够低价区（cherry-picking）。
12. **【新】Rome economic 辅证、不替代 GeoLife anchor**。"across datasets" 在 claim 里只修饰 robustness（pinned 恒 0），不修饰 economic magnitude。
