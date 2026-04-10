# TSIP Baseline 实验详细方案

**6 个 Baseline × 4 类实验 = 完整对比矩阵**

---

## 总览：Baseline 与实验矩阵

```
             ┌──────────┬──────────┬──────────┬──────────┬──────────┐
             │ Exp-1    │ Exp-2    │ Exp-3    │ Exp-4    │ Exp-5    │
             │ 攻击检测  │ Utility  │ 隐私效用  │ 开销     │ 规模     │
             │ (TPR/FPR)│ (Jaccard)│ (ε曲线)  │ (时延)   │ (扩展)   │
┌────────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ TSIP(Full) │ ✅ 必做   │ ✅ 必做  │ ✅ 必做   │ ✅ 必做  │ ✅ 已完成│
│ No-Integ   │ ✅ 已完成 │ ✅ 必做  │ ✅ 必做   │ ✅ 必做  │ ✅ 已完成│
│ Commit-Only│ ✅ 必做   │ ✅ 必做  │ ○ 可选   │ ✅ 必做  │ ○ 可选  │
│ RiseFL     │ ✅ 必做   │ ✅ 必做  │ ○ 可选   │ ✅ 必做  │ ○ 可选  │
│ Nebula     │ ✅ 必做   │ ✅ 必做  │ ✅ 必做   │ ✅ 必做  │ ○ 可选  │
│ Pure LDP   │ ✅ 必做   │ ✅ 必做  │ ✅ 必做   │ ✅ 必做  │ ○ 可选  │
│ EIFFeL     │ ✅ 必做   │ ✅ 必做  │ ○ 可选   │ ✅ 必做  │ ○ 可选  │
└────────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

## Baseline 1: No-Integrity（已完成，仅需补 Utility）

### 本质
关闭所有完整性验证（TSIP + 承诺链 + proof），仅保留 DP 层。

### 已有结果
- `malicious_reject_rate = 0.0`（恶意数据全部通过）
- 服务器 10 轮已完成

### 需要补的实验

**Exp-2: Utility 对比**

你需要从 No-Integrity 的聚合输出中提取热力图，与 ground truth 比较。

```bash
# 跑一组 No-Integrity 实验，同时记录聚合输出
ROUNDS=10 CLIENT_TOTAL=50 \
SHUFFLER_TSIP_ENABLE=0 CLIENT_TSIP_ENABLE=0 \
SHUFFLER_ZK_STEP_ENABLE=0 CLIENT_ZK_STEP_ENABLE=0 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=boundary_teleport TELEPORT_JUMP_M=7200 \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
```

每轮结束后调用 `dump_latest_dp` 保存聚合结果：
```bash
curl -s "http://localhost:8002/dump_latest_dp?epsilon=1.0&tau=3&tau2=3" > no_integrity_dp_round_${r}.json
```

**Utility 计算脚本（需新建）**：
```python
# experiments/compute_utility.py
import json, numpy as np

def load_heatmap(dp_json_path):
    """从 dump_latest_dp 输出加载热力图"""
    with open(dp_json_path) as f:
        data = json.load(f)
    heatmap = {}
    for cell_id, count in data["top_cells"]:
        heatmap[cell_id] = count
    return heatmap

def compute_ground_truth(trajectories, domain_size=10000):
    """从轨迹计算 ground truth 直方图"""
    gt = np.zeros(domain_size)
    for traj in trajectories:
        for x, y, t in traj:
            cell = int(x * 100 + y) % domain_size  # 你的网格映射
            gt[cell] += 1
    return gt

def jaccard(heatmap_pred, heatmap_gt, threshold=0):
    """Jaccard 相似度：两个热力图的 top-cell 集合重叠度"""
    set_pred = set(k for k, v in heatmap_pred.items() if v > threshold)
    set_gt = set(k for k, v in heatmap_gt.items() if v > threshold)
    if len(set_pred | set_gt) == 0:
        return 1.0
    return len(set_pred & set_gt) / len(set_pred | set_gt)

def rmse(heatmap_pred, heatmap_gt, domain_size=10000):
    """RMSE：每个网格的估计值 vs 真实值"""
    pred_vec = np.zeros(domain_size)
    gt_vec = np.array(heatmap_gt) if isinstance(heatmap_gt, np.ndarray) else np.zeros(domain_size)
    for cell_id, count in heatmap_pred.items():
        pred_vec[cell_id] = count
    return np.sqrt(np.mean((pred_vec - gt_vec) ** 2))
```

---

## Baseline 2: Commitment-Only

### 本质
保留 Poseidon2 承诺链（提交 prev/curr commitment），但关闭 ZK 距离约束验证。
这回答了：**"承诺链本身就够了吗？ZK 证明的边际价值是什么？"**

### 实现方式

在 Shuffler 中，修改验证逻辑：只检查承诺链连续性（prev_chain → curr_chain 是否匹配），不调用 snarkjs verify 验证距离约束。

**方案 A（推荐，最简单）**：新增环境变量 `SHUFFLER_TSIP_VERIFY_PROOF=0`

```python
# services/shuffler/app.py 中的验证路径修改
if TSIP_ENABLE:
    # 1. 始终检查承诺链连续性
    chain_ok = verify_chain_continuity(payload)
    
    # 2. 仅当 VERIFY_PROOF=1 时才验证 ZK 距离证明
    if TSIP_VERIFY_PROOF:
        proof_ok = verify_tsip_proof(payload)
    else:
        proof_ok = True  # 跳过距离验证
    
    accepted = chain_ok and proof_ok
```

**方案 B（不改代码）**：客户端正常生成证明，但 Shuffler 侧强制 `proof_ok=True`。

### 需要跑的实验

**Exp-1: 攻击检测**

```bash
# A1 瞬移攻击 —— Commitment-Only 应该无法检测
ROUNDS=10 CLIENT_TOTAL=50 \
SHUFFLER_TSIP_ENABLE=1 CLIENT_TSIP_ENABLE=1 \
SHUFFLER_TSIP_VERIFY_PROOF=0 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=boundary_teleport TELEPORT_JUMP_M=7200 \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
# 预期：malicious_reject_rate ≈ 0（承诺链不验距离，瞬移通过）

# A2 身份交换 —— Commitment-Only 应该能检测
ROUNDS=10 CLIENT_TOTAL=50 \
SHUFFLER_TSIP_ENABLE=1 CLIENT_TSIP_ENABLE=1 \
SHUFFLER_TSIP_VERIFY_PROOF=0 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=identity_swap \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
# 预期：malicious_reject_rate = 1.0（承诺链断裂检测生效）

# A5 重放攻击 —— Commitment-Only 应该能检测
ROUNDS=10 CLIENT_TOTAL=50 \
SHUFFLER_TSIP_ENABLE=1 CLIENT_TSIP_ENABLE=1 \
SHUFFLER_TSIP_VERIFY_PROOF=0 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=replay \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
# 预期：malicious_reject_rate = 1.0（链状态过时）
```

**Exp-4: 开销**
```bash
# 测客户端时间（承诺链计算但无 prove）
# 记录 per-client latency
```

### 预期结果汇总

| 攻击 | Full TSIP | Commit-Only | 说明 |
|------|-----------|-------------|------|
| A1 瞬移 | 100% 拦截 | 0% 拦截 | **ZK 的边际价值** |
| A2 身份交换 | 100% 拦截 | 100% 拦截 | 承诺链足够 |
| A5 重放 | 100% 拦截 | 100% 拦截 | 承诺链足够 |
| A3 渐进偏移 | 0% 拦截 | 0% 拦截 | 两者都无法检测 |

---

## Baseline 3: RiseFL-style（L2 范数约束）

### 本质
用 L2 范数检查替代 TSIP 的距离约束。验证的是"单个位置向量的范数是否在阈值内"，不验证跨窗口连续性。

### 实现方式

你的系统中已有 `proof_statistic_S()` 函数实现了 RiseFL 的核心逻辑——内积检验。
关键是：**只做单步范数检查，不做跨步距离约束。**

```python
# experiments/baselines/risefl_baseline.py
"""
RiseFL baseline: 只验证每个位置向量的 L2 范数 <= B
不验证 prev_loc 和 curr_loc 之间的距离
"""

def risefl_verify(location_vector, norm_bound, random_vectors, alpha=0.05):
    """RiseFL 的范数检查"""
    from scipy.stats import chi2
    m = len(random_vectors)
    s = sum(np.dot(location_vector, a)**2 for a in random_vectors)
    threshold = norm_bound**2 * chi2.ppf(1 - alpha, df=m)
    return s <= threshold

# 关键：RiseFL 不检查 dist(loc_prev, loc_curr)
# 所以瞬移攻击（prev 在北京, curr 在上海）只要每个点的范数合法就通过
```

**在你现有框架中的实现**：

利用已有的 `PROOF_ENABLE=1` + `PROOF_S_THRESHOLD` 机制，关闭 TSIP：
```bash
# RiseFL baseline: 有 proof S 检查，无 TSIP 距离约束
ROUNDS=10 CLIENT_TOTAL=50 \
PROOF_ENABLE=1 PROOF_S_THRESHOLD=100 \
SHUFFLER_TSIP_ENABLE=0 CLIENT_TSIP_ENABLE=0 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=boundary_teleport TELEPORT_JUMP_M=7200 \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
```

### 需要跑的实验

**Exp-1: 攻击检测（核心对比）**

| 攻击 | 配置 | 预期 |
|------|------|------|
| A1 瞬移 7200m | `PROOF_ENABLE=1, TSIP=0, TELEPORT=7200` | malicious_reject_rate ≈ 0（范数合法，距离不查） |
| A1 瞬移 + 范数超标 | 位置向量范数故意超大 | malicious_reject_rate > 0（范数检查生效） |
| A2 身份交换 | `ATTACK_TYPE=identity_swap` | malicious_reject_rate ≈ 0（RiseFL 无承诺链） |

**Exp-2: Utility**
```bash
# 同 No-Integrity 流程：保存 dump_latest_dp，计算 Jaccard
# RiseFL 在无攻击时 utility 应该和 TSIP 接近
# RiseFL 在有攻击时 utility 应该严重退化（恶意数据混入聚合）
```

**Exp-4: 开销**
```bash
# 记录 RiseFL 的 proof 生成时间（内积计算 vs TSIP 的 snarkjs prove）
# RiseFL 应该快很多（毫秒级 vs 秒级）
# 但安全性差异是你的核心卖点
```

---

## Baseline 4: Nebula

### 本质
Nebula 的 ESA 架构（Encode-Shuffle-Analyze）和你很像，但完全没有完整性验证。
差异：Nebula 用采样 + 阈值聚合实现 DP，你用 SVT + Laplace。

### 实现方式

Nebula 的核心是**客户端以概率 p_s 采样自己的值，加上 dummy 扰动，发送给 shuffle 服务器，服务器做阈值截断**。

```python
# experiments/baselines/nebula_baseline.py

import numpy as np

class NebulaClient:
    def __init__(self, epsilon=1.0, domain_size=10000):
        self.epsilon = epsilon
        self.p_s = 1 - np.exp(-epsilon)  # 采样概率
        self.domain_size = domain_size
    
    def encode(self, true_cell):
        """Nebula 客户端编码"""
        if np.random.random() < self.p_s:
            # 真实值
            return true_cell
        else:
            # dummy: 均匀随机
            return np.random.randint(0, self.domain_size)

class NebulaServer:
    def __init__(self, n_clients, domain_size=10000, threshold=3):
        self.n_clients = n_clients
        self.domain_size = domain_size
        self.threshold = threshold
    
    def aggregate(self, encoded_values):
        """Nebula 服务端聚合 + 阈值截断"""
        histogram = np.zeros(self.domain_size)
        for val in encoded_values:
            histogram[val] += 1
        
        # 阈值截断
        histogram[histogram < self.threshold] = 0
        
        # 去偏估计
        debiased = histogram  # 简化版；完整版需要根据 p_s 去偏
        return debiased
```

**在你的框架中模拟 Nebula**：

由于 Nebula 没有完整性验证，最简单的方法是：
1. 关闭 TSIP 和 proof
2. 客户端编码模拟 Nebula 的采样机制
3. 服务端聚合用 Nebula 的阈值截断

```bash
# Nebula 模拟：无完整性验证 + Nebula 式 DP
ROUNDS=10 CLIENT_TOTAL=50 \
SHUFFLER_TSIP_ENABLE=0 CLIENT_TSIP_ENABLE=0 \
PROOF_ENABLE=0 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=boundary_teleport TELEPORT_JUMP_M=7200 \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
```

但为了精确模拟 Nebula 的隐私机制（采样率 p_s + 阈值 τ），你需要写一个独立脚本：

```python
# experiments/run_nebula_baseline.py
"""
独立模拟 Nebula 的编码-洗牌-分析流程
输入：轨迹数据（合成 / GeoLife / T-Drive）
输出：聚合热力图 + Utility 指标
"""

def run_nebula_experiment(trajectories, epsilon, malicious_rate, 
                          attack_jump_m, domain_size=10000, rounds=10):
    results = []
    for r in range(rounds):
        encoded = []
        malicious_count = 0
        for i, traj in enumerate(trajectories):
            is_malicious = (i / len(trajectories)) < malicious_rate
            
            # 计算真实网格
            true_cell = trajectory_to_cell(traj, domain_size)
            
            if is_malicious:
                # 恶意客户端注入虚假位置
                fake_cell = random_cell(domain_size)
                true_cell = fake_cell
                malicious_count += 1
            
            # Nebula 编码
            client = NebulaClient(epsilon=epsilon, domain_size=domain_size)
            encoded.append(client.encode(true_cell))
        
        # Nebula 聚合
        server = NebulaServer(len(trajectories), domain_size)
        heatmap = server.aggregate(encoded)
        
        # 计算 Utility
        gt = compute_ground_truth(trajectories, domain_size)
        j = jaccard_from_arrays(heatmap, gt)
        r_val = rmse_from_arrays(heatmap, gt)
        
        results.append({
            "round": r,
            "jaccard": j,
            "rmse": r_val,
            "malicious_total": malicious_count,
            "malicious_reject_rate": 0.0,  # Nebula 不拦截任何人
        })
    
    return results
```

### 需要跑的实验

**Exp-1: 攻击检测**
- 所有攻击类型：malicious_reject_rate = 0（Nebula 无检测能力）
- 这和 No-Integrity 结果一致，但 Nebula 的 DP 机制不同

**Exp-2: Utility（核心对比）**
- 无攻击时：Nebula vs TSIP 的 Jaccard（同 ε=1.0）
- 有攻击时（10%/30%/50% 恶意）：Nebula 的 utility 退化 vs TSIP 的 utility 保持
- **这是 Money Figure 的核心**

**Exp-3: ε 曲线**
- ε = {0.1, 0.5, 1.0, 2.0, 5.0}
- 画 Nebula vs TSIP 的 ε-Jaccard 曲线

---

## Baseline 5: Pure LDP

### 本质
每个客户端本地用 Randomized Response 或 Laplace 加噪后直接发给服务端，无 shuffle，无验证。

### 实现方式

```python
# experiments/baselines/pure_ldp_baseline.py

import numpy as np

class PureLDPClient:
    def __init__(self, epsilon=1.0, domain_size=10000):
        self.epsilon = epsilon
        self.domain_size = domain_size
        # Generalized Randomized Response
        self.p = np.exp(epsilon) / (np.exp(epsilon) + domain_size - 1)
        self.q = 1.0 / (np.exp(epsilon) + domain_size - 1)
    
    def randomize(self, true_cell):
        """GRR 随机化"""
        if np.random.random() < self.p:
            return true_cell  # 真实值
        else:
            # 随机选一个其他值
            candidates = list(range(self.domain_size))
            candidates.remove(true_cell)
            return np.random.choice(candidates)

class PureLDPServer:
    def __init__(self, n_clients, epsilon, domain_size=10000):
        self.n = n_clients
        self.epsilon = epsilon
        self.d = domain_size
        self.p = np.exp(epsilon) / (np.exp(epsilon) + domain_size - 1)
        self.q = 1.0 / (np.exp(epsilon) + domain_size - 1)
    
    def aggregate(self, responses):
        """频率估计 + 去偏"""
        counts = np.zeros(self.d)
        for r in responses:
            counts[r] += 1
        # 去偏
        estimated = (counts - self.n * self.q) / (self.p - self.q)
        return np.maximum(estimated, 0)
```

```python
# experiments/run_ldp_baseline.py
def run_ldp_experiment(trajectories, epsilon, malicious_rate, 
                       attack_jump_m, domain_size=10000, rounds=10):
    results = []
    for r in range(rounds):
        responses = []
        for i, traj in enumerate(trajectories):
            is_malicious = (i / len(trajectories)) < malicious_rate
            true_cell = trajectory_to_cell(traj, domain_size)
            
            if is_malicious:
                true_cell = random_cell(domain_size)  # 注入虚假
            
            client = PureLDPClient(epsilon=epsilon, domain_size=domain_size)
            responses.append(client.randomize(true_cell))
        
        server = PureLDPServer(len(trajectories), epsilon, domain_size)
        heatmap = server.aggregate(responses)
        
        gt = compute_ground_truth(trajectories, domain_size)
        results.append({
            "round": r,
            "jaccard": jaccard_from_arrays(heatmap, gt),
            "rmse": rmse_from_arrays(heatmap, gt),
            "malicious_reject_rate": 0.0,
        })
    return results
```

### 需要跑的实验

**全部和 Nebula 一样的实验矩阵**，但 Pure LDP 的 utility 应该是所有方案中最差的（因为每个客户端独立加噪，noise 方差为 O(1/ε²)，而 shuffle 方案的 noise 是 O(1/(n·ε²))）。

---

## Baseline 6: EIFFeL-style

### 本质
EIFFeL（CCS 2022）是通用的"安全聚合 + 完整性检查"框架。它允许在安全聚合过程中嵌入任意完整性约束，并移除不合规的更新。

### 与 TSIP 的关键区别
- EIFFeL 的完整性检查是**单轮的**（检查"这个更新是否满足约束"），不做跨轮一致性
- EIFFeL 需要**多服务器协作**验证（MPC-based），通信开销比 TSIP 大 3 个数量级
- EIFFeL 不用 ZK 证明，而是用秘密分享 + 验证电路

### 实现方式

完整实现 EIFFeL 非常复杂（论文代码有数千行 C++）。
**推荐做法：实现一个 EIFFeL 的简化版，聚焦于对比维度。**

```python
# experiments/baselines/eiffel_baseline.py
"""
EIFFeL 简化版：
- 安全聚合（和 TSIP 一样用 secret sharing）
- 单轮范围检查（位置是否在合法网格范围内）
- 不做跨轮距离约束
"""

class EIFFeL:
    def __init__(self, domain_size=10000, norm_bound=100):
        self.domain_size = domain_size
        self.norm_bound = norm_bound
    
    def verify_single_update(self, cell_id, value):
        """EIFFeL 的单轮完整性检查"""
        # 检查 1：cell_id 在合法范围内
        if cell_id < 0 or cell_id >= self.domain_size:
            return False
        # 检查 2：value 范数在阈值内
        if abs(value) > self.norm_bound:
            return False
        # ❌ 不检查：这个 cell_id 和上一轮的 cell_id 的距离是否合理
        return True
    
    def aggregate_with_verification(self, submissions, malicious_flags):
        """EIFFeL 聚合：先验证再聚合"""
        accepted = []
        rejected_malicious = 0
        rejected_honest = 0
        total_malicious = sum(malicious_flags)
        
        for i, (sub, is_mal) in enumerate(zip(submissions, malicious_flags)):
            ok = self.verify_single_update(sub["cell_id"], sub["value"])
            if ok:
                accepted.append(sub)
            else:
                if is_mal:
                    rejected_malicious += 1
                else:
                    rejected_honest += 1
        
        mal_reject_rate = rejected_malicious / max(total_malicious, 1)
        false_reject_rate = rejected_honest / max(len(submissions) - total_malicious, 1)
        
        return accepted, mal_reject_rate, false_reject_rate
```

**在你的框架中的模拟**：

EIFFeL 在你的框架中等价于：
- 开启安全聚合（secret sharing）
- 开启范围检查（cell_id 合法性）
- 关闭 TSIP 距离约束和承诺链

```bash
# EIFFeL 模拟：有安全聚合 + 范围检查，无距离约束
ROUNDS=10 CLIENT_TOTAL=50 \
SHUFFLER_TSIP_ENABLE=0 CLIENT_TSIP_ENABLE=0 \
PROOF_ENABLE=1 PROOF_S_THRESHOLD=100 \
MALICIOUS_RATE=0.1 ATTACK_TYPE=boundary_teleport TELEPORT_JUMP_M=7200 \
TSIP_USER_SCOPE=stable WARMUP_ROUNDS=1 \
BUILD_SERVICES=0 \
bash script/run_experiment_rounds.sh
```

### 需要跑的实验

和 RiseFL 一样的实验矩阵，但需要额外记录**通信开销**。
EIFFeL 的通信开销是 O(n·d)（每个客户端发送每个维度的 share），而 TSIP 是 O(K + proof_size) ≈ 2KB。

---

## 汇总：完整实验执行计划

### 阶段 1（3 天）：Utility 框架 + Ground Truth

**Day 1：** 实现 `compute_utility.py`
- 从无攻击实验中提取 ground truth 热力图
- 实现 Jaccard / RMSE / Relative Error 计算
- 验证：Full TSIP 无攻击时 Jaccard 应接近 1.0

**Day 2：** 补跑 Utility 数据
- 对已有实验（Full TSIP / No-Integrity）补采 `dump_latest_dp` 输出
- 计算 Jaccard 和 RMSE

**Day 3：** DP ε 曲线
- ε = {0.1, 0.5, 1.0, 2.0, 5.0}，每档跑 5 轮
- 固定攻击率 10%，记录 Jaccard

### 阶段 2（4 天）：Baseline 实现与运行

**Day 4：** Commitment-Only
- 在 Shuffler 中加一个开关跳过 proof verify
- 跑 A1/A2/A5 三组攻击实验

**Day 5：** RiseFL-style
- 用已有的 `PROOF_ENABLE=1, TSIP=0` 配置
- 跑 A1 攻击实验 + Utility 实验

**Day 6：** Nebula + Pure LDP
- 写独立脚本模拟两个方案
- 跑 Utility 实验（核心是 ε-Jaccard 曲线）
- 跑攻击实验（确认 malicious_reject_rate = 0）

**Day 7：** EIFFeL
- 写简化版模拟
- 跑 A1 攻击 + Utility + 通信开销对比

### 阶段 3（2 天）：整合与画图

**Day 8：** 汇总所有数据
- 生成 6 baseline × 5 实验的完整 CSV
- 计算均值和标准差

**Day 9：** 画图
- **Figure 1 (Money Figure):** 攻击率 vs Utility（TSIP/No-Integrity/Nebula/LDP 四线）
- **Figure 2:** ε vs Jaccard（4 个方案的隐私效用曲线）
- **Figure 3:** 攻击检测率对比（bar chart，6 个方案 × 4 种攻击）
- **Table 1:** 综合对比表（所有方案 × 所有指标）

---

## 已同步实测数据（可直接写论文）

固定设置：
- ε = 1.0
- 恶意比例 = 10%
- 攻击 = A1 边界瞬移（7200m）
- 轮数 = 10
- 客户端 = 50

### 攻击防御能力总对比（T-Drive，TPR/FPR）

| Scheme | A1 TPR | A1 FPR | A2 TPR | A2 FPR | A5 TPR | A5 FPR |
|---|---:|---:|---:|---:|---:|---:|
| TSIP (Full) | 1.0000 | 0.0402 | 1.0000 | 0.0000 | 1.0000 | 0.0000 |
| Commitment-Only | 0.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 |
| RiseFL | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Nebula | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| EIFFeL-style | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Pure LDP | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| No-Integrity | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

> 注：这里 FPR 口径与文中 FRR 一致（均表示 honest 样本被误拒比例）。

### T-Drive 实测对比表

| Scheme | A1 TPR | A2 TPR | A5 TPR | Jaccard | FRR | Comm (KB) |
|---|---:|---:|---:|---:|---:|---:|
| TSIP (Full) | 1.00 | 1.00 | 1.00 | ~1.00 | 0.0402 | 2 |
| Commit-Only | 0.00 | 1.00 | 1.00 | ~1.00 | 0.0000 | 1 |
| No-Integrity | 0.00 | 0.00 | 0.00 | ~1.00* | 0.0000 | 1 |
| Nebula | 0.00 | 0.00 | 0.00 | 0.0000 | 0.0000 | 2.7 |
| Pure LDP | 0.00 | 0.00 | 0.00 | 0.0040 | 0.0000 | 0.01 |
| EIFFeL-style | 0.00 | 0.00 | 0.00 | 0.1699 | 0.0000 | 40.0 |

### GeoLife 实测对比表

| Scheme | A1 TPR | A2 TPR | A5 TPR | Jaccard | FRR | Comm (KB) |
|---|---:|---:|---:|---:|---:|---:|
| TSIP (Full) | 1.00 | 1.00 | 1.00 | ~1.00 | 0.0402 | 2 |
| Commit-Only | 0.00 | 1.00 | 1.00 | ~1.00 | 0.0000 | 1 |
| No-Integrity | 0.00 | 0.00 | 0.00 | ~1.00* | 0.0000 | 1 |
| Nebula | 0.00 | 0.00 | 0.00 | 0.8000 | 0.0000 | 2.7 |
| Pure LDP | 0.00 | 0.00 | 0.00 | 0.0019 | 0.0000 | 0.01 |
| EIFFeL-style | 0.00 | 0.00 | 0.00 | 0.7552 | 0.0000 | 40.0 |

### 直接可用结论

- TSIP (Full) 在 A1 上达到 `100%` 恶意拦截，Commit-Only 和 No-Integrity 在 A1 上均为 `0%`，说明检测能力来自 ZK 距离约束而非仅承诺链。
- 在这组设置下，Nebula、Pure LDP、EIFFeL-style 对 A1 的恶意拦截率均为 `0%`。
- Utility 方面，T-Drive 与 GeoLife 的 baseline 表现差异明显（例如 Nebula: `0.0000` vs `0.8000`），后续论文应分别报告两数据集结果，不做混合平均。
