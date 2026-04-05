# TSIP 顶会论文精进指南 — 完整展开版

> 本文档针对 TSIP (Temporal-Spatial Integrity Proof) 论文的每一个关键薄弱环节，提供详细的修复方案、代码框架、实验设计和写作指导。目标投稿：NDSS 2027 Cycle 2 / USENIX Security 2027 Cycle 1。

---

## 目录

1. [底层设定修复](#1-底层设定修复)
   - 1.1 威胁模型统一与形式化
   - 1.2 Enrollment 锚点安全边界
   - 1.3 Lemma 1 循环论证修复
   - 1.4 MPC 协议明确化
2. [安全证明重写](#2-安全证明重写-game-based--reduction)
   - 2.1 Game-Based 安全定义
   - 2.2 Soundness 归约证明
   - 2.3 Privacy 证明修复
   - 2.4 Theorem 4 通信下界修复
3. [Baseline 实现方案](#3-baseline-实现方案)
   - 3.1 RiseFL 实现
   - 3.2 Nebula 实现
   - 3.3 Pure LDP (OUE) 实现
   - 3.4 No-Integrity Baseline
   - 3.5 Commitment-Only Baseline (无 ZK)
4. [攻击类型扩展](#4-攻击类型扩展)
   - 4.1 A1: 瞬移攻击（改进版）
   - 4.2 A2: 身份交换攻击
   - 4.3 A3: 渐进偏移攻击
   - 4.4 A4: Sybil 协调注入
   - 4.5 A5: 重放攻击
5. [Utility 实验设计](#5-utility-实验设计)
   - 5.1 热力图质量指标
   - 5.2 Privacy-Utility Tradeoff
   - 5.3 攻击下的聚合质量退化
6. [消融实验设计](#6-消融实验设计)
7. [规模与性能实验](#7-规模与性能实验)
8. [论文结构与写作](#8-论文结构与写作)
9. [时间线规划](#9-时间线规划)

---

## 1. 底层设定修复

### 1.1 威胁模型统一与形式化

**问题诊断**：当前文档中同时定义了三类攻击者（A/B/C），但安全证明只覆盖了 A+B 的组合。混合攻击者 C 没有形式化处理，而 k-of-t 委员会机制虽然工程实现了，但没有进入安全证明。

**修复方案**：采用顶会标准的"分层威胁模型"写法。

```
修复后的威胁模型定义：

Threat Model.
We consider a system with N clients, one Shuffler committee of t nodes,
and two Aggregators (A, R).

Adversary capabilities:
• The adversary controls up to f < N/2 clients (malicious, arbitrary
  behavior, including Sybil identities).
• Among the t Shuffler nodes, the adversary controls at most t-k nodes
  (i.e., at least k nodes remain honest), where k is the committee
  threshold.
• Between Aggregators A and R, the adversary controls at most one
  (honest-but-curious).

Trust assumptions:
(T1) At least k-of-t Shuffler nodes follow the protocol faithfully.
(T2) At least one Aggregator is honest-but-curious (does not deviate
     from protocol but may try to learn individual locations).
(T3) The ZK-SNARK setup (CRS generation) is trusted (or performed
     via MPC ceremony).

Non-goals (explicitly out of scope):
• We do not protect against a fully malicious Shuffler committee
  (all t nodes compromised).
• We do not prevent denial-of-service attacks.
• We do not guarantee trajectory truthfulness for the enrollment
  submission (see Section X for discussion).
```

**关键原则**：每个定理的陈述必须明确引用它依赖的假设子集。例如：

- Theorem 1 (Soundness): 依赖 T1 + T3 + Groth16 knowledge-soundness + Poseidon collision-resistance
- Theorem 2 (Privacy): 依赖 T2 + DP composition
- Theorem 3 (ZK): 依赖 T3 + DDH assumption

**k-of-t 的安全性形式化**：

```
Definition (Committee-Verified Integrity).
A submission (enc_loc, H_curr, π) is committee-verified if at least k
out of t Shuffler nodes independently:
  (1) verify π against (H_prev, H_curr, max_dist_sq), and
  (2) produce an attestation signature σ_i.

The Aggregators accept a submission only if they receive ≥ k valid
attestations.

Lemma (Committee Soundness).
Under assumption T1, if a submission passes committee verification,
then the TSIP proof π was verified by at least one honest Shuffler node.

Proof. Since the adversary controls at most t-k Shuffler nodes and the
threshold is k, at least one of the k attestations must come from an
honest node. An honest node only attests after successful proof
verification. □
```

### 1.2 Enrollment 锚点安全边界

**问题诊断**：TSIP 的 soundness 只对链深度 ≥1 的提交成立。恶意用户可以在 enrollment 阶段提交虚假的 H₀，然后构造一条"物理合法但完全虚构"的轨迹。

**修复方案（三层策略）**：

**层一：论文层面 — 精确界定安全声明**

```
Definition (Temporal-Spatial Integrity, Revised).
TSIP guarantees that for any enrolled user with commitment chain
depth ≥ 1, each submitted location is spatially consistent with
the user's previously committed location — that is, the displacement
does not exceed v_max · Δt.

TSIP does NOT guarantee:
• That the enrollment location corresponds to the user's true
  physical location.
• That the user is a real person (Sybil resistance is orthogonal).

Discussion: The enrollment submission establishes a "trust anchor."
Its integrity relies on out-of-band mechanisms (e.g., device
attestation, registration-time verification). Once the anchor is
established, TSIP ensures all subsequent locations form a physically
plausible trajectory.
```

**层二：协议层面 — Enrollment 不进聚合**

这个你已经实现了（`TSIP_BOOTSTRAP_POLICY=enroll_only`）。论文中需要明确写出：

```
Protocol modification: The first submission from each user in a
session is treated as an enrollment-only submission. It establishes
H₀ but does NOT contribute to the aggregate heatmap. Only submissions
with depth ≥ 1 (i.e., accompanied by a valid TSIP proof linking to
a previous commitment) enter the aggregation pipeline.
```

**层三：增强层面 — 可选的 Enrollment 验证（不要求论文完成，但讨论）**

在 Discussion 章节中提出以下增强方向，展示你考虑过这个问题：

```
Strengthening enrollment:
(1) Device attestation: Require the enrollment submission to include
    a hardware attestation (e.g., Android SafetyNet / Apple DeviceCheck)
    binding the location to a physical device.
(2) Proof-of-presence: Require the enrollment location to be
    corroborated by a proximity proof (e.g., Wi-Fi AP signature).
(3) Rate limiting: Limit enrollment frequency per device/account
    to mitigate Sybil + fresh-enrollment attacks.
```

### 1.3 Lemma 1 循环论证修复

**问题诊断**：Lemma 1 声称 TSIP 验证消耗 ε_verify = 0.2 的隐私预算，但推导存在两个严重问题：

1. 最终方案使用 Laplace 噪声给 verify score 加噪，但实验中 `TSIP_VERIFY_DP_ENABLE=0`（关闭状态）
2. 即使打开，ε_verify = 0.2 产生的 Laplace 噪声 scale = 1/0.2 = 5，而 score ∈ {0,1}，这意味着大约 40% 的概率 noisy_score 的符号会翻转，FPR 和 FNR 都会剧烈恶化

**修复方案（推荐方案 B）**：

**方案 A：打开随机化 verify 并诚实报告代价**

```python
# 如果坚持 Lemma 1 的路线，必须在实验中打开并报告
# 配置：TSIP_VERIFY_DP_ENABLE=1, TSIP_VERIFY_EPSILON=0.2

# 预期影响分析：
# score ∈ {0, 1}，noise ~ Lap(1/ε) = Lap(5)
# threshold = 0.5
#
# True Positive (honest user, score=1):
#   P[1 + Lap(5) > 0.5] ≈ P[Lap(5) > -0.5] ≈ 0.952
#   → FNR ≈ 4.8% (之前 ≈ 0.17%)
#
# True Negative (malicious user, score=0):
#   P[0 + Lap(5) > 0.5] = P[Lap(5) > 0.5] ≈ 0.048
#   → 攻击通过率 ≈ 4.8% (之前 = 0%)
#
# 这个代价非常高！malicious_reject_rate 从 100% 降到 ~95.2%

# 实验需要报告的表格：
# | ε_verify | FPR (false reject) | FNR (missed attack) | ε_total |
# |----------|-------------------|---------------------|---------|
# | 0 (off)  | 0.0017            | 0.0000              | 0.8*    |
# | 0.1      | ~0.07             | ~0.07               | 0.9     |
# | 0.2      | ~0.05             | ~0.05               | 1.0     |
# | 0.5      | ~0.02             | ~0.02               | 1.3     |
# * 当 ε_verify=0 时，verify 步骤的 1-bit 泄露不在 DP 框架内
```

**方案 B（推荐）：将 verify 步骤视为 DP 之前的预处理**

这是更干净的处理方式，很多顶会论文都采用类似的分析框架：

```
论文中的写法：

Remark (Privacy of the verification step).
The TSIP proof verification is a deterministic function of each
user's submission and does not access the submissions of other
users. The binary outcome (accept/reject) reveals whether the
user's trajectory satisfies the distance constraint, which is a
property of the user's own data.

In the DP framework, the verification step can be modeled as a
per-user filter applied before aggregation. Since DP protects
against changes to one user's data while all other users' data
remain fixed, and the verification outcome for user i depends
only on user i's submissions, this step does not consume DP budget
from the perspective of protecting user i's privacy against the
server.

However, we acknowledge that the accept/reject outcome does leak
1 bit of information about the user's trajectory to the Shuffler
(specifically, whether the displacement exceeded v_max · Δt).
This leakage is inherent to any integrity verification scheme
and is mitigated by two factors:
(1) The Shuffler only learns a binary outcome, not the actual
    displacement or location.
(2) Under our threat model, the Shuffler is part of the trusted
    infrastructure (assumption T1).

Consequently, our DP guarantee of (ε=0.8, δ=10⁻⁸) applies to
the aggregated heatmap output, with ε = ε_SVT + ε_value = 0.3 + 0.5.
```

**方案 B 的优势**：
1. 不需要引入随机化 verify，malicious_reject_rate 保持 100%
2. ε 的计算更诚实，不需要 Lemma 1
3. 顶会审稿人更容易接受（因为很多 secure aggregation 论文都是这样分析的）
4. 但需要在 Discussion 中诚实讨论 verify 步骤的 1-bit 泄露

**如果采用方案 B，原 Lemma 1 删除，改为上面的 Remark。**

### 1.4 MPC 协议明确化

**问题诊断**：文档中提到 share_A 和 share_R，但没有说明具体的秘密分享方案和聚合协议。

**修复方案**：明确描述你实际使用的方案。根据代码结构推测，你使用的是 2-out-of-2 加性秘密分享：

```
Secret Sharing Scheme.
We use additive secret sharing over Z_p, where p is a large prime.

Share generation (client side):
  For each location (x, y) mapped to cell index c ∈ [D]:
  1. Client generates a one-hot vector v ∈ {0,1}^D with v[c] = 1
  2. Client samples r_A ←$ Z_p^D uniformly at random
  3. Client computes r_R = v - r_A mod p
  4. Client sends r_A to Aggregator A, r_R to Aggregator R

Aggregation (server side):
  Aggregator A computes S_A = Σ_{i ∈ valid} r_A^{(i)}
  Aggregator R computes S_R = Σ_{i ∈ valid} r_R^{(i)}

Reconstruction (Decoder):
  Decoder receives S_A and S_R
  Decoder computes histogram = S_A + S_R mod p
  This equals Σ_{i ∈ valid} v^{(i)}, the true aggregate

Security: Under assumption T2 (at least one Aggregator honest),
no single party learns any individual user's location.
Aggregator A sees only random shares; Aggregator R sees only
complementary random shares. Neither can reconstruct v^{(i)}
without the other's share.
```

如果你实际用的是稀疏表示（每个用户只发 Top-K 个 cell 的索引和值），需要说明：

```
Sparse representation optimization:
Instead of dense D-dimensional vectors, each client sends:
  - To Aggregator A: {(idx_j, val_A_j)}_{j=1}^{K}
  - To Aggregator R: {(idx_j, val_R_j)}_{j=1}^{K}
where val_A_j + val_R_j = dwell_time_j for cell idx_j.

Communication per client: O(K) instead of O(D).
```

---

## 2. 安全证明重写 (Game-Based + Reduction)

### 2.1 Game-Based 安全定义

**当前问题**：安全定义是自然语言描述，不是标准的密码学游戏。

**修复后的 Soundness 定义**：

```latex
Definition 1 (TSIP Soundness Game).
The TSIP soundness game Game^{sound}_{TSIP,A}(λ) between a challenger C
and an adversary A proceeds as follows:

Setup:
  C runs TSIP.Setup(1^λ) to generate (crs, pk, vk).
  C gives (crs, pk) to A.

Challenge:
  A interacts with C in multiple rounds. In each round r:
  • A submits (H_prev^{(r)}, H_curr^{(r)}, π^{(r)}) for any user
    identity of A's choice.
  • C verifies π^{(r)} using vk and returns accept/reject.

Winning condition:
  A wins if there exists a round r where:
  (1) C returned accept for (H_prev^{(r)}, H_curr^{(r)}, π^{(r)})
  (2) For the witness w = (x1,y1,x2,y2) extracted from π^{(r)}
      (via the knowledge extractor):
      ||（x2,y2) - (x1,y1)|| > v_max · Δt
      OR Hash(x1,y1) ≠ H_prev^{(r)}
      OR Hash(x2,y2) ≠ H_curr^{(r)}

Advantage:
  Adv^{sound}_{TSIP}(A) = Pr[A wins Game^{sound}_{TSIP,A}(λ)]

TSIP is sound if for all PPT A:
  Adv^{sound}_{TSIP}(A) ≤ negl(λ)
```

### 2.2 Soundness 归约证明

**修复后的完整归约**：

```
Theorem 1 (TSIP Soundness).
If Groth16 is knowledge-sound and Poseidon is collision-resistant,
then TSIP is sound. Specifically:

  Adv^{sound}_{TSIP}(A) ≤ Adv^{ks}_{Groth16}(B1) + Adv^{cr}_{Poseidon}(B2)

where B1, B2 are PPT algorithms constructed from A.

Proof.
Assume A wins Game^{sound}_{TSIP,A}(λ) with non-negligible probability.
We consider two cases based on how A wins.

CASE 1: A produces an accepting proof π for public inputs
(H_prev, H_curr, max_dist_sq) such that the extracted witness
w = (x1,y1,x2,y2) does NOT satisfy the circuit constraints.

  That is, at least one of:
  (a) Poseidon(x1,y1) ≠ H_prev, or
  (b) Poseidon(x2,y2) ≠ H_curr, or
  (c) (x2-x1)² + (y2-y1)² > max_dist_sq

  In this case, we construct B1 that uses A to break Groth16's
  knowledge-soundness:

  B1 receives (crs, pk, vk) from the Groth16 challenger.
  B1 forwards (crs, pk) to A.
  B1 runs A and obtains (H_prev, H_curr, π).
  B1 uses the knowledge extractor E to extract witness w from π.
  If w does not satisfy the circuit → B1 breaks Groth16 soundness.

  Therefore:
  Pr[Case 1] ≤ Adv^{ks}_{Groth16}(B1) ≤ negl(λ)

CASE 2: A produces an accepting proof π for public inputs
(H_prev, H_curr, max_dist_sq) such that the extracted witness
w = (x1,y1,x2,y2) satisfies all circuit constraints, BUT the
actual trajectory violates the physical constraint.

  This means:
  • Poseidon(x1,y1) = H_prev ← circuit-enforced
  • Poseidon(x2,y2) = H_curr ← circuit-enforced
  • (x2-x1)² + (y2-y1)² ≤ max_dist_sq ← circuit-enforced

  For A to still have a trajectory violation, A must have
  submitted a DIFFERENT pair (x1',y1') in the previous round
  such that H_prev = Poseidon(x1',y1') = Poseidon(x1,y1)
  but (x1',y1') ≠ (x1,y1).

  This is exactly a collision in Poseidon!

  We construct B2 that uses A to find a Poseidon collision:
  B2 records all commitments submitted by A.
  When A produces a proof with extracted (x1,y1) such that
  Poseidon(x1,y1) = H_prev but (x1,y1) ≠ (x1',y1') previously
  committed → B2 outputs the collision pair.

  Therefore:
  Pr[Case 2] ≤ Adv^{cr}_{Poseidon}(B2) ≤ negl(λ)

Combining both cases:
  Adv^{sound}_{TSIP}(A) ≤ Adv^{ks}_{Groth16}(B1) + Adv^{cr}_{Poseidon}(B2)
                        ≤ negl(λ)                                        □
```

**注意点**：

1. Case 2 是你原来没有覆盖到的关键归约步骤——从"TSIP 被攻破"归约到"Poseidon 碰撞"
2. 整个证明不需要讨论具体的攻击场景（身份交换、瞬移等），因为归约已经覆盖了所有情况
3. 身份交换攻击等可以作为 Corollary（推论）：

```
Corollary 1 (Identity Swap Resistance).
Under the soundness of TSIP, two users Alice and Bob cannot
successfully swap their commitment chains without being detected.

Proof sketch. If Alice attempts to continue Bob's chain, she
must produce a proof π linking Bob's H_prev to her new location.
The extracted witness must satisfy Poseidon(x1,y1) = Bob's H_prev,
meaning Alice must know (x1,y1) such that this holds. Since she
does not know Bob's previous coordinates (only the hash), finding
such (x1,y1) requires either breaking Poseidon's preimage resistance
or finding a collision, both with negligible probability. □
```

### 2.3 Privacy 证明修复

**采用方案 B（推荐）后的 Privacy Theorem**：

```
Theorem 2 (Privacy of TSIP).
The TSIP protocol satisfies (ε, δ)-differential privacy for the
aggregated heatmap output, where ε = ε_SVT + ε_value and
δ = δ_SVT.

Proof.
We analyze the privacy of the aggregation pipeline, which
consists of three stages:

Stage 1: Integrity Filtering (Shuffler)
  The Shuffler verifies each user's TSIP proof and produces a
  binary accept/reject decision. This decision depends only on
  the submitting user's own data (current and previous location).
  It does not access other users' data.

  By the billboard lemma [Hsu et al., 2014], a mechanism that
  applies a per-record filter (depending only on that record)
  before an (ε,δ)-DP mechanism preserves (ε,δ)-DP.

  Privacy cost of this stage: 0.

Stage 2: Secure Aggregation (Aggregators A, R)
  Under assumption T2, the secret sharing scheme provides
  information-theoretic privacy. No single aggregator learns
  any individual contribution. The reconstruction produces only
  the aggregate histogram.

  Privacy cost of this stage: 0.

Stage 3: DP Noise Addition (Decoder)
  3a. Sparse Vector Technique (SVT):
      The Decoder applies SVT to identify cells with counts
      exceeding a noisy threshold. By Theorem 3.25 of [Dwork
      and Roth, 2014]:
      Privacy cost: (ε_SVT, 0)-DP with ε_SVT = 0.3.

  3b. Value perturbation:
      For cells passing the threshold, the Decoder adds
      Laplace noise Lap(Δf/ε_value) to each count.
      Global sensitivity: Δf = K (each user affects at most
      K cells by at most 1 count each).
      Privacy cost: (ε_value, 0)-DP with ε_value = 0.5.

By sequential composition [Dwork et al., 2006]:
  ε_total = ε_SVT + ε_value = 0.3 + 0.5 = 0.8
  δ_total = 0

Note: The verification step (Stage 1) is excluded from the DP
accounting. We discuss its information leakage in Section 8.1
(Limitations).                                                 □
```

### 2.4 Theorem 4 通信下界修复

**问题诊断**：原 Theorem 4 声称 TSIP 达到了 O(λ + log T) 的通信下界，但这是不准确的：

1. Groth16 证明大小是 O(1)（3 个群元素，约 128 bytes），与 T 无关
2. 你的协议中每轮发送一个证明，总通信是 O(T · λ)，不是 O(log T)
3. 下界证明的推导过程过于粗略

**修复方案：删除 Theorem 4 或大幅修改**

**选项 A（推荐）：删除 Theorem 4，改为简单的效率分析**

```
Per-submission communication cost:
  • TSIP proof:           ~710 bytes (Groth16 proof)
  • Current commitment:    32 bytes (Poseidon hash)
  • Previous commitment:   32 bytes (Poseidon hash)
  • Encrypted location:   ~200 bytes (shares for A and R)
  Total per submission:  ~974 bytes ≈ 1 KB

This is independent of the domain size D and the number of time
windows T, making TSIP communication-efficient for large-scale
deployments.

Comparison with RiseFL:
  RiseFL requires transmitting inner products with m random vectors
  over a d-dimensional space, resulting in O(m·d) communication
  per submission. For d = 10^6 and m = 10, this is ~40 MB per
  submission — four orders of magnitude larger than TSIP.
```

**选项 B：改写为更modest的claim**

```
Theorem 4' (Communication Efficiency).
The per-submission communication cost of TSIP is O(λ), which is
independent of the domain size D and the trajectory length T.

Proof. Each submission consists of a Groth16 proof (O(λ) bits),
two Poseidon commitments (O(λ) bits each), and encrypted location
shares (O(λ) bits). The total is O(λ). □

This contrasts with range-proof-based approaches (e.g., RiseFL)
that require O(D) or O(m·D) communication per submission.
```

---

## 3. Baseline 实现方案

### 3.1 RiseFL 实现

**RiseFL 的核心思想**：服务器生成随机向量 a₁,...,aₘ，客户端计算其位置向量 v 与每个随机向量的内积 zⱼ = ⟨v, aⱼ⟩，服务器验证 Σ zⱼ² ≤ B²（卡方检验）。

**你需要实现的不是完整的 RiseFL 系统，而是其核心验证逻辑在你的场景下的适配版本。**

```python
# baselines/risefl_baseline.py

import numpy as np
from scipy.stats import chi2

class RiseFLBaseline:
    """
    RiseFL-style single-point norm verification baseline.
    
    RiseFL 验证每个时间窗口内位置向量的 L2 范数是否在合理范围内，
    但无法验证跨时间窗口的时空连续性。
    
    对于公平对比，我们在 TSIP 的系统框架内替换验证模块。
    """
    
    def __init__(self, domain_size=10000, m=10, alpha=0.05):
        """
        Args:
            domain_size: 网格域大小 D
            m: 随机向量数量
            alpha: 显著性水平（χ² 检验）
        """
        self.domain_size = domain_size
        self.m = m
        self.alpha = alpha
        self.threshold = chi2.ppf(1 - alpha, df=m)
        
        # 每轮生成新的随机向量
        self.random_vectors = None
    
    def server_generate_challenge(self):
        """服务器为每轮生成 m 个随机向量"""
        self.random_vectors = [
            np.random.randn(self.domain_size)
            for _ in range(self.m)
        ]
        return self.random_vectors
    
    def client_compute_proof(self, location_vector):
        """
        客户端计算 RiseFL 证明
        
        Args:
            location_vector: 稀疏的 one-hot 或 top-K 位置向量，维度 D
        
        Returns:
            inner_products: 内积向量 [z_1, ..., z_m]
        """
        inner_products = []
        for a in self.random_vectors:
            z = np.dot(location_vector, a)
            inner_products.append(z)
        return np.array(inner_products)
    
    def server_verify_single(self, inner_products, norm_bound):
        """
        服务器验证单个提交
        
        验证: Σ z_j² ≤ norm_bound² · threshold
        
        ⚠️ 关键：这只验证当前位置的范数合理性
                不验证与历史位置的时空连续性
        """
        sum_sq = np.sum(inner_products ** 2)
        return sum_sq <= norm_bound ** 2 * self.threshold
    
    def verify_submission(self, user_id, location_vector, 
                          prev_location=None, norm_bound=1.0):
        """
        完整的 RiseFL 验证流程
        
        注意：prev_location 参数被忽略——这正是 RiseFL 的核心缺陷。
        """
        # RiseFL 只验证当前位置的范数
        inner_products = self.client_compute_proof(location_vector)
        return self.server_verify_single(inner_products, norm_bound)
    
    # === 通信开销计算 ===
    def communication_cost_per_user(self):
        """
        RiseFL 的通信开销：
        - 服务器 → 客户端: m 个 D 维随机向量 = m·D·4 bytes
        - 客户端 → 服务器: m 个内积 = m·4 bytes
        总计: O(m·D) bytes
        """
        server_to_client = self.m * self.domain_size * 4  # float32
        client_to_server = self.m * 4
        return {
            "server_to_client_bytes": server_to_client,
            "client_to_server_bytes": client_to_server,
            "total_bytes": server_to_client + client_to_server
        }


class RiseFLExperimentRunner:
    """在 TSIP 实验框架下运行 RiseFL baseline"""
    
    def __init__(self, domain_size=10000, num_clients=200, 
                 malicious_rate=0.1, rounds=10):
        self.risefl = RiseFLBaseline(domain_size=domain_size)
        self.num_clients = num_clients
        self.malicious_rate = malicious_rate
        self.rounds = rounds
    
    def generate_attack_trajectories(self, attack_type="teleport"):
        """
        生成与 TSIP 实验相同的攻击场景
        
        attack_type: "teleport" | "identity_swap" | "gradual_drift"
        """
        # ... 使用与 TSIP 实验相同的轨迹生成逻辑
        pass
    
    def run_experiment(self, trajectories, attack_labels):
        """
        运行对比实验
        
        Returns:
            {
                "malicious_reject_rate": float,  # TPR
                "false_reject_rate": float,       # FPR
                "avg_valid_clients": float,
                "communication_per_user_bytes": int
            }
        """
        results_per_round = []
        
        for round_id in range(self.rounds):
            self.risefl.server_generate_challenge()
            
            accepted = 0
            rejected = 0
            malicious_caught = 0
            malicious_total = 0
            false_reject = 0
            honest_total = 0
            
            for user_id, traj in enumerate(trajectories):
                is_malicious = attack_labels[user_id]
                loc_vector = self._to_location_vector(traj[round_id])
                
                verified = self.risefl.verify_submission(
                    user_id, loc_vector
                )
                
                if is_malicious:
                    malicious_total += 1
                    if not verified:
                        malicious_caught += 1
                else:
                    honest_total += 1
                    if not verified:
                        false_reject += 1
                
                if verified:
                    accepted += 1
                else:
                    rejected += 1
            
            results_per_round.append({
                "round": round_id,
                "valid_clients": accepted,
                "rejected": rejected,
                "malicious_reject_rate": (
                    malicious_caught / malicious_total 
                    if malicious_total > 0 else 0
                ),
                "false_reject_rate": (
                    false_reject / honest_total 
                    if honest_total > 0 else 0
                )
            })
        
        return self._aggregate_results(results_per_round)
```

**实验对比重点**：

```
RiseFL 对比实验的核心发现应该是：
1. RiseFL 对瞬移攻击的 TPR ≈ 0（因为每个位置单独看都合法）
2. RiseFL 对身份交换攻击的 TPR = 0（完全无法检测）
3. RiseFL 的通信开销是 TSIP 的 ~40000 倍（m·D vs ~1KB）
4. RiseFL 的 FPR 可以做到很低（因为只检查范数）

这个对比直接证明了"时序完整性"的核心贡献价值。
```

### 3.2 Nebula 实现

**Nebula 的核心思想**：纯 DP 聚合，无任何完整性验证。使用稀疏向量技术（SVT）+ 拉普拉斯噪声生成隐私保护的直方图。

```python
# baselines/nebula_baseline.py

import numpy as np

class NebulaBaseline:
    """
    Nebula-style pure DP aggregation without integrity verification.
    
    核心区别：不做任何证明验证，所有提交直接进入聚合。
    攻击者可以提交任意虚假数据。
    """
    
    def __init__(self, domain_size=10000, epsilon=1.0, delta=1e-8):
        self.domain_size = domain_size
        self.epsilon = epsilon
        self.delta = delta
        
        # 拆分 epsilon 预算
        self.eps_svt = 0.3 * epsilon  # SVT 阈值检测
        self.eps_value = 0.7 * epsilon  # 值扰动
    
    def aggregate_no_verification(self, all_user_vectors):
        """
        无验证的聚合：所有提交直接加总
        
        这意味着恶意用户的虚假数据会直接污染结果。
        
        Args:
            all_user_vectors: list of sparse vectors [{cell: count}]
        
        Returns:
            histogram: 域大小 D 的直方图
        """
        histogram = np.zeros(self.domain_size)
        for user_vec in all_user_vectors:
            for cell, count in user_vec.items():
                histogram[cell] += count
        return histogram
    
    def apply_svt(self, histogram, threshold):
        """稀疏向量技术：识别显著的网格"""
        noisy_threshold = threshold + np.random.laplace(
            0, 2.0 / self.eps_svt
        )
        
        significant_cells = []
        for cell_id in range(len(histogram)):
            noisy_count = histogram[cell_id] + np.random.laplace(
                0, 4.0 / self.eps_svt
            )
            if noisy_count >= noisy_threshold:
                significant_cells.append(cell_id)
        
        return significant_cells
    
    def apply_value_noise(self, histogram, significant_cells, 
                          sensitivity):
        """对显著网格添加值噪声"""
        result = {}
        for cell_id in significant_cells:
            noisy_value = histogram[cell_id] + np.random.laplace(
                0, sensitivity / self.eps_value
            )
            result[cell_id] = max(0, noisy_value)
        return result
    
    def run_pipeline(self, all_user_vectors, threshold=5, 
                     sensitivity=50):
        """完整的 Nebula 风格 pipeline"""
        # 1. 无验证聚合
        histogram = self.aggregate_no_verification(all_user_vectors)
        
        # 2. SVT 识别显著网格
        significant = self.apply_svt(histogram, threshold)
        
        # 3. 值噪声
        dp_result = self.apply_value_noise(
            histogram, significant, sensitivity
        )
        
        return dp_result, histogram  # 返回 DP 结果和真实直方图
```

**Nebula 对比实验的核心发现**：

```
1. Nebula 的 malicious_reject_rate = 0（无任何完整性验证）
2. Nebula 的 false_reject_rate = 0（不拒绝任何人）
3. 在有攻击者的情况下，Nebula 的热力图质量严重退化
   （这是最重要的对比结果 — 证明完整性验证的必要性）
4. 在无攻击者的情况下，Nebula 的 utility 可能略好于 TSIP
   （因为 TSIP 的误拒降低了有效样本数）
```

### 3.3 Pure LDP (OUE) 实现

```python
# baselines/ldp_baseline.py

import numpy as np

class OptimizedUnaryEncoding:
    """
    Optimized Unary Encoding (OUE) for Local DP.
    
    每个用户在本地对位置向量加噪后发送给服务器。
    不需要可信服务器，但 utility 远低于中心化 DP。
    
    参考: [Wang et al., USENIX Security 2017]
    """
    
    def __init__(self, domain_size, epsilon):
        self.domain_size = domain_size
        self.epsilon = epsilon
        self.p = 0.5  # P[报告 1 | 真值 = 1]
        self.q = 1.0 / (np.exp(epsilon) + 1)  # P[报告 1 | 真值 = 0]
    
    def client_encode(self, true_cell):
        """
        客户端本地编码
        
        Args:
            true_cell: 用户真实所在的网格 ID
        
        Returns:
            noisy_vector: 经过随机化的二进制向量
        """
        noisy_vector = np.zeros(self.domain_size)
        for i in range(self.domain_size):
            if i == true_cell:
                noisy_vector[i] = 1 if np.random.random() < self.p else 0
            else:
                noisy_vector[i] = 1 if np.random.random() < self.q else 0
        return noisy_vector
    
    def server_aggregate(self, all_noisy_vectors):
        """
        服务器聚合并去偏
        """
        n = len(all_noisy_vectors)
        sum_vector = np.sum(all_noisy_vectors, axis=0)
        
        # 去偏估计
        estimated = (sum_vector - n * self.q) / (self.p - self.q)
        estimated = np.maximum(estimated, 0)
        
        return estimated
    
    def communication_cost_per_user(self):
        """OUE 通信开销: D bits（远高于 TSIP 的 ~1KB）"""
        return self.domain_size / 8  # bytes
```

### 3.4 No-Integrity Baseline

这个你已经有了（No-ZK），但需要标准化命名和对比方式：

```
No-Integrity Baseline ≡ 你的 Nebula 实现
  - 关闭 TSIP + zk_step
  - 保留 secret sharing + DP 输出
  - 本质上等同于 Nebula 的验证层

论文中的呈现方式：
  "We compare against a No-Integrity baseline that uses the same
   secret sharing and DP mechanisms as TSIP but removes all
   verification (TSIP proofs, zk_step proofs, and commitment
   chain checks). This isolates the contribution of integrity
   verification."
```

### 3.5 Commitment-Only Baseline（无 ZK）

**这个 baseline 对于消融实验至关重要**：

```python
# baselines/commitment_only.py

class CommitmentOnlyBaseline:
    """
    只使用承诺链绑定身份，但不用 ZK 证明距离约束。
    
    Shuffler 必须解密位置来验证距离约束（破坏隐私性）。
    
    用于量化 "零知识性" 的额外开销。
    """
    
    def verify_submission(self, user_id, curr_loc, curr_commitment,
                          prev_commitment_stored):
        """
        验证提交（需要明文位置）
        
        ⚠️ 隐私问题：Shuffler 看到了明文 curr_loc！
        """
        # 1. 验证承诺
        computed = poseidon_hash(curr_loc.x, curr_loc.y)
        if computed != curr_commitment:
            return False, "commitment_mismatch"
        
        # 2. 查找上次的明文位置（Shuffler 必须存储）
        prev_loc = self.stored_locations.get(user_id)
        if prev_loc is None:
            # 首次提交，接受
            self.stored_locations[user_id] = curr_loc
            return True, "enrolled"
        
        # 3. 明文距离检查（无 ZK）
        dx = curr_loc.x - prev_loc.x
        dy = curr_loc.y - prev_loc.y
        dist_sq = dx*dx + dy*dy
        max_dist_sq = (self.v_max * self.time_window) ** 2
        
        if dist_sq > max_dist_sq:
            return False, "distance_violation"
        
        # 4. 更新存储
        self.stored_locations[user_id] = curr_loc
        return True, "accepted"
```

**Commitment-Only 对比的意义**：

```
1. 安全性: 与 TSIP 相同（同样检测瞬移攻击）
2. 隐私性: 远差于 TSIP（Shuffler 看到明文位置）
3. 效率: 远快于 TSIP（无 ZK 证明开销）
4. 通信: 更小（无 ZK 证明传输）

论文中的论证:
"The Commitment-Only baseline achieves the same integrity
guarantees as TSIP but requires the Shuffler to see plaintext
locations. This demonstrates that TSIP's ZK proof overhead
(~1s prove, ~1s verify) is the cost of achieving integrity
verification WITHOUT sacrificing location privacy."
```

---

## 4. 攻击类型扩展

### 4.1 A1: 瞬移攻击（改进版）

你已经做了基础瞬移实验（200m/1000m/50000m），但需要更细粒度的分析：

```python
# experiments/attacks/teleport_sweep.py

def run_teleport_sweep():
    """
    细粒度瞬移攻击距离扫描
    
    关键创新：测试恰好超过阈值的边界情况
    """
    v_max = 110  # m/s
    time_window = 60  # s
    max_dist = v_max * time_window  # = 6600 m
    
    # 关键距离点
    jump_distances = [
        max_dist * 0.5,    # 3300m  — 合法，应该通过
        max_dist * 0.9,    # 5940m  — 合法，接近边界
        max_dist * 0.99,   # 6534m  — 合法，极近边界
        max_dist * 1.0,    # 6600m  — 恰好等于阈值
        max_dist * 1.01,   # 6666m  — 刚超过阈值
        max_dist * 1.1,    # 7260m  — 略超阈值
        max_dist * 1.5,    # 9900m  — 明显超过
        max_dist * 2.0,    # 13200m — 大幅超过
        max_dist * 5.0,    # 33000m — 极端超过
        max_dist * 50.0,   # 330km  — 城际瞬移
    ]
    
    # 对每个距离运行 10 轮实验
    for dist in jump_distances:
        config = {
            "TELEPORT_JUMP_M": dist,
            "CLIENT_TOTAL": 50,
            "MALICIOUS_RATE": 0.1,
            "ROUNDS": 10,
        }
        # 运行实验，记录 malicious_reject_rate
        results = run_tsip_experiment(config)
        
        # 预期结果：
        # dist < max_dist: malicious_reject_rate ≈ 0（合法移动）
        # dist ≥ max_dist: malicious_reject_rate = 1.0（被拦截）
        # 关键观察：边界处的行为（dist ≈ max_dist）
```

**论文中的呈现**：

```
一张折线图：
X 轴: jump distance / max_allowed_distance (ratio)
Y 轴: malicious_reject_rate (%)
标注 ratio = 1.0 处的临界点

预期结果: 在 ratio = 1.0 处有一个陡峭的 step function
          ratio < 1.0 → 0%, ratio > 1.0 → 100%

配合表格给出每个 ratio 的具体数值。
```

### 4.2 A2: 身份交换攻击

**这是 TSIP 最重要的新贡献之一，必须有实验验证。**

```python
# experiments/attacks/identity_swap.py

def generate_identity_swap_attack(num_pairs=5, total_users=50):
    """
    身份交换攻击实现
    
    攻击模式：
    - 选择 num_pairs 对用户（A_i, B_i）
    - 前 warm-up 轮正常提交，建立承诺链
    - 从第 R_swap 轮开始，A_i 使用 B_i 的 user_id 提交，反之亦然
    
    攻击者的策略：
    - A 知道自己的位置历史和 B 的 user_id
    - A 不知道 B 的实际位置（只有 B 的 H_prev）
    - A 必须为 B 的 H_prev 构造一个合法的 TSIP 证明
    
    预期结果：
    - 由于 A 不知道 B 的明文坐标，无法生成有效证明
    - TSIP 应该 100% 拦截这种攻击
    
    实现方式：
    - 方案1（完整实现）：修改 client_sim，让恶意客户端在
      第 R_swap 轮后使用另一个客户端的 user_id
    - 方案2（简化实现）：恶意客户端在 warm-up 后提交一个
      伪造的 prev_loc_commitment（不匹配自己的真实历史）
    """
    
    # 配置恶意行为
    attack_config = {
        "ATTACK_TYPE": "identity_swap",
        "SWAP_PAIRS": num_pairs,
        "SWAP_START_ROUND": 2,  # 从第 2 轮开始交换
        "CLIENT_TOTAL": total_users,
        "MALICIOUS_RATE": num_pairs * 2 / total_users,
    }
    
    return attack_config


def implement_swap_in_client_sim():
    """
    在 client_sim 中实现身份交换逻辑
    
    修改点：
    1. 配对的恶意客户端交换 user_id
    2. 客户端尝试用对方的 H_prev 生成证明
    3. 由于不知道对方的 (x, y)，只能随机猜测
    """
    # 伪代码
    """
    if is_swap_attack and round >= swap_start_round:
        # 获取 partner 的 user_id
        my_original_id = self.user_id
        self.user_id = partner.user_id
        
        # 尝试生成证明
        # 问题：我不知道 partner 的上一个位置
        # 策略1：随机猜测 partner 的位置
        guessed_prev_loc = random_location()
        # 但 Poseidon(guessed_prev_loc) ≠ partner 的 H_prev
        # → 电路约束不满足 → fullprove 失败
        # → proof = None → shuffler 拒绝
        
        # 策略2：直接提交 proof=None
        # → shuffler 必然拒绝（missing proof）
    """
```

**简化实现方案（推荐，更容易集成到现有框架）**：

```python
# 不需要真正交换 user_id
# 只需要让恶意客户端在提交时使用一个
# 与自己实际轨迹不匹配的 prev_loc_commitment

# 在 client_sim 中添加攻击模式：
ATTACK_TYPE = os.getenv("ATTACK_TYPE", "teleport")

if ATTACK_TYPE == "identity_swap":
    # 恶意客户端提交时，prev_loc 使用一个随机值
    # 模拟"我在用别人的承诺链"
    fake_prev_x = random.randint(0, 9999)
    fake_prev_y = random.randint(0, 9999)
    # 用 fake prev 生成证明
    # Poseidon(fake_prev_x, fake_prev_y) ≠ stored H_prev
    # → 电路约束 hash_prev 不满足
    # → proof 无效
    # → shuffler 拒绝
```

### 4.3 A3: 渐进偏移攻击

**这是一种比瞬移更狡猾的攻击，审稿人很可能会问。**

```python
# experiments/attacks/gradual_drift.py

def generate_gradual_drift_attack():
    """
    渐进偏移攻击
    
    攻击模式：
    - 恶意客户端每步移动 EXACTLY v_max · Δt（最大允许距离）
    - 但移动方向始终朝向目标位置
    - 经过若干步后，累积偏移远超单步阈值
    
    关键问题：TSIP 只检查相邻步的距离，不检查累积偏移。
    这是否构成安全威胁？
    
    分析：
    - 如果攻击者确实在物理上以 v_max 的速度持续移动，
      那么这是一条合法轨迹（例如高速驾车）
    - TSIP 的设计目标是防止"物理上不可能"的轨迹，
      而不是防止所有不诚实行为
    - 因此，这不是 TSIP 的安全漏洞，而是其设计范围
    
    但仍需在论文中讨论：
    "TSIP ensures each step is physically plausible. It does not
    prevent an attacker from taking a long but physically possible
    journey to a distant target. This is by design: the v_max
    parameter should be set to the maximum realistic velocity
    (e.g., 360 km/h for air travel), making multi-step drift
    attacks impractical in short time frames."
    """
    
    # 实验：验证渐进偏移攻击中每步都通过 TSIP
    v_max = 110  # m/s
    time_window = 60  # s
    max_step = v_max * time_window  # 6600 m
    
    # 攻击者从 (0,0) 出发，每步走最大距离
    # 10 步后到达 66km 外
    trajectory = [(0, 0)]
    target = (66000, 0)  # 66km 外的目标
    
    for step in range(10):
        curr = trajectory[-1]
        direction = np.arctan2(
            target[1] - curr[1], target[0] - curr[0]
        )
        next_x = curr[0] + max_step * 0.99 * np.cos(direction)
        next_y = curr[1] + max_step * 0.99 * np.sin(direction)
        trajectory.append((next_x, next_y))
    
    # 验证：每步都应该通过 TSIP
    # 因为每步距离 < max_step
    
    # 论文结论：这是 intended behavior, not a vulnerability
```

**论文中的呈现**：

```
在 Discussion / Limitations 章节中讨论：

"Gradual drift attacks: An attacker could construct a trajectory
where each step is just below the v_max · Δt threshold, allowing
them to gradually drift to a distant location over multiple rounds.
We argue this is not a vulnerability but a feature of the design:
TSIP enforces per-step physical plausibility, not global trajectory
constraints. Setting v_max appropriately (e.g., to the maximum
speed of the fastest transportation mode in the deployment area)
mitigates this concern. For urban heatmap applications where the
time window is 60 seconds and v_max = 110 m/s (400 km/h), an
attacker would need over 15 consecutive rounds (15 minutes) to
drift 100 km — a physically plausible journey by high-speed rail."
```

### 4.4 A4: Sybil 协调注入

```python
# experiments/attacks/sybil_coordinated.py

def generate_sybil_attack(num_sybils=20, total_users=200,
                          target_cell=5000):
    """
    Sybil 协调注入攻击
    
    攻击模式：
    - 攻击者创建 num_sybils 个虚假账户
    - 所有虚假账户在 enrollment 阶段分散注册
    - 从第 2 轮开始，所有虚假账户"瞬移"到 target_cell
    - 目的：虚增 target_cell 的热度
    
    与单用户瞬移的区别：
    - 更多的恶意用户同时行动
    - 对聚合结果的影响更大
    - 但 TSIP 应该能独立拦截每一个
    """
    attack_config = {
        "ATTACK_TYPE": "sybil_coordinated",
        "SYBIL_COUNT": num_sybils,
        "TARGET_CELL": target_cell,
        "CLIENT_TOTAL": total_users,
        # 所有 sybil 用户的 TELEPORT 目标都是 target_cell
    }
    
    # 关键实验指标（除了 malicious_reject_rate）：
    # 1. target_cell 在有 TSIP 保护 vs 无保护时的计数差异
    # 2. 热力图被污染的程度（见 Utility 实验）
    
    return attack_config
```

### 4.5 A5: 重放攻击

```python
# experiments/attacks/replay.py

def generate_replay_attack():
    """
    重放攻击
    
    攻击模式：
    - 恶意客户端在第 R 轮成功提交
    - 在第 R+1 轮，重新发送第 R 轮的 (proof, commitment)
    
    预期结果：
    - shuffler 检查 prev_commitment 是否匹配存储的最新承诺
    - 第 R+1 轮的 prev_commitment 应该是第 R 轮的 curr_commitment
    - 但重放的 proof 的 prev_commitment 是第 R-1 轮的承诺
    - → commitment_mismatch → 拒绝
    """
    # 实现：修改 client_sim，让恶意客户端缓存上一轮的提交并重发
```

---

## 5. Utility 实验设计

### 5.1 热力图质量指标

**这是当前实验最大的缺口之一。**

```python
# experiments/utility/heatmap_quality.py

import numpy as np
from scipy.stats import wasserstein_distance
from collections import Counter

def compute_ground_truth_heatmap(trajectories, domain_size):
    """
    计算真实热力图（ground truth）
    
    使用所有诚实用户的真实位置，不加噪声
    """
    histogram = np.zeros(domain_size)
    for traj in trajectories:
        for loc in traj:
            cell_id = xy_to_cell(loc.x, loc.y)
            histogram[cell_id] += 1
    return histogram


def compute_dp_heatmap(dp_output):
    """从 TSIP/Nebula 的 DP 输出构造热力图"""
    histogram = np.zeros(domain_size)
    for cell_id, count in dp_output.items():
        histogram[cell_id] = count
    return histogram


class HeatmapQualityMetrics:
    """热力图质量评估指标"""
    
    @staticmethod
    def jaccard_top_k(predicted, ground_truth, k=100):
        """
        Top-K Jaccard 指数
        
        衡量预测的热点区域与真实热点的重叠度
        这是位置数据聚合中最重要的指标
        """
        top_k_pred = set(np.argsort(predicted)[-k:])
        top_k_true = set(np.argsort(ground_truth)[-k:])
        
        intersection = len(top_k_pred & top_k_true)
        union = len(top_k_pred | top_k_true)
        
        return intersection / union if union > 0 else 0
    
    @staticmethod
    def rmse(predicted, ground_truth):
        """均方根误差"""
        return np.sqrt(np.mean((predicted - ground_truth) ** 2))
    
    @staticmethod
    def relative_error(predicted, ground_truth):
        """相对误差"""
        total = np.sum(np.abs(ground_truth))
        if total == 0:
            return 0
        return np.sum(np.abs(predicted - ground_truth)) / total
    
    @staticmethod
    def emd(predicted, ground_truth):
        """
        Earth Mover's Distance
        衡量两个分布之间的"搬运距离"
        """
        # 归一化为概率分布
        p = predicted / (np.sum(predicted) + 1e-10)
        q = ground_truth / (np.sum(ground_truth) + 1e-10)
        return wasserstein_distance(p, q)
    
    @staticmethod
    def kendall_tau_top_k(predicted, ground_truth, k=100):
        """
        Top-K Kendall Tau 排名相关性
        衡量排名保持能力
        """
        from scipy.stats import kendalltau
        
        top_k_true_idx = np.argsort(ground_truth)[-k:]
        
        true_ranks = np.argsort(ground_truth[top_k_true_idx])
        pred_ranks = np.argsort(predicted[top_k_true_idx])
        
        tau, _ = kendalltau(true_ranks, pred_ranks)
        return tau


def run_utility_comparison():
    """
    完整的 utility 对比实验
    
    在以下配置下分别运行并计算质量指标：
    1. Ground truth (无隐私，无攻击)
    2. TSIP (有隐私，有攻击者)
    3. Nebula/No-ZK (有隐私，有攻击者，无完整性保护)
    4. Pure LDP (本地 DP，有攻击者)
    """
    
    scenarios = {
        "no_attack": {"malicious_rate": 0.0},
        "10%_attack": {"malicious_rate": 0.1},
        "20%_attack": {"malicious_rate": 0.2},
        "30%_attack": {"malicious_rate": 0.3},
    }
    
    methods = ["TSIP", "Nebula", "RiseFL", "LDP"]
    
    results = {}
    for scenario_name, scenario_config in scenarios.items():
        results[scenario_name] = {}
        
        for method in methods:
            # 运行实验
            dp_output = run_method(method, scenario_config)
            ground_truth = compute_ground_truth(scenario_config)
            
            # 计算指标
            metrics = HeatmapQualityMetrics()
            results[scenario_name][method] = {
                "jaccard_100": metrics.jaccard_top_k(
                    dp_output, ground_truth, k=100
                ),
                "jaccard_50": metrics.jaccard_top_k(
                    dp_output, ground_truth, k=50
                ),
                "rmse": metrics.rmse(dp_output, ground_truth),
                "relative_error": metrics.relative_error(
                    dp_output, ground_truth
                ),
            }
    
    return results

# 论文中的表格格式：
# 
# Table X: Heatmap Quality under Different Attack Rates
# 
# | Method  | Attack | Jaccard@100 | RMSE   | Rel.Error |
# |---------|--------|-------------|--------|-----------|
# | TSIP    | 0%     | 0.82        | 12.3   | 0.15      |
# | TSIP    | 10%    | 0.80        | 13.1   | 0.16      |
# | TSIP    | 20%    | 0.78        | 14.5   | 0.18      |
# | Nebula  | 0%     | 0.85        | 11.0   | 0.13      |
# | Nebula  | 10%    | 0.45        | 35.2   | 0.52      |  ← 关键！
# | Nebula  | 20%    | 0.22        | 58.7   | 0.78      |  ← 关键！
# | LDP     | 0%     | 0.35        | 45.0   | 0.60      |
# | LDP     | 10%    | 0.33        | 47.2   | 0.62      |
#
# 核心发现：
# - 无攻击时，Nebula 的 utility 略好于 TSIP
#   （因为 TSIP 有小概率误拒降低了样本数）
# - 有攻击时，Nebula 的 utility 急剧下降（被攻击污染）
# - TSIP 在有攻击时仍保持高 utility（攻击被拦截）
# - LDP 的 utility 始终很差（本地 DP 噪声太大）
```

### 5.2 Privacy-Utility Tradeoff

```python
# experiments/utility/privacy_utility_tradeoff.py

def run_privacy_utility_tradeoff():
    """
    隐私-效用权衡实验
    
    固定攻击率 = 10%，扫描不同的 ε 值
    """
    epsilon_values = [0.1, 0.2, 0.5, 0.8, 1.0, 2.0, 5.0, 10.0]
    
    results = {}
    for eps in epsilon_values:
        # 对每个 ε 值运行 TSIP
        config = {
            "EPSILON_TOTAL": eps,
            "EPSILON_SVT": 0.3 * eps,    # 按比例分配
            "EPSILON_VALUE": 0.7 * eps,
            "MALICIOUS_RATE": 0.1,
            "ROUNDS": 10,
        }
        
        dp_output = run_tsip(config)
        ground_truth = compute_ground_truth()
        
        results[eps] = {
            "jaccard_100": compute_jaccard(dp_output, ground_truth),
            "rmse": compute_rmse(dp_output, ground_truth),
            "malicious_reject_rate": get_reject_rate(),
        }
    
    # 论文图表：
    # X 轴: ε (log scale)
    # Y 轴: Jaccard@100
    # 多条线: TSIP, Nebula (无攻击), Nebula (有攻击)
    #
    # 关键发现：
    # - 在所有 ε 值下，TSIP (有攻击) 的 utility ≈ Nebula (无攻击)
    # - 而 Nebula (有攻击) 的 utility 在低 ε 时更差
```

### 5.3 攻击下的聚合质量退化

```python
# experiments/utility/attack_degradation.py

def run_attack_degradation():
    """
    核心实验：展示无完整性保护时聚合质量如何随攻击率退化
    
    这是论文最重要的实验之一。
    """
    attack_rates = [0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
    
    for rate in attack_rates:
        # TSIP
        tsip_result = run_tsip({"MALICIOUS_RATE": rate})
        tsip_quality = compute_quality(tsip_result)
        
        # No-ZK (Nebula-like)
        nozk_result = run_no_zk({"MALICIOUS_RATE": rate})
        nozk_quality = compute_quality(nozk_result)
    
    # 论文图表：
    # X 轴: Attack rate (%)
    # Y 轴: Jaccard@100
    # 两条线: TSIP (几乎水平) vs No-ZK (急剧下降)
    #
    # 这张图是论文的 "money figure"
    # 直观展示了完整性验证的价值
```

---

## 6. 消融实验设计

```python
# experiments/ablation/run_ablation.py

def run_ablation_study():
    """
    消融实验：逐一移除 TSIP 的组件，观察影响
    """
    
    configurations = {
        # 完整 TSIP
        "Full TSIP": {
            "TSIP_ENABLE": 1,
            "ZK_STEP_ENABLE": 1,
            "BLACKLIST_ENABLE": 1,
            "DP_ENABLE": 1,
        },
        
        # 移除 TSIP 证明（只保留 zk_step）
        "No TSIP proof": {
            "TSIP_ENABLE": 0,
            "ZK_STEP_ENABLE": 1,
            "BLACKLIST_ENABLE": 1,
            "DP_ENABLE": 1,
        },
        
        # 移除 zk_step（只保留 TSIP）
        "No zk_step": {
            "TSIP_ENABLE": 1,
            "ZK_STEP_ENABLE": 0,
            "BLACKLIST_ENABLE": 1,
            "DP_ENABLE": 1,
        },
        
        # 移除黑名单
        "No blacklist": {
            "TSIP_ENABLE": 1,
            "ZK_STEP_ENABLE": 1,
            "BLACKLIST_ENABLE": 0,
            "DP_ENABLE": 1,
        },
        
        # 移除 DP
        "No DP": {
            "TSIP_ENABLE": 1,
            "ZK_STEP_ENABLE": 1,
            "BLACKLIST_ENABLE": 1,
            "DP_ENABLE": 0,
        },
        
        # 全部移除（No-ZK baseline）
        "No defense": {
            "TSIP_ENABLE": 0,
            "ZK_STEP_ENABLE": 0,
            "BLACKLIST_ENABLE": 0,
            "DP_ENABLE": 1,  # DP 还是保留的
        },
    }
    
    # 对每个配置运行 10 轮，malicious_rate=0.1
    # 记录：malicious_reject_rate, false_reject_rate,
    #        Jaccard@100, prove_time, verify_time
    
    # 论文表格：
    #
    # Table Y: Ablation Study
    #
    # | Configuration  | Mal.Rej | FPR   | Jaccard | Prove(s) |
    # |----------------|---------|-------|---------|----------|
    # | Full TSIP      | 1.000   | 0.002 | 0.80    | 0.41     |
    # | No TSIP proof  | 0.000   | 0.000 | 0.45    | 0.31     |
    # | No zk_step     | 1.000   | 0.001 | 0.79    | 0.35     |
    # | No blacklist   | 1.000   | 0.002 | 0.80    | 0.41     |
    # | No DP          | 1.000   | 0.002 | 0.95    | 0.41     |
    # | No defense     | 0.000   | 0.000 | 0.45    | 0.00     |
    #
    # 核心发现：
    # - TSIP proof 是检测能力的关键（移除后 TPR→0）
    # - zk_step 对检测率影响较小（TSIP 已覆盖大部分攻击）
    # - 黑名单主要影响持续攻击的场景
    # - DP 降低了 utility 但不影响安全性
```

---

## 7. 规模与性能实验

```python
# experiments/scalability/performance_breakdown.py

def run_performance_breakdown():
    """
    性能细分实验
    
    分解每个组件的耗时，识别瓶颈
    """
    
    # 客户端性能分解
    client_breakdown = {
        "poseidon_commitment": [],  # Poseidon 哈希计算
        "zk_step_prove": [],        # zk_step 证明生成
        "tsip_prove": [],           # TSIP 主证明生成
        "encryption": [],           # 秘密分享加密
        "network_upload": [],       # 网络上传
    }
    
    # 服务器性能分解
    server_breakdown = {
        "tsip_verify": [],          # TSIP 证明验证
        "commitment_check": [],     # 承诺链检查
        "blacklist_check": [],      # 黑名单检查
        "forward_to_agg": [],       # 转发到聚合器
        "aggregation": [],          # 聚合计算
        "dp_noise": [],             # DP 噪声添加
    }
    
    # 扩展到更大规模
    scales = [100, 200, 500, 1000, 2000, 5000]
    
    for n in scales:
        # 运行实验并记录每个组件的耗时
        pass
    
    # 论文图表：
    # 1. 堆叠柱状图：客户端各组件耗时 vs 用户数
    # 2. 折线图：服务器总吞吐量 vs 用户数（应接近线性）
    # 3. 表格：各方法的通信开销对比
    #
    # | Method  | Per-user Upload | Per-user Download | Server/user |
    # |---------|----------------|-------------------|-------------|
    # | TSIP    | ~1 KB          | ~0               | ~1.0 s      |
    # | RiseFL  | ~40 MB         | ~40 MB           | ~0.05 s     |
    # | Nebula  | ~200 B         | ~0               | ~0.001 s    |
    # | LDP     | ~1.25 KB       | ~0               | ~0.001 s    |


def run_domain_size_experiment():
    """
    域大小扩展实验
    
    当前实验 DOMAIN_SIZE=10^4，设计目标 10^8
    需要验证域大小对性能的影响
    """
    domain_sizes = [1000, 10000, 100000, 1000000]
    
    # 关键观察：
    # - ZK 证明的大小和时间与域大小无关（只依赖约束数）
    # - 但聚合和 DP 的开销与域大小相关
    # - 稀疏化（Top-K）使客户端开销与域大小无关
    
    for d in domain_sizes:
        # 记录：prove_time, verify_time, aggregation_time, memory
        pass
    
    # 论文结论：
    # "TSIP's ZK proof overhead is independent of the domain size D,
    #  as the circuit only operates on individual coordinates.
    #  The aggregation and DP stages scale with the number of
    #  significant cells (determined by SVT), not D."
```

---

## 8. 论文结构与写作

### 推荐的论文结构

```
Title: TSIP: Privacy-Preserving Location Aggregation with
       Temporal-Spatial Integrity Proofs

Abstract (250 words)

1. Introduction (2 pages)
   - Urban heatmap aggregation motivation
   - Cross-window attack problem (THE key insight)
   - Limitations of existing approaches (RiseFL, Nebula)
   - Our contributions (3 bullets):
     (1) Formalize temporal-spatial integrity
     (2) Design TSIP protocol with ZK proofs
     (3) Comprehensive evaluation on real datasets

2. Problem Definition (1 page)
   - System model
   - Threat model (formal, game-based)
   - Security goals (Definitions 1-3)

3. TSIP Protocol (3 pages)
   - 3.1 Overview (high-level flow diagram)
   - 3.2 Commitment chain
   - 3.3 ZK circuit design
   - 3.4 Committee verification
   - 3.5 DP aggregation

4. Security Analysis (2-3 pages)
   - 4.1 Theorem 1: Soundness (with reduction proof)
   - 4.2 Theorem 2: Privacy (DP composition)
   - 4.3 Theorem 3: Zero-Knowledge
   - 4.4 Attack resistance analysis (corollaries)

5. Implementation (1 page)
   - System architecture
   - Circuit stats (674 constraints, Poseidon2)
   - Deployment (Docker, rapidsnark)

6. Evaluation (3-4 pages)
   - 6.1 Setup (datasets, baselines, metrics, hardware)
   - 6.2 Attack defense (Table + Figure: TPR comparison)
   - 6.3 Heatmap quality (Table: Jaccard, RMSE under attack)
   - 6.4 Privacy-utility tradeoff (Figure: ε vs Jaccard)
   - 6.5 Scalability (Figure: users vs throughput)
   - 6.6 Ablation study (Table: component contributions)
   - 6.7 Overhead analysis (Table: prove/verify/comm costs)

7. Discussion (0.5 page)
   - Limitations (enrollment anchor, trusted setup)
   - Extensions (multi-modal, dynamic ε)

8. Related Work (1 page)
   - DP for location (Nebula, GeoMask, PrivTrace)
   - Integrity verification (RiseFL, VerifyFL)
   - ZK for privacy (applications in FL, blockchain)

9. Conclusion (0.3 page)

References
Appendix: Full proofs, additional experiments
```

### 写作要点

**Introduction 的核心叙事线**（第一段就要抓住审稿人）：

```
段1: 城市热力图聚合是一个重要的应用（举 2-3 个具体场景）

段2: 现有方案分为两类——
     (a) DP 方案（Nebula）保护隐私但无法防御恶意注入
     (b) 完整性方案（RiseFL）检测异常但无时序验证

段3: THE KEY INSIGHT: 跨时间窗口攻击
     "Consider two users Alice (Tokyo) and Bob (Osaka) who collude
      to swap identities at time t=1..."
     用一个具体的攻击场景说明为什么现有方案都失败

段4: 我们的方案 TSIP: 用 ZK 证明验证时空连续性，
     同时保持位置隐私

段5: 贡献列表 (3 bullets)

段6: 实验结果 headline numbers:
     "TSIP detects 100% of cross-window attacks with only 0.17%
      false positive rate, while maintaining heatmap quality
      (Jaccard@100 = 0.80) even under 10% malicious users."
```

**Evaluation 的写作原则**：

```
1. 每个实验先说 "Research Question"，再说 "Setup"，再说 "Results"
   RQ1: Does TSIP effectively detect cross-window attacks?
   RQ2: How does TSIP affect heatmap quality?
   RQ3: How does TSIP scale with the number of users?
   RQ4: What is the contribution of each component?
   RQ5: What is the computational and communication overhead?

2. 每个 figure/table 都有明确的 takeaway 写在 caption 或文中：
   "Figure X shows that TSIP maintains Jaccard@100 above 0.78
    regardless of attack rate, while the No-Integrity baseline
    drops below 0.45 at 10% attack rate."

3. 对比要公平：
   - 所有方法使用相同数据集
   - 所有方法使用相同 ε 值
   - 报告置信区间（多轮实验的 std）
```

---

## 9. 时间线规划

假设从现在开始全力投入：

```
Week 1-2: Baseline 实现
  □ 实现 RiseFL 验证逻辑（core verify + 在 TSIP 框架中集成）
  □ 实现 Nebula baseline（≈ No-ZK + 标准 DP）
  □ 实现 Pure LDP (OUE)
  □ 实现 Commitment-Only baseline
  □ 验证所有 baseline 在无攻击场景下的正确性

Week 3-4: 攻击扩展
  □ 实现 A2 身份交换攻击
  □ 实现 A3 渐进偏移攻击
  □ 实现 A4 Sybil 协调注入
  □ 实现 A1 改进版（细粒度距离扫描）
  □ 在所有 baseline 上运行所有攻击

Week 5-6: Utility 实验
  □ 实现 ground truth 热力图计算
  □ 实现 Jaccard, RMSE, Relative Error 指标
  □ 运行 utility comparison（Table X）
  □ 运行 privacy-utility tradeoff（Figure Y）
  □ 运行 attack degradation（Figure Z — money figure）

Week 7: 消融 + 规模实验
  □ 运行 ablation study（6 种配置 × 10 轮）
  □ 运行 scale experiment（100-5000 用户）
  □ 运行 domain size experiment（如可行）
  □ 性能分解（prove/verify/comm breakdown）

Week 8-9: 安全证明重写
  □ 重写 Theorem 1（game-based + reduction）
  □ 修复 Theorem 2（删除 Lemma 1，采用方案 B）
  □ 清理 Theorem 3（引用 Groth16 ZK）
  □ 修复或删除 Theorem 4
  □ 加入 enrollment boundary discussion

Week 10-12: 论文写作
  □ Introduction + Problem Definition
  □ Protocol Design (重写为论文格式，删除工程日志)
  □ Security Analysis
  □ Implementation
  □ Evaluation (整合所有实验结果)
  □ Discussion + Related Work + Conclusion

Week 13-14: 打磨与审阅
  □ 内部审阅（找同学/导师看）
  □ 绘图美化（统一配色、字体）
  □ 代码开源准备
  □ 投稿前 checklist
```

---

## 附录：实验结果呈现模板

### Figure 1: Attack Detection Comparison (Money Figure)

```
X 轴: Attack Rate (0%, 5%, 10%, 15%, 20%, 25%, 30%)
Y 轴: Heatmap Quality (Jaccard@100)

四条线：
- TSIP (蓝色实线, ★标记) — 几乎水平在 ~0.80
- Nebula (红色虚线, ○标记) — 从 ~0.85 急剧下降到 ~0.20
- RiseFL (绿色点线, △标记) — 下降但略好于 Nebula
- LDP (灰色点线, □标记) — 始终低在 ~0.35

Caption: "TSIP maintains high heatmap quality regardless of
attack rate by detecting and filtering malicious submissions.
Without integrity verification (Nebula), even 10% malicious
users can reduce Jaccard@100 by over 50%."
```

### Table 1: Attack Detection Rate Comparison

```
| Method     | Teleport | Id Swap | Sybil | Grad.Drift | FPR    |
|------------|----------|---------|-------|------------|--------|
| TSIP       | 100%     | 100%    | 100%  | 0%*        | 0.17%  |
| RiseFL     | 0%       | 0%      | 0%    | 0%         | 5.0%   |
| Nebula     | 0%       | 0%      | 0%    | 0%         | 0%     |
| Comm.Only  | 100%     | 100%    | 100%  | 0%*        | 0.17%  |

* Gradual drift within v_max·Δt is by design not flagged
  (physically plausible movement).
```

### Table 2: Communication and Computation Overhead

```
| Method    | Prove    | Verify   | Upload/user | Download/user |
|-----------|----------|----------|-------------|---------------|
| TSIP      | 0.41s    | 1.03s    | ~1 KB       | 0             |
| RiseFL    | 0.10s    | 0.05s    | ~40 MB      | ~40 MB        |
| Nebula    | N/A      | N/A      | ~200 B      | 0             |
| LDP       | N/A      | N/A      | ~1.25 KB    | 0             |
| Comm.Only | N/A      | 0.001s   | ~300 B      | 0             |

Note: TSIP prove time is for rapidsnark; snarkjs is ~1.39s.
Verify time is snarkjs (no native verifier currently).
```
