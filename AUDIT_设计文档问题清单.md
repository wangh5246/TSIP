# TSIP 完整设计方案 — 审计问题清单

> 审计日期：2026-04-12
> 审计范围：`TSIP_完整设计方案.md` 全文（第1-9章）对照实际代码
> 目标：确保文档可以直接支撑 NDSS 论文撰写，无版本差异、过时定理、遗漏机制

---

## 🔴 严重问题（必须修复，影响论文核心可信度）

### S1. §5.5.1 电路展示仍为旧版 v1，缺少 P4/P5

**位置**：设计文档 ~行 1885-2010（§5.5.1 TSIP主电路）

**文档写的**：
```circom
// circuits/tsip_main.circom
// canonical v1: public = [hash_prev, hash_curr, max_dist_sq]
// v2(P0待落地): public = [hash_prev, hash_curr, max_dist_sq, payload_commitment]
template TSIPCircuit() { ... }
component main {public [hash_prev, hash_curr, max_dist_sq]} = TSIPCircuit();
```

**实际代码**（`circuits/tsip_main_v2.circom`，已完成 trusted setup）：
- 5 个 public inputs: `[hash_prev, hash_curr, max_dist_sq, payload_commitment, secret_commitment]`
- 8 个 witness: `x1, y1, x2, y2, payload_lo, payload_hi, secret, user_id_field`
- 1154 constraints（v1 是 674）
- P4 约束: `Poseidon(payload_lo, payload_hi) === payload_commitment`
- P5 约束: `Poseidon(secret, user_id_field) === secret_commitment`

**问题**：
1. 文档仍然展示 v1 的 `TSIPCircuit()` 模板（3 public inputs, 4 witness），论文读者会以为这是最终方案
2. 标注 "v2(P0待落地)" 与事实矛盾（v2 已完成 trusted setup，5/5 测试通过）
3. v2 的 `secret_commitment` 在注释中完全未出现（只提到 `payload_commitment`）
4. witness 列表缺少 `payload_lo, payload_hi, secret, user_id_field`

**修复**：将 §5.5.1 的电路代码替换为 `tsip_main_v2.circom` 的内容，作为唯一主电路。删除 "v1/v2" 区分和 "P0待落地" 标注。

---

### S2. Theorem 3 (ZK) 的 public inputs 和 witness 未更新

**位置**：设计文档 ~行 2740-2820（§6.4 定理3: 零知识性）

**文档写的**：
```
x: public inputs (hash_prev, hash_curr, max_dist_sq)    ← 只有 3 个
w: witness (x1, y1, x2, y2)                              ← 只有 4 个
```

**实际**：
- public inputs 是 5 个: `(hash_prev, hash_curr, max_dist_sq, payload_commitment, secret_commitment)`
- witness 是 8 个: `(x1, y1, x2, y2, payload_lo, payload_hi, secret, user_id_field)`

**问题**：
- 模拟器构造（§6.4.3 ~行 2780-2815）只生成 4 维 fake_witness，不包含 payload 和 secret 维度
- ZK 性质的 scope 不对：文档只证明了"坐标不泄露"，但 v2 还需要证明 "payload_lo/payload_hi 不泄露" 和 "secret 不泄露"
- 这不影响结论（Groth16 ZK 性质覆盖所有 witness），但审稿人会指出定理陈述与实际不一致

**修复**：
1. 将 public inputs 更新为 5 个
2. 将 witness 更新为 8 个
3. 模拟器构造增加 `fake_payload_lo, fake_payload_hi, fake_secret, fake_uid`
4. 或者简化为直接引用 Groth16 原文定理（如 `paper_security_analysis.tex` 中的写法）

---

### S3. Theorem 1 将 P4/P5 标记为"可选增强"，但 v2 电路中是强制约束

**位置**：设计文档 ~行 2299-2320（§6.2.1 定理陈述）

**文档写的**：
```
(v)   [P4, when enabled] HMAC / SHA-256 second-preimage resistance,
(vi)  [P5, when enabled] HMAC-SHA-256 unforgeability,
...
条件 (v)(vi) 为可选增强：启用 P4/P5 后...
```

**实际代码**（`tsip_main_v2.circom`）：
- P4: `payloadHash.out === payload_commitment`（第 133 行，`===` 是硬约束）
- P5: `secretHash.out === secret_commitment`（第 142 行，`===` 是硬约束）
- v2 电路内无条件执行这两个约束，不存在"可选"概念

**问题**：
1. 既然论文要使用 v2 电路，P4/P5 不是"可选增强"而是电路级强制约束
2. 条件 (v) 写 "HMAC / SHA-256 second-preimage resistance" 是 v1 chain-level 绑定的假设；v2 的电路级绑定依赖的是 **Poseidon collision resistance**（电路内用 Poseidon 哈希），不是 HMAC/SHA-256
3. 条件 (vi) 同理：v2 P5 电路约束是 `Poseidon(secret, uid) === secret_commitment`，依赖 Poseidon，不是 HMAC-SHA256

**修复**：
1. 删除 "[when enabled]" 标注
2. 将 (v) 改为 "Poseidon collision resistance for payload commitment binding"
3. 将 (vi) 改为 "Poseidon collision resistance for secret commitment binding"
4. 在证明中增加 Path P4 和 Path P5 的分析（当前证明只有 Case 1-3，缺少 payload/secret 的 case）

---

### S4. §5.5.1 电路代码中 Poseidon 写法与实际不匹配

**位置**：设计文档 ~行 1893（§5.5.1 导入语句）

**文档写的**：
```circom
include "node_modules/circomlib/circuits/poseidon.circom";
```

**实际代码**（`tsip_main_v2.circom` 行 45）：
```circom
include "circomlib/circuits/poseidon.circom";
```

**问题**：导入路径不同（`node_modules/circomlib/` vs `circomlib/`），且 pragma 版本不同（文档 2.1.0 vs 实际 2.1.9）。虽然功能相同，但论文若引用文档中的代码会产生编译路径问题。

**修复**：统一为实际代码的写法。

---

## 🟡 中等问题（应修复，影响论文完整性/清晰度）

### M1. §5 协议规范中完全缺失 P4/P5 的协议描述

**位置**：§5.3（客户端协议）和 §5.4（服务器端协议）

**问题**：
- §5.3 客户端代码中没有 `compute_payload_digest()` 的调用
- §5.3 客户端代码中没有 `compute_secret_commitment()` 的调用
- §5.4 Shuffler 验证流程中没有 `payload_commitment` 和 `secret_commitment` 的检查步骤
- §5.2 TSIPProof 数据结构定义中没有 `payload_commitment` 和 `secret_commitment` 字段

但实际代码全部有实现：
- `common/tsip.py`: `compute_payload_digest()`, `compute_secret_commitment()`
- `services/shuffler/app.py`: `public_signals[3]`/`[4]` 检查逻辑（行 642-673）

**修复**：在 §5 协议规范中补充 P4/P5 完整流程。

---

### M2. §5.1 哈希函数参数仍标注为 "poseidon"（应为 "poseidon2"）

**位置**：设计文档 ~行 1048

**文档写的**：
```
HASH_FUNCTION = "poseidon"
```

**实际代码**（`common/tsip.py` 行 14）：
```python
TSIP_LOC_HASH_MODE = os.getenv("TSIP_LOC_HASH_MODE", "poseidon2")
```

**问题**：Poseidon ≠ Poseidon2，它们是不同的哈希函数（不同轮数和结构）。审稿人可能会追问具体用的是哪个。

**注意**：位置承诺用 Poseidon2，链承诺用 MiMC7。但电路内（`tsip_main_v2.circom`）用的是 circomlib 的 `Poseidon(2)`，这是 Poseidon（不是 Poseidon2）。所以实际上存在一个更深层的问题：

- **链下计算（Python）**：`_poseidon2_hash()` → 调用的是 poseidon2_bench WASM
- **链上电路（Circom）**：`Poseidon(2)` → 这是 circomlib 的原始 Poseidon

如果这两个哈希函数不一致，proof 生成时计算出的 hash 和电路里期望的 hash 就不会匹配。需要验证 poseidon2_bench 的 WASM 和 circomlib 的 Poseidon(2) 是否产生相同输出。

**修复**：
1. 确认 poseidon2_bench 和 circomlib Poseidon(2) 是否输出一致（如果一致，则只是命名混淆）
2. 在文档中统一术语：明确说明系统使用 circomlib 的 Poseidon 哈希，Python 端通过 snarkjs WASM 保持一致

---

### M3. §6.2 证明只分析 3 条攻击路径（Case 1-3），缺少 P4/P5 路径

**位置**：设计文档 ~行 2325-2480（§6.2.2-6.2.3 证明详细）

**文档的证明思路**：
```
Case 1: 伪造证明 → Groth16 soundness阻断
Case 2: 哈希碰撞 → Poseidon安全性阻断
Case 3: 复用证明 → 承诺链机制阻断
```

**缺失**：
- Case 4（Path P4）：payload 替换攻击 → payload_commitment 约束阻断
- Case 5（Path P5）：身份冒用攻击 → secret_commitment 约束阻断

**修复**：增加 Case 4 和 Case 5，与 `paper_security_analysis.tex` 中 Theorem 1 的 5 路径证明保持一致。

---

### M4. §6.5 通信效率分析中的公式可能过时

**位置**：设计文档 ~行 2898-2975（§6.5）

**问题**：v2 电路的 proof 大小（因为多了 2 个 public inputs）可能与 v1 不同。但 Groth16 proof 大小是固定的（3 群元素 ≈ 128-192 bytes），不随 public input 数量变化。公开输入本身会增加通信：从 3 个 field elements 增至 5 个（多 64 bytes）。应在通信分析中反映。

**修复**：更新通信公式，加入 payload_commitment 和 secret_commitment 的传输开销。

---

### M5. §7.6/§7.7 (P4/P5) 仍含工程代码路径

**位置**：设计文档 §7.6 和 §7.7

**问题**：这两节混合了协议安全分析和代码实现细节（如 `services/shuffler/app.py` 行号、环境变量名）。论文叙事应聚焦于安全机制本身，不应出现代码文件路径。

**修复**：将工程细节移至附录或删除，保留安全机制描述。

---

### M6. §8 实验评估方案中 Baseline 描述不完整

**位置**：设计文档 §8.3（~行 3734）

**问题**：
- EIFFeL-style baseline 的实现细节不足
- 缺少 "Commitment-Only" 和 "No-Integrity" baseline 的正式定义
- 实验参数（ε=1.0, malicious_rate=10%, A1=7200m）在 §8 中未统一声明

**修复**：在 §8.3 开头添加统一的实验参数表和所有 6 个 baseline 的形式化定义。

---

## 🟢 轻微问题（建议修复）

### L1. §9 论文撰写指南中的时间线过时
部分内容假设电路实现尚未开始，与当前状态不符。建议删除或更新。

### L2. §2.4 教学章节的电路示例过于简化
仍是 v1 的 3-public-input 版本。如果保留作为教学引入，应在末尾注明"完整电路见 §5.5.1"。

### L3. 参考文献缺少 Poseidon2 和 MiMC7 的引用
§6 用到了 Poseidon、Poseidon2、MiMC7 三种哈希，但参考文献只有一处 Poseidon 引用。

---

## 优先级总结

| 优先级 | 编号 | 章节 | 问题 | 预估修复时间 |
|--------|------|------|------|-------------|
| 🔴 | S1 | §5.5.1 | 电路仍为 v1，缺 P4/P5 | 1.5h |
| 🔴 | S2 | §6.4 | Theorem 3 public inputs/witness 未更新 | 0.5h |
| 🔴 | S3 | §6.2 | Theorem 1 将 P4/P5 标为可选+密码学假设错误 | 1h |
| 🔴 | S4 | §5.5.1 | 导入路径和 pragma 不匹配 | 0.2h |
| 🟡 | M1 | §5.2-5.4 | 协议规范缺 P4/P5 流程 | 2h |
| 🟡 | M2 | §5.1 | poseidon vs poseidon2 术语混淆 | 0.5h |
| 🟡 | M3 | §6.2 | Theorem 1 证明缺 Case 4/5 | 1h |
| 🟡 | M4 | §6.5 | 通信分析未含 v2 公开输入开销 | 0.5h |
| 🟡 | M5 | §7.6-7.7 | P4/P5 节混有工程代码路径 | 0.5h |
| 🟡 | M6 | §8.3 | Baseline 描述不完整 | 1h |
| 🟢 | L1 | §9 | 论文指南时间线过时 | 0.3h |
| 🟢 | L2 | §2.4 | 教学电路示例是 v1 | 0.2h |
| 🟢 | L3 | 参考文献 | 缺 Poseidon2/MiMC7 引用 | 0.2h |

**总计约 9 小时**的修复工作量。建议优先处理 S1-S3（核心定理和电路），这三项是 NDSS 审稿人最可能质疑的点。
