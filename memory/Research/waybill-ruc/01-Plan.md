---
type: project-plan
project: waybill-ruc
updated: 2026-07-15
status: active
tags: [waybill, ruc, plan, v6]
---

# WayBill / RUC V6 方法优化计划

## 总目标

把当前“对提交者给出的公开策略保持内部一致”的证明，升级为“对权威策略、可审计测量与明确 fallback 规则保持一致”的结算证明；同时补齐城市规模和 E3 最优性证据。完成顺序由安全依赖决定，不由论文段落顺序决定。

## 完成定义

V6 方法阶段只有在以下四项均达到 `verified` 后完成：

- M0：攻击者不能通过自选 tariff root、低报 `r_max` 或放宽公开限制生成可被 charger 接受的低账单。
- M1：停车 outage 为零收费；可信里程覆盖的 withholding 不产生少缴；两侧误差界和四数据集 surcharge 分布均有证据。
- M2：depth 14 在声明资源环境内完成真实 witness/prove/verify，规模表可复现。
- M3：代表性实例有可行下界、松弛上界和 gap；超时也保留证书状态。

任何一项未通过，都必须按门禁规则缩小主张，不能用写作润色替代。

当前检查点（2026-07-15）：M0–M3 均为 `verified`，但正式服务器实验就绪性为
`blocked`。本机方法门禁不能替代 clean Git revision、Linux 容器、完整数据、正式
job matrix 和目标主机 receipt。详情见
[[Results/Reports/服务器正式实验就绪性审计-2026-07-15]]。

## P0 — M4 服务器正式大规模实验就绪性

正式设计：[[Experiments/M4-服务器正式大规模实验]]。

- [ ] RG0：把 WayBill V6 代码、circuits、configs、tests 和 Obsidian 固定到 clean
  commit/tag；raw/restricted data 与 14 GiB M2 artifact 不进入普通 Git，对外用 hash manifest。
- [ ] RG1：建立 Linux x86_64 OCI/Apptainer 镜像和依赖锁，固定 Python 3.12、Node 26、
  Circom 2.1.9、snarkjs 0.7.6、circomlib 与 Python 包。
- [ ] RG2：取得完整 T-Drive，并为四个真实数据集建立 WayBill 专用 provenance、条款、
  raw/prepared hash 与完整性计数；所有正式预处理 cap 为 0。
- [ ] RG3：把 normalized capacity tariff 与现实 economic tariff 分开登记，固定单位、
  source、root、maximum 和可用主张。
- [ ] RG4：把 M2 资源采集移植到 Linux，增加 Linux CI receipt，删除对
  `/usr/bin/time -l` 和 macOS `sysctl` 的硬依赖。
- [ ] RG5：实现 formal manifest、dry-run、local/Slurm job arrays、immutable run id、
  resume、最多两次 attempt、strict merge 和缺单元 fail-closed。
- [ ] RG6：在目标服务器验证 ≥32 GiB RAM/job、≥100 GiB workspace、CPU/disk/toolchain、
  container digest 与 PTAU hash；该项不得在本机代签。
- [ ] RG7：把 S1–S5 expected cardinality、seeds、timeout、并发和统计方法写入 hash 固定
  的 protocol JSON；禁止正式运行中改配置。
- [ ] RG8：全套 tests/static/negative/manifest validator 和 Obsidian lint/link check 通过。
- [ ] RG0–RG8 全通过后才允许 `--formal`，依次执行 S1 全量公平、S2 16 配置真实证明、
  S3 全量 certified bounds、S4 route/linkability；S5 最后作系统补充。

服务器阶段只接受正式矩阵。环境检查不产生论文结果；`max-trips`、`max-raw-points`、
`limit-per-input`、`max-fixes` 任一非 0 的运行都标为 debug，不进入 aggregate。

## P0 — M0 Canonical Policy Binding

- [x] 定义 `PolicyProfile` 的 SSOT：jurisdiction、version、有效期、撤销/回滚状态、tariff root、真实 `r_max`、cadence、`max_dt`、速度/上限策略、circuit ID、vkey hash、定点/舍入/溢出版本、reconciliation rate。
- [x] 定义确定性的 `policy_profile_commitment` 和 domain separation。
- [x] 明确 measurement attestation 只签测量日志根、设备、周期、序号和必要上下文，不让接收机定义价格策略。
- [x] charger 按 jurisdiction + billing period 选择本地权威 profile，并逐字段比对 proof statement。
- [x] vkey 缺失、profile 未知/过期/撤销/降级、字段缺失或不一致时 fail closed。
- [x] 由 canonical artifact 检查保证 tariff tree、声明 root 与 `r_max` 一致，提交者不能自行声明 maximum。
- [x] 增加低价私有 root、低报 `r_max`、扩大 cadence/`v_max`/`max_dt`、改变 cap、vkey downgrade、replay、rollback、跨辖区复用等负测。
- [x] 输出 threat-model delta、profile schema、测试 receipt 和攻击回归结果到 [[Results/Reports/V6方法门禁与实验台账-2026-07]]。

详细卡片：[[Experiments/M0-Canonical-Policy-Binding]]

## P0 — M1 三层 Fallback 与双侧保证

依赖：M0 profile 字段和金额语义冻结。

- [x] 把 checkpoint 统一为时间、可信里程、单调序号和显式 position-valid evidence；reset/repair/wrap-around 未经认证时 fail closed。
- [x] 正常区间按 `Δodo × r(zone)`，定位缺失区间按 `Δodo × r_max`。
- [x] 月末只对 `monthly_Δodo - accounted_Δodo` 的未覆盖里程按 `r_max` 对账，避免双计费。
- [x] 月度里程证明也缺失时，明确进入行政异常，不把长期不提交静默变成零账单。
- [x] 形式化 Revenue Soundness，显式列出 odometer calibration、量化、舍入和算术误差条件。
- [x] 形式化 Honest-user Fairness，给出 outage rate premium 的最坏界与经验分布。
- [x] 检查停车 `Δodo=0`、乱序、重复结算、整数溢出、单位错误、里程回滚/重置、跨期边界。
- [x] 做 circuit / charger / Python SSOT 差分测试。
- [x] 在所有现有数据集上与旧 `Δt × v_max × r_max` 比较 median/P95 surcharge、undercharge、拒绝率和敏感性。

详细卡片：[[Experiments/M1-三层Fallback与双侧保证]]

## P0 — M2 Tariff 树深度与 Fix 规模

依赖：M1 公共输入接口冻结；可与 M3 并行。

- [x] 参数化 depth 与 `N_FIXES`，去掉只适用于 8/25 的 wrapper 假设。
- [x] 编译 depth 8/12/14/16 × fixes 25/50/100/200，并完成 16/16 真实 setup receipt；非 depth-14 临时 zkey 在记录与导出 vkey 后清理。
- [x] 对 depth 14 的 25/50/100/200 分别执行 warm-up + 3 次真实 witness/prove/verify；12/12 measured proofs 终端复验通过。
- [x] 报告三次独立测量的 p50/P95、峰值 RAM、proof/key size、吞吐和失败率；VRAM 明确为 N/A。
- [x] 验证 10,000-cell provenance-backed tariff artifact 可被 depth-14 root 完整承载；费率值仅为容量实验的 normalized tiers，不是现实 RUC 金额。
- [x] depth 14 成功至 200 fixes；主张限定为 normalized-test-unit capacity benchmark，不外推为现实计费或生产安全认证。

详细卡片：[[Experiments/M2-Tariff树深度与Fix规模]]

## P1 — M3 E3 求解器收敛与严格界

依赖：冻结攻击目标、位置偏移半径和账单真值定义；可与 M2 并行。

- [x] 写清 adversary objective、决策变量和所有约束。
- [x] 对 100/50/25/10 m bucket 构造可行攻击下界与已证明的松弛上界。
- [x] 用独立 exact integer oracle、strict feasible checker 与 relaxation direction gate 获得证书；报告 absolute/relative gap。
- [x] receipt schema 保留 best feasible、best bound、gap、运行时间、内存和 timeout 状态；本轮 24 个实例无 timeout。
- [x] 复核 Rome 100 m → 50 m 的 P95 0.464 → 0.295，确认它是 legacy sensitivity 而非严格界；旧 648m→361m 被 `ODO_BINDING` 拒绝。
- [x] `ρ`-robust tariff envelope 保持未启用可选分支；因本轮未完成相应定理和诚实边界过收费评估，不进入主方法。

详细卡片：[[Experiments/M3-E3求解器收敛与界]]

## P1 — 可信输入与真实账单证据

- [ ] 把信任链分成导航消息认证、接收机/安全执行环境、位置有效性判定、里程计防回滚和月度 attestation 五层。
- [ ] 不再把 OSNMA 表述成物理位置真实性证明。
- [ ] 若保留部署主张，做小规模接收机 + odometer field trial，报告丢失、漂移、重置、时间同步和校准误差。
- [ ] 选择可追溯的真实 tariff 与月度账单，明确税费、舍入和 reconciliation 基准。

## P2 — 隐私、相机与基线

- [ ] E5 从 pool size 扩展到 route inference、跨期 linkability、fallback 标志和里程增量泄漏。
- [ ] E4 用真实候选相机点位、道路拓扑和 set cover 替代 100 m segment-equivalent 数量。
- [ ] TEE 仅在完成同等功能、威胁模型和硬件测量后做绝对对比，否则删去绝对优越性结论。

## P2 — 论文重写

- [x] M0–M3 门禁通过，Method、Security 与本机方法门禁部分可开始重写。
- [ ] Evaluation 主表和正式规模结论等待 M4 S1–S4 strict aggregate，不复制本机小矩阵
  或 debug 结果冒充正式服务器实验。
- [ ] 按 [[Writing/WayBill主张与术语修订]] 全文替换过强术语。
- [ ] 建立 claim → assumption → theorem/test → artifact 的证据表。
- [ ] 删除 `WayBill/main.tex` 的占位符并补齐 bibliography、limitations 和 reproducibility。

## 执行与记录规则

- `planned` 只表示设计存在；代码完成但无 receipt 仍不能写 `verified`。
- 每个实验先写 hypothesis、variables、metrics、gate、stop rule，再运行。
- 所有金额结果同时报告相对误差和绝对货币误差；所有优化结果同时报告 feasible value、bound 和 gap。
- 所有公开参数都必须能追到权威 profile；所有传感器真实性主张都必须能追到具体 attestation 能力。
- 结果统一回填 [[Results/Reports/V6方法门禁与实验台账-2026-07]]，历史事实保留在 [[Results/Reports/V5证据快照与审阅差距-2026-07]]。
