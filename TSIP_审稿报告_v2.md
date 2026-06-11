# TSIP 论文审稿与改善建议（v2）

> 基于对 main_1.tex 全文的逐段阅读，并对照近三年 USENIX Security / CCS / NDSS 的写作与评估范式（Nebula CCS'25、EIFFeL CCS'22、RiseFL S&P'24、ZKSL Usenix'24、Prio & Prio3、ELSA S&P'23 等）。本报告和已有的 `TSIP_审稿报告.md` 互补，聚焦在它没覆盖的几条关键线：**创新点突破空间、定理语义与威胁模型对齐、评估规模与真实性、写作规范与专业化排版**。

---

## 0. 一句话定位

**目前的 TSIP 是一篇"小而正"的 workshop / 区域会议稳投论文；若要冲 NDSS/CCS 主会，主要瓶颈不是技术正确性，而是 (1) 创新密度 (2) 评估规模 (3) 定理的"硬度"三个维度都处在及格线附近。** 下面按"打到几分"和"怎么提到几分"两个视角展开。

| 维度 | 当前位置 | 顶会期望 | 差距性质 |
|---|---|---|---|
| 问题定义 | 清晰、有新颖性 | 清晰、新颖 | **接近** |
| 核心技术 | 组合既有原语（Groth16 + Poseidon + ESA） | 有新原语、新协议证明技巧、或新系统抽象 | **中等差距** |
| 威胁模型 | 6 类攻击 A1–A6，覆盖不均 | 定理覆盖应与攻击集合一一对应 | **中等差距** |
| 形式化证明 | reduction-style 非正式论证 | game-based + hybrid argument | **中等差距** |
| 实证规模 | 50 / 200 / 500 / 1000 clients × 10 轮 | 顶会普遍 10K+ clients、多数据集、多 DP 机制 | **较大差距** |
| 写作/排版 | 结构完整、术语一致 | 顶会级精细打磨 | **小差距，可完全补齐** |

---

## 1. 创新点突破空间（如果你愿意做更深的改造）

你在提问里说"如果在阅读了我的全部工程发现我有可以让我的创新点有突破的改善"是欢迎的。**我认真读完全文后的判断是：现在这篇论文的"贡献硬度"在顶会审稿人眼里偏薄——因为它把几个已知原语（Groth16、Poseidon、MiMC、ESA、SVT、Laplace）拼接起来，没有一个属于 TSIP 原创的新技术构件。** 这不是致命伤（EIFFeL 本身也是组合拼接），但代价是你的技术叙事必须异常精彩，才能守住稀缺的版面。

下面按"改造成本从低到高"列四条**真正可以让审稿人眼前一亮**的突破方向，任选一条就能把论文从"还算可以"推到"有技术深度"。

### 1.1 ★ 最推荐：把 A3 sliding-window 搬进电路里（防守式突破）

**现状**：A3 gradual drift 目前靠 Shuffler 维护的累积位移状态来检查。这是整个论文里最软的一段，审稿人只要抓住"你把这个约束放在电路外，证明边界就塌了"就能打破论文声称的"cryptographically enforce"。

**改造**：设计一个新的辅助电路 `TSIPWindow`，把最近 $K_w$ 轮的位移累积和 $\sum_{j=w-K_w+1}^{w} d_j$ 变成一个电路内的 aggregator，以 Merkle 累积器（或新的链式承诺变量 $a_w = a_{w-1} + d_w - d_{w-K_w}$）的形式在电路内部强制验证 $a_w \leq K_w \cdot v_{\max} \cdot \Delta t$。

**收益（明确可写进 contributions）**：
- A3 从"成本提升"升格为"密码学意义上被阻断"
- 所有 6 类攻击全部进入强保证，Table 1 的 ✓✓✓ 可以横扫
- 电路规模预估从 1154 涨到约 2500–3500 约束，proof 仍然是 128 B；客户端证明时间从 0.31 s 涨到约 0.8–1.0 s（rapidsnark），仍然在 aggregation window 内
- 这是一个**可以写一整节**的新技术，因为在位置聚合语境下，把"跨轮累积约束"做进电路是一件非平凡的事

**为什么能打动顶会**：位置聚合场景的"连续性"在过去几年一直是 open problem（Bittau et al. Prochlo '17、Roth Nebula '19 都把 cross-round 留给"future work"），把它做严、做闭环，是一个有辨识度的技术贡献。

---

### 1.2 ★ 次推荐：对抗性建模的升级——从"点速度上限"到"移动模式感知"

**现状**：你的 $v_{\max}$ 是全局常数 110 m/s（飞机速度）。这个太宽松了——审稿人会问"为什么一个地面 App 要允许飞机速度？"，而且宽上限直接意味着 A3 drift 的 $v_{\max} - v_{\text{real}}$ gap 变大，residual-scope 变得很难辩护。

**改造**：引入**移动模式上下文**作为电路的额外 public input。客户端在 enrollment 时选择一个 transport mode 类别 $m \in \{\text{walk}, \text{bike}, \text{vehicle}, \text{transit}\}$，每个类别对应不同的 $(v_{\max}^{(m)}, a_{\max}^{(m)})$ 参数。电路内部根据 $m$ 选择正确的上界进行 C3 检查。

更进一步的版本：把 $m$ 本身也做成 zero-knowledge disclosure（不泄漏具体模式只泄漏 "mode 属于一个允许集合"），用 selector 电路在两组距离约束之间二选一。

**收益**：
- $v_{\max}$ 从 110 m/s 降到 40 m/s（车）或 2 m/s（步行），$d_{\max}$ 随之降一个数量级，A1/A3 的可观测边界大幅收紧
- 实证上，T-Drive 是出租车，GeoLife 是多模态，你现在统一当一个 vmax 处理，利用率其实被浪费了
- 模式感知的合理性可以写进 "what continuity really means in the real world" 这一小节

**风险**：用户可能切换模式时被错误拒绝，需要补一个 mode-transition 协议（e.g., warmup 重新走），这可以作为一个小 contribution。

---

### 1.3 Sybil attack 的 cryptographic hardening（A4 的正式化）

**现状**：A4 在 §Security 的描述是"multi-shuffler committee gating … DP attenuates marginal impact"。这两句话在顶会审稿人眼里几乎等于"没有防"。

**改造方向（三选一）**：

1. **基于 PoPs 的注册速率限制**：在 enrollment 时要求客户端绑定到一个有使用成本的 credential（TEE 证明、DID 证明、FIDO2 硬件密钥），使得 Sybil 的生成需要实际物理资源。这可以放在 §Threat Model 和 §Enrollment 之间作为一个新小节 "Admission Control"。
2. **跨客户端距离正则化**：要求同一时间窗口内，多个客户端的提交如果来自"几乎相同坐标"且绑定到不同 identity，需要附加一个 non-collision proof（用 Poseidon 做 bucket commitment，在 Shuffler 端 bucket 冲突触发额外验证）。
3. **注册锚点的链下 attestation**：引入一个 federated anchor set（例如多个独立 OIDC issuers），enrollment 时 $c_0$ 必须由至少 $t$ 个 anchor 联合签名。Sybil 成本从 $O(1)$ 升到 $O(t)$。

**收益**：A4 从"未被密码学覆盖"上升到"形式化的部分覆盖"，在定理里就可以加一条 bounded-Sybil 定理：在 $t$-of-$n$ anchor 不共谋的假设下，Sybil 数量 $\leq m$。

---

### 1.4 更深的理论贡献：为"cross-round continuity"给出形式化定义

**现状**：你把"cross-round trajectory continuity"作为核心贡献概念提出，但全文没有给它一个形式化定义（Definition block）。G1 是物理可行性，不是 continuity 本身。

**改造**：在 §Preliminaries 加一个独立 definition：

```
Definition (Cross-Round Trajectory Continuity).
A location aggregation protocol Π satisfies cross-round
trajectory continuity w.r.t. a physical-plausibility
predicate Φ if, for any PPT adversary A controlling at most
m < N/2 clients, and any accepted sequence of submissions
{σ_w^(i)}_{w=1..T}, it holds that:
  Pr[ ∃ i ∈ [N] \ Corrupt, w ∈ [T] :
       Φ(extract(σ_{w-1}^(i)), extract(σ_w^(i))) = 0 ] ≤ negl(λ).
```

然后把 G1 作为 Φ 的一个具体实例（distance bound），为 A3 sliding-window 情况再给一个 Φ_W 实例。这样论文就有了一个**可引用的抽象定义**，后续工作可以基于它扩展 Φ。顶会非常喜欢看到这种"定义先行"的贡献形式。

**收益**：这条配合 1.1 使用，价值翻倍——把 A3 也归到 Φ 的某个实例，定理覆盖就真的"齐了"。

---

## 2. 内容与论证层面的关键风险（必改）

### 2.1 [高] "first protocol to … cryptographically enforce" 这句话需要加限定

**位置**：Abstract、Introduction、Contributions、Conclusion 共 4 处。

**问题**：顶会审稿人对"first"类 claim 极度敏感。ZKSL '24、RiseFL '24 已经在 FL 场景提供了 cross-round 相关的 integrity 属性（虽然不是位置聚合）。Chainlink 的 PoL、Foursquare 的 location trust 机制也是相关工作。你目前的表述容易被说成"overselling"。

**建议改写**（每处都加上两个限定词）：
> TSIP is the first protocol **in the Encode-Shuffle-Analyze federated location aggregation setting** to cryptographically enforce **inter-round spatial plausibility** without revealing individual coordinates.

不要省掉"in the ESA federated location aggregation setting"——这个是你的真实贡献边界，而且是诚实且有区分度的。

---

### 2.2 [高] Theorem 与 Attack 的映射要显式化

**问题**：你提了 A1–A6，但论文正文从没做过"A_i ↔ Defense ↔ Theorem/Proposition"的一张表。审稿人必然要问"A4 的定理在哪""A6 的实验在哪"。

**建议**：在 §Security 开头加一张 "Coverage Map" 表：

```
Attack | Defense mechanism           | Formal statement        | Evaluation
-------+-----------------------------+-------------------------+------------
A1     | C3 distance constraint      | Theorem 1 (E1)          | §Eval-Headline
A2     | C5 identity commitment      | Theorem 1 (E4)          | §Eval-Headline
A3     | Sliding-window check        | Proposition 1           | §Eval-A3 (residual)
A4     | Admission control + DP      | Not formalized (scope)  | not evaluated
A5     | Chain state machine         | Theorem 1 (E2)          | §Eval-Headline
A6     | Groth16 soundness (CA1)     | Theorem 1 (E3)          | statistical bound
```

这张表如果你不自己写，审稿人的 major revision 一定会要你写。现在写比等他问再写有用。

---

### 2.3 [高] 实证规模对 NDSS/CCS 偏小

**事实**：你目前跑的是 N ∈ {50, 200, 500, 1000}, T = 10 rounds。对照：
- Nebula CCS'25: 简单 DP histogram 跑到 N = 1M
- EIFFeL CCS'22: N = 30K+
- RiseFL S&P'24: N 较小但换成了更深的 ML-model baseline 对比
- Prio3（最近）: 工业部署规模 N > 1M

1000 客户端、10 轮是**明显偏小**的规模。而且你的 1000 clients 其实也是 synthetic augment 的（T-Drive 只有 10,357 辆出租车，你 sample 的方式应该写清楚）。

**最低限度整改**（在不改数据集的前提下）：
1. 把主实验扩到 N = 10,000（用 T-Drive 全量或做 bootstrap resampling），T = 30+ 轮。
2. 把 §Eval-Scale 的投影做成实测：客户端证明用本地并行化跑出真值，不要停在 1000。
3. 加一条 "Deployment at realistic scale" 的讨论，明确说明 per-verifier 吞吐 4,000 proof/s × 8 核 = 32K proof/s，能支持 N = 10M（10 分钟 aggregation window）。

**推荐整改**（如果时间允许）：
1. 加一个公开真实数据集 Porto Taxi（比 T-Drive 大，~1.7M traces）或 NYC Taxi（~170M trips）。
2. 实测到 N ≥ 100K 的吞吐（哪怕只跑一个 subset 做 profile）。

---

### 2.4 [中高] 移动端/约束设备测量缺失

**问题**：你在 Conclusion 写 "we anticipate that TSIP's proving latency on mobile-class hardware would remain within the aggregation window; a first-party mobile measurement is deferred to extended artifact evaluation."

**NDSS/CCS 读者会直接减分**，因为位置聚合天然是 mobile scenario。"anticipate" 在顶会实证论文里是审稿人反感的词。

**建议**：
1. **至少**：用 ARM 模拟器（QEMU-user + rapidsnark 交叉编译）跑 M 个代表性 proof，给出上界。
2. **最好**：跑一台真实的 Android/iOS 设备（用 circom-wasm in Capacitor 或 snarkjs-rn）。这个工程投入大概 1–2 周，但回报非常大：没有 mobile 数据，很多审稿人就会给"nice idea but unproven at scale" 的评价；有 mobile 数据（哪怕只给一个 Pixel + 一个 iPhone 两点数据），就完全堵住这一路攻击。

---

### 2.5 [中] A6 "forged proof" 实验不能简单跳过

**现状**：你在 §Eval-Headline 的 Table 1 脚注说 "A6 column is omitted because forged-proof rejection is statistical (1-negl(λ)) and cannot be meaningfully reported in a 500-round experiment."

**问题**：这个话是对的，但审稿人会反手问"那你为什么做 A1/A2/A5 的实验？这些也是密码学保证的。"答案是因为你想做边界测试（S-curve）。同样的逻辑也适用于 A6——你应该做一个**malleability test**：把一个合法 proof 的某些比特翻转，或者拿另一个 submission 的 proof 配一个新的 public input，看 verifier 是否 100% 拒绝。实验成本：几行代码，几分钟机时，换来"empirical validation of Groth16 soundness in our harness"的一行表格。

---

### 2.6 [中] 与 2024–2025 的新工作对齐不足

**关键遗漏**：
- 没引 **Marius Lombard-Platet et al. "Zero-Knowledge Location Proofs" (NDSS 2024)**（如果存在）—— check the real title
- 没引 **Binding ID in ZK-SNARK context** 的最新工作
- 没引 **VRF-based location commitment** 相关工作
- 没引 **Differential Privacy for Spatial Data**（DPSpatial, 2023–2024）最新综述

**建议**：在 §Related Work 加一小段 "Concurrent and Recent Work (2024–2025)"，专门讨论这一年内的同主题工作，说明与 TSIP 的区别。顶会评审通常会在同一批里看到相似主题的论文，写清 concurrency 是基本功。

---

### 2.7 [中] 关于"truth gap at enrollment"的定位

**现状**：你把 enrollment 阶段无法验证"初次位置真实性"归为 limitation。

**但这正是 A4 Sybil 的攻击入口！** 换句话说，TSIP 当前的威胁模型里 A4 没有被防的根本原因是 enrollment 没有 anchor。**把这两个 limitation 合并成一个，并在 §1.3 里提出 anchor 改进**，论文的 limitation section 会显得"你已经意识到并给出了路径"而不是"你只是承认弱点"。顶会尤其喜欢看到 limitation 是**被结构性地理解**的，而不是被陈述的。

---

## 3. 写作与排版（专业化 / "看起来像顶会"）

下面按你拿到这些建议就能立刻改的程度排列。

### 3.1 [bug] 重复的 `\label`

**位置**：line 764
```latex
\subsection{ZK Distance Verification Circuit}\label{sec:circuit}\label{sec:circuits}
```

同一个 subsection 挂了两个 label。**删掉 `\label{sec:circuit}` 保留 `\label{sec:circuits}`**（或反之，保证与所有 `\ref` 一致）。这是编译不报错但审稿人一眼看出来的低级问题。

### 3.2 Abstract 写作节奏（顶会范式）

**现状**：你的 Abstract 先说 "Privacy-preserving location aggregation systems today..."，然后才到 TSIP。这是 NDSS/CCS 比较不喜欢的节奏——它们更偏好四段式：

1. **问题**（1–2 句，what's broken）
2. **Insight / 贡献**（1 句，we observe / we propose）
3. **技术实现**（2–3 句具体技术）
4. **结果**（1–2 句具体数字）

建议重写版（参考 Nebula/EIFFeL 节奏）：

> **Motivation.** Privacy-preserving location heatmaps remain vulnerable to a class of cross-round trajectory attacks—teleportation, replay, and identity-swap—in which each submission is individually valid but the sequence across rounds is physically impossible.
>
> **Our approach.** We formalize this class as a violation of *cross-round trajectory continuity* (Def. 1) and present TSIP, the first protocol to cryptographically enforce it in the Encode-Shuffle-Analyze pipeline for federated location aggregation.
>
> **Technical core.** Each submission carries a 128-B Groth16 proof that chains the current location commitment to its predecessor, simultaneously certifying physical plausibility, binding the submitted payload, and anchoring a per-user secret—all without disclosing any coordinate.
>
> **Results.** On T-Drive and GeoLife with up to 1,000 clients, TSIP achieves 100% detection of A1/A2/A5 attacks at ~2 KB/submission communication overhead, with Jaccard parity against the no-integrity Nebula baseline under identical DP parameters.

每段第一个词用粗体放在开头，是目前三大顶会 Abstract 正在流行的写法（EIFFeL CCS'22、ELSA S&P'23 都这样写）。

### 3.3 引言的 "Gap Paragraph" 不够尖锐

**现状**：§1 第二段 "However privacy does not ensure integrity…" 开头过平。

**改造**：把第二、三段合并成一个 "Gap" 段落，开头用一个**具体的、刺痛审稿人的反例**：

> *A malicious user in Beijing reports herself in the Forbidden City at 10:00, at the Great Wall at 10:01, and back in Tiananmen at 10:02. Each submission is a valid LDP-noised histogram vector, each survives shuffler-side integrity checks, and the released heatmap faithfully integrates all three into its count. The violation is not detectable by any privacy mechanism; it is detectable only by a verifier that relates the three submissions in time. Today no federated location system enforces this relation.*

具体的反例比抽象的 "teleportation" 更能让审稿人的脑内仿真跑起来。CCS/NDSS 过会的引言一定是有类似反例的，单纯的抽象 gap 描述不够。

### 3.4 图的数量和信息密度

**现状**：你现在正文只有 5 张图（attacking example、model、scurve、ratio、utility）。实际 `figures/` 目录里还有 fig1_architecture_v2, fig2_protocol_sequence, fig3_commitment_chain, fig4_zk_performance, fig5_security_30rounds, fig6_utility_30rounds 等等——**大量做好的图没有用进正文**。

**建议必加**：
1. **Protocol sequence diagram**（你已经有 fig2_protocol_sequence）：在 §System Design 加入，一个 client-shuffler-aggregator-decoder 时序图比文字 Algorithm 1 更直观。
2. **Commitment chain diagram**（你已经有 fig3_commitment_chain）：在 §Commitment Chain 加入。
3. **Circuit constraint block diagram**：C1–C5 五组约束的连接关系图（这个似乎没做，建议画一张）。

顶会论文 14 页左右通常 8–12 张图表；你现在 5 张偏少。

### 3.5 表的排版一致性

**现状**：Table 1 (positioning) 和 Table 2 (ablation) 的字体大小、间距、宽度都不一致。

**建议**：统一用
```latex
\footnotesize
\setlength{\tabcolsep}{4pt}
\renewcommand{\arraystretch}{1.1}
```
这三个参数值在所有主要表格里保持一致。另外：
- Table 1 用了 `\tabularx{\textwidth}` 横跨双栏，后面的 ablation 表是单栏——这是正确的选择，但要检查 Table 1 的内容是否真的需要双栏宽度（Prio 那行 "SNIP for range checks" 确实挤，但可以缩）。
- `\midrule` 之前加 `\midrule[0.08em]`（稍粗）或 `\cmidrule` 分组，能让类别边界更清晰。

### 3.6 数学符号的一致性

扫描全文，有几处不一致：
- 位置写过 $(x_w^{(i)}, y_w^{(i)})$（§Prelim），也写过 $x_w$（§System）。**统一用 $\mathbf{p}_w^{(i)} = (x_w^{(i)}, y_w^{(i)})$**，省得审稿人问"同一个人的坐标有几种写法"。
- 单位：$\SI{128}{B}$ 和 128 B 混用；$\SI{6600}{m}$ 和 6,600 m 混用。统一用 `siunitx` 的 `\SI{...}{...}`。
- 承诺链：$c_w$ 和 $\mathrm{com}_{\mathrm{sec}}$ 的记号风格不一致（一个是斜体小写，一个是 $\mathrm$ 带下标）。统一成 $\mathrm{com}_w$ 和 $\mathrm{com}_{\mathrm{sec}}$ 或都用斜体。

### 3.7 Contributions 的写法

**现状**：三条 contribution 每条都是一段文字 + 数字堆砌。

**顶会惯例**：每条 contribution 都以**一个动词短语开头**，用**一句话说清贡献**，再给**1–2 个支撑性量化**。

改写示范：

> **We formalize cross-round trajectory continuity** as a new property for federated location aggregation (Def. 1), closing a gap in prior ESA-based systems which verify submissions only in isolation.
>
> **We design a minimal-overhead ZK construction** (§4) that enforces this property through 1,154 R1CS constraints and a 128-B Groth16 proof, preserving the ESA pipeline's aggregation logic and its pure ε-DP release intact.
>
> **We empirically validate** on T-Drive and GeoLife with up to 1,000 clients, achieving 100% detection of A1/A2/A5 attacks, Jaccard parity against the no-integrity baseline, and a deployment bottleneck of ~4,000 proofs/s per verifier core.

注意三条都以"We [VERB]"开头，这是 Nebula/EIFFeL/ELSA 共同采用的模式。

### 3.8 Related Work 结构

**现状**：三小节 + ZK primitives 一节，排列尚可。

**建议微调**：
- 每个子节末尾用一句**与 TSIP 的 differential statement**结尾，粗体或斜体标出："**Unlike [system X], TSIP also enforces [property Y]**."——这叫做 related-work 的 "delta sentence" 惯例。你现在 §2.1 末尾有这类句子（"TSIP builds on the same ESA pipeline…"），但 §2.2 和 §2.3 末尾也需要，现在一个是"TSIP contributes a cross-round relation…"，另一个是"The combination of cross-round continuity and pure ε-DP release is, to our knowledge, new."——第二个太弱，建议改成类似 §2.2 的 delta 写法。
- Table 1 （positioning）应该提早，**放在 §Related Work 第一段之后**。现在它排在中间，但读者的眼睛会先扫表格，因此先放表 → 随后用三个子节解释每一行，是更自然的顺序。

### 3.9 排版细节 checklist

- Algorithm 1 里 `\State Aggregators sum shares independently; ...` 一行太长，建议拆成 2–3 行。
- §4.3 "Warmup Policy" 只有一段两句话，不值得一个 `\subsubsection`；并回 §Enrollment 那节。
- `\begin{definition}[G1: Trajectory Plausibility]` 连续 3 个 definition 环境占了小半页，可以把三者并排一个 box（`\begin{tabular}` 或 `minipage` 并列）节省空间。
- §Evaluation 每个 subsection 都用 `\paragraph{}` 起始，信号很好；保持一致。
- bibliography 里 `biber` 必须和 `biblatex` 配套；检查 `main.bib` 的 entry key 是否与 `\cite{}` 完全一致（目前看来一致，good）。
- 行号 `\usepackage[switch]{lineno}` 投稿前不要删（审稿需要），camera-ready 再删。现在投稿版本正确。
- `\IEEEpeerreviewmaketitle` 放对了位置。
- Abstract 后一般加 `\IEEEpeerreviewmaketitle`，但如果用的是 NDSS 模板则不需要——看你最终投向哪个会，对应更换模板。

### 3.10 "不专业的措辞"需要警惕的词

扫一遍全文：
- "This paper presents…" / "We present…"：顶会偏好 "We present"，统一用主动语态。
- "Crucially" / "Importantly"（用了两次）：顶会审稿人对这类修饰词敏感，建议删。
- "At first glance, the required relation appears simple"：这一句挺好，保留。
- "inspire further work" / "We hope it inspires…"（Conclusion 末句）：**删掉**。这句话在顶会审稿里几乎必被画线吐槽（过于虚）。换成具体的下一步研究方向。
- "to the best of our knowledge"（用了两次）：**统一改成 "to our knowledge"**，顶会写作更简洁。

---

## 4. 评估部分的额外建议（关于科学性）

### 4.1 FRR 在 N=50 时 4.02% 的解释

**现状**：你在 §Eval-Ablation 和 §FRR Remark 两处都指出 4.02% 的 FRR 来自 SVT 而非 circuit。

**问题**：这个数字对 DP 感兴趣的审稿人很敏感，因为 SVT-induced FRR 不是你的 contribution，是参数选择问题。

**建议**：
1. 补一个 "FRR decomposition" 小表：circuit FRR、chain-state FRR、SVT FRR 分开报。现在你的说法是"circuit FRR = 0"，那就直接把这三列列出来，数字会更有说服力。
2. 加一个 $\tau$ 敏感性分析（SVT threshold $\tau \in \{1.0, 2.0, 3.0, 4.0\}$），让审稿人看到 FRR 随 $\tau$ 的单调关系。这个实验量很小，但可以彻底消除"你选 $\tau = 3.0$ 是为了让 FRR 好看吗"的质疑。

### 4.2 S-curve 的精度

**现状**：S-curve 从 0 到 7200 m，50 m 步长一次，边界 6534 m，距离 6600 m 的 66 m 差被归因于"fixed-precision $d^2_{\max}$ 编码"。

**建议**：把 bin 改成 10 m 步长（实验量 × 5），重跑一次。0–7200 / 10 = 720 个点，用 rapidsnark 在一个 session 内可以 15 分钟跑完。这会让 "66 m 差" 变成"$d^2_{\max}$ rounding with error bound ≤ 10 m"，精度上提一档。

### 4.3 A3 residual bound 需要一个数学表达式

**现状**：§Eval-A3 描述很文字化。

**建议**：给一个封闭形式的 residual drift bound：
$$d_{\text{residual}}(K_w, v_{\max}, \Delta t, \delta) = K_w \cdot (v_{\max} - v_{\text{real}}) \cdot \Delta t$$
然后在图中用这条曲线标出 "feasible-infeasible" 的划分，让 A3 的 residual 规模可以定量理解。

### 4.4 与 Nebula 的 Jaccard 对等性要更严谨

**现状**：你说 "On T-Drive dense urban dataset, the released heatmap achieves Jaccard parity with the no-integrity Nebula baseline"。

**问题**：Jaccard parity 只是 "≈1.00 vs ≈1.00"，这在 T-Drive 上太容易达到，不能作为强证据。

**建议**：在 GeoLife（更 sparse 的数据集）上也做一次 Jaccard 对比，并报 RMSE（能分辨 1.00 和 0.98 的情况）。如果 GeoLife 上 TSIP 和 Nebula 的 Jaccard 差 < 1%、RMSE 差 < 5%，那个 claim 会硬得多。

---

## 5. 具体到某一行的字词建议（选取若干）

| 位置 | 现状 | 建议改成 |
|---|---|---|
| L61 | "Privacy-preserving location aggregation systems today release heatmaps that are private but not necessarily truthful" | "Privacy-preserving location aggregation systems release heatmaps whose privacy is established but whose **integrity is not**." |
| L108 | "This gap is structural rather than incidental." | "This gap is structural, not incidental, and cannot be closed by tuning existing primitives." |
| L166 | "A sound solution must therefore provide four properties simultaneously" | "Any sound solution must provide **four properties simultaneously**, which existing systems address at most individually:" |
| L215 | "A key technical barrier is specific to the Encode-Shuffle-Analyze pipeline." | "The key technical barrier is ESA-specific:" |
| L840 | "it is useful to summarize how these protections compose" | "we summarize how these protections compose" |
| L1279 | "TSIP demonstrates that trajectory integrity and location privacy need not be in tension." | "TSIP demonstrates that trajectory integrity and location privacy **are compatible** in practical federated aggregation." |
| Abstract: "Crucially" | "Crucially, this proof is inserted *upstream* …" | 删掉 "Crucially"，直接 "This proof is inserted upstream …" |

---

## 6. 优先级落地清单

如果只改一晚上：
- [ ] 3.1（双 label 修复）
- [ ] 2.1（"first …" 的限定词）
- [ ] 3.2（Abstract 重写为四段式）
- [ ] 3.7（Contributions 动词开头）
- [ ] 3.10（"inspire" / "crucially" / "to the best of our knowledge" 全局替换）

如果有一周：
- [ ] 2.2（Attack ↔ Defense ↔ Theorem 显式映射表）
- [ ] 2.5（A6 malleability empirical 小表）
- [ ] 3.3（引言加具象反例段）
- [ ] 3.4（加 protocol sequence & commitment chain 图）
- [ ] 4.1（FRR decomposition + τ sensitivity）
- [ ] 4.3（A3 封闭 residual bound）

如果有三周：
- [ ] 1.1（把 A3 sliding-window 搬进电路）——**这是最大的杠杆**
- [ ] 1.4（cross-round continuity 的正式定义）
- [ ] 2.3（实验规模扩到 N = 10K）
- [ ] 2.4（mobile 测量）
- [ ] 2.6（2024–2025 concurrent work 对齐）

如果时间充裕做大改（推向 NDSS 主会）：
- [ ] 1.1 + 1.2 + 1.4 合一起做
- [ ] 加一个新的 real-world 数据集（Porto / NYC Taxi）
- [ ] 写一版 game-based security proof 放进 Appendix
- [ ] 开源 artifact 冲一下 artifact-available 徽章

---

## 7. 我对"能投哪个会"的粗略判断

按改造深度对应命中概率：

| 改造范围 | 推荐目标 | 命中概率（主观） |
|---|---|---|
| 只做 §3 写作打磨 + §5 字词修缮 | IEEE S&P Workshop、WPES、CODASPY、DSN | 较高 |
| + §2 威胁模型对齐 + §4 评估修缮 | PETS（SoCal）、ACSAC、ESORICS | 中等偏高 |
| + 1.1（电路内 sliding-window） | NDSS、USENIX Security | 中等 |
| + 1.1 + 1.2/1.3 + §2.3 N=10K 实验 | CCS、NDSS | 中等偏高 |
| 所有 1.1–1.4 都做 + 实证规模上量 + 新数据集 + 正式 game-based proof | CCS / S&P | 可一搏 |

---

**最后一句：**TSIP 现在是一个"诚实、干净、边界清晰"的小系统论文；它缺的不是正确性，而是**技术辨识度**和**实证厚度**。要把它推到 NDSS/CCS，我最强烈推荐的动作是 **§1.1（A3 搬进电路）+ §1.4（定义形式化）+ §2.3（N=10K 实测）**这三件事——加起来大概 3 周工程，换回来的是一个真正站得住的顶会投稿。
