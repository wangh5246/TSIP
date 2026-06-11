# TSIP-RUC Baseline 设计审计

> 日期：2026-06-10
> 目的：逐项核查所有 baseline 设计的准确性与可被攻击面，给出加固方案。
> 元原则贯穿全文：**Generous Baseline 原则**——所有建模选择系统性偏向 baseline，并在论文中显式声明。审稿人攻击 baseline 的唯一入口是"你弱化了对手"；把每个自由度都让给对手，这个入口就关死了。

---

## 0. 最重要的发现：仓库里有两套 baseline 体系，其中一套已失效

`TSIP_Baseline实验详细方案.md`（4月12日）的 7-baseline 矩阵——TSIP(Full) / No-Integ / Commit-Only / **RiseFL / Nebula / EIFFeL / Pure LDP**——属于 RUC pivot 之前的位置聚合论文。这些是 secure aggregation / FL 完整性方案，与计费结算**没有可比性维度**：它们防"恶意数据污染聚合"，RUC 防"理性用户少付钱"。`handoff_e1_tier1` §10 也还在引用这套计划。

**行动**：给该文件加 archived banner（"适用于聚合版 TSIP，不适用于 TSIP-RUC 论文"）。若 RUC 论文沿用任何一个 FL baseline，reviewer 一眼看出领域错位。

当前 RUC 论文的真实 baseline 体系是四层：

| 层 | Baseline | 角色 |
|---|---|---|
| E1 内部 | 约束消融分支（self-baseline） | 每条约束的边际价值 |
| E2 内部 | alpha=1 理论充分界 | 机制设计参照点 |
| E4 外部 | VPriv/PrETP/Milo spot-check 谱系 | 执法基础设施对比 |
| E5 外部 | GPS-upload | 隐私泄漏对比 |

以下逐层审计。

---

## 1. E4：spot-check 谱系 baseline

### 1.1 文献事实核查（已对原始论文核验）

| 系统 | 出处 | 执法机制 | 你的合并是否成立 |
|---|---|---|---|
| VPriv | Popa et al., **USENIX Security 2009** | 随机路侧 spot check（隐藏摄像头/巡逻车）+ 挑战协议 | ✓ 依赖路侧观察 |
| PrETP | Balasch et al., **USENIX Security 2010** | OBU + Optimistic Payment（同态承诺逐段费用）+ spot check 记录核对 | ✓ 依赖 spot check |
| Milo | Meiklejohn et al., **USENIX Security 2011** | 基于 PrETP，修复 audit 协议在 **driver collusion** 下的信息泄漏 | ✓ 仍依赖 spot check |

结论：**按 enforcement 轴合并为"spot-check 谱系"是公平的**——三者密码构造不同（这正是 Milo 对 PrETP 的改进点），但执法都依赖不可预测的路侧观察。两个写作要求：(a) related work 必须分开介绍三者并写对年份（2009/2010/2011）；(b) 合并表的表注明确"合并维度仅为执法基础设施，密码构造差异见 §related work"。设计文档 §13.1 已有此意，保持。

一个必须知道的细节：**PrETP 论文自称 "without any need for tamper-proof elements"**——它的卖点之一恰是不需要可信硬件。所以你的设计空间表里 spot-check 谱系与 TSIP-RUC 的交换关系是干净的对偶：**他们用路侧基础设施换掉可信硬件，你用可信硬件（现已法规化）换掉路侧基础设施**。这句对偶写进 §1.3，比单向"他们需要摄像头"更诚实也更有力。

### 1.2 被攻击点 A：P(caught) 模型过简（最大风险）

`P(caught) = 1-(1-c)^(fS)` 会被攻击为玩具模型。防御不是把模型做复杂，而是**把每个参数推到对 baseline 最有利的极端并声明**：

- 每次观察 = 完美检出（无漏检、无 GPS 误差争议）；
- 攻击者不知道摄像头位置（对 spot-check 最优；现实中摄像头位置会泄漏，Waze 类应用实时标注）；
- 不计 baseline 的误罚成本与争议处理成本；
- 摄像头按攻击者路径最优布置（而非预算约束下的静态布置）。

然后结论句式变为："**即使在每个假设都偏向 spot-check 的模型下**，达到确定性拒绝等价仍需 X cameras/km²。"这个句式让攻击模型简化的 review 意见失去力量——简化方向全部对你不利。

### 1.3 被攻击点 B："低覆盖 + 高罚金也能威慑"（必须正面处理）

经济学 reviewer 必然指出：威慑只需 `fine × P(caught) ≥ saving`，所以稀疏摄像头配大额罚金即可，何须城市级覆盖？这是 E4 当前模型的真实缺口。补一节 deterrence 分析：

- 反解等价罚金：给定摄像头密度 c，威慑 E1 测得的 saving 分布需要 `fine ≥ saving / P(caught)`。用你自己的 E1 数据（GeoLife p95 saving）算出来——稀疏覆盖下所需罚金会高得不成比例。
- 罚金的现实上限：法律比例原则（罚金须与违法所得相称）、误罚不可避免（GPS 漂移、车牌误读）→ 高罚金 × 非零误罚率在政治上不可行。引 ANPR 误读率公开数据。
- TSIP-RUC 的对应面也要诚实写：确定性拒绝同样会拒绝传感器故障的诚实用户——但你的 fallback 机制恰好是为此设计的（E2），且 fallback 是自动定价而非指控欺诈。**"误罚在 spot-check 里是指控，在 TSIP-RUC 里是多收费且有 E2 量化的上界"**——这是两种错误代价的本质差异，值一段。

这一节把 E4 从"数摄像头"升级为"威慑经济学对比"，且全部材料（E1 saving 分布、E2 penalty 界）已在库。

### 1.4 被攻击点 C：遗漏的对比对象

- **P4TC**（Fraunhofer/KIT，PoPETs 2020）：形式化最完整的 ETC 安全模型，但工作在 **DSRC/RSU 设定**——收费交互发生在路侧单元。必须引用；它不破坏你的 trilemma claim（RSU = 路侧基础设施列），反而是表格的好填充行。不引用会被认为文献功课不足，因为它自称"最全面的 ETC 形式化处理"。
- **KIT 的 ETC 隐私方案 survey（2023）**：用它的分类法自检你的设计空间表是否漏列，并在 related work 引用。这是 reviewer 检查你完备性时会用的同一份文献，先用它自查。
- **Smart tachograph 本身作为 baseline 行**（免费且锋利）：当前法规现状 = 认证轨迹交给检查员读取，零密码隐私。把它加进设计空间表作"trusted-reader"行——既是 motivation 的现状批判，又多一个真实部署的对比锚点。
- **PriPAYD**（Troncoso et al., PAYD 保险）：相邻域，related work 一句话即可，不需进表。
- 建议投稿前做一次 2024–2026 文献扫尾（IACR eprint / PoPETs / NDSS / USENIX 检索 "toll" "road pricing" "RUC" "zk"），我检索到的最新系统性工作止于 2020–2021，这对你的 "first" claim 是好消息，但需要投稿时点的再确认。

### 1.5 三城路网选择

北京/Porto/Rome 与四数据集对齐，公平 ✓。建议表注说明 T-Drive 与 GeoLife 共用北京路网，避免"为何只有三城"之问。

---

## 2. E5：隐私 baseline

### 2.1 被攻击点：明文 GPS-upload 是稻草人

"plaintext GPS upload" 当 baseline 太弱——没有任何严肃方案主张明文上传。修复：把 baseline 重命名并锚定到真实部署：

> **Policy-protected GPS collection（部署现状）**：Oregon OReGO 等真实 RUC 由商业 account manager（Azuga/emovis 类）收集完整 GPS 计费，隐私保护靠合同与数据保留政策，非技术机制。

这不是稻草人，是**今天真实运行的系统**，且"靠政策不靠技术"正是你 motivation 的现状批判。E5 表从 2 行扩为 4 行光谱：

| 方案 | 位置可见性 | zone 计费 |
|---|---|---|
| Policy-protected GPS（OReGO 现状） | 完整轨迹（对运营方） | ✓ |
| Trusted-reader tachograph（欧盟现状） | 完整认证轨迹（对检查员） | ✓ |
| Odometer-only | 零位置 | ✗ |
| TSIP-RUC proof-only statement | period 级元组 | ✓ |

这个光谱让 TSIP-RUC 的位置被夹逼出来，而不是与稻草人二元对比。

### 2.2 前提依赖

E5 的测量对象必须是 proof-only path（P0-2），且应包含创新性补充文档 §2.4 的元数据推断攻击——对自己方案的攻击做得越狠，baseline 对比越可信。

---

## 3. E1/E2 内部 baseline

### 3.1 E1 消融分支（已审计，基础扎实）

receipts、逐位封印、objective/billing 同源——这部分是全论文最难被攻击的。三个加固点：

1. **补一行 "all-integrity-off" 上界锚点**。当前各分支是单条约束消融，缺总攻击面：全部约束关闭时理性对手能省多少。这给所有单项数字一个分母（"zone binding 单独贡献了总暴露的 X%"），solver 现成，跑一次即可。没有这行，reviewer 可能问"单项消融加起来是否漏了交互项"。
2. 主表配置（distance_bucket=25m, radius=2）的取值理由进表注（综合审阅报告 §3.3 已提）。
3. 论文里分支用语义名（zone-binding ablation），代码名 no_xxx 留 artifact。

### 3.2 E2 的 alpha=1 内部参照

alpha=1 作为理论充分界 baseline 是干净的 ✓。一个补充：related work 中说明 **spot-check 谱系没有 outage 机制设计**——PrETP 的 Optimistic Payment 是"承诺后抽查核对"，传感器中断在这些方案里是故障处理问题而非激励问题。这使 E2 的"outage 作为机制设计"定位有了外部参照，而不是悬空的内部实验。

### 3.3 E6 性能对比的边界

不要与 VPriv/PrETP 论文里的 OBU 时序数字直接列表对比——硬件相差 15 年，任何方向的结论都会被攻击。正确做法：E6 只报自身绝对成本 + "可在驾驶中后台生成"的运营论证；如需外部参照，引用各方案的**渐近通信/计算结构**（每段一次承诺 vs 每 period 一个 proof）而非绝对毫秒数。

---

## 4. 行动清单

1. ☐ `TSIP_Baseline实验详细方案.md` 加 archived banner（FL baselines 不进 RUC 论文）
2. ☐ E4 模型参数全部推向 baseline 最优 + 论文显式声明 Generous Baseline 原则
3. ☐ E4 增加 deterrence 经济学小节（等价罚金反解，用 E1 saving 分布；误罚代价对比 fallback）
4. ☐ related work 补 P4TC（PoPETs 2020）+ KIT survey（2023）+ 用 survey 分类法自检设计空间表
5. ☐ 设计空间表加 "trusted-reader tachograph" 行；spot-check 行写成"基础设施换可信硬件"的对偶
6. ☐ E5 baseline 重命名为 policy-protected GPS collection，扩成 4 行光谱表
7. ☐ E1 补 all-integrity-off 上界行
8. ☐ E2 related work 注明 spot-check 谱系无 outage 机制设计
9. ☐ E6 不做跨年代绝对性能对比
10. ☐ 投稿前 2024–2026 文献扫尾，确认 "first" claim 时点

---

## Sources

- [VPriv/PrETP/Milo: The Phantom Tollbooth (USENIX Security 2011)](https://www.usenix.org/conference/usenix-security-11/phantom-tollbooth-privacy-preserving-electronic-toll-collection)
- [Milo 论文 PDF（含对 VPriv/PrETP spot-check 依赖的描述）](http://www0.cs.ucl.ac.uk/staff/s.meiklejohn/files/usenix11.pdf)
- [PrETP: Privacy-Preserving Electronic Toll Pricing (Semantic Scholar)](https://www.semanticscholar.org/paper/PrETP:-Privacy-Preserving-Electronic-Toll-Pricing-Balasch-Rial/c648aba11077ef95764e3162766fbda5b1de8ef5)
- [P4TC — Provably-Secure yet Practical Privacy-Preserving Toll Collection (IACR eprint 2018/1106)](https://eprint.iacr.org/2018/1106.pdf)
- [KIT: A Survey on Privacy-Preserving Electronic Toll Collection Schemes for ITS](https://publikationen.bibliothek.kit.edu/1000164328/155566448)
- [ODOT OReGO（account manager 模式）](https://www.oregon.gov/odot/programs/pages/orego.aspx)
