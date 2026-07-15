---
id: exp-001
type: experiment
project: waybill-ruc
status: verified
updated: 2026-07-14
priority: P0
tags: [waybill, v6, policy-binding, security]
---

# M0 — Canonical Policy Binding

## 研究问题

charger 能否只接受由权威 `PolicyProfile` 定义的 tariff、限制和 verification key，即使提交者能任意构造 public statement 与合法 Groth16 proof？

方法决定：[[Knowledge/WayBill-v6方法优化决策]]  
当前缺口：[[Knowledge/WayBill-v5真实状态与证据边界]]  
结果台账：[[Results/Reports/V6方法门禁与实验台账-2026-07]]

## 假设

若 charger 自主解析 billing period 与 jurisdiction，查找 canonical profile，并对所有 policy-derived public signals 做全等比较，同时按 profile 的 vkey fail-closed 验证，则攻击者无法通过自选低 tariff root、低 `r_max`、宽松 cadence/speed/cap 或旧 key 获得可接受的低账单。

## 威胁模型

攻击者可以：

- 控制客户端、public statement、proof inputs 和提交顺序；
- 为任意自选 tariff tree 和公开参数生成密码学上有效的 proof；
- 重放旧 period、旧 profile 或其他 jurisdiction 的 statement；
- 利用 charger 配置缺失、version rollback 或 vkey fallback。

暂不声称抵抗：policy authority 私钥失陷、charger 本机完全失陷、被假设可信的 measurement source 私钥失陷。它们必须在论文 limitation 中单列。

## 设计变化

### PolicyProfile SSOT

至少包含：

- `jurisdiction_id`, `profile_version`, `valid_from`, `valid_to`, `revoked_at`, `min_accepted_version`；
- `tariff_root`, authority-certified `max_zone_rate`；
- `cadence_sec`, `max_dt`, `tier_vmax`, `mode_vmax`, `cap_policy_hash`；
- `circuit_id`, `verification_key_hash`；
- `currency`, fixed-point scale, rounding mode, overflow policy；
- `monthly_reconciliation_rate` 和 fallback semantics version。

定义 canonical serialization、domain separator 与 `policy_profile_commitment`。profile 文件和生成器共同构成 authority SSOT，不能从用户 statement 反推 expected profile。

### Charger acceptance relation

1. 从认证设备、jurisdiction 与 period 解析 expected profile。
2. 拒绝未知、过期、未生效、撤销或低于 anti-rollback floor 的 profile。
3. 逐字段比较 statement public signals 与 expected profile。
4. 校验 statement 的 profile commitment。
5. 只加载 `verification_key_hash` 对应的 key；缺失或 hash 不符立即拒绝。
6. 验证 measurement root attestation、proof、statement commitment、period freshness 和 replay state。
7. 只有所有步骤通过才进入结算接受状态。

measurement attestation 绑定设备、period、measurement log root 与单调序号，不让 measurement authority 定义 tariff。

## 实验矩阵

### 正向用例

- canonical active profile + canonical vkey + valid measurement root + valid proof；
- profile version rollover 的边界前后；
- 合法 jurisdiction 切换且每个 period 只使用对应 profile；
- authority 生成的 tariff root 与 `r_max` 一致性检查。

### 负向用例

每个用例都生成内部一致且密码学有效的 proof，然后确认 charger 拒绝：

| Attack ID | 仅修改项 | 预期 |
|---|---|---|
| P-ROOT | 私有低费率 tariff root | reject |
| P-RMAX | 低报 `max_zone_rate` | reject |
| P-CAD | 放宽 cadence / `max_dt` | reject |
| P-SPEED | 放宽 tier/mode `v_max` | reject |
| P-CAP | 更换 cap policy | reject |
| P-ARITH | 更换定点、舍入或 currency | reject |
| P-VKEY | 使用未知、旧版或 hash 不符 vkey | reject |
| P-NOKEY | charger 未配置 expected vkey | reject |
| P-OLD | 回滚到已过期或低于 floor 的 profile | reject |
| P-REVOKE | 使用已撤销 profile | reject |
| P-XJUR | 跨 jurisdiction 重放 | reject |
| P-REPLAY | 重复提交已结算 device-period | reject/idempotent without double credit |

## 固定变量

- 同一 measurement log 和真实账单；
- 同一 circuit source 与 proof system；
- 每个负测只改变一个 policy 或生命周期条件；
- charger 运行在同一配置与数据库快照上。

## 指标

- canonical 正向用例接受率；
- 每类攻击拒绝率；
- fail-open 次数；
- profile lookup、proof verification 和总请求延迟；
- registry/version/revocation coverage；
- statement ↔ profile 字段差分覆盖率。

## 硬门槛

- 正向用例 100% 接受。
- 上表所有负向用例 100% 拒绝，fail-open 为 0。
- vkey 缺失或 hash 不符时服务不能降级到“跳过验证”。
- 所有 policy-derived public signals 都有至少一条单字段 mutation test。
- authority profile 构建时验证 `r_max = max(tariff leaves)`，或由同一可审计生成过程同时产出 root 与 maximum。
- 同一 device-period 不发生重复结算；合法 retry 的语义明确且有测试。
- profile schema、commitment test vectors 和攻击 receipt 可从干净环境复现。

任一安全负测被接受，M0 状态为 `failed`，M1/M2 结果不得用于“权威结算安全”主张。

## 执行结果（2026-07-14）

### 门禁判定

M0 在已声明威胁模型内为 **verified**。判定 SSOT 是
`experiments/waybill_m0/v1/summary.json`；该文件记录
`status=verified`、`hard_gate_passed=true`，并由
`experiments/waybill_m0/v1/acceptance_receipts.jsonl` 保存逐例 receipt。

| 检查 | 实测结果 | 判定 |
|---|---:|---|
| canonical 正向提交 | 1/1 accepted | pass |
| 单因素攻击矩阵 | 12/12 rejected | pass |
| fail-open | 0 | pass |
| 提交 proof 的独立验证 | 全部有效 | pass |
| canonical / 私有低 tariff 账单 | 12000 / 2400 cents | 攻击具备经济动机，但 charger 拒绝私有 policy |

- canonical profile commitment 为
  `21150643352738071342383300823421096337243216680434872497268001051641820180147`；
  汇总 receipt SHA-256 为
  `f409b6f65247c51d2f0de62e9baa0237976cd8e39bba32918d608005087e8858`。
- profile schema、canonical serialization/test vectors、canonical tariff 与 vkey
  均位于 `configs/settlement_policy_profiles/`；运行环境绑定保存在
  `experiments/waybill_m0/v1/environment_manifest.json`。
- 负测覆盖低 tariff root、低 `r_max`、放宽 cadence/speed/cap、算术策略替换、
  vkey 缺失/错配、版本回滚、撤销、跨 jurisdiction 与 replay；这些 proof 本身
  有效，因此拒绝来自 canonical policy acceptance relation，而非无效 proof。

### 证据边界与主张降级

- `verified` 只表示本卡威胁模型和固定攻击矩阵通过，不表示 policy authority
  私钥、measurement source 私钥或 charger 主机失陷后仍安全。
- M0 不单独证明 odometer/位置物理真实性，也不把后续 M1/M2 的实验 profile
  自动提升为现实部署 policy。
- 若 SSOT 重新运行后 `hard_gate_passed` 不再为真，或任一安全负测被接受，
  本卡必须立即降级为 `failed`，且不得用 M1/M2 支撑“权威结算安全”主张。

## Artifact 清单

- `configs/settlement_policy_profiles/`：canonical profiles、authority ID、profile
  commitment 与 SHA-256；当前 artifact **不含** authority digital-signature chain，
  因而不能据此声称 profile 发布签名链已实现；
- profile schema、canonical serialization 和 commitment test vectors；
- charger acceptance truth table；
- mutation-test JSON/CSV；
- proof/vkey/profile hashes；
- 运行环境和命令 manifest；
- 汇总写入 [[Results/Reports/V6方法门禁与实验台账-2026-07]]。

## 停止与升级规则

- 先用现有 V5 circuit 证明 policy pinning 的 acceptance semantics，再把 commitment 接入 V6 relation；不要同时修改 fallback 导致归因不清。
- 若字段数量过多导致 public inputs 扩张，优先公开单一 `H(P)` 并由 charger 比对，但 circuit 内使用的每个 policy value仍必须被 commitment 约束。
- 只有攻击矩阵全绿后，M0 从 `planned` 升为 `verified`。
