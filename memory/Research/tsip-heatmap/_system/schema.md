---
type: schema
project: tsip-heatmap
updated: 2026-07-13
status: active
---

# TSIP Heatmap Knowledge Schema

## Canonical root

`Research/tsip-heatmap/`

## Routing

- `Sources/` 保存本地审计、数据和对话索引等原始依据摘要。
- `Knowledge/` 保存 V4 方法、主张范围和跨 artifact 稳定结论。
- `Experiments/` 保存实验配置、门禁、执行状态和完成判据。
- `Results/Reports/` 保存可引用结果及其 verified/partial 边界。
- `Writing/` 保存论文结构、术语和投稿决策。
- `Daily/` 保存每次同步和诊断检查点，不进入 canonical registry。
- `Archive/` 保存已失效但仍需追溯的笔记。

## Status vocabulary

- `active`：当前维护中的事实或计划。
- `verified`：有直接 artifact receipt 支撑。
- `partial-verified`：部分矩阵通过，但整体完成条件未满足。
- `interrupted`：状态曾为 running，但执行进程已退出且进度停止。
- `planned`：尚未运行。
- `stale`：历史上正确但已被新 artifact 覆盖。
- `archived`：仅供追溯，不应进入当前论文主张。

## Evidence rule

完成状态以 JSON receipt 为主，并结合 PID、mtime、counter 和 container process 交叉核验。聊天文本、健康容器或 stale stdout 不能单独升级实验状态。
