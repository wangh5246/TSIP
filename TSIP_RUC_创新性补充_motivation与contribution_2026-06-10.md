# TSIP-RUC 创新性补充：夯实 Motivation 与 Contribution

> 日期：2026-06-10
> 性质：这不是工程审阅（见综合审阅报告），而是对方案本身的概念性补充——如何把已有的实验和设计升级为可命名、可定义、可被引用的贡献。
> 原则：以下每条都建立在你已有的代码/实验之上，不要求新发明密码学原语；大部分是"重新框定 + 少量补充工作"。

---

## 一、Motivation 的三层重构

### 1.1 把信任假设从"代价"翻转为"机会"（最高优先级）

当前 thesis 把 trusted receiver/odometer/OSNMA 写成 "at the cost of a stronger trusted assumption"——这是防守姿态。事实已经反转：

- **Galileo OSNMA 于 2025-07-24 宣布正式运营**（EUSPA）。
- **欧盟 Implementing Regulation (EU) 2021/1228 强制 smart tachograph 使用 OSNMA 认证位置**；自 **2025-12-24 起所有新注册商用车必须装载支持 OSNMA 的 Smart Tachograph 2**。
- 即：一个防篡改的、OSNMA 认证 GNSS + 安全里程计的车载可信设备，**已经是欧盟每辆新商用车的法定标配**——这正是 TSIP-RUC 假设的 receiver。

motivation 应改写为：

> The trusted sensing hardware TSIP-RUC assumes is not hypothetical: EU regulation already mandates OSNMA-authenticated GNSS and tamper-evident odometry in every newly registered commercial vehicle (Smart Tachograph v2). What regulation has *not* provided is a settlement protocol that exploits this hardware for privacy. Today the tachograph records authenticated positions precisely so that authorities can *read* them — the privacy model is "trust the inspector." TSIP-RUC inverts this: the same hardware root of trust, but the authority learns only a verified bill.

这一段同时完成三件事：假设去魔法化（reviewer 无法再说 assumption exotic）、给出明确部署载体（商用车 RUC——德国 Maut、比利时 Viapass 正是现实中收费最重的场景）、并制造一个尖锐的现状批判（现有法规设备的隐私模型是"把认证轨迹交给检查员"）。

### 1.2 政策时间窗：RUC 正在从试点变强制，隐私是头号反对理由

- EV 普及 → 燃油税收入侵蚀 → 各国被迫转向按里程/按区域收费。
- **Oregon 已立法美国首个强制性 RUC 分阶段时间表**（⚠️ 2026-06-11 v3 审阅纠错:此前"2026-04 已强制"为媒体标题党口径,与官方不符。正确口径:自愿项目 OReGO 自 2015 运行,2026 年费率升至 2.3¢/mile;**强制阶段:2027-07-01 二手 EV 续期、2028-01-01 新 EV、2028-07-01 混动**。论文写 "Oregon has legislated the first mandatory RUC phase-in (EVs from 2027)",引 ODOT/NCSL 官方源,不引二手媒体）；多州（Utah、Virginia、Hawaii）已有 program。
- RUC 试点的公开听证中，GPS 追踪隐私始终是最大公众反对点（Oregon/California 试点报告均有记录，写作时引官方报告）。

叙事：**这不是"假如未来有 RUC"的论文，而是"RUC 正在立法落地、隐私反对正在阻碍它、硬件前提刚刚就位"的三线交汇时刻**。把这写成 intro 第一段，时效性即是 motivation。

### 1.3 把设计空间表升级为"RUC 三难困境"（trilemma）

现有 §1.3 表格已经隐含此结构，建议显式命名：

> **The RUC trilemma**: zone-granular pricing, route privacy, and zero roadside enforcement — existing systems achieve at most two. Plaintext GPS upload: pricing + no infrastructure, no privacy. Odometer-only: privacy + no infrastructure, no zone pricing. Spot-check cryptographic RUC (VPriv/PrETP/Milo): pricing + privacy, but enforcement requires city-scale roadside observation. We show the trilemma is not fundamental: it dissolves under a trusted-sensing assumption that regulation has already made universal.

"trilemma + dissolution condition"是 reviewer 会记住、别人引用时会复述的句式。E4 的作用随之清晰：它量化的就是第三轴（拒绝放弃 enforcement 的代价 = 多少摄像头）。

### 1.4 正面回答 "why zk at all"：Policy-Free TCB 原则

这是审阅报告指出的攻击点，这里给出可命名的回答——**把它变成贡献而非辩护**：

> **Policy-free trusted computing base.** The receiver is trusted for exactly one narrow capability: attesting raw sensor readings (time, cell, odometer tick). It contains *zero pricing logic*. Tariff tables, calendar windows, fallback policy, and trajectory-feasibility rules live outside the trust boundary and are enforced by the proof. Consequently: tariff updates require no firmware trust; a compromised or buggy receiver firmware can corrupt *readings* but cannot mis-*price* them; regulators can change charging policy without re-certifying hardware; and disputes about billing logic never reduce to "trust the device vendor."

对比锚点：TEE 方案把计费策略放进 trust boundary（策略更新 = 重新信任）；tachograph 现状把整条认证轨迹交给读取方。TSIP-RUC 是第三点：**信任传感，验证策略**（trust the sensing, verify the policy）。这八个字可以做 section 标题。

---

## 二、Contribution 的升级：从"实验"到"可定义的概念"

你的四个 contribution 目前是"我们做了 X 实验"。下面把每个升级为"我们定义/证明了 Y，并用 X 测量它"。定义型贡献的引用寿命远长于系统型。

### 2.1 ε-economic soundness：把 E1/E3 升级为定义性贡献（最重要）

E1 的方法论——"关掉一条约束，量化理性对手能省多少钱"——实际上是一个可泛化的安全度量，但目前埋在实验章节。建议显式定义：

> **Definition (ε-economic soundness).** A billing system is ε-economically sound against adversary class A if no strategy in A that passes verification reduces the adversary's payment by more than an ε fraction of the honest fee:
> `sup_{a∈A, accepted(a)} (fee_honest − fee(a)) / fee_honest ≤ ε`

在此定义下，整个 evaluation 获得统一语义：

- **E1 = 约束消融下的 ε 测量**：去掉 zone binding 后系统仅 0.27-economic-sound（GeoLife）；OSNMA pinned 下对 replay 类 0-economic-sound。
- **E3 = proof-consistent 对手类的 residual ε**：约束全开时 ε 还剩多少（relay/粒度/余量）。
- **E2 = 对 outage 声明策略类的 ε**：alpha≥1 时 ε=0（可证），alpha=0.6 时经验 p95 ε=0。
- 传统二元 soundness 是 ε 的退化情形；max_dt bitwidth 修复对应"ε 从可达 1 修到受控"。

写作建议：第 3 章给定义，每个实验章节首句声明"本实验测量对手类 A_x 下的 ε"。贡献句：

> We replace binary soundness with a *quantitative economic security metric* for verifiable billing, and instantiate the first measurement methodology for it: constraint ablation with receipt-level forensics over real mobility data, with a single-source-of-truth billing oracle shared between the adversary's optimizer and the settlement path (preventing the objective/billing drift we identified as a measurement hazard).

最后半句很重要：你们踩过的 Rome 0.94 假阳性坑，本身就是这个方法论的 methodological contribution——"对手目标函数与真实计费必须同源，否则 ε 测量系统性高估"。这是任何后续做经济消融的人都要遵守的 protocol，值得一小节。

### 2.2 单调降级原则 + DSIC 定理：把 E2 升级为"定理 + 测量"对

E2 目前是 frontier 实验。它里面藏着一个可以陈述为定理的机制设计结果：

> **Proposition (outage-DSIC).** If fallback_rate ≥ max_zone_rate and per-interval distance ≤ dt·v_max holds, then truthful outage reporting is a dominant strategy: for every interval, fallback_fee ≥ exact_fee, hence no declaration strategy reduces payment.

（证明就是 §5.3 那四行不等式——形式化它，写成 proposition + proof，从"公式注释"升格为"结果"。）

再向上抽象一层，命名一个设计原则：

> **Monotone degradation principle.** Every degradation path in the protocol (missing fix → fallback; missing proof → administrative penalty) must be weakly more expensive for the payer than the exact path it replaces. This turns sensor failure from an attack surface into a self-pricing event.

E2 的角色随之变成：**充分条件 alpha=1 太保守，经验 break-even 分布给出更优运营点（0.6/0.4），代价是可量化的 honest penalty**——"理论给安全界、数据给运营点"。这是密码学约束与机制设计 co-design 的完整闭环，目前文献里 RUC 的 outage 处理从未被当作激励问题来设计。这本身就是一条独立 contribution：

> We treat sensor outage as a mechanism-design problem rather than an availability problem, give a sufficient condition for dominant-strategy truthful outage reporting, and chart the empirical fairness–incentive frontier that lets operators run below the conservative bound.

### 2.3 基础设施汇率：给 E4 一个可命名的度量

E4 的核心产出建议命名为 **enforcement exchange rate**（执法汇率）：达到与确定性 proof 拒绝同等检出率，spot-check 谱系需要的 cameras/km²。

- 框架句："we quantify the exchange rate between cryptographic verification and physical enforcement infrastructure, per city."
- 图建议：x 轴摄像头密度、y 轴 P(caught)，三城三条曲线，TSIP-RUC 是 y=1 的水平线——一图讲完整个 E4。
- 加一个对偶视角（几乎免费但很有力）：反向折算成钱。城市级 ANPR 摄像头的采购+运维成本是公开数据，把"省下的摄像头"换算成 $/vehicle/year，与 E6 的 proof 计算成本（client CPU 秒数）同表对比——**"密码学每月几十秒 CPU，替代的是城市每年数百万美元的路侧基建"**。这是给非密码学读者（包括政策读者）的 takeaway。

### 2.4 结算最小披露 + 元数据推断攻击：把 E5 从 checkbox 升级为研究问题

E5 当前定位是"对比明文上传"，太容易。建议加一个更锋利的问题，它同时是诚实的自我攻击：

> **How much does money leak about location?** Even the proof-only statement reveals a monthly *sequence* of (fee, distance, fallback count, 2h window) tuples. Fee is a tariff-weighted path integral — a high-fee, short-distance period implies presence in expensive zones.

具体可做（工作量可控，数据和 tariff 都已在库）：

- 推断攻击：给定 period 元组序列 + 公开 tariff，攻击者能否分类通勤模式 / 推断常驻 zone 档位 / 区分两条候选路线？用你已有的 GeoLife/Rome period 数据直接构造。
- **cadence 作为隐私旋钮**：60s cadence → 每月 150 个元组 → 更细的费用时间序列 → 更多泄漏。这把 E6 的性能维度和 E5 的隐私维度耦合成同一个 design dial（period 粒度），是论文里少见的 honest tradeoff 分析。
- 可加的廉价缓解作为 discussion：fee bucketing（账单按档位取整呈报，月底精确结算）、period 时间窗对齐到固定网格以减少启停时刻泄漏。

这样 E5 的贡献句变成：

> We give the first leakage analysis of *settlement metadata* in proof-based RUC, showing that per-period fee sequences constitute a non-trivial side channel, quantifying its dependence on proof cadence, and proposing bucketing mitigations — in contrast to prior work that treats "no raw GPS upload" as the end of the privacy argument.

注意这条的策略价值：**主动量化自己方案的残余泄漏，比只打稻草人 baseline 可信得多**，而且先发制人地占住了 reviewer 最可能提出的批评。

### 2.5 新增小协议：基于 interval commitment root 的选择性披露争议仲裁（近乎免费的贡献）

当前设计缺 dispute resolution，而你的数据结构已经把答案准备好了：`interval_commitment_root` 是逐段承诺的 Merkle 聚合。补一个两页的小协议：

- 用户质疑账单 / charger 怀疑欺诈 → 仲裁方指定（或抽样）k 个 interval。
- 用户打开这 k 个 interval 的 Merkle path + 承诺内容（cell、odo delta、rate、fee、fallback flag）。
- 仲裁方核对该段费用与 tariff root 一致，**其余 23−k 段保持隐藏**。

性质：披露量 O(k·depth)，轨迹其余部分零披露；可与 E5 联动量化"一次仲裁泄漏多少"。部署现实性问题（reviewer：真实计费系统必须可仲裁）被一个已有结构的自然推论解决。贡献句：

> The interval commitment structure yields a selective-disclosure dispute protocol for free: arbitration over any single charged segment reveals only that segment.

工程成本：不需要改电路，只需要一个 opening verifier（Python 一两百行）+ 单元测试，建议做最小实现而不只是纸面协议。

### 2.6 泛化声明：Pay-by-Proof / verifiable metered billing 模板

Discussion 加一段，把电路模式抽象为模板：

> authenticated sensor stream → Merkle-bound public tariff → physical feasibility constraints → committed per-interval fees → total。

同一模板直接覆盖：拥堵费、低排放区收费、按驾驶行为保险（PAYD/UBI）、EV 充电结算、无人机走廊收费。一段话把论文从 "an RUC system" 抬到 "a template for privacy-preserving metered billing over attested physical sensors"。不要超过一段——泛化声明写多了会被要求证明。

### 2.7 跨月不可链接性（写成 future work，一句话占坑）

device attestation commitment 使同一设备的各月账单天然可链接（charger 必须知道向谁收钱，本月内可链接是功能需求）。但跨场景链接（如同一 commitment 出现在多个收费域）值得一句 future work：per-domain pseudonymous attestation key + 月度聚合，防 charger 之间共谋画像。占住这个坑防止 reviewer 当新发现提出。

---

## 三、建议的 Contribution 列表重写（论文可直接改写使用）

> 1. **Design point & trilemma dissolution.** We identify the RUC trilemma (zone pricing / route privacy / zero roadside enforcement) and show it dissolves under a trusted-sensing assumption that EU smart-tachograph regulation has already universalized — with a *policy-free* TCB: the device attests readings, never prices them.
> 2. **ε-economic soundness.** We introduce a quantitative economic security metric for verifiable billing and a receipt-auditable measurement methodology (constraint ablation with a shared billing oracle), exposing per-constraint economic attack surface on four real mobility datasets.
> 3. **Incentive-compatible degradation.** We prove a sufficient condition for dominant-strategy truthful outage reporting (monotone degradation) and chart the empirical fairness–incentive frontier that admits operating points well below the conservative bound.
> 4. **Enforcement exchange rate.** We quantify the roadside infrastructure (cameras/km², $/vehicle/year) that spot-check RUC systems require to match deterministic proof rejection, across three city road networks.
> 5. **Settlement-metadata leakage.** We give the first side-channel analysis of proof-based RUC public statements, including the cadence–leakage tradeoff and bucketing mitigations, plus a selective-disclosure dispute protocol derived from the interval commitment structure.
> 6. **Implementation & artifacts.** A 226k-constraint Groth16 settlement circuit, charger service, and a fully receipted evaluation harness.

对照原列表的差异：每条都有一个被命名的概念（trilemma / policy-free TCB / ε-economic soundness / monotone degradation / enforcement exchange rate / settlement-metadata leakage），而不是实验编号。**命名的概念才会被别的论文引用和复述。**

---

## 四、新增工作量评估（只列本文档新提出的）

| 补充项 | 类型 | 工作量 | 阻塞关系 |
|---|---|---|---|
| 法规事实核引（OSNMA/Smart Tacho 2/Oregon RUC） | 写作+引证 | 1 天 | 无 |
| ε-economic soundness 定义 + 各实验重新挂接 | 写作 | 2–3 天 | 无（E1/E2 数字不变） |
| outage-DSIC proposition 形式化 | 写作 | 1 天 | 无 |
| 争议仲裁协议 + opening verifier 最小实现 | 协议+代码 | 3–5 天 | 不依赖 P0-2 |
| E5 元数据推断攻击 + cadence 泄漏曲线 | 实验 | 1–2 周 | 依赖 P0-2（proof-only statement 定型） |
| E4 成本对偶（摄像头→$/vehicle/year） | 数据+写作 | 2–3 天 | 依赖 E4 主线 |
| 泛化段落 + 不可链接性 future work | 写作 | 0.5 天 | 无 |

注意：表中超过一半是**纯写作层面的重新框定**，不新增实验风险；真正的新实验只有 E5 推断攻击一项，且复用已有数据。

---

## 五、一致性提醒

- ε-economic soundness 的措辞必须与 E1 既有口径兼容："机制演示非统计估计"在新框架下自然成立——ε 是对手类下的上确界测量，本来就不是人群统计量。
- 引用法规事实时分清：OSNMA 运营宣告（2025-07-24, EUSPA）、强制安装时点（2025-12-24 新注册商用车）、适用范围（商用车，**不是**私家车）——motivation 写商用车 RUC 为主战场，私家车作为外推，不要过度声称。
- 所有新增 claim 仍遵守文档维护规则：定理标"可证"，推断攻击结果出来前不预填数字。

---

## Sources

- [EUSPA: Galileo OSNMA Service Now Available to Users](https://www.euspa.europa.eu/newsroom-events/news/testing-operations-galileo-osnma-service-now-available-users)
- [Stoneridge: OSNMA tachograph mandatory from 2025](https://stoneridge-tachographs.com/en/news-events/osnma-mandatory-from-late-2025)
- [EUR-Lex: Implementing Regulation (EU) 2023/980 (smart tachograph technical specs)](https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX:32023R0980)
- [JRC Digital Tachograph: Smart Tachograph](https://dtc.jrc.ec.europa.eu/dtc_smart_tachograph.php.html)
- [Streetsblog: Oregon Launches Nation's First Road-User Charge (2026-04)](https://usa.streetsblog.org/2026/04/29/the-end-of-gas-pain-oregon-launches-nations-first-road-user-charge)
- [ODOT: OReGO Road Usage Charge Program](https://www.oregon.gov/odot/programs/pages/orego.aspx)
