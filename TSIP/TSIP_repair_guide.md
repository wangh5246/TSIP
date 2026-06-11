# TSIP 论文修复清单（投稿 NDSS 2027 前必读）

**适用版本**：当前 PDF（main(9).pdf，17 页）
**目标投稿**：NDSS 2027 Fall Cycle（截稿 2026-08-19）或更晚
**预计修复周期**：6–8 周专注工作
**修复完成判定**：所有 P0 项闭合 + 至少 1 位领域内同行 pre-review 通过

---

## 修复优先级总览

| 级别 | 含义 | 项数 |
|---|---|---|
| **P0** | 致命问题，不修则核心 claim 不成立或被审稿人当场打穿 | 5 项 |
| **P1** | 严重问题，会显著降低录用概率 | 4 项 |
| **P2** | 表述与定位问题，影响审稿印象 | 4 项 |
| **P3** | 合规与润色（NDSS CFP 强制） | 5 项 |

---

# P0：致命问题（必须修复，否则不要投稿）

## P0-1：补全 payload–location 一致性约束（核心 claim 缺口）

### 问题
当前 C6 仅证明 `Poseidon(payloadlo, payloadhi) = payload_commitment`，即 proof 绑定到一个 payload digest，但**没有任何约束证明 payload 中的 cell 索引是从隐藏坐标 (xw, yw) 正确编码得到**。

### 攻击场景
1. 攻击者在合法位置生成物理上合理的轨迹
2. 用真实 (xw, yw) 生成通过所有 ADWC、per-step、chain 检查的 ZK proof
3. 提交一个完全无关的 payload（任意污染 heatmap cell，例如灌入商场、政治敏感地点、竞争对手店面）
4. 所有 trajectory continuity 检查通过，aggregate heatmap 被污染

### 为什么致命
论文核心定位是 "location aggregation **integrity**"，目标是热图不被污染。这个 gap 直接打穿核心 claim。摘要、§I、§VIII 反复强调的"truthful inputs"、"plausible aggregation"全部失效。

### 修复方案

**电路层**：新增一组约束（命名为 C17–C19，或重排为 C6 子集）：

```
C17: cell_x = floor_div(x_w, cell_size)        // 网格坐标
C18: cell_y = floor_div(y_w, cell_size)
C19: payload[primary_idx] 中的 visited cell 包含 (cell_x, cell_y) 编码后的索引
```

具体实现思路（任选其一）：

- **方案 A（最小改动）**：在 payload 的 active slots 中至少有一个 slot 必须等于 `encode(cell_x, cell_y)`，circuit 强制证明此关系成立。Dummy slots 可保留为 client-chosen（用于 LDP 噪声），但至少 1 个 visited slot 必须与坐标对应。
- **方案 B（推荐）**：把 visited cell 索引集合改为 deterministic 的 `{encode(cell_x, cell_y)}`，dummy 集合通过 PRF(seed, w) 生成并暴露 seed 作为 public input，circuit 证明 dummy 集合等于 PRF 输出，visited 集合等于位置编码。这样 payload 完全由 (xw, yw) + seed 决定。
- **方案 C（理论最强但最贵）**：用 ZK-friendly merkle proof 证明 "payload 是从 (xw, yw) 经过 LDP 编码函数 LDP_encode(·) 得到的"，保留 randomized response 的随机性但绑定其种子。

### 必须重做的工作
1. 修改 circom 源码加入新约束
2. 重新编译，记录新的 R1CS 约束数（**预计从 2,403 升到 2,800–3,500**）
3. 重新生成 Groth16 proving/verification key
4. 重跑全部 benchmark：Table IX、Table VIII、Table XIII（移动端）、Table VII（verifier 路径）
5. 更新 Appendix B 的约束列表
6. 在 §V 的 Theorem 1 中新增 E6（payload encoding correctness）作为新的提取属性
7. 更新 Theorem 1 的攻击概率上界（多一个 hash collision term）

### 文档修改位置
- §IV-D（Circuit description）：新增 "Grid-encoding consistency" 子段
- Appendix B：列出 C17–C19 的明确公式
- §V Theorem 1：在 E1–E5 后加入 E6
- Table IX：更新约束计数与 prover/verifier 时间
- Table IV：补一行 NO-PAYLOAD-ENCODING ablation（验证此约束的必要性）

---

## P0-2：写透有限域中 "≤" 与距离计算的 soundness

### 问题
当前 Appendix B 只列了高层公式（`d² ≤ tier_vmax_sq · step_dt_sq` 等），但 R1CS / Groth16 在 BN254 域上**没有原生整数大小关系**。所有比较必须用 LessThan / bit-decomposition gadget 实现，且必须配套 range check。

### 审稿人会问的具体问题
- 坐标 (x, y) 的 bit-width 是多少？
- 坐标差 `x2 − x1` 是有符号的，如何在域中表示？是否补码？是否 range-check 后转无符号？
- 距离平方 `(x2−x1)² + (y2−y1)²` 是否可能 overflow（接近 p ≈ 2^254）？
- `step_dt_sq`、`tier_vmax_sq`、`cap_policy_sq` 是否都有显式 range check（< 2^n < p）？
- 所有 ≤ 是用什么 gadget 实现？LessThan？Num2Bits？
- 这些 range check 是否计入了你声明的 2,403 R1CS 约束？

### 为什么致命
ZK 系统论文最容易被打穿的就是这一层。如果攻击者能传一个数值上接近 p 的 `cap_policy_sq` 作为 public input，所有 `anchor_dist_sq ≤ cap_policy_sq` 平凡通过，Theorem 1 (E5) 直接失效。这不是 deployment hint，是 circuit soundness 本身。

### 修复方案

**新增 Appendix B.1 子节："Integer Semantics and Range Constraints"**，至少要包含以下内容：

1. **Bit-width 表**：
   ```
   x, y           : signed 24-bit (范围 ±8M 米，覆盖 16,000 km × 16,000 km 域)
   step_dt_sq     : unsigned 24-bit (Δt ∈ [1, 4096] s)
   tier_vmax_sq   : unsigned 16-bit (vmax ∈ [1, 256] m/s)
   cap_policy_sq  : unsigned 50-bit
   d²             : unsigned 50-bit (24-bit signed × 2 = 48 bits + slack)
   anchor_dist_sq : unsigned 50-bit
   timestamp t    : unsigned 32-bit
   ```
   所有中间值满足 < 2^60 << p ≈ 2^254，无 wraparound。

2. **Signed difference 处理**：
   ```
   dx_signed = x2 - x1   (in field, may be > p/2 if negative)
   Num2Bits(dx_signed + 2^24, 25)  // shift to unsigned
   d² = dx² + dy²        (computed in unsigned domain)
   ```

3. **比较 gadget**：所有 `a ≤ b` 实现为 `LessEqThan(60)(a, b) = 1`，每个 LessEqThan 约 60 个约束。

4. **Public input range checks**（最关键）：
   ```
   Num2Bits(cap_policy_sq, 50)         // 防止 cap 接近 p
   Num2Bits(tier_vmax_sq, 16)
   Num2Bits(step_dt_sq, 24)
   ```

5. **更新约束计数**：明确说明 range/comparison gadget 占 2,403 中的多少（预计 600–900 个约束）。如果当前 circom 代码没写完整 range check，**必须补上重编**，并报告新的约束计数。

### 必须做的事
- 读自己的 circom 源码，逐个比较找出所有 LessThan/LessEqThan 调用
- 检查 public inputs 是否都有 Num2Bits 约束
- 如果有缺失，补上、重编、重跑全部 benchmark
- 如果当前已经完整，把上述细节明确写入论文

### 文档修改位置
- 新增 Appendix B.1 "Integer Semantics and Range Constraints"
- §IV-D 提及 "All comparisons use LessEqThan gadgets with explicit range checks; details in Appendix B.1"
- Table IX 的 caption 注明约束计数包括 range/comparison gadget 开销

---

## P0-3：Δt 必须由 Shuffler 强制，不能由客户端自由输入

### 问题
当前 `step_dt_sq` 是 circuit 的 public input，但论文没有明确说明它由谁计算、谁验证。§VII 把"Shuffler clamp Δt"列为 deployment hint：

> "Production deployments could additionally clamp ∆t to a server-trusted lower bound to prevent clock-skew-induced cap inflation."

### 攻击场景
攻击者把 Δt 填成 3600s（1 小时），per-step 距离上限从 vehicle tier 1980m 直接放大到 119km。A1 teleportation 完全失效。Theorem 1 (E1) 在攻击者可控 Δt 下是空陈述。

### 为什么致命
这不是 deployment hint，是**协议安全前提**。Theorem 1 必须有一个清晰的 trusted Δt 定义才能成立。

### 修复方案

**协议层**：在 §IV-C 或 §IV-D 增加明确文字：

> "**Server-enforced timestamp validation.** The Shuffler maintains per-uid `last_accepted_server_timestamp_u`. Upon receiving a submission at server-side time `t_server`, the Shuffler computes:
> 
> ```
> Δt = t_server − last_accepted_server_timestamp_u
> if Δt < Δt_min or Δt > G:  reject (or trigger warmup re-entry)
> step_dt_sq = Δt²    // computed by Shuffler, included as public input
> ```
> 
> The client does **not** supply `step_dt_sq`; it is computed by the Shuffler and provided to the proof verification context. The client's local Δt estimate is used only for proof generation and must match the Shuffler's value (else verification fails on `step_dt_sq` mismatch). `Δt_min` defaults to 1 s; `G` (session-gap threshold) defaults to 30 min."

### Theorem 1 修改

E1 的陈述改为：

> "E1 (Per-step continuity, conditional on server-trusted Δt): Under Assumption SRV-TS (the Shuffler honestly computes and enforces `step_dt_sq`), `‖p_i − p_{i-1}‖² ≤ tier_vmax_sq · step_dt_sq` and `‖p_i − p_{i-1}‖² ≤ mode_vmax_sq(selected) · step_dt_sq`."

并在 §IV-B Threat Model 末尾新增 Assumption SRV-TS：

> "**Assumption SRV-TS (Server-Trusted Timestamp).** The Shuffler is honest in computing per-uid Δt from server-side receive timestamps. This assumption is consistent with the honest-but-curious server model of §IV-B."

### 文档修改位置
- §IV-C 或 §IV-D：新增 "Server-enforced timestamp validation" 段落
- §IV-B：新增 Assumption SRV-TS
- §V Theorem 1：E1 加 conditional on SRV-TS
- §VII：删除原 "Production deployments could additionally clamp Δt" 一句（已上升为协议要求）
- Appendix A "Session-timing filter"：与新协议描述同步

---

## P0-4：DP claim 与 sensitivity 计算必须对齐

### 问题
当前 §III-B 写 "pure ε-DP under user-level adjacency"、§IV-F 写 `εtotal=1.0, Δf=1`、§VI-A 写每客户端 100 active slots（50 visited + 50 dummy），T=10 rounds。

User-level adjacency = "差一个用户的全部记录"。该用户每轮贡献到 ≤ 50 个 visited cell，T=10 轮共贡献到 ≤ 500 个 cell-round 计数。**Δf=1 与 user-level adjacency + 100 active slots 在数值上不自洽**。

### 为什么致命
Privacy 方向审稿人（NDSS 这方向很多）会立刻在审稿表上写 "DP accounting is incorrect"。G3 不成立则整个 §V 的 composition 论述都要重写。

### 修复方案（三选一）

**方案 A（推荐，改动最小）：L1 clipping 到 1**

每个用户每轮的 payload 贡献向量 L1 范数限制为 1。具体实现：
- 每轮只在 visited cell 里挑 1 个作为 "primary cell"，权重为 1（或归一化为 1/k for top-k）
- 所有 visited cell 权重之和 = 1
- Δf = 1 per round per user
- T 轮 sequential composition: εtotal = T × ε_per_round，所以 ε_per_round = 0.1，仍可用现有 SVT/Laplace 划分但需重新报告每轮 ε

代价：每个用户每轮只能"投票"一个 cell，丢失 multi-cell 表达。但对热图聚合任务影响可控。

**方案 B：保留 100 slots，调整 sensitivity**

- 声明 user-level Δf = 50（每轮 50 visited slot），总 Δf_T = 500（T=10 轮）
- 保持 εtotal=1.0 则 Laplace scale = 500/1.0 = 500，噪声会非常大
- Jaccard 会大幅下降，可能掉到 < 0.05

不推荐，因为会摧毁 utility claim。

**方案 C：降级为 event-level / per-window DP**

- 改 claim 为 "event-level ε-DP per release window，user-level per-window"
- T=1 时即为 user-level，T>1 需要明确 composition

需要重写 §III-B Definition 1 和 §V G3。

### 必须做的事
1. 选定方案（建议方案 A）
2. 重写 §III-B Definition 1 / §IV-F / §V G3 中所有 DP 论述
3. 修改 client 编码逻辑（如选方案 A）
4. 重跑 §VI-D 的 ε sweep + Jaccard 实验
5. 在 Table IV、Table XI 更新数字

### 文档修改位置
- §III-B：明确 privacy unit、composition strategy
- §IV-F：明确 sensitivity 计算
- §V Definition 5 (G3)：补 "after L1 clipping" 或对应限定
- §VI-A "Default configuration"：明确每用户每轮贡献单位
- §VI-D：重跑实验后更新数字

---

## P0-5：移动端 benchmark 内部矛盾必须消除

### 问题
- **摘要**：browser-based 物理设备测量 "on the salted artifact"，297.1 ms (iPhone) – 395.3 ms (Android)
- **§VI-F**：iPhone 数字是 "**pre-salt** on-device reference, not as a measurement of the rebuilt salted artifact"
- **Appendix G + Table XIII**：又写 on-device 测量是 "salted TSIP-K6 artifact"，"measured 2026-04-28"
- **Table XIII 同表**：Cortex-A78 proxy 1794.5 ms（与 iPhone 297 ms 相差 6×）

iPhone A18 Pro vs Cortex-A78 性能差距不可能 6× 同一个 R1CS 单线程任务。这组数字内部冲突。

### 为什么致命
NDSS 系统论文最忌讳 benchmark hygiene 问题。审稿人看到三处自相矛盾的描述会判定**有学术诚信风险**，即使其他都合格也会 reject。

### 修复方案（必须二选一，绝不能并存）

**方案 R（重测）**：在物理设备上重新测量当前 salted artifact

1. 在 iPhone 16 Pro Max 和 Android 设备上跑当前 2,403 约束（或 P0-1 修复后的新约束数）的 salted artifact
2. 记录：witness 生成时间、proof 生成时间、proof serialization 时间，全部分开报告
3. 记录：浏览器版本、snarkjs 版本、proving key 哈希
4. 删除 §VI-F 的 "pre-salt reference" 一句
5. Table XIII 只保留物理设备测量行，移除 Cortex-A78 proxy 行（或明确标注 proxy 是 server-side baseline，与 mobile 测量分开报告）

**方案 D（删除）**：承认这些是 pre-salt 数字，从主体中移除

1. 摘要中删除 297.1–395.3 ms 数字，只保留 "1.72–1.79 s on a commodity CPU"
2. §VI-F 中保留物理设备测量但明确标注 "pre-salt artifact (2,340 R1CS), retained as historical reference; current salted artifact (2,403 R1CS) is characterized through the Cortex-A78-class analytical proxy"
3. 移除 Abstract 中 "browser-based physical-device measurements on the salted artifact" 表述
4. Appendix G 改为 "Mobile measurement scope (pre-salt reference)"

### 推荐
**方案 R**。论文的 mobile 数字是少有的"上设备真测"的卖点，删掉很可惜。如果你能在 1-2 周内重测，强烈建议走 R。

### 文档修改位置
- 摘要
- §VI-F
- Appendix G "Mobile measurement scope"
- Table XIII（caption + 表格内容）
- §VIII Conclusion（如果提到 mobile 数字）

---

# P1：严重问题（强烈建议修复）

## P1-1：澄清 ESA 与 per-user continuity state 的隐私模型矛盾

### 问题
ESA 模型核心价值是 unlinkability，但 TSIP 要求 Shuffler 维护 per-uid 状态、做 per-uid timing 检查、看 chain topology——这已经**不是标准 ESA**。

§IV-B 已承认这一点，但摘要、§I、§II 仍把 "ESA pipeline" 当成卖点。

### 修复方案

**重新定位**：TSIP 不是 "privacy-preserving ESA aggregation"，而是 **"Shuffler-linkable, coordinate-hidden, output-DP location aggregation with cross-round integrity"**。

具体修改：

1. **摘要**：把 "Encode–Shuffle–Analyze (ESA) location-aggregation pipeline" 后立即加一句限定：
   > "Unlike standard ESA deployments that target full per-report unlinkability, TSIP exposes per-user chain topology and submission timing to the Shuffler in exchange for cross-round integrity; coordinate values remain hidden, and the released heatmap is protected by ε-DP."

2. **§I 倒数第二段**：在 contributions 列表前加一句定位说明，明确"我们牺牲了什么、保留了什么"。

3. **§II-A**：在介绍 Prochlo/Nebula 时明确 TSIP 与它们的隐私模型差异。

4. **§IV-B**：把当前末尾的"metadata leakage"段落上移到 §IV-A 开头，作为 system overview 的一部分公开声明。

### 文档修改位置
- 摘要（关键）
- §I（contributions 之前）
- §II-A
- §IV-A / §IV-B

---

## P1-2：G2 隐私定义需要诚实化

### 问题
当前 G2 challenge 要求两条候选轨迹"诱导相同的 public metadata、chain topology、accept/reject trace、timing"。这等于把最敏感的位置泄露**预先排除**了。

在位置系统里，accept/reject trace、session reset、tier/mode tag、提交时间都可能携带强位置信息。

### 修复方案

**重命名 G2 为 "G2: Coordinate-Value Privacy"**（而不是 Location Privacy）：

- 明确 G2 保护 "the numeric values of (x_w, y_w)"，不保护 "the trajectory shape or the user's mobility pattern"
- 在 §V 加一段 leakage analysis："A malicious Shuffler can infer mobility patterns from accept/reject sequences, session gap distributions, and tier/mode transitions. We do not model these leakages; mitigations require additional cryptographic infrastructure (e.g., oblivious transfer for accept/reject) outside this work's scope."

这样诚实，并不会让贡献变弱（因为 coordinate hiding 本身是有价值的），反而让审稿人觉得论述精准。

### 文档修改位置
- §III-E Definition 4（重命名 G2）
- §V Theorem 1 之后新增 "Leakage Analysis" 子段
- §V-c "Composition" 段落同步更新
- 摘要可不改（已经说"computational hiding of raw coordinates"）

---

## P1-3：A2b 排除后必须改 identity-swap 表述

### 问题
- Fig 1(b) 画的是"两用户交换身份"，更接近 A2b（共谋/凭证转移）
- 摘要写 "modeled secret-unknown identity-swap attacks"，已经限定但仍有歧义
- §I 和 §VIII 仍然给读者"防 identity swap"的整体印象

### 修复方案

**统一术语**：全文搜索 "identity swap" / "identity-swap"，按以下规则替换：

- 保留 "modeled secret-unknown identity impersonation"（A2a 的精确描述）
- 删除或改写宽泛的 "identity swap" claim

**Fig 1(b) 重画或重述**：

- 当前画法：两用户交换 ID
- 改为：单一攻击者尝试在不持有 secret 的情况下接管另一个 uid 的链
- 或：保留交换图但 caption 明确写 "Without access to either user's device-held secret, an attacker cannot continue either chain (A2a). Voluntary credential or device transfer (A2b) is outside the in-circuit guarantee and addressed behaviorally in §VII."

**摘要改动**：
- 原："TSIP detects 100% of teleportation, replay, and modeled secret-unknown identity-swap attacks"
- 改为："TSIP detects 100% of teleportation, replay, forged-proof, and secret-unknown impersonation attacks (A1, A5, A6, A2a). Voluntary credential/device transfer (A2b) is outside the in-circuit guarantee and addressed via behavioral signals (§VII)."

### 文档修改位置
- 摘要
- §I 倒数第二段（contributions）
- Fig 1(b) caption 与图本身
- §III-D / §IV-B
- §VIII Conclusion

---

## P1-4：统一 payload digest 哈希函数

### 问题
- §IV-C 写 `hpay = SHA-256(sort(idx))`
- Appendix B C6 写 `Poseidon(payloadlo, payloadhi) = payload_commitment`
- §VI 提到 "recompute payload digest" 但未指明用哪个

### 为什么严重
审稿人会问：proof 绑定的是 SHA digest 还是 Poseidon digest？Shuffler 重算的是哪个？chain commitment 用的是哪个？这种不一致会让人怀疑 spec 与 implementation 不匹配。

### 修复方案

**全协议统一**为 Poseidon-based payload commitment：

1. **§IV-C 重写**：
   ```
   Client computes:
     canonical_payload = sort_and_pack(active_slots)
     (payloadlo, payloadhi) = field_split(canonical_payload)
     hpay = Poseidon2(payloadlo, payloadhi)
   
   Chain commitment uses hpay (Poseidon-based, in-circuit compatible).
   Shuffler recomputes hpay using identical canonical encoding.
   ```

2. **删除 SHA-256 提及**：除非有特殊理由保留 SHA（如外部审计兼容），否则统一用 Poseidon。

3. **Appendix B C6**：与 §IV-C 文字保持完全一致的公式。

4. **§VI 实现描述**：明确"Shuffler runs the same Poseidon2 over the canonical encoding"。

### 文档修改位置
- §IV-C 公式 (3)
- Appendix B C6
- §V Theorem 1 E2
- §VI 实现细节段落
- Appendix C (a) A6 分析

---

# P2：中等重要（建议修复以提升录用概率）

## P2-1：补一个真正的 adaptive adversary 实验

### 问题
Table IV 的 ablation 几乎完全是机制定义的同义重复（去掉某层 → 检测不到某攻击）。Table VI 的 boundary sweep 仍偏 synthetic。审稿人会问："如果攻击者联合优化 payload pollution + 缓慢 drift + mode switching + timing，detection 还是 100% 吗？"

### 修复方案

**新增 §VI-X "Joint Adaptive Adversary Evaluation"**：

实验设计：
- 攻击者已知所有 public params（τ, K, cap, G, mode set）
- 攻击者目标：最大化 `expected_pollution = E[ Σ accepted_malicious_contribution ]`，subject to 不被任何检测层 reject
- 攻击策略空间（联合优化）：
  - 每轮 step displacement ∈ [0, τ·Δt)（per-step 不被 reject）
  - 累积漂移 ∈ [0, cap_policy)（ADWC 不被 reject）
  - Payload pollution: 在 grid-encoding 约束允许范围内（P0-1 修复后）选择 cell
  - Mode switching: 在 enrolled mode set 内切换以利用最大 vmax
  - Timing: 在 [Δt_min, G) 内调整提交频率

可用 grid search 或 Bayesian optimization 在 simulator 中找最优策略，报告：
- TPR（attack rejection rate）
- 攻击者成功污染的 cell-rounds 数
- 与 random adversary 的对比

### 修复位置
- 新增 §VI-X
- §VIII Conclusion 中提及 "robust to joint adaptive adversaries"（如果实验结果支持）

---

## P2-2：扩大 evaluation 规模或重新定位 scalability claim

### 问题
- 默认 N=50，T=10 偏小
- N=1000 是 simulated（不是真物理客户端）
- N=5000 / N=10,000 是 verifier-path projection，不是 full pipeline

### 修复方案（二选一）

**方案 A（工程量大）**：把 full pipeline 跑到 N=5000

需要并行化 simulator 的 prover 调用，预计需要 32-core 服务器跑 24-48 小时。

**方案 B（修辞修复）**：明确重新定位 scalability claim

- 摘要中删除 "with up to 1,000 simulated clients"，改为 "we demonstrate end-to-end correctness up to 1,000 clients and project verifier scalability up to 10,000 clients"
- §VI-F 表格 caption 更明确："Rows above N=1000 are verifier-path capacity projections under fixed per-proof verifier cost; not full-pipeline runs."
- §VII Limitations 加一段 "Full-pipeline scalability beyond N=1000 remains an engineering exercise; we report verifier-path projections that reflect production deployment cost."

推荐方案 B。

### 修复位置
- 摘要
- §VI-A、§VI-F
- §VII

---

## P2-3：弱化或移除 "first system" claim

### 问题
摘要、§I 写 "to the best of our knowledge, the first system to enforce cross-round trajectory continuity directly inside a zero-knowledge circuit for an ESA location-aggregation pipeline"。这种 claim 在 NDSS 容易被同行打：proof-of-location、anonymous credentials、verifiable sensor data、ZK state transition systems 都至少有部分相关工作。

### 修复方案

**降调 + 扩大 related work**：

1. 摘要改为："we present TSIP, which combines per-step speed bounding, K-window anchor-distance constraints, and proof–payload binding into a constant-size 128-byte Groth16 proof for ESA location aggregation"。删除 "first system"。

2. §II 新增至少 3 段相关工作讨论：
   - **Proof of Location**：APPLAUS、SureThing、location attestation 等
   - **Anonymous Credentials & Trajectory Validation**：Idemix、BBS+ in mobility、Sybil-resistant location systems
   - **Verifiable Sensor Data / ZK State Transition**：zkRollups、Hyperledger anchored sensors、TPM-based remote attestation in mobility

3. Table I 增加几行：APPLAUS、SureThing、Sybil-resistant location protocols。即使它们 cross-round continuity = ✗，也要列出，让对比公平。

### 修复位置
- 摘要
- §I 倒数第二段
- §II（扩展约 0.5 页）
- Table I

---

## P2-4：澄清 Sybil 防御边界

### 问题
Theorem 3（Bounded Sybil）依赖 EA threshold attestation 与外部 credential 成本，本质是**部署假设下的成本论述**，不是密码学防御。论文当前把它列为"main contribution"之一容易被质疑。

### 修复方案

1. §III-E Definition 7 (G5) 加限定："G5 is a deployment-cost guarantee under CA3, not a cryptographic prevention property."

2. §V Theorem 3 之前补一句："Theorem 3 quantifies the external acquisition cost of Sybil identities under the deployment assumption CA3; it does not preclude Sybil attacks under unbounded budget."

3. 摘要的 contributions 不要把 Sybil 防御作为独立卖点，可融入"complemented by EA-based threshold enrollment"。

### 修复位置
- 摘要（contributions 列表）
- §III-E Definition 7
- §V Theorem 3 前后
- §VIII Conclusion

---

# P3：合规与润色（NDSS CFP 强制 + 提升观感）

## P3-1：页数核查与压缩

NDSS 2027 规定：正文 ≤ 13 页，**Ethics、References、Appendices 不计入；Open Science 计入正文**。

### 操作
1. 用 NDSS 2026 模板（letter paper, two-column, Times 10pt+）重排
2. 精确测量 §I–§VIII + Open Science 的页数
3. 如超过 13 页，按以下顺序压缩：
   - 合并 Table II 与 Table III
   - Fig 5 + Fig 6 合成单图双面板
   - §VII 6 段压缩为 4 段
   - §VI-B 前两段合并

P0/P1 修复完成后页数会膨胀，请预留 0.5–1 页给新增内容。

---

## P3-2：添加 Generative AI 使用声明

NDSS 2027 强制要求披露生成式 AI 使用。

### 添加位置
References 之前，作为 Acknowledgments 章节末尾或独立短段：

```
Use of Generative AI

Generative AI tools were used for grammar polishing and figure
caption refinement during manuscript preparation. All technical
content, system design, experimental results, formal proofs, and
analysis are the authors' own work. The authors take full
responsibility for the veracity and correctness of all material
in this paper.
```

如果 AI 参与生成了完整段落，披露级别要相应提高（列出工具版本与具体章节）。

---

## P3-3：双盲合规自查

### 必查项
- [ ] 全文搜索任何作者真实姓名、单位简称
- [ ] 全文搜索 "SparseGuard" 或其他你的前作 → 改为第三人称引用或盲化为 [anon]
- [ ] Open Science 章节中的仓库 URL → 改为 "anonymous repository (URL upon acceptance)"
- [ ] 资助编号、Acknowledgments 章节 → 删除或改为 "[removed for blind review]"
- [ ] PDF 元数据：`\hypersetup{pdfauthor={}}` 清空 Author 字段
- [ ] 上传文件名：改为中性名（如 `tsip_submission.pdf`）

---

## P3-4：全文 "could" 修正

学术论文陈述事实应用现在时直陈，"could" 削弱贡献力度。

### Find & Replace 清单

| 当前 | 修改为 |
|---|---|
| "could produce private heatmaps"（摘要首句） | "produce private heatmaps" |
| "Short zero-knowledge proofs could also be used to enforce per-round validity"（§I） | "Short zero-knowledge proofs have been used to enforce per-round validity" |
| "TSIP shows that cross-round trajectory integrity could be enforced"（§VIII） | "TSIP shows that cross-round trajectory integrity can be enforced" |
| "These mechanisms could strengthen enrollment"（§II-C） | "These mechanisms can strengthen enrollment" |

注意：讨论"未来可能扩展"或"可选优化"时保留 could/would 是正确的。重点修改**陈述已完成事实**的地方。

---

## P3-5：模板与排版细节

- 使用 NDSS 2026 模板：https://www.ndss-symposium.org/ndss2026/submissions/templates/
- US Letter 纸张（不是 A4）。LaTeX 中 `\documentclass[letterpaper]{...}`
- Times 10pt+，行距 11pt+
- Adobe Reader 黑白打印测试
- 章节顺序：Conclusion → Open Science → Ethics Considerations → References（Ethics 必须紧邻 References）
- 表格 caption 末尾标点统一（统一加句号或统一不加）
- 全文小写自动编号工件（"VII-0b"）改为命名引用（"§VII Discussion"）
- §VI-G 中的 "k6" 与 "k30" 与正文 "K=6" / "K=30" 统一为大写 K
- References DOI 格式统一（要么都加要么都不加）

---

# 修复执行顺序与时间表

## 第 1-2 周：表述层 + 协议层修改（不动电路）
- P0-3：Δt 强制（协议改 + Theorem 1 修订）
- P0-4：DP sensitivity 重述
- P0-5：mobile benchmark（删除冲突或重测）
- P1-1：ESA 隐私模型重新定位
- P1-2：G2 改名为 Coordinate-Value Privacy
- P1-3：identity-swap 术语统一
- P1-4：payload digest 统一为 Poseidon
- P3-2、P3-3：AI 声明 + 双盲自查

## 第 3-4 周：电路改动 + 重编
- P0-1：grid-encoding 约束设计与实现
- P0-2：range check 完整性补全
- 重编 circom，记录新约束计数
- 重新生成 proving/verification key

## 第 5-6 周：实验重跑
- 重跑 Table IX（约束、prover/verifier）
- 重跑 Table VIII（verifier 路径微基准）
- 重跑 Table XIII（移动端，如选 P0-5 方案 R）
- 重跑 §VI-D ε sweep（DP 重定义后）
- P2-1：joint adaptive adversary 实验
- 重跑 Table IV、Table XI

## 第 7 周：写作整合
- P1-1 至 P1-4 文字落地
- P2-2 scalability claim 重定位
- P2-3 弱化 first claim + 扩 related work
- P2-4 Sybil 边界澄清
- P3-1 页数核查与压缩
- P3-4 "could" 修正
- P3-5 排版细节

## 第 8 周：内部 pre-review
- 找 1-2 位领域内同行（最好做过 ZK / DP 系统、有 NDSS/USENIX/S&P 投稿经验）
- 把修订版 + 本文档 + 原审稿意见一起发给同行
- 根据反馈做最后一轮修改
- 最终 PDF 元数据清理 + 双盲终检
- 提交

---

# 投稿决策建议

## 不要投 NDSS 2027 Summer Cycle (5/6)
- 修复时间不够（仅 1 周）
- Summer 拒后 Fall 不能重投同主题（CFP 明文规定）
- 仓促投稿 = 浪费整个 NDSS 2027 窗口

## 推荐时间线
- **目标 1**：NDSS 2027 Fall Cycle（截稿 2026-08-19，今天起约 16 周）— 时间充裕
- **备选 2**：USENIX Security 2027（cycle 通常 6 月、10 月、2 月）
- **备选 3**：IEEE S&P 2028 Spring（截稿一般 6 月初）

如果 P0-1 电路改动遇到困难，不要硬冲 8/19，宁可延到下一个 cycle。质量 > 速度。

---

# 自检 checklist（投稿前最后一遍过）

## P0 项
- [ ] payload-location 一致性约束已加入 circuit（C17–C19 或等价）
- [ ] Appendix B.1 完整描述 bit-width、signed handling、range checks
- [ ] Theorem 1 (E1) 在 SRV-TS 假设下重新陈述
- [ ] §IV 明确 Δt 由 Shuffler 计算
- [ ] DP sensitivity 与 user-level adjacency 自洽（方案 A/B/C 之一已实施）
- [ ] mobile benchmark 数字内部一致（无 pre-salt vs salted 冲突）

## P1 项
- [ ] 摘要明确 TSIP 不是标准 ESA（Shuffler-linkable）
- [ ] G2 重命名为 Coordinate-Value Privacy
- [ ] 全文 identity-swap 术语已统一
- [ ] payload digest 全文用 Poseidon

## P2 项
- [ ] 加入 joint adaptive adversary 实验
- [ ] scalability claim 已诚实定位
- [ ] "first system" claim 已弱化或加充分 related work
- [ ] Sybil 防御标注为 deployment-cost guarantee

## P3 项
- [ ] 正文 ≤ 13 页（letter, 2-col, Times 10pt+）
- [ ] AI 使用声明已添加
- [ ] 双盲自查（姓名、自引、URL、致谢、PDF 元数据）通过
- [ ] "could" 全文修正
- [ ] NDSS 2026 模板使用正确

## 同行 pre-review
- [ ] 至少 1 位 ZK 系统方向同行已审阅
- [ ] 至少 1 位 DP / privacy 方向同行已审阅
- [ ] 同行反馈已纳入

---

# 致命问题速查表

| 编号 | 问题 | 修复工作量 | 不修后果 |
|---|---|---|---|
| P0-1 | payload–location 一致性缺失 | 2-3 周（电路改动） | 核心 claim 不成立 |
| P0-2 | 有限域 range check 不全 | 1-2 周 | circuit soundness 不成立 |
| P0-3 | Δt 客户端可控 | 3-5 天 | Theorem 1 (E1) 是空陈述 |
| P0-4 | DP sensitivity 错误 | 3-5 天 + 重跑 | G3 不成立 |
| P0-5 | mobile benchmark 冲突 | 1-2 周（重测）或 3 天（删除） | 学术诚信风险 |

---

**最后**：这份清单基于审稿意见 + 我对论文的二次审视。如果有任何一项你认为审稿人理解有误（例如你 circom 源码里其实已经有完整 range check，只是论文没写明），先用代码或文档证据回应再决定是否修改。但 P0-1（payload-location gap）几乎可以确定是真实存在的设计缺口，必须修复。

祝修订顺利。
