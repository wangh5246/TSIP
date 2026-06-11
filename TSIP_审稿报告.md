# TSIP 论文审稿报告
**基于实证的综合审阅：内容、结构与排版**

> 参考材料：TSIP main.tex 全文；Nebula (CCS 2025)；EIFFeL (CCS 2022)；NDSS 2024/2025 投稿规范与接受论文风格。
> 审阅逻辑：所有结论均来自对照阅读，不来自臆测。

---

## 一、总体判断

论文的核心机制是扎实的：Groth16 commitment chain + ESA pipeline 的结合点清晰，1154 约束的极简电路是合理的设计选择，三条定理的框架也是完整的。当前的主要风险不在技术深度不够，而在**审稿人会沿着你已经自行开口的几个缺口打进来**。以下按风险等级从高到低逐条列出。

---

## 二、内容与论证问题（Content Issues）

### C1【高风险】主表与 Baseline 可信度问题

**具体位置：** §4.2 (Baseline Fidelity)、Table 2 (tab:comparison)

**问题所在：**
你已经在 §4.2 里诚实地区分了 Class 1 (fidelity-exact) 和 Class 2 (mechanism-analogue)，并在表格中用 `\midrule` 分隔两类，caption 也加了 $^\dagger$ 注释。这是正确的做法。但现有排版仍然有一个未解决的张力：**表格标题写的是 "Headline attack detection"**，暗示表内所有行都是对等的 headline comparison——而 Nebula / Pure LDP / EIFFeL-style 三行在这个语境下无法做到这点，因为它们根本不是为检测 A1/A2/A5 设计的，TPR 全 0 是设计上的必然，不是你系统的"优胜"。

审稿人的合理反应是：Nebula/Pure LDP/EIFFeL TPR=0 是废话，这张表证明的不是你对原系统的 superiority，只是证明"专门为检测 continuity 设计的系统能检测到 continuity violation"。

对照 Nebula 论文（CCS 2025）和 EIFFeL 论文（CCS 2022）的 evaluation 组织：两篇论文都**把 mechanism-level comparison 放在单独节里**，主表只做 overhead/utility 对比，从不在检测率表里把"根本不做检测"的系统和"专为检测设计"的系统并列作为主要发现呈现。

**建议行动（分两步）：**
1. 把 Table 2 标题改为类似 "TSIP component ablation and mechanism ordering"，并把 Class 2 的三行明确移到一个独立的小表（或附录），标题改为 "Mechanism-analogue compatibility study"。
2. 主表只保留 TSIP-Full / Commit-Only / No-Integrity 三行，作为 ablation study 呈现，这才是表格的真正科学价值所在。Nebula/LDP/EIFFeL 的 Jaccard / Comm 对比（这是有意义的比较）可以单独用一个小表展示。

---

### C2【高风险】威胁模型 A1–A6 与定理覆盖不对齐

**具体位置：** §2.2 (Threat Model)、§3 (Theorem 1)、Table tab:eval-map

**问题所在：**
你的威胁模型列了六类攻击 A1–A6。你的 Theorem 1 证明了四条 attack path E1–E4。这两者之间的映射关系**在正文中从未显式写出**：

| 攻击 | 定理覆盖 | 当前状态 |
|------|----------|----------|
| A1 teleportation | E1 (C3 violation) | 主实验闭环 ✓ |
| A2 identity swap | E4 (C5 violation) | 主实验闭环 ✓ |
| A3 gradual drift | Proposition 1 only | 只有 cost elevation，不是 prevention |
| A4 Sybil | 描述性段落，无定理 | 未系统性实验 |
| A5 replay | E2 (chain state) + state machine | 主实验闭环 ✓ |
| A6 forged proof | CA1 assumption 直接引用 | 未在主实验中体现，以"统计意义上无法在500轮内报告"为由省略 |

对照 EIFFeL 的组织方式：EIFFeL 在 §2.3 Threat Model 之后立即接 §2.4 Solution Overview，在 Solution Overview 里明确列出"每个 security goal 对应哪个 cryptographic primitive"（见其 Fig. 1 表格：Input Privacy → Shamir's Threshold Secret Sharing；Input Integrity → SNIP）。这种一一对应的显式映射让审稿人无法找到"哪个 goal 没有被证"的漏洞。

**建议行动：**
在 §3（Security Analysis）开头加一个显式的 mapping 小表或段落，明确说明：
- A1/A2/A5/A6 → Theorem 1 (E1–E4 paths) — 加密强保证
- A3 → Proposition 1 — cost elevation，明确不是 full prevention
- A4 → 超出当前加密保证边界，DP 层提供部分衰减，显式 scope

这样做，reviewer 在看到 A3/A4 没有完整闭环时，你已经先于他把原因说清楚了，而不是让他发现你没说。

---

### C3【高风险】"statistically indistinguishable" 是修辞，不是统计结论

**具体位置：** Abstract 末段；§4.3 末段；§4.5 关于 utility

**问题所在：**
Abstract 和正文多次使用 "statistically indistinguishable from Nebula baseline" 这个表达。但读遍整个 evaluation 部分，没有看到：
- 每个数据点的重复运行次数（runs）
- 均值 ± 标准差
- 95% 置信区间
- 任何显著性检验（t-test、Mann-Whitney、permutation test 等）

Table 2 里 TSIP-Full 的 Jaccard 写的是 `$\approx 1.00$`，Nebula 写的是 `1.0000`——这个数字的格式本身就在暗示 Nebula 是精确值、TSIP 是近似值，而你的主张是两者"无差异"。

对照 Nebula 论文：在其 §5 Evaluation 里，每个 utility 数字都来自多次独立运行，并报告了均值和误差。即使是纯系统论文，NDSS 2024/2025 的接受稿也越来越多地在 utility claim 上提供 error bars 或至少说明 "results are averaged over X independent trials"。

**建议行动：**
- 把所有涉及 utility 的实验（Jaccard, RMSE）改成至少 5 次独立运行，报告 mean ± std。
- 把 "statistically indistinguishable" 改为经过实际检验支撑的表述，例如 "a Wilcoxon signed-rank test yields p > 0.05" 或 "mean Jaccard difference < 0.001 (95% CI: [x, y])"。
- 如果 Jaccard 数字稳定（可能本来就是），这个修改的实际工作量很小，但可以把 abstract 里最脆弱的 claim 变成最坚固的。

---

### C4【中风险】Theorem 1 定义—引理—攻击路径的映射不清晰

**具体位置：** Definition def:plausibility（6条约束(i)–(vi)）、Lemma lem:circuit（5条约束 C1–C5）、Theorem thm:soundness（4条攻击路径 E1–E4）

**问题所在：**
有三套编号系统叠加在一起：

- **Definition 2（Plausibility）**列了 6 个 constraints: (i) distance, (ii) chain consistency, (iii) payload bound, (iv) identity exclusivity, (v) payload-proof binding, (vi) identity-secret binding

- **Lemma 1（Circuit Correctness）**证明了 5 个电路约束 C1–C5

- **Theorem 1 的证明**分了 4 条互不相交的 attack paths E1–E4

这三套编号之间的关系审稿人需要自行推断：C3→E1，C1/C2→E2，C4→E3，C5→E4；而 Definition 的 (iii) payload bound 哪里去了？(ii) chain consistency 和 E2 的关系是电路保证还是 state machine 保证？

一个关心 technical consistency 的审稿人（NDSS CFP 明确说 reviewer 会关注这点）会提问：Definition 2 列了 6 项，但 Lemma 1 只检查了 5 个约束，Theorem 1 只证了 4 条路径，这个数字递减是否暗示有什么保证丢失了？

**建议行动：**
在 Theorem 1 的证明前加一个短段（3–4行），显式建立映射：
"The six constraints of Definition~\ref{def:plausibility} are enforced through the following mechanisms: (i)–(iii) via circuit constraints C3, C1/C2, and C4 respectively, addressed by E1–E3; (iv)–(vi) via C5 and the state machine check, addressed by E4 and E2. Constraint (iii) payload size bound is enforced by the circuit parameter $P_{\max}$ and is not separately attacked because no adversary gains from undersizing the payload."

这个段落只有几句话，但能彻底消除审稿人对"6→5→4"的疑虑。

---

### C5【中风险】Abstract 信息密度过高，主线被稀释

**具体位置：** Abstract 全段

**直接比对：**

| | 摘要字数 | 关键数字数量 | 机制术语数量 |
|---|---|---|---|
| Nebula (CCS 2025) | ~200 词 | 2个 (0.0036s, 0.0016MB) | 约3个 |
| EIFFeL (CCS 2022) | ~100 词 | 1个 (2.4s) | 约2个 |
| TSIP (当前版本) | ~250 词 | **9个以上** (128B, 6534m, 2KB, 0.31s, 4.02%, 0.17%, N≥500, ε=1.0, δ=0) | **约10个** |

TSIP abstract 里同时出现了：Poseidon2 chain、Groth16、P4/P5 隐式提及（payload digest + per-user secret）、committee attestation、sliding-window、pure ε-DP、100% detection、6534m boundary、2KB、0.31s、FRR、N≥500 改善。

NDSS 官方指引明确说 abstract 应 "accessible and compelling to a general security researcher"。当前的 abstract 更像是一个 spec sheet，而不是一个 compelling narrative。第一遍阅读时，读者很难提炼出 "这篇论文的核心洞见是什么"。

**建议改写框架（不超过 200 词）：**
1. 问题（2句）：location heatmaps 现在可以 private 但 not truthful；cross-round attacks 无法被现有系统检测。
2. 核心机制（2–3句）：TSIP 是第一个在 ESA pipeline 里用 Groth16 proof chain 强制执行 cross-round continuity 的协议；proof 是 128B constant size，插在 aggregation 上游，不破坏现有 DP 保证。
3. 主要结果（2句）：100% TPR on A1/A2/A5，Jaccard equivalent to no-integrity baseline，2KB overhead。
4. 明确的 scope（1句）：不声明 ground-truth presence，enrollment truth gap 是 acknowledged limitation。

删除 abstract 中的：committee attestation、sliding-window 具体参数、6534m（→留给正文）、N≥500 改善（→留给正文）。

---

### C6【中风险】Mobile-class latency 不应作为 deployment claim

**具体位置：** §4.4 末段 "Mobile-class projection"

**问题所在：**
"Based on published Groth16/BN254 microbenchmarks on Snapdragon-class mobile cores, we project client proving latency on mobile devices in the 1.5s–2.5s range, which remains within the per-minute aggregation window."

这是一个 projection，不是测量。在当前位置（§4.4 Scalability 节），它紧跟在真实测量数据之后，在叙述语气上很容易被误读为"deployment 已经评估"。

对照 Scrappy (NDSS 2024)：该论文在实验部分明确对三类设备（PC、server-class、ARM embedded）做了实测，而非 projection。NDSS 近年审稿人对"系统可部署性"的要求越来越高。

**建议行动：**
把 mobile projection 这段移到 §5 Conclusion 的 "Future directions" 里，措辞改为 "Based on published microbenchmarks, we anticipate that TSIP's proving latency on mobile-class hardware would remain within the aggregation window; a first-party mobile measurement is deferred to extended artifact evaluation."

不要在 evaluation 节里给 projection 超出其应有的分量。

---

### C7【中风险】FRR 的语义需要更清晰的分层

**具体位置：** Abstract；Table 2；§4.5 末段 "Note on FRR and utility"

**问题所在：**
"4.02% FRR" 在 Abstract 中和 Table 2 headline 里以裸数字出现时，审稿人的第一个问题是：这是 ZK circuit 的 false reject 还是 DP layer 的 false reject？

你在 §4.5 最后一段解释了 "FRR 主要来自 SVT threshold，不是 ZK circuit"——这个解释是正确的，但位置太晚，而且在 evaluation 的最末尾，审稿人可能已经带着先入为主的疑问读过前面所有内容了。

此外，Table 2 里 Commit-Only 的 FRR = 0.0000，而 TSIP-Full 是 0.0402。如果审稿人不理解 FRR 来源，他会合理地得出"加了 ZK proof 之后 FRR 从 0 跳到 4%"这个错误结论——这会被解读为 ZK circuit 造成了 4% 的误杀。

**建议行动：**
在 §4.1 (Experimental Setup) 的 metrics 列表里，把 FRR 的定义改成两层：
- *Circuit FRR*: fraction of benign submissions rejected by the Groth16 verifier — 这个应该是 0。
- *Pipeline FRR*: fraction of benign submissions ultimately excluded from the aggregate (combining circuit rejection and SVT suppression).

然后 Table 2 里报的是 Pipeline FRR，并在 caption 加一句 "Pipeline FRR is dominated by SVT suppression; circuit-level FRR is 0 for all configurations."

---

## 三、结构与叙事问题（Structure Issues）

### S1【需要改进】编号系统过多，叙事碎片化

**具体位置：** 全文

当前论文同时使用了 9 套编号系统：A1–A6（攻击）、C1–C5（电路约束）、E1–E4（攻击路径）、L1–L8（防御层）、P1–P5（协议机制）、CA1–CA4（密码假设）、G1–G3（安全目标）、以及各类定义/定理/引理编号。

对照 Nebula 和 EIFFeL：两篇论文几乎不使用内部编号系统，而是用段落标题（bold paragraph headers 或 subsection headers）来组织内容。EIFFeL 的 Threat Model 只是分了 "Malicious Server" 和 "Malicious Clients" 两个 bullet，不给它们编号。

编号密度高的论文会给审稿人两个信号：(1) 作者在用编号掩盖没有理清楚的逻辑；(2) 系统规格说明书多于研究论文。

**建议：**
- 删除 L1–L8 这套防御层编号（Table tab:tsip_defense_layers）——这个表在正文中几乎没有被引用过，审稿人读到它会觉得是冗余。把关键信息整合进 §3.1 System Overview 的散文描述里。
- P1–P5 的编号在正文中不连贯出现（P1 warmup、P2 sliding window、P4 payload binding、P5 secret binding，P3 committee 只在 A4 分析里一次出现），建议改为用描述性名称（*warmup policy*、*sliding-window check*、*payload binding*、*secret binding*），不再用 P 编号。
- A1–A6 这套编号是必要的，保留。
- C1–C5 和 E1–E4 在 security proof 里是必要的，保留，但需要加显式映射（见 C4 建议）。

---

### S2【需要改进】§3.5 Protocol Flow 与 §3.1 System Overview 内容重复

**具体位置：** §3.1 (System Overview, Stage 1-3 描述) vs §3.5 (Protocol Flow, Step 1-5 描述)

Algorithm 1 之后的 Step 1–Step 5 子小节（§3.5.1–§3.5.5）基本是对 §3.1 中 Stage 1-3 的重复，只是换了个编号体系（Stage→Step）。这对页面预算的消耗是无效的。

NDSS 系统论文普遍的做法是：Overview section 用散文或 1–2 个 figure 把系统讲清楚，Algorithm 里写伪代码，不再用单独的步骤子节重述一遍。

**建议：**
删除 §3.5 下的 Step 1–Step 5 子节（约 0.5 页），把 Algorithm 1 的伪代码提前到 System Overview 之后，让 Overview 文字 + 算法 + 图组合替代现在的重复文字。

---

### S3【建议】Table tab:tsip_defense_layers 可以删除或大幅精简

**具体位置：** §3.4 末段，Table 2 (tab:tsip_defense_layers)

这个八层防御表（L1–L8）在正文中没有被后续章节引用（security 节用的是 A1–A6 分析，theorem 用的是 E1–E4），相当于一个孤立的 summary。它占据了将近一整栏的空间，信息密度低于其他表格。

**建议：** 删除，或精简为一个嵌入段落（2–3 句），把核心意思（proof layer + chain layer + DP layer 各司其职）传达清楚即可。

---

## 四、排版与格式问题（Formatting Issues）

### F1【需立即修复】bib 文件路径错误

**具体位置：** main.tex 第 39 行

```latex
\addbibresource{main.bib}
```

但项目目录中的 bib 文件是 `references.bib`，不是 `main.bib`。这会导致 biblatex 无法找到参考文献，编译出来的 PDF 里所有引用都会显示为 `[?]`。

**修复：** 把第 39 行改为 `\addbibresource{references.bib}`。

---

### F2【需立即修复】图片文件名含空格

**具体位置：** main.tex 第 129 行

```latex
\includegraphics[width=\columnwidth]{figures/attacking example.pdf}
```

文件名 `attacking example.pdf` 含有空格，在多数 TeX 发行版下会导致编译失败或图片不显示。

**修复：** 将文件重命名为 `attacking_example.pdf`（或任意不含空格的名称），并更新 tex 文件中的引用。

---

### F3【格式不统一】图片引用路径不一致

**具体位置：** 全文图片 `\includegraphics` 调用

部分图片用了完整路径（`figures/fig_scurve`），部分用了相对路径（`fig_scurve`），还有一处用了完整路径加扩展名（`figures/attacking example.pdf`）。虽然 `\graphicspath{{figures/}}` 设置了搜索路径，但混用仍然容易出错。

**建议：** 统一为不含 `figures/` 前缀的短名（依靠 `graphicspath`），所有图片不加扩展名（由 LaTeX 自动选择 .pdf/.png）。

---

### F4【排版】重复的注释块

**具体位置：** main.tex 第 98–110 行

同一个注释块

```
% =============================================================
%  Introduction — Proving You Were There:
%  ...
% =============================================================
```

出现了两次（第 98–103 行和第 104–110 行完全相同）。虽然不影响编译，但说明文件有 copy-paste 遗留，应清理。

---

### F5【排版】lineno 包未启用但被加载

**具体位置：** main.tex 第 29 行

```latex
\usepackage[switch]{lineno}
```

正文中没有 `\linenumbers` 调用，这个包被加载但未使用。如果提交到 NDSS 不需要行号，应删除此行；如果需要审稿版行号，应加 `\linenumbers`。

---

### F6【排版细节】Table 2 数字格式不统一

**具体位置：** Table 2 (tab:comparison)

- TSIP-Full 的 Jaccard 写成 `$\approx 1.00$`
- Nebula 的 Jaccard 写成 `1.0000`（精确值，无 `$\approx$`）

这个差异会被 reviewer 注意：如果两者"statistically indistinguishable"，为什么格式不同？建议统一为 `$0.9997 \pm 0.0003$`（如果有 std data）或统一用 `$\approx 1.00$`。

---

### F7【排版细节】§3.2 中的 itemize 列表可以改为散文

**具体位置：** §3.2 Chain Commitment 里的变量说明 itemize

```latex
\begin{itemize}
  \item $c_{w-1}$ is the previous commitment...
  \item $t_w$ is the timestamp...
  ...
\end{itemize}
```

对于公式里每个变量的一句话解释，NDSS 接受论文的惯例是用散文（"where $c_{w-1}$ is the previous commitment, $t_w$ is the timestamp..."），而不是 itemize。当前的写法让这一段看起来像 spec 文档。

---

## 五、具体可执行的修改优先级

| 优先级 | 问题编号 | 工作量 | 风险降低 |
|--------|----------|--------|----------|
| 必须做（影响能否接受） | C1, C2, F1, F2 | 中/小 | 极高 |
| 强烈建议（影响 weak accept vs borderline） | C3, C5, C7 | 中 | 高 |
| 建议做（影响审稿印象） | C4, S1, S2, F3–F6 | 小 | 中 |
| 可选（改善完整性） | C6, S3, F7 | 小 | 低 |

---

## 六、如果时间允许：补充实验建议

以下两项实验，如果能在截止前完成，可以直接拔高 reviewer 信心：

**实验 A：Statistical validation of utility claim（1–2天工作量）**
对 Jaccard 和 RMSE 各跑 10–20 次独立实验，报告 mean ± std 和 Wilcoxon test p-value（或等价检验）。把 abstract 里的 "statistically indistinguishable" 变成有数字支撑的表述。这是性价比最高的补充实验。

**实验 B：A4 Sybil 的量化分析（3–5天工作量）**
不一定需要和 A1/A2/A5 一样的完整 TPR 表格，但可以做一个简单的 "number of Sybils needed to move a target cell past the SVT threshold as a function of N and ε"——这是一个有模型支撑的定量描述，可以变成一个小 proposition 或 figure，比现在的纯描述性分析要强。

---

## 七、一句话总结

论文的技术核心是可信的，最大的危险不在于"你做了什么"，而在于"你已经承认了什么但没有及时在结构上管理它"——把 Class 2 baseline 从主表移走、在 Theorem 1 前加显式攻击路径映射、把 "statistically indistinguishable" 换成真实统计测试，这三件事如果做好，当前的 borderline 风险会大幅降低。
