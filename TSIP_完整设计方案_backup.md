# TSIP完整设计方案 - Part 1: 概述与理论基础

## Temporal-Spatial Integrity Proof for Privacy-Preserving Location Aggregation

---

## 目录
- Part 1: 概述与理论基础 (本文档)
- Part 2: 协议设计与实现
- Part 3: 安全性证明
- Part 4: 实验评估与论文撰写

---

## 第一章: 问题定义与动机

### 1.1 背景：位置隐私保护的挑战

#### 应用场景
```
城市级位置数据聚合:
- 输入: N个用户在T个时间窗口的轨迹
- 输出: 城市热力图 (每个网格的访问次数)
- 要求: 
  1. 服务器无法推断个人位置 (隐私性)
  2. 在连续性作用域内高概率拒绝违规轨迹，并提高恶意污染成本 (完整性)
  3. 高效处理百万级网格 (可扩展性)
```

#### 现有方案的局限

**方案A: 纯差分隐私 (如Nebula)**
```
 优点: 强隐私保证
❌ 缺点: 无法防御恶意用户注入虚假数据
```

**方案B: 物理约束验证 (如RiseFL)**
```
协议流程:
1. 服务器生成随机向量 a ∈ R^d
2. 用户计算内积 z = ⟨trajectory, a⟩
3. 服务器验证 Σz² ≤ B² (卡方检验)

 优点: 能检测单个位置的物理合理性
❌ 关键缺陷: 无法验证时间序列的一致性!
```

---

### 1.2 核心问题：跨时间窗口攻击 (Cross-Window Attack)

#### 攻击场景1: 身份交换攻击

```
场景描述:
- 用户Alice在东京 (t=0时刻)
- 用户Bob在大阪 (t=0时刻)
- 两人串谋,在t=1时刻交换ID

攻击流程:
t=0:
  Alice提交: (东京, ID_Alice) 通过RiseFL验证
  Bob提交:   (大阪, ID_Bob) 通过RiseFL验证

t=1: (身份交换)
  Alice使用ID_Bob提交: (东京附近的位置)
  Bob使用ID_Alice提交:  (大阪附近的位置)
  
  每个位置单独看都合理   但Alice的"轨迹"从东京瞬移到大阪! ❌

结果:
- 热力图显示有人从东京快速移动到大阪
- 破坏数据质量,影响城市规划决策
```

#### 攻击场景2: Sybil + 瞬移攻击

```
攻击者策略:
1. 创建1000个虚假ID
2. 在t=0时,所有ID报告分散在城市各处 (通过RiseFL)
3. 在t=1时,所有ID突然"瞬移"到商场A
4. 商场A的热度虚高1000倍!

RiseFL的盲点:
- 只验证"单个时刻"的位置合理性
- 不关心"同一ID的历史轨迹"是否连续
```

#### 为什么现有方案失效?

**RiseFL的验证逻辑**:
```python
def risefl_verify(location, random_vector):
    """
    只关心当前这一个位置向量
    """
    inner_product = dot(location, random_vector)
    return inner_product² <= threshold  # 单点验证
```

**缺失的维度**: **时间维度的连续性**

```
需要验证的约束:
∀ 用户i, ∀ 时刻t:
  distance(location[i][t], location[i][t+1]) ≤ v_max * Δt

但如何在不泄露具体位置的前提下验证这个约束?
→ 这就是TSIP要解决的核心问题!
```

---

### 1.3 研究问题形式化

#### 定义1.1: 时空完整性 (Temporal-Spatial Integrity)

**非正式描述**:
> 一个位置聚合协议满足时空完整性,当且仅当:
> 在给定威胁模型与状态机规则下,恶意用户若提交违反速度/连续性约束的跨时间轨迹,
> 其通过验证概率可忽略 (即使每个时刻的位置单独看是合理的)。

**形式化定义**:

```latex
Definition 1.1 (Temporal-Spatial Integrity):
A location aggregation protocol Π satisfies (λ, ε)-temporal-spatial 
integrity if for any PPT adversary A controlling up to t users:

Pr[
  A submits trajectory {(x₀, t₀), (x₁, t₁), ..., (xₜ, tₜ)} 
  such that ∃i: ||xᵢ₊₁ - xᵢ|| > v_max·(tᵢ₊₁ - tᵢ) 
  AND A is not detected
] ≤ 2^(-λ) + ε

where:
- λ: security parameter (soundness)
- ε: negligible error probability
- v_max: maximum physically possible velocity

scope note:
- 该定义约束的是 trajectory continuity/plausibility,不是真实世界在场真实性(presence/truthfulness)。
- 作用域针对链深度 >= 1 且满足协议状态机约束的用户提交。
```

**关键要求**:
1. **Soundness (完备性)**: 违反约束的轨迹以高概率被拒绝
2. **Zero-Knowledge (零知识性)**: 验证过程不泄露位置信息
3. **Efficiency (高效性)**: 证明大小和验证时间与T(时间窗口数)对数相关

---

### 1.4 设计目标

#### 目标1: 安全性

| 属性 | 定义 | TSIP保证 |
|------|------|----------|
| **完整性** | 恶意轨迹被检测 | Pr[检测] ≥ 1-2^(-128) |
| **隐私性** | 服务器学不到位置 | ε-DP（当前主口径 ε=1.0） |
| **零知识性** | 验证不泄露轨迹细节 | 满足ZK定义 |

#### 目标2: 效率

| 指标 | RiseFL (baseline) | TSIP目标 |
|------|-------------------|---------|
| 证明大小 | O(m·d) = 10MB | 当前实测约 `0.70~0.81KB`（proof 文件） |
| 证明生成时间 | O(m·d) = 100ms | 当前实测约 `0.31~1.39s`（rapidsnark/snarkjs） |
| 验证时间 | O(m·d) = 50ms | 当前实测约 `1.03s`（snarkjs verify） |
| 通信量 (per user) | 10MB 级 | 当前实现约 `1KB` 级（含证明与提交元数据） |

#### 目标3: 实用性

- 支持T=288个时间窗口 (每5分钟一个,覆盖24小时)
- 支持d=10^6个网格 (城市级规模)
- 客户端开销（当前实测口径）: prove 为亚秒到秒级，后续需补移动端实测，不再使用 `<100ms` 口径

---

## 第二章: 技术准备

### 2.1 零知识证明基础

#### 什么是零知识证明?

**非正式定义**:
> Alice想向Bob证明"我知道某个秘密",但不想透露秘密本身。
> 零知识证明允许Alice生成一个"证明π",使得:
> 1. Bob验证π通过 → Alice确实知道秘密 (Soundness)
> 2. π本身不泄露任何关于秘密的信息 (Zero-Knowledge)

**经典例子: 阿里巴巴的洞穴**
```
场景: 有一个环形洞穴,中间有一道需要密码才能打开的门

Alice (Prover)        Bob (Verifier)
知道密码              不知道密码

证明协议:
1. Alice进入洞穴,随机选择左边或右边的路
2. Bob在洞穴外等待
3. Bob随机喊: "从左边出来" 或 "从右边出来"
4. 如果Alice真知道密码,她总能满足Bob的要求
   (因为她可以通过门从任意一边出来)
5. 重复100次,如果Alice每次都成功 → Bob确信Alice知道密码
6. 但Bob学不到密码本身!

数学特性:
- Completeness: 如果Alice知道密码,成功概率=100%
- Soundness: 如果Alice不知道密码,成功概率≤(1/2)^100 ≈ 0
- Zero-Knowledge: Bob只知道"Alice知道密码",不知道密码是什么
```

#### zk-SNARKs: 简洁的非交互式零知识证明

**SNARK = Succinct Non-interactive ARgument of Knowledge**

关键特性:
```
1. Succinct (简洁): 
   - 证明大小: O(1) (约200-500 bytes,与语句复杂度无关!)
   - 验证时间: O(1) (实现相关,通常毫秒级到秒级)

2. Non-interactive (非交互):
   - 不需要Prover和Verifier来回通信
   - Prover生成一次性证明π,Verifier直接验证

3. Zero-Knowledge:
   - π不泄露witness (秘密输入)

4. Argument (计算完备性):
   - 可以证明任意NP语句
   - 如: "我知道x使得SHA256(x) = y"
   - 如: "我知道Bitcoin私钥对应这个地址"
```

**工作原理 (高度简化)**:
```
Step 1: 电路化 (Arithmetization)
将要证明的语句转为算术电路 (加法和乘法门)

例: 证明"我知道x使得x² = 9"
电路: 
  输入: x (私密)
  输出: y (公开)
  约束: x * x = y, y = 9

Step 2: Setup (可信设置)
生成proving key (pk) 和 verification key (vk)
 需要可信第三方销毁setup过程的随机数

Step 3: Proving
Prover用pk和witness(私密输入)生成证明π

Step 4: Verification
Verifier用vk和公开输入验证π
```

**我们使用的方案: Groth16**
```
特性:
- 证明大小: 仅128 bytes (2个G₁元素 + 1个G₂元素)
- 验证时间: 实现相关（本项目当前 `snarkjs` 实测约 `1.03s`）
- 可信设置: 需要(但可用MPC生成,如Zcash的Powers of Tau)

缺点:
- 电路需要预先固定(不支持通用计算)
- 需要可信设置(虽有解决方案如Plonk,但效率稍低)

在TSIP中的应用:
- 电路: 距离验证 (固定)
- Setup: 一次性完成,所有用户复用
```

---

### 2.2 Groth16协议详解

#### 数学准备：椭圆曲线配对

**椭圆曲线群**:
```
选择曲线: BN254 (Barreto-Naehrig curve)
三个群:
- G₁: 椭圆曲线上的点群 (base field)
- G₂: twist curve上的点群
- Gₜ: target group (pairing的输出)

配对函数 e: G₁ × G₂ → Gₜ
性质: 
  e(aP, bQ) = e(P, Q)^(ab)  (双线性)
  e(P, Q) ≠ 1 (非退化)
```

**为什么需要配对?**
```
目的: 让Verifier能检查多项式关系

例: 证明"我知道a, b, c使得a·b = c"
Naive方案: 直接发送a,b,c → 泄露witness
zk-SNARK方案:
  Setup生成: g^α, g^β ∈ G₁
  Prover计算: A = g^a, B = g^b, C = g^c
  Verifier检查: e(A, B) = e(C, g)
  
  如果a·b=c,则: e(g^a, g^b) = e(g^(ab), g) = e(g^c, g) ✓
  但Verifier学不到a,b,c的具体值!
```

#### Groth16证明系统

**Setup阶段**:
```python
def setup(circuit):
    """
    输入: 算术电路C (包含n个变量, m个约束)
    输出: (proving_key, verification_key)
    """
    # 1. 采样随机数 (toxic waste,必须销毁!)
    α, β, γ, δ, τ = random.sample(5)
    
    # 2. 构造QAP (Quadratic Arithmetic Program)
    #    将电路转为多项式
    L(x) = Σ aᵢ·xⁱ  # left polynomial
    R(x) = Σ bᵢ·xⁱ  # right polynomial
    O(x) = Σ cᵢ·xⁱ  # output polynomial
    Z(x) = (x-1)(x-2)...(x-m)  # vanishing polynomial
    
    # 3. 生成proving key
    pk = {
        [τⁱ·g₁]ᵢ₌₀ⁿ,        # powers of τ
        [α, β, δ, {Lᵢ(τ), Rᵢ(τ), Oᵢ(τ)}]·g₁
    }
    
    # 4. 生成verification key
    vk = {
        α·g₁, β·g₂, γ·g₂, δ·g₂,
        [Lᵢ(τ)·g₁]ᵢ∈public  # 仅公开输入相关
    }
    
    # 5. 销毁 α, β, γ, δ, τ !!
    return pk, vk
```

**Proving阶段**:
```python
def prove(pk, circuit, witness, public_input):
    """
    输入: 
      - pk: proving key
      - witness: 私密输入 (如: 两个位置坐标)
      - public_input: 公开输入 (如: 最大速度v_max)
    输出:
      - proof: (A, B, C) ∈ G₁ × G₂ × G₁
    """
    # 1. 计算多项式
    #    根据witness给每个变量赋值
    a = assign_values(circuit, witness, public_input)
    
    # 2. 构造多项式H(x) = (L(x)·R(x) - O(x)) / Z(x)
    #    关键: 只有满足电路约束时, Z(x)才能整除
    h_coeffs = compute_h_polynomial(a, circuit)
    
    # 3. 计算证明元素
    r, s = random.sample(2)  # 随机盲化因子
    
    A = α·g₁ + Σ aᵢ·Lᵢ(τ)·g₁ + r·δ·g₁
    B = β·g₂ + Σ aᵢ·Rᵢ(τ)·g₂ + s·δ·g₂
    C = Σ aᵢ·Oᵢ(τ)·g₁ + H(τ)·g₁ + s·A + r·B - r·s·δ·g₁
    
    return (A, B, C)
```

**Verification阶段**:
```python
def verify(vk, public_input, proof):
    """
    输入:
      - vk: verification key
      - public_input: 公开输入
      - proof: (A, B, C)
    输出:
      - True/False
    """
    A, B, C = proof
    
    # 构造公开输入部分
    L_pub = Σ public_input[i] · L_i(τ)·g₁
    
    # 配对检查 (核心!)
    check1 = e(A, B) 
    check2 = e(α·g₁, β·g₂) · e(L_pub, γ·g₂) · e(C, δ·g₂)
    
    return check1 == check2
```

**为什么有效?**
```
核心原理: QAP的可满足性

如果witness正确,则:
  L(τ) · R(τ) - O(τ) = H(τ) · Z(τ)

配对等式验证了这个关系:
  e(A, B) 包含了 L(τ)·R(τ) 的信息
  e(C, δ·g₂) 包含了 O(τ) + H(τ)·Z(τ) 的信息
  
通过精心设计的组合,确保:
  只有当 L·R - O = H·Z 时,配对等式才成立
```

**零知识性来源**:
```
随机盲化因子 r, s:
- 即使Verifier看到A, B, C
- 由于r, s的随机性,无法反推witness
- 类似于"加性秘密分享": a + random = ?
```

---

### 2.3 电路设计基础

#### 什么是"电路"?

**从程序到电路的转换**:
```python
# 普通程序
def check_distance(x1, y1, x2, y2, v_max, dt):
    dx = x2 - x1
    dy = y2 - y1
    dist_sq = dx*dx + dy*dy
    max_dist = v_max * dt
    return dist_sq <= max_dist * max_dist

# 转为算术电路
R1CS (Rank-1 Constraint System):
每个约束的形式: (a·b = c)

约束1: dx = x2 - x1
  w_dx · 1 = w_x2 - w_x1
  
约束2: dy = y2 - y1
  w_dy · 1 = w_y2 - w_y1
  
约束3: dist_sq = dx²
  w_dx · w_dx = w_dist_sq
  
约束4: dy_sq = dy²
  w_dy · w_dy = w_dy_sq
  
约束5: dist_sq = dx² + dy²
  w_dist_sq · 1 = w_dx_sq + w_dy_sq
  
...

总约束数: 约15-20个
```

**电路大小与性能**:
```
电路大小 = 约束数量

影响:
- Setup时间: O(约束数) ~= 1秒 per 10K约束
- Proving时间: O(约束数·log(约束数)) ~= 0.1秒 per 10K约束
- 证明大小: O(1) (与约束数无关!) = 128 bytes
- 验证时间: O(公开输入数)（实现相关）

TSIP的距离验证电路:
- 约束数: `70`
- Proving时间: `snarkjs≈1151ms` / `rapidsnark≈308ms`
- 验证时间: `snarkjs≈1035ms`
```

#### Circom语言简介

**Circom**: 专门用于编写zk-SNARK电路的DSL

**基本语法**:
```circom
pragma circom 2.0.0;

// 模板 = 电路组件
template Multiplier() {
    // 信号 = 电路中的变量
    signal input a;
    signal input b;
    signal output c;
    
    // 约束
    c <== a * b;  // <== 表示约束 + 赋值
}

// 主电路
component main = Multiplier();
```

**关键概念**:
```circom
1. signal: 电路中的变量
   - signal input: 输入信号(可以是私密或公开)
   - signal output: 输出信号
   - signal intermediate: 中间变量

2. 约束操作符:
   - <==  : 赋值+约束 (最常用)
   - === : 纯约束 (不赋值)
   - <-- : 纯赋值 (不生成约束,危险!)

3. 组件 (component): 复用电路
   template LessThan(n) { ... }
   component lt = LessThan(32);
   lt.in[0] <== a;
   lt.in[1] <== b;
```

**TSIP距离检查电路 (预览, 教学示例)**:
```circom
template DistanceCheck() {
    // 私密输入: 两个位置
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    signal input t1;
    signal input t2;
    
    // 公开输入: 物理参数
    signal input v_max;
    
    // 输出: 是否合法
    signal output valid;
    
    // 中间信号
    signal dx;
    signal dy;
    signal dist_sq;
    signal time_diff;
    signal max_dist_sq;
    
    // 约束1: 计算位移
    dx <== x2 - x1;
    dy <== y2 - y1;
    
    // 约束2: 距离平方
    dist_sq <== dx*dx + dy*dy;
    
    // 约束3: 时间差
    time_diff <== t2 - t1;
    
    // 约束4: 最大允许距离的平方
    signal max_dist;
    max_dist <== v_max * time_diff;
    max_dist_sq <== max_dist * max_dist;
    
    // 约束5: 距离检查
    component lt = LessThanOrEqual(64);
    lt.in[0] <== dist_sq;
    lt.in[1] <== max_dist_sq;
    
    valid <== lt.out;
}
```

---

### 2.4 将TSIP问题转化为电路

> 本节用于教学解释电路建模思路；详细规范见第 5.5 节。

#### 问题分解

**TSIP要证明的语句**:
```
公开信息:
- v_max: 最大速度 (如 100 m/s)
- Δt: 时间差 (如 300秒)
- H(loc₁): 上一个位置的哈希 (承诺)

私密信息 (witness):
- (x₁, y₁): 上一个位置的坐标
- (x₂, y₂): 当前位置的坐标

要证明:
1. H(x₁, y₁) = 上传的哈希 (位置一致性)
2. √((x₂-x₁)² + (y₂-y₁)²) ≤ v_max · Δt (物理约束)
```

#### 电路结构设计

```
[主电路: TSIPCircuit]
    ↓
[子电路1: PositionCommitment]
    验证: Hash(x₁,y₁) = H_prev
    ↓
[子电路2: DistanceCheck]
    验证: dist(loc₁, loc₂) ≤ max_dist
    ↓
[子电路3: RangeCheck]
    验证: 坐标在合理范围内
    (防止溢出攻击)
```

**完整电路伪代码（教学版，简化）**:
```circom
include "poseidon.circom";  // 哈希函数
include "comparators.circom";

template TSIPCircuit() {
    // ===== 输入信号 =====
    // 私密
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    
    // 公开
    signal input hash_prev;  // 上一个位置的承诺
    signal input hash_curr;  // 当前位置的承诺(由电路计算)
    signal input max_dist_sq; // 预计算后的最大允许位移平方
    
    // ===== 输出信号 =====
    signal output valid;
    
    // ===== 子电路1: 验证历史位置 =====
    component hash1 = Poseidon(2);
    hash1.inputs[0] <== x1;
    hash1.inputs[1] <== y1;
    
    // 约束: 必须等于声明的哈希
    hash1.out === hash_prev;
    
    // ===== 子电路2: 计算当前位置哈希 =====
    component hash2 = Poseidon(2);
    hash2.inputs[0] <== x2;
    hash2.inputs[1] <== y2;
    hash2.out === hash_curr;  // 公开输出
    
    // ===== 子电路3: 距离检查 =====
    signal dx;
    signal dy;
    dx <== x2 - x1;
    dy <== y2 - y1;
    
    signal dx_sq;
    signal dy_sq;
    dx_sq <== dx * dx;
    dy_sq <== dy * dy;
    
    signal dist_sq;
    dist_sq <== dx_sq + dy_sq;
    
    // ===== 子电路4: 比较 =====
    component lt = LessThanOrEqual(128);  // 128位比较器
    lt.in[0] <== dist_sq;
    lt.in[1] <== max_dist_sq;
    
    // ===== 子电路5: 范围检查 =====
    // 确保坐标在合理范围 (如: 0 ≤ x ≤ 10^6)
    component range_x1 = RangeCheck(32);
    range_x1.in <== x1;
    
    component range_y1 = RangeCheck(32);
    range_y1.in <== y1;
    
    component range_x2 = RangeCheck(32);
    range_x2.in <== x2;
    
    component range_y2 = RangeCheck(32);
    range_y2.in <== y2;
    
    // ===== 最终输出 =====
    signal all_checks_pass;
    all_checks_pass <== lt.out * range_x1.out * range_y1.out 
                              * range_x2.out * range_y2.out;
    1 === all_checks_pass;   // 关键: 不允许 valid=0 的 witness 被接受
    valid <== 1;
}
```

> 说明：本段仅用于概念讲解（简化示意）。论文与实现统一采用的主电路为 §5.5.1 的 `TSIPMain`（5 个 public inputs + P4/P5 约束）。

#### 电路优化技巧

**优化1: 避免平方根**
```
错误写法:
  dist = sqrt(dx² + dy²)
  check: dist ≤ max_dist

问题: 电路中没有高效的平方根运算!

正确写法:
  dist² = dx² + dy²
  check: dist² ≤ max_dist²

好处: 只需乘法,约束数减少50%
```

**优化2: 预计算公开值**
```
错误写法:
  max_dist_sq <== v_max * dt * v_max * dt  (4次乘法)

优化写法:
  在电路外预计算: max_dist_sq_pub = (v_max * dt)²
  作为公开输入传入
  约束: max_dist_sq === max_dist_sq_pub

好处: 约束数减少,proving时间降低
```

**优化3: 批量验证**
```
如果需要验证T个时间窗口:

Naive方案:
  for i in 0..T:
      proof[i] = prove(location[i], location[i+1])
  总proof大小: T * 128 bytes

优化方案 (聚合):
  单个电路验证所有T对位置
  总proof大小: 128 bytes (不变!)
  
实现: 将T对位置作为数组输入到一个大电路
```

---

## 第三章: TSIP协议概览

### 3.1 协议参与方

```
┌─────────────┐
│  Client_i   │ (N个用户)
│  - 轨迹数据  │
│  - proving key
└──────┬──────┘
       │ 上传: (encrypted_location, TSIP_proof)
       ↓
┌─────────────┐
│  Shuffler   │
│  - 验证proof │
│  - 去重/批处理
└──────┬──────┘
       │ 转发: 通过验证的数据
       ↓
┌──────────────────┐
│  Aggregator A/R  │
│  - MPC聚合       │
│  - 不解密位置     │
└──────┬───────────┘
       │ 加密份额
       ↓
┌─────────────┐
│   Decoder   │
│  - 重构热力图 │
│  - 添加DP噪声│
└─────────────┘
```

### 3.2 协议流程 (高层视角)

#### 初始化阶段 (Setup Phase)
```
Step 0: 系统初始化
1. 可信第三方生成 (proving_key, verification_key)
2. proving_key 分发给所有客户端
3. verification_key 存储在Shuffler
4. 客户端初始化: location_history = []
```

#### 第一个时间窗口 (t=0)
```
Client_i:
  1. 采集位置: loc₀ = (x₀, y₀)
  2. 计算承诺: H₀ = Hash(x₀, y₀)
  3. 加密位置: enc_loc₀ = Encrypt(loc₀)
  4. 上传: (enc_loc₀, H₀)
  
 第一个位置无历史对比:
     - 在 legacy_accept 策略下可直接入链;
     - 在 enroll_only 策略下仅登记锚点,不计入发布轮统计。

Shuffler:
  1. 存储 H₀ 与 user_id 的映射
  2. 转发 enc_loc₀ 到聚合器
```

#### 后续时间窗口 (t≥1)
```
Client_i (时刻t):
  1. 采集新位置: locₜ = (xₜ, yₜ)
  2. 取出历史: locₜ₋₁ = history[-1]
  3. 生成TSIP证明:
     proof = TSIP_Prove(
         witness: (xₜ₋₁, yₜ₋₁, xₜ, yₜ),
         public:  (Hₜ₋₁, Hₜ, max_dist_sq)
     )
  4. 加密新位置: enc_locₜ = Encrypt(xₜ, yₜ)
  5. 计算新承诺: Hₜ = Hash(xₜ, yₜ)
  6. 上传: (enc_locₜ, Hₜ, proof)
  7. 更新历史: history.append(locₜ)

Shuffler (时刻t):
  1. 获取用户i的历史承诺: Hₜ₋₁
  2. 验证TSIP证明:
     valid = TSIP_Verify(
         proof, 
         public_inputs: (Hₜ₋₁, Hₜ, max_dist_sq)
     )
  3. 如果valid:
       - 更新承诺: commitment[user_i] = Hₜ
       - 转发 enc_locₜ 到聚合器
     否则:
       - 拒绝提交
       - 记录恶意行为
```

### 3.3 关键机制

#### 机制1: 位置承诺链 (Location Commitment Chain)

**目的**: 将时间序列的位置"链接"起来,防止身份交换

```
用户A的承诺链:
t=0: H₀ᴬ = Hash(loc₀ᴬ)
t=1: H₁ᴬ = Hash(loc₁ᴬ), prove: loc₁ᴬ与loc₀ᴬ连续
t=2: H₂ᴬ = Hash(loc₂ᴬ), prove: loc₂ᴬ与loc₁ᴬ连续
...

关键属性:
- 服务器只存储哈希H,不知道具体位置
- 但可以验证: "第i个证明对应的loc_i"确实是"第i-1个证明声称的loc_{i-1}的延续"
```

**防御身份交换攻击**:
```
攻击尝试:
t=0: Alice提交H₀ᴬ, Bob提交H₀ᴮ
t=1: Alice想用Bob的ID提交

问题:
- Alice不仅要满足距离约束,还必须同时满足:
  1) hidden user secret 跨轮一致;
  2) epoch/nullifier 未重放;
  3) proof_digest 与 payload_core_digest 绑定一致。
- 仅靠"A不知道B的loc₀"不是主要安全依据。

∴ 攻击失败 ✓
```

#### 机制2: 零知识距离验证

**传统方案的问题**:
```
# RiseFL的验证
def verify_location(loc, random_vector):
    inner_prod = dot(loc, random_vector)
    return check_bound(inner_prod)

缺点: 需要知道loc的明文!
```

**TSIP的解决**:
```
# 零知识验证
def tsip_verify(proof, public_inputs):
    # 不需要知道loc₁或loc₂的明文
    # 只验证密码学证明
    return groth16.verify(proof, public_inputs)

优势:
- 聚合器永远看不到明文位置
- 仍能确保物理约束满足
```

---

### 3.4 安全性直觉

#### 为什么TSIP是安全的?

**完整性 (Soundness)**:
```
假设攻击者想提交违反物理约束的位置:

情况1: 伪造证明
  攻击者构造 fake_proof
  由于Groth16的soundness,
  Pr[fake_proof通过验证] ≤ 2^(-128)

情况2: 复用他人的证明
  攻击者复制Alice的proof
  但proof绑定了Alice的承诺链H_prev^Alice
  攻击者的H_prev不同 → 验证失败

情况3: 身份交换
  攻击者A和B想在t=1交换ID
  A需要prove(loc₁ᴬ, H₀ᴮ)
  仅靠"A不知道B的loc₀"不是充分论证;
  强安全需结合 user-secret 绑定与状态机规则

结论:
  在定理作用域与系统假设内，违规提交通过概率可忽略；
  不宣称”所有攻击路径无条件被阻断”。
```

**隐私性 (Zero-Knowledge)**:
```
Shuffler和聚合器学到的信息:
1. 承诺哈希: H₀, H₁, H₂, ...
   - 由于哈希的单向性,无法反推位置
2. 证明: π₁, π₂, ...
   - 由于zk-SNARK的零知识性,不泄露witness

额外保护:
- 位置本身用秘密分享加密
- 聚合在MPC中进行
- 最终输出添加DP噪声

结论:
  对公开发布热力图满足 public-output DP；
  内部 accept/reject 与链状态信息作为 internal leakage 单独讨论。
```

---

## 第四章: 与现有方案的对比

### 4.1 功能对比

| 方案 | 验证单点位置 | 验证时序连续性 | 零知识 | DP保证 |
|------|-------------|---------------|--------|--------|
| **Nebula** | ❌ | ❌ | ❌ | |
| **RiseFL** | | ❌ | 部分 | ❌ |
| **Clover** | ❌ | ❌ | | 弱 |
| **TSIP (ours)** | | | | |

### 4.2 攻击抵抗能力

| 攻击类型 | Nebula | RiseFL | Clover | TSIP |
|---------|--------|--------|--------|------|
| **虚假位置注入** | ❌ | | ❌ | |
| **身份交换攻击** | ❌ | ❌ | ❌ | |
| **Sybil+瞬移** | ❌ | ❌ | ❌ | |
| **差分攻击** | | ❌ | | |
| **模型反演** | | ❌ | | |

### 4.3 效率对比 (理论分析)

| 指标 | Nebula | RiseFL | Clover | TSIP |
|------|--------|--------|--------|------|
| **客户端计算** | O(k) | O(m·d) | O(k log d) | O(k log d) |
| **通信量** | O(k) | O(m·d) | O(k) | O(k + log T) |
| **服务器验证** | O(1) | O(m·d) | O(k) | O(log T) |

**数值示例** (k=50, d=10⁶, m=10, T=288):
```
通信量:
- Nebula: 50 × 4 bytes = 200 bytes
- RiseFL: 10 × 10⁶ × 4 bytes = 40 MB (!!)
- Clover: 50 × 4 bytes = 200 bytes
- TSIP: 200 + log(288) × 128 = 200 + 1KB = 1.2 KB

客户端延迟:
- Nebula: ~1 ms
- RiseFL: ~100 ms
- Clover: ~5 ms
- TSIP: snarkjs约1.15~1.39s；rapidsnark约0.31~0.41s（当前实测）
```

---

## 小结

本部分建立了TSIP的理论基础:
1. 形式化了"时空完整性"问题
2. 介绍了零知识证明和Groth16
3. 设计了距离验证电路
4. 给出了协议的高层流程

**下一部分**: 详细协议设计与完整实现代码

---

## 参考文献

[1] Groth, J. (2016). On the Size of Pairing-based Non-interactive Arguments. EUROCRYPT.

[2] Ben-Sasson, E., et al. (2014). Succinct Non-Interactive Zero Knowledge for a von Neumann Architecture. USENIX Security.

[3] RiseFL: Secure Aggregation for Federated Learning. NDSS 2024.

[4] Clover: Efficient Sparse Aggregation. USENIX Security 2023.

[5] Nebula: Differentially Private Histograms. SIGMOD 2022

[6] Grassi, L. et al. Poseidon: A New Hash Function for Zero-Knowledge Proof Systems. USENIX Security 2021.

[7] Albrecht, M. et al. MiMC: Efficient Encryption and Cryptographic Hashing with Minimal Multiplicative Complexity. ASIACRYPT 2016.

## 第五章: 详细协议规范

### 5.1 系统参数

#### 全局参数配置

```python
# config/tsip_params.py

class TSIPParameters:
    """TSIP系统参数配置"""
    
    # ===== 隐私参数 =====
    EPSILON_TOTAL = 1.0          # 总隐私预算
    EPSILON_SVT = 0.3            # 稀疏向量技术预算
    EPSILON_VALUE = 0.7          # 值噪声预算
    EPSILON_VERIFY_EXPERIMENT = 0.2  # 仅用于可选随机化验证实验，不计入主口径
    DELTA = 1e-8                 # 兼容字段（当前纯 Laplace 主口径下不计入主结论）
    
    # ===== 物理约束参数 =====
    V_MAX = 110.0                # 当前实现默认最大速度 (m/s)
    TIME_WINDOW = 60             # 当前实现默认时间窗口 (秒)
    MAX_DISTANCE = V_MAX * TIME_WINDOW  # = 6,600 m
    
    # ===== 地理空间参数 =====
    GRID_SIZE = 100              # 网格大小 (米)
    GRID_WIDTH = 100             # 当前实现网格宽度数量
    GRID_HEIGHT = 100            # 当前实现网格高度数量
    DOMAIN_SIZE = GRID_WIDTH * GRID_HEIGHT  # = 10^4 个网格
    
    # 坐标范围 (假设东京市区)
    LAT_MIN = 35.5               # 最小纬度
    LAT_MAX = 35.8               # 最大纬度
    LON_MIN = 139.5              # 最小经度
    LON_MAX = 139.9              # 最大经度
    
    # 投影后的坐标范围 (米)
    X_MIN = 0
    X_MAX = GRID_WIDTH * GRID_SIZE   # = 1,000,000 m = 1000 km
    Y_MIN = 0
    Y_MAX = GRID_HEIGHT * GRID_SIZE  # = 1,000,000 m = 1000 km
    
    # ===== 零知识证明参数 =====
    CURVE = "bn254"              # 椭圆曲线
    # 哈希函数口径（与代码一致）:
    # - 位置承诺（链下计算）: Poseidon(2 inputs)
    # - 链承诺: MiMC7
    # - 主电路约束: circomlib Poseidon(2)
    # 注：仓库中 `poseidon2_bench` 仅为历史命名，实际调用的是 Poseidon(2) 电路。
    HASH_FUNCTION = "Poseidon(2-ary) + MiMC7"
    SECURITY_PARAM = 128         # 安全参数 (bits)
    
    # ===== 稀疏化参数 =====
    TOP_K = 50                   # 每个用户保留的Top-K位置
    QUANTIZATION_BITS = 4        # 停留时间量化位数
    
    # ===== 系统参数 =====
    NUM_TIME_WINDOWS = 1440      # 24小时,每60秒一个窗口
    BATCH_SIZE = 100             # 聚合批次大小
    BATCH_TIMEOUT = 30           # 批次超时 (秒)
    
    # ===== 恶意行为检测 =====
    MAX_REJECTION_RATE = 0.05    # 最大允许拒绝率 (5%)
    BLACKLIST_THRESHOLD = 3      # 连续拒绝次数阈值
```

---

### 5.2 数据结构定义

#### 位置数据结构

```python
# tsip/types.py

from dataclasses import dataclass
from typing import List, Tuple
import numpy as np

@dataclass
class Location:
    """单个位置点"""
    x: float              # 投影后的x坐标 (米)
    y: float              # 投影后的y坐标 (米)
    timestamp: int        # Unix时间戳 (秒)
    cell_id: int          # 网格ID
    dwell_time: float     # 停留时间 (秒)
    
    def to_array(self) -> np.ndarray:
        """转为numpy数组 (用于电路输入)"""
        return np.array([self.x, self.y, self.timestamp], dtype=np.int64)
    
    @staticmethod
    def from_latlon(lat: float, lon: float, timestamp: int) -> 'Location':
        """从经纬度创建位置"""
        x, y = latlon_to_xy(lat, lon)
        cell_id = xy_to_cell_id(x, y)
        return Location(x, y, timestamp, cell_id, 0.0)

@dataclass
class Trajectory:
    """用户轨迹"""
    user_id: str
    locations: List[Location]
    
    def get_sparse_vector(self) -> Tuple[np.ndarray, np.ndarray]:
        """转为稀疏向量表示"""
        # 聚合停留时间
        cell_visits = {}
        for loc in self.locations:
            if loc.cell_id not in cell_visits:
                cell_visits[loc.cell_id] = 0
            cell_visits[loc.cell_id] += loc.dwell_time
        
        # Top-K筛选
        sorted_cells = sorted(
            cell_visits.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:TSIPParameters.TOP_K]
        
        indices = np.array([c[0] for c in sorted_cells], dtype=np.int32)
        values = np.array([c[1] for c in sorted_cells], dtype=np.float32)
        
        return indices, values

@dataclass
class LocationCommitment:
    """位置承诺"""
    hash: bytes           # Hash(x, y) - 32 bytes
    timestamp: int        # 时间戳
    window_id: int        # 时间窗口ID
    
    def verify(self, location: Location) -> bool:
        """验证位置是否匹配承诺"""
        computed_hash = poseidon_hash(location.x, location.y)
        return computed_hash == self.hash

@dataclass
class TSIPProof:
    """TSIP零知识证明（主电路口径）"""
    proof_a: bytes        # Groth16证明的A部分 (G1点, 32 bytes)
    proof_b: bytes        # Groth16证明的B部分 (G2点, 64 bytes)
    proof_c: bytes        # Groth16证明的C部分 (G1点, 32 bytes)
    
    # 公开输入（5个）
    hash_prev: int              # Poseidon(x1, y1)
    hash_curr: int              # Poseidon(x2, y2)
    max_dist_sq: int            # (v_max * Δt)^2
    payload_commitment: int     # Poseidon(payload_lo, payload_hi)
    secret_commitment: int      # Poseidon(secret, user_id_field)
    
    # 私有 witness（8个，文档字段说明）
    # x1, y1, x2, y2, payload_lo, payload_hi, secret, user_id_field
    
    def to_bytes(self) -> bytes:
        """序列化为字节"""
        return self.proof_a + self.proof_b + self.proof_c
    
    @staticmethod
    def from_bytes(data: bytes, public_inputs: dict) -> 'TSIPProof':
        """从字节反序列化"""
        return TSIPProof(
            proof_a=data[:32],
            proof_b=data[32:96],
            proof_c=data[96:128],
            **public_inputs
        )
    
    def size(self) -> int:
        """证明大小 (字节)"""
        return 128  # Groth16固定大小

@dataclass
class EncryptedLocation:
    """加密的位置数据"""
    ciphertext: bytes        # 加密的(x, y, timestamp)
    shares_a: bytes          # 给聚合器A的秘密份额
    shares_r: bytes          # 给聚合器R的秘密份额
    nonce: bytes             # 加密nonce
    
    def decrypt(self, key_a: bytes, key_r: bytes) -> Location:
        """解密位置 (需要两个密钥)"""
        # 重构秘密
        combined_key = xor_bytes(key_a, key_r)
        plaintext = aes_decrypt(self.ciphertext, combined_key, self.nonce)
        
        x, y, t = decode_location(plaintext)
        return Location(x, y, t, xy_to_cell_id(x, y), 0.0)
```

---

### 5.3 客户端协议实现

#### 5.3.1 TSIP客户端完整实现

```python
# tsip/client.py

import time
import hashlib
from typing import Optional, List
from snarkjs import groth16_prove, groth16_verify  # zk-SNARK库

class TSIPClient:
    """TSIP客户端实现"""
    
    def __init__(self, user_id: str, proving_key_path: str):
        """
        初始化客户端
        
        Args:
            user_id: 用户唯一标识
            proving_key_path: Groth16 proving key文件路径
        """
        self.user_id = user_id
        self.proving_key = self.load_proving_key(proving_key_path)
        
        # 历史位置链
        self.location_history: List[Location] = []
        self.commitment_history: List[LocationCommitment] = []
        
        # 统计信息
        self.stats = {
            "total_submissions": 0,
            "accepted": 0,
            "rejected": 0,
            "avg_proof_time": 0.0
        }
    
    def load_proving_key(self, path: str):
        """加载proving key"""
        with open(path, 'rb') as f:
            return f.read()
    
    def submit_location(self, 
                       lat: float, 
                       lon: float, 
                       timestamp: int,
                       shuffler_url: str) -> bool:
        """
        提交位置到服务器
        
        Args:
            lat: 纬度
            lon: 经度
            timestamp: 时间戳
            shuffler_url: Shuffler服务器地址
            
        Returns:
            是否提交成功
        """
        # 1. 创建位置对象
        location = Location.from_latlon(lat, lon, timestamp)
        
        # 2. 计算位置承诺
        commitment = self.compute_commitment(location)
        
        # 3. 判断是否需要生成TSIP证明
        if len(self.location_history) == 0:
            # 第一次提交,无需证明
            proof = None
        else:
            # 生成TSIP证明
            prev_location = self.location_history[-1]
            prev_commitment = self.commitment_history[-1]
            
            start_time = time.time()
            proof = self.generate_tsip_proof(
                prev_location, 
                location, 
                prev_commitment
            )
            proof_time = time.time() - start_time
            
            # 更新统计
            self.stats["avg_proof_time"] = (
                self.stats["avg_proof_time"] * self.stats["total_submissions"]
                + proof_time
            ) / (self.stats["total_submissions"] + 1)
        
        # 4. 加密位置
        encrypted_loc = self.encrypt_location(location)
        
        # 5. 构造上传消息
        message = {
            "user_id": self.user_id,
            "encrypted_location": encrypted_loc.to_dict(),
            "commitment": commitment.hash.hex(),
            "timestamp": timestamp,
            "window_id": self.get_window_id(timestamp),
            "proof": proof.to_dict() if proof else None
        }
        
        # 6. 发送到Shuffler
        response = self.send_to_shuffler(shuffler_url, message)
        
        # 7. 处理响应
        if response["status"] == "accepted":
            # 更新历史
            self.location_history.append(location)
            self.commitment_history.append(commitment)
            self.stats["accepted"] += 1
            self.stats["total_submissions"] += 1
            return True
        else:
            # 拒绝
            self.stats["rejected"] += 1
            self.stats["total_submissions"] += 1
            print(f"❌ Submission rejected: {response['reason']}")
            return False
    
    def compute_commitment(self, location: Location) -> LocationCommitment:
        """
        计算位置承诺
        
        使用Poseidon哈希: H = Poseidon(x, y)
        """
        hash_value = poseidon_hash(
            int(location.x), 
            int(location.y)
        )
        
        return LocationCommitment(
            hash=hash_value,
            timestamp=location.timestamp,
            window_id=self.get_window_id(location.timestamp)
        )
    
    def generate_tsip_proof(self,
                           prev_location: Location,
                           curr_location: Location,
                           prev_commitment: LocationCommitment) -> TSIPProof:
        """
        生成TSIP零知识证明
        
        证明语句:
        1. prev_commitment = Hash(prev_location)
        2. distance(prev_location, curr_location) ≤ v_max * Δt
        """
        # 准备witness (私密输入)
        witness = {
            "x1": int(prev_location.x),
            "y1": int(prev_location.y),
            "t1": prev_location.timestamp,
            "x2": int(curr_location.x),
            "y2": int(curr_location.y),
            "t2": curr_location.timestamp
        }
        
        # 准备公开输入
        time_diff = curr_location.timestamp - prev_location.timestamp
        curr_commitment = self.compute_commitment(curr_location)
        
        public_inputs = {
            "hash_prev": bytes_to_field_element(prev_commitment.hash),
            "hash_curr": bytes_to_field_element(curr_commitment.hash),
            "v_max": int(TSIPParameters.V_MAX),
            "time_diff": time_diff
        }
        
        # 调用Groth16证明生成
        proof_data = groth16_prove(
            circuit="tsip_circuit.wasm",
            proving_key=self.proving_key,
            witness=witness,
            public_inputs=public_inputs
        )
        
        # 构造证明对象
        return TSIPProof(
            proof_a=proof_data["pi_a"],
            proof_b=proof_data["pi_b"],
            proof_c=proof_data["pi_c"],
            prev_commitment=prev_commitment.hash,
            curr_commitment=curr_commitment.hash,
            v_max=TSIPParameters.V_MAX,
            time_diff=time_diff
        )
    
    def encrypt_location(self, location: Location) -> EncryptedLocation:
        """
        加密位置数据 (使用秘密分享)
        
        将位置(x, y)分成两个份额:
        - share_A 给聚合器A
        - share_R 给聚合器R
        满足: x = share_A + share_R (mod p)
        """
        # 生成随机份额
        import secrets
        prime = 2**31 - 1  # 梅森素数
        
        x_share_a = secrets.randbelow(prime)
        x_share_r = (int(location.x) - x_share_a) % prime
        
        y_share_a = secrets.randbelow(prime)
        y_share_r = (int(location.y) - y_share_a) % prime
        
        # 打包份额
        shares_a = encode_shares(x_share_a, y_share_a)
        shares_r = encode_shares(x_share_r, y_share_r)
        
        # 生成ciphertext (用于完整性校验)
        nonce = secrets.token_bytes(12)
        ciphertext = aes_encrypt(
            data=encode_location(location),
            key=hashlib.sha256(shares_a + shares_r).digest(),
            nonce=nonce
        )
        
        return EncryptedLocation(
            ciphertext=ciphertext,
            shares_a=shares_a,
            shares_r=shares_r,
            nonce=nonce
        )
    
    def get_window_id(self, timestamp: int) -> int:
        """计算时间窗口ID"""
        return timestamp // TSIPParameters.TIME_WINDOW
    
    def send_to_shuffler(self, url: str, message: dict) -> dict:
        """发送消息到Shuffler"""
        import requests
        try:
            response = requests.post(
                f"{url}/tsip/submit",
                json=message,
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {"status": "error", "reason": str(e)}
    
    def get_statistics(self) -> dict:
        """获取客户端统计信息"""
        total = self.stats["total_submissions"]
        if total == 0:
            return self.stats
        
        return {
            **self.stats,
            "acceptance_rate": self.stats["accepted"] / total,
            "rejection_rate": self.stats["rejected"] / total
        }
```

---

#### 5.3.2 电路接口实现

```python
# tsip/circuit_interface.py

import subprocess
import json
import os

class CircuitInterface:
    """与circom编译的电路交互的接口"""
    
    def __init__(self, wasm_path: str, zkey_path: str):
        """
        初始化电路接口
        
        Args:
            wasm_path: 编译后的wasm文件路径
            zkey_path: proving key文件路径
        """
        self.wasm_path = wasm_path
        self.zkey_path = zkey_path
    
    def generate_witness(self, inputs: dict) -> str:
        """
        生成witness
        
        Args:
            inputs: 电路输入 (私密+公开)
            
        Returns:
            witness.wtns文件路径
        """
        # 写入input.json
        input_file = "/tmp/input.json"
        with open(input_file, 'w') as f:
            json.dump(inputs, f)
        
        # 调用snarkjs生成witness
        witness_file = "/tmp/witness.wtns"
        cmd = [
            "snarkjs", "wtns", "calculate",
            self.wasm_path,
            input_file,
            witness_file
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        return witness_file
    
    def prove(self, witness_file: str) -> dict:
        """
        生成Groth16证明
        
        Args:
            witness_file: witness文件路径
            
        Returns:
            证明数据 {proof, publicSignals}
        """
        proof_file = "/tmp/proof.json"
        public_file = "/tmp/public.json"
        
        cmd = [
            "snarkjs", "groth16", "prove",
            self.zkey_path,
            witness_file,
            proof_file,
            public_file
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # 读取证明
        with open(proof_file, 'r') as f:
            proof = json.load(f)
        with open(public_file, 'r') as f:
            public_signals = json.load(f)
        
        return {
            "proof": proof,
            "publicSignals": public_signals
        }
    
    @staticmethod
    def verify(vkey_path: str, 
              proof: dict, 
              public_signals: list) -> bool:
        """
        验证Groth16证明
        
        Args:
            vkey_path: verification key路径
            proof: 证明数据
            public_signals: 公开信号
            
        Returns:
            验证是否通过
        """
        # 写入临时文件
        proof_file = "/tmp/verify_proof.json"
        public_file = "/tmp/verify_public.json"
        
        with open(proof_file, 'w') as f:
            json.dump(proof, f)
        with open(public_file, 'w') as f:
            json.dump(public_signals, f)
        
        # 调用snarkjs验证
        cmd = [
            "snarkjs", "groth16", "verify",
            vkey_path,
            public_file,
            proof_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        return "OK" in result.stdout
```

---

#### 5.3.3 P4/P5 客户端提交流程（与当前实现对齐）

```text
输入：
  idx, val, prev_loc_commitment, curr_loc_commitment, prev_chain_commitment
  user_secret, user_id

步骤：
  1) 计算 payload_digest = SHA-256(sorted(idx))
  2) 构造 payload witness：
       payload_lo, payload_hi（由 payload_digest 切分）
       payload_commitment = Poseidon(payload_lo, payload_hi)
  3) 构造身份 witness：
       secret, user_id_field
       secret_commitment = Poseidon(secret, user_id_field)
  4) 计算 curr_chain_commitment =
       MiMC(prev_chain_commitment, curr_loc_commitment, t, w,
            field(payload_digest), field(secret_commitment))
  5) 生成 TSIP 主证明：
       public_signals = [hash_prev, hash_curr, max_dist_sq,
                         payload_commitment, secret_commitment]
       witness = [x1, y1, x2, y2, payload_lo, payload_hi, secret, user_id_field]
  6) 上传 report:
       {idx, val, tsip:{proof, public_signals, payload_commitment_field, secret_commitment_field}}
```

说明：
- P4 目标：防止“proof 与 payload 拆分替换”。
- P5 目标：防止“已知受害者坐标时的身份冒用”。
- 论文主口径采用电路约束（P4/P5 为强制 public-input 绑定）。

---

### 5.4 服务器端协议实现

#### 5.4.1 Shuffler实现 (TSIP验证器)

```python
# tsip/shuffler.py

from flask import Flask, request, jsonify
from typing import Dict, Optional
import time

app = Flask(__name__)

class TSIPShuffler:
    """
    Shuffler服务器: 负责验证TSIP证明
    """
    
    def __init__(self, vkey_path: str):
        """
        初始化Shuffler
        
        Args:
            vkey_path: Groth16 verification key路径
        """
        self.vkey_path = vkey_path
        
        # 用户状态跟踪
        self.user_commitments: Dict[str, LocationCommitment] = {}
        self.user_submissions: Dict[str, int] = {}  # 提交次数
        self.user_rejections: Dict[str, int] = {}   # 拒绝次数
        
        # 黑名单
        self.blacklist = set()
        
        # 统计
        self.stats = {
            "total_submissions": 0,
            "accepted": 0,
            "rejected": 0,
            "rejection_reasons": {}
        }
    
    @app.route('/tsip/submit', methods=['POST'])
    def handle_submission(self):
        """处理客户端提交"""
        data = request.json
        user_id = data["user_id"]
        
        # 检查黑名单
        if user_id in self.blacklist:
            return jsonify({
                "status": "rejected",
                "reason": "blacklisted"
            }), 403
        
        # 更新统计
        self.stats["total_submissions"] += 1
        self.user_submissions[user_id] = self.user_submissions.get(user_id, 0) + 1
        
        # 验证提交
        validation_result = self.validate_submission(data)
        
        if validation_result["valid"]:
            # 接受
            self.on_accepted(user_id, data)
            return jsonify({
                "status": "accepted",
                "message": "Submission verified"
            })
        else:
            # 拒绝
            self.on_rejected(user_id, validation_result["reason"])
            return jsonify({
                "status": "rejected",
                "reason": validation_result["reason"]
            }), 400
    
    def validate_submission(self, data: dict) -> dict:
        """
        验证提交数据
        
        Returns:
            {"valid": bool, "reason": str}
        """
        user_id = data["user_id"]
        
        # 第一次提交: 无需TSIP证明
        if user_id not in self.user_commitments:
            return {"valid": True, "reason": ""}
        
        # 后续提交: 验证TSIP证明
        if "proof" not in data or data["proof"] is None:
            return {"valid": False, "reason": "missing_proof"}
        
        proof_data = data["proof"]
        
        # 1. 检查时间窗口合理性
        prev_commitment = self.user_commitments[user_id]
        time_diff = data["timestamp"] - prev_commitment.timestamp
        
        if time_diff < 0:
            return {"valid": False, "reason": "time_reversal"}
        
        if time_diff > 2 * TSIPParameters.TIME_WINDOW:
            return {"valid": False, "reason": "time_gap_too_large"}
        
        # 2. 验证Groth16证明
        public_inputs = [
            proof_data["prev_commitment"],
            proof_data["curr_commitment"],
            proof_data["v_max"],
            proof_data["time_diff"]
        ]
        
        proof_verified = CircuitInterface.verify(
            vkey_path=self.vkey_path,
            proof=proof_data["proof"],
            public_signals=public_inputs
        )
        
        if not proof_verified:
            return {"valid": False, "reason": "invalid_tsip_proof"}
        
        # 3. 验证承诺链连续性
        if proof_data["prev_commitment"] != prev_commitment.hash.hex():
            return {"valid": False, "reason": "commitment_mismatch"}
        
        return {"valid": True, "reason": ""}
    
    def on_accepted(self, user_id: str, data: dict):
        """处理接受的提交"""
        # 更新承诺历史
        commitment = LocationCommitment(
            hash=bytes.fromhex(data["commitment"]),
            timestamp=data["timestamp"],
            window_id=data["window_id"]
        )
        self.user_commitments[user_id] = commitment
        
        # 转发到聚合器
        self.forward_to_aggregators(data)
        
        # 更新统计
        self.stats["accepted"] += 1
    
    def on_rejected(self, user_id: str, reason: str):
        """处理拒绝的提交"""
        # 更新拒绝计数
        self.user_rejections[user_id] = self.user_rejections.get(user_id, 0) + 1
        
        # 检查是否应加入黑名单
        if self.user_rejections[user_id] >= TSIPParameters.BLACKLIST_THRESHOLD:
            self.blacklist.add(user_id)
            print(f" User {user_id} blacklisted (rejections: {self.user_rejections[user_id]})")
        
        # 更新统计
        self.stats["rejected"] += 1
        if reason not in self.stats["rejection_reasons"]:
            self.stats["rejection_reasons"][reason] = 0
        self.stats["rejection_reasons"][reason] += 1
    
    def forward_to_aggregators(self, data: dict):
        """转发验证通过的数据到聚合器"""
        import requests
        
        # 提取秘密份额
        encrypted_loc = data["encrypted_location"]
        
        # 发送到聚合器A
        try:
            requests.post(
                "http://aggregator-a:5001/ingestA",
                json={
                    "user_id": data["user_id"],
                    "shares": encrypted_loc["shares_a"],
                    "window_id": data["window_id"]
                },
                timeout=5
            )
        except Exception as e:
            print(f"❌ Failed to forward to Aggregator A: {e}")
        
        # 发送到聚合器R
        try:
            requests.post(
                "http://aggregator-r:5002/ingestR",
                json={
                    "user_id": data["user_id"],
                    "shares": encrypted_loc["shares_r"],
                    "window_id": data["window_id"]
                },
                timeout=5
            )
        except Exception as e:
            print(f"❌ Failed to forward to Aggregator R: {e}")
    
    @app.route('/tsip/stats', methods=['GET'])
    def get_stats(self):
        """获取统计信息"""
        total = self.stats["total_submissions"]
        if total == 0:
            return jsonify(self.stats)
        
        return jsonify({
            **self.stats,
            "acceptance_rate": self.stats["accepted"] / total,
            "rejection_rate": self.stats["rejected"] / total,
            "num_blacklisted": len(self.blacklist)
        })

# 启动服务器
if __name__ == '__main__':
    shuffler = TSIPShuffler(vkey_path="/keys/verification_key.json")
    app.run(host='0.0.0.0', port=5000)
```

#### 5.4.1.1 Shuffler 的 P4/P5 校验顺序（规范化）

```text
对每个 report 执行：

1) 基础结构校验
   - idx/val 长度与范围
   - submission_id / round_id 合法

2) 承诺链校验
   - prev/curr_loc_commitment 与链状态匹配
   - curr_chain_commitment 与服务端重算一致

3) 公开信号一致性校验
   - public_signals[0] == field(prev_loc_commitment)
   - public_signals[1] == field(curr_loc_commitment)
   - public_signals[3] == payload_commitment_field
   - public_signals[4] == secret_commitment_field

4) Groth16 验证
   - verify(proof, public_signals) == true

5) 状态更新
   - 更新用户链状态
   - 更新 enrollment/warmup 与黑名单状态
```

```text
安全含义：
- 第 3 步 + 第 4 步共同确保 P4/P5 不是“字符串字段校验”，而是 ZK 语句中的硬约束。
- 攻击者若替换 payload 或伪造 secret，需同时满足电路约束，成功概率受 Groth16 soundness + Poseidon 抗碰撞约束。
```

#### 当前实现对齐说明（黑名单机制）

上面的代码块描述的是设计上的理想化 Shuffler 逻辑。当前仓库中的真实实现位于 [app.py](/Users/wanghao/Desktop/risefl_mvp/services/shuffler/app.py)，其黑名单机制已经落地，并采用以下工程规则：

- 连续拒绝按 `user_id` 计数
- 同一个 `submission_id` 即使在 `A/R` 双通道都失败，也只计一次拒绝
- 当拒绝次数达到 `TSIP_BLACKLIST_THRESHOLD` 时，后续提交直接返回 `403`
- 一旦某用户完成一次成功提交，其连续拒绝计数会清零
- `/health` 会暴露 `tsip_blacklisted_users` 与 `tsip_blacklist_threshold`，用于部署观测

当前实现与设计稿的差异主要有两点：

- 真实系统的拒绝计数是基于“提交验证失败”统一累积，而不是只针对某一个 TSIP 子错误码
- 当前黑名单仍是内存态策略，服务重启后不会持久化保留

#### 当前验收结果（远程服务器）

远程服务器已经完成黑名单机制验收，观测结果如下：

- 初始状态：`tsip_blacklisted_users = 0`
- 同一测试用户连续提交 3 次非法请求后，前 3 次返回 `400`
- 第 4 次返回 `403`，错误为 `tsip user blacklisted`
- 验收后 `/health` 显示：`tsip_blacklisted_users = 1`

因此，本项目当前可以将“黑名单与连续拒绝惩罚”标记为：

- 已完成基础实现
- 已完成远程部署
- 已完成功能验收

后续如果需要继续增强，应扩展为：

- 持久化黑名单
- 人工解除或超时解除策略
- 按错误类型细分计数
- 跨轮审计与告警

---

#### 5.4.2 聚合器修改 (支持TSIP)

```python
# tsip/aggregator_tsip.py

# 在原有aggregator基础上添加TSIP支持

class TSIPAggregator:
    """支持TSIP的聚合器"""
    
    def __init__(self):
        # 原有字段
        self.bufferA = {}
        self.stats = {}
        
        # TSIP扩展: 记录每个窗口的有效提交
        self.valid_submissions_per_window = {}
    
    @app.route('/ingestA', methods=['POST'])
    def ingest_a(self):
        """接收来自Shuffler的验证通过的份额"""
        data = request.json
        user_id = data["user_id"]
        window_id = data["window_id"]
        shares = data["shares"]
        
        # 解析份额
        x_share, y_share = decode_shares(shares)
        
        # 存储
        if window_id not in self.bufferA:
            self.bufferA[window_id] = {}
            self.valid_submissions_per_window[window_id] = 0
        
        self.bufferA[window_id][user_id] = {
            "x_share": x_share,
            "y_share": y_share
        }
        
        self.valid_submissions_per_window[window_id] += 1
        
        # 检查是否达到批次大小
        if len(self.bufferA[window_id]) >= TSIPParameters.BATCH_SIZE:
            self.flush_window(window_id)
        
        return jsonify({"status": "ok"})
    
    @app.route('/tsip/window_stats/<int:window_id>', methods=['GET'])
    def get_window_stats(self, window_id: int):
        """获取指定窗口的统计"""
        return jsonify({
            "window_id": window_id,
            "valid_submissions": self.valid_submissions_per_window.get(window_id, 0),
            "buffered": len(self.bufferA.get(window_id, {}))
        })
```

---

### 5.5 电路完整实现

#### 5.5.1 TSIP主电路

```circom
// circuits/tsip_main.circom
pragma circom 2.1.9;

include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/poseidon.circom";

template PoseidonHash2() {
    signal input a;
    signal input b;
    signal output out;
    component h = Poseidon(2);
    h.inputs[0] <== a;
    h.inputs[1] <== b;
    out <== h.out;
}

template TSIPMain() {
    // private witness (8)
    signal input x1;
    signal input y1;
    signal input x2;
    signal input y2;
    signal input payload_lo;
    signal input payload_hi;
    signal input secret;
    signal input user_id_field;

    // public inputs (5)
    signal input hash_prev;
    signal input hash_curr;
    signal input max_dist_sq;
    signal input payload_commitment;
    signal input secret_commitment;

    // 1) location hash binding
    component prevHash = PoseidonHash2();
    prevHash.a <== x1;
    prevHash.b <== y1;
    prevHash.out === hash_prev;

    component currHash = PoseidonHash2();
    currHash.a <== x2;
    currHash.b <== y2;
    currHash.out === hash_curr;

    // 2) continuity constraint
    signal dx;
    signal dy;
    signal dx2;
    signal dy2;
    signal dist_sq;
    dx <== x2 - x1;
    dy <== y2 - y1;
    dx2 <== dx * dx;
    dy2 <== dy * dy;
    dist_sq <== dx2 + dy2;

    component leq = LessEqThan(64);
    leq.in[0] <== dist_sq;
    leq.in[1] <== max_dist_sq;
    leq.out === 1;

    // 3) coordinate range checks
    component rangeX1 = LessThan(32);
    component rangeY1 = LessThan(32);
    component rangeX2 = LessThan(32);
    component rangeY2 = LessThan(32);
    rangeX1.in[0] <== x1; rangeX1.in[1] <== 1000000; rangeX1.out === 1;
    rangeY1.in[0] <== y1; rangeY1.in[1] <== 1000000; rangeY1.out === 1;
    rangeX2.in[0] <== x2; rangeX2.in[1] <== 1000000; rangeX2.out === 1;
    rangeY2.in[0] <== y2; rangeY2.in[1] <== 1000000; rangeY2.out === 1;

    // 4) P4 payload binding (circuit-level)
    component payloadHash = PoseidonHash2();
    payloadHash.a <== payload_lo;
    payloadHash.b <== payload_hi;
    payloadHash.out === payload_commitment;

    // 5) P5 secret binding (circuit-level)
    component secretHash = PoseidonHash2();
    secretHash.a <== secret;
    secretHash.b <== user_id_field;
    secretHash.out === secret_commitment;
}

component main {public [
    hash_prev,
    hash_curr,
    max_dist_sq,
    payload_commitment,
    secret_commitment
]} = TSIPMain();
```

接口说明（论文主口径）：
- 主电路唯一接口为 `TSIPMain`（5 个 public inputs，8 个 witness）。
- 仅含 3 个公开输入的最小连续性教学电路不作为论文“当前系统实现”描述对象。
- 当前工程验证口径：`payload_commitment` 与 `secret_commitment` 为强制约束，不是可选增强。

---

#### 5.5.2 编译和Setup脚本

```bash
#!/bin/bash
# scripts/compile_circuit.sh

set -e

CIRCUIT_NAME="tsip_main"   # 对应 §5.5.1 主电路文件 circuits/tsip_main.circom
CIRCUIT_DIR="circuits"
BUILD_DIR="build"
PTAU_FILE="powersOfTau28_hez_final_20.ptau"  # 从ceremonia下载

echo "===== Step 1: 编译电路 ====="
circom ${CIRCUIT_DIR}/${CIRCUIT_NAME}.circom \
    --r1cs \
    --wasm \
    --sym \
    -o ${BUILD_DIR}

echo "===== Step 2: 查看电路信息 ====="
snarkjs r1cs info ${BUILD_DIR}/${CIRCUIT_NAME}.r1cs

echo "===== Step 3: 生成Groth16 zkey (Phase 1) ====="
snarkjs groth16 setup \
    ${BUILD_DIR}/${CIRCUIT_NAME}.r1cs \
    ${PTAU_FILE} \
    ${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey

echo "===== Step 4: Contribute to Phase 2 ====="
snarkjs zkey contribute \
    ${BUILD_DIR}/${CIRCUIT_NAME}_0000.zkey \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    --name="TSIP Contribution" \
    -v \
    -e="$(openssl rand -hex 32)"

echo "===== Step 5: 导出verification key ====="
snarkjs zkey export verificationkey \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    ${BUILD_DIR}/verification_key.json

echo "===== Step 6: 生成Solidity验证器 (可选) ====="
snarkjs zkey export solidityverifier \
    ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey \
    ${BUILD_DIR}/TSIPVerifier.sol

echo " 电路编译完成!"
echo "   - Proving key: ${BUILD_DIR}/${CIRCUIT_NAME}_final.zkey"
echo "   - Verification key: ${BUILD_DIR}/verification_key.json"
echo "   - WASM: ${BUILD_DIR}/${CIRCUIT_NAME}_js/${CIRCUIT_NAME}.wasm"
```

---

### 5.6 系统集成

#### Docker Compose配置

```yaml
# docker-compose-tsip.yml

version: '3.8'

services:
  # Shuffler (TSIP验证器)
  shuffler:
    build: 
      context: .
      dockerfile: Dockerfile.shuffler
    ports:
      - "5000:5000"
    volumes:
      - ./build:/keys:ro
      - ./logs:/logs
    environment:
      - VKEY_PATH=/keys/verification_key.json
      - LOG_LEVEL=INFO
    networks:
      - tsip-network
  
  # 聚合器A
  aggregator-a:
    build:
      context: .
      dockerfile: Dockerfile.aggregator
    ports:
      - "5001:5001"
    environment:
      - AGGREGATOR_ID=A
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - tsip-network
  
  # 聚合器R
  aggregator-r:
    build:
      context: .
      dockerfile: Dockerfile.aggregator
    ports:
      - "5002:5002"
    environment:
      - AGGREGATOR_ID=R
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
    networks:
      - tsip-network
  
  # Decoder
  decoder:
    build:
      context: .
      dockerfile: Dockerfile.decoder
    ports:
      - "5003:5003"
    environment:
      - AGGREGATOR_A_URL=http://aggregator-a:5001
      - AGGREGATOR_R_URL=http://aggregator-r:5002
    networks:
      - tsip-network
  
  # Redis (缓存)
  redis:
    image: redis:7-alpine
    networks:
      - tsip-network
  
  # 客户端模拟器 (可选)
  client-sim:
    build:
      context: .
      dockerfile: Dockerfile.client
    volumes:
      - ./build:/keys:ro
      - ./data:/data
    environment:
      - PROVING_KEY_PATH=/keys/tsip_main_final.zkey
      - SHUFFLER_URL=http://shuffler:5000
      - NUM_USERS=100
    depends_on:
      - shuffler
    networks:
      - tsip-network

networks:
  tsip-network:
    driver: bridge
```

---

## 小结

本部分实现了TSIP协议的完整代码:

1. 客户端完整实现 (包含proof生成)
2. Shuffler验证器实现
3. 聚合器TSIP扩展
4. Circom电路完整代码
5. Docker集成配置

**下一部分**: 安全性证明和实验评估

---

## 参考实现

完整代码仓库结构:

```
tsip-impl/
├── circuits/
│   ├── tsip_main.circom
│   └── helpers/
├── tsip/
│   ├── client.py
│   ├── shuffler.py
│   ├── aggregator_tsip.py
│   └── types.py
├── scripts/
│   ├── compile_circuit.sh
│   └── run_setup.sh
├── tests/
│   ├── test_circuit.py
│   ├── test_client.py
│   └── test_integration.py
├── docker-compose-tsip.yml
└── README.md
```

## 第六章: 形式化安全分析

### 6.1 威胁模型

#### 6.1.1 系统模型

系统由以下实体组成：
- `N` 个客户端（clients）
- `1` 个 Shuffler
- `2` 个 Aggregator（`A` 与 `R`）
- `1` 个 Decoder

客户端持有位置轨迹；系统按轮次周期性收集客户端上报，并输出差分隐私保护的位置密度热力图。

---

#### 6.1.2 对手模型

**客户端对手：恶意（malicious）**

- 至多 `m < N/2` 个客户端可任意偏离协议。
- 可实施的攻击包括：
  - A1：瞬移注入（boundary teleport）
  - A3：渐进偏移（slow/gradual drift）
  - A2：身份冒用（identity swap）
  - A5：证明重放（replay）
  - A6：伪造证明（forged proof）
- 恶意客户端之间允许串谋（共享信息、协同提交）。

**密码学假设**

攻击者不能破解底层密码学原语：
- Groth16 soundness
- Poseidon 抗碰撞
- Groth16 零知识性质（generic group model）

**服务器对手：诚实但好奇（honest-but-curious）**

- 所有服务器忠实执行协议，但尝试从可见信息中推断个人位置。
- 关键假设：Aggregator `A` 与 `R` 不串谋（至少一方诚实）。
- 若该假设被违反，个人隐私保证退化为仅由公开输出层的 DP 噪声提供保护。

**通信信道**

- 通信采用 authenticated channels（认证信道）。

---

#### 6.1.3 安全目标

**G1: Trajectory Plausibility（轨迹可行性）**

系统以至少 `1 - negl(λ)` 的概率拒绝任何不满足物理运动约束
`distance(loc_t, loc_{t+1}) <= v_max * Δt` 的位置更新。

**G2: Input Privacy（输入隐私）**

服务器只能学习聚合后的位置密度统计，不能恢复任一单个客户端的具体位置。

**G3: Output Privacy（输出隐私）**

公开发布的热力图满足 `ε-DP`（当前实现口径）。

---

#### 6.1.4 明确不保证的范围（Truth Gap）

- **初始注册位置真实性（Enrollment Trust Assumption）**：系统不保证初始注册位置真实性（enrollment 是 trust anchor）。攻击者可从第一轮开始提交平滑但完全虚假的轨迹，后续连续性检查无法发现，因为它们仅保证”链深度 ≥ 1 后的跨轮连续性”。
  - **已实施缓解（P1）**：`TSIP_WARMUP_ROUNDS=N` 机制——新用户前 `N` 轮报告通过 TSIP 验证并建立承诺链，但不转发给 aggregator，使其无法在链深度不足时影响聚合结果。论文口径：TSIP 完整性保证适用于已完成 `TSIP_WARMUP_ROUNDS` 轮 enrollment 的用户。
  - **更强缓解（未实现）**：Out-of-Band (OOB) anchor——注册时通过 Wi-Fi AP 或基站粗定位（城市级别）交叉验证初始位置，正交于主协议。
- **Slow-Drift 攻击（A3）**：系统不完全阻止渐进偏移攻击，但将其成本从”零代价”提升为”需持续维护 `T` 轮连贯假轨迹”。
  - **已实施缓解（P2）**：`TSIP_SLIDING_WINDOW_ROUNDS=K` 机制——服务端检查当前位置与 `K` 轮前位置的累积位移是否超过 `K × v_max × Δt`，将攻击所需偏移时间从”零成本”转为”需 `K × round_sec` 秒的持续投入”。
  - **更强缓解（可扩展）**：滑动窗口可结合 ZK 电路内累积距离约束，在不暴露明文坐标的前提下完成检查（circuit 层 future work）。
- 系统不保证”设备确实位于该位置”（需要额外 Proof-of-Location 机制）。

---

### 6.2 定理1: 连续性完整性保证

#### 6.2.1 定理陈述

**Theorem 1 (Soundness of TSIP under continuity scope)**:

```latex
\begin{theorem}[TSIP Soundness (Continuity Scope)]
Let \Pi_{TSIP} be the TSIP protocol with security parameter \lambda.
For any PPT adversary \mathcal{A} controlling up to t clients, under:
(i)   Groth16 knowledge soundness,
(ii)  Poseidon collision resistance,
(iii) chain depth \ge max(1, TSIP_WARMUP_ROUNDS) (post-enrollment),
(iv)  protocol state machine correctness (no fork/double-submit acceptance),
(v)   Poseidon collision resistance for payload commitment binding (P4),
(vi)  Poseidon collision resistance for secret commitment binding (P5),
the probability of accepting a trajectory with step violation is negligible:

\Pr\left[
\begin{aligned}
& \mathcal{A} \text{ submits trajectory } \tau = \{(x_0,y_0), \ldots, (x_T,y_T)\} \\
& \land \exists i: \|(x_{i+1},y_{i+1}) - (x_i,y_i)\| > v_{max} \cdot \Delta t \\
& \land \text{TSIP continuity checks accept}
\end{aligned}
\right] \leq \frac{T}{2^\lambda} + \epsilon_{hash}
\end{theorem}

其中（作用域说明）:
- T: 时间窗口数量
- λ: 安全参数 (128 bits)
- ε_hash: 哈希碰撞概率（对 Poseidon, ≈ 2^{-128}）
- 本定理保证的是”跨轮连续性完整性”，不等价于”真实世界在场真实性（presence/truthfulness）”
- 条件 (iii) 更新：warmup 期间（链深度 < TSIP_WARMUP_ROUNDS）提交不进入聚合，
  定理保证适用于 warmup 完成后的提交（P1 mitigation）
- 条件 (v)(vi) 在当前主电路中为强制约束（非可选）。
```

---

#### 6.2.2 证明思路

**证明结构**:

```
完整性来源:
1. Groth16的soundness
2. 位置承诺的绑定性
3. P4 payload 语句绑定
4. P5 secret 语句绑定
5. 状态机与链连续性约束

攻击路径分析:
Case 1: 伪造证明 → Groth16 soundness阻断
Case 2: 哈希碰撞 → Poseidon安全性阻断
Case 3: 复用证明 → 承诺链机制阻断
Case 4: proof-payload 拆分替换 → P4阻断
Case 5: 身份冒用（已知坐标）→ P5阻断
```

---

#### 6.2.3 详细证明

**Proof of Theorem 1**:

令事件 `Succ` 表示攻击者在存在至少一处步长违规时仍被系统接受。

我们按攻击路径分解 `Succ`：

- `E1` 伪造 Groth16 证明（不满足电路约束）
- `E2` 伪造/碰撞位置承诺（hash_prev/hash_curr）
- `E3` 复用旧证明但仍匹配当前链状态
- `E4` 替换 payload 但保持 proof 有效（P4）
- `E5` 冒用身份且未知 secret（P5）

分别有：

```text
Pr[E1] ≤ negl(λ)                                      (Groth16 soundness)
Pr[E2] ≤ ε_poseidon                                  (Poseidon 抗碰撞)
Pr[E3] ≤ ε_poseidon + ε_state                        (公开信号绑定 + 状态机)
Pr[E4] ≤ ε_poseidon                                  (payload_commitment 约束)
Pr[E5] ≤ ε_poseidon                                  (secret_commitment 约束)
```

于是由 union bound：

```text
Pr[Succ] ≤ Pr[E1]+Pr[E2]+Pr[E3]+Pr[E4]+Pr[E5]
         ≤ negl(λ) + O(ε_poseidon) + ε_state
```

在实现满足状态机正确性（`ε_state` 可忽略）且 λ=128 的前提下：

```text
Pr[Succ] = negl(λ)
```

对 `T` 轮提交：

```text
Pr[Succ over T rounds] ≤ T · (negl(λ) + O(ε_poseidon) + ε_state)
```

该上界即 Theorem 1 的连续性完整性结论。

**Q.E.D. □**

---

### 6.3 定理2: 公开输出的差分隐私保证

#### 6.3.1 定理陈述（主口径）

**Theorem 2 (Public-Output Differential Privacy of TSIP)**:

```latex
\begin{theorem}[TSIP Public-Output Privacy]
Let $M_{pub}$ denote the released heatmap of TSIP.
Then TSIP satisfies $\epsilon$-DP on $M_{pub}$ with:
\[
\epsilon = \epsilon_{SVT} + \epsilon_{value}
\]
\end{theorem}
```

当前实现默认参数下：

- `ε_SVT = 0.3`
- `ε_value = 0.7`
- `ε_total = 1.0`

说明：

- 这里的 DP 保证只针对**最终公开热力图输出**。
- TSIP 验证步骤（accept/reject）属于系统内部过滤信号，不并入主 DP 预算（见 6.3.2）。

---

#### 6.3.2 边界与泄露分解（Who Learns What）

为避免 overclaim，隐私边界拆分如下：

1. Public output（对外发布）
   - 最终热力图（`reconstruct + dp/latest` 结果）
   - 适用主定理中的 DP 保证

2. Internal signals（内部可见）
   - Shuffler 的 `accept/reject`
   - 承诺链状态（`prev/curr commitment`）
   - 提交时序元数据（`round_id/window_id`）
   - 这些属于 trusted infrastructure 侧可见信息，不并入 public-output DP 预算

3. 语义澄清
   - TSIP 验证可以视为“DP 发布前的完整性过滤器”；
   - 它提供完整性约束，不等价于对外发布机制本身。

4. DP 术语冻结（论文写作强制项）
   - adjacency：`user-level`（相邻数据集仅相差一个用户报告）
   - sensitivity：由每用户贡献上界（Top-K + clipping）导出
   - SVT：引用标准 sparse vector 机制定理，不使用“黑盒经验口径”
   - 公开主张仅覆盖 public-output，不外推到 trusted infrastructure 内部可见信号

---

#### 6.3.3 主定理证明（组合定理）

**Proof of Theorem 2**:

**Step 1: 完整性过滤与聚合前阶段**

```
- Top-K、dummy、proof 构造属于客户端本地处理；
- TSIP 验证是系统内部过滤，不直接形成公开发布结果；
- 聚合前阶段不计入 public-output DP 预算。
```

**Step 2: 安全聚合阶段**

```
- A/R 双聚合器仅见秘密份额；
- 在至少一方诚实假设下，单方不可恢复单用户位置；
- 该阶段不增加 public-output DP 支出。
```

**Step 3: Decoder 的 DP 释放阶段**

```
SVT:
  - 消耗 ε_SVT = 0.3

Value noise:
  - 对发布计数加噪
  - 消耗 ε_value = 0.7

小计:
  ε_decoder = ε_SVT + ε_value = 1.0
```

**Step 4: 顺序组合**

```
ε_total = ε_SVT + ε_value = 1.0
```

**Step 5: 后处理不变性**

```
对已发布 DP 结果的可视化与查询属于后处理，不增加隐私泄露。
```

**Q.E.D. □**

---

#### 6.3.4 可选随机化验证（实验项，不是主口径）

为研究完整性-误判权衡，系统保留“随机化验证”实验开关：

- 实现位置：`services/shuffler/app.py`
- 配置项（默认关闭）：
  - `TSIP_VERIFY_DP_ENABLE`
  - `TSIP_VERIFY_EPSILON`
  - `TSIP_VERIFY_NOISY_THRESHOLD`
  - `TSIP_VERIFY_DP_SEED`
- 运行观测：
  - `/health` 中 `tsip_verify_dp_enable / tsip_verify_epsilon / tsip_verify_calls / tsip_verify_spent`

注意：

- 该机制用于附录或扩展实验（验证随机化策略），
- 不纳入论文主结果中的 DP 预算组合公式。

---

**多 Shuffler 门限转发与 payload 绑定（k-of-t）**

- 实现位置：
  - `services/shuffler/app.py`：新增 `/committee/attest`，并在 `ingestA/ingestR` 中收集门限签名
  - `services/aggregator_a/app.py`、`services/aggregator_r/app.py`：新增门限验签守门
  - `common/committee.py`：统一签名/验签与 payload 规范
- 机制（分层）：
  - 基础门控层（已实现）：
    - 每个 Shuffler 对 `(channel, round_id, submission_id, idx/val digest)` 生成 HMAC/MAC
    - 聚合器仅接收“有效 MAC 数量 >= `SHUFFLER_COMMITTEE_THRESHOLD`”的提交
    - 语义注意：HMAC 是 shared-secret MAC，不是可转移数字签名；不可等同于强门限签名
  - 绑定增强层（已落地，持续增强）：
    - 已实现：`payload_digest` 进入 TSIP 链承诺并在服务端重算校验，阻断“合法 proof + 替换 payload”拆分攻击
    - 可选增强：将 committee attestation 摘要升级为 `(channel, round_id, submission_id, user_id, window_id, payload_digest, proof_digest, prev_chain, curr_chain)`
  - 签名增强层（建议，论文增强）：
    - 将 HMAC 层替换为 Ed25519（或 BLS）数字签名；
    - 若主张“门限签名”语义，则需使用真正 threshold signature 方案
- 关键配置：
  - `SHUFFLER_COMMITTEE_ENABLE`
  - `SHUFFLER_COMMITTEE_THRESHOLD`
  - `SHUFFLER_COMMITTEE_ID`、`SHUFFLER_COMMITTEE_SIGN_SECRET`
  - `SHUFFLER_COMMITTEE_PEERS`
  - `SHUFFLER_COMMITTEE_KEYS`（聚合器侧，格式 `s1:sec1,s2:sec2,s3:sec3`）
  - 本地三节点联调可用：`docker compose --profile committee up -d`
- 安全语义：
  - 在 `k=3,t=2` 时，可声明“容忍 1 个恶意/失效 Shuffler 后仍可维持转发门限策略”
  - 基础门控层主要防单点绕过；但其密码学语义是 MAC 门控，不是强可转移签名
  - 绑定增强层进一步防“proof 通过后 payload 被替换”的拆分攻击
  - 仍需结合部署隔离、审计日志与状态机规则（fork/double-submit）共同生效。

---

**首轮（t=0）安全边界修订（2026-03-25）**

- 问题本质：TSIP 的时空连续性证明依赖“上一承诺已存在”，因此严格来说定理只对链深度 `>=1` 的提交成立。
- 修订后的安全声明：
  - 不再宣称“所有提交（包含首轮）都满足同等时空完整性保证”；
  - 明确声明“TSIP 完整性保证适用于已完成 enrollment 的用户提交（即有历史承诺链）”。
- 协议化解决（非 warm-up 工程绕过）：
  - 将首轮提交定义为 **enrollment/anchor** 阶段；
  - enrollment 仅用于建立 `H_0` 承诺锚点，不直接进入聚合；
  - 只有从 `H_0 -> H_1` 开始、具备连续性证明的提交才可进入最终聚合。
- 工程开关：
  - `TSIP_BOOTSTRAP_POLICY=legacy_accept`：旧行为（首轮可聚合）
  - `TSIP_BOOTSTRAP_POLICY=enroll_only`：严格行为（首轮仅锚定、不聚合）
- 实现位置：
  - `services/shuffler/app.py` 中 `ingestA/ingestR` 的 `bootstrap_held` 逻辑与 `/health` 可观测字段。

---

#### 6.3.5 说明

本节与 §6.3.3 证明逻辑等价。为避免重复，论文主文仅保留 §6.3.3 的定理与证明。

---

### 6.4 定理3: 零知识性

#### 6.4.1 定理陈述

**Theorem 3 (Zero-Knowledge Property)**:

```latex
\begin{theorem}[TSIP Zero-Knowledge]
The TSIP proof system satisfies computational zero-knowledge.
Specifically, for any PPT verifier V*, there exists a PPT 
simulator S such that:

\{View_{V^*}(x, w)\} \approx_c \{S(x)\}

where:
- x: public inputs (hash_prev, hash_curr, max_dist_sq,
                    payload_commitment, secret_commitment)
- w: witness (x1, y1, x2, y2, payload_lo, payload_hi, secret, user_id_field)
- View: verifier's view (包括证明和所有交互)
\end{theorem}
```

---

#### 6.4.2 证明框架

**零知识性来源**:

```
TSIP的ZK依赖于Groth16的ZK性质

关键: Groth16中的随机盲化因子 r, s
  proof_A = α·g + Σaᵢ·Lᵢ(τ)·g + r·δ·g
  proof_B = β·g + Σaᵢ·Rᵢ(τ)·g + s·δ·g
  proof_C = ... + s·A + r·B - r·s·δ·g
  
  即使知道proof_A, proof_B, proof_C,
  由于r, s的随机性,无法反推witness {aᵢ}
```

---

#### 6.4.3 模拟器构造

**Simulator S(x)**:

```python
def simulator(public_inputs):
    """
    零知识模拟器: 不知道witness的情况下生成"看起来真实"的证明
    
    Args:
        public_inputs: (hash_prev, hash_curr, max_dist_sq,
                        payload_commitment, secret_commitment)
    
    Returns:
        simulated_proof: 与真实proof计算不可区分
    """
    # 1. 随机采样"假"的witness
    fake_witness = {
        "x1": random_field_element(),
        "y1": random_field_element(),
        "x2": random_field_element(),
        "y2": random_field_element(),
        "payload_lo": random_field_element(),
        "payload_hi": random_field_element(),
        "secret": random_field_element(),
        "user_id_field": random_field_element(),
    }
    
    # 2. 使用CRS的trapdoor生成proof
    # (在真实系统中,trapdoor已被销毁)
    # (这里只是理论分析,证明ZK性质存在)
    
    # 生成随机群元素
    simulated_proof = {
        "pi_a": random_G1_point(),
        "pi_b": random_G2_point(),
        "pi_c": random_G1_point()
    }
    
    # 3. 关键: 调整proof使其通过验证等式
    # (利用trapdoor α, β, γ, δ)
    # adjust_proof_with_trapdoor(simulated_proof, public_inputs, trapdoor)
    
    return simulated_proof

# 不可区分性证明:
# 对任意PPT区分器D:
# |Pr[D(real_proof) = 1] - Pr[D(simulated_proof) = 1]| ≤ negl(λ)
```

---

#### 6.4.4 完整证明

**Proof of Theorem 3**:

我们构造模拟器S并证明其输出与真实proof不可区分

**模拟器S的工作流程**:

```
输入: public_inputs = (hash_prev, hash_curr, max_dist_sq,
                      payload_commitment, secret_commitment)

Step 1: 不使用witness,直接生成"看起来随机"的proof
  
  由于Groth16的proof是群元素:
  proof = (A, B, C) ∈ G₁ × G₂ × G₁
  
  S采样:
  A' ← random_G1()
  B' ← random_G2()
  C' ← random_G1()

Step 2: 使用CRS的trapdoor调整proof
  
  (在Setup阶段,trapdoor = (α, β, γ, δ, τ)已被销毁)
  (但在理论分析中,我们假设S可以访问trapdoor)
  
  S计算:
  A = A' + correction_A(public_inputs, trapdoor)
  B = B' + correction_B(public_inputs, trapdoor)
  C = C' + correction_C(public_inputs, trapdoor)
  
  使得配对等式成立:
  e(A, B) = e(α·g₁, β·g₂) · e(L_pub·g₁, γ·g₂) · e(C, δ·g₂)

Step 3: 输出调整后的proof
```

**不可区分性论证**:

```
考虑两个分布:
- Real: 真实proof,由诚实Prover用witness生成
- Simulated: 模拟proof,由S不用witness生成

关键观察:
  在Groth16中,真实proof包含随机盲化因子(r, s)
  
  Real proof:
  A = α·g + [witness related terms] + r·δ·g
                                      ↑
                                   均匀随机
  
  由于r是均匀随机的,A在G₁中的分布也是均匀随机的
  (除了满足配对等式的约束)

  Simulated proof:
  A' 也是从G₁均匀随机采样
  然后调整为满足配对等式
  
  ∴ Real和Simulated的分布相同(在G₁上的均匀分布)

形式化:
  对任意PPT区分器D:
  
  |Pr[D(Real) = 1] - Pr[D(Sim) = 1]|
  ≤ negl(λ)  (在 pairing generic group model 下，见 [Groth16] Theorem 1)
```

**Q.E.D. □**

---

### 6.5 通信效率分析（工程口径）

> 说明：本节提供工程通信效率对比与实测开销，不作为形式化强定理。

#### 6.5.1 每次提交的通信构成

```
per-submission 主要开销:
- zk proof（Groth16）: 约 0.70~0.81 KB（实测区间）
- 承诺链字段: prev/curr commitment 与链状态元数据
- 主电路公开输入: 5 个 field elements（相较最小连续性电路多 2 个）
  - 新增: payload_commitment, secret_commitment
  - 增量开销: 2 × 32B = 64B
- 稀疏索引与份额: idx/val 提交

合计: 当前实现约 1KB 级（与配置和序列化格式有关）；
相较仅含 3 个公开输入的最小连续性电路，纯公开输入增量约 64B/提交。
```

#### 6.5.2 对比口径（用于实验章节）

```
TSIP:
  通信成本与 domain size 弱相关（使用稀疏 top-k 表示）
  不随全域 D 线性膨胀到 dense 向量级别

Range-proof/inner-product 型基线:
  通信开销可随维度显著增长
  在大域场景下工程代价更高
```

#### 6.5.3 当前主张边界

```
当前文档只主张“工程上通信效率可接受且优于 dense 方案”。
不主张“已完成严格信息论最优下界证明”。
```

---

### 6.6 安全性总结

| 定理 / 机制       | 性质                 | 保证                                                                           | 依赖假设                                        |
| ----------------- | -------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------- |
| **Theorem 1**     | Soundness            | 连续性作用域内，违规步长通过概率可忽略                                         | Groth16 soundness, Poseidon 抗碰撞              |
| **Theorem 2**     | Privacy              | ε-DP（当前主口径下 ε=1.0）                                                      | DP 组合定理                                     |
| **Theorem 3**     | Zero-Knowledge       | 证明不泄露 witness                                                             | Pairing generic group model（Groth16 ZK）      |
| **工程分析**      | Communication        | 1KB 级每次提交（实测口径）                                                     | 稀疏表示 + 实测统计                             |
| **P1 Warmup**     | Enrollment Hardening | 链深度 < N 的提交不进入聚合，防止首轮虚假位置直接影响结果                      | `TSIP_WARMUP_ROUNDS` 配置，服务端状态机正确性   |
| **P2 Sliding Win**| Drift Cost Elevation | 滑动窗口内累积位移超限则拒绝，攻击成本从零升为 ∝ K × round_sec               | 客户端诚实上报坐标；ZK 级无需额外假设（future） |
| **P3 Trust Model**| Collusion Degradation| 两 aggregator 串谋时隐私退化为 DP 输出保护（不失完整性）                       | DP 保证独立于 aggregator 诚实性                 |
| **P4 Payload Bind**| Payload Integrity   | 电路约束 `Poseidon(payload_lo,payload_hi)==payload_commitment`，proof 与 payload 不可分离替换 | Poseidon 抗碰撞                                 |
| **P5 Secret Bind** | Identity Binding    | 电路约束 `Poseidon(secret,user_id_field)==secret_commitment`，即使攻击者知道受害者坐标也无法伪造链 | Poseidon 抗碰撞                                 |

---

## 第七章: 攻击防御分析

### 7.1 跨时间窗口攻击（A2: 身份冒用）

#### 攻击描述

```
攻击者 Alice 和 Bob 串谋:
t=0: Alice 在东京, Bob 在大阪
t=1: 交换 GPS 坐标后, Alice 用 Bob 的 user_id 提交"在大阪"的位置
目的: 让 Bob 在聚合中被计为在大阪，污染热力图
```

#### 防御层次（多层，由浅至深）

```
【第1层】物理连续性约束（原有机制）
 若攻击路径需要大位移跳变，距离约束触发拒绝。
   （若 Alice/Bob 物理距离 > v_max×Δt，ZK 证明生成失败）

【第2层】承诺链一致性（原有机制）
 shuffler 状态机要求 prev_loc_commitment 与上轮存储状态吻合。
   Alice 无法接续 Bob 的合法承诺链，因为她没有 Bob 先前提交后
   服务端存储的链状态。

【第3层 · P5 新增】per-user 隐藏 Secret 绑定
 启用 TSIP_SECRET_BINDING_ENABLE=1 后：
   - Bob 在首次注册时生成 user_secret（客户端本地，从不上传）
   - 链承诺计算变为：
       curr_chain = MiMC(prev_chain, curr_loc, t, w, HMAC(secret, user_id))
   - 即使 Alice 知道 Bob 的坐标，也无法构造与 Bob 服务端存储的
     secret_commitment 一致的链，因为她不知道 Bob 的 secret。
   - 密码学依赖：HMAC-SHA-256 不可伪造性

【第4层 · P4 新增】Proof-Payload 绑定
 启用 TSIP_PAYLOAD_BINDING_ENABLE=1 后：
   - SHA-256(sorted cell indices) 折叠进链承诺
   - 生成证明时绑定的 idx 与最终提交给 aggregator 的 idx 必须一致
   - 防止攻击者复用合法证明并替换 payload 为恶意数据

【ZK 级增强（主电路）】
 在电路内证明 Poseidon(secret, user_id_field) == secret_commitment
   密码学保证升级为 ZK Soundness 级别，无需信任客户端本地计算。
   需重新编译电路并执行新的 trusted setup。
```

#### 实验验证口径

```python
def test_identity_swap_attack():
    # Alice 在东京，Bob 在大阪（相距 499km）
    bob_secret = "bob_hidden_secret_never_shared"
    bob_secret_commitment = HMAC(bob_secret, "bob_user_id")  # 服务端注册时存储

    # t=1: Alice 知道 Bob 的当前坐标（大阪），尝试用 Bob 的 user_id 提交
    alice_chain = compute_chain_commitment(
        prev_chain=bob_prev_chain,   # Alice 无法获取；即使获取，
        curr_loc=osaka_commitment,   # secret_commitment 不匹配：
        secret_commitment=HMAC("alice_wrong_secret", "bob_user_id"),
    )
    # shuffler 比对 stored secret_commitment != Alice 提供的值 → 拒绝
    assert verify_chain(alice_chain, stored=bob_secret_commitment) == False  # ✓
```

---

### 7.2 Sybil + 瞬移攻击

#### 攻击描述

```
攻击者创建1000个虚假账户:
t=0: 分散在城市各处(每个位置都合法)
t=1: 全部"瞬移"到商场A
目的: 虚增商场A的热度
```

#### TSIP防御

```
 每个账户独立验证:
  - 每个账户都有独立的承诺链
  - 如果任何账户"瞬移",其proof验证失败

 成本提升结论:
  - 一步瞬移会被高概率拒绝
  - 攻击者若改为渐进漂移,需要跨多轮持续投入账户与时间成本
  - 论文主张应表述为"attack-cost elevation",而非"一切恶意轨迹绝对阻断"
```

#### 实验验证

```python
def test_sybil_teleport_attack():
    num_sybils = 1000
    
    # t=0: Sybils分散在各处
    sybil_locs_0 = [
        Location(x=random()*1000000, y=random()*1000000, t=0)
        for _ in range(num_sybils)
    ]
    
    # 生成承诺
    commitments = [Hash(loc) for loc in sybil_locs_0]
    
    # t=1: 全部瞬移到(0, 0)
    target = Location(x=0, y=0, t=300)
    
    rejected = 0
    for i in range(num_sybils):
        proof = generate_tsip_proof(sybil_locs_0[i], target)
        if not verify_proof(proof):
            rejected += 1
    
    # 预期: 在该攻击设置中绝大多数被拒绝
    assert rejected > 0.95 * num_sybils
    
    # Shuffler检测到异常
    rejection_rate = rejected / num_sybils
    assert rejection_rate > 0.1  # 触发警报阈值
```

---

### 7.3 时序相关攻击

#### 攻击描述

```
攻击者观察热力图的时序模式,
尝试关联同一用户在不同时间的提交
```

#### TSIP防御

```
 条件化的标识保护:
  - 当系统启用 window 作用域 pseudonym 时,
    可降低跨窗口直接关联能力
  - 当采用 stable user scope 时,服务器可关联同一 user_id;
    该配置主要服务于链式完整性与可复现实验

 DP噪声:
  - 最终输出添加DP噪声
  - 模糊时序相关性

 承诺不泄露位置:
  - 服务器只看到Hash(location)
  - 无法推断具体位置
```

---

### 7.4 服务器串谋攻击（P3: 服务器信任模型）

#### 攻击描述

```
S_A 和 S_R 串谋，尝试重构用户的明文位置或共同篡改聚合结果。
典型场景：两个 aggregator 归同一组织管理，实际上不独立。
```

#### 现有防御层次

```
 秘密分享（原有机制）:
  - 上报值被分成 share_A 和 share_R 两份
  - 单个 aggregator 无法独立重构明文
  - 若 S_A 和 S_R 串谋 → 可以重构明文位置（隐私失效）

 威胁模型假设：至少 1 个 aggregator 诚实（honest-but-curious）
  - 若该假设被违反，个人隐私保证退化为：
    - TSIP 完整性仍然保持（ZK 证明不依赖 aggregator 诚实性）
    - 公开热力图仍满足 ε-DP 保证（输出层 DP 独立于 aggregator）
    - 但 individual 位置可被串谋方重构

【P3 实施】TSIP_MIN_AGGREGATORS 配置：
  - 通过 committee signature 门控，要求至少 TSIP_MIN_AGGREGATORS 个
    独立 shuffler/aggregator 签名才放行上报
  - 设为 2 可防单点 aggregator 伪造，但无法防两者串谋
  - 当 TSIP_MIN_AGGREGATORS=2 时，单一被攻破的 aggregator 无法单独
    接受虚假报告
```

#### 串谋降级分析（P3 论文口径）

| 场景                         | 完整性保证     | 隐私保证                          |
| ---------------------------- | -------------- | --------------------------------- |
| 两 aggregator 均诚实          | 完整        | 秘密分享 + DP                  |
| 一 aggregator 被攻破          | 完整        | 另一方保持秘密分享              |
| 两 aggregator 串谋            | 完整（ZK）  | 退化为 DP 输出层保护           |
| 两 aggregator + shuffler 串谋 | ❌ 无法保证    | ❌ 无法保证                       |

#### 改进方案（Future Work）

```
方案A: 阈值秘密分享 (t-out-of-n)
  - 将位置分成 n=5 份，需 t=3 份才能重构
  - 即使 2 个 aggregator 串谋，仍安全
  - 代价：增加通信开销和服务器数量

方案B: TEE (可信执行环境)
  - Aggregator 运行在 Intel SGX / ARM TrustZone 内
  - 串谋无法读取明文，即使操作系统被攻破
  - 代价：硬件依赖，部署复杂

方案C: MPC (多方安全计算)
  - 将聚合计算替换为 MPC 协议
  - 信任模型降为计算假设
  - 代价：高通信开销，工程复杂度大
```

---

### 7.5 渐进偏移攻击（A3）与滑动窗口缓解（P2）

#### 攻击描述与根本局限

```
TSIP 仅验证相邻两步的距离是否在 v_max × Δt 内（单步约束）。
攻击者每步移动 v_max×Δt - ε，经过 k 轮后可累积偏移：
  drift = k × (v_max × Δt - ε) ≈ k × v_max × Δt

实验结果：
  - 三档 bias（0.30/0.60/0.90）下 malicious_reject_rate = 0.0%
  - 30 轮后平均累积偏移 ≈ 2.57–2.71 km
  → 单步约束对 slow poisoning 完全无效（0% 拦截）

论文口径：这是一个已知局限（limitation），TSIP 不宣称消除 A3，
而是将攻击成本从"零"提升为"需持续 T 轮维护连贯假轨迹"。
```

#### P2 滑动窗口约束（已实施）

```
核心思路：不仅检查 step_i → step_{i+1}，
          还检查 step_i → step_{i+k} 的累积位移是否合理。

实现（TSIP_SLIDING_WINDOW_ROUNDS=K）：
  - 客户端在 TSIP payload 中附带 curr_x / curr_y
  - 服务端维护长度为 K 的位置历史 position_history
  - 每轮验证：
      dist(pos_now, pos_{K_rounds_ago})² ≤ (K × v_max × Δt)²
    若超出则拒绝

攻击成本分析（time-to-poison）：
  若攻击者想在 K 轮内漂移到距离 d_target 的目标区域：
    需要满足：d_target ≤ K × v_max × Δt
  即合法的最大偏移 = K × 6600m（以 v_max=110m/s, Δt=60s 为例）
  
  例：K=30 时，允许最大累积位移 = 30 × 6600m = 198km
       这不是"检测"而是"上界约束"：超过 198km 的偏移会被拒绝，
       低于 198km 的偏移不受额外限制（仍是局限）。
  
  更小的 K 值可收紧约束：K=10 → 最大偏移 66km；K=3 → 19.8km。
  但过小的 K 会影响合法用户的长距离出行（误报率上升）。

隐私考虑：
  当前实现要求客户端上报明文 curr_x/curr_y（服务端可见用户位置）。
  完全隐私保护版本需 ZK 电路扩展（在证明内部验证滑动窗口约束，
  无需向服务端暴露坐标），已在主电路设计中
  预留了框架，具体实现为 future work。
```

#### 量化攻击成本（论文写作参考）

```
对于目标偏移 D（米），滑动窗口约束为：
  time_to_poison ≥ ceil(D / (v_max × Δt)) 轮

以 v_max=110m/s，Δt=60s，v_max×Δt=6600m 为例：

| 目标偏移  | 无滑动窗口   | K=3        | K=10       | K=30       |
| --------- | ------------ | ---------- | ---------- | ---------- |
| 1 km      | 1 轮（立即） | 1 轮       | 1 轮       | 1 轮       |
| 10 km     | 2 轮（立即） | 2 轮       | 2 轮       | 2 轮       |
| 20 km     | 4 轮         | 4 轮       | 4 轮 | 4 轮 |
| 60 km     | 10 轮        | ❌拒绝(3K) | 10 轮      | 10 轮 |
| 200 km    | 31 轮        | ❌拒绝     | ❌拒绝(10K)| 31 轮 |
| 300 km    | 46 轮        | ❌         | ❌         | ❌拒绝(30K)|

（❌ 表示超出滑动窗口上界，提交被拒绝； 表示在上界内，不被拒绝）
```

---

### 7.6 Proof-Payload 绑定（P4）

#### 攻击描述

```
攻击者预先生成一批合法的 TSIP ZK 证明（位置连续性有效），
然后在提交时替换 payload（idx/val）为指向任意伪造热力图的数据。
原因：最小连续性电路仅证明 prev_loc → curr_loc 连续性，
      不约束上报的 cell indices 与位置之间的关系。
```

#### P4 机制

```text
电路级主口径：
  1. 客户端将 payload 摘要拆分为 payload_lo / payload_hi（私有 witness）
  2. 电路强制约束：
       Poseidon(payload_lo, payload_hi) == payload_commitment（公开输入）
  3. 服务端校验：
       public_signals[3] 与提交 payload 对应的 commitment 一致

安全效果：
  - proof 与 payload 属于同一语句，无法“先生成合法 proof，再替换 payload”
  - 攻击者若篡改 payload，需同时伪造满足约束的 proof，成功概率受
    Groth16 soundness + Poseidon 抗碰撞限制

作用域边界：
  - P4 保证的是 proof/payload 一致性
  - 不单独保证 payload 的语义真实性（例如 cell 与物理位置一致性）
```

---

### 7.7 per-user 隐藏 Secret 绑定（P5）

#### 攻击场景

```
A2 身份冒用的强化版：
攻击者 Alice 通过某种方式（侧信道、社工等）获知受害者 Bob 的实时 GPS
坐标，然后冒充 Bob 的 user_id 提交，构造与 Bob 位置一致的连续轨迹。
原版系统仅依赖"攻击者不知道对方坐标"作为 A2 防御——这不是密码学保证。
```

#### P5 机制

```text
电路级主口径：
  1. 每个用户在注册阶段绑定 secret_commitment（服务端保存）
  2. 每轮证明使用私有 witness：secret, user_id_field
  3. 电路强制约束：
       Poseidon(secret, user_id_field) == secret_commitment（公开输入）
  4. 服务端验证：
       public_signals[4] 与该用户已登记 commitment 一致

安全效果：
  - 即使攻击者知道受害者坐标，也无法在未知 secret 的情况下构造有效证明
  - A2 身份冒用从“依赖攻击者不知道坐标”提升为“依赖密码学不可伪造”

作用域边界：
  - P5 解决的是“同一 user_id 的秘密绑定”
  - 不覆盖设备被接管、注册源真实性等正交问题（见 Truth Gap）
```

---

## 小结

本部分完成了 TSIP 的形式化安全分析及五项工程级安全增强：

1. 4 个核心定理及其证明（Theorem 1–3 + 通信分析）
2. 主要攻击场景的防御分析（A1/A2/A3/A5/A6 + 服务器串谋）
3. **P1 Enrollment Warmup**：新用户前 N 轮不进入聚合，缓解首轮虚假注册
4. **P2 Sliding Window**：滑动窗口累积位移约束，将 A3 攻击成本量化
5. **P3 Trust Model**：明确串谋降级场景，文档化 TEE/MPC 改进路径
6. **P4 Payload Binding**：`Poseidon(payload_lo, payload_hi) = payload_commitment`，proof 与 payload 不可分离
7. **P5 Secret Binding**：`Poseidon(secret, user_id_field) = secret_commitment`，同一身份的秘密绑定可验证
8. **TSIP 主电路**：P4+P5 的 ZK 电路级增强方案（已完成 trusted setup 与验证）

**下一部分**: 实验评估与论文撰写指南

---

## 参考文献

[Groth16] Jens Groth. "On the Size of Pairing-Based Non-Interactive Arguments". EUROCRYPT 2016.

[Dwork06] Cynthia Dwork et al. "Calibrating Noise to Sensitivity in Private Data Analysis". TCC 2006.

[Grassi+21] Lorenzo Grassi et al. "Poseidon: A New Hash Function for Zero-Knowledge Proof Systems". USENIX Security 2021.

[MiMC16] Martin R. Albrecht et al. "MiMC: Efficient Encryption and Cryptographic Hashing with Minimal Multiplicative Complexity". ASIACRYPT 2016.

## 第八章: 实验评估方案

### 8.1 实验目标

#### 核心问题

```
Q1: TSIP是否有效阻止跨时间窗口攻击?
Q2: TSIP的性能开销是否可接受?
Q3: TSIP与现有方案相比有何优势?
Q4: TSIP在真实数据上的效果如何?
```

---

### 8.2 数据集

#### 8.2.1 真实数据集

**GeoLife (微软研究院)**

```
规模: 
- 182 用户
- 17,621 条轨迹
- 24,876,978 个GPS点
- 时间跨度: 2007-2012

特点:
- 真实用户行为
- 包含多种交通方式(步行/驾车/公交)
- 适合验证算法正确性

下载: 
https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/

预处理:
- 划分为5分钟时间窗口
- 映射到100m×100m网格
- 计算停留时间
```

**T-Drive (北京出租车轨迹)**

```
规模:
- 10,357 辆出租车
- 15,000,000+ GPS点
- 采样频率: 177秒
- 覆盖范围: 北京市区

特点:
- 大规模数据
- 适合测试可扩展性
- 真实城市交通模式

下载:
https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/
```

---

#### 8.2.2 合成数据生成

```python
# experiments/synthetic_data.py

import numpy as np
from typing import List, Tuple

class SyntheticTrajectoryGenerator:
    """生成符合真实分布的合成轨迹"""
    
    def __init__(self, city_bounds: Tuple[float, float, float, float]):
        """
        Args:
            city_bounds: (x_min, y_min, x_max, y_max)
        """
        self.bounds = city_bounds
        
        # 热点区域(模拟商业区/居民区)
        self.hotspots = self.generate_hotspots(num=100)
    
    def generate_hotspots(self, num: int) -> List[Tuple[float, float]]:
        """生成幂律分布的热点"""
        hotspots = []
        for i in range(num):
            # 幂律分布: 更多热点集中在市中心
            weight = 1.0 / (i + 1) ** 0.5
            angle = np.random.uniform(0, 2*np.pi)
            radius = np.random.exponential(scale=5000) * weight
            
            x = self.bounds[0] + self.bounds[2]/2 + radius * np.cos(angle)
            y = self.bounds[1] + self.bounds[3]/2 + radius * np.sin(angle)
            
            hotspots.append((x, y))
        
        return hotspots
    
    def generate_user_trajectory(self, 
                                 user_id: int, 
                                 num_windows: int = 288) -> List[Location]:
        """
        生成单个用户的轨迹
        
        模式:
        - 00:00-08:00: 在家 (随机游走)
        - 08:00-09:00: 通勤 (家→公司)
        - 09:00-18:00: 在公司 (小范围活动)
        - 18:00-19:00: 通勤 (公司→家)
        - 19:00-24:00: 娱乐 (访问热点)
        """
        # 采样家和公司位置
        home = random.choice(self.hotspots)
        work = random.choice(self.hotspots)
        
        trajectory = []
        current_loc = home
        
        for window_id in range(num_windows):
            hour = (window_id * 5 / 60) % 24  # 当前小时
            
            if 0 <= hour < 8:  # 在家
                next_loc = self.random_walk(current_loc, radius=500)
            
            elif 8 <= hour < 9:  # 通勤到公司
                next_loc = self.interpolate(current_loc, work, steps=12)
            
            elif 9 <= hour < 18:  # 在公司
                next_loc = self.random_walk(work, radius=300)
            
            elif 18 <= hour < 19:  # 通勤回家
                next_loc = self.interpolate(current_loc, home, steps=12)
            
            else:  # 19-24: 娱乐
                if np.random.random() < 0.1:  # 10%概率去热点
                    target = random.choice(self.hotspots)
                    next_loc = self.interpolate(current_loc, target, steps=6)
                else:
                    next_loc = self.random_walk(home, radius=2000)
            
            # 确保满足物理约束
            distance = euclidean(current_loc, next_loc)
            max_dist = 100 * 300  # 100 m/s × 300s = 30km
            if distance > max_dist:
                next_loc = self.clamp_distance(current_loc, next_loc, max_dist)
            
            trajectory.append(Location(
                x=next_loc[0],
                y=next_loc[1],
                timestamp=window_id * 300,
                cell_id=xy_to_cell_id(next_loc[0], next_loc[1]),
                dwell_time=300
            ))
            
            current_loc = next_loc
        
        return trajectory
    
    def random_walk(self, center: Tuple[float, float], radius: float):
        """在中心点附近随机游走"""
        angle = np.random.uniform(0, 2*np.pi)
        dist = np.random.exponential(scale=radius/3)
        dist = min(dist, radius)
        
        x = center[0] + dist * np.cos(angle)
        y = center[1] + dist * np.sin(angle)
        
        return (x, y)
    
    def interpolate(self, start, end, steps: int):
        """线性插值"""
        t = 1.0 / steps
        x = start[0] + (end[0] - start[0]) * t
        y = start[1] + (end[1] - start[1]) * t
        return (x, y)
    
    def clamp_distance(self, start, end, max_dist: float):
        """将终点限制在最大距离内"""
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = np.sqrt(dx**2 + dy**2)
        
        if dist <= max_dist:
            return end
        
        scale = max_dist / dist
        return (start[0] + dx*scale, start[1] + dy*scale)

# 使用示例
generator = SyntheticTrajectoryGenerator(
    city_bounds=(0, 0, 1000000, 1000000)  # 1000km × 1000km
)

# 生成100个用户,每人24小时
trajectories = [
    generator.generate_user_trajectory(user_id=i, num_windows=288)
    for i in range(100)
]
```

---

#### 8.2.3 恶意轨迹生成器

```python
# experiments/attack_generator.py

class MaliciousTrajectoryGenerator:
    """生成各种攻击轨迹"""
    
    def generate_teleport_attack(self, distance_ratio=2.0):
        """
        生成瞬移攻击
        
        Args:
            distance_ratio: 违规倍数 (2.0表示瞬移距离是合法距离的2倍)
        """
        trajectory = []
        
        # t=0: 在东京
        loc_0 = Location(x=0, y=0, t=0, cell_id=0, dwell_time=300)
        trajectory.append(loc_0)
        
        # t=1: 瞬移到大阪 (500km外)
        illegal_distance = 100 * 300 * distance_ratio  # 60km (超过30km限制)
        loc_1 = Location(
            x=illegal_distance, 
            y=0, 
            t=300, 
            cell_id=xy_to_cell_id(illegal_distance, 0), 
            dwell_time=300
        )
        trajectory.append(loc_1)
        
        return trajectory
    
    def generate_identity_swap_attack(self, alice_traj, bob_traj, swap_time=5):
        """
        生成身份交换攻击
        
        Args:
            alice_traj: Alice的正常轨迹
            bob_traj: Bob的正常轨迹
            swap_time: 在第几个时间窗口交换
        """
        # Alice的轨迹: 前5个窗口正常,之后变成Bob的轨迹
        alice_malicious = (
            alice_traj[:swap_time] + 
            bob_traj[swap_time:]
        )
        
        # Bob的轨迹: 前5个窗口正常,之后变成Alice的轨迹
        bob_malicious = (
            bob_traj[:swap_time] + 
            alice_traj[swap_time:]
        )
        
        return alice_malicious, bob_malicious
    
    def generate_sybil_attack(self, num_sybils=1000, target_location=(0, 0)):
        """
        生成Sybil攻击
        
        策略:
        - t=0: 分散在各处
        - t=1: 全部瞬移到目标位置
        """
        sybil_trajectories = []
        
        for i in range(num_sybils):
            # t=0: 随机位置
            start_x = np.random.uniform(0, 1000000)
            start_y = np.random.uniform(0, 1000000)
            loc_0 = Location(x=start_x, y=start_y, t=0, 
                           cell_id=xy_to_cell_id(start_x, start_y),
                           dwell_time=300)
            
            # t=1: 瞬移到目标
            loc_1 = Location(x=target_location[0], y=target_location[1], t=300,
                           cell_id=xy_to_cell_id(*target_location),
                           dwell_time=300)
            
            sybil_trajectories.append([loc_0, loc_1])
        
        return sybil_trajectories
```

---

### 8.3 Baseline方案实现

#### 8.3.0 统一实验参数与Baseline定义（论文主表口径）

统一参数（攻击防御主表）：

| 参数 | 取值 |
| --- | --- |
| 数据集 | GeoLife / T-Drive |
| 客户端数 | 50 |
| 轮数 | 10（含 warmup=1） |
| 隐私预算 | ε=1.0（当前主口径） |
| 恶意比例 | 10%（并报告 5%-50% sweep） |
| 攻击类型 | A1 瞬移（7200m）、A2 身份交换、A5 重放 |

Baseline/对照定义（统一符号）：

| 方案 | 定义 | 预期安全行为 |
| --- | --- | --- |
| TSIP (Full) | TSIP + 链连续性 + 主电路证明约束（含 P4/P5） | A1/A2/A5 高拦截，存在可控 FRR |
| Commitment-Only | 仅承诺链连续性，关闭距离证明 | A1 低拦截，A2/A5 高拦截 |
| No-Integrity | 关闭 TSIP/证明，仅保留 DP 输出 | A1/A2/A5 均低拦截 |
| RiseFL-style | 单轮范数/统计约束，无跨轮链 | 对跨轮攻击拦截弱 |
| Nebula | ESA + shuffle + threshold（无完整性） | 攻击检测基本缺失 |
| Pure LDP | 客户端 GRR 本地扰动（无完整性） | 攻击检测缺失，效用最敏感 |
| EIFFeL-style | 单轮可验证约束（无轨迹连续性） | 对跨轮轨迹攻击拦截弱 |

说明：
- `Nebula / Pure LDP / EIFFeL-style` 主结论来自 standalone baseline 实验（`experiments/run_baselines.py`）。
- 系统级兼容模式用于同流水线观测与趋势对齐，不替代 baseline fidelity 主结论。

#### 8.3.1 Pure LDP (RAPPOR)

```python
# experiments/baselines/pure_ldp.py

class PureLDP:
    """纯本地差分隐私方案"""
    
    def __init__(self, epsilon=1.0, domain_size=1000000):
        self.epsilon = epsilon
        self.domain_size = domain_size
        
        # RAPPOR参数
        self.p = 0.5  # 永久随机化概率
        self.q = 1 / (1 + np.exp(epsilon/2))  # 瞬时随机化概率
    
    def randomize_response(self, true_value: int) -> int:
        """RAPPOR随机化响应"""
        # Step 1: 永久随机化 (Bloom filter)
        if np.random.random() < self.p:
            return np.random.randint(0, self.domain_size)
        
        # Step 2: 瞬时随机化
        if np.random.random() < self.q:
            return np.random.randint(0, self.domain_size)
        
        return true_value
    
    def aggregate(self, responses: List[int]) -> np.ndarray:
        """服务器端聚合"""
        histogram = np.zeros(self.domain_size)
        
        for resp in responses:
            histogram[resp] += 1
        
        # 去偏
        n = len(responses)
        debiased = (histogram - n * self.q) / (1 - self.p - self.q)
        
        return np.maximum(debiased, 0)
```

---

#### 8.3.2 RiseFL (无时序约束)

```python
# experiments/baselines/risefl.py

class RiseFL:
    """RiseFL方案(仅验证单个时刻)"""
    
    def __init__(self, m=10, alpha=0.05):
        """
        Args:
            m: 随机向量数量
            alpha: 显著性水平
        """
        self.m = m
        self.alpha = alpha
    
    def generate_random_vectors(self, dimension: int) -> List[np.ndarray]:
        """服务器生成随机向量"""
        return [np.random.randn(dimension) for _ in range(self.m)]
    
    def compute_proof(self, location_vector: np.ndarray, 
                     random_vectors: List[np.ndarray]) -> float:
        """客户端计算完整性证明"""
        inner_products = [
            np.dot(location_vector, a) 
            for a in random_vectors
        ]
        
        sum_of_squares = sum([ip**2 for ip in inner_products])
        
        return sum_of_squares
    
    def verify(self, proof_s: float, norm_bound: float) -> bool:
        """服务器验证"""
        from scipy.stats import chi2
        
        threshold = norm_bound**2 * chi2.ppf(1 - self.alpha, df=self.m)
        
        return proof_s <= threshold
    
    # 关键缺陷: 无法验证跨时间窗口的连续性!
    def verify_trajectory(self, trajectory: List[Location]) -> bool:
        """验证整条轨迹(RiseFL无法做到这一点)"""
        # RiseFL只能验证每个时刻的位置是否合理
        # 无法验证相邻时刻的连续性
        
        for i, loc in enumerate(trajectory):
            loc_vector = location_to_vector(loc, self.domain_size)
            random_vecs = self.generate_random_vectors(len(loc_vector))
            proof_s = self.compute_proof(loc_vector, random_vecs)
            
            if not self.verify(proof_s, norm_bound=100):
                return False  # 单个位置不合法
        
        # ❌ 无法检测: trajectory[i]到trajectory[i+1]的距离过大!
        return True
```

---

### 8.4 评估指标

#### 8.4.1 安全性指标

**攻击检测率 (Attack Detection Rate)**

```python
def measure_attack_detection_rate(protocol, attack_trajectories):
    """
    测量方案检测攻击的能力
    
    Returns:
        TPR (True Positive Rate): 恶意轨迹被正确拒绝的比例
        FPR (False Positive Rate): 正常轨迹被误拒的比例
    """
    # 恶意轨迹
    malicious_rejected = 0
    for traj in attack_trajectories:
        if not protocol.verify_trajectory(traj):
            malicious_rejected += 1
    
    TPR = malicious_rejected / len(attack_trajectories)
    
    # 正常轨迹
    normal_trajectories = generate_normal_trajectories(n=1000)
    normal_rejected = 0
    for traj in normal_trajectories:
        if not protocol.verify_trajectory(traj):
            normal_rejected += 1
    
    FPR = normal_rejected / len(normal_trajectories)
    
    return {"TPR": TPR, "FPR": FPR}

# 实验
results = {}

# TSIP
tsip_attacks = generate_teleport_attacks(n=1000, distance_ratio=2.0)
results["TSIP"] = measure_attack_detection_rate(TSIP(), tsip_attacks)

# RiseFL (baseline)
results["RiseFL"] = measure_attack_detection_rate(RiseFL(), tsip_attacks)

```

**隐私泄露量化**

```python
def empirical_epsilon_test(protocol, dataset, delta=1e-8, iterations=1000):
    """
    通过蒙特卡洛验证实际隐私预算
    
    方法:
    1. 生成相邻数据集D1和D2(仅差1个用户)
    2. 多次运行协议,获取输出分布
    3. 计算KL散度上界
    """
    epsilon_samples = []
    
    for _ in range(iterations):
        # 生成相邻数据集对
        D1, D2, changed_user = generate_neighboring_datasets(dataset)
        
        # 运行协议
        output_D1 = protocol.run(D1)
        output_D2 = protocol.run(D2)
        
        # 计算散度
        epsilon = compute_max_divergence(output_D1, output_D2, delta)
        epsilon_samples.append(epsilon)
    
    # 95分位数应≤声称的ε
    empirical_epsilon = np.percentile(epsilon_samples, 95)
    
    return empirical_epsilon

# 实验
claimed_epsilon = 1.0
actual_epsilon = empirical_epsilon_test(TSIP(), geolife_dataset)

assert actual_epsilon <= claimed_epsilon * 1.1  # 允许10%误差
print(f"声称: ε={claimed_epsilon}, 实际: ε={actual_epsilon:.2f}")
```

---

#### 8.4.2 效用指标

**热力图准确度**

```python
def heatmap_accuracy(predicted_heatmap, ground_truth_heatmap):
    """
    评估隐私热力图与真实热力图的相似度
    """
    # 1. Top-K重叠率 (Jaccard Index)
    k = 100
    top_k_pred = set(get_top_k_cells(predicted_heatmap, k))
    top_k_true = set(get_top_k_cells(ground_truth_heatmap, k))
    
    jaccard = len(top_k_pred & top_k_true) / len(top_k_pred | top_k_true)
    
    # 2. 均方根误差 (RMSE)
    rmse = np.sqrt(np.mean((predicted_heatmap - ground_truth_heatmap)**2))
    
    # 3. 地球移动距离 (Earth Mover's Distance)
    emd = wasserstein_distance(
        predicted_heatmap.flatten(), 
        ground_truth_heatmap.flatten()
    )
    
    # 4. 相对误差
    relative_error = np.abs(predicted_heatmap - ground_truth_heatmap).sum() / ground_truth_heatmap.sum()
    
    return {
        "jaccard": jaccard,
        "rmse": rmse,
        "emd": emd,
        "relative_error": relative_error
    }

# 对比实验
methods = ["TSIP", "RiseFL", "Clover", "Nebula"]
results = {}

for method in methods:
    protocol = get_protocol(method)
    heatmap = protocol.generate_heatmap(geolife_dataset)
    results[method] = heatmap_accuracy(heatmap, ground_truth)

# 可视化
import matplotlib.pyplot as plt

fig, ax = plt.subplots(1, len(methods), figsize=(20, 4))
for i, method in enumerate(methods):
    ax[i].imshow(results[method]["heatmap"], cmap='hot')
    ax[i].set_title(f"{method}\nJaccard={results[method]['jaccard']:.3f}")
    ax[i].axis('off')

plt.savefig("heatmap_comparison.pdf")
```

---

#### 8.4.3 效率指标

**客户端开销**

```python
def measure_client_overhead(protocol, trajectory):
    """测量客户端计算开销"""
    timings = {
        "top_k": 0,
        "quantization": 0,
        "encryption": 0,
        "proof_generation": 0,
        "total": 0
    }
    
    start = time.time()
    
    # Top-K筛选
    t0 = time.time()
    top_k_indices, top_k_values = trajectory.get_sparse_vector()
    timings["top_k"] = time.time() - t0
    
    # 量化
    t0 = time.time()
    quantized = quantize(top_k_values, bits=4)
    timings["quantization"] = time.time() - t0
    
    # 加密
    t0 = time.time()
    encrypted = protocol.encrypt(top_k_indices, quantized)
    timings["encryption"] = time.time() - t0
    
    # 生成TSIP证明 (TSIP独有)
    if hasattr(protocol, 'generate_tsip_proof'):
        t0 = time.time()
        proof = protocol.generate_tsip_proof(trajectory)
        timings["proof_generation"] = time.time() - t0
    
    timings["total"] = time.time() - start
    
    # 内存占用
    memory_usage = {
        "proof_size": len(proof.to_bytes()) if proof else 0,
        "ciphertext_size": len(encrypted),
        "total_upload": len(encrypted) + timings.get("proof_size", 0)
    }
    
    return timings, memory_usage

# 实验: 在不同设备上测试
devices = {
    "Desktop": {"cpu": "Intel i7", "ram": "16GB"},
    "Laptop": {"cpu": "Intel i5", "ram": "8GB"},
    "Mobile": {"cpu": "Snapdragon 888", "ram": "8GB"}
}

for device_name, device_spec in devices.items():
    print(f"\\n=== {device_name} ({device_spec}) ===")
    
    timings, memory = measure_client_overhead(TSIP(), test_trajectory)
    
    print(f"Total time: {timings['total']*1000:.1f} ms")
    print(f"  - Proof generation: {timings['proof_generation']*1000:.1f} ms")
    print(f"Upload size: {memory['total_upload']/1024:.1f} KB")
```

**服务器吞吐量**

```python
def measure_server_throughput(protocol, num_clients=10000):
    """测量服务器处理能力"""
    # 生成测试数据
    submissions = [
        generate_random_submission() 
        for _ in range(num_clients)
    ]
    
    # 测试验证吞吐量
    start = time.time()
    
    accepted = 0
    for submission in submissions:
        if protocol.verify_submission(submission):
            accepted += 1
    
    elapsed = time.time() - start
    
    throughput = num_clients / elapsed  # submissions/second
    
    return {
        "throughput": throughput,
        "acceptance_rate": accepted / num_clients,
        "avg_latency": elapsed / num_clients * 1000  # ms
    }

# 对比实验
results = {}
for method in ["TSIP", "RiseFL", "Clover"]:
    protocol = get_protocol(method)
    results[method] = measure_server_throughput(protocol)

print("\\n=== Server Throughput ===")
for method, result in results.items():
    print(f"{method:10s}: {result['throughput']:.0f} req/s, "
          f"latency={result['avg_latency']:.1f}ms")
```

---

### 8.5 实验场景设计

#### Experiment 1: 攻击防御能力

**目标**: 验证TSIP能有效检测跨时间窗口攻击

```python
# experiments/exp1_attack_defense.py

def run_attack_defense_experiment():
    """
    实验1: 攻击防御能力
    """
    # 生成不同类型的攻击
    attacks = {
        "Teleport (2x)": generate_teleport_attacks(n=1000, ratio=2.0),
        "Teleport (5x)": generate_teleport_attacks(n=1000, ratio=5.0),
        "Identity Swap": generate_identity_swap_attacks(n=500),
        "Sybil": generate_sybil_attacks(n=100, sybils_per_attacker=10)
    }
    
    # 测试各方案
    protocols = {
        "TSIP": TSIP(),
        "RiseFL": RiseFL(),
        "Clover": Clover(),
        "No Defense": NoDefense()
    }
    
    results = {}
    
    for protocol_name, protocol in protocols.items():
        results[protocol_name] = {}
        
        for attack_name, attack_trajs in attacks.items():
            tpr, fpr = measure_detection_rate(protocol, attack_trajs)
            results[protocol_name][attack_name] = {
                "TPR": tpr,
                "FPR": fpr,
                "F1": 2 * tpr * (1-fpr) / (tpr + 1 - fpr)
            }
    
    # 可视化
    plot_attack_defense_results(results)
    
    return results

```

---

#### Experiment 2: 隐私-效用权衡

**目标**: 研究不同ε值下的准确度变化

```python
def run_privacy_utility_tradeoff():
    """
    实验2: 隐私-效用权衡
    """
    epsilon_values = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
    
    results = {}
    
    for epsilon in epsilon_values:
        # 配置TSIP
        tsip = TSIP(epsilon_total=epsilon)
        
        # 运行协议
        heatmap = tsip.generate_heatmap(geolife_dataset)
        
        # 评估准确度
        accuracy = heatmap_accuracy(heatmap, ground_truth)
        
        results[epsilon] = {
            "jaccard": accuracy["jaccard"],
            "rmse": accuracy["rmse"],
            "relative_error": accuracy["relative_error"]
        }
    
    # 绘制曲线
    plt.figure(figsize=(10, 6))
    
    plt.subplot(1, 2, 1)
    plt.plot(epsilon_values, [r["jaccard"] for r in results.values()], 
             'o-', label='TSIP')
    plt.xlabel('Privacy Budget ε')
    plt.ylabel('Jaccard Similarity')
    plt.xscale('log')
    plt.grid(True)
    plt.legend()
    
    plt.subplot(1, 2, 2)
    plt.plot(epsilon_values, [r["relative_error"] for r in results.values()], 
             'o-', label='TSIP', color='red')
    plt.xlabel('Privacy Budget ε')
    plt.ylabel('Relative Error')
    plt.xscale('log')
    plt.grid(True)
    plt.legend()
    
    plt.tight_layout()
    plt.savefig("privacy_utility_tradeoff.pdf")
    
    return results
```

---

#### Experiment 3: 可扩展性测试

**目标**: 验证TSIP在大规模场景下的性能

```python
def run_scalability_test():
    """
    实验3: 可扩展性
    """
    # 变量1: 用户数量
    user_counts = [100, 1000, 10000, 100000]
    
    # 变量2: 网格数量
    grid_sizes = [1e4, 1e5, 1e6, 1e7]
    
    results = {
        "user_scaling": {},
        "grid_scaling": {}
    }
    
    # 测试用户数扩展
    for n_users in user_counts:
        dataset = generate_synthetic_data(n_users=n_users, n_grids=1e6)
        
        start = time.time()
        tsip = TSIP()
        heatmap = tsip.generate_heatmap(dataset)
        elapsed = time.time() - start
        
        results["user_scaling"][n_users] = {
            "time": elapsed,
            "throughput": n_users / elapsed
        }
    
    # 测试网格数扩展
    for grid_size in grid_sizes:
        dataset = generate_synthetic_data(n_users=10000, n_grids=grid_size)
        
        start = time.time()
        tsip = TSIP()
        heatmap = tsip.generate_heatmap(dataset)
        elapsed = time.time() - start
        
        results["grid_scaling"][grid_size] = {
            "time": elapsed,
            "memory_mb": measure_memory_usage()
        }
    
    # 可视化
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # 用户数扩展
    ax1.loglog(user_counts, 
               [r["time"] for r in results["user_scaling"].values()],
               'o-', label='TSIP')
    ax1.set_xlabel('Number of Users')
    ax1.set_ylabel('Time (seconds)')
    ax1.grid(True)
    ax1.legend()
    
    # 网格数扩展
    ax2.loglog(grid_sizes,
               [r["memory_mb"] for r in results["grid_scaling"].values()],
               's-', color='red', label='TSIP')
    ax2.set_xlabel('Number of Grids')
    ax2.set_ylabel('Memory (MB)')
    ax2.grid(True)
    ax2.legend()
    
    plt.tight_layout()
    plt.savefig("scalability.pdf")
    
    return results
```

---

#### Experiment 4: 真实数据评估

**目标**: 在GeoLife和T-Drive上评估端到端性能

```python
def run_real_data_evaluation():
    """
    实验4: 真实数据评估
    """
    datasets = {
        "GeoLife": load_geolife(),
        "T-Drive": load_tdrive()
    }
    
    protocols = ["TSIP", "RiseFL", "Clover", "Nebula"]
    
    results = {}
    
    for dataset_name, dataset in datasets.items():
        results[dataset_name] = {}
        
        for protocol_name in protocols:
            protocol = get_protocol(protocol_name)
            
            # 运行协议
            start = time.time()
            heatmap = protocol.generate_heatmap(dataset)
            elapsed = time.time() - start
            
            # 评估
            accuracy = heatmap_accuracy(heatmap, compute_ground_truth(dataset))
            
            results[dataset_name][protocol_name] = {
                "jaccard": accuracy["jaccard"],
                "rmse": accuracy["rmse"],
                "time": elapsed,
                "communication_mb": measure_communication(protocol, dataset)
            }
    
    # 生成对比表格
    print("\\n=== Real Data Evaluation ===")
    print(f"{'Dataset':<12} {'Protocol':<10} {'Jaccard':>8} {'RMSE':>8} {'Time(s)':>8} {'Comm(MB)':>10}")
    print("-" * 66)
    
    for dataset_name in datasets.keys():
        for protocol_name in protocols:
            r = results[dataset_name][protocol_name]
            print(f"{dataset_name:<12} {protocol_name:<10} "
                  f"{r['jaccard']:>8.3f} {r['rmse']:>8.1f} "
                  f"{r['time']:>8.1f} {r['communication_mb']:>10.2f}")
    
    return results
```

---

### 8.6 消融实验

**目标**: 证明TSIP各组件的必要性

```python
def run_ablation_study():
    """
    消融实验: 逐个移除TSIP的组件
    """
    variants = {
        "Full TSIP": {
            "clover": True,
            "risefl": False,  # TSIP替代了RiseFL
            "tsip": True,
            "nebula": True
        },
        "w/o TSIP": {
            "clover": True,
            "risefl": True,   # 回退到RiseFL
            "tsip": False,
            "nebula": True
        },
        "w/o Clover": {
            "clover": False,
            "risefl": False,
            "tsip": True,
            "nebula": True
        },
        "w/o Nebula": {
            "clover": True,
            "risefl": False,
            "tsip": True,
            "nebula": False
        },
        "TSIP only": {
            "clover": False,
            "risefl": False,
            "tsip": True,
            "nebula": False
        }
    }
    
    results = {}
    
    for variant_name, config in variants.items():
        protocol = TSIP_Variant(**config)
        
        # 评估安全性
        attack_detection = measure_attack_detection(protocol, attacks)
        
        # 评估效用
        heatmap = protocol.generate_heatmap(geolife_dataset)
        accuracy = heatmap_accuracy(heatmap, ground_truth)
        
        # 评估效率
        overhead = measure_client_overhead(protocol, test_trajectory)
        
        results[variant_name] = {
            "attack_detection": attack_detection["TPR"],
            "jaccard": accuracy["jaccard"],
            "client_time_ms": overhead["total"] * 1000,
            "communication_kb": overhead["total_upload"] / 1024
        }
    
    # 可视化
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    
    metrics = ["attack_detection", "jaccard", "client_time_ms", "communication_kb"]
    titles = ["Attack Detection Rate", "Utility (Jaccard)", 
              "Client Overhead (ms)", "Communication (KB)"]
    
    for idx, (metric, title) in enumerate(zip(metrics, titles)):
        ax = axes[idx // 2, idx % 2]
        
        values = [results[v][metric] for v in variants.keys()]
        ax.bar(range(len(variants)), values)
        ax.set_xticks(range(len(variants)))
        ax.set_xticklabels(variants.keys(), rotation=45, ha='right')
        ax.set_title(title)
        ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig("ablation_study.pdf")
    
    return results

```

---

## 第九章: 论文撰写指南

### 9.1 论文结构

**标题**:

```
TSIP: Temporal-Spatial Integrity Proofs for 
Privacy-Preserving Location Aggregation

或更吸引人的版本:
Detecting Ghost Trajectories: Zero-Knowledge Proofs 
for Cross-Window Location Integrity
```

**摘要模板** (150-200词):

```
Location-based services aggregate user trajectories to generate 
urban heatmaps while preserving privacy. Existing solutions verify 
individual location reports but fail to ensure temporal-spatial 
consistency, enabling sophisticated attacks where users swap 
identities across time windows or teleport between distant locations.

We present TSIP (Temporal-Spatial Integrity Proof), a novel protocol 
that leverages zero-knowledge proofs to verify trajectory continuity 
without revealing locations. TSIP introduces a commitment chain 
mechanism that cryptographically binds consecutive locations, combined 
with Groth16 zk-SNARKs to prove physical movement constraints. We 
show TSIP provides public-output ε-differential privacy with ε=1.0,
and achieves high malicious-trajectory rejection under the continuity
threat model.

Evaluation on GeoLife and T-Drive datasets shows TSIP blocks 99.7% 
of cross-window attacks in our evaluated settings (vs. 0.1% for
state-of-the-art RiseFL) while 
adding second-level client overhead on snarkjs and sub-second proving 
overhead on rapidsnark, with about 2KB communication per submission. 
Communication remains around KB-level in current sparse implementation, 
and we treat communication efficiency as an engineering comparison 
rather than an information-theoretic optimality theorem.
```

---

### 9.2 各章节写作要点

#### Section 1: Introduction

**结构**:

```
1.1 动机 (1段)
  - 位置数据的价值 (城市规划、交通优化)
  - 隐私威胁 (个人追踪、行为分析)

1.2 现有方案的局限 (2段)
  - DP方案: 无完整性保证
  - 完整性验证方案: 仅验证单个时刻
  - 关键盲点: 跨时间窗口攻击

1.3 技术挑战 (1段)
  - Challenge 1: 如何验证时序连续性而不泄露位置
  - Challenge 2: 如何高效处理T个时间窗口
  - Challenge 3: 如何组合完整性与隐私保证

1.4 贡献 (bullet list)
  - [C1] 首次形式化"时空完整性"问题
  - [C2] 提出TSIP协议,结合承诺链与zk-SNARKs
  - [C3] 证明TSIP的连续性安全性与公开输出隐私性，并给出工程通信效率分析
  - [C4] 实现并评估,证明实用性

1.5 论文组织 (简短)
```

**写作技巧**:

- 第一段用具体例子吸引读者
- 用攻击场景激发危机感
- 用"existing work做了A,但无法处理B"的句式过渡

---

#### Section 2: Background

**包含内容**:

```
2.1 差分隐私
  - ε-DP定义（当前主口径；可扩展到(ε,δ)-DP）
  - 组合定理
  - 拉普拉斯机制

2.2 零知识证明
  - zk-SNARK简介
  - Groth16协议
  - 承诺方案 (Poseidon哈希)

2.3 威胁模型
  - 诚实但好奇的服务器
  - 恶意客户端 (Sybil, 身份交换)

2.4 相关工作对比表
```

**注意事项**:

- Background要简洁,不要像教科书
- 只介绍论文中实际用到的技术
- 相关工作表格要突出"我们vs他们"的差异

---

#### Section 3-4: Protocol Design

**组织方式**:

```
3. TSIP Overview
  3.1 High-level idea (配图)
  3.2 Commitment chain机制
  3.3 Distance verification circuit
  3.4 Protocol flow (sequence diagram)

4. Detailed Protocol
  4.1 Setup phase
  4.2 Client submission
  4.3 Server verification
  4.4 Aggregation & DP output
```

**写作建议**:

- 先给直觉(intuition),再给形式化
- 多用图示 (协议流程图、电路示意图)
- 伪代码要简洁,细节放到附录

---

#### Section 5: Security Analysis

**定理顺序**:

```
5.1 Theorem 1: Soundness (最重要)
  - 陈述
  - 证明sketch (主体)
  - 完整证明见附录

5.2 Theorem 2: Privacy
  - 陈述
  - 隐私组合分析
  - 与DP组合定理的关系

5.3 Theorem 3: Zero-Knowledge
  - 陈述
  - 模拟器构造

5.4 Communication Analysis (工程口径)
  - 每次提交通信构成
  - 与基线方案的通信量对比
```

**证明写作技巧**:

- 主体用proof sketch (1-2页)
- 完整证明放附录
- 用Case分析 (攻击者有哪些策略,逐一分析)

---

#### Section 6: Implementation

**内容**:

```
6.1 System architecture
  - Docker部署
  - 各组件实现 (client, shuffler, aggregators)

6.2 Circuit implementation
  - Circom代码统计 (行数、约束数)
  - Setup时间
  - 优化技巧

6.3 Deployment considerations
  - 参数选择 (ε, k, v_max)
  - 可扩展性优化
```

---

#### Section 7: Evaluation

**实验组织**:

```
7.1 Experimental Setup
  - 数据集 (GeoLife, T-Drive, Synthetic)
  - Baselines (RiseFL, Clover, Nebula, Pure LDP)
  - 评估指标
  - 硬件配置

7.2 Attack Defense (Exp 1)
  - 图: 各方案的TPR对比
  - 发现: TSIP TPR=99.7%, RiseFL TPR=0.1%

7.3 Privacy-Utility Tradeoff (Exp 2)
  - 图: ε vs Jaccard
  - 发现: ε=1.0时Jaccard=0.82

7.4 Scalability (Exp 3)
  - 图: 用户数/网格数 vs 时间/内存
  - 发现: 在当前实现中已验证到 1000 用户，后续扩展到更大规模

7.5 Real Data (Exp 4)
  - 表格: 各方案在真实数据上的表现
  - 案例研究: 东京市区热力图

7.6 Ablation Study
  - 图: 移除各组件的影响
  - 发现: TSIP是关键 (移除后TPR降至1%)

7.7 Overhead Analysis
  - 表格: 客户端/服务器开销
  - 发现: snarkjs秒级 prove / rapidsnark亚秒级 prove，通信约2KB
```

**图表建议**:

- 每个实验至少1个图
- 使用对数坐标轴 (scalability实验)
- 标注关键数据点
- 颜色一致 (TSIP总是用蓝色)

---

#### Section 8: Discussion

**包含内容**:

```
8.1 Limitations
  - 需要可信Setup (可用MPC缓解)
  - 假设至少1个服务器诚实
  - 不支持实时查询 (批处理)

8.2 Extensions
  - 多轨迹融合 (汽车+手机)
  - 动态ε调整
  - 联邦学习集成

8.3 Deployment Experiences
  - 与XX公司合作的试点
  - 实际挑战 (网络不稳定、设备异构)
```

---

#### Section 9: Related Work

**分类方式**:

```
9.1 Differential Privacy for Location
  - [Nebula] [GeoMask] ...
  - 对比: 无完整性验证

9.2 Integrity Verification
  - [RiseFL] [VerifyFL] ...
  - 对比: 无时序约束

9.3 Zero-Knowledge Proofs for Privacy
  - [zk-SNARKs应用] ...
  - 对比: 首次用于轨迹验证
```

---

#### Section 10: Conclusion

**结构**:

```
总结贡献 (3句)
  - 形式化了时空完整性问题
  - 提出TSIP协议并证明安全性
  - 实验验证了有效性和效率

Future work (1-2句)
  - 扩展到其他传感器数据
  - 探索更强的威胁模型
```

---

### 9.3 投稿准备

#### 目标会议选择

**Tier 1 (冲刺目标)**:

```
USENIX Security (冬季: 6月截稿, 夏季: 10月截稿)
  - 接受率: ~18%
  - 偏好: 系统+理论结合
  - 审稿周期: 3个月

NDSS (全年滚动)
  - 接受率: ~15%
  - 偏好: 网络安全+隐私
  - 审稿周期: 3-4个月

CCS (春季: 1月截稿, 秋季: 5月截稿)
  - 接受率: ~19%
  - 偏好: 理论创新
  - 审稿周期: 3个月
```

**Tier 2 (保底选择)**:

```
ACSAC
  - 接受率: ~23%
  - 更容易接受应用类工作

ESORICS
  - 欧洲会议,接受率~20%
```

---

#### Timeline建议

**当前状态（2026-04-12）**

```
已完成:
- TSIP 主电路（P4/P5）与 trusted setup
- A1/A2/A5 攻防主结果（含 Commitment-Only / No-Integrity）
- utility sweep 主流程与自动汇总

进行中:
- baseline 完整对照（standalone + 系统兼容模式）
- 论文图表统一口径与附录整理
```

**投稿窗口（按最新计划更新）**:

- **NDSS 2027 Cycle 2**（目标）
- **USENIX Security 2027 Cycle 1**（备选）

**Rebuttal准备**:

```
预判常见质疑:
Q1: "TSIP只是zk-SNARK的应用,创新性不足?"
A: 我们不仅应用,还形式化了新问题,设计了 continuity 约束协议，并给出系统级安全与隐私分析（通信部分按工程效率分析呈现）

Q2: "实验规模不够大?"
A: 当前主结果已覆盖真实数据与 200/500/1000 规模；更大规模作为下一阶段补充实验

Q3: "可信Setup是个问题?"
A: 可用MPC生成,或换用Plonk (透明Setup)

Q4: "真实部署可行性?"
A: snarkjs路径是秒级，rapidsnark可降到亚秒级；需按部署栈给出实测值而非固定12ms
```

---

### 9.4 开源与复现

**代码仓库结构**:

```
tsip-impl/
├── README.md (详细安装说明)
├── circuits/ (Circom源码)
├── tsip/ (Python实现)
├── experiments/ (实验脚本)
├── data/ (数据集下载链接)
├── docker-compose.yml
├── requirements.txt
└── LICENSE
```

**复现文档要求**:

```
README必须包含:
1. 环境配置 (依赖、版本)
2. 快速开始 (5分钟跑通Demo)
3. 完整实验复现 (逐个实验的命令)
4. 结果示例与通过判据（标注 measured/pending）

artifact-evaluation/
├── INSTALL.md (安装指南)
├── EXPERIMENTS.md (实验步骤)
└── RESULTS.md (预期输出)
```

### 9.5 Baseline 系统级运行说明

当前工程里 `experiments/run_utility_sweep.sh` 已支持如下系统级模式：

- `full`
- `commit_only`
- `no_integ`
- `risefl`
- `nebula`
- `ldp`
- `eiffel`

示例命令（GeoLife）：

```bash
cd ~/risefl_mvp

ROUNDS=10 \
WARMUP_ROUNDS=1 \
MALICIOUS_RATES="0.0 0.1 0.2 0.3 0.5" \
TSIP_MODES="full commit_only no_integ risefl nebula ldp eiffel" \
CLIENT_TRAJ_SOURCE=geolife \
GEO_TRAJ_PATH=/app/experiments/geolife_tsip_ready_50u.jsonl \
BUILD_SERVICES=0 \
CLIENT_ZK_STEP_ENABLE=0 \
SHUFFLER_ZK_STEP_ENABLE=0 \
bash experiments/run_utility_sweep.sh
```

写作口径约束：

- `full/commit_only/no_integ/risefl` 可作为系统真实协议路径主结果。
- `nebula/ldp/eiffel` 在系统中通过 `REPORT_PROTOCOL` 做兼容化上报，适合工程对齐与趋势比较。
- 为避免审稿质疑 baseline fidelity，Nebula/LDP/EIFFeL 的主结果仍建议来自 `experiments/run_baselines.py` 的 standalone 仿真，系统兼容结果放附录。

---

## 总结

本完整设计方案包含:

**Part 1**: 问题定义、零知识证明基础、协议概览
**Part 2**: 详细协议实现、电路代码、系统集成
**Part 3**: 形式化安全证明、攻击防御分析
**Part 4**: 实验评估方案、论文撰写指南 (本文档)

---

## 附录: 常用资源

**zk-SNARK学习**:

- ZKP MOOC: https://zk-learning.org/
- Circom文档: https://docs.circom.io/
- snarkjs: https://github.com/iden3/snarkjs

**数据集**:

- GeoLife: https://www.microsoft.com/en-us/research/publication/geolife-gps-trajectory-dataset-user-guide/
- T-Drive: https://www.microsoft.com/en-us/research/publication/t-drive-trajectory-data-sample/

**相关论文**:

- [Groth16] https://eprint.iacr.org/2016/260.pdf
- [RiseFL] https://www.ndss-symposium.org/ndss-paper/risefl/
- [Nebula] https://dl.acm.org/doi/10.1145/3514221.3517871

**工具**:

- Docker: https://www.docker.com/
- Python科学计算栈: numpy, scipy, matplotlib
- LaTeX模板: https://www.overleaf.com/latex/templates
