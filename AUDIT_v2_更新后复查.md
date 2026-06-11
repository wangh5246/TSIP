# TSIP 设计文档复查报告（更新版）

> 复查日期：2026-04-12
> 对比对象：上传的最新 `TSIP_完整设计方案.md` vs 实际代码 + 上一轮审计清单

---

## 上一轮问题修复状态

| 编号 | 问题 | 状态 | 说明 |
|------|------|------|------|
| S1 | §5.5.1 电路仍为 v1 | ✅ **已修复** | 现在展示完整 TSIPMain（5 public, 8 witness, P4+P5 强制约束），注释明确"非可选" |
| S2 | Theorem 3 public inputs/witness 未更新 | ✅ **已修复** | x 已列出 5 个 public inputs，w 已列出 8 个 witness，模拟器含完整 8 维 fake_witness |
| S3 | Theorem 1 P4/P5 标为可选 + 密码学假设错误 | ✅ **已修复** | 条件 (v)(vi) 改为 "Poseidon collision resistance"，注释明确"强制约束" |
| S4 | 导入路径和 pragma 不匹配 | ✅ **已修复** | 已统一为 `pragma circom 2.1.9` + `circomlib/circuits/...` |
| M1 | §5 协议规范缺 P4/P5 | ✅ **已修复** | §5.2 数据结构含 payload/secret_commitment 字段，§5.3.3 新增完整 P4/P5 客户端流程，§5.4 服务端校验含 public_signals[3]/[4] 检查 |
| M2 | poseidon vs poseidon2 术语混淆 | ✅ **已修复** | §5.1 HASH_FUNCTION 改为 "poseidon2 + mimc7 + circom-poseidon2" 并加注释说明 |
| M3 | Theorem 1 证明缺 Case 4/5 | ✅ **已修复** | 证明结构增加 Case 4 (P4 payload) 和 Case 5 (P5 secret)，union bound 含 E1-E5 |
| M4 | 通信分析未含 v2 公开输入开销 | ✅ **已修复** | §6.5 行 2878-2879 明确 "5 个 field elements（多 2 个）" |
| M5 | §7.6/7.7 混有工程代码路径 | ⚠️ **部分修复** | P4/P5 节已简化为"电路级主口径"描述，但仍有个别 `app.py` 引用（可接受） |
| M6 | §8.3 Baseline 描述不完整 | ✅ **已修复** | §8.3.0 新增统一参数表 + 7 种 Baseline 的形式化定义表 |
| L1 | §9 论文指南时间线过时 | ❌ **未修** | 仍假设电路实现尚未开始（非关键） |
| L2 | §2.4 教学电路是 v1 | ❌ **未修** | 仍是 3-input 教学示例（可接受，作为引入） |

---

## 本轮发现的新问题

### 🔴 N1. Theorem 3 不可区分性论证仍使用 DDH 假设——这对 Groth16 是错误的

**位置**：行 2860

**文档写的**：
```
|Pr[D(Real) = 1] - Pr[D(Sim) = 1]|
≤ Adv_DDH(λ)  (依赖于DDH假设)
```

**正确的假设**：
Groth16 的零知识性不依赖 DDH。原文 [Groth16, EUROCRYPT 2016] Theorem 1 的零知识性证明在 **generic group model** 下完成。具体地，Groth16 proof 的不可区分性来自于配对群 (G₁, G₂, G_T) 的 generic group 性质，而非标准 DDH 假设。

DDH 在配对群中实际上是 **不成立的**（因为 `e(g, g)` 打破了标准 DDH），所以写 "≤ Adv_DDH(λ)" 在密码学上是错误的。

**同时**，§6.6 安全性总结表格（行 2914）也写了 "DDH 假设"：
```
| Theorem 3 | Zero-Knowledge | 证明不泄露 witness | DDH 假设 |
```

**修复**：
1. 将行 2860 改为：
   ```
   ≤ negl(λ)  (在 generic group model 下成立，见 [Groth16] Theorem 1)
   ```
2. 将行 2914 的 "DDH 假设" 改为 "Generic group model (pairing-based)"

---

### 🟡 N2. Poseidon2 命名可能误导 NDSS 审稿人

**背景确认**：
我已验证 `circuits/poseidon2_bench.circom` 内部调用的是 `circomlib/circuits/poseidon.circom` 的 `Poseidon(2)`，即**标准 Poseidon 哈希取 2 输入**。所以项目中 "Poseidon2" 的含义是 "Poseidon with arity 2"，而不是 Horizen Labs 2023 年提出的 "Poseidon2" 新哈希函数（不同的轮结构和安全分析）。

**风险**：学术论文中写 "Poseidon2" 可能让审稿人以为你用的是 2023 年的新函数，进而质疑安全分析引用的是哪篇论文。

**建议**：
- 论文中统一称为 **"Poseidon hash with 2 inputs"** 或直接写 **"Poseidon"**
- §5.1 的 `HASH_FUNCTION = "poseidon2 + mimc7 + circom-poseidon2"` 可改为：
  ```
  HASH_FUNCTION = "Poseidon(2-ary) + MiMC7"
  ```
- 引用 [Grassi+21] USENIX Security 2021 的 Poseidon 论文即可

---

### 🟡 N3. Theorem 2 声称 (ε, δ)-DP 但证明过程只用了纯 ε-DP 组合

**位置**：行 2458-2463

**文档写的**：
```
TSIP satisfies (ε, δ)-DP on M_pub with:
  ε = ε_SVT + ε_value
  δ = 10^{-8}
```

**问题**：证明过程（行 2526-2544）只使用了标准顺序组合 `ε = ε_SVT + ε_value = 1.0`，这是纯 ε-DP 组合。但定理声称 δ = 10^{-8}。

如果 SVT 和 Laplace 机制都是纯 ε-DP（Laplace 确实是），那么组合后也是纯 ε-DP（δ = 0），不需要 δ。写 δ = 10^{-8} 反而会让审稿人追问这个 δ 从何而来。

**两种修复方案**：
- 方案 A：如果确实只用纯 Laplace + SVT，将定理改为纯 ε-DP（删除 δ），更简洁有力
- 方案 B：如果 δ 来自 Gaussian noise 或高级组合（advanced composition），需在证明中明确其来源

查看 `.env.example` 中 `DP_DELTA` 默认值可以确认意图。

---

### 🟡 N4. §6.3.5 "主定理分步解释" 与 §6.3.3 "主定理证明" 内容重复

**位置**：行 2505-2552（§6.3.3）和行 2626-2700（§6.3.5）

**问题**：两节内容高度重叠——都是 Theorem 2 的分步证明，只是详细程度略有不同。论文撰写时只需要一个版本。

**建议**：保留 §6.3.3（更简洁），删除 §6.3.5 或将其标注为"扩展解释（不入论文主文）"。

---

### 🟢 N5. §5.5.2 编译脚本仍引用 `tsip_main` 而非 `tsip_main_v2`

**位置**：行 2077

```bash
CIRCUIT_NAME="tsip_main"
```

**问题**：§5.5.1 已经统一为 TSIPMain（v2 电路），但编译脚本仍写 `tsip_main`。虽然不影响论文内容，但如果有人按文档复现会编译错误的电路。

**修复**：改为 `CIRCUIT_NAME="tsip_main_v2"` 或在实际代码中将 v2 电路重命名为 `tsip_main.circom`。

---

### 🟢 N6. §2.4 教学电路仍只有 3 个 public inputs

**位置**：行 570+

这是教学引入章节，展示的是简化版电路。可以保留，但建议在节末加一句："完整电路含 5 个公开输入和 8 个 witness，详见 §5.5.1。"

---

## 总结

| 优先级 | 编号 | 问题 | 修复时间 |
|--------|------|------|---------|
| 🔴 | N1 | Theorem 3 DDH 假设错误 → 应为 generic group model | 10 分钟 |
| 🟡 | N2 | "Poseidon2" 命名可能误导审稿人 | 15 分钟 |
| 🟡 | N3 | Theorem 2 声称 (ε,δ)-DP 但证明只用纯 ε-DP | 20 分钟 |
| 🟡 | N4 | §6.3.3 和 §6.3.5 重复 | 5 分钟 |
| 🟢 | N5 | 编译脚本引用旧电路名 | 2 分钟 |
| 🟢 | N6 | §2.4 教学电路缺尾注 | 2 分钟 |

**结论**：上一轮的 4 个严重问题和 5 个中等问题全部修复或实质性改善。剩余 1 个严重问题（N1 DDH 假设）需要立即修复——这是密码学硬伤，NDSS 审稿人一定会抓住。其余均为改善性建议。

修完 N1 后，这份设计文档就可以直接支撑论文撰写了。
