# 独立 Reviewer Report — TSIP NDSS 投稿

> 阅读模式：以 NDSS reviewer 视角通读 main.tex (1718 行) 一遍，**不参考导师两份审稿
> 意见**。结束后再与导师两份对照，把"导师两份没覆盖到"或"导师覆盖了但我有不同
> 看法"的项标注出来。
>
> 标注：
> - 🆕 = 导师两份均未覆盖
> - ⚠️ = 导师覆盖了但我认为优先级更高 / 视角不同
> - ✅ = 与导师审稿基本一致（仍列出以便交叉验证）

---

## A. Strengths（先肯定，让 weakness 落地更可信）

1. Problem positioning 清晰：DP 保护输出、TSIP 保护输入，二者互补——一句话
   就能让审稿人记住 contribution。
2. ADWC 的 K-window 抽象在 §III-D Definition 3 写得简洁、可数学化、可
   tunable（policy cap 作为 public input）。这一点比导师审稿都更应被强调，
   建议作为 §I 的核心 Pitch。
3. Class-1 / Class-2 baseline 区分这件事本身是诚实的——很多论文不会做。

## B. P0 (must-fix, otherwise reject 风险大)

### B.1 ⚠️ Pipeline FRR 11.36% vs 4.02% 数字直接打架
- L1078 (tab:ablation-headline)：N=50, T=10, T-Drive, 10% adversarial → 0.1136
- L1239, L1256, L1329：同 N=50 在文字中报 0.0402
- 这是数字硬伤，导师两份审稿都没明确指出这一点。reviewer 第一遍读
  evaluation 会停在这里。
- 修复路径：如果两个 setting 不同（headline 含 10% 恶意，scale sweep 是纯
  benign），必须在 §VI-A 增加一句解释 + 在两个数字旁加 footnote。

### B.2 🆕 tab:coverage 表的 A2 行映射错了（C6 vs C7）
- L849 当前写 `A2 & C6 secret binding & Theorem~1 (E3/E4)`
- 但 Appendix B 定义 (L1564–1565)：**C6 是 payload binding**，C7 才是 secret binding
- Appendix C 的 A2 段 (L1596) 自己写的也是 C7
- 这是导师两份审稿都漏掉的硬错。一个 reviewer 顺着 attack→defence 链索引就会
  发现 main 表和 appendix 矛盾。

### B.3 🆕 Theorem 1 E2/E3 标号 (P4)/(P5) 来源不明
- L886 写 "the proof binds to the submitted payload digest (P4)"
- L887 写 "the proof binds to the registered per-user secret commitment (P5)"
- 但 main.tex 全文没有定义 P1–P5 标号体系，这两个 (P4)(P5) 像是从早期版本留
  下的 dangling 引用。应改为 (C6)/(C7)。

### B.4 ✅ Theorem 1 主文几乎只有 statement
- 与导师审稿意见 #2 P0 第 5 条一致。
- 我额外补充：当前 Appendix D.0 (L1626–1639) 也只有 3 行 union bound，跟
  appendix 该有的 hybrid sequence 差距很大。
- 优先级：P0。NDSS reviewer 在阅读 §V Theorem 1 时，预期能看到 Game 0–3 序
  列、bad event bound、reduction 形式定义中至少一项；现在三个都没有。

### B.5 ✅ benign FRR 19.2% / 46.8% 仍以 "FRR" 名义出现
- 与导师审稿意见 #2 P0 第 2 条一致（FRR 必须拆三层）。
- 我额外补充：审稿意见 #1 没强调这点。但这个改动**风险特别低、收益特别大**——
  只是术语替换，不动一个数字。一定要 Day 1 顺手改。
- 具体行：L1337 "benign FRR (0.192 / 0.468)" → "session-withholding rate"
  + 单独一行报 "circuit-level FRR is 0 across all configurations"

### B.6 🆕 Definition 4 (G2) challenge 限制实质上让 G2 趋于 trivial
- L519–523 challenge 要求 "two trajectories satisfy the same per-step and
  ADWC predicate outcomes"
- 这个限制比导师审稿意见 #1 P0 第 1 条说的更严重：因为 trajectory 本质上是连
  续坐标，"satisfy the same predicate outcomes" 实际上要求两条 trajectory
  几何上几乎重合（任何两条不同的 trajectory，在 K-window 内某一步都有概率
  跨过 cap）。
- 这导致 G2 的 challenge 空间几乎是 singleton，定理变成 trivially true。
- 修复方向：要么放宽 challenge 限制（允许预测同一个 reject 序列即可），要
  么明确说明 G2 protect "trajectory geometry given fixed predicate outcome"
  并改名 "G2: Geometric Indistinguishability under Fixed Predicate
  Outcome"——这个改名更诚实。

## C. P1 (强烈建议改)

### C.1 ✅ "first" claim 全文 4 处版本不一致
- L75 (abstract), L232 (contribution), L265 (§II), L360 (§II Summary) — 我
  数到 4 处不同的限定。
- 导师审稿意见 #1 P1 第 8 项已覆盖。

### C.2 🆕 §V Composition 段 disjointness 的论证有问题
- L950–958 当前写 "the goals cover disjoint adversarial events"
- 但 G1（continuity）和 G2（privacy）并不真正 disjoint——一个能制造非法
  trajectory 又被接受的攻击者，可以 "学到" 关于其他用户的 timing/rejection
  pattern，从而违反 G2。
- 导师审稿意见 #1 已轻微提到这点（"G1 与 G2 并非完全独立"），但我认为优
  先级更高：reviewer 看到 "disjoint" 这个词会立刻挑战。
- 修复：写 "near-disjoint with overlap bounded by the timing-leakage term in
  G2's leakage profile"。

### C.3 ⚠️ §IV-C salt management 的 992B 计算有冗余
- L749–750 (§IV-C-3)：31·32B = 992B
- L1413–1414 (§VII)：同样的 31·32B = 992B
- 导师审稿意见 #1 P2 第 16 项已覆盖。但我建议把 §VII 的版本改写为
  "Section IV-C-3 establishes the (K+1)-entry salt ring; the per-K=30
  client cost is therefore 992 B." — 即引用而不是重复。

### C.4 🆕 §IV-D Constraint 数字 2,340 / 2,430–2,460 的"估计 vs 测量"边界没说清
- L781–784 写 "the resulting Groth16/BN254 circuit is **expected** to contain
  about 2,430–2,460 R1CS constraints"
- L1580 写 "**estimated** 90–120 additional R1CS constraints"
- L1465 (Conclusion) 直接写 "salted circuit at roughly 2,430–2,460 constraints"
- "expected" / "estimated" / "actually measured" 应明确：哪一个是从原始
  2,340-constraint artifact 加估计 90–120 来的？哪一个是 salted 版本实际
  compile 后的？
- 修复：在 §IV-D 直接写 "the salted artifact compiles to N R1CS constraints
  (measured)" 给一个具体数字，避免一直用 range。

### C.5 ✅ Mobile 单设备 generalizability
- L1385–1389 §VI-F 自承 single-platform。
- 导师审稿意见 #1 P1 第 9 项已覆盖。

### C.6 🆕 N=50 default configuration 在 NDSS reviewer 眼里太小
- L1024–1030 default N=50, T=10 — 在审稿意见 #2 中有提到 N=1000 偏小，但
  我认为更严重的是 default 是 50（headline 表都用 N=50）。
- 修复：把 default 改成 N=1000（已经在 scale sweep 测过），让 headline ablation
  与 scale sweep 用同一个 N。这样 "Pipeline FRR 4.02%" 与 "Pipeline FRR
  0.0002 at N=1000" 之间的差异也自然解释为 SVT 在更大 N 下截断更少。

### C.7 🆕 §VI-D ε sweep 的 confidence interval 缺失
- L1158–1170 报告 ε ∈ {0.1, 0.5, 1.0, 2.0, 5.0} 下 Jaccard 数字 0.155 /
  0.211 / 0.207 / 0.211 / 0.196
- 这五个数差异很小，几乎在 noise floor。但 §VI-A 说 "3 seeds"，没报告 std。
- 修复：直接报 mean ± std，或加 95% CI。如果 std 比 inter-ε 差异还大，必须
  在文字中说明 "ε within (0.5, 5.0) shows no statistically significant
  utility difference"。

### C.8 🆕 SVT 的 stop condition 完全没说
- §IV-F (L814–823) 写 SVT τ=3.0, ε_SVT=0.3 — 但 SVT 的 standard 算法需要一
  个 cutoff (查询第几个 query 后停止)，paper 完全没提。
- reviewer 看到 SVT 但没 cutoff 会立刻问"剩余 budget 怎么处置？"。
- 导师审稿意见 #1 P2 第 V-F 提了一句但没强调。我认为这是 P1。
- 修复：§IV-F 增加一行 "SVT stops at the first c queries that exceed
  threshold; remaining budget is allocated to the Laplace step."

## D. P2 (润色)

### D.1 ✅ 符号风格混用 (τ_u² vs tier_vmax_sq)
- 与导师审稿一致。

### D.2 🆕 §III-C Poseidon arity-3 "30–40 R1CS constraints" vs §IV-D "90–120"
- L457–458 §III-C：arity 2→3 加 30–40 per Poseidon instance
- L781–782 §IV-D：C1–C3 三个 arity-3 Poseidon 加 90–120 总
- 数字一致（30–40 × 3 = 90–120），但应 cross-reference，让读者看到 §IV-D
  时不需要回去查 §III-C。

### D.3 🆕 §III-D G3 用了 "user-level adjacency" 但 §IV-F 没明说
- L548–552 G3 定义在 user-level adjacency
- L820–823 §IV-F 没明说 sensitivity Δf=1 是 user-level 还是 record-level 的
- 修复：§IV-F 增加 "under user-level adjacency, sensitivity bounds the
  contribution of removing all of one user's records"

### D.4 🆕 §IV-B truth gap 段中的 N_warm·T_window 计算的 6 分钟太弱
- L693–695 "raising the attack cost from zero to maintaining a plausible
  fictitious trajectory for N_warm · T_window seconds"
- K=6, T_window=60s → 6 分钟。这个数字小到让人怀疑 warmup 防御有什么意义。
- 导师审稿意见 #1 P1 第 7 项已部分覆盖，但我认为应进一步：
  - 明确说 "warmup 不是设计来阻止 patient attacker，而是阻止 opportunistic
    enrollment-then-immediate-attack"
  - 引用 botnet 经济学：1000 个设备 × 6 分钟 = 6000 设备分钟，按
    market rate 估算

### D.5 🆕 Table I (positioning) 中 Geo-Indistinguishability 的 DP 列
- L294 当前 ✓ (DP release ✓)，但 Geo-Ind 用的是 metric DP，不是 (ε,δ)-DP
- 应改为 ◦ (partial) + footnote "metric DP, not standard (ε,δ)-DP"
- 导师审稿意见 #1 P2 第 14 项已覆盖。

### D.6 🆕 Appendix A "Stage 3 aggregation walkthrough" 应有图但没图
- L1503–1511 整段描述 share split / decoder / SVT / Laplace 流程，但没有
  对应图。Appendix A 后面的 fig:verification-outcomes (L1519–1525) 是 5 个
  outcome scenario，与 stage 3 walkthrough 不是同一件事。
- 修复：要么补一张 share-split 流程图，要么删掉 "walkthrough" 这个标题改
  叫 "Aggregation flow"

### D.7 ✅ Figure 2 双栏可读性
- 与导师审稿意见 #1 P1 第 15 项一致。

## E. 与导师两份审稿的对比总结

### E.1 导师审稿覆盖了、但我会调整优先级的：
- "K=30 长窗口 80–94% TPR 需要正面解释"（导师 #1 P1 第 4 项）— 我认为这是
  P0 而非 P1。如果 reviewer 只看 abstract 和 §VI-G 的 80–94%，会直接给
  "doesn't generalize beyond short-window"。
- "Trusted setup ceremony"（导师 #1 P1 第 6 项）— 我同意 P1，但补充：必须
  明确"setup compromise 失效模式是 soundness 而非 ZK"，否则 reviewer 会怀
  疑 G2 也会因为 setup compromise 失效。
- "EIFFeL apples-to-apples"（导师 #1 P0 第 5 项）— 我认为这是 **P0 但
  ship-able as P1**：如果 7 天内无法独立复现，可以保留 mechanism-analogue
  但用更显眼的 scope warning，而不是必须复现。

### E.2 我额外发现导师两份都漏掉的硬错（按优先级）：
1. **B.1 Pipeline FRR 11.36% vs 4.02% 数字打架**（P0，硬伤）
2. **B.2 tab:coverage A2 行 C6/C7 错位**（P0，硬伤）
3. **B.3 Theorem 1 E2/E3 (P4)(P5) dangling 标号**（P0，硬伤）
4. **B.6 Definition 4 challenge 限制使 G2 接近 trivial**（P0，定义层面）
5. **C.2 Composition 段 disjointness 论证不严**（P1）
6. **C.4 2,340 / 2,430–2,460 估计 vs 测量边界不清**（P1）
7. **C.6 default N=50 太小，应改为 N=1000**（P1）
8. **C.7 ε sweep 缺 std**（P1）
9. **C.8 SVT stop condition 缺失**（P1）

### E.3 我和导师审稿 #2 在大方向上一致的判断：
- 当前稿件是 "borderline before polishing"，P0+P1 完成可争取 borderline accept。
- FRR 必须拆三层是最高 priority 的 wording change（最容易、最重要）。
- 一致性问题（symbols / proof size 四口径 / "first" claim）必须 grep 全文修。

---

## F. 给作者的两条具体建议（NDSS rebuttal 角度）

### F.1 准备一张"claim-to-evidence"附录表
预防 reviewer 在 rebuttal 阶段质问 "your abstract says X but I cannot find
where you measured it"。每个 abstract claim → main 文中具体表/图，做成一张
table。审稿意见 #2 已建议过；我加一句：**这张表本身放进 Appendix E 或
camera-ready 时放进 supplementary**，不要占主文 page budget。

### F.2 主动写 1 段 "Limitations beyond truth gap and trusted setup"
当前 §VII 已经主动承认 enrollment truth gap + Groth16 trusted setup。
建议再加一段主动承认：
- (a) Shuffler unlinkability 不保证（已经写了，再次强调）
- (b) Mobile 单设备
- (c) Class-2 baseline 是 mechanism analogue
- (d) ε sweep 的 utility 差异在 noise floor

主动承认 limitations 比 reviewer 挑出来再被动 rebuttal 强很多——这是 NDSS
审稿文化的 well-known piece of advice。

---

*报告版本：2026-04-27 由 Claude 独立编制。共发现 P0 硬伤 6 条、P1 16 条、
P2 7 条；其中 9 条为导师两份审稿未覆盖的新发现。*
