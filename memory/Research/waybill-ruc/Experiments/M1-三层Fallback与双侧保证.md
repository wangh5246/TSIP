---
id: exp-002
type: experiment
project: waybill-ruc
status: verified
updated: 2026-07-14
priority: P0
tags: [waybill, v6, fallback, odometer, fairness]
---

# M1 — 三层 Fallback 与双侧保证

## 研究问题

能否用可信里程统一正常与 outage 的距离语义，在阻止 position withholding 少缴的同时，消除 `Δt × v_max` 对停车和长 dwell 的虚构里程？

方法决定：[[Knowledge/WayBill-v6方法优化决策]]  
V5 基线：[[Results/Reports/V5证据快照与审阅差距-2026-07]]  
V6 台账：[[Results/Reports/V6方法门禁与实验台账-2026-07]]

## 前置条件

- [[Experiments/M0-Canonical-Policy-Binding]] 已冻结 authority-controlled `r_max`、单位、rounding、overflow 和 reconciliation policy。
- threat model 明确 odometer 的 attestation、单调性、误差界、维修重置和 freshness 能力。
- 若实际来源不能提供这些能力，只能把结论写成 conditional model，不得宣称已真实部署。

## 假设

在 odometer 误差有界、`r(zone) ≤ r_max` 且 policy canonical 的条件下：

1. outage 计费 `Δodo × r_max` 使 withholding 不产生少缴收益；
2. 停车时 `Δodo=0`，outage 费用为 0；
3. 月度 reconciliation 覆盖未提交里程，不把长期不提交变成零账单；
4. 与时间型 fallback 相比，诚实用户 surcharge 的 median/P95 显著下降。

## SSOT 公式

对 period 内相邻 authenticated checkpoints：

- position-valid：`fee_i = Δo_i × r(z_i)`；
- position-unavailable：`fee_i = Δo_i × r_max`。

月末：

- `accounted = Σ submitted Δo_i`；
- `unaccounted = max(0, monthly_ΔO - accounted)`；
- `reconciliation_fee = unaccounted × r_max`。

总账单：

`B_accept = Σ fee_i + reconciliation_fee`。

若 `accounted > monthly_ΔO + tolerance`，进入异常/拒绝；若月度 attestation 缺失，进入行政流程而非产生 cryptographic zero bill。

## 形式化性质

### Revenue Soundness

在已声明假设下证明或机械检查：

`B_accept ≥ B_true - r_max ε_o - ε_arith`

其中 `ε_o` 必须由 calibration、resolution、量化和 reset policy 推导，不能作为任意 slack。

### Honest-user Fairness

证明：

`B_accept ≤ B_true + Σ_outage Δo_i (r_max - r_true,i) + r_max ε_o + ε_arith`

并用真实/现有数据测量 outage premium 分布。最坏界与经验体验分开报告。

### No-benefit withholding

对任一原本 position-valid 的里程，把它改标为 outage 后，账单变化应满足：

`ΔB = Δo (r_max - r(zone)) ≥ 0`。

## 实现范围

- circuit、charger、reference Python model 共用同一字段、单位和整数运算顺序；
- checkpoint 增加/明确 monotone sequence、odometer、position-valid bit、period binding；
- month-close 只对 unaccounted distance reconciliation；
- 保留 V5 时间型实现作为 baseline，不直接覆盖其 artifact。

## 正确性与攻击测试

| 类别 | 用例 | 不变量 |
|---|---|---|
| Parking | 长时间 outage，`Δo=0` | fee = 0 |
| Withholding | 隐藏低/中/高费率位置 | bill 不下降 |
| Omission | 删除部分或全部 period proof | month close 覆盖未记里程 |
| Replay | 重复 interval / period | 不重复入账 |
| Ordering | 乱序或重复 sequence | reject |
| Rollback | odometer 下降 | reject 或匹配已认证维修事件 |
| Wrap/reset | 位宽回绕、维修重置 | 按显式 policy 处理，不静默负距离 |
| Bounds | 超范围 `Δo`、时间、rate、amount | reject，无整数溢出 |
| Arithmetic | 不同 rounding/scale | circuit/charger/reference 完全一致 |
| Boundary | 月初/月末跨 period | 每段只结算一次 |

## 数据实验

### 数据集

沿用现有 E2 的全部数据集和相同 outage masks；另构造 parking-heavy、stop-and-go、highway 和整月缺失合成集。若引入真实 field data，单独标注，不与轨迹代理数据混写。

### Baselines

- V5：`Δt × v_max × r_max`；
- V6：`Δodo × r_max`；
- oracle：真实 position + `Δodo × r(zone)`；
- ablation：无 month-close reconciliation。

### 指标

- undercharge amount/rate 与最大 withholding advantage；
- honest surcharge 的 mean、median、P95、P99 和 absolute currency；
- parking false distance / false fee；
- month-close reconciliation amount；
- acceptance/rejection rate；
- proof constraints、prove/verify latency 变化；
- odometer error ±0.5%、±1%、±2% 的敏感性。

## 统计协议

- 对同一轨迹和 outage mask 做 paired comparison。
- 报告 bootstrap 95% CI，不只给均值。
- 分数据集和 pooled 两种视图；dwell-heavy Rome 单列。
- 预先固定 outage α、mask seeds、tariff version、货币 scale 和 rounding。
- 分开报告 route-rate premium 与 odometer/calibration error。

## 硬门槛

- 所有 constructed withholding attack 的少缴收益 ≤ 预注册算术/里程误差界。
- 所有 parking outage 在 `Δo=0` 时精确收费 0。
- circuit、charger、reference model 的 property/differential tests 全通过。
- month-close omission 测试中，未覆盖里程不产生隐形零账单，也不双计费。
- 每个真实数据集的 P95 surcharge 都低于 V5；dwell-heavy 数据的改善必须同时出现在绝对金额和相对比例。
- pooled paired median improvement 的 95% CI 不跨 0。
- Revenue Soundness 与 Honest-user Fairness 的假设、误差项和证明草案均可独立审阅。

任一停车、withholding、double-count 或 overflow 用例失败，M1 为 `failed`，不能用平均公平性改善掩盖。

## 执行结果（2026-07-14）

### 组合门禁

M1 在“认证、单调且经校准的 odometer”条件下为 **verified protocol/model
result**。组合判定 SSOT 是 `experiments/waybill_m1/v1/gate_summary.json`；其中
data/property、canonical-profile-bound circuit、真实 charger endpoint 与形式化说明
四项均为 `true`，`hard_gate_passed=true`。

### 数据与性质门禁

- 4 个数据集共接受 226 个 period、拒绝 0 个；预注册的
  `α={0.05,0.1,0.2}` 与 5 个 seeds 产生 3390 条 paired outage 记录。
- GeoLife、Porto、Rome、T-Drive 四个数据集的 V6 P95 surcharge 在绝对金额和
  相对比例上都低于 V5；每个数据集的最大 V6 undercharge 与最大 withholding
  advantage 均为 0 cents。
- pooled、按 226 个 period 聚类的 5000 次 bootstrap 得到 paired median
  improvement 70500 cents，95% CI 为 **[70068, 70680] cents**，不跨 0。
- parking 构造例在 600 s outage、`Δodo=0` 时 V6 费用精确为 0；数据集中所有
  parking outage 的 V6 fee 也为 0。month-close 构造例对 930 m 未覆盖里程收取
  4650 cents，月总额 4720 cents，没有隐形零账单。
- `experiments/waybill_m1/v1/odometer_sensitivity.csv` 保存 1582 条
  ±0.5%、±1%、±2% 敏感性记录；Revenue Soundness、Honest-user Fairness、
  no-benefit withholding 和 `epsilon_arith=0` 的条件与推导见
  `experiments/waybill_m1/v1/formal_properties.md`。

### Circuit 与 charger 门禁

- `SettlementPeriodV6(25,8,6)` 为 **240258 constraints**；真实
  witness/prove/verify receipt 位于
  `experiments/waybill_m1/v1/circuit_differential/receipt.json`，结果 `ok=true`，
  22/22 个 public signals 与 Python reference 完全一致，profile commitment 非零且
  被 circuit 约束。
- 该 proof 的 witness/prove/verify 分别为 471.56 / 12631.93 / 452.84 ms；
  verification-key SHA-256 为
  `f1e73b4e91fff595adff551b13466f15351b587231877f45e9d7b0d473b4569d`。
  此性能 receipt 使用仓库 `pot18` 的 test-only direct Groth16 setup，不能外推为
  production ceremony 证据。
- 非 mock 的 charger 服务端点门禁见
  `experiments/waybill_m1/v1/circuit_differential/charger_endpoint_receipt.json`：
  canonical proof 返回 200，replay 返回 409，篡改 public signal 返回 400；month
  attestation 与 close 均返回 200。accepted period 为 2400 m / 3600 cents，月末仅对
  600 m unaccounted distance reconciliation 3000 cents，月总额 6600 cents。

### 证据边界与主张降级

- 本结果依赖 authenticated、monotone、calibrated odometer 及其 reset/freshness
  保证；本实验**没有**完成 receiver 或 odometer 的现场认证。缺少该能力时，只能
  保留条件式协议结论，必须停止“已部署可行/真实车辆已认证”的主张。
- 数据金额是各数据集的 experimental cents，Rome 使用 `r_max=12`，其余数据集
  使用 `r_max=5`；它们不是统一现实税制的财政估计。
- endpoint receipt 证明当前服务代码的 acceptance/replay/month-close 行为，不代表
  外部 policy authority、HSM、数据库运维或 production trusted setup 已审计。
- 若停车、withholding、double-count、overflow、profile binding 或 endpoint
  任一硬门禁失败，本卡必须降级为 `failed`；不能用平均 P95 改善覆盖安全失败。

## Artifact 清单

- fallback/reconciliation specification 与 test vectors；
- formal-property note 或 mechanized checks；
- circuit/charger/reference differential receipts；
- per-trajectory paired CSV；
- dataset summary + bootstrap CI；
- V5/V6/oracle 图表和 manifest；
- 结果回填 [[Results/Reports/V6方法门禁与实验台账-2026-07]]。

## 停止与分支规则

- 若可信 odometer 假设无法由目标部署支撑，停止“部署可行”主张；可保留条件式协议结果。
- 若 V6 的 outage premium 仍不可接受，先评估 policy-side rate cap 或保险式 reconciliation；不要回退到时间型虚构距离。
- 只有安全、正确性、形式化和数据门槛全部通过后升级为 `verified`。
