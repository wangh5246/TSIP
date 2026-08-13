---
type: project-hub
project: waybill-ruc
updated: 2026-08-12
status: active
tags: [waybill, ruc, hub, v6]
---

# WayBill / RUC V6 项目 Hub

## 项目判断

2026-08-12 全面语义审计推翻了“旧 frozen release 可直接进入目标前置”的部分判断：
`waybill-formal-readiness-v2` 虽能自校验并复现 canonical receipt，但其 S2/S5 artifact、
S5 attestation anchor 和 S3 分组语义使其不具备 M4 执行资格。当前修复工作树已经通过
548 passed、3 skipped 的完整本地 CI，四数据集新 RG2 也通过；但修复尚未成为新的
不可变发布。**当前唯一准确状态为 `local-prerequisites-verified /
conditional-no-go-on-successor-release-target-rg6-materialization-smokes`。** 详见
[[Results/Reports/WayBill全面审阅与大规模实验前置闭环-2026-08-12]]。

WayBill 已完成 M0–M3 的实现与本机方法硬门验证：canonical policy acceptance、
odometer-backed fallback/month close、city-scale normalized capacity benchmark，
以及 certified E3 LB/UB/gap 均已有可复查 artifact。M2 的 16 组电路均已真实编译并
完成 setup，10,000-cell depth-14 tariff 已独立复核，depth-14 四组真实
witness/prove/verify 与终端复验均通过。方法门禁已经全部关闭，项目仍保持 `active`，
后续转入正式服务器实验、可信输入现场证据、隐私评估与论文重写。

2026-07-15 的服务器就绪性审计当时给出 **No-go**。2026-07-16 已完成租用前收口：
clean release 分支、Linux/amd64 容器、完整 raw manifest、formal protocol、
job-array/resume/strict-aggregate、S5 固定证明 corpus 和本地发布门禁均已建立。
当前准确状态为 **pre-rental ready / blocked-on-target**：可以租服务器，但必须在实际
目标机关闭 RG6、物化全量 prepared/canonical corpus 与最终 cardinality 后，才生成
formal run ID。详见
[[Results/Reports/服务器租用前就绪收口-2026-07-16]]。

同日完整复审给出双层裁决：**研究可行性通过、顶会论文预备性有条件通过；立即服务器
开跑和当前投稿成熟度不通过。** 项目不存在已经发现的致命算法/资源障碍，剩余条件均有
明确关闭路径，但不能把“可行”写成“已就绪”。详见
[[Results/Reports/顶会与大规模实验预备性复审-2026-07-15]]。

项目继续执行方案 A：先关闭安全与方法门禁，再补部署、隐私与写作。历史目录
`memory/TSIP_RUC/` 保留为来源，不再作为当前状态的事实源。

## V6 主线

1. **M0 Canonical Policy Binding**：把 tariff root、真实 `r_max`、cadence、速度/上限、circuit/vkey 和有效期固定到权威 profile；charger 缺项即拒绝。
2. **M1 Odometer Fallback**：正常定位按 `Δodo × zone rate`，定位缺失按 `Δodo × r_max`，未覆盖月里程用月度对账，月度证明缺失进入行政流程。
3. **M2 City-scale Proof**：完成 depth 8/12/14/16 × fixes 25/50/100/200 的规模矩阵，并至少让 depth 14 真实 prove/verify。
4. **M3 Certified E3 Bounds**：同时给出可行攻击下界、松弛上界和 optimality gap；在证明前不再称“形式化上界”。

## 当前焦点

- 以 [[Knowledge/WayBill-v6方法优化决策]] 作为唯一方法路线。
- M0–M3 均已 verified；下一阶段不再扩大方法门禁主张，而是补可信输入、真实账单、
  隐私与部署证据。
- 当前 P0 是先把已验证修复树冻结为 successor clean commit/tag/OCI/SIF/SBOM/scan/
  release bundle，再在 32 vCPU / 128 GiB / 1 TiB Linux x86_64 目标关闭 RG6、全量
  prepared/canonical manifest、最终资源计划和八类 smoke，然后执行
  [[Experiments/M4-服务器正式大规模实验]] 的完整 S1–S5 矩阵；S5 只作系统执行性补充。
- 顶会定位以 [[Results/Reports/顶会与大规模实验预备性复审-2026-07-15]] 为准：
  精确新颖性是 policy-pinned settlement + odometer completeness + quantified leakage，
  不泛称“首次 ZK 车辆税收”。
- 用 [[Results/Reports/V6方法门禁与实验台账-2026-07]] 记录每个门禁的证据，不以代码存在或单次成功代替 verified。
- 用 [[Writing/WayBill主张与术语修订]] 限制可信输入、隐私、可部署性和 TEE 表述。

## 当前事实

- M0 当前重跑结果为 1/1 正向接受、12/12 攻击拒绝、fail-open=0；authority
  digital-signature chain 尚未实现，不能把 commitment/hash 写成发布签名证据。
- M1 在 authenticated、monotone、calibrated odometer 条件下通过；226 periods、3390
  paired rows 的 withholding/undercharge 为 0，四数据集 P95 均改善，但尚无 field certification。
- M2 的 16/16 compile 与 16/16 setup receipt 已通过；depth-14 约束量从 275,538
  （25 fixes）增至 2,254,788（200 fixes），四组各 3 份 measured proof 共 12/12
  终端复验成功。该结论仅是 normalized-test-unit capacity benchmark，不是现实 RUC
  或生产安全认证。
- M3 当前 24/24 certified、全部 gap=0；旧 0.464→0.295 仅是 legacy sensitivity，
  旧 648m→361m 投影被 V6 `ODO_BINDING` 拒绝。
- 当前 M1 规模仅 226 periods，M3 仅 24 instances；它们足以关闭方法门禁，但不是
  正式全量服务器结果。正式服务器矩阵已另行冻结，不能把这些本机数字复制进主表。
- WayBill V6 已有 Linux/amd64 OCI 镜像、依赖 lock、GNU time 资源采集、正式 runbook
  与不可覆盖编排；容器 digest 为
  `sha256:931cac8c4888478b0da88d66ee7f6113466f5953a6051a60bc34ef3829bd2b9a`。
- 四数据集 raw manifest 已通过，T-Drive 为完整 10,357 文件；全量 prepared/canonical
  manifest 将在 1 TiB 目标服务器上无 cap 物化。
- 冻结 protocol 的非 S3 静态作业为 1,695，静态预估 1,047 CPU-hours、244.4 GiB
  两次 attempt 存储，峰值调度内存 128 GiB；S3 最终数量等待全量 period count。
- E5 的精确匿名中位数为 1，一次 level-2 opening 可识别约 76%，不能以 pool size 代替真实匿名性。
- `WayBill/main.tex` 是带占位符的短骨架，不是可投稿全文。

## 关键入口

- [[01-Plan]]
- [[02-Index]]
- [[Sources/Docs/WayBill外部审阅报告-2026-07-13]]
- [[Sources/Docs/WayBill当前仓库审计-2026-07-13]]
- [[Knowledge/WayBill-v5真实状态与证据边界]]
- [[Knowledge/WayBill-v6方法优化决策]]
- [[Results/Reports/V5证据快照与审阅差距-2026-07]]
- [[Results/Reports/V6方法门禁与实验台账-2026-07]]
- [[Results/Reports/服务器正式实验就绪性审计-2026-07-15]]
- [[Results/Reports/顶会与大规模实验预备性复审-2026-07-15]]
- [[Results/Reports/服务器租用前就绪收口-2026-07-16]]
- [[Results/Reports/WayBill全面审阅与大规模实验前置闭环-2026-08-12]]
- [[Experiments/M4-服务器正式大规模实验]]
- [[Daily/2026-07-13]]
- [[Daily/2026-07-14]]
- [[Daily/2026-07-15]]
- [[Daily/2026-07-16]]
- [[Daily/2026-08-12]]

## 最近变化

- 2026-07-13：用户批准方案 A，并确认建立独立 `waybill-ruc` Obsidian 项目。
- 2026-07-13：把 Canonical Policy Binding 提升为 M0，优先级高于审阅报告中的 fallback 修改。
- 2026-07-13：旧结论“只差论文写作”标记为历史判断，不再指导下一步。
- 2026-07-14：M0–M3 全部通过硬门；M2 完成 16/16 编译与 setup、10,000-cell
  tariff 复核及 depth-14 四组真实证明，后续转入现场证据、隐私与写作。
- 2026-07-15：正式服务器实验路线获批；审计判定当前为 No-go，建立 M4 的
  RG0–RG8 与 S1–S5 规格，下一步先关闭可复现与全量数据前置条件。
- 2026-07-15：完成顶会与规模预备性复审；研究/矩阵可行性通过，顶会预备性有条件
  通过，立即服务器开跑与投稿成熟度保持不通过。
- 2026-07-16：租用前条件收口；Linux 容器、完整 raw manifest、正式编排、S5 corpus、
  453 项通过测试和安全审计已完成，项目进入目标服务器 RG6/全量物化阶段。
- 2026-07-17：补充稀疏检出不变的 code manifest 与 Git LFS 安全迁移路径；测试增至
  454 passed、2 skipped，冻结 bundle 可在跳过历史 LFS artifact 后干净克隆。
- 2026-08-12：五角审阅发现旧 V2 三项 M4 致命语义缺陷；当前树完成 runner、统计、
  失败回执、论文与 runbook 修复并通过 548 passed、3 skipped。旧 V2 标记为
  superseded/no-go；下一步必须冻结 successor release 并完成目标 RG6/物化/smoke。

## Important Links
- [[01-Plan]]
- [[02-Index]]
- [[_system/registry]]
- [[Daily/2026-07-16]]
- [[Daily/2026-07-17]]
- [[Daily/2026-08-12]]

## Recent Changes
- 2026-07-17: release bundle and sparse-checkout-invariant code manifest verified.
- 2026-08-12: V2 superseded for M4; repaired tree passed local CI, successor release and target gates remain.
- 2026-07-16: pre-rental readiness passed; target-host RG6 and full materialization remain.
- 2026-07-15T15:19:35Z: sync refreshed scaffold, registry, index, and daily note (auto).
- 2026-07-13T20:35:59Z: sync refreshed scaffold, registry, index, and daily note (auto).
