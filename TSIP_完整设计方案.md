# TSIP完整设计方案 - Part 1: 概述与理论基础

## Temporal-Spatial Integrity Proof for Privacy-Preserving Location Aggregation

---

## 目录
- Part 1: 概述与理论基础 (本文档)
- Part 2: 协议设计与实现
- Part 3: 安全性证明
- Part 4: 实验评估与论文撰写

---

## 文档使用说明（与当前实现对齐）

本项目已经从“纯设计方案”进入“已部署原型系统”阶段。为了避免文档与代码、实验、远程部署结果脱节，本文档从当前版本开始同时保留两套口径：

- 设计目标口径：描述 TSIP 的完整研究目标与理想参数
- 当前实现口径：描述仓库中已经实际落地、完成本地和远程验证的版本

后续阅读原则如下：

- 如果某一机制已经在代码中稳定运行，则以当前实现口径为准
- 如果某一机制仍属于设计目标但尚未完全实现，则明确标记为“待完成”
- 论文写作时，系统实现章节应优先使用“当前实现口径”
- 后续研发与实验应围绕“设计目标口径”和“当前实现口径”的差异逐步收敛

### 当前实现对齐摘要（2026-03，更新至 2026-03-27）

| 项目 | 设计目标 | 当前已验证实现 | 当前状态 |
|------|----------|----------------|----------|
| 时间窗口 | `300s` | `60s` | 参数对照实验已确认 `60s/110` 为最优工程参数，`300s/100` 保留为设计目标对照参数 |
| 最大速度阈值 | `100 m/s` | `110 m/s` | 当前值为实验调优后的最终工程参数 |
| 网格域大小 | `10^8` | `10^4` | 当前仍是 MVP/部署规模 |
| 承诺哈希 | `Poseidon` | `Poseidon2` | 已统一为 Poseidon2 路径（客户端承诺计算与 `tsip_main` 电路一致，2026-03-24 修复） |
| TSIP 主证明 | 需要 | 已实现 | 已完成 `tsip_main` 电路、证明生成、服务端验证 |
| 承诺链连续性 | 需要 | 已实现 | 已完成位置承诺 + 链承诺连续性校验，修复后经 30 轮验证稳定 |
| 远程部署 | 需要 | 已实现 | 已在 CPU-only 远程服务器通过验收，rapidsnark 双路径已闭环 |
| DP 预算门控 | 需要 | 已实现 | 已完成 `privacy_budget_reset/status` 与 `dp/latest` 闭环 |
| 黑名单策略 | 需要 | 已实现当前版本 | 已完成连续拒绝计数、阈值封禁和成功后清零 |
| 合成数据实验 | 需要 | 已完成 | 服务器 30 轮（2026-03-27）为最终主结果，`false_reject_rate=0.0017` |
| 真实数据实验（GeoLife） | 需要 | 已完成 ✅ | 服务器修复版 10 轮（2026-03-29），avg_valid_clients=45.10，malicious_reject_rate=1.0000，false_reject_rate=0.0111 |
| 真实数据实验（T-Drive） | 需要 | 已完成 ✅ | 主实验 10 轮（2026-03-30）malicious_reject_rate=1.0000，false_reject_rate=0.0000；**+ boundary sweep 7档（2026-04-05）：阈值以上 100% 检测，false_reject_rate ~3.5%** |
| No-ZK Baseline 对比实验 | 需要 | 已完成 ✅ | 服务器 10 轮（2026-03-29），malicious_reject_rate=0.0000，与 TSIP 形成完整对比 |
| 规模扩展实验 | 需要 | 已完成 ✅ | 服务器 200/500/1000 各 5 轮（2026-03-29/30），malicious_reject_rate=1.0000，false_reject_rate 随规模下降 |
| 攻击强度 sweep（A1 boundary） | 需要 | 已完成 ✅ | **2026-04-01 Synthetic + 2026-04-05 T-Drive**，7档（1000/3300/5940/6534/6600/6666/7200m），各 10 轮；阈值以上 T-Drive 100% 检测，S 型曲线见 `experiments/tsip_scurve.png` |
| A2 身份交换攻击实验 | 需要 | 已完成 ✅ | 服务器 10 轮，stable scope（2026-03-31），malicious_reject_rate=1.0000，false_reject_rate=0.0000 |
| A5 重放攻击实验 | 需要 | 已完成 ✅ | 服务器 10 轮，stable scope（2026-03-31），malicious_reject_rate=1.0000，false_reject_rate=0.0000 |
| A3 渐进偏移攻击实验 | 需要 | 待完成 ⏳ | 需补 10 轮实验，预期 `malicious_reject_rate` 接近 0（用于 Discussion：TSIP 抬升攻击成本而非消灭慢速攻击） |
| Claim 口径收敛 | 需要 | 已启动 ✅ | 统一收敛为“trajectory continuity/plausibility filtering + attack-cost elevation”，不再表述为“ground-truth presence” |

### 当前系统已完成的部分

当前仓库中已经完成并验证的内容包括：

- `zk_step` 单步约束证明与验证
- `tsip_main` 主电路（Poseidon2）、证明生成、验证与链式状态维护
- `client_sim / shuffler / aggregator_a / aggregator_r / decoder` 全链路联调
- secure reconstruct 与 privacy budget gate
- 本地部署、远程服务器部署、离线镜像部署
- rapidsnark 双路径证明器集成（服务器侧负向/正向双验证闭环）
- Poseidon2 承诺链断裂修复（2026-03-24）
- 参数对照实验（`60s/110` vs `300s/100`，确认最终工程参数）
- 合成数据多轮实验：本机 10/30 轮、服务器 10/30 轮（修复后），全部通过

目前最关键的稳定实验结果为：

- `malicious_reject_rate = 1.0`（截至当前已记录 TSIP 批次中均观测到）
- `malicious_reject_rate = 0.0`（No-ZK baseline，无保护时攻击全部通过）
- `false_reject_rate = 0.0017`（服务器合成数据修复版 10 轮与 30 轮结果一致）
- 服务器 30 轮主结果文件：`experiments/round_metrics_20260327_092202.csv`（论文可用）

### 当前系统尚未完成的部分（按审稿风险重排，2026-04-01）

与完整设计目标相比，当前优先缺口如下：

- P0（必须先补，影响论文可信度）
  - **证明-载荷绑定（proof-payload binding）未完成**：当前证明的是 `prev_loc -> curr_loc` 连续性，但需进一步证明上传的 share/cell/weight 与同一 witness 绑定，防止“合法证明 + 非法 payload”拆分攻击。
  - **A1 细粒度边界扫描（论文口径）未完成**：需使用 `tdrive + stable + warmup`，围绕 6600m 阈值做细粒度距离档位实验。
  - **A3 渐进偏移实验未完成**：需量化“可行但高成本”的慢速攻击路径，作为主文 Discussion 关键证据。
- P1（次优先级，影响安全叙事完整性）
  - **身份绑定增强未完成**：需要将 hidden per-user secret / nullifier / epoch anti-replay 统一到协议状态机和证明描述中，避免仅依赖“攻击者不知道坐标”的叙事。
  - **协议状态机形式化未完成**：需要明确 fork / double-submit / late arrival / missed round / re-enrollment 语义及处理策略。
  - **DP 叙事收敛部分完成**：主文已切换为 public-output DP 口径；仍需补 `who learns what` 泄露表和 SVT 引用定理的逐条对齐。
- P2（实验对比完整性）
  - **Utility 指标框架未落地**：ground truth heatmap + Jaccard/RMSE/Relative Error 自动化统计尚未形成稳定脚本闭环。
  - **Baseline 与消融未落地**：RiseFL/Nebula/LDP/Commitment-only 及 6 组消融尚缺可复现实验脚本与结果。
- 已完成但保留项
  - ~~服务器 GeoLife/T-Drive/规模扩展~~ 已完成，可作为现阶段工程可运行证据。
  - Poseidon helper 原生实现替换、黑名单持久化属于优化项，不阻塞当前投稿主线。

### 顶会口径收敛（2026-04-01，覆盖后文旧口径）

若本文档后续章节与本节冲突，以本节为准。

1. 主张边界（Claim Discipline）
   - 当前 TSIP 的强保证是：**跨轮轨迹连续性/物理可行性约束**，以及由此带来的**攻击成本抬升**。
   - 当前 TSIP **不直接保证**：设备在场真实性（ground-truth presence）或“真实世界位置真实性”。
   - 论文主叙事统一为：`privacy-preserving aggregation + trajectory plausibility filtering + attack-cost elevation`。

2. 安全边界（Truth Gap）
   - enrollment 不是唯一 truth gap；若攻击者从首轮开始伪造“平滑但虚构”的轨迹，系统可能接受其连续链。
   - 因此理论表述必须明确：完整性定理针对“链深度 >= 1 且在系统假设内”的连续性，不外推为真实性定理。

3. DP 口径（Public DP vs Internal Leakage）
   - 主文 DP 口径改为：**只对公开发布的最终热力图**给出 DP 保证。
   - 内部可见信息（accept/reject、链状态、时序元数据）单列为 internal leakage，不并入主 DP 预算。
   - 当前推荐总预算口径：`ε_total = ε_SVT + ε_value`（现网默认 `0.3 + 0.7 = 1.0`）。
   - `ε_verify` 仅保留为可选随机化验证实验项，不再作为默认主结果组合项。

4. 当前最高风险（必须先修）
   - proof 与 payload 的同 witness 绑定未形式化时，不应在论文中做强完整性闭环宣称。
   - 该项进入“第一优先级（本周）”。

### 下一步工作顺序（与精进指南对齐，按当前进度重排）

第一优先级（本周，P0）：

1. 完成 proof-payload binding 方案与实现草案（至少到“签名摘要绑定 payload digest + epoch + round_id”级别）。
2. 重跑 A1 细粒度边界扫描（`tdrive + stable + warmup`，围绕 6600m 阈值）。
3. 补齐 A3 渐进偏移实验（10 轮，输出攻击成本曲线与 time-to-poison）。
4. 产出 `who learns what` 泄露表并更新主文 DP 叙事。

第二优先级（下周，P1）：

1. 实现 ground truth 热力图与 Jaccard/RMSE/Relative Error 指标闭环。
2. 运行“Money Figure”：TSIP vs No-Integrity 在攻击率梯度下的 utility 退化对比。

第三优先级（后续，P2）：

1. 落地 RiseFL / Nebula / LDP / Commitment-only baseline。
2. 跑 6 组消融（含 zk_step 价值定位），避免“模块存在但贡献不可观测”的叙事风险。

### 顶会评审意见整合清单（精进指南 + 外部意见，2026-04-01）

以下清单用于统一“意见 -> 方案 -> 落地状态”，后续以此驱动周计划。

| 审稿风险点 | 统一结论 | 落地动作 | 当前状态 |
|---|---|---|---|
| Claim overreach（把 continuity 说成 truthfulness） | 采纳，必须收敛主张边界 | 主文统一改写为 continuity/plausibility + attack-cost elevation | 已执行（主口径） |
| proof 与 payload 可能脱绑定 | 采纳，P0 阻塞项 | 引入 payload digest 绑定（proof/attestation 同摘要）并补攻击实验 | 进行中 |
| identity swap 论证依赖“不知道坐标”过弱 | 采纳，需改为密码学绑定 | 加 hidden user secret + epoch/nullifier，一致性跨轮证明 | 设计中 |
| 状态机未形式化（fork/double-submit/late/missed） | 采纳，系统定理前置条件缺失 | 补状态机定义与处理规则，并映射到 API 行为 | 进行中 |
| Theorem 语义桥未写清（range/timestamp/projection/noise） | 采纳，避免 theorem overclaim | 将物理语义与密码学语义分层，显式列出前提 | 进行中 |
| DP 叙事可能被打穿（verify budget） | 采纳，主口径已调整 | Public-output DP 与 internal leakage 分离；`ε_verify` 转为可选实验项 | 已执行（主口径） |
| baseline 稻草人风险 | 采纳，需确保公平性 | baseline 使用同数据/同预算/同攻击面；报告 CI 与失败案例 | 待执行 |

### 未来 14 天执行路线（可直接用于周报）

1. 第 1-3 天：proof-payload binding 方案与最小实现（P0）
   - 目标：阻断“合法证明 + 非法 payload”拆分攻击。
2. 第 4-6 天：A1 细粒度阈值扫描 + A3 渐进偏移（P0）
   - 目标：给出边界曲线与攻击成本曲线，不再只报单点 TPR。
3. 第 7-10 天：Utility 框架（ground truth + Jaccard/RMSE/RelErr）（P1）
   - 目标：产出 money figure 的可重复脚本与 CSV。
4. 第 11-14 天：Baseline + 消融最小闭环（P2）
   - 目标：先完成 No-Integrity / Commitment-Only / Nebula，再扩 RiseFL/LDP。

### P0 协议修订：Proof-Payload Binding v1→v2（2026-04-01）

本节用于回应“合法证明 + 非法 payload 拆分”风险，作为后续实现与论文口径的统一规范。

#### v1 目标（已实现口径）

- 目标不是证明“真实世界位置真实性”，而是保证：
  - 被验证通过的 proof、承诺链状态、最终上送 payload 在提交链路内不被替换。
- v1 重点是 **consistency binding（提交一致性）**，不是语义绑定终态。

#### v1 绑定对象

定义 `payload_core`（规范化序列化后摘要）：

```text
payload_core = {
  round_id,
  submission_id,
  channel,                 # A or R
  user_id,
  window_id,
  idx,                     # 上送索引数组
  val,                     # 对应 share/value 数组
  tsip_prev_loc_commitment,
  tsip_curr_loc_commitment,
  tsip_prev_chain_commitment,
  tsip_curr_chain_commitment,
  tsip_time_diff,
  tsip_max_dist_sq
}
payload_digest = SHA256(CANONICAL_JSON(payload_core))
```

同时定义 `proof_digest`：

```text
proof_digest = SHA256(CANONICAL_JSON({
  tsip_public_signals,
  zk_step_public_signals
}))
```

#### v1 验证与转发规则（状态机）

1. Shuffler 侧：
   - 先做 `zk_step + tsip` 验证；
   - 计算 `payload_digest/proof_digest`；
   - 生成 attestation 签名消息：
   - `ATT = H(channel|round_id|submission_id|user_id|window_id|payload_digest|proof_digest|prev_chain|curr_chain)`
   - 强制单用户单窗口单提交：
   - 若同 `(user_id, window_id)` 出现第二份不同 `curr_chain`，标记 fork 并拒绝。

2. Aggregator 侧：
   - 仅接收 `>= threshold` 个有效 committee 签名的提交；
   - 本地重算 `payload_digest`，必须与 attestation 内摘要一致；
   - 若摘要不一致，直接拒绝，不进入聚合缓冲区。

3. Decoder/重建侧：
   - 不参与绑定判定，仅消费已通过门限验签的数据。

#### v1 安全语义（论文可写）

- v1 保证的是“proof 与 payload 的提交一致性（consistency binding）”。
- v1 仍不等价于“设备在场真实性”；presence 需要额外锚定机制（attestation / OOB anchor）。

#### v2 语义绑定升级（P0 必做）

为回应“proof 证明了连续性，但 payload 可能来自另一语义对象”的质疑，v2 将绑定从传输一致性升级为**密码学语义绑定**：

1. 新增 witness 关系（电路内）
   - 在证明语句中引入 `payload_commitment`（或 `contrib_commitment`）；
   - 证明目标从：
   - `R_continuity(w) : prev->curr 连续`
   - 升级为：
   - `R_semantic(w) : prev->curr 连续 ∧ payload_commitment = Commit(F(curr_loc, idx, val, clip, epoch, round_id, window_id))`

2. 新增公开输入（canonical v2）
   - `public_inputs = [hash_prev, hash_curr, max_dist_sq, payload_commitment]`
   - 聚合器接收的 `payload_digest` 需与 `payload_commitment` 对应（经规范化映射）。

3. 语义效果
   - committee attestation 负责“链路防篡改”；
   - zk 关系负责“proof 与 payload 的同 witness 语义绑定”；
   - 二者叠加后，才能回答 reviewer 的关键问题：
   - “上传的 contribution 是否由被证明的 curr_loc 导出”。

#### v1 落地计划（代码级）

1. `common/committee.py`
   - 固化 `canonical_json` 与 `payload_digest` 计算函数，避免多语言/多服务编码歧义。
2. `services/shuffler/app.py`
   - 把 `payload_digest + proof_digest + chain tuple` 纳入 attestation message。
3. `services/aggregator_a/app.py`、`services/aggregator_r/app.py`
   - 增加摘要重算与一致性拒绝路径。
4. `tests/`
   - 新增“proof 合法但 payload 篡改”攻击测试，预期必须拒绝。

#### 文档分层规则（仅保留总文档）

为避免“当前实现 / 目标设计 / 计划实验 / 预期结果”混杂，本文档统一采用三层标记：

- `[CURRENT]`：当前可运行协议与已验证参数（论文主文可引用）
- `[PENDING]`：正在实现或未完成项（仅用于研发计划）
- `[ARCHIVE]`：历史方案、教学示例、预期模板（不可作为主文证据）

若章节未显式标记，以本章“顶会口径收敛 + P0 修订”为最高优先级解释。

#### 电路与接口冻结（Canonical Freeze, 2026-04-01）

为消除“多版电路/多版 public input 并存”风险，主线冻结如下：

1. canonical v1（当前实现）
   - 主电路唯一公开输入：`[hash_prev, hash_curr, max_dist_sq]`
   - 不再将 `[v_max, time_diff]` 作为主线 public input schema
   - 电路内必须包含强约束：`1 === all_checks_pass`

2. verifier 约束
   - 禁止“仅返回 valid 字段但不强制为 1”的实现方式；
   - 若保留 `valid` 输出，必须由电路强制固定为 1（或设为 public 并在 verifier 强校验）。

3. canonical v2（P0 进行中）
   - 在 v1 基础上扩展 `payload_commitment`，形成语义绑定接口；
   - 历史版本接口只保留在 `[ARCHIVE]` 段落，不作为主文证明对象。

---

### 参数对照实验结论（2026-03-14）

为了确认当前部署参数是否应当回退到设计初始值，项目已经完成一组 10 轮对照实验：

- 稳定组：`TSIP_WINDOW_SEC = 60`，`MAX_STEP_M = 110`
- 设计组：`TSIP_WINDOW_SEC = 300`，`MAX_STEP_M = 100`

实验结果如下：

| 指标 | 稳定组 `60/110` | 设计组 `300/100` | 结论 |
|------|----------------|------------------|------|
| `avg_valid_clients` | `180.80` | `177.70` | 稳定组更高 |
| `avg_rejected` | `19.20` | `22.30` | 稳定组更低 |
| `avg_malicious_reject_rate` | `1.0000` | `1.0000` | 两组相同 |
| `avg_false_reject_rate` | `0.0000` | `0.0000` | 两组相同 |
| `avg_cells_final` | `8261.10` | `8189.40` | 稳定组更高 |
| `avg_dp_cells_kept_post` | `985.80` | `911.10` | 稳定组更高 |

据此可以得到当前阶段的工程结论：

- 设计初始参数并不是当前实现下的最优已验证配置
- 当前系统应继续采用 `60s / 110` 作为默认稳定部署参数
- `300s / 100` 保留为设计目标参数和对照实验参数，而不是直接覆盖当前实现

因此，后续文档、部署说明和论文系统实现部分，应将 `TSIP_WINDOW_SEC = 60`、`MAX_STEP_M = 110` 视为“实验验证后的最终工程参数”。

### 对齐修订（2026-03-20）

针对“12ms 延迟口径不可信、需要 Poseidon 复测、需要大规模实验”的三点意见，当前已完成以下修订：

1. 延迟口径修订（替换旧 `12ms`）
   - 旧口径 `12ms` 已作废，不再作为论文结论使用。
   - 端到端实测（容器链路、`snarkjs` 路径）客户端单次可达秒级（约 `2.9s` 量级）。
   - 电路级 prove 基准已补齐 `snarkjs vs rapidsnark` 对照（见下表与 `experiments/zk_benchmark_20260320_200539.csv`）。

2. Poseidon 切换与基准
   - `circuits/tsip_main.circom` 已由 MiMC 切到 Poseidon 约束。
   - 新约束数与证明体积、prove/verify 时间如下（5轮均值）：

| 电路 | Prover | 约束数 | 证明大小 | prove均值 | verify均值 |
|------|--------|--------|----------|-----------|------------|
| `tsip_step` | `snarkjs` | `70` | `805 B` | `1150.932 ms` | `1040.721 ms` |
| `tsip_step` | `rapidsnark` | `70` | `706 B` | `307.652 ms` | `1034.547 ms` |
| `tsip_main_poseidon` | `snarkjs` | `674` | `804 B` | `1388.000 ms` | `1064.044 ms` |
| `tsip_main_poseidon` | `rapidsnark` | `674` | `708 B` | `409.185 ms` | `1033.237 ms` |

   - 结论：在当前环境下，`rapidsnark` 将 prove 延迟从秒级压到 `0.3~0.4s`；verify 仍由 `snarkjs` 执行，约 `1.03s`。
   - 部署说明：`client_sim` 已支持 `ZK_STEP_PROVER/TSIP_PROVER=auto|snarkjs|rapidsnark`，当容器内未安装 `rapidsnark` 时会自动回退 `snarkjs`。

3. 大规模实验已启动
   - 已新增规模实验入口：`script/run_scale_sweep.sh`。
   - 已完成一次 `CLIENT_TOTAL=500` 的实测样例（`experiments/round_metrics_20260320_200853.csv`）：
     - `total=500`
     - `valid_clients=455`
     - `rejected=45`
     - `malicious_reject_rate=1.0`
     - `false_reject_rate=0.0`

当前论文写作口径建议：

- 客户端开销必须使用“秒级 snarkjs / 亚秒级 rapidsnark”的实测值，不得再写固定 `12ms`。
- Poseidon 相关结论必须绑定当前实测约束数（`674`）与 benchmark 文件。
- 大规模实验章节按 `CLIENT_TOTAL` 梯度（如 `200/500/1000`）继续补齐多轮统计。

### 服务器 rapidsnark 验证闭环（2026-03-22）

在远程服务器 `219.218.158.27` 已完成 prover 切换闭环验证，结论是“配置开关生效，rapidsnark 已实际参与证明生成”。

1. 代码版本确认（容器内）
   - `/app/client.py` 已包含 `ZK_STEP_PROVER`、`RAPIDSNARK_BIN`、`_resolve_prover` 相关逻辑。

2. 负向验证（坏路径故障注入）
   - 以 `ZK_STEP_PROVER=rapidsnark` 且 `RAPIDSNARK_BIN=/not/exist` 启动客户端。
   - 客户端按预期在 `ensure_zk_step_ready` 处报错：
     - `RuntimeError: rapidsnark not found: /not/exist`
   - 说明 prover 路由没有被绕过，环境变量切换已真实生效。

3. 正向验证（正式路径）
   - 将 `/tmp/rapidsnark` 注入容器为 `/usr/local/bin/rapidsnark` 后运行：
     - 日志出现 ` [INFO] zk_step prover: rapidsnark`
     - 日志出现 ` [INFO] tsip prover: rapidsnark`
   - 本轮运行结果：
     - `summary total=200`
     - `valid_clients=169`
     - `rejected=31`
     - `malicious_total=27`
     - `malicious_reject_rate=1.0`
     - `false_reject_rate=0.0231`

4. 工程备注
   - `tsip user blacklisted` 属于已启用的黑名单策略触发，不是 prover 切换异常。
   - 只要 `client_sim` 容器被重建（recreate/build），需重新执行一次：
     - `docker compose cp /tmp/rapidsnark client_sim:/usr/local/bin/rapidsnark`

### 承诺链断裂修复记录（2026-03-24）

本轮修复聚焦一个阻断性问题：次轮提交出现 `missing tsip proof` / `tsip prev_loc_commitment mismatch`，导致多轮链路不可信。

1. 根因确认
   - 客户端 `compute_location_commitment` 仍在使用 MiMC 路径；
   - `tsip_main` 电路约束使用 Poseidon；
   - 两者不一致导致次轮 `fullprove` 失败，客户端降级上报 `proof=None`，服务端表现为 `missing tsip proof`。

2. 已完成修复
   - 统一承诺哈希到 Poseidon2 路径（客户端承诺计算与电路一致）。
   - 新增配置：
     - `TSIP_LOC_HASH_MODE=poseidon2`（默认）
     - `TSIP_POSEIDON_WASM=/app/zk/poseidon2_bench/poseidon2_bench_js/poseidon2_bench.wasm`
     - `TSIP_POSEIDON_TIMEOUT_SEC=20`
   - 将 Poseidon helper 工件纳入镜像路径：`zk/poseidon2_bench/poseidon2_bench_js/*`。

3. 调试可观测性补齐
   - 客户端新增 debug 打印（`DEBUG_CLIENT=1`）：
     - `tsip prev_loc before submit`
     - `tsip stored_loc after accept`
   - shuffler 新增 `TSIP_DEBUG=1` 开关，打印：
     - `stored_prev_loc` 与 `received_prev_loc` 对照
     - `verified_curr_loc`

4. 状态错配补丁（重启场景）
   - 发现 `shuffler` 重启后内存清空，而客户端本地 `tsip_state` 仍保留，会触发
     `unexpected previous tsip commitment for first submission`。
   - 已新增自动对齐：若 `shuffler /health` 返回 `tsip_users=0` 且客户端本地状态非空，则客户端自动清空本地 `tsip_state` 并打印提示。

5. 回归结果
   - 同一 `user_id` 连续两轮提交通过：
     - 第 1 轮：`A_ok=True, R_ok=True`
     - 第 2 轮：`A_ok=True, R_ok=True`
   - 日志对齐验证：
     - client `prev_loc` 与 shuffler `stored_prev_loc` 完全一致；
     - shuffler 成功输出 `verified_curr_loc`。
   - `shuffler` 重启后再次提交可自动恢复，不再因本地旧状态导致首轮拒绝。

### GeoLife 冷启动与次轮验证结论（2026-03-16）

在 `CLIENT_TRAJ_SOURCE=geolife`、`GEO_TRAJ_PATH=/app/experiments/geolife_tsip_ready_50u.jsonl` 下，最新两轮实测结果如下：

| 轮次 | `total` | `valid_clients` | `rejected` | `malicious_total` | `malicious_reject_rate` | `false_reject_rate` |
|------|---------|-----------------|------------|-------------------|--------------------------|---------------------|
| 首轮（冷启动） | `50` | `50` | `0` | `3` | `0.0` | `0.0` |
| 次轮（有历史状态） | `50` | `46` | `4` | `4` | `1.0` | `0.0` |

对应服务端结果（次轮）：

- `status_latest`: `received_A = received_R = 46`
- `secure/reconstruct_latest?expected=46`: `ok=true`
- `dp/latest`: `ok=true`，`cells_kept_post=73`

工程解释：

- 首轮冷启动时，部分用户尚未形成可用于时序一致性判定的历史链状态，恶意注入可能出现“首轮放行”现象。
- 从次轮开始，承诺链与窗口连续性生效，恶意样本可稳定被拦截。

当前执行建议（固定流程）：

1. 先跑一轮作为 warm-up（仅建立状态，不用于最终统计）
2. 从第 2 轮开始统计 `malicious_reject_rate`、`false_reject_rate`
3. reconstruct 使用 `expected=min(received_A, received_R)`，避免因有效样本数波动导致误报

### GeoLife 10轮正式统计（2026-03-16，Poseidon2修复前，仅作参考）

> ⚠️ 此结果为 Poseidon2 修复前版本，不作为论文最终引用结果，仅保留用于对比。

在完成 warm-up 后，使用以下配置完成 10 轮正式统计：

- `CLIENT_TRAJ_SOURCE=geolife`
- `GEO_TRAJ_PATH=/app/experiments/geolife_tsip_ready_50u.jsonl`
- `ROUNDS=10`
- `TAU=3, TAU2=3`

批量实验均值结果：

- `avg_valid_clients = 44.60`
- `avg_rejected = 5.40`
- `avg_malicious_total = 5.20`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0043`
- `avg_cells_final = 3492.20`
- `avg_dp_cells_kept_post = 169.50`

对应结果文件：`experiments/round_metrics_20260316_134407.csv`

---

### GeoLife 服务器修复版 10 轮正式统计（2026-03-29）✅ 论文可用

> 此为 Poseidon2 修复后、使用最新代码在服务器上运行的正式结果，作为论文”真实数据可行性”章节的最终引用版本。

配置：

- `CLIENT_TRAJ_SOURCE=geolife`
- `GEO_TRAJ_PATH=/app/experiments/geolife_tsip_ready_50u.jsonl`
- `CLIENT_TOTAL=50`（50 名 GeoLife 用户）
- `ROUNDS=10`，`TAU=3, TAU2=3`
- `TSIP_USER_SCOPE=round`，`MALICIOUS_RATE=0.1`

批量实验均值结果：

| 指标 | 数值 |
|------|------|
| `rounds` | 10 |
| `avg_valid_clients` | 45.10 |
| `avg_rejected` | 4.90 |
| `avg_malicious_total` | 4.40 |
| `avg_malicious_reject_rate` | **1.0000** |
| `avg_false_reject_rate` | **0.0111** |
| `avg_cells_final` | 3545.90 |
| `avg_dp_cells_kept_post` | 219.60 |

结果文件：`experiments/round_metrics_20260329_095735.csv`

**结论（论文可用）**：
- 在该 10 轮 GeoLife 批次中，观测到 `malicious_reject_rate=1.0000`（样本内为 100% 拦截）；
- 正常用户误拒率为 1.11%，在可接受范围内；
- TSIP + DP 全链路在真实轨迹输入下稳定运行，avg_cells_final=3545.90，聚合结果质量良好。

### No-ZK Baseline 对比实验（2026-03-29）✅ 论文可用

> 关闭全部 ZK 验证层（TSIP + zk_step），验证无保护情况下攻击成功通过，作为论文安全性对比基线。

配置：
- `CLIENT_TSIP_ENABLE=0`，`SHUFFLER_TSIP_ENABLE=0`（关闭承诺链验证）
- `CLIENT_ZK_STEP_ENABLE=0`，`SHUFFLER_ZK_STEP_ENABLE=0`（关闭单步 ZK 证明）
- `CLIENT_TOTAL=200`，`MALICIOUS_RATE=0.1`，`ROUNDS=10`

| 指标 | 数值 |
|------|------|
| `rounds` | 10 |
| `avg_valid_clients` | **200.00** |
| `avg_rejected` | **0.00** |
| `avg_malicious_total` | 21.90 |
| `avg_malicious_reject_rate` | **0.0000** |
| `avg_false_reject_rate` | 0.0000 |
| `avg_cells_final` | 8503.30 |
| `avg_dp_cells_kept_post` | 860.70 |

结果文件：`experiments/round_metrics_20260329_171044.csv`

**与完整 TSIP 的对比（论文核心证据）：**

| 配置 | malicious_reject_rate | false_reject_rate | avg_valid_clients |
|------|----------------------|-------------------|-------------------|
| No-ZK Baseline（无保护） | **0.0000** | 0.0000 | 200.00 |
| 完整 TSIP（合成数据，200用户，30轮） | **1.0000** | 0.0017 | ~179 |
| 完整 TSIP（GeoLife，50用户，10轮） | **1.0000** | 0.0111 | 45.10 |

**结论**：在该 No-ZK 对照批次中，恶意样本未被拒绝（`malicious_reject_rate=0.0000`），聚合结果可被污染；对应 TSIP 批次观测到高拦截率与低误拒率。该对比支持“完整性过滤显著降低攻击污染”的主张。

---

### 规模扩展实验（2026-03-29/30）✅ 论文可用

> 在服务器上使用合成轨迹，分别测试 CLIENT_TOTAL=200/500/1000，每档 5 轮，验证 TSIP 的可扩展性。

配置：`CLIENT_TRAJ_SOURCE=synthetic`，`MALICIOUS_RATE=0.1`，`ROUNDS=5`，`TAU=3, TAU2=3`

| 规模 | avg_valid_clients | avg_malicious_reject_rate | avg_false_reject_rate | avg_cells_final | 结果文件 |
|------|------------------|--------------------------|----------------------|-----------------|---------|
| 200  | 180.80 (90.4%)  | **1.0000** | 0.0011 | 9595.60  | `round_metrics_20260329_221428.csv` |
| 500  | 447.60 (89.5%)  | **1.0000** | 0.0004 | 9997.20  | `round_metrics_20260329_233000.csv` |
| 1000 | 902.60 (90.3%)  | **1.0000** | 0.0002 | 10000.00 | `round_metrics_20260330_023605.csv` |

**结论（论文可用）**：
- 在该组规模实验中，`malicious_reject_rate=1.0000` 在三种规模下一致，未观察到随规模退化；
- `false_reject_rate` 随规模增大单调下降（0.0011 → 0.0004 → 0.0002），大规模场景下系统更稳定；
- `avg_cells_final` 随规模增大趋近于域大小上限（10000），说明覆盖率随参与人数提升；
- 系统在 1000 客户端规模下仍保持完整 TSIP 运行，验证了工程可扩展性。

---

### 服务器合成数据10轮统计（2026-03-17）

在远程服务器（CPU-only）使用默认合成轨迹配置完成 10 轮实验，结果如下：

- `rounds = 10`
- `avg_valid_clients = 176.30`
- `avg_rejected = 23.70`
- `avg_malicious_total = 21.80`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0107`
- `avg_cells_final = 8152.90`
- `avg_dp_cells_kept_post = 853.90`

对应结果文件：

- `experiments/round_metrics_20260317_160842.csv`

该组结果可用于论文中的“服务器部署稳定性与防攻击能力”小节，核心结论为：

- 在该批次中观测到恶意样本拦截率为 `1.0000`；
- 误拒率约 `1.07%`，处于可接受区间；
- 在远程服务器环境下，TSIP + DP 聚合链路可稳定完成多轮运行。

### 服务器合成数据复测（2026-03-19 / 2026-03-20）

为验证部署稳定性，已在同一服务器继续完成两组 10 轮复测：

1. 2026-03-19（`experiments/round_metrics_20260319_200123.csv`）
- `avg_valid_clients = 173.20`
- `avg_rejected = 26.80`
- `avg_malicious_total = 20.30`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0362`
- `avg_cells_final = 8106.20`
- `avg_dp_cells_kept_post = 593.30`

2. 2026-03-20（`experiments/round_metrics_20260320_114249.csv`）
- `avg_valid_clients = 180.70`
- `avg_rejected = 19.30`
- `avg_malicious_total = 19.30`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0000`
- `avg_cells_final = 8225.10`
- `avg_dp_cells_kept_post = 847.50`

截至 2026-03-20 的服务器合成数据口径结论：

- 在复测批次中恶意样本拒绝率均观测为 `1.0000`；
- 误拒率在不同轮次存在波动（`0.0% ~ 3.62%`）；
- 系统整体可稳定完成多轮运行并生成可用 DP 聚合输出。

### 服务器修复后正式10轮统计（2026-03-24）

在完成“承诺链断裂修复 + 服务器代码同步 + poseidon helper 工件补齐”后，服务器侧重新进行正式 10 轮统计，结果如下：

- `rounds = 10`
- `avg_valid_clients = 179.00`
- `avg_rejected = 21.00`
- `avg_malicious_total = 20.70`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0017`
- `avg_cells_final = 8204.40`
- `avg_dp_cells_kept_post = 1060.00`

对应结果文件：

- `experiments/round_metrics_20260324_205127.csv`（服务器，正式可用）

同日本机对照结果：

- `experiments/round_metrics_20260324_163745.csv`
- `avg_valid_clients = 179.20`
- `avg_false_reject_rate = 0.0000`

异常批次说明（作废，不用于论文统计）：

- `experiments/round_metrics_20260324_163726.csv`
- `avg_false_reject_rate = 0.9252`
- 该批次发生在服务器未完全同步修复版本时，属于配置/代码不一致导致的失真结果，已明确排除。

截至 2026-03-24 的服务器合成数据最终口径结论：

- 在修复后批次中恶意样本拒绝率观测为 `1.0000`；
- 误拒率已恢复至接近 `0` 的水平（服务器 `0.17%`）；
- TSIP 主链路（承诺链连续性 + zk_step + DP 输出）在远程 CPU-only 环境可稳定多轮运行。

### 服务器合成数据30轮最终统计（2026-03-27）

在 Poseidon2 承诺链修复版本稳定后，服务器侧完成首次正式 30 轮连续统计，结果如下：

- `rounds = 30`
- `avg_valid_clients = 180.63`
- `avg_rejected = 19.37`
- `avg_malicious_total = 19.07`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0017`
- `avg_cells_final = 8232.30`
- `avg_dp_cells_kept_post = 799.67`

对应结果文件：

- `experiments/round_metrics_20260327_092202.csv`（服务器，30 轮，正式可用）

与 2026-03-24 服务器 10 轮结果对比：

| 指标 | 服务器 10 轮（2026-03-24） | 服务器 30 轮（2026-03-27） | 结论 |
|------|--------------------------|--------------------------|------|
| `avg_valid_clients` | `179.00` | `180.63` | 一致，正常波动 |
| `avg_malicious_reject_rate` | `1.0000` | `1.0000` | 完全一致 |
| `avg_false_reject_rate` | `0.0017` | `0.0017` | 完全一致，30 轮无退化 |
| `avg_cells_final` | `8204.40` | `8232.30` | 稳定 |
| `avg_dp_cells_kept_post` | `1060.00` | `799.67` | DP 随机化导致的正常波动 |

截至 2026-03-27 的服务器合成数据口径结论（论文主结果）：

- 这是 Poseidon2 承诺链修复后，服务器侧首次完整的 30 轮正式统计；
- `avg_false_reject_rate = 0.0017` 与 10 轮结果完全一致，说明系统在 30 轮内没有退化；
- 在该 30 轮批次中 `avg_malicious_reject_rate = 1.0000`，防攻击能力未出现可见退化；
- **本组结果（`round_metrics_20260327_092202.csv`）为论文合成数据实验的最终可用主结果。**

### 服务器合成数据10轮复测（2026-03-28）

在 30 轮主结果完成后，再次进行 10 轮合成数据复测，结果如下：

- `rounds = 10`
- `avg_valid_clients = 177.00`
- `avg_rejected = 23.00`
- `avg_malicious_total = 22.70`
- `avg_malicious_reject_rate = 1.0000`
- `avg_false_reject_rate = 0.0017`
- `avg_cells_final = 8172.70`
- `avg_dp_cells_kept_post = 910.80`

对应结果文件：`experiments/round_metrics_20260328_145624.csv`

结论：`false_reject_rate=0.0017` 第三次在服务器侧稳定复现（与 2026-03-24 10 轮、2026-03-27 30 轮完全一致），进一步确认系统稳定性。

### 下一步研发优先级（更新至 2026-04-05）

从工程和论文一致性的角度，后续工作优先级如下：

1. ✅ 参数对照实验（已完成，2026-03-14）
   结论：`TSIP_WINDOW_SEC=60 / MAX_STEP_M=110` 为最终工程参数。

2. ✅ 服务器合成数据 30 轮正式统计（已完成，2026-03-27）
   结论：`false_reject_rate=0.0017`，与 10 轮结果一致，为论文合成数据主结果。

3. ✅ 服务器合成数据 10 轮复测（已完成，2026-03-28）
   结论：`false_reject_rate=0.0017` 第三次稳定复现，系统一致性已充分验证。

4. ✅ 服务器 GeoLife 10 轮修复版（已完成，2026-03-29）
   结论：`avg_valid_clients=45.10`，`malicious_reject_rate=1.0000`，`false_reject_rate=0.0111`，论文真实数据章节可用。

5. ✅ No-ZK Baseline 对比实验（已完成，2026-03-29）
   关闭所有 ZK 验证（TSIP + zk_step）后，观测到 `malicious_reject_rate=0.0000`（该批次恶意样本均未被拒绝）。
   与 TSIP 实验形成完整对比，论文核心证据。
   结果文件：`experiments/round_metrics_20260329_171044.csv`

6. ✅ 攻击强度 boundary sweep（A1 瞬移，7档，已完成，2026-04-01 / 2026-04-05）

   **背景**：之前粗粒度 3 档（200/1000/50000m）均 100% 检测，未揭示检测阈值。本次细粒度围绕 ~6600m 阈值做边界扫描，分 Synthetic 和 T-Drive 两组。

   **配置**：`ATTACK_TYPE=boundary_teleport`，`stable scope`，`warmup_rounds=1`，`TSIP_MAX_GAP_WINDOWS=2`，10 rounds × 50 clients

   **Synthetic 结果（2026-04-01）**：

   | 跳跃距离 | malicious_reject_rate | false_reject_rate | 结果文件 |
   |---------|----------------------|-------------------|---------|
   | 1000m | 1.0000 | 0.0000 | `boundary_1000m.log` |
   | 3300m | 1.0000 | 0.0000 | `boundary_3300m.log` |
   | 5940m | 1.0000 | 0.0000 | `boundary_5940m.log` |
   | 6534m | 1.0000 | 0.0000 | `boundary_6534m.log` |
   | 6600m | 1.0000 | 0.0000 | `boundary_6600m.log` |
   | 6666m | 1.0000 | 0.0000 | `boundary_6666m.log` |
   | 7200m | 1.0000 | 0.0000 | `boundary_7200m.log` |

   > 注：Synthetic 粗粒度实验（`round` scope，no warmup）全部为 1.0，但该结果来自不同检测机制（非 TSIP 距离约束）。

   **Synthetic TSIP-enabled 结果（stable scope，2026-04-01，`synth_boundary_clean_*.log`）**：

   | 跳跃距离 | malicious_reject_rate | false_reject_rate |
   |---------|----------------------|-------------------|
   | 6534m | 0.0000 | 0.0000 |
   | 6600m | 0.0589 | 0.0000 |
   | 6666m | 0.7437 | 0.0000 |
   | 7200m | 0.8264 | 0.0000 |

   > 注：7200m 未达 100% 因城市边界截断 bug（diagonal fallback 被 clamp），T-Drive 无此问题。

   **T-Drive 结果（2026-04-05，`tdrive_boundary_clean_*.log`）**：

   | 跳跃距离 | malicious_reject_rate | false_reject_rate |
   |---------|----------------------|-------------------|
   | 1000m | 0.0000 | 0.0288 |
   | 3300m | 0.0000 | 0.0227 |
   | 5940m | 0.0000 | 0.0427 |
   | 6534m | 0.0000 | 0.0363 |
   | 6600m | 0.0000 | 0.0469 |
   | **6666m** | **1.0000** | 0.0376 |
   | **7200m** | **1.0000** | 0.0406 |

   **关键发现**：
   - 检测阈值约为 6600m（= v_max × actual_time_diff ≈ 80 m/s × 82.5s），阈值以下完全漏检，阈值以上完全检测（T-Drive）
   - T-Drive 存在 ~2-5% 恒定误拒率，原因是真实轨迹中 GPS 中断后补录等合法大跨度移动超出距离约束，体现 security-utility tradeoff
   - S 型检测曲线见 `experiments/tsip_scurve.png`（Synthetic + T-Drive 双线对比）

   **论文可用性**：✅ Security Evaluation 章节，Detection Threshold 子节

7. ✅ A2 身份交换攻击实验（已完成，2026-03-31）
   TSIP_USER_SCOPE=stable，ATTACK_TYPE=identity_swap，10 轮，50 用户。
   avg_valid_clients=45.10，malicious_reject_rate=1.0000，false_reject_rate=0.0000，结果文件 `experiments/round_metrics_20260331_125319.csv`。
   结论：在该 A2 批次中，攻击者冒用相邻用户 ID 的恶意提交均被检测并拒绝。

8. ✅ A5 重放攻击实验（已完成，2026-03-31）
   TSIP_USER_SCOPE=stable，ATTACK_TYPE=replay，10 轮，50 用户。
   avg_valid_clients=45.00，malicious_reject_rate=1.0000，false_reject_rate=0.0000，结果文件 `experiments/round_metrics_20260331_204055.csv`。
   结论：在该 A5 批次中，重放型恶意提交均被检测并拒绝（`malicious_reject_rate=1.0000`）。

9. ✅ T-Drive 数据集实验（已完成，2026-03-30 + boundary sweep 2026-04-05）
   - **主实验（2026-03-30）**：服务器 10 轮，50 用户（taxi），avg_valid_clients=45.00，malicious_reject_rate=1.0000，false_reject_rate=0.0000，avg_cells_final=3600.60，结果文件 `experiments/round_metrics_20260330_125403.csv`
   - **Boundary Sweep（2026-04-05）**：7档距离（1000~7200m），10 rounds × 50 clients，stable scope + warmup=1；阈值（~6600m）以下 0% 检测，以上 100% 检测，false_reject_rate 全程 ~2-5%；完整数据见本文档第 6 条，S 型曲线见 `experiments/tsip_scurve.png`

8. ✅ 规模扩展实验（已完成，2026-03-29/30）
   200/500/1000 各 5 轮；在该批次中 `malicious_reject_rate=1.0000`，`false_reject_rate` 随规模下降（0.0011→0.0004→0.0002），论文可扩展性章节可用。

9. **【论文阻塞项】安全证明文本对齐**
   所有实验完成后，将安全证明章节重写为与当前 Poseidon2 承诺链 + zk_step + 黑名单机制完全一致的描述。

## 第一章: 问题定义与动机

### 1.1 背景：位置隐私保护的挑战

#### 应用场景
```
城市级位置数据聚合:
- 输入: N个用户在T个时间窗口的轨迹
- 输出: 城市热力图 (每个网格的访问次数)
- 要求: 
  1. 服务器无法推断个人位置 (隐私性)
  2. 在连续性作用域内高概率拒绝违规轨迹，并提高恶意污染成本 (完整性)
  3. 高效处理百万级网格 (可扩展性)
```

#### 现有方案的局限

**方案A: 纯差分隐私 (如Nebula)**
```
✅ 优点: 强隐私保证
❌ 缺点: 无法防御恶意用户注入虚假数据
```

**方案B: 物理约束验证 (如RiseFL)**
```
协议流程:
1. 服务器生成随机向量 a ∈ R^d
2. 用户计算内积 z = ⟨trajectory, a⟩
3. 服务器验证 Σz² ≤ B² (卡方检验)

✅ 优点: 能检测单个位置的物理合理性
❌ 关键缺陷: 无法验证时间序列的一致性!
```

---

### 1.2 核心问题：跨时间窗口攻击 (Cross-Window Attack)

#### 攻击场景1: 身份交换攻击

```
场景描述:
- 用户Alice在东京 (t=0时刻)
- 用户Bob在大阪 (t=0时刻)
- 两人串谋,在t=1时刻交换ID

攻击流程:
t=0:
  Alice提交: (东京, ID_Alice) ✅ 通过RiseFL验证
  Bob提交:   (大阪, ID_Bob)   ✅ 通过RiseFL验证

t=1: (身份交换)
  Alice使用ID_Bob提交: (东京附近的位置)
  Bob使用ID_Alice提交:  (大阪附近的位置)
  
  每个位置单独看都合理 ✅
  但Alice的"轨迹"从东京瞬移到大阪! ❌

结果:
- 热力图显示有人从东京快速移动到大阪
- 破坏数据质量,影响城市规划决策
```

#### 攻击场景2: Sybil + 瞬移攻击

```
攻击者策略:
1. 创建1000个虚假ID
2. 在t=0时,所有ID报告分散在城市各处 (通过RiseFL)
3. 在t=1时,所有ID突然"瞬移"到商场A
4. 商场A的热度虚高1000倍!

RiseFL的盲点:
- 只验证"单个时刻"的位置合理性
- 不关心"同一ID的历史轨迹"是否连续
```

#### 为什么现有方案失效?

**RiseFL的验证逻辑**:
```python
def risefl_verify(location, random_vector):
    """
    只关心当前这一个位置向量
    """
    inner_product = dot(location, random_vector)
    return inner_product² <= threshold  # 单点验证
```

**缺失的维度**: **时间维度的连续性**

```
需要验证的约束:
∀ 用户i, ∀ 时刻t:
  distance(location[i][t], location[i][t+1]) ≤ v_max * Δt

但如何在不泄露具体位置的前提下验证这个约束?
→ 这就是TSIP要解决的核心问题!
```

---

### 1.3 研究问题形式化

#### 定义1.1: 时空完整性 (Temporal-Spatial Integrity)

**非正式描述**:
> 一个位置聚合协议满足时空完整性,当且仅当:
> 在给定威胁模型与状态机规则下,恶意用户若提交违反速度/连续性约束的跨时间轨迹,
> 其通过验证概率可忽略 (即使每个时刻的位置单独看是合理的)。

**形式化定义**:

```latex
Definition 1.1 (Temporal-Spatial Integrity):
A location aggregation protocol Π satisfies (λ, ε)-temporal-spatial 
integrity if for any PPT adversary A controlling up to t users:

Pr[
  A submits trajectory {(x₀, t₀), (x₁, t₁), ..., (xₜ, tₜ)} 
  such that ∃i: ||xᵢ₊₁ - xᵢ|| > v_max·(tᵢ₊₁ - tᵢ) 
  AND A is not detected
] ≤ 2^(-λ) + ε

where:
- λ: security parameter (soundness)
- ε: negligible error probability
- v_max: maximum physically possible velocity

scope note:
- 该定义约束的是 trajectory continuity/plausibility,不是真实世界在场真实性(presence/truthfulness)。
- 作用域针对链深度 >= 1 且满足协议状态机约束的用户提交。
```

**关键要求**:
1. **Soundness (完备性)**: 违反约束的轨迹以高概率被拒绝
2. **Zero-Knowledge (零知识性)**: 验证过程不泄露位置信息
3. **Efficiency (高效性)**: 证明大小和验证时间与T(时间窗口数)对数相关

---

### 1.4 设计目标

#### 目标1: 安全性

| 属性 | 定义 | TSIP保证 |
|------|------|----------|
| **完整性** | 恶意轨迹被检测 | Pr[检测] ≥ 1-2^(-128) |
| **隐私性** | 服务器学不到位置 | (ε,δ)-DP, ε=1.0 |
| **零知识性** | 验证不泄露轨迹细节 | 满足ZK定义 |

#### 目标2: 效率

| 指标 | RiseFL (baseline) | TSIP目标 |
|------|-------------------|---------|
| 证明大小 | O(m·d) = 10MB | 当前实测约 `0.70~0.81KB`（proof 文件） |
| 证明生成时间 | O(m·d) = 100ms | 当前实测约 `0.31~1.39s`（rapidsnark/snarkjs） |
| 验证时间 | O(m·d) = 50ms | 当前实测约 `1.03s`（snarkjs verify） |
| 通信量 (per user) | 10MB 级 | 当前实现约 `1KB` 级（含证明与提交元数据） |

#### 目标3: 实用性

- 支持T=288个时间窗口 (每5分钟一个,覆盖24小时)
- 支持d=10^6个网格 (城市级规模)
- 客户端开销（当前实测口径）: prove 为亚秒到秒级，后续需补移动端实测，不再使用 `<100ms` 口径

---

## 第二章: 技术准备

### 2.1 零知识证明基础

#### 什么是零知识证明?

**非正式定义**:
> Alice想向Bob证明"我知道某个秘密",但不想透露秘密本身。
> 零知识证明允许Alice生成一个"证明π",使得:
> 1. Bob验证π通过 → Alice确实知道秘密 (Soundness)
> 2. π本身不泄露任何关于秘密的信息 (Zero-Knowledge)

**经典例子: 阿里巴巴的洞穴**
```
场景: 有一个环形洞穴,中间有一道需要密码才能打开的门

Alice (Prover)        Bob (Verifier)
知道密码              不知道密码

证明协议:
1. Alice进入洞穴,随机选择左边或右边的路
2. Bob在洞穴外等待
3. Bob随机喊: "从左边出来" 或 "从右边出来"
4. 如果Alice真知道密码,她总能满足Bob的要求
   (因为她可以通过门从任意一边出来)
5. 重复100次,如果Alice每次都成功 → Bob确信Alice知道密码
6. 但Bob学不到密码本身!

数学特性:
- Completeness: 如果Alice知道密码,成功概率=100%
- Soundness: 如果Alice不知道密码,成功概率≤(1/2)^100 ≈ 0
- Zero-Knowledge: Bob只知道"Alice知道密码",不知道密码是什么
```

#### zk-SNARKs: 简洁的非交互式零知识证明

**SNARK = Succinct Non-interactive ARgument of Knowledge**

关键特性:
```
1. Succinct (简洁): 
   - 证明大小: O(1) (约200-500 bytes,与语句复杂度无关!)
   - 验证时间: O(1) (实现相关,通常毫秒级到秒级)

2. Non-interactive (非交互):
   - 不需要Prover和Verifier来回通信
   - Prover生成一次性证明π,Verifier直接验证

3. Zero-Knowledge:
   - π不泄露witness (秘密输入)

4. Argument (计算完备性):
   - 可以证明任意NP语句
   - 如: "我知道x使得SHA256(x) = y"
   - 如: "我知道Bitcoin私钥对应这个地址"
```

**工作原理 (高度简化)**:
```
Step 1: 电路化 (Arithmetization)
将要证明的语句转为算术电路 (加法和乘法门)

例: 证明"我知道x使得x² = 9"
电路: 
  输入: x (私密)
  输出: y (公开)
  约束: x * x = y, y = 9

Step 2: Setup (可信设置)
生成proving key (pk) 和 verification key (vk)
⚠️ 需要可信第三方销毁setup过程的随机数

Step 3: Proving
Prover用pk和witness(私密输入)生成证明π

Step 4: Verification
Verifier用vk和公开输入验证π
```

**我们使用的方案: Groth16**
```
特性:
- 证明大小: 仅128 bytes (2个G₁元素 + 1个G₂元素)
- 验证时间: 实现相关（本项目当前 `snarkjs` 实测约 `1.03s`）
- 可信设置: 需要(但可用MPC生成,如Zcash的Powers of Tau)

缺点:
- 电路需要预先固定(不支持通用计算)
- 需要可信设置(虽有解决方案如Plonk,但效率稍低)

在TSIP中的应用:
- 电路: 距离验证 (固定)
- Setup: 一次性完成,所有用户复用
```

---

### 2.2 Groth16协议详解

#### 数学准备：椭圆曲线配对

**椭圆曲线群**:
```
选择曲线: BN254 (Barreto-Naehrig curve)
三个群:
- G₁: 椭圆曲线上的点群 (base field)
- G₂: twist curve上的点群
- Gₜ: target group (pairing的输出)

配对函数 e: G₁ × G₂ → Gₜ
性质: 
  e(aP, bQ) = e(P, Q)^(ab)  (双线性)
  e(P, Q) ≠ 1 (非退化)
```

**为什么需要配对?**
```
目的: 让Verifier能检查多项式关系

例: 证明"我知道a, b, c使得a·b = c"
Naive方案: 直接发送a,b,c → 泄露witness
zk-SNARK方案:
  Setup生成: g^α, g^β ∈ G₁
  Prover计算: A = g^a, B = g^b, C = g^c
  Verifier检查: e(A, B) = e(C, g)
  
  如果a·b=c,则: e(g^a, g^b) = e(g^(ab), g) = e(g^c, g) ✓
  但Verifier学不到a,b,c的具体值!
```

#### Groth16证明系统

**Setup阶段**:
```python
def setup(circuit):
    """
    输入: 算术电路C (包含n个变量, m个约束)
    输出: (proving_key, verification_key)
    """
    # 1. 采样随机数 (toxic waste,必须销毁!)
    α, β, γ, δ, τ = random.sample(5)
    
    # 2. 构造QAP (Quadratic Arithmetic Program)
    #    将电路转为多项式
    L(x) = Σ aᵢ·xⁱ  # left polynomial
    R(x) = Σ bᵢ·xⁱ  # right polynomial
    O(x) = Σ cᵢ·xⁱ  # output polynomial
    Z(x) = (x-1)(x-2)...(x-m)  # vanishing polynomial
    
    # 3. 生成proving key
    pk = {
        [τⁱ·g₁]ᵢ₌₀ⁿ,        # powers of τ
        [α, β, δ, {Lᵢ(τ), Rᵢ(τ), Oᵢ(τ)}]·g₁
    }
    
    # 4. 生成verification key
    vk = {
        α·g₁, β·g₂, γ·g₂, δ·g₂,
        [Lᵢ(τ)·g₁]ᵢ∈public  # 仅公开输入相关
    }
    
    # 5. 销毁 α, β, γ, δ, τ !!
    return pk, vk
```

**Proving阶段**:
```python
def prove(pk, circuit, witness, public_input):
    """
    输入: 
      - pk: proving key
      - witness: 私密输入 (如: 两个位置坐标)
      - public_input: 公开输入 (如: 最大速度v_max)
    输出:
      - proof: (A, B, C) ∈ G₁ × G₂ × G₁
    """
    # 1. 计算多项式
    #    根据witness给每个变量赋值
    a = assign_values(circuit, witness, public_input)
    
    # 2. 构造多项式H(x) = (L(x)·R(x) - O(x)) / Z(x)
    #    关键: 只有满足电路约束时, Z(x)才能整除
    h_coeffs = compute_h_polynomial(a, circuit)
    
    # 3. 计算证明元素
    r, s = random.sample(2)  # 随机盲化因子
    
    A = α·g₁ + Σ aᵢ·Lᵢ(τ)·g₁ + r·δ·g₁
    B = β·g₂ + Σ aᵢ·Rᵢ(τ)·g₂ + s·δ·g₂
    C = Σ aᵢ·Oᵢ(τ)·g₁ + H(τ)·g₁ + s·A + r·B - r·s·δ·g₁
    
    return (A, B, C)
```

**Verification阶段**:
```python
def verify(vk, public_input, proof):
    """
    输入:
      - vk: verification key
      - public_input: 公开输入
      - proof: (A, B, C)
    输出:
      - True/False
    """
    A, B, C = proof
    
    # 构造公开输入部分
    L_pub = Σ public_input[i] · L_i(τ)·g₁
    
    # 配对检查 (核心!)
    check1 = e(A, B) 
    check2 = e(α·g₁, β·g₂) · e(L_pub, γ·g₂) · e(C, δ·g₂)
    
    return check1 == check2
```

**为什么有效?**
```
核心原理: QAP的可满足性

如果witness正确,则:
  L(τ) · R(τ) - O(τ) = H(τ) · Z(τ)

配对等式验证了这个关系:
  e(A, B) 包含了 L(τ)·R(τ) 的信息
  e(C, δ·g₂) 包含了 O(τ) + H(τ)·Z(τ) 的信息
  
通过精心设计的组合,确保:
  只有当 L·R - O = H·Z 时,配对等式才成立
```

**零知识性来源**:
```
随机盲化因子 r, s:
- 即使Verifier看到A, B, C
- 由于r, s的随机性,无法反推witness
- 类似于"加性秘密分享": a + random = ?
```

---

### 2.3 电路设计基础

#### 什么是"电路"?

**从程序到电路的转换**:
```python
# 普通程序
def check_distance(x1, y1, x2, y2, v_max, dt):
    dx = x2 - x1
    dy = y2 - y1
    dist_sq = dx*dx + dy*dy
    max_dist = v_max * dt
    return dist_sq <= max_dist * max_dist

# 转为算术电路
R1CS (Rank-1 Constraint System):
每个约束的形式: (a·b = c)

约束1: dx = x2 - x1
  w_dx · 1 = w_x2 - w_x1
  
约束2: dy = y2 - y1
  w_dy · 1 = w_y2 - w_y1
  
约束3: dist_sq = dx²
  w_dx · w_dx = w_dist_sq
  
约束4: dy_sq = dy²
  w_dy · w_dy = w_dy_sq
  
约束5: dist_sq = dx² + dy²
  w_dist_sq · 1 = w_dx_sq + w_dy_sq
  
...

总约束数: 约15-20个
```

**电路大小与性能**:
```
电路大小 = 约束数量

影响:
- Setup时间: O(约束数) ~= 1秒 per 10K约束
- Proving时间: O(约束数·log(约束数)) ~= 0.1秒 per 10K约束
- 证明大小: O(1) (与约束数无关!) = 128 bytes
- 验证时间: O(公开输入数)（实现相关）

TSIP的距离验证电路:
- 约束数: `70`
- Proving时间: `snarkjs≈1151ms` / `rapidsnark≈308ms`
- 验证时间: `snarkjs≈1035ms`
```

#### Circom语言简介

**Circom**: 专门用于编写zk-SNARK电路的DSL

**基本语法**:
```circom
pragma circom 2.0.0;

// 模板 = 电路组件
template Multiplier() {
    // 信号 = 电路中的变量
    signal input a;
    signal input b;
    signal output c;
    
    // 约束
    c <== a * b;  // <== 表示约束 + 赋值
}

// 主电路
component main = Multiplier();
```

**关键概念**:
```circom
1. signal: 电路中的变量
   - signal input: 输入信号(可以是私密或公开)
   - signal output: 输出信号
   - signal intermediate: 中间变量

2. 约束操作符:
   - <==  : 赋值+约束 (最常用)
   - === : 纯约束 (不赋值)
   - <-- : 纯赋值 (不生成约束,危险!)

3. 组件 (component): 复用电路
   template LessThan(n) { ... }
   component lt = LessThan(32);
   lt.in[0] <== a;
   lt.in[1] <== b;
```

**TSIP距离检查电路 (预览, [ARCHIVE] 教学示例)**:
```circom
template DistanceCheck() {
    // 私密输入: 两个位置
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    signal input t1;
    signal input t2;
    
    // 公开输入: 物理参数
    signal input v_max;
    
    // 输出: 是否合法
    signal output valid;
    
    // 中间信号
    signal dx;
    signal dy;
    signal dist_sq;
    signal time_diff;
    signal max_dist_sq;
    
    // 约束1: 计算位移
    dx <== x2 - x1;
    dy <== y2 - y1;
    
    // 约束2: 距离平方
    dist_sq <== dx*dx + dy*dy;
    
    // 约束3: 时间差
    time_diff <== t2 - t1;
    
    // 约束4: 最大允许距离的平方
    signal max_dist;
    max_dist <== v_max * time_diff;
    max_dist_sq <== max_dist * max_dist;
    
    // 约束5: 距离检查
    component lt = LessThanOrEqual(64);
    lt.in[0] <== dist_sq;
    lt.in[1] <== max_dist_sq;
    
    valid <== lt.out;
}
```

---

### 2.4 将TSIP问题转化为电路

> [ARCHIVE] 本节用于教学解释电路建模思路；
> canonical 接口与约束以“电路与接口冻结（2026-04-01）”与第 5.5 节为准。

#### 问题分解

**TSIP要证明的语句**:
```
公开信息:
- v_max: 最大速度 (如 100 m/s)
- Δt: 时间差 (如 300秒)
- H(loc₁): 上一个位置的哈希 (承诺)

私密信息 (witness):
- (x₁, y₁): 上一个位置的坐标
- (x₂, y₂): 当前位置的坐标

要证明:
1. H(x₁, y₁) = 上传的哈希 (位置一致性)
2. √((x₂-x₁)² + (y₂-y₁)²) ≤ v_max · Δt (物理约束)
```

#### 电路结构设计

```
[主电路: TSIPCircuit]
    ↓
[子电路1: PositionCommitment]
    验证: Hash(x₁,y₁) = H_prev
    ↓
[子电路2: DistanceCheck]
    验证: dist(loc₁, loc₂) ≤ max_dist
    ↓
[子电路3: RangeCheck]
    验证: 坐标在合理范围内
    (防止溢出攻击)
```

**完整电路伪代码**:
```circom
include "poseidon.circom";  // 哈希函数
include "comparators.circom";

template TSIPCircuit() {
    // ===== 输入信号 =====
    // 私密
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    
    // 公开
    signal input hash_prev;  // 上一个位置的承诺
    signal input hash_curr;  // 当前位置的承诺(由电路计算)
    signal input max_dist_sq; // 预计算后的最大允许位移平方
    
    // ===== 输出信号 =====
    signal output valid;
    
    // ===== 子电路1: 验证历史位置 =====
    component hash1 = Poseidon(2);
    hash1.inputs[0] <== x1;
    hash1.inputs[1] <== y1;
    
    // 约束: 必须等于声明的哈希
    hash1.out === hash_prev;
    
    // ===== 子电路2: 计算当前位置哈希 =====
    component hash2 = Poseidon(2);
    hash2.inputs[0] <== x2;
    hash2.inputs[1] <== y2;
    hash2.out === hash_curr;  // 公开输出
    
    // ===== 子电路3: 距离检查 =====
    signal dx;
    signal dy;
    dx <== x2 - x1;
    dy <== y2 - y1;
    
    signal dx_sq;
    signal dy_sq;
    dx_sq <== dx * dx;
    dy_sq <== dy * dy;
    
    signal dist_sq;
    dist_sq <== dx_sq + dy_sq;
    
    // ===== 子电路4: 比较 =====
    component lt = LessThanOrEqual(128);  // 128位比较器
    lt.in[0] <== dist_sq;
    lt.in[1] <== max_dist_sq;
    
    // ===== 子电路5: 范围检查 =====
    // 确保坐标在合理范围 (如: 0 ≤ x ≤ 10^6)
    component range_x1 = RangeCheck(32);
    range_x1.in <== x1;
    
    component range_y1 = RangeCheck(32);
    range_y1.in <== y1;
    
    component range_x2 = RangeCheck(32);
    range_x2.in <== x2;
    
    component range_y2 = RangeCheck(32);
    range_y2.in <== y2;
    
    // ===== 最终输出 =====
    signal all_checks_pass;
    all_checks_pass <== lt.out * range_x1.out * range_y1.out 
                              * range_x2.out * range_y2.out;
    1 === all_checks_pass;   // 关键: 不允许 valid=0 的 witness 被接受
    valid <== 1;
}
```

#### 电路优化技巧

**优化1: 避免平方根**
```
错误写法:
  dist = sqrt(dx² + dy²)
  check: dist ≤ max_dist

问题: 电路中没有高效的平方根运算!

正确写法:
  dist² = dx² + dy²
  check: dist² ≤ max_dist²

好处: 只需乘法,约束数减少50%
```

**优化2: 预计算公开值**
```
错误写法:
  max_dist_sq <== v_max * dt * v_max * dt  (4次乘法)

优化写法:
  在电路外预计算: max_dist_sq_pub = (v_max * dt)²
  作为公开输入传入
  约束: max_dist_sq === max_dist_sq_pub

好处: 约束数减少,proving时间降低
```

**优化3: 批量验证**
```
如果需要验证T个时间窗口:

Naive方案:
  for i in 0..T:
      proof[i] = prove(location[i], location[i+1])
  总proof大小: T * 128 bytes

优化方案 (聚合):
  单个电路验证所有T对位置
  总proof大小: 128 bytes (不变!)
  
实现: 将T对位置作为数组输入到一个大电路
```

---

## 第三章: TSIP协议概览

### 3.1 协议参与方

```
┌─────────────┐
│  Client_i   │ (N个用户)
│  - 轨迹数据  │
│  - proving key
└──────┬──────┘
       │ 上传: (encrypted_location, TSIP_proof)
       ↓
┌─────────────┐
│  Shuffler   │
│  - 验证proof │
│  - 去重/批处理
└──────┬──────┘
       │ 转发: 通过验证的数据
       ↓
┌──────────────────┐
│  Aggregator A/R  │
│  - MPC聚合       │
│  - 不解密位置     │
└──────┬───────────┘
       │ 加密份额
       ↓
┌─────────────┐
│   Decoder   │
│  - 重构热力图 │
│  - 添加DP噪声│
└─────────────┘
```

### 3.2 协议流程 (高层视角)

#### 初始化阶段 (Setup Phase)
```
Step 0: 系统初始化
1. 可信第三方生成 (proving_key, verification_key)
2. proving_key 分发给所有客户端
3. verification_key 存储在Shuffler
4. 客户端初始化: location_history = []
```

#### 第一个时间窗口 (t=0)
```
Client_i:
  1. 采集位置: loc₀ = (x₀, y₀)
  2. 计算承诺: H₀ = Hash(x₀, y₀)
  3. 加密位置: enc_loc₀ = Encrypt(loc₀)
  4. 上传: (enc_loc₀, H₀)
  
  ⚠️ 第一个位置无历史对比:
     - 在 legacy_accept 策略下可直接入链;
     - 在 enroll_only 策略下仅登记锚点,不计入发布轮统计。

Shuffler:
  1. 存储 H₀ 与 user_id 的映射
  2. 转发 enc_loc₀ 到聚合器
```

#### 后续时间窗口 (t≥1)
```
Client_i (时刻t):
  1. 采集新位置: locₜ = (xₜ, yₜ)
  2. 取出历史: locₜ₋₁ = history[-1]
  3. 生成TSIP证明:
     proof = TSIP_Prove(
         witness: (xₜ₋₁, yₜ₋₁, xₜ, yₜ),
         public:  (Hₜ₋₁, Hₜ, max_dist_sq)
     )
  4. 加密新位置: enc_locₜ = Encrypt(xₜ, yₜ)
  5. 计算新承诺: Hₜ = Hash(xₜ, yₜ)
  6. 上传: (enc_locₜ, Hₜ, proof)
  7. 更新历史: history.append(locₜ)

Shuffler (时刻t):
  1. 获取用户i的历史承诺: Hₜ₋₁
  2. 验证TSIP证明:
     valid = TSIP_Verify(
         proof, 
         public_inputs: (Hₜ₋₁, Hₜ, max_dist_sq)
     )
  3. 如果valid:
       - 更新承诺: commitment[user_i] = Hₜ
       - 转发 enc_locₜ 到聚合器
     否则:
       - 拒绝提交
       - 记录恶意行为
```

### 3.3 关键机制

#### 机制1: 位置承诺链 (Location Commitment Chain)

**目的**: 将时间序列的位置"链接"起来,防止身份交换

```
用户A的承诺链:
t=0: H₀ᴬ = Hash(loc₀ᴬ)
t=1: H₁ᴬ = Hash(loc₁ᴬ), prove: loc₁ᴬ与loc₀ᴬ连续
t=2: H₂ᴬ = Hash(loc₂ᴬ), prove: loc₂ᴬ与loc₁ᴬ连续
...

关键属性:
- 服务器只存储哈希H,不知道具体位置
- 但可以验证: "第i个证明对应的loc_i"确实是"第i-1个证明声称的loc_{i-1}的延续"
```

**防御身份交换攻击**:
```
攻击尝试:
t=0: Alice提交H₀ᴬ, Bob提交H₀ᴮ
t=1: Alice想用Bob的ID提交

问题:
- Alice不仅要满足距离约束,还必须同时满足:
  1) hidden user secret 跨轮一致;
  2) epoch/nullifier 未重放;
  3) proof_digest 与 payload_core_digest 绑定一致。
- 仅靠"A不知道B的loc₀"不是主要安全依据。

∴ 攻击失败 ✓
```

#### 机制2: 零知识距离验证

**传统方案的问题**:
```
# RiseFL的验证
def verify_location(loc, random_vector):
    inner_prod = dot(loc, random_vector)
    return check_bound(inner_prod)

缺点: 需要知道loc的明文!
```

**TSIP的解决**:
```
# 零知识验证
def tsip_verify(proof, public_inputs):
    # 不需要知道loc₁或loc₂的明文
    # 只验证密码学证明
    return groth16.verify(proof, public_inputs)

优势:
- 聚合器永远看不到明文位置
- 仍能确保物理约束满足
```

---

### 3.4 安全性直觉

#### 为什么TSIP是安全的?

**完整性 (Soundness)**:
```
假设攻击者想提交违反物理约束的位置:

情况1: 伪造证明
  攻击者构造 fake_proof
  由于Groth16的soundness,
  Pr[fake_proof通过验证] ≤ 2^(-128)

情况2: 复用他人的证明
  攻击者复制Alice的proof
  但proof绑定了Alice的承诺链H_prev^Alice
  攻击者的H_prev不同 → 验证失败

情况3: 身份交换
  攻击者A和B想在t=1交换ID
  A需要prove(loc₁ᴬ, H₀ᴮ)
  仅靠"A不知道B的loc₀"不是充分论证;
  强安全需结合 user-secret 绑定与状态机规则

结论(当前实现口径):
  在定理作用域与系统假设内，违规提交通过概率可忽略；
  不宣称“所有攻击路径无条件被阻断”。
```

**隐私性 (Zero-Knowledge)**:
```
Shuffler和聚合器学到的信息:
1. 承诺哈希: H₀, H₁, H₂, ...
   - 由于哈希的单向性,无法反推位置
2. 证明: π₁, π₂, ...
   - 由于zk-SNARK的零知识性,不泄露witness

额外保护:
- 位置本身用秘密分享加密
- 聚合在MPC中进行
- 最终输出添加DP噪声

结论:
  对公开发布热力图满足 public-output DP；
  内部 accept/reject 与链状态信息作为 internal leakage 单独讨论。
```

---

## 第四章: 与现有方案的对比

### 4.1 功能对比

| 方案 | 验证单点位置 | 验证时序连续性 | 零知识 | DP保证 |
|------|-------------|---------------|--------|--------|
| **Nebula** | ❌ | ❌ | ❌ | ✅ |
| **RiseFL** | ✅ | ❌ | ⚠️ 部分 | ❌ |
| **Clover** | ❌ | ❌ | ✅ | ⚠️ 弱 |
| **TSIP (ours)** | ✅ | ✅ | ✅ | ✅ |

### 4.2 攻击抵抗能力

| 攻击类型 | Nebula | RiseFL | Clover | TSIP |
|---------|--------|--------|--------|------|
| **虚假位置注入** | ❌ | ✅ | ❌ | ✅ |
| **身份交换攻击** | ❌ | ❌ | ❌ | ✅ |
| **Sybil+瞬移** | ❌ | ❌ | ❌ | ✅ |
| **差分攻击** | ✅ | ❌ | ✅ | ✅ |
| **模型反演** | ✅ | ❌ | ⚠️ | ✅ |

### 4.3 效率对比 (理论分析)

| 指标 | Nebula | RiseFL | Clover | TSIP |
|------|--------|--------|--------|------|
| **客户端计算** | O(k) | O(m·d) | O(k log d) | O(k log d) |
| **通信量** | O(k) | O(m·d) | O(k) | O(k + log T) |
| **服务器验证** | O(1) | O(m·d) | O(k) | O(log T) |

**数值示例** (k=50, d=10⁶, m=10, T=288):
```
通信量:
- Nebula: 50 × 4 bytes = 200 bytes
- RiseFL: 10 × 10⁶ × 4 bytes = 40 MB (!!)
- Clover: 50 × 4 bytes = 200 bytes
- TSIP: 200 + log(288) × 128 = 200 + 1KB = 1.2 KB

客户端延迟:
- Nebula: ~1 ms
- RiseFL: ~100 ms
- Clover: ~5 ms
- TSIP: snarkjs约1.15~1.39s；rapidsnark约0.31~0.41s（当前实测）
```

---

## 小结

本部分建立了TSIP的理论基础:
1. ✅ 形式化了"时空完整性"问题
2. ✅ 介绍了零知识证明和Groth16
3. ✅ 设计了距离验证电路
4. ✅ 给出了协议的高层流程

**下一部分**: 详细协议设计与完整实现代码

---

## 参考文献

[1] Groth, J. (2016). On the Size of Pairing-based Non-interactive Arguments. EUROCRYPT.

[2] Ben-Sasson, E., et al. (2014). Succinct Non-Interactive Zero Knowledge for a von Neumann Architecture. USENIX Security.

[3] RiseFL: Secure Aggregation for Federated Learning. NDSS 2024.

[4] Clover: Efficient Sparse Aggregation. USENIX Security 2023.

[5] Nebula: Differentially Private Histograms. SIGMOD 2022

## 第五章: 详细协议规范 [CURRENT]

### 5.1 系统参数

#### 全局参数配置

```python
# config/tsip_params.py

class TSIPParameters:
    """TSIP系统参数配置"""
    
    # ===== 隐私参数 =====
    EPSILON_TOTAL = 1.0          # 总隐私预算
    EPSILON_SVT = 0.3            # 稀疏向量技术预算
    EPSILON_VALUE = 0.7          # 值噪声预算
    EPSILON_VERIFY_EXPERIMENT = 0.2  # 仅用于可选随机化验证实验，不计入主口径
    DELTA = 1e-8                 # DP参数δ
    
    # ===== 物理约束参数 =====
    V_MAX = 110.0                # 当前实现默认最大速度 (m/s)
    TIME_WINDOW = 60             # 当前实现默认时间窗口 (秒)
    MAX_DISTANCE = V_MAX * TIME_WINDOW  # = 6,600 m
    
    # ===== 地理空间参数 =====
    GRID_SIZE = 100              # 网格大小 (米)
    GRID_WIDTH = 100             # 当前实现网格宽度数量
    GRID_HEIGHT = 100            # 当前实现网格高度数量
    DOMAIN_SIZE = GRID_WIDTH * GRID_HEIGHT  # = 10^4 个网格
    
    # 坐标范围 (假设东京市区)
    LAT_MIN = 35.5               # 最小纬度
    LAT_MAX = 35.8               # 最大纬度
    LON_MIN = 139.5              # 最小经度
    LON_MAX = 139.9              # 最大经度
    
    # 投影后的坐标范围 (米)
    X_MIN = 0
    X_MAX = GRID_WIDTH * GRID_SIZE   # = 1,000,000 m = 1000 km
    Y_MIN = 0
    Y_MAX = GRID_HEIGHT * GRID_SIZE  # = 1,000,000 m = 1000 km
    
    # ===== 零知识证明参数 =====
    CURVE = "bn254"              # 椭圆曲线
    HASH_FUNCTION = "poseidon"   # 承诺哈希函数
    SECURITY_PARAM = 128         # 安全参数 (bits)
    
    # ===== 稀疏化参数 =====
    TOP_K = 50                   # 每个用户保留的Top-K位置
    QUANTIZATION_BITS = 4        # 停留时间量化位数
    
    # ===== 系统参数 =====
    NUM_TIME_WINDOWS = 1440      # 24小时,每60秒一个窗口
    BATCH_SIZE = 100             # 聚合批次大小
    BATCH_TIMEOUT = 30           # 批次超时 (秒)
    
    # ===== 恶意行为检测 =====
    MAX_REJECTION_RATE = 0.05    # 最大允许拒绝率 (5%)
    BLACKLIST_THRESHOLD = 3      # 连续拒绝次数阈值
```

---

### 5.2 数据结构定义

#### 位置数据结构

```python
# tsip/types.py

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np

@dataclass
class Location:
    """单个位置点"""
    x: float              # 投影后的x坐标 (米)
    y: float              # 投影后的y坐标 (米)
    timestamp: int        # Unix时间戳 (秒)
    cell_id: int          # 网格ID
    dwell_time: float     # 停留时间 (秒)
    
    def to_array(self) -> np.ndarray:
        """转为numpy数组 (用于电路输入)"""
        return np.array([self.x, self.y, self.timestamp], dtype=np.int64)
    
    @staticmethod
    def from_latlon(lat: float, lon: float, timestamp: int) -> 'Location':
        """从经纬度创建位置"""
        x, y = latlon_to_xy(lat, lon)
        cell_id = xy_to_cell_id(x, y)
        return Location(x, y, timestamp, cell_id, 0.0)


@dataclass
class Trajectory:
    """用户轨迹"""
    user_id: str
    locations: List[Location]
    
    def get_sparse_vector(self) -> Tuple[np.ndarray, np.ndarray]:
        """转为稀疏向量表示"""
        # 聚合停留时间
        cell_visits = {}
        for loc in self.locations:
            if loc.cell_id not in cell_visits:
                cell_visits[loc.cell_id] = 0
            cell_visits[loc.cell_id] += loc.dwell_time
        
        # Top-K筛选
        sorted_cells = sorted(
            cell_visits.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:TSIPParameters.TOP_K]
        
        indices = np.array([c[0] for c in sorted_cells], dtype=np.int32)
        values = np.array([c[1] for c in sorted_cells], dtype=np.float32)
        
        return indices, values


@dataclass
class LocationCommitment:
    """位置承诺"""
    hash: bytes           # Hash(x, y) - 32 bytes
    timestamp: int        # 时间戳
    window_id: int        # 时间窗口ID
    
    def verify(self, location: Location) -> bool:
        """验证位置是否匹配承诺"""
        computed_hash = poseidon_hash(location.x, location.y)
        return computed_hash == self.hash


@dataclass
class TSIPProof:
    """TSIP零知识证明"""
    proof_a: bytes        # Groth16证明的A部分 (G1点, 32 bytes)
    proof_b: bytes        # Groth16证明的B部分 (G2点, 64 bytes)
    proof_c: bytes        # Groth16证明的C部分 (G1点, 32 bytes)
    
    # 公开输入
    prev_commitment: bytes   # 前一个位置的承诺
    curr_commitment: bytes   # 当前位置的承诺
    v_max: float             # 最大速度
    time_diff: int           # 时间差
    
    def to_bytes(self) -> bytes:
        """序列化为字节"""
        return self.proof_a + self.proof_b + self.proof_c
    
    @staticmethod
    def from_bytes(data: bytes, public_inputs: dict) -> 'TSIPProof':
        """从字节反序列化"""
        return TSIPProof(
            proof_a=data[:32],
            proof_b=data[32:96],
            proof_c=data[96:128],
            **public_inputs
        )
    
    def size(self) -> int:
        """证明大小 (字节)"""
        return 128  # Groth16固定大小


@dataclass
class EncryptedLocation:
    """加密的位置数据"""
    ciphertext: bytes        # 加密的(x, y, timestamp)
    shares_a: bytes          # 给聚合器A的秘密份额
    shares_r: bytes          # 给聚合器R的秘密份额
    nonce: bytes             # 加密nonce
    
    def decrypt(self, key_a: bytes, key_r: bytes) -> Location:
        """解密位置 (需要两个密钥)"""
        # 重构秘密
        combined_key = xor_bytes(key_a, key_r)
        plaintext = aes_decrypt(self.ciphertext, combined_key, self.nonce)
        
        x, y, t = decode_location(plaintext)
        return Location(x, y, t, xy_to_cell_id(x, y), 0.0)
```

---

### 5.3 客户端协议实现

#### 5.3.1 TSIP客户端完整实现

```python
# tsip/client.py

import time
import hashlib
from typing import Optional, List
from snarkjs import groth16_prove, groth16_verify  # zk-SNARK库

class TSIPClient:
    """TSIP客户端实现"""
    
    def __init__(self, user_id: str, proving_key_path: str):
        """
        初始化客户端
        
        Args:
            user_id: 用户唯一标识
            proving_key_path: Groth16 proving key文件路径
        """
        self.user_id = user_id
        self.proving_key = self.load_proving_key(proving_key_path)
        
        # 历史位置链
        self.location_history: List[Location] = []
        self.commitment_history: List[LocationCommitment] = []
        
        # 统计信息
        self.stats = {
            "total_submissions": 0,
            "accepted": 0,
            "rejected": 0,
            "avg_proof_time": 0.0
        }
    
    def load_proving_key(self, path: str):
        """加载proving key"""
        with open(path, 'rb') as f:
            return f.read()
    
    def submit_location(self, 
                       lat: float, 
                       lon: float, 
                       timestamp: int,
                       shuffler_url: str) -> bool:
        """
        提交位置到服务器
        
        Args:
            lat: 纬度
            lon: 经度
            timestamp: 时间戳
            shuffler_url: Shuffler服务器地址
            
        Returns:
            是否提交成功
        """
        # 1. 创建位置对象
        location = Location.from_latlon(lat, lon, timestamp)
        
        # 2. 计算位置承诺
        commitment = self.compute_commitment(location)
        
        # 3. 判断是否需要生成TSIP证明
        if len(self.location_history) == 0:
            # 第一次提交,无需证明
            proof = None
        else:
            # 生成TSIP证明
            prev_location = self.location_history[-1]
            prev_commitment = self.commitment_history[-1]
            
            start_time = time.time()
            proof = self.generate_tsip_proof(
                prev_location, 
                location, 
                prev_commitment
            )
            proof_time = time.time() - start_time
            
            # 更新统计
            self.stats["avg_proof_time"] = (
                self.stats["avg_proof_time"] * self.stats["total_submissions"]
                + proof_time
            ) / (self.stats["total_submissions"] + 1)
        
        # 4. 加密位置
        encrypted_loc = self.encrypt_location(location)
        
        # 5. 构造上传消息
        message = {
            "user_id": self.user_id,
            "encrypted_location": encrypted_loc.to_dict(),
            "commitment": commitment.hash.hex(),
            "timestamp": timestamp,
            "window_id": self.get_window_id(timestamp),
            "proof": proof.to_dict() if proof else None
        }
        
        # 6. 发送到Shuffler
        response = self.send_to_shuffler(shuffler_url, message)
        
        # 7. 处理响应
        if response["status"] == "accepted":
            # 更新历史
            self.location_history.append(location)
            self.commitment_history.append(commitment)
            self.stats["accepted"] += 1
            self.stats["total_submissions"] += 1
            return True
        else:
            # 拒绝
            self.stats["rejected"] += 1
            self.stats["total_submissions"] += 1
            print(f"❌ Submission rejected: {response['reason']}")
            return False
    
    def compute_commitment(self, location: Location) -> LocationCommitment:
        """
        计算位置承诺
        
        使用Poseidon哈希: H = Poseidon(x, y)
        """
        hash_value = poseidon_hash(
            int(location.x), 
            int(location.y)
        )
        
        return LocationCommitment(
            hash=hash_value,
            timestamp=location.timestamp,
            window_id=self.get_window_id(location.timestamp)
        )
    
    def generate_tsip_proof(self,
                           prev_location: Location,
                           curr_location: Location,
                           prev_commitment: LocationCommitment) -> TSIPProof:
        """
        生成TSIP零知识证明
        
        证明语句:
        1. prev_commitment = Hash(prev_location)
        2. distance(prev_location, curr_location) ≤ v_max * Δt
        """
        # 准备witness (私密输入)
        witness = {
            "x1": int(prev_location.x),
            "y1": int(prev_location.y),
            "t1": prev_location.timestamp,
            "x2": int(curr_location.x),
            "y2": int(curr_location.y),
            "t2": curr_location.timestamp
        }
        
        # 准备公开输入
        time_diff = curr_location.timestamp - prev_location.timestamp
        curr_commitment = self.compute_commitment(curr_location)
        
        public_inputs = {
            "hash_prev": bytes_to_field_element(prev_commitment.hash),
            "hash_curr": bytes_to_field_element(curr_commitment.hash),
            "v_max": int(TSIPParameters.V_MAX),
            "time_diff": time_diff
        }
        
        # 调用Groth16证明生成
        proof_data = groth16_prove(
            circuit="tsip_circuit.wasm",
            proving_key=self.proving_key,
            witness=witness,
            public_inputs=public_inputs
        )
        
        # 构造证明对象
        return TSIPProof(
            proof_a=proof_data["pi_a"],
            proof_b=proof_data["pi_b"],
            proof_c=proof_data["pi_c"],
            prev_commitment=prev_commitment.hash,
            curr_commitment=curr_commitment.hash,
            v_max=TSIPParameters.V_MAX,
            time_diff=time_diff
        )
    
    def encrypt_location(self, location: Location) -> EncryptedLocation:
        """
        加密位置数据 (使用秘密分享)
        
        将位置(x, y)分成两个份额:
        - share_A 给聚合器A
        - share_R 给聚合器R
        满足: x = share_A + share_R (mod p)
        """
        # 生成随机份额
        import secrets
        prime = 2**31 - 1  # 梅森素数
        
        x_share_a = secrets.randbelow(prime)
        x_share_r = (int(location.x) - x_share_a) % prime
        
        y_share_a = secrets.randbelow(prime)
        y_share_r = (int(location.y) - y_share_a) % prime
        
        # 打包份额
        shares_a = encode_shares(x_share_a, y_share_a)
        shares_r = encode_shares(x_share_r, y_share_r)
        
        # 生成ciphertext (用于完整性校验)
        nonce = secrets.token_bytes(12)
        ciphertext = aes_encrypt(
            data=encode_location(location),
            key=hashlib.sha256(shares_a + shares_r).digest(),
            nonce=nonce
        )
        
        return EncryptedLocation(
            ciphertext=ciphertext,
            shares_a=shares_a,
            shares_r=shares_r,
            nonce=nonce
        )
    
    def get_window_id(self, timestamp: int) -> int:
        """计算时间窗口ID"""
        return timestamp // TSIPParameters.TIME_WINDOW
    
    def send_to_shuffler(self, url: str, message: dict) -> dict:
        """发送消息到Shuffler"""
        import requests
        try:
            response = requests.post(
                f"{url}/tsip/submit",
                json=message,
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def get_statistics(self) -> dict:
        """获取客户端统计信息"""
        total = self.stats["total_submissions"]
        if total == 0:
            return self.stats
        
        return {
            **self.stats,
            "acceptance_rate": self.stats["accepted"] / total,
            "rejection_rate": self.stats["rejected"] / total
        }
```

---

#### 5.3.2 电路接口实现

```python
# tsip/circuit_interface.py

import subprocess
import json
import os

class CircuitInterface:
    """与circom编译的电路交互的接口"""
    
    def __init__(self, wasm_path: str, zkey_path: str):
        """
        初始化电路接口
        
        Args:
            wasm_path: 编译后的wasm文件路径
            zkey_path: proving key文件路径
        """
        self.wasm_path = wasm_path
        self.zkey_path = zkey_path
    
    def generate_witness(self, inputs: dict) -> str:
        """
        生成witness
        
        Args:
            inputs: 电路输入 (私密+公开)
            
        Returns:
            witness.wtns文件路径
        """
        # 写入input.json
        input_file = "/tmp/input.json"
        with open(input_file, 'w') as f:
            json.dump(inputs, f)
        
        # 调用snarkjs生成witness
        witness_file = "/tmp/witness.wtns"
        cmd = [
            "snarkjs", "wtns", "calculate",
            self.wasm_path,
            input_file,
            witness_file
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return witness_file
    
    def prove(self, witness_file: str) -> dict:
        """
        生成Groth16证明
        
        Args:
            witness_file: witness文件路径
            
        Returns:
            证明数据 {proof, publicSignals}
        """
        proof_file = "/tmp/proof.json"
        public_file = "/tmp/public.json"
        
        cmd = [
            "snarkjs", "groth16", "prove",
            self.zkey_path,
            witness_file,
            proof_file,
            public_file
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # 读取证明
        with open(proof_file, 'r') as f:
            proof = json.load(f)
        with open(public_file, 'r') as f:
            public_signals = json.load(f)
        
        return {
            "proof": proof,
            "publicSignals": public_signals
        }
    
    @staticmethod
    def verify(vkey_path: str, 
              proof: dict, 
              public_signals: list) -> bool:
        """
        验证Groth16证明
        
        Args:
            vkey_path: verification key路径
            proof: 证明数据
            public_signals: 公开信号
            
        Returns:
            验证是否通过
        """
        # 写入临时文件
        proof_file = "/tmp/verify_proof.json"
        public_file = "/tmp/verify_public.json"
        
        with open(proof_file, 'w') as f:
            json.dump(proof, f)
        with open(public_file, 'w') as f:
            json.dump(public_signals, f)
        
        # 调用snarkjs验证
        cmd = [
            "snarkjs", "groth16", "verify",
            vkey_path,
            public_file,
            proof_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "OK" in result.stdout
```

---

### 5.4 服务器端协议实现

#### 5.4.1 Shuffler实现 (TSIP验证器)

```python
# tsip/shuffler.py

from flask import Flask, request, jsonify
from typing import Dict, Optional
import time

app = Flask(__name__)

class TSIPShuffler:
    """
    Shuffler服务器: 负责验证TSIP证明
    """
    
    def __init__(self, vkey_path: str):
        """
        初始化Shuffler
        
        Args:
            vkey_path: Groth16 verification key路径
        """
        self.vkey_path = vkey_path
        
        # 用户状态跟踪
        self.user_commitments: Dict[str, LocationCommitment] = {}
        self.user_submissions: Dict[str, int] = {}  # 提交次数
        self.user_rejections: Dict[str, int] = {}   # 拒绝次数
        
        # 黑名单
        self.blacklist = set()
        
        # 统计
        self.stats = {
            "total_submissions": 0,
            "accepted": 0,
            "rejected": 0,
            "rejection_reasons": {}
        }
    
    @app.route('/tsip/submit', methods=['POST'])
    def handle_submission(self):
        """处理客户端提交"""
        data = request.json
        user_id = data["user_id"]
        
        # 检查黑名单
        if user_id in self.blacklist:
            return jsonify({
                "status": "rejected",
                "reason": "blacklisted"
            }), 403
        
        # 更新统计
        self.stats["total_submissions"] += 1
        self.user_submissions[user_id] = self.user_submissions.get(user_id, 0) + 1
        
        # 验证提交
        validation_result = self.validate_submission(data)
        
        if validation_result["valid"]:
            # 接受
            self.on_accepted(user_id, data)
            return jsonify({
                "status": "accepted",
                "message": "Submission verified"
            })
        else:
            # 拒绝
            self.on_rejected(user_id, validation_result["reason"])
            return jsonify({
                "status": "rejected",
                "reason": validation_result["reason"]
            }), 400
    
    def validate_submission(self, data: dict) -> dict:
        """
        验证提交数据
        
        Returns:
            {"valid": bool, "reason": str}
        """
        user_id = data["user_id"]
        
        # 第一次提交: 无需TSIP证明
        if user_id not in self.user_commitments:
            return {"valid": True, "reason": ""}
        
        # 后续提交: 验证TSIP证明
        if "proof" not in data or data["proof"] is None:
            return {"valid": False, "reason": "missing_proof"}
        
        proof_data = data["proof"]
        
        # 1. 检查时间窗口合理性
        prev_commitment = self.user_commitments[user_id]
        time_diff = data["timestamp"] - prev_commitment.timestamp
        
        if time_diff < 0:
            return {"valid": False, "reason": "time_reversal"}
        
        if time_diff > 2 * TSIPParameters.TIME_WINDOW:
            return {"valid": False, "reason": "time_gap_too_large"}
        
        # 2. 验证Groth16证明
        public_inputs = [
            proof_data["prev_commitment"],
            proof_data["curr_commitment"],
            proof_data["v_max"],
            proof_data["time_diff"]
        ]
        
        proof_verified = CircuitInterface.verify(
            vkey_path=self.vkey_path,
            proof=proof_data["proof"],
            public_signals=public_inputs
        )
        
        if not proof_verified:
            return {"valid": False, "reason": "invalid_tsip_proof"}
        
        # 3. 验证承诺链连续性
        if proof_data["prev_commitment"] != prev_commitment.hash.hex():
            return {"valid": False, "reason": "commitment_mismatch"}
        
        return {"valid": True, "reason": ""}
    
    def on_accepted(self, user_id: str, data: dict):
        """处理接受的提交"""
        # 更新承诺历史
        commitment = LocationCommitment(
            hash=bytes.fromhex(data["commitment"]),
            timestamp=data["timestamp"],
            window_id=data["window_id"]
        )
        self.user_commitments[user_id] = commitment
        
        # 转发到聚合器
        self.forward_to_aggregators(data)
        
        # 更新统计
        self.stats["accepted"] += 1
    
    def on_rejected(self, user_id: str, reason: str):
        """处理拒绝的提交"""
        # 更新拒绝计数
        self.user_rejections[user_id] = self.user_rejections.get(user_id, 0) + 1
        
        # 检查是否应加入黑名单
        if self.user_rejections[user_id] >= TSIPParameters.BLACKLIST_THRESHOLD:
            self.blacklist.add(user_id)
            print(f"⚠️  User {user_id} blacklisted (rejections: {self.user_rejections[user_id]})")
        
        # 更新统计
        self.stats["rejected"] += 1
        if reason not in self.stats["rejection_reasons"]:
            self.stats["rejection_reasons"][reason] = 0
        self.stats["rejection_reasons"][reason] += 1
    
    def forward_to_aggregators(self, data: dict):
        """转发验证通过的数据到聚合器"""
        import requests
        
        # 提取秘密份额
        encrypted_loc = data["encrypted_location"]
        
        # 发送到聚合器A
        try:
            requests.post(
                "http://aggregator-a:5001/ingestA",
                json={
                    "user_id": data["user_id"],
                    "shares": encrypted_loc["shares_a"],
                    "window_id": data["window_id"]
                },
                timeout=5
            )
        except Exception as e:
            print(f"❌ Failed to forward to Aggregator A: {e}")
        
        # 发送到聚合器R
        try:
            requests.post(
                "http://aggregator-r:5002/ingestR",
                json={
                    "user_id": data["user_id"],
                    "shares": encrypted_loc["shares_r"],
                    "window_id": data["window_id"]
                },
                timeout=5
            )
        except Exception as e:
            print(f"❌ Failed to forward to Aggregator R: {e}")
    
    @app.route('/tsip/stats', methods=['GET'])
    def get_stats(self):
        """获取统计信息"""
        total = self.stats["total_submissions"]
        if total == 0:
            return jsonify(self.stats)
        
        return jsonify({
            **self.stats,
            "acceptance_rate": self.stats["accepted"] / total,
            "rejection_rate": self.stats["rejected"] / total,
            "num_blacklisted": len(self.blacklist)
        })

# 启动服务器
if __name__ == '__main__':
    shuffler = TSIPShuffler(vkey_path="/keys/verification_key.json")
    app.run(host='0.0.0.0', port=5000)
```

#### 当前实现对齐说明（黑名单机制）

上面的代码块描述的是设计上的理想化 Shuffler 逻辑。当前仓库中的真实实现位于 [app.py](/Users/wanghao/Desktop/risefl_mvp/services/shuffler/app.py)，其黑名单机制已经落地，并采用以下工程规则：

- 连续拒绝按 `user_id` 计数
- 同一个 `submission_id` 即使在 `A/R` 双通道都失败，也只计一次拒绝
- 当拒绝次数达到 `TSIP_BLACKLIST_THRESHOLD` 时，后续提交直接返回 `403`
- 一旦某用户完成一次成功提交，其连续拒绝计数会清零
- `/health` 会暴露 `tsip_blacklisted_users` 与 `tsip_blacklist_threshold`，用于部署观测

当前实现与设计稿的差异主要有两点：

- 真实系统的拒绝计数是基于“提交验证失败”统一累积，而不是只针对某一个 TSIP 子错误码
- 当前黑名单仍是内存态策略，服务重启后不会持久化保留

#### 当前验收结果（远程服务器）

远程服务器已经完成黑名单机制验收，观测结果如下：

- 初始状态：`tsip_blacklisted_users = 0`
- 同一测试用户连续提交 3 次非法请求后，前 3 次返回 `400`
- 第 4 次返回 `403`，错误为 `tsip user blacklisted`
- 验收后 `/health` 显示：`tsip_blacklisted_users = 1`

因此，本项目当前可以将“黑名单与连续拒绝惩罚”标记为：

- 已完成基础实现
- 已完成远程部署
- 已完成功能验收

后续如果需要继续增强，应扩展为：

- 持久化黑名单
- 人工解除或超时解除策略
- 按错误类型细分计数
- 跨轮审计与告警

---

#### 5.4.2 聚合器修改 (支持TSIP)

```python
# tsip/aggregator_tsip.py

# 在原有aggregator基础上添加TSIP支持

class TSIPAggregator:
    """支持TSIP的聚合器"""
    
    def __init__(self):
        # 原有字段
        self.bufferA = {}
        self.stats = {}
        
        # TSIP扩展: 记录每个窗口的有效提交
        self.valid_submissions_per_window = {}
    
    @app.route('/ingestA', methods=['POST'])
    def ingest_a(self):
        """接收来自Shuffler的验证通过的份额"""
        data = request.json
        user_id = data["user_id"]
        window_id = data["window_id"]
        shares = data["shares"]
        
        # 解析份额
        x_share, y_share = decode_shares(shares)
        
        # 存储
        if window_id not in self.bufferA:
            self.bufferA[window_id] = {}
            self.valid_submissions_per_window[window_id] = 0
        
        self.bufferA[window_id][user_id] = {
            "x_share": x_share,
            "y_share": y_share
        }
        
        self.valid_submissions_per_window[window_id] += 1
        
        # 检查是否达到批次大小
        if len(self.bufferA[window_id]) >= TSIPParameters.BATCH_SIZE:
            self.flush_window(window_id)
        
        return jsonify({"status": "ok"})
    
    @app.route('/tsip/window_stats/<int:window_id>', methods=['GET'])
    def get_window_stats(self, window_id: int):
        """获取指定窗口的统计"""
        return jsonify({
            "window_id": window_id,
            "valid_submissions": self.valid_submissions_per_window.get(window_id, 0),
            "buffered": len(self.bufferA.get(window_id, {}))
        })
```

---

### 5.5 电路完整实现

#### 5.5.1 TSIP主电路

```circom
// circuits/tsip_main.circom

pragma circom 2.1.0;

include "node_modules/circomlib/circuits/poseidon.circom";
include "node_modules/circomlib/circuits/comparators.circom";

/*
 * TSIP主电路: 验证时空完整性
 * 
 * 公开输入:
 *   - hash_prev: 前一个位置的哈希
 *   - hash_curr: 当前位置的哈希 (由电路计算)
 *   - max_dist_sq: 最大距离平方 (预计算)
 * 
 * canonical v1:
 *   public = [hash_prev, hash_curr, max_dist_sq]
 * 
 * v2(P0待落地):
 *   public = [hash_prev, hash_curr, max_dist_sq, payload_commitment]
 * 
 * 私密输入:
 *   - x1, y1: 前一个位置坐标
 *   - x2, y2: 当前位置坐标
 * 
 * 输出:
 *   - valid: 是否通过验证
 */
template TSIPCircuit() {
    // ===== 信号声明 =====
    
    // 私密输入
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    
    // 公开输入
    signal input hash_prev;
    signal input hash_curr;
    signal input max_dist_sq;
    
    // 输出
    signal output valid;
    
    // ===== 子电路1: 验证前一个位置的哈希 =====
    component hasher1 = Poseidon(2);
    hasher1.inputs[0] <== x1;
    hasher1.inputs[1] <== y1;
    
    // 约束: 计算的哈希必须等于声明的哈希
    hasher1.out === hash_prev;
    
    // ===== 子电路2: 计算当前位置的哈希 =====
    component hasher2 = Poseidon(2);
    hasher2.inputs[0] <== x2;
    hasher2.inputs[1] <== y2;
    
    // 约束: 计算的哈希必须等于公开的哈希
    hasher2.out === hash_curr;
    
    // ===== 子电路3: 计算距离平方 =====
    signal dx;
    signal dy;
    dx <== x2 - x1;
    dy <== y2 - y1;
    
    signal dx_sq;
    signal dy_sq;
    dx_sq <== dx * dx;
    dy_sq <== dy * dy;
    
    signal dist_sq;
    dist_sq <== dx_sq + dy_sq;
    
    // ===== 子电路4: 距离检查 =====
    // 检查: dist_sq ≤ max_dist_sq
    component less_than = LessThan(64);  // 64位比较
    less_than.in[0] <== dist_sq;
    less_than.in[1] <== max_dist_sq + 1;  // +1 to make it ≤
    
    // ===== 子电路5: 坐标范围检查 =====
    // 防止整数溢出攻击
    signal x1_valid;
    signal y1_valid;
    signal x2_valid;
    signal y2_valid;
    
    component range_x1 = LessThan(32);
    range_x1.in[0] <== x1;
    range_x1.in[1] <== 1000000;  // X_MAX
    x1_valid <== range_x1.out;
    
    component range_y1 = LessThan(32);
    range_y1.in[0] <== y1;
    range_y1.in[1] <== 1000000;  // Y_MAX
    y1_valid <== range_y1.out;
    
    component range_x2 = LessThan(32);
    range_x2.in[0] <== x2;
    range_x2.in[1] <== 1000000;
    x2_valid <== range_x2.out;
    
    component range_y2 = LessThan(32);
    range_y2.in[0] <== y2;
    range_y2.in[1] <== 1000000;
    y2_valid <== range_y2.out;
    
    // ===== 最终输出 =====
    // 所有检查都必须通过（禁止 valid=0 通过约束）
    signal all_range_valid;
    all_range_valid <== x1_valid * y1_valid * x2_valid * y2_valid;
    signal all_checks_pass;
    all_checks_pass <== less_than.out * all_range_valid;
    1 === all_checks_pass;
    valid <== 1;
}

component main {public [hash_prev, hash_curr, max_dist_sq]} = TSIPCircuit();
```

> 接口冻结说明（2026-04-01）：
> - 主线只保留上述 `canonical v1` 接口；
> - 旧版 `[hash_prev, hash_curr, v_max, time_diff]` 仅作为历史草案，不再作为主线接口；
> - v2 语义绑定升级会在不破坏 v1 可运行性的前提下引入 `payload_commitment`。

---

#### 5.5.2 编译和Setup脚本

```bash
#!/bin/bash
# scripts/compile_circuit.sh

set -e

CIRCUIT_NAME="tsip_main"
CIRCUIT_DIR="circuits"
BUILD_DIR="build"
PTAU_FILE="powersOfTau28_hez_final_20.ptau"  # 从ceremonia下载

echo "===== Step 1: 编译电路 ====="
circom ${CIRCUIT_DIR}/${CIRCUIT_NAME}.circom \
    --r1cs \
    --wasm \
    --sym \
    -o ${BUILD_DIR}

echo "===== Step 2: 查看电路信息 ====="
snarkjs r1cs info ${BUILD_DIR}/${CIRCUIT_NAME}.r1cs

echo "===== Step 3: 生成Groth16 zkey (Phase 1) ====="
snarkjs groth16 setup \
    ${BUILD_DIR}/${CIRCUIT_NAME}.r1cs \
    ${PTAU_FILE} \
    ${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey

echo "===== Step 4: Contribute to Phase 2 ====="
snarkjs zkey contribute \
    ${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    --name="TSIP Contribution" \
    -v \
    -e="$(openssl rand -hex 32)"

echo "===== Step 5: 导出verification key ====="
snarkjs zkey export verificationkey \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    ${BUILD_DIR}/verification_key.json

echo "===== Step 6: 生成Solidity验证器 (可选) ====="
snarkjs zkey export solidityverifier \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    ${BUILD_DIR}/TSIPVerifier.sol

echo "✅ 电路编译完成!"
echo "   - Proving key: ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey"
echo "   - Verification key: ${BUILD_DIR}/verification_key.json"
echo "   - WASM: ${BUILD_DIR}/${CIRCUIT_NAME}_js/${CIRCUIT_NAME}.wasm"
```

---

### 5.6 系统集成

#### Docker Compose配置

```yaml
# docker-compose-tsip.yml

version: '3.8'

services:
  # Shuffler (TSIP验证器)
  shuffler:
    build: 
      context: .
      dockerfile: Dockerfile.shuffler
    ports:
      - "5000:5000"
    volumes:
      - ./build:/keys:ro
      - ./logs:/logs
    environment:
      - VKEY_PATH=/keys/verification_key.json
      - LOG_LEVEL=INFO
    networks:
      - tsip-network
  
  # 聚合器A
  aggregator-a:
    build:
      context: .
      dockerfile: Dockerfile.aggregator
    ports:
      - "5001:5001"
    environment:
      - AGGREGATOR_ID=A
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - tsip-network
  
  # 聚合器R
  aggregator-r:
    build:
      context: .
      dockerfile: Dockerfile.aggregator
    ports:
      - "5002:5002"
    environment:
      - AGGREGATOR_ID=R
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - tsip-network
  
  # Decoder
  decoder:
    build:
      context: .
      dockerfile: Dockerfile.decoder
    ports:
      - "5003:5003"
    environment:
      - AGGREGATOR_A_URL=http://aggregator-a:5001
      - AGGREGATOR_R_URL=http://aggregator-r:5002
    networks:
      - tsip-network
  
  # Redis (缓存)
  redis:
    image: redis:7-alpine
    networks:
      - tsip-network
  
  # 客户端模拟器 (可选)
  client-sim:
    build:
      context: .
      dockerfile: Dockerfile.client
    volumes:
      - ./build:/keys:ro
      - ./data:/data
    environment:
      - PROVING_KEY_PATH=/keys/tsip_main_final.zkey
      - SHUFFLER_URL=http://shuffler:5000
      - NUM_USERS=100
    depends_on:
      - shuffler
    networks:
      - tsip-network

networks:
  tsip-network:
    driver: bridge
```

---

## 小结

本部分实现了TSIP协议的完整代码:

1. ✅ 客户端完整实现 (包含proof生成)
2. ✅ Shuffler验证器实现
3. ✅ 聚合器TSIP扩展
4. ✅ Circom电路完整代码
5. ✅ Docker集成配置

**下一部分**: 安全性证明和实验评估

---

## 参考实现

完整代码仓库结构:

```
tsip-impl/
├── circuits/
│   ├── tsip_main.circom
│   └── helpers/
├── tsip/
│   ├── client.py
│   ├── shuffler.py
│   ├── aggregator_tsip.py
│   └── types.py
├── scripts/
│   ├── compile_circuit.sh
│   └── run_setup.sh
├── tests/
│   ├── test_circuit.py
│   ├── test_client.py
│   └── test_integration.py
├── docker-compose-tsip.yml
└── README.md
```

## 第六章: 形式化安全分析

### 6.1 威胁模型

#### 6.1.1 攻击者能力

**攻击者类型A: 恶意客户端**

```
能力:
✓ 控制至多t<N个客户端(Sybil攻击)
✓ 伪造任意轨迹数据
✓ 观察自己提交的响应
✓ 串谋: 多个恶意客户端协作

限制:
✗ 无法破解密码学原语(如Poseidon哈希)
✗ 无法获取其他用户的私钥
✗ 无法控制服务器
```

**攻击者类型B: 诚实但好奇的服务器**

```
能力:
✓ 观察所有网络流量
✓ 看到所有加密的位置数据
✓ 看到所有TSIP证明
✓ 串谋: 至多2个服务器(S_A, S_R, S_C中的任意2个)

限制:
✗ 无法破解加密
✗ 无法伪造客户端签名
✗ 至少1个服务器保持诚实
```

**攻击者类型C: 混合攻击**

```
能力:
✓ 同时控制部分客户端和部分服务器
✓ 主动攻击: 修改/丢弃消息

限制:
✗ 至少1个服务器诚实
✗ 大多数客户端诚实
```

---

#### 6.1.2 安全目标

**G1: 完整性 (Integrity)**

```
定义: 恶意客户端无法提交违反物理约束的轨迹而不被检测

形式化:
对任意PPT攻击者A,
Pr[
  A提交轨迹τ = {loc_0, loc_1, ..., loc_T}
  ∧ ∃i: distance(loc_i, loc_{i+1}) > v_max·Δt
  ∧ 所有TSIP证明通过验证
] ≤ negl(λ)
```

**G2: 隐私性 (Privacy)**

```
定义: 服务器无法推断单个用户的具体位置

形式化:
TSIP满足(ε,δ)-差分隐私,其中:
- ε = 1.0 (总隐私预算)
- δ = 10^-8
```

**G3: 零知识性 (Zero-Knowledge)**

```
定义: TSIP证明不泄露位置witness

形式化:
对任意PPT验证者V,
存在模拟器S,使得:
View_V(proof) ≈_c S(public_inputs)
(计算不可区分)
```

---

### 6.2 定理1: 连续性完整性保证（当前实现口径）

#### 6.2.1 定理陈述

**Theorem 1 (Soundness of TSIP under continuity scope)**:

```latex
\begin{theorem}[TSIP Soundness (Continuity Scope)]
Let \Pi_{TSIP} be the TSIP protocol with security parameter \lambda.
For any PPT adversary \mathcal{A} controlling up to t clients, under:
(i) Groth16 knowledge soundness,
(ii) Poseidon collision resistance,
(iii) chain depth \ge 1 (post-enrollment),
(iv) protocol state machine correctness (no fork/double-submit acceptance),
the probability of accepting a trajectory with step violation is negligible:

\Pr\left[
\begin{aligned}
& \mathcal{A} \text{ submits trajectory } \tau = \{(x_0,y_0), \ldots, (x_T,y_T)\} \\
& \land \exists i: \|(x_{i+1},y_{i+1}) - (x_i,y_i)\| > v_{max} \cdot \Delta t \\
& \land \text{TSIP continuity checks accept}
\end{aligned}
\right] \leq \frac{T}{2^\lambda} + \epsilon_{hash}
\end{theorem}

其中（作用域说明）:
- T: 时间窗口数量
- λ: 安全参数 (128 bits)
- ε_hash: 哈希碰撞概率 (对Poseidon, ≈ 2^{-128})
- 本定理保证的是“跨轮连续性完整性”，不等价于“真实世界在场真实性（presence/truthfulness）”
```

---

#### 6.2.2 证明思路

**证明结构**:

```
完整性来源:
1. Groth16的soundness
2. 位置承诺的绑定性
3. 电路约束的正确性

攻击路径分析:
Case 1: 伪造证明 → Groth16 soundness阻断
Case 2: 哈希碰撞 → Poseidon安全性阻断
Case 3: 复用证明 → 承诺链机制阻断
```

---

#### 6.2.3 详细证明

**Proof of Theorem 1**:

假设攻击者A成功,即:

- 提交了违反物理约束的轨迹τ
- 所有TSIP证明都通过验证

我们分析所有可能的攻击策略:

---

**Case 1: 伪造Groth16证明**

```
攻击者尝试:
  构造fake_proof使得verify(fake_proof, public_inputs) = True
  但对应的witness不满足电路约束

分析:
  根据Groth16的soundness性质 [Groth16]:
  
  Pr[verify(fake_proof) = True | witness invalid] ≤ 2^(-λ)
  
  其中λ=128,故概率 ≤ 2^(-128)

结论: 此攻击路径成功概率可忽略
```

---

**Case 2: 哈希碰撞攻击**

```
攻击者尝试:
  找到(x', y') ≠ (x, y)使得Hash(x', y') = Hash(x, y)
  从而在不改变承诺的情况下修改位置

分析:
  Poseidon哈希基于有限域上的置换,
  抗碰撞性依赖于离散对数困难假设 [Grassi+2021]
  
  碰撞概率:
  Pr[Hash(x1,y1) = Hash(x2,y2) | (x1,y1) ≠ (x2,y2)] ≤ 1/|F|
  
  其中|F| = 2^254 (BN254曲线的域大小)
  
  故碰撞概率 ≤ 2^(-254) < 2^(-128)

结论: 此攻击路径成功概率可忽略
```

---

**Case 3: 复用他人证明**

```
攻击者尝试:
  窃取诚实用户Bob的proof,用于自己的提交

分析:
  TSIP证明绑定了公开输入:
  - hash_prev: 前一个位置的承诺
  - hash_curr: 当前位置的承诺
  
  攻击者Alice的hash_prev ≠ Bob的hash_prev
  (除非发生哈希碰撞,概率已分析为negl)
  
  验证器检查:
  verify(Bob_proof, Alice_hash_prev) 
    → 失败 (公开输入不匹配)

结论: 此攻击路径被承诺链机制阻断
```

---

**Case 4: 身份交换攻击（超出本定理直接证明范围）**

```
攻击者尝试:
  Alice和Bob在时刻t交换ID
  
  t=0: Alice提交commitment_A = Hash(loc_A^0)
       Bob提交commitment_B = Hash(loc_B^0)
  
  t=1: Alice用Bob的ID提交loc_A^1

修订后的保守结论:
  仅依赖“攻击者不知道他人坐标”不足以构成顶会级安全论证。
  完整抗身份交换声明需要:
  - hidden per-user secret 的跨轮一致性绑定
  - epoch/nullifier 防重放与双提交
  - 状态机规则防分叉

当前口径:
  - 该场景先作为 proposition/assumption 处理，不并入 Theorem 1 的概率上界计算；
  - 等 hidden secret + nullifier + 状态机完整落地后，再升级为强声明。
```

---

**Case 5: 时序攻击（重放，状态机前提）**

```
攻击者尝试:
  在t=2时重放t=1的proof

分析:
  重放防御不应只依赖 time_diff。
  需要状态机级绑定:
  - (user_id, round_id/window_id, submission_id)
  - payload digest
  - 链状态版本（prev/curr commitment）

当前口径:
  - 该场景依赖状态机前提，不并入 Theorem 1 的直接概率求和；
  - 论文中应写成“在状态机正确实现前提下”。
```

---

**Union Bound**:

```
Theorem 1 仅对 Case 1~3 给出直接上界:
总成功概率 ≤ P(case1) + P(case2) + P(case3)
         ≤ 2^(-128) + 2^(-254) + negl(λ)
         = negl(λ)

对于T个时间窗口,每个窗口都有上述概率,
故总概率 ≤ T × negl(λ)

当T=288时:
  Pr[攻击成功] 仍为可忽略量级（由 λ 控制）
```

**Q.E.D. □**

---

### 6.3 定理2: 公开输出的差分隐私保证

#### 6.3.1 定理陈述（主口径）

**Theorem 2 (Public-Output Differential Privacy of TSIP)**:

```latex
\begin{theorem}[TSIP Public-Output Privacy]
Let $M_{pub}$ denote the released heatmap of TSIP.
Then TSIP satisfies $(\epsilon, \delta)$-DP on $M_{pub}$ with:
\begin{align}
\epsilon &= \epsilon_{SVT} + \epsilon_{value} \\
\delta &= 10^{-8}
\end{align}
\end{theorem}
```

当前实现默认参数下：

- `ε_SVT = 0.3`
- `ε_value = 0.7`
- `ε_total = 1.0`

说明：

- 这里的 DP 保证只针对**最终公开热力图输出**。
- TSIP 验证步骤（accept/reject）属于系统内部过滤信号，不并入主 DP 预算（见 6.3.2）。

---

#### 6.3.2 边界与泄露分解（Who Learns What）

为避免 overclaim，隐私边界拆分如下：

1. Public output（对外发布）
   - 最终热力图（`reconstruct + dp/latest` 结果）
   - 适用主定理中的 DP 保证

2. Internal signals（内部可见）
   - Shuffler 的 `accept/reject`
   - 承诺链状态（`prev/curr commitment`）
   - 提交时序元数据（`round_id/window_id`）
   - 这些属于 trusted infrastructure 侧可见信息，不并入 public-output DP 预算

3. 语义澄清
   - TSIP 验证可以视为“DP 发布前的完整性过滤器”；
   - 它提供完整性约束，不等价于对外发布机制本身。

4. DP 术语冻结（论文写作强制项）
   - adjacency：`user-level`（相邻数据集仅相差一个用户报告）
   - sensitivity：由每用户贡献上界（Top-K + clipping）导出
   - SVT：引用标准 sparse vector 机制定理，不使用“黑盒经验口径”
   - 公开主张仅覆盖 public-output，不外推到 trusted infrastructure 内部可见信号

---

#### 6.3.3 主定理证明（组合定理）

**Proof of Theorem 2**:

**Step 1: 完整性过滤与聚合前阶段**

```
- Top-K、dummy、proof 构造属于客户端本地处理；
- TSIP 验证是系统内部过滤，不直接形成公开发布结果；
- 聚合前阶段不计入 public-output DP 预算。
```

**Step 2: 安全聚合阶段**

```
- A/R 双聚合器仅见秘密份额；
- 在至少一方诚实假设下，单方不可恢复单用户位置；
- 该阶段不增加 public-output DP 支出。
```

**Step 3: Decoder 的 DP 释放阶段**

```
SVT:
  - 消耗 ε_SVT = 0.3

Value noise:
  - 对发布计数加噪
  - 消耗 ε_value = 0.7

小计:
  ε_decoder = ε_SVT + ε_value = 1.0
```

**Step 4: 顺序组合**

```
ε_total = ε_SVT + ε_value = 1.0
δ_total = 10^(-8)
```

**Step 5: 后处理不变性**

```
对已发布 DP 结果的可视化与查询属于后处理，不增加隐私泄露。
```

**Q.E.D. □**

---

#### 6.3.4 可选随机化验证（实验项，不是主口径）

为研究完整性-误判权衡，系统保留“随机化验证”实验开关：

- 实现位置：`services/shuffler/app.py`
- 配置项（默认关闭）：
  - `TSIP_VERIFY_DP_ENABLE`
  - `TSIP_VERIFY_EPSILON`
  - `TSIP_VERIFY_NOISY_THRESHOLD`
  - `TSIP_VERIFY_DP_SEED`
- 运行观测：
  - `/health` 中 `tsip_verify_dp_enable / tsip_verify_epsilon / tsip_verify_calls / tsip_verify_spent`

注意：

- 该机制用于附录或扩展实验（验证随机化策略），
- 不纳入论文主结果中的 DP 预算组合公式。

---

**多 Shuffler 门限转发与 payload 绑定（k-of-t，2026-03-25~2026-04-01）**

- 实现位置：
  - `services/shuffler/app.py`：新增 `/committee/attest`，并在 `ingestA/ingestR` 中收集门限签名
  - `services/aggregator_a/app.py`、`services/aggregator_r/app.py`：新增门限验签守门
  - `common/committee.py`：统一签名/验签与 payload 规范
- 机制（分版本）：
  - v0（已实现）：
    - 每个 Shuffler 对 `(channel, round_id, submission_id, idx/val digest)` 生成 HMAC/MAC
    - 聚合器仅接收“有效 MAC 数量 >= `SHUFFLER_COMMITTEE_THRESHOLD`”的提交
    - 语义注意：HMAC 是 shared-secret MAC，不是可转移数字签名；不可等同于强门限签名
  - v1（进行中，P0）：
    - 签名摘要升级为 `(channel, round_id, submission_id, user_id, window_id, payload_digest, proof_digest, prev_chain, curr_chain)`
    - 聚合器本地重算 `payload_digest`，与 attestation 摘要不一致即拒绝
  - v2（建议，论文增强）：
    - 将 v0/v1 的 HMAC 层替换为 Ed25519（或 BLS）数字签名；
    - 若主张“门限签名”语义，则需使用真正 threshold signature 方案
- 关键配置：
  - `SHUFFLER_COMMITTEE_ENABLE`
  - `SHUFFLER_COMMITTEE_THRESHOLD`
  - `SHUFFLER_COMMITTEE_ID`、`SHUFFLER_COMMITTEE_SIGN_SECRET`
  - `SHUFFLER_COMMITTEE_PEERS`
  - `SHUFFLER_COMMITTEE_KEYS`（聚合器侧，格式 `s1:sec1,s2:sec2,s3:sec3`）
  - 本地三节点联调可用：`docker compose --profile committee up -d`
- 安全语义：
  - 在 `k=3,t=2` 时，可声明“容忍 1 个恶意/失效 Shuffler 后仍可维持转发门限策略”
  - v0 主要防单点绕过；但其密码学语义是 MAC 门控，不是强可转移签名
  - v1 进一步防“proof 通过后 payload 被替换”的拆分攻击
  - 仍需结合部署隔离、审计日志与状态机规则（fork/double-submit）共同生效。

---

**首轮（t=0）安全边界修订（2026-03-25）**

- 问题本质：TSIP 的时空连续性证明依赖“上一承诺已存在”，因此严格来说定理只对链深度 `>=1` 的提交成立。
- 修订后的安全声明：
  - 不再宣称“所有提交（包含首轮）都满足同等时空完整性保证”；
  - 明确声明“TSIP 完整性保证适用于已完成 enrollment 的用户提交（即有历史承诺链）”。
- 协议化解决（非 warm-up 工程绕过）：
  - 将首轮提交定义为 **enrollment/anchor** 阶段；
  - enrollment 仅用于建立 `H_0` 承诺锚点，不直接进入聚合；
  - 只有从 `H_0 -> H_1` 开始、具备连续性证明的提交才可进入最终聚合。
- 工程开关：
  - `TSIP_BOOTSTRAP_POLICY=legacy_accept`：旧行为（首轮可聚合）
  - `TSIP_BOOTSTRAP_POLICY=enroll_only`：严格行为（首轮仅锚定、不聚合）
- 实现位置：
  - `services/shuffler/app.py` 中 `ingestA/ingestR` 的 `bootstrap_held` 逻辑与 `/health` 可观测字段。

---

#### 6.3.5 主定理分步解释（实现对齐）

**Proof of Theorem 2**:

**Step 1: 客户端阶段**

```
本地操作不消耗全局隐私预算:
- Top-K筛选/clip/dummy: 属于本地预处理与贡献约束，不单独宣称DP
- Dummy注入: 从公开分布采样，用于稀疏掩蔽与鲁棒性

TSIP证明生成:
- witness(私密位置)在本地处理
- 输出的proof满足零知识性
- 验证结果属于内部过滤信号，不计入主 DP 预算

小计: ε_client = 0
```

**Step 2: 聚合器阶段**

```
MPC聚合:
- 单个聚合器只看到秘密份额
- 满足2-privacy (任意1个聚合器学不到信息)
- 不额外消耗DP预算

小计: ε_aggregation = 0
```

**Step 3: Decoder阶段**

```
稀疏向量技术(SVT):
  - 对阈值加噪声: Lap(2/ε_SVT)
  - 对每个计数加噪声: Lap(1/ε_SVT)
  - 消耗预算: ε_SVT = 0.3

值噪声注入:
  - 对通过阈值的网格,计数加噪声: Lap(Δf/ε_value)
  - adjacency 口径: user-level（相邻数据集仅相差一个用户报告）
  - 全局敏感度: Δf 由每用户贡献上界（Top-K + clip）给出
  - 消耗预算: ε_value = 0.7

小计: ε_decoder = 0.3 + 0.7 = 1.0
```

**Step 4: 组合定理应用**

```
根据DP的顺序组合定理:
  ε_total = ε_client + ε_aggregation + ε_decoder
          = 0 + 0 + 1.0
          = 1.0

δ_total = δ_client + δ_aggregation + δ_decoder
        = 0 + 0 + 10^(-8)
        = 10^(-8)
```

**Step 5: 后处理不变性**

```
最终热力图经过DP机制产生后,
任何不访问原始数据的后处理(如可视化、查询)
都不会增加隐私泄露

这保证了输出的热力图可以安全地公开使用
```

**Q.E.D. □**

---

### 6.4 定理3: 零知识性

#### 6.4.1 定理陈述

**Theorem 3 (Zero-Knowledge Property)**:

```latex
\begin{theorem}[TSIP Zero-Knowledge]
The TSIP proof system satisfies computational zero-knowledge.
Specifically, for any PPT verifier V*, there exists a PPT 
simulator S such that:

\{View_{V^*}(x, w)\} \approx_c \{S(x)\}

where:
- x: public inputs (hash_prev, hash_curr, max_dist_sq)
- w: witness (x1, y1, x2, y2)
- View: verifier's view (包括证明和所有交互)
\end{theorem}
```

---

#### 6.4.2 证明框架

**零知识性来源**:

```
TSIP的ZK依赖于Groth16的ZK性质

关键: Groth16中的随机盲化因子 r, s
  proof_A = α·g + Σaᵢ·Lᵢ(τ)·g + r·δ·g
  proof_B = β·g + Σaᵢ·Rᵢ(τ)·g + s·δ·g
  proof_C = ... + s·A + r·B - r·s·δ·g
  
  即使知道proof_A, proof_B, proof_C,
  由于r, s的随机性,无法反推witness {aᵢ}
```

---

#### 6.4.3 模拟器构造

**Simulator S(x)**:

```python
def simulator(public_inputs):
    """
    零知识模拟器: 不知道witness的情况下生成"看起来真实"的证明
    
    Args:
        public_inputs: (hash_prev, hash_curr, max_dist_sq)
    
    Returns:
        simulated_proof: 与真实proof计算不可区分
    """
    # 1. 随机采样"假"的witness
    fake_witness = {
        "x1": random_field_element(),
        "y1": random_field_element(),
        "x2": random_field_element(),
        "y2": random_field_element()
    }
    
    # 2. 使用CRS的trapdoor生成proof
    # (在真实系统中,trapdoor已被销毁)
    # (这里只是理论分析,证明ZK性质存在)
    
    # 生成随机群元素
    simulated_proof = {
        "pi_a": random_G1_point(),
        "pi_b": random_G2_point(),
        "pi_c": random_G1_point()
    }
    
    # 3. 关键: 调整proof使其通过验证等式
    # (利用trapdoor α, β, γ, δ)
    # adjust_proof_with_trapdoor(simulated_proof, public_inputs, trapdoor)
    
    return simulated_proof


# 不可区分性证明:
# 对任意PPT区分器D:
# |Pr[D(real_proof) = 1] - Pr[D(simulated_proof) = 1]| ≤ negl(λ)
```

---

#### 6.4.4 完整证明

**Proof of Theorem 3**:

我们构造模拟器S并证明其输出与真实proof不可区分

**模拟器S的工作流程**:

```
输入: public_inputs = (hash_prev, hash_curr, max_dist_sq)

Step 1: 不使用witness,直接生成"看起来随机"的proof
  
  由于Groth16的proof是群元素:
  proof = (A, B, C) ∈ G₁ × G₂ × G₁
  
  S采样:
  A' ← random_G1()
  B' ← random_G2()
  C' ← random_G1()

Step 2: 使用CRS的trapdoor调整proof
  
  (在Setup阶段,trapdoor = (α, β, γ, δ, τ)已被销毁)
  (但在理论分析中,我们假设S可以访问trapdoor)
  
  S计算:
  A = A' + correction_A(public_inputs, trapdoor)
  B = B' + correction_B(public_inputs, trapdoor)
  C = C' + correction_C(public_inputs, trapdoor)
  
  使得配对等式成立:
  e(A, B) = e(α·g₁, β·g₂) · e(L_pub·g₁, γ·g₂) · e(C, δ·g₂)

Step 3: 输出调整后的proof
```

**不可区分性论证**:

```
考虑两个分布:
- Real: 真实proof,由诚实Prover用witness生成
- Simulated: 模拟proof,由S不用witness生成

关键观察:
  在Groth16中,真实proof包含随机盲化因子(r, s)
  
  Real proof:
  A = α·g + [witness related terms] + r·δ·g
                                      ↑
                                   均匀随机
  
  由于r是均匀随机的,A在G₁中的分布也是均匀随机的
  (除了满足配对等式的约束)

  Simulated proof:
  A' 也是从G₁均匀随机采样
  然后调整为满足配对等式
  
  ∴ Real和Simulated的分布相同(在G₁上的均匀分布)

形式化:
  对任意PPT区分器D:
  
  |Pr[D(Real) = 1] - Pr[D(Sim) = 1]|
  ≤ Adv_DDH(λ)  (依赖于DDH假设)
  ≤ negl(λ)
```

**Q.E.D. □**

---

### 6.5 通信效率分析（工程口径）

> 说明：原“通信下界最优性定理”属于理想化草案，当前版本不作为主文强定理使用。
> 论文主文建议改为“工程通信效率对比 + 实测开销”。

#### 6.5.1 每次提交的通信构成

```
per-submission 主要开销:
- zk proof（Groth16）: 约 0.70~0.81 KB（实测区间）
- 承诺链字段: prev/curr commitment 与链状态元数据
- 稀疏索引与份额: idx/val 提交

合计: 当前实现约 1KB 级（与配置和序列化格式有关）
```

#### 6.5.2 对比口径（用于实验章节）

```
TSIP:
  通信成本与 domain size 弱相关（使用稀疏 top-k 表示）
  不随全域 D 线性膨胀到 dense 向量级别

Range-proof/inner-product 型基线:
  通信开销可随维度显著增长
  在大域场景下工程代价更高
```

#### 6.5.3 当前主张边界

```
当前文档只主张“工程上通信效率可接受且优于 dense 方案”。
不主张“已完成严格信息论最优下界证明”。
```

---

### 6.6 安全性总结

| 定理          | 性质           | 保证                            | 依赖假设               |
| ------------- | -------------- | ------------------------------- | ---------------------- |
| **Theorem 1** | Soundness      | 连续性作用域内，违规步长通过概率可忽略 | Groth16 soundness, Poseidon 抗碰撞 |
| **Theorem 2** | Privacy        | (1.0, 10^(-8))-DP               | DP组合定理             |
| **Theorem 3** | Zero-Knowledge | 证明不泄露witness               | DDH假设                |
| **工程分析**  | Communication  | 1KB 级每次提交（实测口径）      | 稀疏表示 + 实测统计    |

---

## 第七章: 攻击防御分析

### 7.1 跨时间窗口攻击

#### 攻击描述

```
攻击者Alice和Bob串谋:
t=0: Alice在东京, Bob在大阪
t=1: 交换ID, Alice提交"在大阪"
```

#### TSIP防御

```
✅ 核心防御不是"不知道坐标",而是跨轮绑定:
  - 证明中要求 user_secret 一致性 + epoch/nullifier 防重放
  - proof 与 payload 摘要绑定,防止"合法proof + 非法payload"拆分
  - 承诺链前后状态由 shuffler 状态机检查(单轮单提交、防fork)

✅ 物理连续性约束:
  - 若攻击路径需要大位移跳变
  - 则距离约束触发拒绝
```

#### 实验验证口径

```python
def test_identity_swap_attack():
    # Alice在东京
    alice_loc_0 = Location(x=0, y=0, t=0)
    alice_commitment_0 = Hash(alice_loc_0)
    
    # Bob在大阪
    bob_loc_0 = Location(x=500000, y=0, t=0)  # 500km外
    bob_commitment_0 = Hash(bob_loc_0)
    
    # t=1: Alice尝试用Bob的ID提交
    alice_loc_1 = Location(x=1000, y=1000, t=300)  # 仍在东京附近
    
    # Alice即使猜测了Bob的初始位置,
    # 也无法通过 secret/nullifier/epoch/payload 绑定检查
    # 下面仅演示距离约束分支:
    guessed_bob_loc_0 = Location(x=500000, y=0, t=0)
    
    # 距离检查:
    distance = euclidean(guessed_bob_loc_0, alice_loc_1)
    assert distance > v_max * time_diff  # 499km > 30km
    
    # 生成proof会失败(至少一个约束分支不满足)
    proof = generate_tsip_proof(guessed_bob_loc_0, alice_loc_1)
    assert verify_proof(proof) == False  # ✓ 攻击被阻止
```

---

### 7.2 Sybil + 瞬移攻击

#### 攻击描述

```
攻击者创建1000个虚假账户:
t=0: 分散在城市各处(每个位置都合法)
t=1: 全部"瞬移"到商场A
目的: 虚增商场A的热度
```

#### TSIP防御

```
✅ 每个账户独立验证:
  - 每个账户都有独立的承诺链
  - 如果任何账户"瞬移",其proof验证失败

✅ 成本提升结论:
  - 一步瞬移会被高概率拒绝
  - 攻击者若改为渐进漂移,需要跨多轮持续投入账户与时间成本
  - 论文主张应表述为"attack-cost elevation",而非"一切恶意轨迹绝对阻断"
```

#### 实验验证

```python
def test_sybil_teleport_attack():
    num_sybils = 1000
    
    # t=0: Sybils分散在各处
    sybil_locs_0 = [
        Location(x=random()*1000000, y=random()*1000000, t=0)
        for _ in range(num_sybils)
    ]
    
    # 生成承诺
    commitments = [Hash(loc) for loc in sybil_locs_0]
    
    # t=1: 全部瞬移到(0, 0)
    target = Location(x=0, y=0, t=300)
    
    rejected = 0
    for i in range(num_sybils):
        proof = generate_tsip_proof(sybil_locs_0[i], target)
        if not verify_proof(proof):
            rejected += 1
    
    # 预期: 在该攻击设置中绝大多数被拒绝
    assert rejected > 0.95 * num_sybils
    
    # Shuffler检测到异常
    rejection_rate = rejected / num_sybils
    assert rejection_rate > 0.1  # 触发警报阈值
```

---

### 7.3 时序相关攻击

#### 攻击描述

```
攻击者观察热力图的时序模式,
尝试关联同一用户在不同时间的提交
```

#### TSIP防御

```
✅ 条件化的标识保护:
  - 当系统启用 window 作用域 pseudonym 时,
    可降低跨窗口直接关联能力
  - 当采用 stable user scope 时,服务器可关联同一 user_id;
    该配置主要服务于链式完整性与可复现实验

✅ DP噪声:
  - 最终输出添加DP噪声
  - 模糊时序相关性

✅ 承诺不泄露位置:
  - 服务器只看到Hash(location)
  - 无法推断具体位置
```

---

### 7.4 服务器串谋攻击

#### 攻击描述

```
S_A和S_R串谋,尝试重构用户的明文位置
```

#### TSIP防御

```
✅ 秘密分享:
  - 位置被分成3份: share_A, share_R, share_C
  - 需要至少2份才能重构
  - 如果S_A和S_R串谋 → 可以重构

⚠️ 但这已在威胁模型假设中:
  "至少1个服务器诚实"
  
  如果S_A和S_R都不诚实,系统退化为:
  - 仍有TSIP验证(完整性保持)
  - 但隐私依赖DP噪声(不是MPC)
```

#### 改进方案

```
使用阈值秘密分享(t-out-of-n):
- 将位置分成n=5份
- 需要t=3份才能重构
- 即使2个服务器串谋,仍安全

代价: 增加通信开销和服务器数量
```

---

## 小结

本部分完成了TSIP的形式化安全分析:

1. ✅ 4个核心定理及其证明
2. ✅ 主要攻击场景的防御分析
3. ✅ 实验验证代码

**下一部分**: 实验评估与论文撰写指南

---

## 参考文献

[Groth16] Jens Groth. "On the Size of Pairing-Based Non-Interactive Arguments". EUROCRYPT 2016.

[Dwork06] Cynthia Dwork et al. "Calibrating Noise to Sensitivity in Private Data Analysis". TCC 2006.

[Grassi+21] Lorenzo Grassi et al. "Poseidon: A New Hash Function for Zero-Knowledge Proof Systems". USENIX Security 2021.

## 第八章: 实验评估方案 [PENDING/ARCHIVE]

> 本章包含实验模板与计划项；论文主结果请以文档前部 `[CURRENT]` 实测统计为准。

### 8.1 实验目标

#### 核心问题

```
Q1: TSIP是否有效阻止跨时间窗口攻击?
Q2: TSIP的性能开销是否可接受?
Q3: TSIP与现有方案相比有何优势?
Q4: TSIP在真实数据上的效果如何?
```

---

### 8.2 数据集

#### 8.2.1 真实数据集

**GeoLife (微软研究院)**

```
规模: 
- 182 用户
- 17,621 条轨迹
- 24,876,978 个GPS点
- 时间跨度: 2007-2012

特点:
- 真实用户行为
- 包含多种交通方式(步行/驾车/公交)
- 适合验证算法正确性

下载: 
https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/

预处理:
- 划分为5分钟时间窗口
- 映射到100m×100m网格
- 计算停留时间
```

**T-Drive (北京出租车轨迹)**

```
规模:
- 10,357 辆出租车
- 15,000,000+ GPS点
- 采样频率: 177秒
- 覆盖范围: 北京市区

特点:
- 大规模数据
- 适合测试可扩展性
- 真实城市交通模式

下载:
https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/
```

---

#### 8.2.2 合成数据生成

```python
# experiments/synthetic_data.py

import numpy as np
from typing import List, Tuple

class SyntheticTrajectoryGenerator:
    """生成符合真实分布的合成轨迹"""
    
    def __init__(self, city_bounds: Tuple[float, float, float, float]):
        """
        Args:
            city_bounds: (x_min, y_min, x_max, y_max)
        """
        self.bounds = city_bounds
        
        # 热点区域(模拟商业区/居民区)
        self.hotspots = self.generate_hotspots(num=100)
    
    def generate_hotspots(self, num: int) -> List[Tuple[float, float]]:
        """生成幂律分布的热点"""
        hotspots = []
        for i in range(num):
            # 幂律分布: 更多热点集中在市中心
            weight = 1.0 / (i + 1) ** 0.5
            angle = np.random.uniform(0, 2*np.pi)
            radius = np.random.exponential(scale=5000) * weight
            
            x = self.bounds[0] + self.bounds[2]/2 + radius * np.cos(angle)
            y = self.bounds[1] + self.bounds[3]/2 + radius * np.sin(angle)
            
            hotspots.append((x, y))
        
        return hotspots
    
    def generate_user_trajectory(self, 
                                 user_id: int, 
                                 num_windows: int = 288) -> List[Location]:
        """
        生成单个用户的轨迹
        
        模式:
        - 00:00-08:00: 在家 (随机游走)
        - 08:00-09:00: 通勤 (家→公司)
        - 09:00-18:00: 在公司 (小范围活动)
        - 18:00-19:00: 通勤 (公司→家)
        - 19:00-24:00: 娱乐 (访问热点)
        """
        # 采样家和公司位置
        home = random.choice(self.hotspots)
        work = random.choice(self.hotspots)
        
        trajectory = []
        current_loc = home
        
        for window_id in range(num_windows):
            hour = (window_id * 5 / 60) % 24  # 当前小时
            
            if 0 <= hour < 8:  # 在家
                next_loc = self.random_walk(current_loc, radius=500)
            
            elif 8 <= hour < 9:  # 通勤到公司
                next_loc = self.interpolate(current_loc, work, steps=12)
            
            elif 9 <= hour < 18:  # 在公司
                next_loc = self.random_walk(work, radius=300)
            
            elif 18 <= hour < 19:  # 通勤回家
                next_loc = self.interpolate(current_loc, home, steps=12)
            
            else:  # 19-24: 娱乐
                if np.random.random() < 0.1:  # 10%概率去热点
                    target = random.choice(self.hotspots)
                    next_loc = self.interpolate(current_loc, target, steps=6)
                else:
                    next_loc = self.random_walk(home, radius=2000)
            
            # 确保满足物理约束
            distance = euclidean(current_loc, next_loc)
            max_dist = 100 * 300  # 100 m/s × 300s = 30km
            if distance > max_dist:
                next_loc = self.clamp_distance(current_loc, next_loc, max_dist)
            
            trajectory.append(Location(
                x=next_loc[0],
                y=next_loc[1],
                timestamp=window_id * 300,
                cell_id=xy_to_cell_id(next_loc[0], next_loc[1]),
                dwell_time=300
            ))
            
            current_loc = next_loc
        
        return trajectory
    
    def random_walk(self, center: Tuple[float, float], radius: float):
        """在中心点附近随机游走"""
        angle = np.random.uniform(0, 2*np.pi)
        dist = np.random.exponential(scale=radius/3)
        dist = min(dist, radius)
        
        x = center[0] + dist * np.cos(angle)
        y = center[1] + dist * np.sin(angle)
        
        return (x, y)
    
    def interpolate(self, start, end, steps: int):
        """线性插值"""
        t = 1.0 / steps
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        return (x, y)
    
    def clamp_distance(self, start, end, max_dist: float):
        """将终点限制在最大距离内"""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = np.sqrt(dx**2 + dy**2)
        
        if dist <= max_dist:
            return end
        
        scale = max_dist / dist
        return (start[0] + dx*scale, start[1] + dy*scale)

# 使用示例
generator = SyntheticTrajectoryGenerator(
    city_bounds=(0, 0, 1000000, 1000000)  # 1000km × 1000km
)

# 生成100个用户,每人24小时
trajectories = [
    generator.generate_user_trajectory(user_id=i, num_windows=288)
    for i in range(100)
]
```

---

#### 8.2.3 恶意轨迹生成器

```python
# experiments/attack_generator.py

class MaliciousTrajectoryGenerator:
    """生成各种攻击轨迹"""
    
    def generate_teleport_attack(self, distance_ratio=2.0):
        """
        生成瞬移攻击
        
        Args:
            distance_ratio: 违规倍数 (2.0表示瞬移距离是合法距离的2倍)
        """
        trajectory = []
        
        # t=0: 在东京
        loc_0 = Location(x=0, y=0, t=0, cell_id=0, dwell_time=300)
        trajectory.append(loc_0)
        
        # t=1: 瞬移到大阪 (500km外)
        illegal_distance = 100 * 300 * distance_ratio  # 60km (超过30km限制)
        loc_1 = Location(
            x=illegal_distance, 
            y=0, 
            t=300, 
            cell_id=xy_to_cell_id(illegal_distance, 0), 
            dwell_time=300
        )
        trajectory.append(loc_1)
        
        return trajectory
    
    def generate_identity_swap_attack(self, alice_traj, bob_traj, swap_time=5):
        """
        生成身份交换攻击
        
        Args:
            alice_traj: Alice的正常轨迹
            bob_traj: Bob的正常轨迹
            swap_time: 在第几个时间窗口交换
        """
        # Alice的轨迹: 前5个窗口正常,之后变成Bob的轨迹
        alice_malicious = (
            alice_traj[:swap_time] + 
            bob_traj[swap_time:]
        )
        
        # Bob的轨迹: 前5个窗口正常,之后变成Alice的轨迹
        bob_malicious = (
            bob_traj[:swap_time] + 
            alice_traj[swap_time:]
        )
        
        return alice_malicious, bob_malicious
    
    def generate_sybil_attack(self, num_sybils=1000, target_location=(0, 0)):
        """
        生成Sybil攻击
        
        策略:
        - t=0: 分散在各处
        - t=1: 全部瞬移到目标位置
        """
        sybil_trajectories = []
        
        for i in range(num_sybils):
            # t=0: 随机位置
            start_x = np.random.uniform(0, 1000000)
            start_y = np.random.uniform(0, 1000000)
            loc_0 = Location(x=start_x, y=start_y, t=0, 
                           cell_id=xy_to_cell_id(start_x, start_y),
                           dwell_time=300)
            
            # t=1: 瞬移到目标
            loc_1 = Location(x=target_location[0], y=target_location[1], t=300,
                           cell_id=xy_to_cell_id(*target_location),
                           dwell_time=300)
            
            sybil_trajectories.append([loc_0, loc_1])
        
        return sybil_trajectories
```

---

### 8.3 Baseline方案实现

#### 8.3.1 Pure LDP (RAPPOR)

```python
# experiments/baselines/pure_ldp.py

class PureLDP:
    """纯本地差分隐私方案"""
    
    def __init__(self, epsilon=1.0, domain_size=1000000):
        self.epsilon = epsilon
        self.domain_size = domain_size
        
        # RAPPOR参数
        self.p = 0.5  # 永久随机化概率
        self.q = 1 / (1 + np.exp(epsilon/2))  # 瞬时随机化概率
    
    def randomize_response(self, true_value: int) -> int:
        """RAPPOR随机化响应"""
        # Step 1: 永久随机化 (Bloom filter)
        if np.random.random() < self.p:
            return np.random.randint(0, self.domain_size)
        
        # Step 2: 瞬时随机化
        if np.random.random() < self.q:
            return np.random.randint(0, self.domain_size)
        
        return true_value
    
    def aggregate(self, responses: List[int]) -> np.ndarray:
        """服务器端聚合"""
        histogram = np.zeros(self.domain_size)
        
        for resp in responses:
            histogram[resp] += 1
        
        # 去偏
        n = len(responses)
        debiased = (histogram - n * self.q) / (1 - self.p - self.q)
        
        return np.maximum(debiased, 0)
```

---

#### 8.3.2 RiseFL (无时序约束)

```python
# experiments/baselines/risefl.py

class RiseFL:
    """RiseFL方案(仅验证单个时刻)"""
    
    def __init__(self, m=10, alpha=0.05):
        """
        Args:
            m: 随机向量数量
            alpha: 显著性水平
        """
        self.m = m
        self.alpha = alpha
    
    def generate_random_vectors(self, dimension: int) -> List[np.ndarray]:
        """服务器生成随机向量"""
        return [np.random.randn(dimension) for _ in range(self.m)]
    
    def compute_proof(self, location_vector: np.ndarray, 
                     random_vectors: List[np.ndarray]) -> float:
        """客户端计算完整性证明"""
        inner_products = [
            np.dot(location_vector, a) 
            for a in random_vectors
        ]
        
        sum_of_squares = sum([ip**2 for ip in inner_products])
        
        return sum_of_squares
    
    def verify(self, proof_s: float, norm_bound: float) -> bool:
        """服务器验证"""
        from scipy.stats import chi2
        
        threshold = norm_bound**2 * chi2.ppf(1 - self.alpha, df=self.m)
        
        return proof_s <= threshold
    
    # ⚠️ 关键缺陷: 无法验证跨时间窗口的连续性!
    def verify_trajectory(self, trajectory: List[Location]) -> bool:
        """验证整条轨迹(RiseFL无法做到这一点)"""
        # RiseFL只能验证每个时刻的位置是否合理
        # 无法验证相邻时刻的连续性
        
        for i, loc in enumerate(trajectory):
            loc_vector = location_to_vector(loc, self.domain_size)
            random_vecs = self.generate_random_vectors(len(loc_vector))
            proof_s = self.compute_proof(loc_vector, random_vecs)
            
            if not self.verify(proof_s, norm_bound=100):
                return False  # 单个位置不合法
        
        # ❌ 无法检测: trajectory[i]到trajectory[i+1]的距离过大!
        return True
```

---

### 8.4 评估指标

#### 8.4.1 安全性指标

**攻击检测率 (Attack Detection Rate)**

```python
def measure_attack_detection_rate(protocol, attack_trajectories):
    """
    测量方案检测攻击的能力
    
    Returns:
        TPR (True Positive Rate): 恶意轨迹被正确拒绝的比例
        FPR (False Positive Rate): 正常轨迹被误拒的比例
    """
    # 恶意轨迹
    malicious_rejected = 0
    for traj in attack_trajectories:
        if not protocol.verify_trajectory(traj):
            malicious_rejected += 1
    
    TPR = malicious_rejected / len(attack_trajectories)
    
    # 正常轨迹
    normal_trajectories = generate_normal_trajectories(n=1000)
    normal_rejected = 0
    for traj in normal_trajectories:
        if not protocol.verify_trajectory(traj):
            normal_rejected += 1
    
    FPR = normal_rejected / len(normal_trajectories)
    
    return {"TPR": TPR, "FPR": FPR}

# 实验
results = {}

# TSIP
tsip_attacks = generate_teleport_attacks(n=1000, distance_ratio=2.0)
results["TSIP"] = measure_attack_detection_rate(TSIP(), tsip_attacks)

# RiseFL (baseline)
results["RiseFL"] = measure_attack_detection_rate(RiseFL(), tsip_attacks)

# [ARCHIVE] 历史预期模板（非实测，不能用于论文主文）:
# TSIP:   TPR=0.997, FPR=0.05
# RiseFL: TPR=0.001, FPR=0.05  (几乎无法检测跨时间攻击!)
```

**隐私泄露量化**

```python
def empirical_epsilon_test(protocol, dataset, delta=1e-8, iterations=1000):
    """
    通过蒙特卡洛验证实际隐私预算
    
    方法:
    1. 生成相邻数据集D1和D2(仅差1个用户)
    2. 多次运行协议,获取输出分布
    3. 计算KL散度上界
    """
    epsilon_samples = []
    
    for _ in range(iterations):
        # 生成相邻数据集对
        D1, D2, changed_user = generate_neighboring_datasets(dataset)
        
        # 运行协议
        output_D1 = protocol.run(D1)
        output_D2 = protocol.run(D2)
        
        # 计算散度
        epsilon = compute_max_divergence(output_D1, output_D2, delta)
        epsilon_samples.append(epsilon)
    
    # 95分位数应≤声称的ε
    empirical_epsilon = np.percentile(epsilon_samples, 95)
    
    return empirical_epsilon

# 实验
claimed_epsilon = 1.0
actual_epsilon = empirical_epsilon_test(TSIP(), geolife_dataset)

assert actual_epsilon <= claimed_epsilon * 1.1  # 允许10%误差
print(f"声称: ε={claimed_epsilon}, 实际: ε={actual_epsilon:.2f}")
```

---

#### 8.4.2 效用指标

**热力图准确度**

```python
def heatmap_accuracy(predicted_heatmap, ground_truth_heatmap):
    """
    评估隐私热力图与真实热力图的相似度
    """
    # 1. Top-K重叠率 (Jaccard Index)
    k = 100
    top_k_pred = set(get_top_k_cells(predicted_heatmap, k))
    top_k_true = set(get_top_k_cells(ground_truth_heatmap, k))
    
    jaccard = len(top_k_pred & top_k_true) / len(top_k_pred | top_k_true)
    
    # 2. 均方根误差 (RMSE)
    rmse = np.sqrt(np.mean((predicted_heatmap - ground_truth_heatmap)**2))
    
    # 3. 地球移动距离 (Earth Mover's Distance)
    emd = wasserstein_distance(
        predicted_heatmap.flatten(), 
        ground_truth_heatmap.flatten()
    )
    
    # 4. 相对误差
    relative_error = np.abs(predicted_heatmap - ground_truth_heatmap).sum() / ground_truth_heatmap.sum()
    
    return {
        "jaccard": jaccard,
        "rmse": rmse,
        "emd": emd,
        "relative_error": relative_error
    }

# 对比实验
methods = ["TSIP", "RiseFL", "Clover", "Nebula"]
results = {}

for method in methods:
    protocol = get_protocol(method)
    heatmap = protocol.generate_heatmap(geolife_dataset)
    results[method] = heatmap_accuracy(heatmap, ground_truth)

# 可视化
import matplotlib.pyplot as plt

fig, ax = plt.subplots(1, len(methods), figsize=(20, 4))
for i, method in enumerate(methods):
    ax[i].imshow(results[method]["heatmap"], cmap='hot')
    ax[i].set_title(f"{method}\nJaccard={results[method]['jaccard']:.3f}")
    ax[i].axis('off')

plt.savefig("heatmap_comparison.pdf")
```

---

#### 8.4.3 效率指标

**客户端开销**

```python
def measure_client_overhead(protocol, trajectory):
    """测量客户端计算开销"""
    timings = {
        "top_k": 0,
        "quantization": 0,
        "encryption": 0,
        "proof_generation": 0,
        "total": 0
    }
    
    start = time.time()
    
    # Top-K筛选
    t0 = time.time()
    top_k_indices, top_k_values = trajectory.get_sparse_vector()
    timings["top_k"] = time.time() - t0
    
    # 量化
    t0 = time.time()
    quantized = quantize(top_k_values, bits=4)
    timings["quantization"] = time.time() - t0
    
    # 加密
    t0 = time.time()
    encrypted = protocol.encrypt(top_k_indices, quantized)
    timings["encryption"] = time.time() - t0
    
    # 生成TSIP证明 (TSIP独有)
    if hasattr(protocol, 'generate_tsip_proof'):
        t0 = time.time()
        proof = protocol.generate_tsip_proof(trajectory)
        timings["proof_generation"] = time.time() - t0
    
    timings["total"] = time.time() - start
    
    # 内存占用
    memory_usage = {
        "proof_size": len(proof.to_bytes()) if proof else 0,
        "ciphertext_size": len(encrypted),
        "total_upload": len(encrypted) + timings.get("proof_size", 0)
    }
    
    return timings, memory_usage

# 实验: 在不同设备上测试
devices = {
    "Desktop": {"cpu": "Intel i7", "ram": "16GB"},
    "Laptop": {"cpu": "Intel i5", "ram": "8GB"},
    "Mobile": {"cpu": "Snapdragon 888", "ram": "8GB"}
}

for device_name, device_spec in devices.items():
    print(f"\\n=== {device_name} ({device_spec}) ===")
    
    timings, memory = measure_client_overhead(TSIP(), test_trajectory)
    
    print(f"Total time: {timings['total']*1000:.1f} ms")
    print(f"  - Proof generation: {timings['proof_generation']*1000:.1f} ms")
    print(f"Upload size: {memory['total_upload']/1024:.1f} KB")
```

**服务器吞吐量**

```python
def measure_server_throughput(protocol, num_clients=10000):
    """测量服务器处理能力"""
    # 生成测试数据
    submissions = [
        generate_random_submission() 
        for _ in range(num_clients)
    ]
    
    # 测试验证吞吐量
    start = time.time()
    
    accepted = 0
    for submission in submissions:
        if protocol.verify_submission(submission):
            accepted += 1
    
    elapsed = time.time() - start
    
    throughput = num_clients / elapsed  # submissions/second
    
    return {
        "throughput": throughput,
        "acceptance_rate": accepted / num_clients,
        "avg_latency": elapsed / num_clients * 1000  # ms
    }

# 对比实验
results = {}
for method in ["TSIP", "RiseFL", "Clover"]:
    protocol = get_protocol(method)
    results[method] = measure_server_throughput(protocol)

print("\\n=== Server Throughput ===")
for method, result in results.items():
    print(f"{method:10s}: {result['throughput']:.0f} req/s, "
          f"latency={result['avg_latency']:.1f}ms")
```

---

### 8.5 实验场景设计

#### Experiment 1: 攻击防御能力

**目标**: 验证TSIP能有效检测跨时间窗口攻击

```python
# experiments/exp1_attack_defense.py

def run_attack_defense_experiment():
    """
    实验1: 攻击防御能力
    """
    # 生成不同类型的攻击
    attacks = {
        "Teleport (2x)": generate_teleport_attacks(n=1000, ratio=2.0),
        "Teleport (5x)": generate_teleport_attacks(n=1000, ratio=5.0),
        "Identity Swap": generate_identity_swap_attacks(n=500),
        "Sybil": generate_sybil_attacks(n=100, sybils_per_attacker=10)
    }
    
    # 测试各方案
    protocols = {
        "TSIP": TSIP(),
        "RiseFL": RiseFL(),
        "Clover": Clover(),
        "No Defense": NoDefense()
    }
    
    results = {}
    
    for protocol_name, protocol in protocols.items():
        results[protocol_name] = {}
        
        for attack_name, attack_trajs in attacks.items():
            tpr, fpr = measure_detection_rate(protocol, attack_trajs)
            results[protocol_name][attack_name] = {
                "TPR": tpr,
                "FPR": fpr,
                "F1": 2 * tpr * (1-fpr) / (tpr + 1 - fpr)
            }
    
    # 可视化
    plot_attack_defense_results(results)
    
    return results

# [ARCHIVE] 历史预期模板（非实测）:
# ┌───────────┬──────────┬──────────┬──────────┬──────────┐
# │ Protocol  │ Teleport │ ID Swap  │  Sybil   │ Average  │
# ├───────────┼──────────┼──────────┼──────────┼──────────┤
# │ TSIP      │  99.7%   │  98.5%   │  99.9%   │  99.4%   │
# │ RiseFL    │   0.1%   │   0.0%   │  95.2%   │  31.8%   │
# │ Clover    │   0.0%   │   0.0%   │   5.1%   │   1.7%   │
# │ No Def    │   0.0%   │   0.0%   │   0.0%   │   0.0%   │
# └───────────┴──────────┴──────────┴──────────┴──────────┘
```

---

#### Experiment 2: 隐私-效用权衡

**目标**: 研究不同ε值下的准确度变化

```python
def run_privacy_utility_tradeoff():
    """
    实验2: 隐私-效用权衡
    """
    epsilon_values = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
    
    results = {}
    
    for epsilon in epsilon_values:
        # 配置TSIP
        tsip = TSIP(epsilon_total=epsilon)
        
        # 运行协议
        heatmap = tsip.generate_heatmap(geolife_dataset)
        
        # 评估准确度
        accuracy = heatmap_accuracy(heatmap, ground_truth)
        
        results[epsilon] = {
            "jaccard": accuracy["jaccard"],
            "rmse": accuracy["rmse"],
            "relative_error": accuracy["relative_error"]
        }
    
    # 绘制曲线
    plt.figure(figsize=(10, 6))
    
    plt.subplot(1, 2, 1)
    plt.plot(epsilon_values, [r["jaccard"] for r in results.values()], 
             'o-', label='TSIP')
    plt.xlabel('Privacy Budget ε')
    plt.ylabel('Jaccard Similarity')
    plt.xscale('log')
    plt.grid(True)
    plt.legend()
    
    plt.subplot(1, 2, 2)
    plt.plot(epsilon_values, [r["relative_error"] for r in results.values()], 
             'o-', label='TSIP', color='red')
    plt.xlabel('Privacy Budget ε')
    plt.ylabel('Relative Error')
    plt.xscale('log')
    plt.grid(True)
    plt.legend()
    
    plt.tight_layout()
    plt.savefig("privacy_utility_tradeoff.pdf")
    
    return results
```

---

#### Experiment 3: 可扩展性测试

**目标**: 验证TSIP在大规模场景下的性能

```python
def run_scalability_test():
    """
    实验3: 可扩展性
    """
    # 变量1: 用户数量
    user_counts = [100, 1000, 10000, 100000]
    
    # 变量2: 网格数量
    grid_sizes = [1e4, 1e5, 1e6, 1e7]
    
    results = {
        "user_scaling": {},
        "grid_scaling": {}
    }
    
    # 测试用户数扩展
    for n_users in user_counts:
        dataset = generate_synthetic_data(n_users=n_users, n_grids=1e6)
        
        start = time.time()
        tsip = TSIP()
        heatmap = tsip.generate_heatmap(dataset)
        elapsed = time.time() - start
        
        results["user_scaling"][n_users] = {
            "time": elapsed,
            "throughput": n_users / elapsed
        }
    
    # 测试网格数扩展
    for grid_size in grid_sizes:
        dataset = generate_synthetic_data(n_users=10000, n_grids=grid_size)
        
        start = time.time()
        tsip = TSIP()
        heatmap = tsip.generate_heatmap(dataset)
        elapsed = time.time() - start
        
        results["grid_scaling"][grid_size] = {
            "time": elapsed,
            "memory_mb": measure_memory_usage()
        }
    
    # 可视化
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # 用户数扩展
    ax1.loglog(user_counts, 
               [r["time"] for r in results["user_scaling"].values()],
               'o-', label='TSIP')
    ax1.set_xlabel('Number of Users')
    ax1.set_ylabel('Time (seconds)')
    ax1.grid(True)
    ax1.legend()
    
    # 网格数扩展
    ax2.loglog(grid_sizes,
               [r["memory_mb"] for r in results["grid_scaling"].values()],
               's-', color='red', label='TSIP')
    ax2.set_xlabel('Number of Grids')
    ax2.set_ylabel('Memory (MB)')
    ax2.grid(True)
    ax2.legend()
    
    plt.tight_layout()
    plt.savefig("scalability.pdf")
    
    return results
```

---

#### Experiment 4: 真实数据评估

**目标**: 在GeoLife和T-Drive上评估端到端性能

```python
def run_real_data_evaluation():
    """
    实验4: 真实数据评估
    """
    datasets = {
        "GeoLife": load_geolife(),
        "T-Drive": load_tdrive()
    }
    
    protocols = ["TSIP", "RiseFL", "Clover", "Nebula"]
    
    results = {}
    
    for dataset_name, dataset in datasets.items():
        results[dataset_name] = {}
        
        for protocol_name in protocols:
            protocol = get_protocol(protocol_name)
            
            # 运行协议
            start = time.time()
            heatmap = protocol.generate_heatmap(dataset)
            elapsed = time.time() - start
            
            # 评估
            accuracy = heatmap_accuracy(heatmap, compute_ground_truth(dataset))
            
            results[dataset_name][protocol_name] = {
                "jaccard": accuracy["jaccard"],
                "rmse": accuracy["rmse"],
                "time": elapsed,
                "communication_mb": measure_communication(protocol, dataset)
            }
    
    # 生成对比表格
    print("\\n=== Real Data Evaluation ===")
    print(f"{'Dataset':<12} {'Protocol':<10} {'Jaccard':>8} {'RMSE':>8} {'Time(s)':>8} {'Comm(MB)':>10}")
    print("-" * 66)
    
    for dataset_name in datasets.keys():
        for protocol_name in protocols:
            r = results[dataset_name][protocol_name]
            print(f"{dataset_name:<12} {protocol_name:<10} "
                  f"{r['jaccard']:>8.3f} {r['rmse']:>8.1f} "
                  f"{r['time']:>8.1f} {r['communication_mb']:>10.2f}")
    
    return results
```

---

### 8.6 消融实验

**目标**: 证明TSIP各组件的必要性

```python
def run_ablation_study():
    """
    消融实验: 逐个移除TSIP的组件
    """
    variants = {
        "Full TSIP": {
            "clover": True,
            "risefl": False,  # TSIP替代了RiseFL
            "tsip": True,
            "nebula": True
        },
        "w/o TSIP": {
            "clover": True,
            "risefl": True,   # 回退到RiseFL
            "tsip": False,
            "nebula": True
        },
        "w/o Clover": {
            "clover": False,
            "risefl": False,
            "tsip": True,
            "nebula": True
        },
        "w/o Nebula": {
            "clover": True,
            "risefl": False,
            "tsip": True,
            "nebula": False
        },
        "TSIP only": {
            "clover": False,
            "risefl": False,
            "tsip": True,
            "nebula": False
        }
    }
    
    results = {}
    
    for variant_name, config in variants.items():
        protocol = TSIP_Variant(**config)
        
        # 评估安全性
        attack_detection = measure_attack_detection(protocol, attacks)
        
        # 评估效用
        heatmap = protocol.generate_heatmap(geolife_dataset)
        accuracy = heatmap_accuracy(heatmap, ground_truth)
        
        # 评估效率
        overhead = measure_client_overhead(protocol, test_trajectory)
        
        results[variant_name] = {
            "attack_detection": attack_detection["TPR"],
            "jaccard": accuracy["jaccard"],
            "client_time_ms": overhead["total"] * 1000,
            "communication_kb": overhead["total_upload"] / 1024
        }
    
    # 可视化
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    
    metrics = ["attack_detection", "jaccard", "client_time_ms", "communication_kb"]
    titles = ["Attack Detection Rate", "Utility (Jaccard)", 
              "Client Overhead (ms)", "Communication (KB)"]
    
    for idx, (metric, title) in enumerate(zip(metrics, titles)):
        ax = axes[idx // 2, idx % 2]
        
        values = [results[v][metric] for v in variants.keys()]
        ax.bar(range(len(variants)), values)
        ax.set_xticks(range(len(variants)))
        ax.set_xticklabels(variants.keys(), rotation=45, ha='right')
        ax.set_title(title)
        ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig("ablation_study.pdf")
    
    return results

# [ARCHIVE] 历史预期模板（非实测）:
# - w/o TSIP: 攻击检测率从99%降至1% (关键组件!)
# - w/o Clover: 通信量增加100倍 (稀疏化重要)
# - w/o Nebula: 隐私预算无限 (DP机制必要)
# - TSIP only: 效用低但安全性高 (TSIP是核心创新)
```

---

## 第九章: 论文撰写指南 [ARCHIVE]

> 本章属于写作模板与投稿组织建议，不作为系统“已实现/已证明”证据来源。

### 9.1 论文结构

**标题**:

```
TSIP: Temporal-Spatial Integrity Proofs for 
Privacy-Preserving Location Aggregation

或更吸引人的版本:
Detecting Ghost Trajectories: Zero-Knowledge Proofs 
for Cross-Window Location Integrity
```

**摘要模板** (150-200词):

```
Location-based services aggregate user trajectories to generate 
urban heatmaps while preserving privacy. Existing solutions verify 
individual location reports but fail to ensure temporal-spatial 
consistency, enabling sophisticated attacks where users swap 
identities across time windows or teleport between distant locations.

We present TSIP (Temporal-Spatial Integrity Proof), a novel protocol 
that leverages zero-knowledge proofs to verify trajectory continuity 
without revealing locations. TSIP introduces a commitment chain 
mechanism that cryptographically binds consecutive locations, combined 
with Groth16 zk-SNARKs to prove physical movement constraints. We 
show TSIP provides public-output (ε,δ)-differential privacy with ε=1.0,
and achieves high malicious-trajectory rejection under the continuity
threat model.

Evaluation on GeoLife and T-Drive datasets shows TSIP blocks 99.7% 
of cross-window attacks in our evaluated settings (vs. 0.1% for
state-of-the-art RiseFL) while 
adding second-level client overhead on snarkjs and sub-second proving 
overhead on rapidsnark, with about 2KB communication per submission. 
Communication remains around KB-level in current sparse implementation, 
and we treat communication efficiency as an engineering comparison 
rather than an information-theoretic optimality theorem.
```

---

### 9.2 各章节写作要点

#### Section 1: Introduction

**结构**:

```
1.1 动机 (1段)
  - 位置数据的价值 (城市规划、交通优化)
  - 隐私威胁 (个人追踪、行为分析)

1.2 现有方案的局限 (2段)
  - DP方案: 无完整性保证
  - 完整性验证方案: 仅验证单个时刻
  - 关键盲点: 跨时间窗口攻击

1.3 技术挑战 (1段)
  - Challenge 1: 如何验证时序连续性而不泄露位置
  - Challenge 2: 如何高效处理T个时间窗口
  - Challenge 3: 如何组合完整性与隐私保证

1.4 贡献 (bullet list)
  - [C1] 首次形式化"时空完整性"问题
  - [C2] 提出TSIP协议,结合承诺链与zk-SNARKs
  - [C3] 证明TSIP的连续性安全性与公开输出隐私性，并给出工程通信效率分析
  - [C4] 实现并评估,证明实用性

1.5 论文组织 (简短)
```

**写作技巧**:

- 第一段用具体例子吸引读者
- 用攻击场景激发危机感
- 用"existing work做了A,但无法处理B"的句式过渡

---

#### Section 2: Background

**包含内容**:

```
2.1 差分隐私
  - (ε,δ)-DP定义
  - 组合定理
  - 拉普拉斯机制

2.2 零知识证明
  - zk-SNARK简介
  - Groth16协议
  - 承诺方案 (Poseidon哈希)

2.3 威胁模型
  - 诚实但好奇的服务器
  - 恶意客户端 (Sybil, 身份交换)

2.4 相关工作对比表
```

**注意事项**:

- Background要简洁,不要像教科书
- 只介绍论文中实际用到的技术
- 相关工作表格要突出"我们vs他们"的差异

---

#### Section 3-4: Protocol Design

**组织方式**:

```
3. TSIP Overview
  3.1 High-level idea (配图)
  3.2 Commitment chain机制
  3.3 Distance verification circuit
  3.4 Protocol flow (sequence diagram)

4. Detailed Protocol
  4.1 Setup phase
  4.2 Client submission
  4.3 Server verification
  4.4 Aggregation & DP output
```

**写作建议**:

- 先给直觉(intuition),再给形式化
- 多用图示 (协议流程图、电路示意图)
- 伪代码要简洁,细节放到附录

---

#### Section 5: Security Analysis

**定理顺序**:

```
5.1 Theorem 1: Soundness (最重要)
  - 陈述
  - 证明sketch (主体)
  - 完整证明见附录

5.2 Theorem 2: Privacy
  - 陈述
  - 隐私组合分析
  - 与DP组合定理的关系

5.3 Theorem 3: Zero-Knowledge
  - 陈述
  - 模拟器构造

5.4 Communication Analysis (工程口径)
  - 每次提交通信构成
  - 与基线方案的通信量对比
```

**证明写作技巧**:

- 主体用proof sketch (1-2页)
- 完整证明放附录
- 用Case分析 (攻击者有哪些策略,逐一分析)

---

#### Section 6: Implementation

**内容**:

```
6.1 System architecture
  - Docker部署
  - 各组件实现 (client, shuffler, aggregators)

6.2 Circuit implementation
  - Circom代码统计 (行数、约束数)
  - Setup时间
  - 优化技巧

6.3 Deployment considerations
  - 参数选择 (ε, k, v_max)
  - 可扩展性优化
```

---

#### Section 7: Evaluation

**实验组织**:

```
7.1 Experimental Setup
  - 数据集 (GeoLife, T-Drive, Synthetic)
  - Baselines (RiseFL, Clover, Nebula, Pure LDP)
  - 评估指标
  - 硬件配置

7.2 Attack Defense (Exp 1)
  - 图: 各方案的TPR对比
  - 发现: TSIP TPR=99.7%, RiseFL TPR=0.1%

7.3 Privacy-Utility Tradeoff (Exp 2)
  - 图: ε vs Jaccard
  - 发现: ε=1.0时Jaccard=0.82

7.4 Scalability (Exp 3)
  - 图: 用户数/网格数 vs 时间/内存
  - 发现: 在当前实现中已验证到 1000 用户，后续扩展到更大规模

7.5 Real Data (Exp 4)
  - 表格: 各方案在真实数据上的表现
  - 案例研究: 东京市区热力图

7.6 Ablation Study
  - 图: 移除各组件的影响
  - 发现: TSIP是关键 (移除后TPR降至1%)

7.7 Overhead Analysis
  - 表格: 客户端/服务器开销
  - 发现: snarkjs秒级 prove / rapidsnark亚秒级 prove，通信约2KB
```

**图表建议**:

- 每个实验至少1个图
- 使用对数坐标轴 (scalability实验)
- 标注关键数据点
- 颜色一致 (TSIP总是用蓝色)

---

#### Section 8: Discussion

**包含内容**:

```
8.1 Limitations
  - 需要可信Setup (可用MPC缓解)
  - 假设至少1个服务器诚实
  - 不支持实时查询 (批处理)

8.2 Extensions
  - 多轨迹融合 (汽车+手机)
  - 动态ε调整
  - 联邦学习集成

8.3 Deployment Experiences
  - 与XX公司合作的试点
  - 实际挑战 (网络不稳定、设备异构)
```

---

#### Section 9: Related Work

**分类方式**:

```
9.1 Differential Privacy for Location
  - [Nebula] [GeoMask] ...
  - 对比: 无完整性验证

9.2 Integrity Verification
  - [RiseFL] [VerifyFL] ...
  - 对比: 无时序约束

9.3 Zero-Knowledge Proofs for Privacy
  - [zk-SNARKs应用] ...
  - 对比: 首次用于轨迹验证
```

---

#### Section 10: Conclusion

**结构**:

```
总结贡献 (3句)
  - 形式化了时空完整性问题
  - 提出TSIP协议并证明安全性
  - 实验验证了有效性和效率

Future work (1-2句)
  - 扩展到其他传感器数据
  - 探索更强的威胁模型
```

---

### 9.3 投稿准备

#### 目标会议选择

**Tier 1 (冲刺目标)**:

```
USENIX Security (冬季: 6月截稿, 夏季: 10月截稿)
  - 接受率: ~18%
  - 偏好: 系统+理论结合
  - 审稿周期: 3个月

NDSS (全年滚动)
  - 接受率: ~15%
  - 偏好: 网络安全+隐私
  - 审稿周期: 3-4个月

CCS (春季: 1月截稿, 秋季: 5月截稿)
  - 接受率: ~19%
  - 偏好: 理论创新
  - 审稿周期: 3个月
```

**Tier 2 (保底选择)**:

```
ACSAC
  - 接受率: ~23%
  - 更容易接受应用类工作

ESORICS
  - 欧洲会议,接受率~20%
```

---

#### Timeline建议

**2025年2-9月: 实现与实验** (现在开始)

```
2月: 电路实现 + 基础测试
3月: 协议集成 + 单元测试
4-5月: 完整实验 (4个主实验+消融实验)
6月: 数据分析 + 绘图
7-8月: 论文写作
9月: 内部审阅 + 投稿
```

**投稿窗口（按最新计划更新）**:

- **NDSS 2027 Cycle 2**（目标）
- **USENIX Security 2027 Cycle 1**（备选）

**Rebuttal准备**:

```
预判常见质疑:
Q1: "TSIP只是zk-SNARK的应用,创新性不足?"
A: 我们不仅应用,还形式化了新问题,设计了 continuity 约束协议，并给出系统级安全与隐私分析（通信部分按工程效率分析呈现）

Q2: "实验规模不够大?"
A: 当前主结果已覆盖真实数据与 200/500/1000 规模；更大规模作为下一阶段补充实验

Q3: "可信Setup是个问题?"
A: 可用MPC生成,或换用Plonk (透明Setup)

Q4: "真实部署可行性?"
A: snarkjs路径是秒级，rapidsnark可降到亚秒级；需按部署栈给出实测值而非固定12ms
```

---

### 9.4 开源与复现

**代码仓库结构**:

```
tsip-impl/
├── README.md (详细安装说明)
├── circuits/ (Circom源码)
├── tsip/ (Python实现)
├── experiments/ (实验脚本)
├── data/ (数据集下载链接)
├── docker-compose.yml
├── requirements.txt
└── LICENSE
```

**复现文档要求**:

```
README必须包含:
1. 环境配置 (依赖、版本)
2. 快速开始 (5分钟跑通Demo)
3. 完整实验复现 (逐个实验的命令)
4. 结果示例与通过判据（标注 measured/pending）

artifact-evaluation/
├── INSTALL.md (安装指南)
├── EXPERIMENTS.md (实验步骤)
└── RESULTS.md (预期输出)
```

---

## 总结

本完整设计方案包含:

**Part 1**: 问题定义、零知识证明基础、协议概览
**Part 2**: 详细协议实现、电路代码、系统集成
**Part 3**: 形式化安全证明、攻击防御分析
**Part 4**: 实验评估方案、论文撰写指南 (本文档)

---

## 立即行动清单

### Week 1-2: 环境搭建

- [ ] 安装circom + snarkjs
- [ ] 实现Hello World电路
- [ ] 测试Groth16 prove/verify

### Week 3-4: 核心电路

- [ ] 实现TSIP主电路
- [ ] 单元测试 (正常/异常输入)
- [ ] 性能基准测试

### Week 5-8: 协议集成

- [ ] 客户端实现
- [ ] Shuffler实现
- [ ] 端到端测试

### Week 9-12: 实验评估

- [ ] Experiment 1: 攻击防御
- [ ] Experiment 2: 隐私-效用
- [ ] Experiment 3: 可扩展性
- [ ] Experiment 4: 真实数据

### Week 13-16: 论文写作

- [ ] Section 1-2 (引言+背景)
- [ ] Section 3-4 (协议设计)
- [ ] Section 5 (安全分析)
- [ ] Section 6-7 (实现+实验)
- [ ] Section 8-10 (讨论+相关工作+结论)

### Week 17: 投稿前检查

- [ ] 导师审阅
- [ ] 实验数据复核
- [ ] 代码开源准备
- [ ] 投稿!

---

## 联系与支持

如需进一步讨论:

- 电路实现细节
- 安全证明审阅
- 实验设计优化
- 论文写作建议

随时提问! 祝你顺利发表CCF A!

---

## 附录: 常用资源

**zk-SNARK学习**:

- ZKP MOOC: https://zk-learning.org/
- Circom文档: https://docs.circom.io/
- snarkjs: https://github.com/iden3/snarkjs

**数据集**:

- GeoLife: https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/
- T-Drive: https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/

**相关论文**:

- [Groth16] https://eprint.iacr.org/2016/260.pdf
- [RiseFL] https://www.ndss-symposium.org/ndss-paper/risefl/
- [Nebula] https://dl.acm.org/doi/10.1145/3514221.3517871

**工具**:

- Docker: https://www.docker.com/
- Python科学计算栈: numpy, scipy, matplotlib
- LaTeX模板: https://www.overleaf.com/latex/templates
