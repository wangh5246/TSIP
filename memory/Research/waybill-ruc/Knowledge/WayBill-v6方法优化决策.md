---
id: knowledge-002
type: knowledge
project: waybill-ruc
status: active
updated: 2026-07-13
decision: approved
tags: [waybill, v6, method, decision]
---

# WayBill V6 方法优化决策

## 决策摘要

已批准采用 **方案 A：security-first V6**。V6 的核心不是增加更多外围实验，而是把 proof 的语义改成：

> 对权威 policy profile、被明确限定能力的测量 attestation、单调里程结算和可审计 fallback 规则，证明账单计算正确；任何 profile 缺失、降级或不一致均 fail closed。

依据：[[Sources/Docs/WayBill外部审阅报告-2026-07-13]]、[[Sources/Docs/WayBill当前仓库审计-2026-07-13]]。

## 为什么先做 M0

fallback、公平性和规模都重要，但如果 tariff root、`r_max`、cadence、速度上限或 vkey 可由提交者影响，那么 proof 只是在证明一个攻击者自选世界中的一致性。此时即使电路零知识、性能良好，也不能推出权威结算正确。因此依赖顺序固定为：

`canonical policy binding → odometer fallback → city-scale proof / certified E3 → deployment/privacy/writing`

## V6 方法结构

### 1. Authority-controlled PolicyProfile

定义：

`P = (jurisdiction, version, validity, tariff_root, r_max, cadence, max_dt, speed_policy, cap_policy, circuit_id, vkey_hash, arithmetic_policy, reconciliation_policy)`

由政策 authority 签名或由 charger 的受控 registry 固定。proof public inputs 包含 `profile_id` 或 `H(P)`；charger 自己查找 `P_expected`，而不是相信提交者给出 expected values。

关键不变量：

- proof 的 tariff membership root 等于 `P_expected.tariff_root`；
- outage 所用 `r_max` 等于 authority 对该 tree 发布的真实 maximum；
- cadence、`max_dt`、速度和 caps 等限制逐字段相等；
- proof 由 `P_expected.vkey_hash` 对应的 key 验证；
- profile 处于当前 billing period 的有效窗口且未撤销、未回滚。

### 2. Measurement log 与 price policy 分离

测量 attestation 只负责：device、period、log root、单调 sequence、timestamp/odometer 以及被明确支持的 position-valid evidence。它不能替代 policy authority，也不自动证明物理轨迹真实。

论文的安全定理必须写成条件式：若 measurement source 满足所列不可伪造、单调与误差假设，且 policy registry 正确，则结算性质成立。

### 3. Odometer-backed monotone settlement

设月度可信里程变化为 `ΔO`，已被 period proofs 覆盖的里程为 `A`：

`B_accept = Σ_valid Δo_i r(z_i) + Σ_outage Δo_j r_max + max(0, ΔO - A) r_max`

其中：

- `Δo` 必须非负、范围合法、单位固定，并处理维修重置与回绕；
- outage 不再从时间和最大速度推导虚构距离；
- reconciliation 只收费未覆盖里程，避免 double count；
- 月度 attestation 缺失进入行政 exception，不能静默记零。

### 4. 两侧保证

令 `B_true` 是按真实距离和真实 tariff 计算的基准账单，`ε_o` 汇总里程标定、量化与可信来源误差，`ε_a` 汇总定点和舍入误差。

Revenue Soundness 的目标形式：

`B_accept ≥ B_true - r_max ε_o - ε_a`

成立范围必须明确排除物理传感器被攻破等超出假设的情况。

Honest-user Fairness 的目标形式：

`B_accept ≤ B_true + Σ_outage Δo_j (r_max - r_true,j) + r_max ε_o + ε_a`

该式揭示 outage premium 可能仍大，因此还要报告实际 median/P95，不把 worst-case bound 写成体验良好。

关键性质：停车时 `Δo=0`，fallback fee 为 0；在 canonical `r_max` 与可信 odometer 条件下，隐瞒 position 不会降低收费。

### 5. 城市规模 relation

把 depth 与 fixes 做成 profile 参数或经审计的 circuit variants。城市规模主张以 depth 14 的真实 proof receipt 为门槛，不以 256-leaf prototype 外推。

### 6. Certified attack evaluation

E3 将攻击最大化问题拆成：

- 一个满足原约束的 feasible solution，给最大攻击值的 lower bound；
- 一个包含原可行域的 relaxation，给 upper bound；
- `gap = upper - lower` 与 relative gap。

bucket 只是一种离散化工具。若 bucket refinement 没有集合包含关系或误差证明，就只能报告 sensitivity。

## 可选增强：ρ-robust tariff envelope

候选定义：对每个 cell，把费率改成位移半径 `ρ` 内所有可能 cell 的最高费率：

`r_ρ(c) = max_{dist(c,c')≤ρ} r(c')`

若攻击只能把真实位置移动到 `ρ` 邻域，该 envelope 可阻止通过局部跨 tariff 边界降费，而且只需替换 authority 发布的 tariff root，不必显著增加 membership 电路结构。

但它会对边界附近诚实用户产生 overcharge，因此目前仅作为 M3 后的条件分支。进入主方法前必须同时满足：

- bounded-displacement 定理完整；
- envelope root 由 authority 生成并纳入 M0 profile；
- 真实 tariff 上的诚实 surcharge median/P95 可接受；
- 与更细 map matching 或软边界方案对比。

## 方案取舍

### 已选方案 A：安全优先、增量升级

保留 V5 架构和实验资产，先修语义缺口，再替换 fallback 和补规模/solver 证据。优点是问题可分解、每步有负测和门禁，且不会把未验证硬件纳入核心贡献。

### 未选方案 B：全面可信硬件重构

把 receiver、odometer、secure element、TEE 和远程证明统一重做。潜在部署故事更完整，但依赖特定硬件、周期长，且无法自动解决 policy pinning 与 solver 证据。

### 未选方案 C：保守投稿救援

仅收缩主张、补写作与小实验。可以减少工作量，但 canonical policy、fallback 公平性和城市规模三个核心缺口仍会被审稿人直接击穿。

## 论文贡献候选（门禁通过后）

1. policy-bound private road-use charging relation：proof 与权威价格、限制和 verification profile 绑定；
2. odometer-backed monotone fallback：消除 dwell-time 虚构距离，并给收益安全与诚实公平的两侧界；
3. city-scale verified evaluation：depth-14 真实证明与 certified attack bounds；
4. 可选的 robust tariff envelope：仅在理论与诚实成本均通过时加入。

这些是候选贡献，不在实验门禁通过前写成既成结果。

## 方法冻结点

- M0 profile schema 和 threat model 通过负测后冻结公开字段。
- M1 公式、单位、rounding 和 reconciliation 通过 SSOT 差分测试后冻结算术接口。
- M2 使用冻结接口做 circuit profile matrix。
- M3 在账单真值和攻击模型冻结后才能报告 certified gap。

执行细节见 [[01-Plan]] 和 [[Experiments/M0-Canonical-Policy-Binding]] 至 [[Experiments/M3-E3求解器收敛与界]]。
