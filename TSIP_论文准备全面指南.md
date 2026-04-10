# TSIP 论文准备全面指南

## Related Work · Baseline · 实验补充 · 方案修改

**生成日期：2026-04-09**  
**基于项目当前进度（含 2026-04-08 恶意比例 sweep 结果）**

---

## 一、Related Work 文献分类与推荐

你的论文核心主题是 **"隐私保护的位置数据聚合 + 基于零知识证明的轨迹连续性完整性验证"**，Related Work 需要覆盖三个主方向，并在每个方向说清楚 TSIP 的差异化贡献。

### 1.1 差分隐私与位置数据收集（DP for Location）

这一类工作只关注隐私，不做完整性验证，是你的"隐私层"对标。

| 文献 | 发表信息 | 核心方法 | 与 TSIP 的关系 |
|------|---------|---------|--------------|
| **Nebula** (Shamsabadi et al.) | SIGMOD 2022 / PETS 2024 | 阈值聚合 + shuffle + DP 直方图 | TSIP 的隐私架构（ESA 范式）部分参考了此类方案，但 Nebula **无完整性验证**，恶意客户端可任意注入虚假位置 |
| **RAPPOR** (Erlingsson et al.) | CCS 2014 | 随机响应 + Bloom filter + LDP | 经典 LDP 方案，Google 部署级。TSIP 在 DP 层使用了类似的本地扰动思想，但 RAPPOR **无跨轮一致性检查** |
| **Prochlo** (Bittau et al.) | SOSP 2017 | ESA 三阶段架构（Encode-Shuffle-Analyze） | TSIP 的系统架构直接借鉴了 ESA 范式，但在 Shuffle 阶段加入了 ZK 证明验证，这是 Prochlo 不具备的 |
| **LDP for Trajectory** (Cunningham et al.) | PVLDB 2021 | LDP 轨迹发布 | 关注轨迹级 LDP，但仍无完整性保证。可在 related work 中引用说明"纯 LDP 方案在恶意注入下效用严重退化" |
| **Private Spatial Data Aggregation** (Chen et al.) | ICDE 2016 | 个性化 LDP + 空间域分解 | 提出 PLDP 模型，比标准 LDP 更灵活，但同样缺乏完整性层 |
| **DP for Time-Series** (Rastogi & Nath) | SIGMOD 2010 | 傅里叶变换 + 加密聚合 | 时序 DP 的经典工作，你可在讨论时序相关性时引用 |

**论文中的叙事角度**：这些工作解决了"如何在不信任服务器的前提下收集位置统计"，但共同的盲区是：**当客户端本身是恶意的，纯 DP 机制无法阻止虚假数据注入**。TSIP 的 ZK 证明层正是填补这一缺口。

### 1.2 安全聚合与完整性验证（Integrity Verification in Aggregation）

这一类工作做了完整性，但没有时空约束。

| 文献 | 发表信息 | 核心方法 | 与 TSIP 的关系 |
|------|---------|---------|--------------|
| **RiseFL** (Xiao et al.) | NDSS 2024 / PVLDB 2024 | ZKP + L2 范数约束验证 FL 梯度 | **最重要的 baseline**。RiseFL 验证的是"梯度范数是否在阈值内"，但完全不考虑跨轮时序关系。对瞬移攻击（A1）无检测能力 |
| **EIFFeL** (Roy Chowdhury et al.) | CCS 2022 | 安全聚合 + 任意完整性检查 | 提出了一个通用框架，在安全聚合中嵌入完整性约束。TSIP 可视为 EIFFeL 在"位置轨迹连续性"方向的特化和深化 |
| **VerifyNet** (Xu et al.) | IEEE TIFS 2020 | 双重掩码 + 聚合正确性证明 | 关注服务器聚合的正确性验证（防恶意服务器），而 TSIP 关注客户端输入的完整性验证（防恶意客户端），方向互补 |
| **SVeriFL** (多方签名) | Information Sciences 2022 | BLS 签名 + 多方验证 | 验证参数上传完整性和聚合一致性，但无 ZK 保护，且不处理时序 |
| **ZKSL** (匿名) | NDSS 2026 | ZKP 验证垂直 FL 训练完整性 | 最新工作，将 ZKP 应用于垂直联邦学习。TSIP 可与之对比：ZKSL 验证的是"训练计算正确性"，TSIP 验证的是"输入数据时空可行性" |
| **FLTrust** (Cao et al.) | NDSS 2021 | 服务器持有小规模可信数据集 | 依赖服务器有真实数据进行 trust bootstrapping，TSIP 不需要服务器持有位置数据 |

**论文中的叙事角度**：这些工作关注"聚合过程中的完整性"，但它们验证的对象（范数、计算正确性、聚合一致性）与位置数据的物理约束（速度、距离、时间窗口）正交。**没有一个方案能检测"在时间维度上不合理的位置跳变"**——这正是 TSIP 的核心创新点。

### 1.3 零知识证明与位置隐私（ZKP for Location）

| 文献 | 发表信息 | 核心方法 | 与 TSIP 的关系 |
|------|---------|---------|--------------|
| **ZK-PoL for IoT** (Wu et al.) | IEEE IoT Journal 2020 | 区块链 + ZK-PoL | 单次位置证明，无跨轮轨迹验证。执行时间较长（分钟级），不适合高频聚合场景 |
| **ZK-PoL for Vehicle Subsidies** (最新) | 2025 预印本 | 几何技术 + 驾驶行为证明 | 最接近 TSIP 的工作之一，但面向车辆补贴合规场景，非统计聚合；且依赖可信 Witness 设备 |
| **Proof-of-Location (PoL) 综述** | 2025 | 分类学：密码学保证、时空同步、信任模型 | TSIP 可定位为 PoL 领域中"面向统计聚合的隐私保护轨迹完整性方案"，与传统 PoL 的"面向凭证的位置证明"区分开 |
| **zkFDL** (Ahmadi & Nourmohammadi) | ICAIC 2024 | ZKP 去中心化联邦学习 | 将 ZKP 用于 FL 的隐私保护，但不涉及位置或时空约束 |
| **Groth16** (Groth) | EUROCRYPT 2016 | zk-SNARK 标准方案 | TSIP 底层密码学基础，需在 Preliminaries 中引用 |

**论文中的叙事角度**：ZKP 在位置领域的应用主要集中在"单点位置证明"（Proof-of-Location），**尚无工作将 ZKP 应用于 "跨时间窗口的轨迹连续性验证 + 隐私保护统计聚合"这一组合问题**。TSIP 是第一个这样做的。

### 1.4 其他应参考的重要文献

| 文献 | 用途 |
|------|------|
| **Poseidon Hash** (Grassi et al., USENIX Security 2021) | TSIP 使用的 ZK-friendly 哈希函数 |
| **Secure Aggregation** (Bonawitz et al., CCS 2017) | 安全聚合经典方案，TSIP 的 secret sharing 层的理论基础 |
| **GeoLife 数据集** (Zheng et al., 2010) | 实验数据集 |
| **T-Drive 数据集** (Yuan et al., 2010) | 实验数据集 |
| **SVT (Sparse Vector Technique)** (Dwork & Roth, 2014) | TSIP 的 DP 门控使用了 SVT，需引用原定理 |

---

## 二、Baseline 推荐与实验设计

### 2.1 必须做的 Baseline（P0）

| Baseline 名称 | 实现方式 | 对比维度 | 预期结果 |
|-------------|---------|---------|---------|
| **No-Integrity（已完成 ✅）** | 关闭 TSIP，仅保留 DP | malicious_reject_rate | 0%（恶意数据全部通过） |
| **Commitment-Only** | 保留 Poseidon2 承诺链，但关闭 ZK 证明验证 | 恶意拦截率 + 开销 | 承诺链可检测链断裂，但无距离/速度约束验证，部分攻击漏过 |
| **Pure LDP** | 客户端本地加噪，服务端直聚合，无 shuffle | utility（Jaccard/RMSE） | 在同 ε 下 utility 显著低于 TSIP 的 shuffle DP 方案 |

### 2.2 强烈建议做的 Baseline（P1）

| Baseline 名称 | 实现方式 | 对比维度 | 预期结果 |
|-------------|---------|---------|---------|
| **RiseFL-style（范数约束 only）** | 用 L2 范数约束替代 TSIP 的距离约束 | 跨窗口攻击检测 | 对 A1 瞬移攻击：RiseFL 无法检测（约 0% TPR）；对 A3 渐进偏移：两者都无法检测 |
| **Statistical Outlier（统计离群检测）** | 服务端看到明文位置后做 z-score 异常检测 | TPR + 隐私泄露 | TPR 可能较高，但需要服务端看到明文位置 → 隐私完全丧失。与 TSIP 形成"安全 vs 隐私"的 tradeoff 对比 |

### 2.3 消融实验（Ablation Study，P1-P2）

| 消融组 | 移除的组件 | 验证的问题 | 预期结果 |
|-------|----------|----------|---------|
| **-ZK** | 移除 ZK 证明，保留承诺链 + DP | ZK 证明的价值 | 恶意客户端可伪造承诺，拦截率下降 |
| **-Chain** | 移除承诺链连续性，仅保留单步 ZK | 链式约束的价值 | A2 身份交换攻击漏过 |
| **-DP** | 移除差分隐私 | DP 层对 utility 的影响 | 聚合结果更精确，但无隐私保证 |
| **-Shuffle** | 去掉 shuffler 中间层 | Shuffle 的隐私增益 | 服务器可通过提交顺序推断用户身份 |
| **-Blacklist** | 关闭黑名单机制 | 黑名单对持续攻击的防御价值 | 同一恶意客户端可反复尝试，false_reject 下降但安全性降低 |
| **Full TSIP** | 完整系统 | 基准 | malicious_reject_rate=1.0, false_reject_rate≈0.002-0.05 |

---

## 三、实验补充清单（按优先级）

### 3.1 已完成实验盘点

| 实验 | 状态 | 可用于论文章节 |
|------|------|-------------|
| 合成数据 30 轮 | ✅ | 主结果 |
| GeoLife 10 轮 | ✅ | 真实数据验证 |
| T-Drive 主实验 + boundary sweep 7 档 | ✅ | 安全评估（S 型曲线） |
| No-ZK baseline | ✅ | Baseline 对比 |
| 规模扩展 200/500/1000 | ✅ | Scalability |
| A1 瞬移攻击 | ✅ | 攻防评估 |
| A2 身份交换攻击 | ✅ | 攻防评估 |
| A5 重放攻击 | ✅ | 攻防评估 |
| A3 渐进偏移（初版） | ⚠️ | Limitation 讨论 |
| 恶意比例 sweep 5%-50% | ✅ | 鲁棒性分析 |
| ZK 基准 (snarkjs vs rapidsnark) | ✅ | 开销分析 |
| 参数对照 60s/110 vs 300s/100 | ✅ | 参数选择依据 |

### 3.2 缺失的关键实验

#### 🔴 P0（阻塞论文提交）

**实验 A：Utility 指标框架**
- **为什么必须做**：审稿人一定会问"你的聚合结果质量如何？"，目前只有 malicious_reject_rate，没有从聚合输出角度衡量效用。
- **需要的指标**：
  - **Jaccard Similarity**：TSIP 聚合热力图 vs ground truth 热力图的网格重叠度
  - **RMSE**：每个网格的估计频率 vs 真实频率的均方根误差
  - **Relative Error**：相对误差中位数
- **实验设计**：
  - 生成 ground truth 热力图（无攻击无噪声下的真实分布）
  - 对比：(1) Full TSIP, (2) No-Integrity + DP, (3) Pure LDP, (4) No-DP
  - 在不同 ε 值（0.1, 0.5, 1.0, 2.0, 5.0）下画 ε-Jaccard 曲线
  - 在不同攻击率（0%, 10%, 30%, 50%）下画 utility 退化曲线
- **预期产出**：Money Figure——TSIP vs No-Integrity 在攻击率梯度下的 utility 退化对比图

**实验 B：Commitment-Only Baseline**
- **为什么必须做**：如果不做这个 baseline，审稿人会质疑"ZK 证明的边际价值是什么？承诺链本身就能防御了？"
- **实现方式**：`SHUFFLER_TSIP_ENABLE=0, CLIENT_TSIP_ENABLE=0`，但保留承诺链提交和检查
- **预期结果**：承诺链能检测链断裂（A2, A5），但对 A1 瞬移攻击无能力（因为不验证距离约束）

**实验 C：DP ε 敏感性**
- **为什么必须做**：Privacy-Utility Tradeoff 是顶会评审的标准问题
- **实验设计**：固定其他参数，sweep ε = {0.1, 0.5, 1.0, 2.0, 5.0}，报告 cells_kept_post 和 Jaccard
- **预期产出**：ε vs Utility 曲线

#### 🟡 P1（强烈建议）

**实验 D：端到端延迟分解（Latency Breakdown）**
- 画 stacked bar chart：proof_gen → network → verify → aggregate → dp
- 对比 snarkjs vs rapidsnark 路径

**实验 E：RiseFL-style Baseline**
- 实现 L2 范数约束（对位置向量做范数检查，不做距离约束）
- 对比 TSIP 在 A1 攻击下的 TPR

**实验 F：A3 渐进偏移强度曲线（补充版）**
- 在当前初版基础上，固定 bias 方向，增加更多 bias 档位
- 输出：累计偏移 vs 轮数的曲线，明确 TSIP 的检测边界

#### 🟢 P2（锦上添花）

**实验 G：多维度对比表**

构建一个对比表，覆盖所有 baseline：

| 方案 | 恶意拦截率 | 误拒率 | Jaccard@ε=1 | 客户端开销 | 需要暴露明文位置？ |
|------|----------|-------|------------|----------|--------------|
| TSIP | 1.0 | 0.002 | TBD | ~3s prove | ❌ |
| No-Integrity | 0.0 | 0.0 | TBD | 0 | ❌ |
| Pure LDP | N/A | N/A | TBD | ~0ms | ❌ |
| Commitment-Only | TBD | TBD | TBD | ~0.1s | ❌ |
| Statistical Outlier | TBD | TBD | TBD | 0 | ✅ |

---

## 四、方案需要修改的地方

### 4.1 🔴 P0 修改（阻塞论文）

#### 4.1.1 Proof-Payload Binding（v2）
- **当前问题**：证明的是 `prev_loc → curr_loc` 连续性，但 payload（share/cell/weight）与同一 witness 未绑定。攻击者可以用合法证明 + 篡改后的 payload。
- **修改方案**：在 ZK 电路中引入 `payload_commitment`，证明语句升级为 `R_semantic(w): prev→curr 连续 ∧ payload_commitment = Commit(F(curr_loc, ...))`
- **论文影响**：这是安全定理的前提条件，不完成此项，论文中的完整性声明会被审稿人攻破
- **建议**：如果电路修改工期不够，至少需要：
  - (a) 在论文中明确写出 v1 的 consistency binding 语义
  - (b) 在 Shuffler 中实现 payload_digest + proof_digest 的 attestation 签名
  - (c) 在 Limitation 中声明 v2 语义绑定是 future work

#### 4.1.2 Claim 边界收敛
- **当前问题**：不能再声称"TSIP 保证设备在场真实性（ground-truth presence）"
- **修改方案**：统一使用"trajectory continuity/plausibility filtering + attack-cost elevation"
- **状态**：主口径已收敛，但论文各章节的措辞需要逐段检查

#### 4.1.3 DP 叙事收敛
- **当前问题**：需要明确"Public-output DP"口径，internal leakage 单列
- **需要补的材料**：
  - `who learns what` 泄露表：Shuffler 看到什么、Aggregator 看到什么、Decoder 看到什么
  - SVT 引用定理与你的实现的逐条对齐

### 4.2 🟡 P1 修改（强烈建议）

#### 4.2.1 身份绑定增强
- **当前问题**：A2 身份交换攻击的防御依赖"攻击者不知道对方坐标"，这不是密码学级别的保证
- **修改方案**：引入 hidden per-user secret + epoch/nullifier，使得攻击者即使知道对方坐标也无法伪造对方的承诺链
- **论文影响**：如果不做，需要在 Threat Model 中明确声明"不考虑共谋攻击者"

#### 4.2.2 协议状态机形式化
- 需要明确定义：fork / double-submit / late arrival / missed round / re-enrollment 的处理语义
- 目前代码中已有黑名单和窗口检查，但论文中需要形式化描述

#### 4.2.3 安全证明补全
- 当前安全证明不完整，需要补齐：
  - **Theorem 1 (Soundness)**：如果 TSIP 证明通过，则轨迹满足距离约束（reduction to Groth16 soundness）
  - **Theorem 2 (Zero-Knowledge)**：证明过程不泄露具体位置（由 Groth16 的 ZK 性质直接继承）
  - **Theorem 3 (DP Guarantee)**：最终输出满足 (ε, δ)-DP（SVT + Laplace 组合定理）

### 4.3 🟢 P2 修改（建议）

- Poseidon helper 原生实现替换（性能优化，非阻塞）
- 黑名单持久化（跨轮保留，非阻塞）
- Committee 模式实验验证（多 Shuffler 场景）

---

## 五、论文结构建议（含写作优先级）

### 推荐论文结构

```
§1 Introduction (2 pages)
   - 问题动机：跨窗口位置欺骗攻击
   - 现有方案的缺口
   - TSIP 的贡献（3 点）

§2 Background & Problem Formulation (1.5 pages)
   - ZK-SNARKs 基础
   - DP 基础
   - 系统模型 + 威胁模型
   - 问题定义

§3 TSIP Protocol Design (3 pages)
   - 系统架构（ESA + ZK）
   - 承诺链机制
   - ZK 电路设计
   - DP 层设计
   - Proof-Payload Binding

§4 Security Analysis (2.5 pages)
   - Theorem 1-3 + 证明
   - 攻击分析（A1-A6）
   - Claim 边界声明

§5 Implementation (1 page)
   - 系统实现
   - 电路统计
   - 部署配置

§6 Evaluation (3 pages)
   6.1 Setup（数据集/Baselines/指标/硬件）
   6.2 Attack Defense（A1-A6 TPR 对比）
   6.3 Baseline 对比（TSIP vs No-Integrity vs Commitment-Only vs Pure LDP）
   6.4 Privacy-Utility Tradeoff（ε vs Jaccard）
   6.5 Scalability（200/500/1000）
   6.6 Ablation Study
   6.7 Overhead Analysis

§7 Related Work (1.5 pages)
   7.1 DP for Location Data
   7.2 Integrity Verification in Aggregation
   7.3 ZKP for Location Privacy

§8 Discussion & Limitations (0.5 pages)
§9 Conclusion (0.3 pages)
```

### 写作优先级

| 优先级 | 章节 | 理由 |
|-------|------|------|
| 第 1 批 | §3 Protocol Design + §4 Security Analysis | 这是论文的技术核心，也是审稿人最关注的 |
| 第 2 批 | §6 Evaluation | 需要所有实验数据就绪 |
| 第 3 批 | §1 Introduction + §2 Background | 等协议和实验定稿后再打磨叙事 |
| 第 4 批 | §7 Related Work + §8 Discussion | 最后写，确保所有 claim 已收敛 |

---

## 六、投稿时间线建议

### 目标会议

| 会议 | DDL（预估） | 匹配度 | 建议 |
|------|-----------|-------|------|
| **NDSS 2027 Cycle 2** | 2026 年 6-7 月 | ⭐⭐⭐⭐⭐ | 最佳目标，对系统+隐私友好 |
| **PETS 2027** | 2026 年 8 月 | ⭐⭐⭐⭐⭐ | 隐私方向最佳匹配，审稿态度友好 |
| **USENIX Security 2027** | 2026 年 9-10 月 | ⭐⭐⭐⭐ | 偏系统安全，原型是加分项 |
| **CCS 2027** | 2026 年底-2027 年初 | ⭐⭐⭐⭐ | 理论创新要求高 |

### 倒推时间线（以 NDSS 2027 Cycle 2 = 2026/07/01 为目标）

| 日期 | 任务 | 产出 |
|------|------|------|
| 4/9 - 4/15 | Proof-payload binding v1 实现 + utility 指标框架搭建 | 代码 + 初步 Jaccard 数据 |
| 4/16 - 4/22 | Commitment-Only baseline + DP ε sweep + latency breakdown | 3 组新实验数据 |
| 4/23 - 4/30 | RiseFL-style baseline + 消融实验 + money figure | 完整 baseline 对比表 |
| 5/1 - 5/7 | 安全证明完整化（Theorem 1-3） | 定理 + 证明草稿 |
| 5/8 - 5/14 | 论文 §3-§4 初稿 | 5.5 页 |
| 5/15 - 5/21 | 论文 §6 初稿（含所有图表） | 3 页 |
| 5/22 - 5/28 | 论文 §1-§2 + §7-§9 初稿 | 全文初稿 |
| 5/29 - 6/7 | 全文打磨 + 导师审阅 | 第二稿 |
| 6/8 - 6/14 | 根据反馈修订 | 第三稿 |
| 6/15 - 6/21 | 格式调整 + artifact 准备 | 投稿版 |
| 6/22 - 6/30 | Buffer + 提交 | 提交 |

---

## 七、快速行动清单（本周 4/9-4/15）

1. **立即开始**：搭建 Utility 指标框架（ground truth 热力图生成 + Jaccard 计算脚本）
2. **同步进行**：实现 Proof-Payload Binding v1（payload_digest + attestation 签名）
3. **同步进行**：准备 Commitment-Only baseline 的实验配置
4. **阅读**：精读 RiseFL 和 EIFFeL 的论文，理解它们的实验设计和叙事方式
5. **开始写**：Related Work 章节草稿（利用本文档的文献分类）

---

## 附录：关键文献引用列表

```bibtex
% DP for Location
@inproceedings{nebula2022,
  title={Nebula: Efficient, Private and Accurate Histogram Estimation},
  author={Shamsabadi et al.},
  booktitle={SIGMOD},
  year={2022}
}

@inproceedings{rappor2014,
  title={RAPPOR: Randomized Aggregatable Privacy-Preserving Ordinal Response},
  author={Erlingsson, Úlfar and Pihur, Vasyl and Korolova, Aleksandra},
  booktitle={CCS},
  year={2014}
}

@inproceedings{prochlo2017,
  title={Prochlo: Strong Privacy for Analytics in the Crowd},
  author={Bittau, Andrea and others},
  booktitle={SOSP},
  year={2017}
}

% Integrity Verification
@inproceedings{risefl2024,
  title={RiseFL: Secure and Verifiable Federated Learning},
  author={Xiao et al.},
  booktitle={NDSS / PVLDB},
  year={2024}
}

@inproceedings{eiffel2022,
  title={EIFFeL: Ensuring Integrity for Federated Learning},
  author={Roy Chowdhury, Amrita and others},
  booktitle={CCS},
  year={2022}
}

@inproceedings{verifynet2020,
  title={VerifyNet: Secure and Verifiable Federated Learning},
  author={Xu et al.},
  journal={IEEE TIFS},
  year={2020}
}

@inproceedings{zksl2026,
  title={ZKSL: Verifiable and Efficient Split FL via Asynchronous ZKP},
  booktitle={NDSS},
  year={2026}
}

@inproceedings{fltrust2021,
  title={FLTrust: Byzantine-robust FL via Trust Bootstrapping},
  author={Cao et al.},
  booktitle={NDSS},
  year={2021}
}

% ZKP Foundations
@inproceedings{groth16,
  title={On the Size of Pairing-Based Non-interactive Arguments},
  author={Groth, Jens},
  booktitle={EUROCRYPT},
  year={2016}
}

@inproceedings{poseidon2021,
  title={Poseidon: A New Hash Function for ZK-Proof Systems},
  author={Grassi et al.},
  booktitle={USENIX Security},
  year={2021}
}

% Secure Aggregation
@inproceedings{secagg2017,
  title={Practical Secure Aggregation for Privacy-Preserving ML},
  author={Bonawitz et al.},
  booktitle={CCS},
  year={2017}
}

% ZK for Location
@inproceedings{zkpol2020,
  title={Blockchain Based Zero-Knowledge Proof of Location in IoT},
  author={Wu et al.},
  journal={IEEE IoT Journal},
  year={2020}
}

% DP Foundations
@book{dpfoundations2014,
  title={The Algorithmic Foundations of Differential Privacy},
  author={Dwork, Cynthia and Roth, Aaron},
  year={2014}
}

% LDP for Trajectory
@inproceedings{ldptraj2021,
  title={Real-World Trajectory Sharing with LDP},
  author={Cunningham et al.},
  booktitle={PVLDB},
  year={2021}
}

@inproceedings{ldptraj2023,
  title={Trajectory Data Collection with LDP},
  booktitle={PVLDB},
  year={2023}
}

% Datasets
@article{geolife,
  title={GeoLife GPS Trajectory Dataset},
  author={Zheng, Yu and others},
  year={2010}
}

@article{tdrive,
  title={T-Drive: Driving Directions Based on Taxi Trajectories},
  author={Yuan, Jing and others},
  year={2010}
}
```
