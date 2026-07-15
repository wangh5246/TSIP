---
type: schema
project: waybill-ruc
updated: 2026-07-13
status: active
---

# WayBill / RUC Knowledge Schema

## Canonical root

`Research/waybill-ruc/`

## Routing

- `Sources/Docs/`：保存外部审阅与仓库审计的可追溯摘要；原文件路径作为普通文本，不作为跨项目 wikilink。
- `Knowledge/`：保存从来源提炼的稳定判断、证据边界和已批准方法决策。
- `Experiments/`：保存假设、变量、门禁、停止条件和 artifact 要求；不把计划状态写成结果。
- `Results/Reports/`：保存 V5 已核验证据和 V6 门禁台账；只有直接 artifact 支撑才升级为 verified。
- `Writing/`：保存论文主张、术语、结构和 claim-evidence 约束。
- `Daily/`：保存同步检查点，不进入 canonical registry。
- `Archive/`：保存已失效但需追溯的 canonical note；当前 legacy `memory/TSIP_RUC/` 不迁移、不改写。

## Status vocabulary

- `active`：当前维护中的来源、知识或写作决策。
- `planned`：实验设计和门禁已定义，但尚无完成证据。
- `running`：执行进程和 receipt 均表明正在运行。
- `partial-verified`：部分事实已由 artifact 核验，但整体门禁未通过。
- `verified`：所有完成条件均有可复查 artifact 支撑。
- `failed`：门禁明确失败，并已记录失败证据和主张降级。
- `stale`：历史上曾适用，但已被新证据覆盖。
- `archived`：仅供追溯，不应进入当前主张。

## Evidence rules

- 安全性质必须同时有威胁模型、正向测试和攻击负测。
- cryptographic scale 必须有真实 witness/prove/verify receipt；constraint count 不能代替证明成功。
- 优化“上界”必须有合法松弛论证；“最优”必须报告 gap 或证书。
- sensor authenticity 必须精确到被认证的对象，不把导航消息、接收机输出和物理位置混为一谈。
- 论文数字只能来自 Results 中标明 artifact 路径与状态的记录。
