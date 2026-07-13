---
type: project-hub
project: tsip-heatmap
updated: 2026-07-14
status: active
tags: [tsip-heatmap, hub, v4]
---

# TSIP Heatmap V4 项目 Hub

## 项目摘要

本项目研究面向私有热力图聚合的有状态隐藏轨迹与载荷一致性。当前 V4 方法把 accepted predecessor、轨迹包络、隐藏 primary 推导和 same-primary payload/route binding 放入同一 Groth16 admission relation，并将安全主张限定为准入一致性，不把它表述为轨迹真实性、来源认证或完整部署安全。

## 当前状态

- V4 静态与 Route-B/C21 门禁为 22/22 通过。
- 五数据集 Docker clean protocol smoke 为 5/5 通过。
- N=1000、五数据集、三种子固定公平效用比较已完成，V4 proposed 在五个数据集上均优于最强基线 Nebula，honest FRR 为 0。
- V4 paper-scale cryptographic matrix 为 5 数据集 x 3 seeds x 16 rounds，共 15 个单元；2026-07-13 23:24:37 +0800 已完成 15/15，launcher receipt 为 pass、failed units 为 0。
- 15/15 只确认执行矩阵完成；论文级 latency/throughput 仍需 strict aggregate builder 验证全部 unit hashes、16-round contract 与 manifest/launch binding。

## 当前焦点

- 按 `docs/superpowers/specs/2026-07-13-tsip-heatmap-tdsc-revision-design.md` 执行 TDSC 分阶段证据驱动修订。
- Pre-scale 已完成 Git 保全、artifact 一致性、摘要、五数据集固定效用、合规门、18 页 clean build 与 adversarial self-review；科学证据只剩 CE23 strict scale aggregate 未关闭。
- 不再启动 scale launcher；保留 15 个 pass receipts，运行 strict aggregate builder 后才更新 RQ6 性能数字。
- 区分 [[Experiments/V4-Docker-N1000完整实验]]、旧版 full N=1000 RQ suite 和简单 Docker sanity run，避免证据混用。
- 用 [[Knowledge/V4方法与证据边界]] 约束论文措辞。
- 根据 [[Writing/论文修订与投稿决策]] 复核当前主稿，而不是沿用早期聊天中的页数或术语判断。

## 下一步动作

1. 实现并用测试锁定 strict aggregate builder，对 15 个单元逐一 fail closed 验证。
2. 核验每单元 16 轮、15,000 proofs、proof failures=0、evaluation reconstruction/DP 全通过，生成 aggregate JSON/CSV/LaTeX。
3. 将 strict aggregate 的 manifest/launch/unit hashes 绑定进 `paper_evidence.json`。
4. 只有 aggregate receipt 为 verified 时才更新 [[Results/Reports/V4实验结果-2026-07]] 并把最终 scale 数字接入论文。

## 重要链接

- [[01-Plan]]
- [[02-Index]]
- [[Knowledge/V4方法与证据边界]]
- [[Experiments/V4-Docker-N1000完整实验]]
- [[Results/Reports/V4实验结果-2026-07]]
- [[Writing/论文修订与投稿决策]]
- [[Sources/Notes/Codex对话同步审计-2026-07-13]]
- [[Daily/2026-07-13]]

## 最近重要变化

- 2026-07-14 Task 9 对抗自审及 Obsidian 基线已提交为 `a0db10db`。
- 2026-07-14 Task 9 五维对抗自审完成：27 claims = 17 supported + 7 analytical + 2 assumption + 1 partial + 0 unsupported；169 tests 通过，唯一 partial 是 CE23 strict scale。
- 2026-07-14 删除 MDS/EETS 治理类比过强的支撑作用，将 HBC/非合谋明确为管理域分离、访问记录与审计的部署假设。
- 2026-07-13 23:24 +0800 N=1000 scale launcher 正常结束，15/15 单元 pass、failed=0；性能统计仍等待 strict aggregate。
- 2026-07-13 Task 7 已建立五数据集 DATA_NOTICE、artifact guide、citation audit 与作者确认门；仓库 license 明确阻塞，未猜测或创建 LICENSE。
- 2026-07-13 19:37 +0800 新续跑处于活跃计算：13/15 已通过，Rome/303 与 Synthetic/303 各 2/16；不再适用“无进程、先 compose down”的旧操作。
- 2026-07-13 用户批准 TDSC 修订规格；pre-scale 与 final-scale 实施计划已通过静态自审并提交为 `ed4d2f86`，等待执行方式选择。
- 2026-07-13 确认 TDSC 为唯一目标并批准方案 A；修订设计已提交为 `c6243a02`。
- 2026-07-13 当前稿审计发现摘要约 247 词、PDF 为 7 月 7 日旧 17 页产物、`main.tex` 处于索引删除加未跟踪重建状态。
- 2026-07-13 区分 14-input archive compatibility circuit 与 manifest-bound 16-input paper circuit；论文旧 3,056/14/23 数字待统一。
- 2026-07-13 核验 V4 大规模矩阵实际为 13/15，两个 seed 303 单元中断而非继续计算。
- 2026-07-10 T-Drive/101 N=1000 pilot 完成 16 轮和 15,000 次证明验证，零证明失败。
- 2026-07-10 V4 静态、Docker smoke、三种子效用门禁和 publication heatmap 全部通过。
- 2026-07-09 恢复并优化独立 V4 circuit/source，完成五数据集输入和 N=1000 执行器。

## Important Links
- [[01-Plan]]
- [[02-Index]]
- [[_system/registry]]
- [[Daily/2026-07-14]]

## Recent Changes
- 2026-07-13T16:39:29Z: sync refreshed scaffold, registry, index, and daily note (tdsc-final-scale-task2-precommit).
- 2026-07-13T16:37:42Z: sync refreshed scaffold, registry, index, and daily note (tdsc-final-scale-task2-aggregate-fix).
- 2026-07-13T16:35:54Z: sync refreshed scaffold, registry, index, and daily note (tdsc-final-scale-task2-aggregate).
- 2026-07-13T16:20:48Z: sync refreshed scaffold, registry, index, and daily note (tdsc-final-scale-task1-complete).
- 2026-07-13T16:19:21Z: sync refreshed scaffold, registry, index, and daily note (tdsc-pre-scale-revision-task9-commit).
- 2026-07-13T16:18:16Z: sync refreshed scaffold, registry, index, and daily note (tdsc-pre-scale-revision-task9).
- 2026-07-13T16:09:21Z: sync refreshed scaffold, registry, index, and daily note (tdsc-pre-scale-revision-task8-commit).
- 2026-07-13T16:06:40Z: sync refreshed scaffold, registry, index, and daily note (tdsc-pre-scale-revision-task8).
