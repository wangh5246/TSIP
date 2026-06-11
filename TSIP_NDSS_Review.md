# TSIP (NDSS 投稿) 审阅意见

> 按 NDSS reviewer 视角（experimental rigor / threat model clarity / formal soundness 三轴）对全文逐节细评。
> 优先级标注：**Critical**（不修很容易被拒）/ **Important**（review 里会列为明确 weakness）/ **Minor**（polish）

---

## 一、全局性 Critical 问题

### 1. "128-byte proof" vs "807B proof" 前后矛盾
- Abstract、Intro、Table I、Conclusion 都写 "128 B Groth16 proof"
- Table VI 却写 proof size = 807 B；§VI-F 又说 "Groth16 proofs are constant at 128 B"
- **真相**：BN254 上 Groth16 压缩形式 (A,C∈G1 + B∈G2) 正好 128B；807B 大概率是 proof + 11 个 public inputs (11×32B ≈ 352B) + 少量 framing
- **必须修复**：在 §IV-D 或 §VI 明确区分 "proof object size (128 B)" 与 "wire payload (~2 KB including public signals + chain metadata)"
- Table VI 列名从 "proof (B)" 改为 "wire payload (B)"，或单列两栏 `π | π + publics`

### 2. S-curve 的 boundary 与 theoretical cap 对不上
- Fig. 3 标注的 transition 在 ~6534 m
- §V 写 A1 的 mode-specific cap: walk 180m / bike 600m / vehicle 1980m / transit 2400m (at Δt=60s)
- 6534m 远超任何 mode cap — 读者会立刻问：**测试用的是哪个 tier？cap_policy_sq 和 tier_anchor_cap_sq 关系是什么？**
- 看起来 Fig. 3 其实画的是 **anchor-distance cap**（K=6 × vehicle ≈ 11.9 km，cap_policy=0.5× 即 ~5.9 km，接近 6534m），而不是 per-step cap
- **必须修复**：图注明确 "testing against ADWC cap at K=6, vehicle tier, cap_policy=0.5×tier_anchor_cap"
- 目前的图和 §VI-C 的叙述暗示 per-step teleport detection，会误导审稿人

### 3. Threat model 里 A7 从未定义但在 §VI-G 出现
- §IV-B 只定义了 A1–A6
- §VI-G 最后说 "For A7 fallback characterization, we additionally run enrollment-authority fault injection..."
- **必须**：在 §IV-B 加 A7 (EA fault / enrollment-authority compromise)，或改成 "For EA fault characterization"

### 4. Mobile-class 数字全部是 "proxy"，没有真机测量
- §VI-F、Table VII 明确写 "analytic proxies scaled from server-side measurements"
- "DVFS and thermal-aware on-device measurements are deferred to future work"
- NDSS 审稿人会说：**你声称 mobile crowdsensing 系统，却没有一台真实手机的测量**
- **强烈建议**：至少跑 Pixel 6/7 或 iPhone SE 上 snarkjs / rapidsnark-mobile benchmark
  - 给 3 个真实数据点（proof gen time、energy via Battery Historian 或 `powermetrics`）
  - 哪怕 N=3 设备，有真机数据就能堵住这个洞

### 5. Groth16 proof verification 1030 ms 才是真正的 scaling bottleneck
- §VI-F(d) 承认："server verify 1030 ms per proof" 是 binding constraint
- N=1000 客户端每轮，单 verifier 需要 ~17 分钟 — 但 aggregation window 只有 60s
- 目前的"解决方案"只是一句话：horizontal verifier workers
- **需要**：加实际并行验证实验（即使 8-worker thread pool），给出 "with k workers, per-round latency = max(client_prove, verify_time / k)" 曲线
- 否则审稿人会直接说 "claimed scalability is not demonstrated"

### 6. Benign FRR 19.2%（k=6）和 46.8%（k=30）远超可部署阈值
- 解释是 "session-timing dominated"，但这个 "session-timing filter" 在 §IV 从未正式定义
- 读者不知道是 SVT？warmup？GeoLife 里连续观测间隔 > Δt 的 session break？
- 19% 诚实用户被剔除，在强调 deployability 的 NDSS 是巨大红旗
- **必须**：
  - 在 §IV 新增 "session-timing filter" 正式定义（应该是"同一用户连续两次 GPS sample 间隔 > max_gap 时视为 session 中断"）
  - §VI 单独实验说明：
    - T-Drive（采样密集）上 session-timing FRR 多少？
    - 是否可以通过调整 max_gap 或 re-enrollment 阈值把 FRR 压到 5% 以下？
- 目前表述会让审稿人认为 "TSIP 在稀疏数据集上不能用"

---

## 二、Important 问题

### 7. Related Work 引用可能有误（逐条核实）
- **[5] Nebula (Roth & Cuff, arXiv 1910.08059)**：NDSS 2024 有一篇 "Nebula: A Privacy-First Platform for Data Backhaul" by Wang et al.，是目前 ESA location aggregation 代表作。你引的 arxiv 1910.08059 似乎是另一篇（未发表，作者可能不是 Roth/Cuff）
- **[9] RiseFL (Pillutla et al., S&P 2024)**：RiseFL 通常引的是 Hao Chen 等人（SIGMOD 或 USENIX）。Pillutla 的工作可能是 "Robust Aggregation" (RFA)
- **[12] ZKSL (Wang et al., USENIX Security 2024)**：需要核对作者和会议
- **[10] EIFFeL**：通常是 Amrita Roy Chowdhury et al., CCS 2022 — 这个应该对

引文错误在 NDSS 是硬伤，每条都要能在 Google Scholar 1-click 查到，DOI 对得上。

### 8. Definition 重复与不一致
- Definition 2 (Cross-Round Trajectory Continuity) 和 Definition 3 (ADWC) 内容重叠严重
- Definition 4 (G1) 用 τ_i（按 index 下标），但 Definition 2 用 τ_u（按 user 下标）— **全局统一成 τ_u**
- Definition 2 的 "tier_anchor_cap²_u" 下标 u 突兀，正文里 cap 是 tier-级参数不是 user-级
- Definition 7 的 `commodeset` 很可能是 `com_modeset` 的排版错误，整篇论文出现多次这类 LaTeX spacing 问题
- **建议**：拆成 "cross-round continuity (informal security goal)" 和 "ADWC (formal cryptographic predicate)"

### 9. Theorem/Proposition 编号错乱
- "Theorem 1 (Theorem 1: the main circuit Integrity Properties)" — 括号内重复标题是排版错误
- Proposition 1 的标题写成 "(Proposition 2: VC Cost Stratification)"
- Theorem 3 的 proof 里 "Combining this with Proposition 2" — 但前面只有 Proposition 1
- **必须修复**：审稿人读到交叉引用错位会怀疑整篇稿件的打磨程度

### 10. Security Analysis 缺少 formal proof，只有 proof sketch
NDSS 对 security arguments 的 bar 比较高：
- Theorem 1 的 "reduction follows from Groth16 knowledge soundness and Poseidon collision resistance" 没有给出具体 game-based reduction
- G2 (Input Privacy) 的 "under EA introduction" argument 只有一段文字
- **建议**：
  - Theorem 1 按 A1–A6 逐条写 adversary game，每条给出 reduction
  - G2 写成 simulator-based proof：构造 Sim 对每个 server (Shuffler/Aggregator A/R/EA) 给出 view 的 indistinguishability argument
  - 至少把 Groth16 knowledge soundness 的 hiding/binding 属性对应到 TSIP 的哪些 public inputs
- 如果 proof 写不下，至少在 appendix 给出完整版

### 11. 缺少与"最近的竞争对手"的直接比较
你的 Class-1 vs Class-2 区分是诚实的，但审稿人仍会问：
- **ZK rollup 的 state transition proofs**（zkSync、Polygon zkEVM 的 state 证明本质上也是 cross-round）— 至少在 related work acknowledge 并说明 TSIP 的 domain-specific 优化
- **Zebra (Rondon et al., NDSS 2024 if applicable)** 或其他 location privacy + 完整性的新工作
- **Hardware attestation + DP 组合方案**（SGX-DP）作为 baseline — 即使只跑一个 "TEE-trusted-location" 近似 baseline，也能显著增强对比

### 12. Table IV 的 Jaccard "≈1.00" 对三个配置都一样非常可疑
- TSIP-FULL、COMMIT-ONLY、NO-INTEGRITY 全部 Jaccard≈1.00
- 如果 NO-INTEGRITY 吸收了恶意数据但 Jaccard 还是 1.00，说明恶意数据落在 ground-truth top-K 之外、SVT 又过滤了
- 需要给出具体数字（0.983、0.991、1.000）而不是 "≈1.00"
- Fig. 4 里 TSIP-FULL 在 ε=1.0 时 Jaccard=0.207，为什么 Table IV 的 T-Drive 又是≈1.00？两个数据集差距 4–5 倍 — 已解释是 SVT×密度，但 Table IV 应给出精确值

### 13. 缺失的 ablation: 每条 constraint 的边际贡献
§IV-D-3) 列了 C1–C16，但 §VI-E 的 ablation 只比较 FULL / COMMIT-ONLY / NO-INTEGRITY 三个粗粒度 setting
- 审稿人会问：**C8–C10 (hidden mode membership) 到底贡献了什么？** 能否去掉只留 C4 (tier cap)？
- 建议至少做 "disable mode constraints" 变体实验，看 A1 detection 是否下降、circuit 缩小多少

### 14. N=1000 对 NDSS 来说太小
- Abstract 声称 "up to 1,000 simulated clients"
- NDSS 审稿人看 ESA/location 系统通常期待 10k-100k 规模
- Prochlo 和 Nebula 都能处理 ≥10k
- 即使全在 simulation，也请把 N sweep 扩展到 N=5000 或 N=10000，哪怕只做 1 个 seed

### 15. 攻击者全为 simulated，没有 adaptive adversary
- 所有 A1–A6 的攻击 trace 都是 scripted（固定参数、固定策略）
- NDSS reviewer 会问：**攻击者针对你的 ADWC 策略做 best-response 怎么办？**
- 比如知道 cap_policy=3.3km，就按 cap_policy/K 恰好以下的速率 drift，per-round 和 window-sum 都刚好不触发
- 建议：加 "adaptive adversary" 实验，给攻击者 oracle access to all public params (tier_vmax_sq, cap_policy_sq, K)，看检测率是否掉

### 16. Commitment chain 和 EA 的 binding 没说清
- §IV-C 说 tag_sec = HMAC-SHA256(secret, uid) 用于 "registration and committee layer"
- §IV-A (a) 说 EA 建立 "enrollment metadata including federated anchors and public tier/mode parameters"
- 问题：**proof circuit 里如何保证 submitted proof 和 EA-attested tier_vmax_sq 一致？**
- 目前看起来只能靠 shuffler 维护 (uid → tier_vmax_sq) 表，proof 的 tier_vmax_sq 作为 public input 进来 shuffler 查表。这是 off-circuit check，应在 §IV 或 §V 显式说明
- 如果依赖 off-circuit check 才能把 EA attestation 和 proof 绑起来，那 "threshold EA → G4 Tier Integrity" 的证明链就不是纯 in-circuit 的，应诚实标注

### 17. Warmup policy 的攻击成本分析过于简化
- §IV-B 说 warmup 把攻击成本从 "0 提升到 N_warm·T_window 秒"
- 但 N_warm = max(K, 2) = 6 rounds = 6 分钟（k=6 profile）— 对 botnet 攻击者基本可忽略
- **建议**：
  - 让 warmup 和 tier 挂钩（高 tier 需要更长 warmup）
  - 或引入 "gradual influence weight"：warmup 后前若干轮以衰减权重进入 aggregate
  - 至少在 limitations 坦诚承认 warmup 防不住 determined adversary，只能提高 opportunistic attacker 成本

---

## 三、Important — Evaluation 设置细节

### 18. DP 预算的 SVT 参数
- §IV-F 写 SVT threshold τ=3.0, budget ε_SVT=0.3
- §VI-F 的 N sweep 里 FRR 随 N 下降（0.0402@50 → 0.0002@1000），意味着 SVT 在小 N 下剔除了大量正常用户
- SVT τ=3.0 对 N=50 不合适（典型 per-cell count 本就 <3）
- 建议：τ 应随 N scale（比如 τ = max(3, 0.01·N)），或至少跑 τ sweep 看敏感性
- Fig. 9、Fig. 10 的 (τ, τ₂) grid 是朝这个方向，但 τ 用 1–5 的整数小范围不足以覆盖部署场景

### 19. Communication 数字不一致
- Abstract: "≈2 KB per submission"
- Table IV: TSIP-FULL Comm = 2.0 KB
- Table X: bytes = 5,614 (≈5.5 KB), comm = 4.49 ms
- **5614 B vs 2 KB 差 2.7 倍** — 需说明 Table X 是否包含 double-encrypted shares、TLS overhead 等
- **必须澄清**：每个数字到底包含哪些字段（proof / public inputs / share_A / share_R / signature / TLS framing）

### 20. Groth16 verifier 1030 ms 异常地慢
- 标准 rapidsnark verifier 在 Intel Xeon 上验证 BN254 Groth16 proof 应该 < 10 ms
- 1030 ms 的 verify time 极其异常 — 是否因为把 "11 个 public inputs 上的 pairing precomputation" 也算进来了？或 Python binding overhead？
- **必须**：用 C++ rapidsnark 测一次，报告 "pure verifier latency (C++ optimal): X ms / Python wrapper overhead: Y ms / full pipeline per-submission: Z ms"
- 如果 verifier 真的 1030 ms，scalability claim 完全站不住
- 如果是 Python overhead，把它从关键路径移除

### 21. Dataset 选择的偏见
- T-Drive 是出租车数据 — vehicle tier 为主
- GeoLife 是研究者 + 实验对象，multi-modal 但非常规用户行为
- 这两个都不是 "mobile crowdsensing 真实用户"
- **建议**：
  - 至少加一个 synthetic dataset 模拟真实 bus-dispatch scenario（和 intro 里的 motivating example 对得上）
  - 或用 Porto taxi、NYC taxi 做 sanity check

### 22. Fig. 4 的 ε sweep 里 Nebula 达到 Jaccard=1.0 的解读
- 你写 "NEBULA (no privacy, no TSIP) converges to Jaccard 1.00 at ε ≥ 0.5, serving as the noiseless upper bound"
- 但 Nebula 本身是 DP 系统，"no privacy" 的说法是因为你的 mechanism-analogue 不加 DP noise？
- 容易引起误解 — 审稿人读到会说 "作者搞错了 Nebula 的定义"
- 应改为 "NEBULA-analogue with DP disabled"，或 "noiseless upper bound (which we label NEBULA for the ESA pipeline structure)"

### 23. Table X 的 e2e 差距
- TSIP-Full: 2243 ms, Commit-Only: 762 ms, No-Integrity: 13 ms
- TSIP 比 No-Integrity 慢 170× — 这是 per-client-round 的 wall-clock，用户每分钟发一次完全可接受
- **但需明确**：这个 2.2s 是否在 client 侧可以和 60s aggregation window 重叠？
- Table caption 加一句："This wall-clock is not user-facing latency; TSIP proof generation occurs in background during the Δt=60s window"

---

## 四、Writing / Presentation 问题

### 24. LaTeX 与标点问题
- 多处 `commodeset` 应为 `com_modeset` 或 `com_{modeset}`
- `comsec` 应为 `com_{sec}` — 整篇论文的下标都是 flat text，不是 math-mode
- `ℓw` 偶尔写成 `ell_w`，偶尔数学斜体，不统一
- "TSIPMAIN" 在 Fig 2 里是一个词；正文里应是 `TSIP_main` 或直接写 "main circuit"
- Definition 7 的公式里 `comsec, commodeset` 和 `exp, kid` 放在一起但没说明 `exp` 是什么（expiration？）
- "≈ 0.34 s–≈ 0.36 s" 重复 "≈"，应是 "≈ 0.34–0.36 s"

### 25. 术语不统一
- "TSIP-FULL" / "TSIP (Full)" / "TSIP main circuit" / "TSIPMAIN" — 统一
- "v2" / "v3-k6" / "v3-k30" — engineering log 味道，不适合论文。改为 "baseline" / "TSIP-K6" / "TSIP-K30"
- "MRR"（malicious reject rate）vs "TPR" 混用 — 挑一个
- "session-timing" / "session-gap" / "session-timing filter" 多种表述

### 26. Abstract 需要重写
- 前 6 行讲 motivation（太长）
- 后 10 行堆实验数字
- **缺**：enrollment truth gap 只在最后两句提，但这是核心限制应更早写
- **缺**：A3 (gradual drift) 被列为 motivation 四大攻击之一，但 detection rate 在 abstract 里没给（只给了 A1/A2/A5 的 100%）
- **建议**：重写成 "problem–approach–result–limitation" 四段，每段 3–4 句

### 27. Figure 2 架构图
- 图注过于简单（只有 "Overview of the TSIP system"）
- Stage 1/2/3 的划分对未看过 ESA 的读者不友好
- **建议**：图注加 3–4 句描述，解释每 Stage 的 actor、input、output
- Fig. 2(b) 的 "Verification Outcomes" 塞在右下小方块，像 afterthought — 建议独立为 Fig. 3 (renumber)

### 28. Fig. 1 motivating examples
- 两个子图 (a)(b) 设计得好，但缺 caption 解释
- "400 km / 5 min" 过于极端 — 不如用"50 km / 3 min"（intro 里已用）保持一致性

### 29. "v3-specific claims" 的表达
§VI-H 标题 "v3 Architecture: Circuit Cost, Anti-Tamper, and Federated EA" — v3 这个 version 号不应出现在 NDSS 论文里。**改为** "Cross-Cutting Evaluation: ..."

---

## 五、Minor / Polish

### 30. Table I 的 "∼100 KB" for EIFFeL
需要 pin 到具体 vector dim，否则审稿人会说 "EIFFeL 证明大小取决于 model size，你选的是哪个？"

### 31. Proof size in §II-E
"TSIP's circuit is intentionally minimal: ... 2,340 R1CS constraints yield ≈ 0.34 s ... proving latency"
- 这句在 §II 末尾重复了 §VI 的结论
- related work 里不该 leak evaluation results — 移到合适位置

### 32. §III-A 最后一段
"A critical gap that exists in all prior ESA implementations is that none enforce whether the sequence..."
- 这是观点不是 preliminaries 内容 — 挪到 §II 或 §IV-A

### 33. Cite [35] Shoup 1997 不合适
作为 q-type assumption 的来源并不合适 — q-type assumption 通常引 Boneh-Boyen 2004 或 Groth 本人。核对引用

### 34. Intro 末尾的 (i)(ii)(iii)(iv) 要与 §III-D G1–G5 对齐
"At first glance the required relation appears simple" 这段写得很好，但最后四点编号和 §III-D 的 G1–G5 要对齐，目前对应关系需要读者自己猜

### 35. Fig. 11 的 Bounded Sybil envelope 的单位
- "anchor-committee budget B_A" — B_A 单位是什么？USD？"credential acquisition units"？
- `c_anchor` 和 `c_VC(τ)` 的 unit 也没说
- Fig. 11 的 y 轴 `n_S^max` 从 0 到 60，但 abstract 声称 "up to 1,000 clients" — 如果 Sybil 上限是 60，那 N=1000 意味着至少 940 是真实用户
- 这个链条应在 §V 或 §VII 写出

### 36. Open Science
- 只说 "release artifact upon acceptance"
- NDSS 有 AE track，建议主动 opt-in 并说明 "we commit to AE evaluation"
- 可加 "artifacts submitted to AE include: Groth16 proving/verification keys, Python harness, docker-compose for shuffler/aggregator/decoder, 3 dataset preprocessing scripts"

### 37. Ethics
- 当前段落可以，但 NDSS 明确要求讨论 **compliance with Computer Fraud and Abuse Act / jurisdictional considerations** 如涉及攻击实验
- 你的攻击都是 simulation against your own system，可加一句 "All adversarial experiments are conducted against our own prototype with simulated clients; no third-party systems were probed"

### 38. Conclusion 的 Roadmap
Conclusion 写 3 点 future work 很好，但应明确 which is next paper 和 which is long-term — NDSS reviewer 会根据这个判断你的 follow-up trajectory

---

## 六、NDSS 特定建议

1. **Artifact Evaluation**：NDSS 非常看重 AE。把 `scripts/reproduce/` 目录在 submission 时就能跑 end-to-end（即使用 N=10 的 mini config）对 camera-ready 很有帮助

2. **Response letter 准备**：NDSS 有 rebuttal，以下问题要提前准备回应：
   - "Why not STARK to avoid trusted setup?" → 现有 §VII Future Directions 提了，但回答要更具体（STARK proof 10KB+，circuit 复杂度至少 3×）
   - "How does ADWC compare to server-side trajectory validation?" → 强调 server 看不到 plaintext，只有 per-user commitments
   - "N=1000 is too small" → 准备好 verifier parallelism 的数据

3. **Threat model 明确写出 adversary's prior knowledge**：adversary 知道 public params，不知道 secret、不知道其他 user 的 coordinates — 这个要在 §IV-B 加一句

4. **TCB discussion**：TSIP 的 TCB 包含 Groth16 setup、EA 签名公钥、Poseidon/MiMC 密码学假设。在 §V 或 §VII 加 TCB 枚举列表

---

## 七、优先级总结（时间有限按此顺序改）

### 必须（截稿前 Day 1–3）
- [ ] 1. 128B vs 807B proof size 澄清 → 改 abstract、Table VI、§VI-F
- [ ] 2. S-curve 图注 + 和 per-step cap 的关系澄清 (Fig. 3)
- [ ] 3. A7 threat model 定义
- [ ] 4. Theorem/Proposition 交叉引用修复
- [ ] 5. Benign FRR 19%/47% 的 session-timing filter 正式定义
- [ ] 6. 引文 [5][9][10][12] 核对

### 强烈建议（Day 3–7）
- [ ] 7. 真机 mobile benchmark（哪怕 N=1 手机）
- [ ] 8. Adaptive adversary 实验
- [ ] 9. Verifier parallelism 实验
- [ ] 10. Game-based proofs in appendix
- [ ] 11. N=10000 scalability 数据

### Polish（Day 7–10）
- [ ] 12. 术语统一（TSIP-FULL 等）
- [ ] 13. LaTeX 排版（下标、commodeset → com_modeset）
- [ ] 14. Abstract 重写
- [ ] 15. Ethics / Open Science / AE 部分加强

---

## 整体评价

**核心贡献（in-circuit cross-round continuity + ADWC）清晰且有价值**，circuit 设计合理。

**最大风险**：
- (a) Experimental scale 和 rigor 不足
- (b) 真机数据缺失
- (c) Formal soundness argument 深度不够

如果上面 Critical 问题都能修掉，核心材料质量已接近 NDSS 录用线。
