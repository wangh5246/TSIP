# TSIP 一周定稿日程 (Day 1–7)

> 基础假设：今天是 2026-04-27 (周一)。Day 1 = 今天，Day 7 = 周日 2026-05-03。
> 实验边界：可跑代码（数小时级）、可借中端 Android、可独立复现 EIFFeL/Nebula。
> 编辑入口：`/Users/wanghao/Desktop/risefl_mvp/TSIP/main.tex` (1718 行)。

---

## 顶层路径选择

两份审稿意见去重后的"必改"清单总共 **22 个 P0/P1**。一周 7 天，
留 Day 7 给最后 verify + 编译，所以 Day 1–6 共 6 个工作日，
平均每天必须吃掉 3.5 个改动。这是紧的，但可控——**前提是不要一边改文字一边
跑实验**。把"必跑实验"集中到 Day 2 的早晨和 Day 3 的整天，其余日子全用于改
文字。

按"先扫雷、再改章节、再补实验"的顺序排。每一天列出：
1. 早上必须先做的硬伤修复（不超过 1 小时）
2. 主任务（具体改哪几节、改成什么样）
3. 是否要起实验
4. 当晚 commit 检查点

---

## Day 1 (今天，周一) — 扫雷 + Threat Model 重写

### 早 (1h) — 修四处硬伤
独立 reviewer pass 已发现的硬错，会让审稿人直接失去信心，必须 Day 1 全部修掉：

- **F1**: tab:coverage 的 A2 行 (L849)：`C6 secret binding` → `C7 secret binding`，
  Theorem 1 (E3/E4) → Theorem 1 (E3)
- **F2**: Theorem 1 E2/E3 的 (P4)/(P5) 标号 (L886–887) → (C6)/(C7)
- **F3**: Pipeline FRR 11.36% vs 4.02% 必须先决定哪个是真值：
    - 如果两个 setting 不同（headline 含 10% 恶意，scale sweep 纯 benign），
      则在 §VI-A 加一行明确"Headline FRR 分母为 90% 诚实用户，scale sweep 分
      母为 100% 诚实用户，二者不可直接比较"。
    - 如果其中一个是 stale 数据，必须重跑确认。
- **F4**: Definition 4 (G2) logical operator (L513–515) 加括号：
  `(|S∩{A_A,A_R}|≤1 ∧ EA∉S) ∨ S⊆{EA}`

### 主 (5–6h) — §IV-B Threat Model 重写
按审稿意见 #2 P0 第 4 条，把 metadata leakage 提到 Threat Model 主段落：

1. 在 §IV-B "Honest-but-curious servers" 后面新增 \subsubsection*{Metadata
   leakage scope}，把现在 §V "Leakage profile"（L863–872）的内容整体上移。
2. §V "Leakage profile" 改成一句话引用回 §IV-B。
3. 增加 "Truth gap at enrollment" 段落已有 (L684–702)，但要再加一句明确：
   "TSIP 把 *continuity attack* 与 *enrollment attack* 解耦；continuity 在
   circuit 内 enforce，enrollment 由 EA 阈值 attestation 保护，二者独立
   失效模式。" — 这是审稿意见 #1 的 P1 第 7 项（enrollment cost 论证）。
4. EA fault 重命名：当前 §VI 用 A7 称呼 EA fault（虽然 main.tex 没明显出现
   A7，但表 tab_ea_fault 有），需检查并改成 EA-F1/F2 命名。

### 主 (剩余 1–2h) — Definition 4 (G2) 措辞
- L519–523 challenge 限制 "satisfy the same per-step and ADWC predicate
  outcomes" 后面追加一句解释为什么这个限制不弱化 G2 的实际意义（这是 #1 审
  稿意见 P0 第 1 项的子问题）：
  "This restriction is necessary because TSIP is not an unlinkability primitive;
  G2 quantifies the residual *coordinate* confidentiality given that the protocol
  legitimately reveals tier/mode tags and chain topology. Trajectories with
  different ADWC outcomes are already distinguishable through public reject
  signals and are therefore outside G2's scope by construction."

### Day 1 commit checkpoint
- [ ] F1–F4 已 grep 不出
- [ ] §IV-B 包含 Metadata leakage scope 子节
- [ ] Definition 4 logical operator 正确，且有限制理由说明
- [ ] LaTeX 编译通过 (xelatex/biber/xelatex/xelatex)

---

## Day 2 (周二) — Theorem 1 game skeleton + Abstract/Intro 重写

### 早 (3h) — 起 saturation-attack 实验
P0 第 4 项需要 worst-case adaptive attacker 数据。在 Day 2 早晨先 kick off：
- 攻击策略：每步取 0.99 × τ_u·Δt (per-step) AND 同时累计达到 0.99 × cap\_policy
- profile：vehicle, K=6, 100 用户, 50 round
- 输出：TPR 至少要保留三位有效数字
- 对应填入 tab_adaptive_boundary 的最后一行（当前是 "see §VI-G"）

### 主 (4h) — Theorem 1 game/reduction skeleton
当前 Theorem 1 (L874–907) 主文几乎只有 statement，Appendix D.0 (L1626–1639)
也只有 3 句话。改为：

1. 主文 Theorem 1 statement 后面 (L907 后) 紧接 1.5 段 proof skeleton：
```
\begin{proof}[Proof sketch]
We use a sequence of games. Let $\mathsf{Win}$ denote the event that
$\mathcal{A}$ outputs an accepting submission whose extracted witness
violates at least one of E1--E5.

\textbf{Game $G_0$:} Real TSIP acceptance game.
$\Pr[\mathsf{Win}_0]=\mathsf{Adv}^{\mathsf{int}}_{\mathcal{A}}$.

\textbf{Game $G_1$:} Abort if KS-Groth16 fails to extract a witness from
any accepting proof. By Groth16 knowledge soundness over $q$ accepting
proofs,
$|\Pr[\mathsf{Win}_1]-\Pr[\mathsf{Win}_0]|\le q\cdot
\mathsf{Adv}^{\textsf{KS-Groth16}}$.

\textbf{Game $G_2$:} Abort if any two distinct location openings collide
under Poseidon. By collision resistance,
$|\Pr[\mathsf{Win}_2]-\Pr[\mathsf{Win}_1]|\le q\cdot
\mathsf{Adv}^{\textsf{CR-Poseidon}}$.

\textbf{Game $G_3$:} Abort if any two distinct chain states collide under
MiMC7. Similarly bounded by
$q\cdot\mathsf{Adv}^{\textsf{CR-MiMC7}}$.

In $G_3$, every accepted submission has an extracted witness $w$ such that
the circuit relation holds and no two distinct openings or chain states
collide. Conditioned on no abort: C4/C5 force $\|p_i-p_{i-1}\|^2$ to obey
the per-step bound (E1); C11--C15 force the anchor distance to obey
$\min(\mathrm{tier\_anchor\_cap}_u^2,\mathrm{cap}_{\mathrm{policy}}^2)$
(E5); C6/C7 bind payload digest and secret commitment (E2/E3); the
Shuffler chain-state machine forces predecessor matching (E4). Hence in
$G_3$, $\Pr[\mathsf{Win}_3]=0$, and the bound follows.
\end{proof}
```
2. Appendix D.0 扩展：把上面 sketch 里每个 Game 的 hop 详细化，加上 reduction 的
   形式定义（KS-Groth16 extractor 怎么用、Poseidon collision 给定 collision
   pair 怎么破 G_2 的 abort 条件）

### 主 (1.5h) — Abstract 改写
按 #1 审稿意见和 #2 审稿意见综合，abstract (L69–105) 改写要点：
- "the first in-circuit enforcement..." 保留但要和 §II (L265, L360) 三处全
  对齐到一个版本（推荐 L75 的版本 + 三件套限定）
- "128-byte Groth16 proof" → "constant-size 128-byte Groth16 proof"
- "salted Poseidon" → "salted with ≥128-bit fresh randomness"
- "100% under default short-window K=6, 80–94% under K=30 stress test" — 把
  K=30 重定位为 stress test
- "benign FRR attributable entirely to session-timing effects" 改成：
  "circuit-level FRR is zero on benign continuous traces; the observed 19.2%
  withholding rate in the long-window stress setting comes from session-gap
  resets, not from the ZK circuit."
- 加最后一句限制：scalability 不要写成 "scales to 10k"，写
  "verifier path projects to 10,000-client rounds in 1.7 s under native
  Rust verification, while the full-stack prototype is directly evaluated up
  to 1,000 clients."

### 主 (1.5h) — Introduction Contribution bullets
当前 L230–242 contribution 只有 3 条，按审稿意见 #2 改为 reviewer 可验证 claim：
- bullet 1: formalize cross-round integrity + ADWC predicate (定义 + 形式化)
- bullet 2: design proof-carrying continuity protocol composing in-circuit
  C1–C16 + Shuffler state machine + EA registry checks
- bullet 3: evaluate across 6 axes (RQ1–RQ6 — attack detection, ADWC,
  privacy-utility, cost, verifier scalability, operational edge cases)

### Day 2 commit checkpoint
- [ ] saturation-attack 实验数据已落到 tab_adaptive_boundary
- [ ] Theorem 1 后有 proof sketch 段（>= 15 行）
- [ ] Appendix D.0 扩展到至少 30 行
- [ ] Abstract 重写完，"benign FRR 19.2%" 不再以 "FRR" 名义出现在 abstract
- [ ] "first" claim 全文 4 处统一为同一版本

---

## Day 3 (周三) — 实验日：EIFFeL apples-to-apples + Android prover

### 全天实验 + 录数据 — 不改文字
今天专门跑实验。审稿意见 #1 P0 第 5 项要求 EIFFeL 独立复现，#1 P1 第 9 项要
求 Android 数据点。两个并行：

#### 实验 A — EIFFeL apples-to-apples (4h, 上午)
1. clone EIFFeL 官方 GitHub (https://github.com/...)
2. 在它自己的 setting 下（FL norm-bound, d=100 维度、近似 TSIP 11 个公开输入
   的等价规模）跑 communication overhead
3. 记录：proof bytes, public inputs bytes, prover time, verifier time
4. 在 Table V (tab:mechanism-compatibility, L1085–1103) 旁边加一行
   "EIFFeL@native" 与 "EIFFeL-style@TSIP-harness" 并列，并在正文 §VI-B 加一
   句 "to address the validity-of-comparison concern, we additionally report
   EIFFeL communication measured in EIFFeL's own reference implementation
   under a $d=100$ dimensional setting that approximates TSIP's public-input
   width; the two columns are reported separately to avoid the cross-harness
   conflation flagged in our scope statement."

#### 实验 B — Android prover (4h, 下午)
1. 装机：Pixel 6a (Snapdragon 778G) 或同档位
2. 跑 TSIP-K6 prover：snarkjs/WASM, 至少 50 次取 mean ± std
3. 记录：proof time, peak memory, energy (用 Battery Historian 或 DUMPSYS
   batterystats), thermal status
4. 数据填入 tab_mobile_energy 增加一行 (Pixel 6a 行)，并在 §VI-F "Mobile
   measurement scope" (L1385) 改为 "two-platform: iPhone 16 Pro Max + Pixel
   6a (Snapdragon 778G), with 50 runs per device"

#### 实验 C — N=1000 directly measured verifier (1h, 下午晚)
当前 Table tab_scale_projection 只有 N=100 是 "directly measured"，N=1000 是
projected。在 32-core Xeon 上跑 N=1000 in-process pool 一次，把 N=1000 行的
in-process 列从 projected 改成 measured (3.2 s 看是否 match)，**这一项是
审稿意见 #1 P1 第 11 项的硬要求**。

### Day 3 commit checkpoint
- [ ] 三个实验数据 CSV 都已存在
- [ ] tab:mechanism-compatibility 已加 EIFFeL@native 行
- [ ] tab_mobile_energy 已加 Pixel 6a 行
- [ ] tab_scale_projection 的 N=1000 in-process 标 "directly measured"

---

## Day 4 (周四) — §V Security Analysis 重写 + Composed Enforcement Table

### 主 (3h) — 加 Composed Enforcement Table
按审稿意见 #2 P1 第 1 项，在 §V 开头（在当前 tab:coverage 之后或之前）加一
张新表：

```latex
\begin{table}[t]
\caption{Composed enforcement matrix. Each row names a property and the
layer that enforces it. ``Not guaranteed'' marks properties intentionally
outside TSIP's scope.}
\label{tab:composed-enforcement}
% 列：Property | Circuit | Shuffler state | EA registry | DP release | Not guaranteed
% 行：per-step continuity / ADWC drift / payload binding / secret binding /
%      tier integrity / output privacy / chain unlinkability(NO) / ground-truth presence(NO)
\end{table}
```

### 主 (3h) — G2 hybrid proof 拆 server view
当前 Appendix D.1 (L1641–1684) 只有一条线性 hybrid。按审稿意见 #2 P1 第 2 项
拆为 5 个 server view（Shuffler / Aggregator A / Aggregator R / Decoder /
EA），每个 view 一段，每段说明：(i) 该 view 看到什么、(ii) 哪一条假设让该
view 与 b 独立。EA 已经写过了，主要补 Shuffler 的"timing+topology 显式列出
但不影响 b"和两个 Aggregator 的 "additive sharing security" 段。

### 主 (2h) — DP 改 pure ε-DP
当前 §III-B Definition 1 已经写了 pure ε-DP (L399–402)，但 §IV-F (L820–823)
写 "ε_total=1.0" 但没明说没用 δ。检查全文是否还有 (ε,δ) 类表达，全部统一
到 pure ε-DP。审稿意见 #2 P1 第 4 项硬要求。

### Day 4 commit checkpoint
- [ ] Composed Enforcement Table 已加
- [ ] Appendix D.1 拆为 5 个 server view
- [ ] 全文搜不到 \delta = 1e-8 这类残留
- [ ] LaTeX 编译通过

---

## Day 5 (周五) — Evaluation 重组 + RQ1–RQ6 narrative

### 主 (3h) — Evaluation 章重组为 RQ 驱动
当前 §VI 已经有 5 个 axis (L961–975)。按审稿意见 #2 P1 第 3 项改为 6 个
RQ：
- RQ1: Does TSIP reject cross-round trajectory attacks? → A1/A2/A5/A6 + A3 短窗
- RQ2: What does ADWC add beyond per-step continuity? → K sweep, drift bias, policy cap
- RQ3: Does integrity change DP utility? → ε sweep, Jaccard/RMSE
- RQ4: What is the cost of proof-carrying integrity? → prover time, proof size, circuit, mobile
- RQ5: Can the Shuffler verify at deployment scale? → CLI / pool / native, measured vs projected
- RQ6: What are the operational edge cases? → session gap, EA fault, bounded Sybil, warmup

加一张 Table at the head of §VI："Evaluation map: RQ → subsection → table/figure"。

### 主 (3h) — Adaptive-boundary 独立子节
当前 adaptive 测评散在 §VI-C "Adaptive adversary" paragraph (L1131–1143)。
独立成 §VI-X "Adaptive-boundary attacker"：
- 把昨天 Day 2 跑的 saturation-attack 数据放进来
- 标题写明 "Attacker has oracle access to all public caps (τ_u, K, cap\_policy)"
- 子标题 "Just-below cap" / "Just-above cap" / "Saturation attack (joint
  per-step + ADWC)" / "Mode-switching attack" 四组
- mode-switching 攻击如果数据未跑，本周再补一次小实验（1h），策略：每个 K
  window 内切换 mode\_tag 拿最宽松 cap

### 主 (2h) — Class-2 baseline scope warning 显眼化
- 当前 Table V (L1085–1103) 已经有 footnote (L1101)，但太小且在表底
- 改为：(i) 在 §VI-B 标题后第一段就用一句话强调 "Class-2 baselines are
  mechanism-analogue baselines instantiated in the TSIP harness; comparisons
  are valid only for ordering and trends, not for fidelity-exact attack
  coverage." (ii) Table V caption 第一句加 "Mechanism-analogue, not faithful
  reimplementation"

### Day 5 commit checkpoint
- [ ] §VI 开头有 RQ map 表
- [ ] Adaptive-boundary 独立成节，包含 saturation attack 和 mode-switching
- [ ] Class-2 scope warning 在三处出现：§VI-B 第一段 / Table V caption / Table V footnote
- [ ] 编译通过

---

## Day 6 (周六) — 文字润色 + 图表修复 + Discussion

### 早 (2h) — 一致性大扫除
按 Day 0 一致性报告（CONSISTENCY_REPORT.md）的 60+ 项逐条修，重点：
- τ\_u² vs tier\_vmax\_sq：选定 LaTeX 数学符号 τ\_u² 用于定义，代码符号 tier\_vmax\_sq
  保留在 circuit/Appendix B 范围内，main 章节强制用 τ\_u²
- proof size 四口径：在第一次出现的位置（abstract）就明列 128 B / 807 B /
  2 KB / 5.6 KB 各自含义，全文每次提及都写其中之一不再混用
- "first" claim 4 处归一
- 数字格式：1.000±0.000 改为 "1.000 (3/3 seeds)"; 5,000.00 改为 5,000

### 主 (3h) — 图表修复
- Figure 2 (L580–589, fig:architecture)：导出 300 DPI，确保所有标签 ≥ 7pt
- 所有 log-scale 轴 (fig_ratio, fig_verifier_worker_projection)：tick label 用普通数字
- 所有 caption 检查"四要素自包含"：varied parameter / dataset / setting / takeaway
- Table caption 缩短，scope warning 移到正文

### 主 (2h) — §VII Discussion 增补
按审稿意见 #1 P1 第 6 项 + #1 P1 第 10 项 + #1 P1 第 12 项：
- §VII 增加 "Trusted setup ceremony"：明确用 Hermez Powers-of-Tau ceremony
  还是独立执行，soundness vs zero-knowledge 失效模式
- §VII 增加 "Signal noise and timing uncertainty"：GPS jitter (5–10m)、clock
  skew、τ\_u 的 +20m margin
- §VII 增加 "Mode transition protocol"：walk → vehicle 切换时 mode\_tag /
  mode\_vmax\_sq / warmup 的处理（当前在 Appendix A 但只 1 句）
- §VII 删除 "Server collusion" 与 §IV-B 重复段
- §VII Future directions 中 "ark-groth16 demonstrated at 1.37ms" 改为
  "productionising the native verifier as a long-lived Rust service"

### Day 6 commit checkpoint
- [ ] 一致性报告 60+ 项全部 close
- [ ] 所有图 ≥ 7pt 字体
- [ ] §VII 包含 trusted setup / GPS noise / mode transition 三段
- [ ] 编译通过 + chktex 0 fatal warning

---

## Day 7 (周日) — Verify + 提交准备

### 早 (2h) — 第二次独立 reviewer pass
我从头到尾再读一遍 main.tex，对照 Day 0 给的 Independent Reviewer Report，确认每一
条都已 close，没有新引入的不一致。

### 中 (2h) — Citation audit
- 逐条核对 Nebula / RiseFL / EIFFeL / ZKSL / Camel / ACORN / ZEBRA /
  TEE-DP / Prio / Prochlo 的 BibTeX 条目（标题 / 作者 / venue / year /
  DOI/URL）
- 删除任何 placeholder key（如 Saif2024Rollups 之类）
- DOI 格式统一（all-or-nothing）

### 中 (1h) — 投稿 checklist
按审稿意见 #2 第 7 节 checklist 一条条打钩：
- Claim checklist (5 条)
- Proof checklist (6 条)
- Evaluation checklist (7 条)
- Figure/table checklist (6 条)
- Citation checklist (5 条)

### 晚 (2h) — 最终编译 + Artifact Evaluation 段落
- xelatex / biber / xelatex / xelatex 三遍，确保 cross-ref 全部稳定
- 双栏 PDF 实际打印一份用肉眼检查 Figure 2 / 所有 caption / 表格不溢出
- §"Open Science" (L1481–1492) 增补：哪些表 docker-compose 一键复现 / 哪些
  需要 32-core CPU / Groth16 .zkey 是否随 artifact 分发

### Day 7 final checkpoint
- [ ] 所有 checklist 项打钩
- [ ] PDF 编译干净
- [ ] 投稿包准备完毕（main.pdf + supplementary materials + artifact tarball）

---

## 风险池 (如果 Day 1–6 任何一天落后)

按"最容易被砍但仍 ship 得动"的顺序，可以从下往上砍：
1. **Mode-switching attack 实验**（Day 5 的 1h 加项）— 砍掉影响最小，可
   在 §VI 加一句 "mode transition adversary is left to future work"
2. **Pixel 6a Android 数据**（Day 3 实验 B）— 砍掉但保留 §VII 的 Mobile
   measurement scope discussion，写 "we plan to extend to mid-tier Android in
   the camera-ready"
3. **EIFFeL apples-to-apples**（Day 3 实验 A）— 砍掉但 Table V 的 scope
   warning 必须留，用文字补足 "an apples-to-apples reimplementation under
   EIFFeL's original setting is left to future work"

**绝对不能砍**：F1–F4 硬伤、Theorem 1 game skeleton、Composed Enforcement
Table、Adaptive-boundary 独立节、abstract 重写、"first" claim 限定。

---

## 工作模式建议

1. 每天早上先读上一天的 commit，再开工
2. 改 main.tex 的同时维护一个 `CHANGELOG_REVIEW.md`，每条改动写
   "审稿条目 → 行号 → 改前 → 改后 → 一句理由" — 这是 NDSS rebuttal 的素材
3. Day 7 的 reviewer pass 用一个干净状态的 brain 做，不要一边改一边 verify
4. 如果遇到拿不准的取舍，写在 `OPEN_QUESTIONS.md` 攒到一起问导师，不要每个
   都打断

---

*本日程版本：2026-04-27 由 Claude 编制。*
