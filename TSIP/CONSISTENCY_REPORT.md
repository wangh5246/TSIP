# TSIP main.tex 全文一致性检查报告

> 范围：`/Users/wanghao/Desktop/risefl_mvp/TSIP/main.tex` (1718 行)
> 不含 14 个 `tables/*.tex` 表格文件单独的 caption 文字（除非引用）。
> 检查方式：grep + 人工配对。每条问题都给行号便于定位修复。
>
> 标注：
> - 🚨 = 数字直接打架（reviewer 一眼可见的硬错）
> - ⚠️ = 概念/标号映射错误（导致逻辑链断裂）
> - 🔄 = 风格/符号混用（不影响正确性，但显得不专业）
> - 📌 = 单位/格式不统一（润色级）

---

## A. 数字硬伤 🚨

### A.1 Pipeline FRR 11.36% vs 4.02% 同 setting 不同值
| 行号 | 来源 | 值 | 上下文 |
|---|---|---|---|
| L1078 | tab:ablation-headline | 0.1136 (11.36%) | "TSIP-Full at default config (N=50, T=10, T-Drive)" |
| L1239 | §VI-D 文字 | 4.02% | "FRR cost of the full protocol, 4.02% at N=50" |
| L1256 | §VI-D 文字 | 0.0402 | "benign FRR falls from 0.0402 at N=50 to 0.0002 at N=1000" |
| L1329 | §VI-G | 4.02% | "TSIP's FRR of 4.02% at N=50 (Table 4)" — **直接引用** Table 4，但 Table 4 写的是 0.1136 |

**判定**：L1329 把 Table 4 的 0.1136 错引为 4.02%，或 Table 4 数据错。必须先确定哪个数字是真值。建议：
1. 重跑 N=50 的 default config 一次，定一个数字
2. 如果 0.1136 是 "10% 恶意 setting 下的 benign 拒绝率（分母含恶意用户被拒）"，
   而 0.0402 是 "纯 benign setting 下的拒绝率"，则在 §VI-A 加一行说明，并在
   两个数字旁加 footnote

### A.2 Theorem 1 E2/E3 标号 (P4)/(P5) — 来源不存在
- L885–887: `E2 (Payload binding): the proof binds to the submitted payload digest (P4)`
- L887: `E3 (Secret binding): the proof binds to the registered per-user secret commitment (P5)`
- 全文 grep "P[1-9]" 标号体系不存在。这两个 (P4)(P5) 应改为 (C6)/(C7)
- 修复：L886 `(P4)` → `(C6)`；L887 `(P5)` → `(C7)`

### A.3 tab:coverage A2 行 C6 vs C7 错位
- L849: `A2 & C6 secret binding + chain state & Theorem~1 (E3/E4)`
- L778 (§IV-D): `(C6--C7)` 整组叫 "payload/secret binding"
- L1563–1565 (Appendix B): C6 是 payload binding (`Poseidon(payload_lo, payload_hi)`)，C7 是 secret binding (`Poseidon(secret, uid_field)`)
- L1596 (Appendix C, A2 段): `Constraint C7 binds the proof to the registered secret commitment` ← 与 L849 直接矛盾
- 修复：L849 `C6 secret binding` → `C7 secret binding`，且 `Theorem~1 (E3/E4)` → `Theorem~1 (E3)`（E4 是 chain continuity 已经在 A5 行）

### A.4 Constraint count "2,340 / 2,430–2,460 / 90–120" 三套数字混用
| 行号 | 表述 | 状态词 |
|---|---|---|
| L347 | "≈2,430–2,460 R1CS constraints" | "compact" — 默认值 |
| L455 | "approximately 110 R1CS constraints" | "Poseidon arity-2 base cost" |
| L457–458 | "Moving... arity 2 to arity 3 adds only about 30–40 R1CS constraints per Poseidon instance" | — |
| L781–784 | "C1–C3 from arity-2 to arity-3 Poseidon, adding roughly 90–120 constraints over the 2,340-constraint artifact; the resulting circuit is **expected** to contain about 2,430–2,460" | "expected" |
| L1465 (Conclusion) | "salted circuit at roughly 2,430–2,460 constraints" | "roughly" |
| L1579–1580 (Appendix B) | "the **estimated** 90–120 additional R1CS constraints; other groups are unchanged from the 2,340-constraint artifact" | "estimated" |

**问题**：2,430–2,460 是估计值，不是实测。reviewer 会要求实测值。
**修复路径**：
- 实际 compile 一次 salted circuit 拿到具体数字（例如 2,447）
- 全文用这一个数字替换 range，并将 estimated 字样删除

### A.5 ε sweep Jaccard 数字缺 std
- L1165–1167: ε=0.1: 0.155 / ε=0.5: 0.211 / ε=1.0: 0.207 / ε=2.0: 0.211 / ε=5.0: 0.196
- §VI-A (L1010, L1015–1016) 明确说 3 seeds, mean ± std — 但这五个 ε 值都没报 std
- 修复：报 mean ± std，或在 paragraph 末加一句 "std < 0.01 across all ε"

### A.6 Salt buffer 992 B 计算重复
- L749–750: §IV-C-3 "31·32B = 992B; anchor-history alone 960B"
- L1413–1414: §VII "31·32B = 992B; 960B attributable to anchor-history"
- 内容完全重复，应在 §VII 改为 "Section IV-C-3 establishes the (K+1)-entry salt ring; per-K=30 client cost is therefore 992 B"

### A.7 Mobile latency "0.35–0.37 s" vs "278.6 ms"
- L96–97 abstract: "${\approx}0.35$--$0.37\,\mathrm{s}$ on a commodity CPU"
- L241 §I contributions: "$\approx$0.35--0.37\,s"
- L1258–1259 §VI-D: "$\approx 0.35\,\mathrm{s}$ for short-window, $0.37\,\mathrm{s}$ for long-window — **after the estimated arity-3 salted-location overhead**"
- L1270 §VI-D: "iPhone 16 Pro Max gives $278.6\pm2.2$\,ms for TSIP-K6"
- L1436 §VII: "single iPhone 16 Pro Max run ($278.6\pm2.2$\,ms for TSIP-K6)"
- L1444 future: "$1.37$\,ms per proof; $N{=}10{,}000$ in $1.7$\,s with $k{=}8$"

**问题**：
1. 0.35–0.37s 是 desktop CPU prover；278.6 ms 是 iPhone — reviewer 看
   abstract 会以为 0.35–0.37s 是 mobile 数字。Abstract / contribution 必须
   明示 "commodity CPU"。
2. "after the estimated arity-3 salted-location overhead" — 又一个 estimated。
   实测过 salted 版本的 prover 时间吗？如果没有，这个 0.35–0.37 也是估计。

---

## B. 概念/标号映射 ⚠️

### B.1 "MRR" 全文未定义但出现 3 次
- L1163: "MRR=1.00 at every ε"
- L1169: "MRR=0"
- L1191 (caption): "(solid: FRR, dashed: MRR)"
- 全文搜不到 MRR 的定义（应该是 Malicious Rejection Rate？）。
- 修复：在 §VI-A "Metrics" (L1034–1036) 增加 MRR 定义，或全文改为 "TPR" 保持
  与其他章节一致

### B.2 "first" claim 4 处版本不一致
| 行号 | 限定 |
|---|---|
| L75 (abstract) | "the first in-circuit enforcement of cross-round trajectory continuity within an ESA private aggregation pipeline" |
| L232 (contribution) | "the first in-circuit enforcement of cross-round trajectory continuity within an ESA private aggregation pipeline" |
| L265 (§II) | "the first design to simultaneously offer cross-round continuity, physical-plausibility enforcement, and shuffle-model DP release in a single pipeline" |
| L360 (§II Summary) | "no prior system jointly provides (i) per-submission ZK verification of physical-mobility continuity, (ii) shuffle-model DP release, and (iii) operation without trusted hardware or server-side trajectory state" |

**修复**：选 L75 版本统一，§II Summary 保留三件套但措辞改为
"jointly providing (i) in-circuit cross-round physical continuity, (ii)
shuffle-model DP release, and (iii) operation without trusted hardware or
server-side trajectory state"

### B.3 "to the best of our knowledge" / "to the best of the authors' knowledge" / "To our knowledge" 三种说法
- L232: "to the best of our knowledge"
- L265: "to the best of the authors' knowledge"
- L360: "To our knowledge"
- 修复：统一为 "to our knowledge"，且整篇只保留 1–2 处（abstract + contribution
  各一次），删掉重复

### B.4 Composition 段 "disjoint adversarial events"
- L950–958: 写 "G1...G2...G4...G3 cover disjoint adversarial events"
- 实际并非完全 disjoint：见 INDEPENDENT_REVIEWER_REPORT C.2
- 修复：改为 "near-disjoint with overlap bounded by the timing-leakage term in
  G2's leakage profile" 或类似措辞

### B.5 Definition 4 (G2) logical operator 歧义
- L513–515:
  ```
  |S∩{AggregatorA,AggregatorR}|≤1
  \quad and \quad
  EA∉S \ or \ S⊆{EA}
  ```
- and / or 优先级在 LaTeX 渲染下不清楚
- 修复：
  ```
  (|S∩{AggregatorA,AggregatorR}|≤1 ∧ EA∉S) ∨ S⊆{EA}
  ```
  在 LaTeX 中显式用 `\bigl(...\bigr)` 括号

### B.6 EA fault 命名缺失
- main.tex 没有 A7 这个标号，但 §VI-G L1324 写 "enrollment-authority fault
  injection... under {0,1,2,3} anchor failures"
- tab_ea_fault.tex 文件存在，但 main.tex 通过 `\input{tables/tab_ea_fault}`
  (L1717) 引用
- 修复：在 §IV-B threat model 显式定义 "EA-F1 (signature-invalid attestation),
  EA-F2 (anchor unavailability)" 命名，与 A1–A6 区分

---

## C. 符号风格混用 🔄

### C.1 速度 cap 数学体 vs 代码体混用
| 数学体 (τ_u, τ²_u) | 代码体 (tier\_vmax\_sq) | 行号 |
|---|---|---|
| L491, L494, L496 (Definition 3 ADWC) | — | math 风格 |
| L639 (§IV-B) | — | "$\tau_u\!\cdot\!\Delta t$" |
| L653 | "tier\_anchor\_cap_u" + "cap\_policy" | math下标 + 代码 |
| L1134 (§VI-C adaptive) | — | "$\tau_u, \mathrm{cap}_{\mathrm{policy}}, K$" |
| — | L558 (G4) "tier\_vmax\_sq, com\_sec, com\_modeset" | 代码 |
| — | L881–894 (Theorem 1) "tier\_vmax\_sq, mode\_vmax\_sq(selected), tier\_anchor\_cap\_sq, cap\_policy\_sq" | 代码 |
| — | L1561, L1571, L1573 (Appendix B) "tier\_vmax\_sq, mode\_vmax\_sq(selected), tier\_anchor\_cap\_sq, cap\_policy\_sq" | 代码 |

**修复策略**（建议）：
- 数学定义部分（§III-D Definitions, §IV-B Threat Model 描述部分）用数学符号
  τ_u, τ²_u, $C_{policy}^2$, $C_{tier}^2$
- Circuit 描述部分（§IV-D, Theorem 1, Appendix B, Appendix C）用代码符号
  tier\_vmax\_sq 等
- 在 §IV-D 开头加一段 "Notation bridge"：
  ```
  In what follows we use the circuit-implementation notation
  tier_vmax_sq for τ²_u, tier_anchor_cap_sq for C²_tier,
  cap_policy_sq for C²_policy, etc.
  ```

### C.2 "K=6 / K{=}6 / short-window" 三种说法
- L92, L1026, L1109 等大量 "K=6" 直接 inline
- L1116, L1119, L1124 等 "$K{=}6$"
- L1258, L1259 "short-window setting" / "long-window setting"
- L1309, L1313 "short-window setting (K=6)" / "long-window setting (K=30)"

**问题**：abstract 里直接讲 K=6/K=30，但读者第一次见这两个数字可能没 context。
**修复**：abstract 第一次提及时写 "default short-window setting K=6 and a 30-window stress test"

### C.3 "snarkjs" / "ark-groth16" / "Native Rust" 三种 verifier 命名
- L1004 §VI-A "Circom/snarkjs Groth16 toolchain"
- L1264 §VI-D "prototype CLI verifier" (= snarkjs CLI)
- L1267 "in-process Node.js pool"
- L1268 "native ark-groth16 verifier"
- L1278–1283 caption "CLI / in-process Node.js pool / native ark-groth16"
- L1290 "long-lived Rust service" (= ark-groth16)
- L1443 "ark-groth16 or equivalent"

**问题**：CLI = snarkjs CLI subprocess，pool = Node.js worker pool，native = ark-groth16；但 figure caption 用 "Native Rust"，正文混用名称
**修复**：定义三个固定名称："snarkjs-CLI / snarkjs-pool / ark-rs"，全文统一

### C.4 "warmup" 拼写
- L754, L1399 "Warmup"
- L808 "warmup"
- L1528 "Warmup"
- 大写小写没有规则，建议统一为小写 "warmup"（除句首）

---

## D. Proof size 四口径分布

期望（按导师审稿意见 #2 C2 要求）：
- L1 proof object: 128 B
- L2 proof JSON: 807 B
- L3 integrity package: 2 KB
- L4 full frame: 5,614 B (≈ 5.6 KB)

实际全文出现：

| 行号 | 数字 | 含义判定 | 是否标注层级? |
|---|---|---|---|
| L78 | "128-byte Groth16 proof" | L1 proof object | ❌ 没说 L1 |
| L96 | (含 abstract) "communication is ${\approx}2$\,KB for the TSIP integrity contribution" | L3 | ✅ 说了 "integrity contribution" |
| L99 | "the full prototype packet including encrypted shares totals ${\approx}5.6$\,KB" | L4 | ✅ 说了 "full prototype" |
| L218 | "(128\,B)" | L1 | ❌ 没说 L1 |
| L241 | "$\approx$2\,KB" | L3 | ❌ 没说 L1/L2/L3 哪一层 |
| L296 | "$\SI{128}{B}$" (Table I) | L1 | ❌ |
| L438 | "(128 bytes)" Groth16 spec | L1 (定义性陈述) | OK |
| L784 | "proof size unchanged at 128\,B" | L1 | OK |
| L1456 | "constant-size Groth16 proof" + "128\,B" | L1 | ❌ |
| L1466 | "the proof at 128\,B" | L1 | ❌ |
| **L1078** (Table 4) | **"L3 payload" 列：2.0 / 1.0 / 1.0** | L3 但 No-Integrity 是 1.0? | ⚠️ 见 D.1 |

### D.1 ⚠️ Table 4 L3 payload 列 "1.0 / 1.0" 不对
- L1078 (TSIP-Full): L3 payload = 2.0
- L1079 (Commit-Only): L3 payload = 1.0
- L1080 (No-Integrity): L3 payload = 1.0
- 但 Commit-Only 应该有 chain commitment，No-Integrity 才是裸 payload
- 修复：核实 Commit-Only / No-Integrity 的实际 payload 大小，重新填表

### D.2 全文应在 abstract 第一次提到 128 B 时插入一句脚注或括号说明四层口径
建议 abstract 改写为：
"Each client submission carries a 128-byte Groth16 proof object (L1).
Including public signals, chain metadata, and authentication fields, the
TSIP integrity package is approximately 2 KB (L3); the full prototype
wire-format packet including encrypted shares is approximately 5.6 KB (L4)."

---

## E. FRR 三义混用

### E.1 "circuit-FRR" / "session-withholding" / "DP/SVT exclusion" 当前状态
| 行号 | 当前用词 | 应改成 |
|---|---|---|
| L90 | "zero circuit-level false rejects on benign traces" | ✅ 已是 circuit-FRR=0 |
| L94–95 | "benign FRR... attributable entirely to session-timing effects" | ⚠️ 仍称 FRR，应改 |
| L240 | "zero circuit-level FRR" | ✅ |
| L1035 | "circuit/session-gap/DP-SVT/pipeline FRR" | ⚠️ 用 / 分隔，但下文不严格分开 |
| L1316 | "benign FRR is 0.47" | 🚨 必须改：长窗口 stress 设置下，47% 不应叫 FRR |
| L1317 | "filtered at session-timing" | OK |
| L1322 | "benign FRR constant across cap settings (session-timing dominates)" | ⚠️ 还是 "benign FRR" |
| L1329–1338 §VI-G "Decoupling of FRR sources" 段 | 文字解释了 circuit-FRR=0，但仍把 0.192/0.468 称为 "benign FRR" | ⚠️ |
| L1345 | "benign-FRR remains exactly 0.192" | 🚨 |
| L1352 | "The benign FRR of 19.2%" | 🚨 |

**修复策略**（统一替换）：
- 所有把 0.192 / 0.468 / 0.47 称为 "FRR" 的地方，改为
  "session-withholding rate"
- "circuit-level FRR" 保留（值=0）
- 在 §VI-A "Metrics" 增加明确定义：
  ```
  We distinguish three rejection rates:
  (i) circuit-FRR: fraction of honest submissions rejected by Groth16 circuit;
  (ii) session-withholding: fraction held back by warmup/session-gap policy;
  (iii) DP-SVT exclusion: fraction filtered by SVT threshold below release threshold.
  ```

---

## F. 引用 / Reference 风险点

### F.1 [9] 是 EIFFeL，应在 §I 添加 location-aggregation 引用
- L146 "Per-round input validation can additionally be enforced via short
  zero-knowledge proofs~\cite{Chowdhury2022EIFFeL}"
- EIFFeL 是 FL 场景，这里引一个 location-aggregation 的 per-round ZK 工作
  会更精确（导师审稿意见 #1 §I 第 1 项）

### F.2 [5] Nebula CCS 2025 — positioning 必须准确
- L125, L291 (Table I), L1046, L1175, L1213 多处引用 Shamsabadi2025Nebula
- L1175 写 "Nebula-analogue (DP disabled, noiseless upper bound)" — 这与
  "Nebula" 实际是不同的设计
- 修复：所有 "Nebula-analogue" 用词必须明示是 mechanism analogue，避免和
  原 Nebula 混淆

### F.3 Saif2024Rollups 等 placeholder key
- L349 "ZK rollups~\cite{Saif2024Rollups,Sasson2014Zerocash,Gabizon2019PLONK}"
- Saif2024Rollups 看起来像是临时 key（年份 + 主题）。检查 reference.bib
  确认是真实条目

---

## G. 数字格式不统一 📌

### G.1 Jaccard 报告位数
| 行号 | 数字 | 位数 |
|---|---|---|
| L1078 (Table 4) | 0.3992 | 4 位 |
| L1080 (Table 4) | 0.4289 | 4 位 |
| L1165 | 0.155 | 3 位 |
| L1166 | 0.211, 0.207, 0.211 | 3 位 |
| L1167 | 0.196 | 3 位 |
| L1169 | 0.37–0.46 | 2 位 |
| L1192 | 0.16–0.21 | 2 位 |
| L1247 | 0.3992±0.0179 | 4 位 |

**修复**：选 4 位有效数字（0.3992），全文统一

### G.2 std 报告 1.000±0.000
- tab_adaptive_boundary L13–17 多处 "1.000" 和 "0.000"
- 导师审稿意见 #1 P2 第 18 项已覆盖
- 修复：改为 "1.000 (3/3 seeds)" 或 "100% (n=3)"

### G.3 distance 单位混用
- L639 "$\tau_u\!\cdot\!\Delta t$"（无单位，纯符号）
- L1109, L1122 "$\tau_{\mathrm{vehicle}}\Delta t=\SI{1980}{m}$"
- L1591 "(walk: 180m, bike: 600m, vehicle: 1980m, transit: 2400m)" — 不用 \SI
- L1109 用 \SI{1980}{m}，L1591 用 1980m — 内联格式不统一
- 修复：全文用 \SI{...}{m} 或 \SI{...}{\meter}

### G.4 mile/km 在 §VI-G 数字
- L1302 "$\SI{39.6}{km}$", L1303 "$\SI{3.3}{km}$", L1304 "$\SI{198}{km}$",
  L1305 "$\SI{16.5}{km}$"
- 与 L1591 "1980m" 混用单位（米/公里），无规则
- 修复：< 10000 m 用 m，≥ 1 km 用 km，全文统一阈值

---

## H. Cross-reference 检查

### H.1 §I 所有 forward reference 命中
| 行号 | reference | label | OK? |
|---|---|---|---|
| L207 | `\ref{sec:prelim-goals}` | `\label{sec:prelim-goals}` (L471) | ✅ |
| L246 | `\ref{sec:related-work}` | L257 | ✅ |
| L247 | `\ref{sec:prelim}` | L365 | ✅ |
| L249 | `\ref{sec:system}` | L591 | ✅ |
| L250 | `\ref{sec:security}` | L825 | ✅ |
| L251 | `\ref{sec:eval}` | L962 | ✅ |
| L253 | `\ref{sec:discussion}` | L1392 | ✅ |
| L254 | `\ref{sec:conclusion}` | L1451 | ✅ |

OK，主结构 cross-ref 没问题。但 Theorem 1 没有 `\label`：
- L874 `\begin{theorem}[Main Circuit Integrity Properties]` 后没有 `\label{thm:integrity}` 或类似 — 全文用 "Theorem~1" hardcoded 引用。一旦定理插入或重排，会失败。
- 修复：加 `\label{thm:integrity}` 并把全文 "Theorem 1" 改为 `Theorem~\ref{thm:integrity}`

### H.2 Definition labels
- L477: `\label{def:g1}\label{def:cross-round}` — 双 label 是 OK 的，但奇怪
- L488: `\label{def:adwc}` ✅
- L508: `\label{def:g2}` ✅
- L547: `\label{def:g3}` ✅
- L556: `\label{def:g4}` ✅
- L563: `\label{def:g5}` ✅

### H.3 Equations 没有 label
- L394 (DP definition) 用 `\begin{equation}...\end{equation}` 但无 label — 不需引用，OK
- L711 (Location commitment) 同上
- L727 (Chain commitment) 同上
- 全文没有 numeric equation reference 需求，OK

---

## I. 修复优先级总览

按修复成本/收益排序，建议执行顺序：

### I.1 必须 Day 1 (低成本高收益)
- A.2 (P4)/(P5) → (C6)/(C7) （5 分钟）
- A.3 tab:coverage A2 行 C6→C7（5 分钟）
- B.5 Definition 4 logical operator（10 分钟）
- B.1 MRR 加定义（10 分钟）

### I.2 必须 Day 1 (中成本高收益)
- A.1 Pipeline FRR 11.36 vs 4.02 — 必须先确定真值（可能要重跑 1 次）
- E 全部 — FRR 三义术语替换（grep 替换 30 分钟）
- B.2/B.3 "first" claim 4 处统一（10 分钟）

### I.3 Day 2-3
- A.4 实测 salted constraint count（重 compile 一次）
- A.5 ε sweep 加 std（重跑实验或从已有 CSV 读 std）
- D.1 Table 4 L3 payload 列重新填

### I.4 Day 4-6 (随章节重写一起做)
- A.6 §VII 992B 段引用 §IV-C 而非重复
- A.7 mobile latency 注明 commodity CPU vs mobile
- C.1 符号风格 + Notation bridge 段
- C.2 K=6/K=30 标 "short-window/long-window stress test"
- C.3 verifier 三种命名统一
- F 引用核查

### I.5 Day 7 verify
- G 数字格式 grep 全文
- H Theorem label
- 编译 + chktex 0 fatal

---

## J. 总计问题数

| 类别 | 数量 |
|---|---|
| 🚨 数字硬伤 | 7 |
| ⚠️ 概念/标号映射 | 6 |
| 🔄 风格/符号混用 | 4 |
| 📌 数字/格式 | 4 |
| 引用风险 | 3 |
| Cross-ref | 1 |
| **总计** | **25** |

其中 **15 项是 P0/P1**，**10 项是 P2 润色**。配合 7 天日程在 Day 1
扫雷阶段就能消化掉一半左右。

---

*报告版本：2026-04-27 由 Claude grep + 人工核对编制。所有行号对应当前
main.tex 1718 行版本，修改后行号会变。*
