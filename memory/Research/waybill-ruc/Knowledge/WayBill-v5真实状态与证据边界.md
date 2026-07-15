---
id: knowledge-001
type: knowledge
project: waybill-ruc
status: verified
updated: 2026-07-13
tags: [waybill, v5, evidence-boundary]
---

# WayBill V5 真实状态与证据边界

## 结论

WayBill V5 已有可运行的方法骨架和多组评估资产，但尚不具备直接投稿所需的安全语义、公平性和规模证据。当前最准确的状态是：**核心架构可继承，关键方法门禁未关闭，论文仍是骨架**。

依据：[[Sources/Docs/WayBill外部审阅报告-2026-07-13]]、[[Sources/Docs/WayBill当前仓库审计-2026-07-13]]。

## 已有且可复用

- period settlement circuit、public statement 和 charger 接收路径已形成端到端骨架。
- 正常定位路径已使用 odometer distance 与 zone rate，为统一 distance semantics 提供基础。
- E2 已覆盖多个数据集和 outage/fallback trade-off，可作为 V5 对照。
- E3 已有 bucket solver 和 100 m/50 m 敏感性结果，可作为严格求解器的 warm start 与回归集。
- E5 已暴露精确匿名性不足，能作为更现实隐私攻击的基线。
- 现有 statement commitment 可演进为 policy profile commitment，无需从零重写全部协议。

## 当前不能支撑的主张

| 主张 | 当前证据 | 判断 |
|---|---|---|
| proof 遵循权威 tariff policy | proof 与用户 statement 一致，但 charger 未逐字段 pin 权威 profile | 不成立，M0 阻断 |
| fallback 同时 revenue-safe 且对诚实用户公平 | `Δt × v_max × r_max` 在 dwell-heavy gap 上产生极端 surcharge | 不成立，M1 阻断 |
| 可直接支持约 10,000 个城市 tariff cells | 当前 depth 8 / 256 leaves / 25 fixes | 不成立，M2 阻断 |
| E3 给出形式化攻击上界或最优攻击 | 有 bucket sensitivity，无 relaxation proof / gap | 只能称敏感性或可行攻击证据 |
| OSNMA 等于物理位置真实性 | 只认证导航消息语义 | 过强，必须收缩 |
| pool size 等于有效匿名性 | exact anonymity median 1，少量 opening 可强去匿名 | 不成立 |
| 已有完整可投稿论文 | `WayBill/main.tex` 是 5 页占位骨架 | 不成立 |

## 三层事实源

### 规范事实

未来只以 V6 `PolicyProfile`、fallback 公式 SSOT 和 threat model 为规范事实。legacy 设计文档只用于追溯 V5。

### 实现事实

当前实现事实以 circuit 和 charger 为准。特别是：fallback 仍为时间型，proof-only charger 尚未显示完整 authority-policy pinning。

### 结果事实

已有 CSV/设计文档数字可用于选择下一实验，但在统一脚本、配置 manifest 和 receipt 完成前，不升级为最终论文数字。

## 已解决的记录冲突

- “只差写作”被降级为 stale historical judgment。
- “城市规模”被拆分为算法可以参数化与 depth-14 真实 proof 已完成；目前只有前者有希望，后者尚未证明。
- “E3 upper bound”被改写为 bucket-based sensitivity / candidate bound，直到 M3 给出合法 relaxation。
- “trusted GNSS”被改写为 conditional attested measurement source，不再把消息认证等同于物理真实性。

## 当前证据等级

- V5 架构存在：verified（静态代码与文档一致）。
- fallback 公平性问题：verified（公式与现有数据同时支持）。
- canonical policy 缺口：verified static finding；攻击利用仍需 M0 负测 receipt。
- depth-14 可行性：unknown / planned。
- E3 全局 bound：unknown / planned。
- V6 收益与公平保证：planned。

## 对下一步的约束

下一次代码或实验迭代必须从 [[Knowledge/WayBill-v6方法优化决策]] 和四张实验卡出发。不得仅修正文、继续增加小规模性能表，或用更强措辞包装 V5 现有结果。
