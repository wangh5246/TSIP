---
id: exp-003
type: experiment
project: waybill-ruc
status: verified
updated: 2026-07-14
priority: P0
tags: [waybill, v6, merkle-tree, scalability, groth16]
---

# M2 — Tariff 树深度与 Fix 规模

## 研究问题

V6 settlement relation 能否在至少 10,000 tariff cells 的城市规模 profile 上完成真实 witness、Groth16 proof 和 verification，并给出随 fixes 增长的可复现资源曲线？

方法决定：[[Knowledge/WayBill-v6方法优化决策]]  
V5 差距：[[Results/Reports/V5证据快照与审阅差距-2026-07]]  
V6 台账：[[Results/Reports/V6方法门禁与实验台账-2026-07]]

## 假设

Merkle depth 从 8 增加到 14 会线性增加每个 fix 的 membership 成本，但在固定 V6 relation 和声明硬件上仍可完成真实 proof。fixes 增长应给出可解释、近线性的 constraints 与时间趋势；不能以编译成功替代证明可执行。

## 容量语义

| Depth | Leaf capacity | 解释 |
|---:|---:|---|
| 8 | 256 | V5 prototype |
| 12 | 4,096 | 中等区域 |
| 14 | 16,384 | 可直接覆盖约 10,000 cells |
| 16 | 65,536 | 扩展压力测试 |

真实 tariff artifact 必须记录 cell 数、padding 规则、leaf ordering、empty leaf value、hash domain 和 root，不允许只把同一 256-leaf tree 补零后称城市数据。

## 变量

### 自变量

- tree depth：8、12、14、16；
- fixes per proof：25、50、100、200；
- profile：V5-compatible relation 与冻结后的 V6 relation；
- 可选 backend/hardware 仅作为单独 ablation，不混入主表。

### 固定变量

- proof system、curve、compiler/snark tool versions；
- circuit source commit/worktree hash；
- tariff leaf encoding 与 hash；
- witness 数据分布、public inputs 和 randomness protocol；
- CPU/GPU、线程、内存限制和热身策略。

## 执行矩阵

### Phase A — 静态与编译矩阵

对 16 个 depth × fixes 配置：

- compile；
- constraint count；
- R1CS/WASM 大小；
- trusted setup/key generation 时间与峰值内存；
- verification-key/proving-key 大小。

### Phase B — 真实 proof gate

- depth 14 × fixes 25/50/100/200 全部执行 witness/prove/verify；
- 每个配置至少 1 次 warm-up + 3 次独立测量；
- depth 8 用作回归基线；
- depth 16 资源允许时执行，失败也保留阶段、时间和资源 receipt。

### Phase C — tariff artifact 真实性

- 构建或导入至少 10,000 个非空/有效 cell 的 tariff；
- 独立重算 root；
- 随机 membership paths 和边界 leaf 验证；
- 证明输入实际引用该 artifact，而非 prototype root。

## 指标

- constraints、non-linear constraints；
- compile/setup/witness/prove/verify p50 与 P95；
- 峰值 RSS、可用时报告 VRAM，否则明确 N/A；
- R1CS/WASM/proving key/verification key/proof size；
- proofs/hour、失败率、timeout/OOM 阶段；
- 每 fix 与每 depth level 的边际成本。

## 正确性检查

- 所有 valid proof 必须 verify；
- 修改任一 tariff leaf、path、root、profile commitment 或 bill 后 verification 失败；
- 同一 artifact 的 root 由两个独立实现重算一致；
- fixes padding 不产生虚构收费或跳过真实 fix；
- depth wrapper 与实际 path length 一致；
- public profile 的 circuit ID/vkey hash 与运行 artifact 一致。

## 硬门槛

- 16 个配置均有 compile/constraint receipt；资源失败必须留下结构化 failure receipt。
- depth 14 × fixes 25/50/100/200 全部完成至少 3 次真实 witness/prove/verify，验证失败率为 0。
- 至少 10,000-cell tariff artifact 的 root 与 membership 被独立复核。
- 主表报告 p50/P95、内存、key/proof size 和 throughput，不只给一次 wall-clock。
- clean environment 可用 manifest 复跑关键 depth-14 profile。

若只完成 depth 14 × 25，可写“relation supports a city-sized tariff domain in a small batch”，不能写支持 100/200 fixes。若 depth 14 无真实 proof，则 M2 为 `failed`，删除城市规模 deployability。

## 验证结果（2026-07-14）

- 16/16 depth × fixes 配置已真实编译并产生 constraint receipt；depth-14 的
  25/50/100/200 fixes 分别为 275,538 / 558,288 / 1,123,788 / 2,254,788
  constraints。完整 compile 时间、峰值 RSS、R1CS/WASM 大小位于
  `experiments/waybill_m2/circuit_matrix/receipts/compile/`。
- depth-14 tariff artifact 包含 cell 0..9999，共 10,000 个真实有效 leaf，容量
  16,384，repeat-last padding 6,384；root 为
  `13699623093631692182889334311784675380256108557104408704717957921466979708714`。
  primary/independent Poseidon 重算一致，4 个边界与 8 个固定 seed membership sample
  全部验证通过。
- tariff 的 5/10/12 只保留公开 Rome 停车小时费率的比例，属于容量/provenance
  实验用 dimensionless normalized tiers；不是现实 RUC、不是 cents/m，不得作为账单
  金额引用。
- 16/16 配置均完成真实 Groth16 setup，`setup_ready=16`、`setup_failed=0`。非
  depth-14 的 12 份大型临时 zkey 在记录 bytes/hash 并导出 vkey 后清理；四份
  depth-14 zkey 保留并通过完整 `snarkjs zkey verify`。最后一项 depth-16 × 200 fixes
  setup 用时 1,345,908 ms、峰值 RSS 4,500,733,952 bytes。
- depth-14 × 25/50/100/200 fixes 各完成 1 次 warm-up + 3 次独立实测，12/12
  measured proofs 在最终汇总后再次由终端验证成功，负向 tariff/profile/bill/path
  篡改全部拒绝。主性能如下：

| Fixes | E2E P50 (ms) | E2E P95 (ms) | P50 proofs/hour |
|---:|---:|---:|---:|
| 25 | 10,375.989 | 11,064.110 | 346.955 |
| 50 | 23,910.473 | 31,681.634 | 150.562 |
| 100 | 57,673.586 | 66,127.585 | 62.420 |
| 200 | 177,866.717 | 387,336.828 | 20.240 |

- 官方 power-22 phase-2 参数精确大小为 4,831,921,304 bytes，BLAKE2b 为
  `0d64f63dba1a6f11139df765cb690da69d9b2f469a1ddd0de5e4aa628abb28f787f04c6a5fb84a235ec5ea7f41d0548746653ecab0559add658a83502d1cb21b`；
  PTAU receipt、当前 R1CS/WASM、setup/vkey/profile/input/proof 哈希链均进入硬门禁。
- 最终 `summary.json` 为 `m2_hard_gate_passed=true`，SHA-256
  `b5b996c9f54a4ba9dd93bed805390f11e615e412e130109ee183cb100dc78f2e`；终端验证
  receipt SHA-256 为
  `aad8180f75179f5907662aa55bc9e253efd23f14c7553773e44fa7c94b1e3a54`，run ID 为
  `573a965852fda4311f86bcd5d123a9af8782aa43ff82bb1f75a7f82bef5b2f22`。
- 本门禁只解锁“normalized-test-unit 容量基准在 depth-14 × 200 fixes 可执行”；
  不构成现实 Rome 计费、可信设置生产贡献或 production-security certification。

## 计划 artifact

- parameterized circuit profiles 和 generated wrappers；
- 16-config manifest；
- compile/setup/prove/verify JSONL receipts；
- hardware/software environment manifest；
- 10,000+ cell tariff manifest/root；
- aggregate CSV 与 scaling plots；
- 汇总写入 [[Results/Reports/V6方法门禁与实验台账-2026-07]]。

## 停止与分支规则

- 单配置 timeout/OOM 后记录峰值与阶段，最多按预注册资源上限重试，不无限放大机器掩盖设计问题。
- 若 depth 是主要瓶颈，再立项 tiled/sparse tariff；该分支必须有新的 commitment semantics 和攻击分析。
- 不在本实验同时引入 IVC/folding，避免把 core relation 的规模问题与新 proof system 混合。
