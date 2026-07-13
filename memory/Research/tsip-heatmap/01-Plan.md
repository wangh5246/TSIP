---
type: project-plan
project: tsip-heatmap
updated: 2026-07-14
status: active
tags: [tsip-heatmap, plan, v4]
---

# TSIP Heatmap V4 完整实验计划

## P0 TDSC 非实验修订

- [x] 确认 IEEE TDSC 为唯一投稿目标。
- [x] 批准分阶段证据驱动方案 A。
- [x] 写入并提交 TDSC 修订设计规格 `c6243a02`。
- [x] 用户批准设计规格并生成、静态验证、提交 pre-scale 与 final-scale 两份详细实施计划（`ed4d2f86`）。
- [x] 比对并保全 `TSIP/main.tex` 的索引版本与工作区重建版本（`2636cec8`；spec/quality review 均通过）。
- [x] 建立 manifest-bound paper artifact 的唯一事实表（`paper_evidence.json`；focused 86、baseline 45、两层审查通过）。
- [x] 建立 manuscript evidence contract checker（`1cc26e9d`、`f45972dc`；focused 73、Task 2/3 combined 159、baseline 45；本地规格/质量复核通过）。
- [x] 将全文旧 3,056/14/23 circuit 数字与当前 artifact 对齐（生成宏唯一加载；三层 relation 分离；checker 仅余 Tasks 5--6 四项）。
- [x] 将 Abstract 从约 247 词压缩到 100 至 200 词（final-scale 传播后为 147 词；五消息；只用 verified evidence）。
- [x] 把四个真实数据集加一个 Synthetic 及固定公平效用接入正文（`3f1d5d4b`；固定主比较、生成表图、checker 0 issue、focused 169）。
- [x] 增加 DATA_NOTICE、Heatmap 可复现索引、citation audit 与作者确认声明（`dec09503`）；LICENSE 因缺少作者明确 SPDX 选择而保持阻塞并不创建。
- [x] 从 clean auxiliary state 重新编译、统计 18 页并完成 18/18 逐页视觉检查；pre-scale verified checkpoint 已提交为 `d54ac1a5`，最终 scale aggregate 写回后须重复该门禁。
- [x] 建立 Abstract/Introduction claim-evidence map（final-scale 后为 27 claims：18 supported、7 analytical、2 assumption、0 partial、0 unsupported）。
- [x] 完成并提交 Task 9 五维对抗自审（`a0db10db`）；关闭 citation/artifact 两项 partial，移除过强治理类比，claim map 收敛为 17 supported / 7 analytical / 2 assumption / 1 partial / 0 unsupported，169 tests 通过。

Pre-scale 阶段不提前写入 15/15 scale 结论；final-scale 严格聚合通过后已按下方门禁完成一次性传播。

## 执行规则

- `status.json` 和 gate receipt 是状态事实源，不以容器健康或聊天表述代替完成证据。
- utility evaluator 使用原始五数据集 N=1000 输入；`TSIP_SAFE_PROTOCOL_TRAJECTORY=1` 仅用于 clean protocol 的状态机、证明、重构与 DP smoke，不能作为真实轨迹效用证据。
- 固定公平主比较使用同一 `epsilon=5.0`、`tau=2.0`；逐数据集优化只作为 upper-bound view。
- 不把开发 Groth16 setup、Docker health 或 admission consistency 写成生产安全部署。
- 已通过单元默认跳过；重跑只针对中断或失败单元，不使用 `--rerun-passed`。

## P0 大规模矩阵闭环

- [x] 五数据集各 1000 条输入及 manifest artifact 完整。
- [x] static 22/22、protocol smoke 5/5、utility、compose、images、disk 和 resource gates 通过。
- [x] T-Drive/101 pilot 16/16 rounds 通过。
- [x] 15/15 dataset-seed 单元通过。
- [x] 清理 Rome/303 与 Synthetic/303 的旧空闲 compose 项目并启动新的受控续跑。
- [x] Rome/303 与 Synthetic/303 受控续跑完成并返回 pass；launcher 于 2026-07-13 23:24:37 +0800 正常退出。
- [x] 确认 15/15 pass，`launch_status.json` 已从 `running` 收敛为 `pass`，failed units 为 0。
- [x] 汇总每单元 proof generation/verification、失败率、连续计时、reconstruction 和 DP receipt；Rome/101 与 Synthetic/101 的 host-suspension timing 已明确排除但功能 receipt 保留。

## P1 论文结果闭环

- [x] 生成 15 单元 aggregate CSV/JSON/LaTeX 和可审计 manifest/launch/unit hash 绑定。
- [x] Strict aggregate 生成器、33 项 tests 和三份聚合 artifacts 已提交为 `248f858c`。
- [x] 报告均值、样本标准差和 seed 间波动，不只报告最优 seed；同时显式披露 13/15 timing receipts 及排除规则。
- [x] 将 protocol scalability 与 fixed utility 分成不同表或小节（Experimental Setup 三层分离；RQ5 固定效用；RQ6 scale）。
- [x] 更新论文中数据集、实验协议、效用和成本数字；规模数字只来自 verified `paper_evidence.json`、生成宏和生成表，220 项测试通过。
- [x] 全文搜索并消除过强的 authenticity、robustness、security guarantee 与现实治理类比表述；最终 scale 写回后再跑同一 checker。
- [x] 重新编译并视觉核验论文页数、图表和引用；final-scale 18 页 PDF、90 citekeys、220 tests、0 manuscript issues、18/18 页视觉检查与 mirror 字节一致性均通过（`71b7e418`）。

## 完成门槛

- 15 个单元均有 `state=pass`、16 rounds、无 failure。
- 每个单元 warmup 6 轮、evaluation 10 轮；evaluation A/R 计数为 1000/1000，reconstruction 和 DP 均为 true。
- 所有证明尝试都有对应 verified receipt，proof failed 为 0。
- 论文表格只引用汇总脚本生成的 artifact，且与 manifest hash 一致。
- [x] [[Results/Reports/V4实验结果-2026-07]] 已从 `partial-verified` 更新为 `verified`，并披露 timing exclusion。

## P0 最终全文润色

- [x] 复审 Obsidian、strict aggregate、utility receipts、baseline adapters 与论文证据边界，确认无需新增实验。
- [x] 修复 `Sources/Docs/V4方法审计与实验事实源` 中 13/15 running 的过期当前状态。
- [x] 补充论文硬件环境与 adapter baseline 说明。
- [x] 按 claim-safe 原则润色 Abstract、Introduction、Related Work、Method、Evaluation、Discussion 和 Conclusion。
- [x] 复跑 237 项 evidence/figure/manuscript tests、clean LaTeX/Biber build、18/18 页视觉检查和 mirror 字节比较；final-polish 提交为 `43f84752`。
