# TSIP-RUC Evaluation 工作汇总
*供新对话继续使用*

## 项目背景

把一篇被 desk reject 的隐私保护道路计费（RUC）论文重做 evaluation。原版死因 B 是"密码学被实验证明不起作用"。新框架的核心洞察：**RUC 下没有聚合，每个 proof 直接决定一份账单，所以消融实验会显示每个密码学组件都在改变账单金额**——正是原版缺的证据。整篇论文 thesis = 那张设计空间表的最后一行：TSIP-RUC 是唯一同时做到"区域计费 ✓ + 隐私强 + 路侧基础设施零"的方案，代价是更强的设备信任假设。

技术栈：Circom/Groth16/Poseidon、rapidsnark。环境：MacBook 开发 + 80 核服务器。目标 NDSS，PoPETs 为 fallback。

---

## 六组实验

- **E1** 完整性消融（最高优先，修 desk reject 根因）：逐个关闭密码学组件，测对手能省多少钱。全开≈0，每松一条约束露出它独自挡的那块钱。
- **E2** 诚实用户 fallback penalty + 帕累托前沿（fallback rate ≥ max zone rate 时 withholding 收益归零）。
- **E3** 对抗经济残余：第一层 soundness 检出=1；第二层量化 proof-consistent relay 残余，扫 zone 粒度 × relay 能力。
- **E4** 基础设施成本 vs spot-check（VPriv/PrETP/Milo），反解所需摄像头数。
- **E5** 隐私泄漏 vs GPS-upload（再识别 vs 仅 2-bit profile）。
- **E6** 性能与规模（刻意去 hype）。
- **最小可发表 = E1+E2+E3。**

---

## 关键架构洞察：E1/E3 是同一个求解器

把对手建成**资源约束最短路（RCSPP）**：最小化账单 fee，四个约束对应优化问题的不同结构（OSNMA→候选集 S_i；continuity→边可行性；cadence→可删节点；odometer→全局距离等式）。**E1 的每行消融 = E3 的 RCSPP 松弛某条约束**。所以先搭 harness，E1/E2/E3 几乎免费。

---

## 四个数据集（已获取并预处理）

| 数据集 | 来源 | 格式要点 | 状态 |
|---|---|---|---|
| T-Drive（北京出租车） | MS 免费 | `taxi_id,time,lon,lat`，~177s 稀疏，需切 trip | ✓ |
| GeoLife（北京个人） | MS 免费 | PLT 跳 6 行，只留 car/taxi/driving 标签，秒级密集 | ✓ |
| Porto（出租车） | UCI id=339 / Kaggle | `json.loads(POLYLINE)`，15s，已按 trip 切好 | ✓ |
| Rome（出租车） | IEEE DataPort（需订阅） | `DRIVER_ID;TIMESTAMP;POINT(lat lon)`，注意 lat 在前 | ✓ |

---

## 文献校准结论

**E2 OSNMA fallback**（比原估 2-10% 严重得多）：
- 开阔/高速：>99% 可用，fallback ≈1%
- 密集城区：认证可用率 ~68%（≥4 星）低至 ~19%（Galileo-only strict），fallback 30%–80%
- 隧道/地下：全 outage（fallback=1.0）
- TTFAF 再获取惩罚：~60s
- **对 E2 有利**（penalty 更有分量，Pareto 前沿更关键）

**E4 spot-check 模型**（VPriv/PrETP/Milo 谱系）：
- P(caught) = 1-(1-c)^(fS)，检出靠摄像头密度 c 和漏报比例 f
- 抓小额作弊需要密集覆盖（城市路网通常数千摄像头）
- TSIP-RUC：需 0 个摄像头，违背证明检出=1（确定性）

---

## 已落地的工程实现

| 文件 | 内容 |
|---|---|
| `common/eval_harness.py` | 复用真实 `fee_for_period()`；keep/drop RCSPP；快路径；strict/relay/off 候选集；`cross_check_against_circuit()` 钩子；`e1_ablation_row()` |
| `common/eval_experiments.py` | E2 outage+TTFAF+Pareto；E3 sweep+soundness hook；E4 摄像头模型 |
| `common/trajectory_preprocess.py` | 四数据集统一预处理；IdentityMatcher 默认+ExternalMapMatcher adapter；按 cadence 重采样；逐点 haversine 合成 odometer；超 study-area 直接跳过 |
| `common/osm_vectors.py` | tunnel=yes 解析；env_labeler（30m buffer）；provisional tariff；`tariff_from_geojson()`；boundary_buffer |
| `script/prepare_eval_datasets.py` | 四数据集统一入口，smoke 各出 2 条规范化 trip |
| 诊断脚本 | audit_matching_need、audit_tariff_boundary_sensitivity、audit_geometric_binding 等 |

PBF 已就绪：`beijing.osm.pbf` 88MB / `portugal-latest.osm.pbf` 394MB / `centro-latest.osm.pbf` 361MB。osmium 替代 pyrosm（macOS+Python 3.12 构建失败）。tunnel ways：北京 6958 / Portugal 10418 / Italy 15199。

回归：29 passed（harness + experiments + settlement + charger）。

---

## 关键电路语义（已确认）

`settlement_period_v5_base.circom`，当前 224,234 约束：

```
计费：odo_delta[i] × zone_rate
fallback：dt[i] × tier_vmax_mps × max_rate（cadence 失效时）
约束：sum(odo_delta) === total_distance_m
路径一（已加）：odo_delta[i] <= dt[i] * tier_vmax_mps
```

**已确认：odo_delta 与几何距离无一致性约束（两条独立支路）、无单段上界（已由路径一补上）、continuity 约束的是 dist_sq 而计费用 odo_delta。**

后果：odo-on 对手最优 ≈ `total_distance × continuity 可达的最低 zone_rate`，**DP 不需要 distance bucket 维**；E3 残余由"continuity+relay 下真实轨迹够不够得到便宜 zone 边界"决定，zone 粒度成为残余主控变量。

---

## Odometer 解耦的处理方式

**结论：limitation 不是 vulnerability**（可改进 + 有事实依据）。

正确 framing：放进 threat model 的 in/out-of-scope，不放末尾 limitations。对比基线：硬件 odometer（单个组件、可审计）vs 城市级摄像头（城市级盲区、概率性检出）——攻击面更窄，检出=1。

三档加固路径：
- **L1** `odo_delta ≤ dt·tier_vmax`：已实现，零成本，消掉"原地声称大里程"。
- **L2** 几何绑定 `[dist, sinuosity×dist]`：需米级坐标 + 物理 odometer 实测校准阈值，cadence 60s 下临界可行。
- **L3** map-matched 里程 ZK 证明：future work，另一篇论文的工作量。

论文里做成"三档加固的 trade-off 表"，展示设计空间和选择依据。

---

## 几何绑定 audit 结果

扫 10,498 段（T-Drive/GeoLife/Porto），odo_delta 用 GPS 折线长度 proxy（proxy 因 GPS 抖动虚长，真实物理 odometer p95 大概率更低）。筛 dist≥50m：

| cadence | p95 odo/dist | >2.5 |
|---|---:|---:|
| 60s | 1.624 | 1.70% |
| 300s | 3.443 | 8.74% |

**决策：300s 下固定阈值 1.4/2.5 误杀不可接受，退回路径一。60s 下几何绑定临界可行，但阈值标定需物理 odometer 数据（四数据集均为 GPS，无 OBD，是方法学硬缺口）。**

---

## 当前卡点：cadence 决策

cadence 可调（`.env` 默认 300s，非电路硬约束，`cadence_sec` 是公开输入）。

| | 300s（现状） | 60s |
|---|---|---|
| proof 覆盖 | ~2h | ~24min |
| 月度 proof 数 | N | 5N |
| 几何绑定 | 不可行（p95=3.44） | 临界可行（p95=1.62） |
| E2 诚实 penalty | fallback 块大 | 5× 细粒度，penalty 下降 |
| E3 relay 残余 | 较大 | 更紧（continuity 更紧） |
| 月度聚合 | 未定 | 未定（同一个问题，5× 放大） |

**60s 的收益是三合一的（绑定可行性 + E2 penalty + E3 残余），成本耦合一个未定的月度聚合策略（per-trip 累加 vs 递归 SNARK）。**

---

## 下一步（新对话从这里开始）

**第一件事（阻塞其他所有成本估算）：定月度聚合策略。**
- per-trip proof 累加：N 个 proof 各自 verify，月度账单=累加。60s → 5× verify 吞吐 + 5× 存储。
- 递归 SNARK 聚合：叶子 5×，递归深度和聚合成本涨。

**第二件事（不依赖物理 odometer，现有 harness 就能出）：cadence 三档对比表。**
出"cadence ∈ {60,120,300}s × {proof成本, E2诚实penalty, E3残余}"纯计算表。这张表本身是论文强节，展示 cadence 是贯穿成本/隐私/安全的统一旋钮。

**第三件事（若 60s 值）：补物理 odometer 标定数据。**
选项：公开 naturalistic driving study（SHRP2 等含 CAN 数据）；或自采（OBD-II + GPS，几百公里足够标定分位数）。

**仍欠的工程项：**
- `cross_check_against_circuit()` 接真实 witness 生成器（E1 可信度根，优先级最高）
- 嵌套三粒度真实 tariff polygon（coarse 必须是 fine 的合并，不能独立画三遍）
- DP-vs-闭式正确性测试（强制 no-continuity 走通用 DP，断言 = total_odo × min_rate）
- 批量 E1–E4 正式 CSV、统计表、论文图
- Git commit（当前状态是干净里程碑，先打一个）
