# TSIP 实验计划

**生成日期：2026-03-28**
**当前状态：GeoLife 服务器修复版 10 轮已同步进行中**

---

## 一、当前已完成的工作盘点

| 类别 | 已完成项 | 可用于论文 |
|------|---------|-----------|
| 核心实验 | 合成数据 10 轮 + 30 轮（服务器修复版），malicious_reject_rate=1.0, false_reject_rate=0.0017 | ✅ 主结果 |
| 真实数据 | GeoLife 本地 10 轮（修复前），malicious_reject_rate=1.0, false_reject_rate=0.0043 | ⚠️ 需重跑修复版 |
| **攻防评估** | **T-Drive boundary sweep（7档距离，10轮）：阈值以上100%检测，误拒率~3.5%** | **✅ 已完成 2026-04-05** |
| **攻防评估** | **Synthetic boundary sweep（7档距离，10轮）：阈值以上74-83%检测，误拒率0%** | **✅ 已完成 2026-04-01** |
| **攻防评估** | **A3 gradual drift（服务器初版，Synthetic fixed seeds，30轮）：0%恶意拒绝、0%误拒、累计偏移约2.6-2.7km** | **⚠️ 已完成 2026-04-07，可用于 Limitation，强度曲线待补** |
| **攻防评估** | **T-Drive 恶意比例 sweep（7200m，5档比例，10轮）：完成 Full TSIP / Commitment-Only / No-TSIP 三路对照；仅 Full TSIP 保持 100% 恶意拦截** | **✅ 已完成 2026-04-09** |
| 可视化 | S 型检测曲线（synthetic + T-Drive 双线），见 `experiments/tsip_scurve.png` | ✅ 已完成 2026-04-05 |
| 参数调优 | 60s/110 vs 300s/100 对照实验，确认 60s/110 为最优 | ✅ |
| ZK 基准 | snarkjs vs rapidsnark 对照，prove 时间 1.15s → 0.31s | ✅ |
| 规模验证 | CLIENT_TOTAL=500 单次验证通过 | ⚠️ 缺多轮统计 |
| 系统部署 | 远程 CPU-only 服务器全链路闭环 | ✅ |
| 单元测试 | 黑名单、承诺链、DP budget、secure reconstruct | ✅ |

---

## 二、还需要进行的实验（按优先级排序）

### 🔴 P0：

#### 实验 1：服务器 GeoLife 10 轮（修复版）
- **为什么必须做**：当前 GeoLife 结果是 Poseidon2 修复前的，审稿人会质疑真实数据结果的可信度
- **预期耗时**：2-3 小时（含部署 + 运行）
- **命令**：
```bash
ROUNDS=10 CLIENT_TRAJ_SOURCE=geolife \
GEO_TRAJ_PATH=/app/experiments/geolife_tsip_ready_50u.jsonl \
CLIENT_TOTAL=50 BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
```

#### 实验 2：规模扩展实验（200/500/1000 客户端，每档 5 轮）
- **为什么必须做**：顶会审稿人一定会问 "Does it scale?"，这是 scalability 章节的核心数据
- **需要展示**：随客户端数增加，malicious_reject_rate 保持 1.0，false_reject_rate 不显著增长，端到端时延线性增长
- **预期耗时**：4-6 小时
- **命令**：
```bash
TOTALS="200 500 1000" ROUNDS_PER_SCALE=5 BUILD_FIRST=0 \
bash script/run_scale_sweep.sh
```

#### 实验 3：恶意比例敏感性实验（Malicious Ratio Sweep）✅ 已完成（三路对照，服务器正式结果，2026-04-08/09）
- **目的**：回答 “What happens at 30%? 50% malicious users?”，并通过 `Full TSIP / Commitment-Only / No-TSIP` 三路对照区分“commitment 链作用”和“ZK 距离验证作用”。
- **配置**：`T-Drive`，`ATTACK_TYPE=boundary_teleport`，`TELEPORT_JUMP_M=7200m`，`TSIP_USER_SCOPE=stable`，`WARMUP_ROUNDS=1`，`TSIP_MAX_GAP_WINDOWS=1000`，`TSIP_BLACKLIST_THRESHOLD=0`，10 rounds × 50 clients。

| Malicious Rate | Full TSIP MRR | Full TSIP FRR | Commitment-Only MRR | Commitment-Only FRR | No-TSIP MRR | No-TSIP FRR |
|---------------|---------------|---------------|---------------------|---------------------|-------------|-------------|
| 0.05 | 1.0000 | 0.0378 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 0.10 | 1.0000 | 0.0402 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 0.20 | 1.0000 | 0.0412 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 0.30 | 1.0000 | 0.0345 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 0.50 | 1.0000 | 0.0522 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

![T-Drive 7200m mode comparison](experiments/tsip_mode_comparison_7200m.png)

- **结论**：
  - `Full TSIP` 在恶意比例从 `5%` 到 `50%` 时，`avg_malicious_reject_rate` 全程保持 `1.0000`；
  - `avg_false_reject_rate` 仅在 `0.0345 ~ 0.0522` 范围内波动，说明高恶意占比下检测鲁棒性仍稳定；
  - `Commitment-Only` 与 `No-TSIP` 均为 `0.0000` 恶意拦截、`0.0000` 误拒，说明 commitment 链本身不能检测 `7200m` teleport，真正提供检测能力的是 ZK 距离验证。

### 🟡 P1：强烈建议完成

#### 实验 4：攻防对照实验（Attack & Defense Evaluation）
- **你确实需要攻防实验！** 这是投顶会的关键差异化实验。
- **需要设计的攻击类型**：

| 攻击类型 | 描述 | 预期结果 |
|---------|------|---------|
| **A1: 瞬移攻击 (Teleportation)** | 恶意客户端在连续窗口间报告不可能的距离跳跃 | TSIP 100% 拦截 ✅（已验证） |
| **A2: 身份交换攻击 (Identity Swap)** | 两个串谋客户端在某轮交换 user_id | TSIP 应在下一轮通过承诺链不匹配拦截 |
| **A3: 渐进式偏移攻击 (Gradual Drift)** | 恶意客户端每步移动刚好低于 v_max，但总位移不合理 | **服务器初版已完成**：三档 bias 均 `0%` 恶意拒绝、`0%` 误拒；可作为 limitation 证据，强度曲线待补 |
| **A4: Sybil 攻击 (Sybil + 集中报告)** | 大量假 ID 在某区域集中报告 | DP 层可缓解，展示 DP 前后对比 |
| **A5: 重放攻击 (Replay)** | 重放之前轮次的合法证明 | 承诺链 + window_id 检查应拦截 |
| **A6: 伪造证明攻击 (Proof Forgery)** | 提交非法 ZK 证明 | snarkjs verify 拒绝 |

- **实现方式**：在 `client.py` 中增加攻击模式参数，例如 `ATTACK_MODE=teleport|swap|drift|sybil|replay|forge`
- **预期耗时**：5-7 天（设计 + 实现 + 运行 + 分析） 

#### 实验 5：Baseline 对比实验
| Baseline | 对比维度 | 你的优势 |
|----------|---------|---------|
| **RiseFL (无 TSIP)** | 恶意拦截率 | RiseFL 无法检测跨窗口攻击，你可以 |
| **纯 DP (无验证)** | 数据质量 (utility) | 纯 DP 在恶意注入下 utility 大幅下降 |
| **无 ZK 的统计检验** | 隐私保护 | 统计检验需暴露原始轨迹，你不需要 |
| **中心化验证** | 隐私 + 开销 | 中心化方案泄露所有位置 |

- **最低要求**：至少做 RiseFL (无 TSIP) vs TSIP 的对比
- **预期耗时**：3-5 天

#### 实验 6：T-Drive 数据集实验 ✅ 已完成（服务器正式结果，2026-04-05/06）

**Boundary Sweep 结果（远程 CPU-only 服务器，stable scope, warmup=1, TSIP enabled, `TSIP_MAX_GAP_WINDOWS=1000`, `TSIP_BLACKLIST_THRESHOLD=0`, 10 rounds × 50 clients）：**

| 跳跃距离 | avg_valid_clients | malicious_reject_rate | false_reject_rate | 说明 |
|---------|-------------------|----------------------|-------------------|------|
| 1000m | 48.40 | 0.0000 | 0.0355 | 阈值内，完全漏检（符合预期） |
| 3300m | 48.80 | 0.0000 | 0.0261 | 阈值内，完全漏检（符合预期） |
| 5940m | 49.40 | 0.0000 | 0.0133 | 阈值内，完全漏检（符合预期） |
| 6534m | 47.90 | 0.0000 | 0.0470 | 0.99× 阈值，漏检（符合预期） |
| 6600m | 48.80 | 0.0000 | 0.0264 | 刚好在阈值处，仍被接受 |
| **6666m** | **42.90** | **1.0000** | 0.0357 | 1.01× 阈值，**完全检测** ✅ |
| **7200m** | **42.90** | **1.0000** | 0.0407 | 1.09× 阈值，**完全检测** ✅ |

**与 Synthetic 的关键差异：**
- T-Drive 在 6666m 和 7200m 均达到 **100% 检测率**（Synthetic 分别为 74% 和 83%），因为真实轨迹不触发城市边界截断 bug
- T-Drive 存在 **~2-5% 的恒定误拒率**（Synthetic 为 0%），原因是真实出租车轨迹中存在 GPS 中断后补录等正常大跨度移动，超出 TSIP 距离约束

**S 型检测曲线：** 见 `experiments/tsip_scurve.png`

**结论：** 服务器正式结果表明检测阈值与当前工程参数一致，即 `6600m = 110 * 60`。`<=6600m` 时恶意拒绝率为 `0%`，`>=6666m` 时恶意拒绝率为 `100%`，呈清晰阶跃。误拒率约 `1.3%~4.7%`，均值约 `3.2%`，是 T-Drive 真实轨迹中少量合法大跨度移动带来的固有代价。

**论文可用性：** ✅ 可直接用于 Security Evaluation 章节，与 Synthetic 结果互为补充。

#### 实验 6.5：A3 渐进式偏移攻击（服务器初版，2026-04-07）

**配置（远程 CPU-only 服务器）：**
- `ATTACK_TYPE=gradual_drift`
- `CLIENT_TRAJ_SOURCE=synthetic`
- `FIXED_SYNTHETIC_SEEDS=1`
- `EXPERIMENT_SEED_BASE=20260407`
- `TSIP_USER_SCOPE=stable`
- `MALICIOUS_SCOPE=stable`
- `WARMUP_ROUNDS=1`
- `ROUNDS=30`
- `CLIENT_TOTAL=50`
- `MALICIOUS_RATE=0.1`
- `SHUFFLER_TSIP_ENABLE=1`
- `CLIENT_TSIP_ENABLE=1`
- `SHUFFLER_ZK_STEP_ENABLE=0`
- `CLIENT_ZK_STEP_ENABLE=0`
- 由于服务器镜像拉取超时，本轮使用 `TSIP_PROVER=snarkjs`、`ZK_STEP_PROVER=snarkjs`

**结果（`experiments/a3_drift_fixed_bias*.log`）：**

| Bias Ratio | avg_malicious_reject_rate | avg_false_reject_rate | gradual_drift_offset_avg_m | gradual_drift_offset_max_m |
|-----------|---------------------------|-----------------------|----------------------------|----------------------------|
| 0.30 | 0.0000 | 0.0000 | 2635.20 | 3959.80 |
| 0.60 | 0.0000 | 0.0000 | 2708.96 | 3959.80 |
| 0.90 | 0.0000 | 0.0000 | 2573.30 | 3959.80 |

**当前可得结论：**
- `gradual_drift` 在服务器上可稳定绕过 TSIP 的单步连续性检查；
- 三档 bias 均实现 `0%` 恶意拒绝与 `0%` 误拒；
- 平均累计偏移处于 `2.57-2.71km` 量级，足以说明 slow-drift 攻击可在不触发 TSIP 的前提下造成显著偏移；
- 但三档 bias 的平均偏移尚未形成干净单调趋势，因此本轮结果适合写入 **Discussion / Limitation**，不宜直接写成“强度响应曲线”。

### 🟢 P2：锦上添花

#### 实验 7：DP 参数 (epsilon) 敏感性实验
- 在不同 epsilon 值（0.1, 0.5, 1.0, 2.0, 5.0）下，展示 privacy-utility tradeoff
- 预期耗时：1-2 天

#### 实验 8：端到端延迟分解实验（Latency Breakdown）
- 将总延迟分解为：proof generation → network → verification → aggregation → DP
- 画出 stacked bar chart，让审稿人看到各阶段的开销分布
- 预期耗时：1 天

---

## 三、方案不完善的地方（审稿人可能质疑的点）

### 🔴 关键不足

1. **缺乏形式化安全证明**
   - 当前安全证明文本仍基于理想化假设，未完全对齐当前 Poseidon2 + zk_step + 黑名单的实际实现
   - **影响**：顶会（CCS/S&P/USENIX Security/NDSS）对安全证明要求极严，不完整的证明直接导致 reject
   - **行动**：必须写出完整的 Theorem + Proof，覆盖 Soundness、Zero-Knowledge、Privacy

2. **渐进式偏移攻击的 Limitation 未讨论**
   - TSIP 只验证相邻步的速度约束，无法检测长期缓慢偏移
   - **行动**：在论文中诚实讨论这个 limitation，并提出可能的扩展方向（如滑动窗口累积约束）

3. **单 Shuffler 信任假设**
   - 当前部署是单 shuffler，虽有 committee 模式代码但未在实验中验证
   - **行动**：至少在 threat model 中明确讨论，或补一组 committee 模式实验

4. **Groth16 的 trusted setup 问题**
   - Groth16 需要可信设置，这是已知 limitation
   - **行动**：在论文中讨论，并提到可替换为 PLONK 等 universal setup 方案

### 🟡 中等不足

5. **实验规模偏小**
   - 当前最大 500 客户端，真实城市场景可能需要数万
   - **行动**：规模扩展实验 + 理论复杂度分析来说明线性可扩展性

6. **Verify 时间偏长**（snarkjs ~1.03s）
   - 对比其他 ZK 系统（Plonk、Halo2）的 verify 时间，snarkjs 的实现效率不是最优
   - **行动**：说明这是工程实现层面的问题，不是协议本身的瓶颈；提到可用 native verifier 替换

7. **缺乏与 state-of-the-art 的定量对比**
   - 论文中需要一张 comparison table 对比 RiseFL、Nebula、Prochlo 等
   - **行动**：补充 related work comparison table

---

## 四、攻防实验：你是否需要？—— 答案是必须要

对于投安全方向顶会（CCS/S&P/USENIX Security/NDSS），攻防实验不是 "nice to have"，而是 **必需的**。

**最低要求（P0）**：
- A1 瞬移攻击（已有数据，需规范化展示）
- A5 重放攻击（实现简单，1 天内可完成）
- A6 伪造证明攻击（已有验证逻辑，需转为实验数据）

**建议完成（P1）**：
- A2 身份交换攻击（你的论文动机场景，必须验证）
- A4 Sybil 攻击（展示 DP 层的防御价值）

**讨论即可（P2）**：
- A3 渐进式偏移攻击的强度响应曲线（当前服务器初版已足够支撑 limitation 讨论，但若要画 bias-response curve 仍需补低噪声终态偏移实验）

---

## 五、方案亮点（审稿人可能 accept 的理由）

1. **解决了一个真实且未被充分解决的问题**
   - 跨时间窗口的位置欺骗攻击是 RiseFL 等现有方案的已知盲区
   - 你提出的 TSIP 是第一个用 ZK 证明来填补这个缺口的方案
   - **审稿人心理**：问题重要 + 解决方案 novel = 强 contribution

2. **端到端系统实现 + 真实部署验证**
   - 不是纯理论论文，有完整的 5 服务微架构、Docker 部署、远程服务器验证
   - **审稿人心理**：顶会越来越重视 practical systems，你有完整原型 = 强 artifact

3. **ZK + DP + MPC 的组合创新**
   - TSIP 证明（ZK）+ 安全聚合（MPC/secret sharing）+ 差分隐私（DP）三层防护
   - 很少有工作同时处理 integrity + privacy + utility
   - **审稿人心理**：三位一体 = 完整的 security story

4. **100% 恶意拦截率 + 接近 0 的误拒率**
   - 在 30 轮实验中持续保持 malicious_reject_rate=1.0, false_reject_rate=0.0017
   - **审稿人心理**：实验结果干净漂亮 = 方案确实 work

5. **承诺链机制的设计**
   - Poseidon2 位置承诺 + MiMC7 链承诺 + 黑名单的组合，工程设计精巧
   - 解决了"首轮冷启动"问题（warm-up 轮）

---

## 六、目前最大的不足是什么？

如果只能说一个，最大的不足是：

> **缺乏完整的形式化安全证明 + 与 baseline 的定量对比实验。**

顶会审稿人的判断逻辑是：

1. 问题重要吗？→ ✅（跨窗口攻击是真实威胁）
2. 方案是否 novel？→ ✅（TSIP = ZK + 承诺链）
3. 安全性能否被形式化证明？→ ❌（当前不完整）
4. 实验是否与 baseline 做了公平对比？→ ❌（缺少）
5. 系统是否实用？→ ✅（有原型 + 部署）

缺的 3 和 4 恰好是顶会最在意的两个维度。**补上这两个，accept 概率会大幅提升。**

---

## 七、最大化 Accept 的逐步行动计划

### 阶段 1：补齐核心实验（1-2 周）

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1 | 服务器 GeoLife 10 轮（修复版） | GeoLife 主结果 CSV |
| Day 2-3 | 规模扩展实验 200/500/1000 | Scalability 数据 |
| Day 3-4 | 恶意比例 Sweep（5%/10%/20%/30%/50%） | Robustness 数据 |
| Day 5-7 | 攻防实验 A1/A2/A5/A6 实现 + 运行 | Security evaluation 数据 |
| Day 8-9 | Baseline 对比（至少 RiseFL 无 TSIP vs TSIP） | Comparison table |
| Day 10 | DP epsilon 敏感性 + 延迟分解 | Privacy-utility tradeoff 图 |

### 阶段 2：形式化安全证明（1-2 周）

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-3 | 定义 Threat Model + Security Game | Definition 1-3 |
| Day 4-6 | Soundness Proof（TSIP 证明的完备性） | Theorem 1 + Proof |
| Day 7-9 | Zero-Knowledge Proof（不泄露位置） | Theorem 2 + Proof |
| Day 10-12 | Privacy Proof（DP 组合定理） | Theorem 3 + Proof |
| Day 13-14 | 同行 review + 修订 | 定稿 |

### 阶段 3：论文撰写（2-3 周）

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-2 | Introduction + Motivation（Cross-Window Attack 场景） | 2 页 |
| Day 3-4 | System Model + Threat Model | 1.5 页 |
| Day 5-7 | TSIP Protocol Design（电路 + 承诺链 + 验证流程） | 3 页 |
| Day 8-10 | Security Analysis（形式化证明） | 2.5 页 |
| Day 11-14 | Evaluation（所有实验结果 + 图表） | 3 页 |
| Day 15-16 | Related Work + Conclusion | 1.5 页 |
| Day 17-18 | 全文打磨 + 格式调整 | 14 页 |
| Day 19-21 | 导师 review + 修订 + 最终提交 | 定稿 |

### 阶段 4：投稿前检查清单

- [ ] 所有实验结果文件已归档，可复现
- [ ] 安全证明已由至少一位同行审阅
- [ ] 与至少 3 个 baseline 做了定量对比
- [ ] 论文中诚实讨论了所有 known limitations
- [ ] 图表清晰、表格完整、符号一致
- [ ] Artifact 准备好（代码 + 数据 + 运行脚本），方便 artifact evaluation
- [ ] 选定投稿目标（CCS/NDSS/USENIX Security/S&P），确认 DDL 和格式要求

---

## 八、推荐投稿目标与时间线

| 会议 | 下一个 DDL（预估） | 匹配度 | 理由 |
|------|-------------------|--------|------|
| **NDSS 2027** | 2026 年 6-7 月 | ⭐⭐⭐⭐⭐ | 网络安全 + 隐私方向，对系统实现友好 |
| **CCS 2026** | 2026 年 5 月（如有第二轮） | ⭐⭐⭐⭐ | 安全顶会，ZK + Privacy 是热门 track |
| **USENIX Security 2027** | 2026 年 9-10 月 | ⭐⭐⭐⭐ | 偏系统安全，你的原型是加分项 |
| **S&P 2027** | 2026 年 6 月或 12 月 | ⭐⭐⭐ | 最顶级，竞争最激烈，安全证明要求最高 |
| **PETS 2027** | 2026 年 8 月 | ⭐⭐⭐⭐⭐ | 隐私增强技术专会，与你的方向完美匹配 |

**建议策略**：
- 如果 5-6 周内能补完所有实验 + 安全证明，优先投 **CCS 2026 第二轮** 或 **NDSS 2027**
- 如果需要更多时间打磨，投 **PETS 2027** 或 **USENIX Security 2027**
- PETS 虽不算"四大安全顶会"，但在隐私方向影响力很高，匹配度最好，且对系统实现论文非常友好

---

## 九、你现在的第一步

既然你已经在跑 GeoLife 服务器修复版 10 轮，等它结束后：

1. **立即开始规模扩展实验**（`run_scale_sweep.sh`）
2. **同时** 开始设计恶意比例 sweep 脚本（可以并行准备）
3. **同时** 开始写攻防实验的攻击模式代码（`ATTACK_MODE` 参数）

这三件事可以并行推进，不互相阻塞。
