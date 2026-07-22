---
type: project-hub
project: tsip-heatmap
updated: 2026-07-22
status: active
tags: [tsip-heatmap, hub, v4]
---

# TSIP Heatmap V4 项目 Hub

## 项目摘要

本项目研究面向私有热力图聚合的有状态隐藏轨迹与载荷一致性。当前 V4 方法把 accepted predecessor、轨迹包络、隐藏 primary 推导和 same-primary payload/route binding 放入同一 Groth16 admission relation，并将安全主张限定为准入一致性，不把它表述为轨迹真实性、来源认证或完整部署安全。

## 当前状态

- V4 静态与 Route-B/C21 门禁为 22/22 通过。
- 五数据集 Docker clean protocol smoke 为 5/5 通过。
- N=1000、五数据集、三种子固定公平效用比较已完成，V4 proposed 在五个数据集的观测均值和 15 个观测 dataset-seed 配对上均优于 Nebula-style 机制适配器，honest FRR 为 0；Porto 与 Synthetic 小增益不作统计显著性主张。
- V4 paper-scale cryptographic matrix 为 5 数据集 x 3 seeds x 16 rounds，共 15 个单元；2026-07-13 23:24:37 +0800 已完成 15/15，launcher receipt 为 pass、failed units 为 0。
- Strict aggregate 已验证全部 unit hashes、16-round contract、功能总账与 manifest/launch binding；15 个功能单元全部通过，13 个计时单元为 1.000 +/- 0.069 proofs/s、4.183 +/- 0.248 h/单元。
- 论文 evidence 已升级为 `scale.status=verified`，CE23 已关闭；最终 clean build、18/18 页视觉 QA 与 paper mirror 字节同步均已通过。
- 2026-07-22 已完成 reviewer-facing 内部版本审计。最终 PDF 不含 `V1/V2/V3/V4`、修正前后、旧版/新版、历史关系、归档性能、内部评审记录或投稿前 TODO。RQ6 只保留 evaluated Groth16 relation 与五数据集 scale matrix。
- 2026-07-22 已完成实验复现细节补强。RQ1 明确 12 次 payload mutations。RQ3 使用 700/300 user-disjoint split，四真实数据集 session AUC 为 0.7434、0.7491、0.7268、0.7316。图 5 已明确 External ESA 的 sampling、raw-count threshold 3 与 debiasing rules。
- 源码中的 `VFour*` 宏、`tab_v4_*` 标签、图文件名和 IEEE 模板版本注释不会渲染，继续作为 evidence traceability 标识保留。

## 当前焦点

- 实验完整性再审确认不存在阻塞性补实验需求；claim-safe 全文润色、最终重编译与视觉复核现已完成。
- Reviewer-version gate 已加入 `script/check_heatmap_manuscript.py`，可区分可见正文与不渲染的 LaTeX 标识；当前 265 项 evidence/figure/RQ3 split/manuscript tests 通过。
- 按 `docs/superpowers/specs/2026-07-13-tsip-heatmap-tdsc-revision-design.md` 执行 TDSC 分阶段证据驱动修订。
- Pre-scale 已完成 Git 保全、artifact 一致性、摘要、五数据集固定效用、合规门、18 页 clean build 与 adversarial self-review；final-polish 回归已通过 237 项证据、图形与稿件合同测试。
- 不再启动 scale launcher；保留 15 个 pass receipts。实验与机器可验证论文门禁均已闭合，当前只剩作者拥有的 release/submission 声明。
- 区分 [[Experiments/V4-Docker-N1000完整实验]]、旧版 full N=1000 RQ suite 和简单 Docker sanity run，避免证据混用。
- 用 [[Knowledge/V4方法与证据边界]] 约束论文措辞。
- 根据 [[Writing/论文修订与投稿决策]] 复核当前主稿，而不是沿用早期聊天中的页数或术语判断。

## 下一步动作

1. 作者明确 license、署名、单位/ORCID、COI、funding、ethics、code/data availability 和 AI-use disclosure。
2. 按投稿系统要求准备匿名稿、补充材料和最终元数据；不再启动或重跑现有实验矩阵。

## 重要链接

- [[01-Plan]]
- [[02-Index]]
- [[Knowledge/V4方法与证据边界]]
- [[Experiments/V4-Docker-N1000完整实验]]
- [[Results/Reports/V4实验结果-2026-07]]
- [[Results/Reports/V4实验完整性再审-2026-07-14]]
- [[Results/Reports/论文内部版本与投稿痕迹审计-2026-07-22]]
- [[Results/Reports/论文实验复现细节补强-2026-07-22]]
- [[Writing/论文修订与投稿决策]]
- [[Sources/Notes/Codex对话同步审计-2026-07-13]]
- [[Daily/2026-07-13]]
- [[Daily/2026-07-22]]

## 最近重要变化

- 2026-07-22 实验复现细节补强已提交为 `1e30bce4`：RQ1 为 12 次 payload mutations，RQ3 为 700/300 user-disjoint split，图 5 披露 External ESA 完整过滤/去偏规则；265 tests、稿件 0 issues、18/18 页视觉 QA 通过。
- 2026-07-22 闭合 RQ1 尝试数量、RQ3 classifier/user-disjoint split/精确 AUC 和图 5 external ESA filtering rules。轻量 RQ3 三种子重跑稳定，265 tests、18 页 clean build 与 18/18 页视觉 QA 通过。
- 2026-07-22 完成 reviewer-facing 内部版本与投稿痕迹审计：删除 RQ6 的旧关系/旧计时叙事、历史成本图、release TODO、内部评审说明和投稿前作者待办；最终 PDF 文本扫描为 0 命中，256 tests、18 页 clean build 和 18/18 页视觉 QA 通过。
- 2026-07-14 final-polish 论文提交为 `43f84752`：补充 Apple M4/Docker/软件环境，明确 Nebula-style 与 EIFFeL-style 为机制级适配器，收紧三种子小增益表述，重写核心章节并同步 canonical/mirror；237 tests、Abstract 147 words、稿件 issues 0、18 页 clean build 与 18/18 页视觉 QA 全部通过。
- 2026-07-14 实验完整性再审确认执行合同全部完成且无需补跑；发现并修复 Obsidian 事实源的 13/15 过期快照，同时把适配器基线、三种子小增益、clean-scale、timing exclusion 和硬件环境列为润色必须主动披露的非阻塞风险。
- 2026-07-14 final-scale verified paper build 已提交为 `71b7e418`：18 页 letter/PDF 1.7，90 citekeys，220 tests，稿件 issues 0；undefined/fatal/rerun/overfull/LaTeX/package/Biber warnings 均为 0，18/18 页视觉检查和 canonical/mirror 字节比较通过。
- 2026-07-14 final-scale evidence propagation 已提交为 `3591866c`（`feat: bind verified V4 N1000 paper evidence`）。
- 2026-07-14 final-scale paper evidence 已升级为 verified：220 tests、Abstract 147 words、manuscript issues 0；RQ6、Abstract、Conclusion 与 CE23 已只通过生成宏/表传播。
- 2026-07-14 strict aggregate 已提交为 `248f858c`；15 个功能 units verified，13 个连续计时 units 均值为 1.000 +/- 0.069 proofs/s，两个 host-suspended timing receipts 显式排除。
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
- [[Daily/2026-07-22]]

## Recent Changes
- 2026-07-22T08:22:50Z: sync refreshed scaffold, registry, index, and daily note (rq-reproducibility-hash-normalization).
- 2026-07-22T08:18:52Z: sync refreshed scaffold, registry, index, and daily note (rq-reproducibility-details-commit).
- 2026-07-22T08:08:08Z: sync refreshed scaffold, registry, index, and daily note (rq-reproducibility-details-receipt).
- 2026-07-22T08:06:25Z: sync refreshed scaffold, registry, index, and daily note (rq-reproducibility-details-final).
- 2026-07-22T08:04:48Z: sync refreshed scaffold, registry, index, and daily note (rq-reproducibility-details).
- 2026-07-22T07:21:12Z: sync refreshed scaffold, registry, index, and daily note (reviewer-version-hygiene).
- 2026-07-13T18:53:02Z: sync refreshed scaffold, registry, index, and daily note (tdsc-final-polish).
- 2026-07-13T18:25:44Z: sync refreshed scaffold, registry, index, and daily note (experiment-completeness-reaudit).
