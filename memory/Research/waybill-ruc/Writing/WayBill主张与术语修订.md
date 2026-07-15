---
id: writing-001
type: writing
project: waybill-ruc
status: active
updated: 2026-07-15
tags: [waybill, writing, claims, terminology]
---

# WayBill 主张与术语修订

## 写作状态

当前 `WayBill/main.tex` 仍是短骨架。M0–M3 方法门禁已经通过，因此 Method、Security、
assumptions 与 limitations 可以开始重写；Evaluation 的正式全量数值必须等待
[[Experiments/M4-服务器正式大规模实验]] S1–S4 strict aggregate。当前本机样本只能
作为方法门禁和回归证据，不能替代正式服务器主表。V5 事实边界见
[[Knowledge/WayBill-v5真实状态与证据边界]]。

依据来源：[[Sources/Docs/WayBill外部审阅报告-2026-07-13]]、[[Sources/Docs/WayBill当前仓库审计-2026-07-13]]。

## 核心叙事（门禁通过后的候选）

WayBill V6 研究的不是“零知识自动保证真实道路使用”，而是：在权威 policy profile 与明确测量假设下，如何私密证明道路收费计算、使定位缺失不带来少缴、避免用停车时间虚构行驶距离，并给出城市规模与攻击最坏区间的可审计证据。

## 术语替换

| 避免使用 | 改为 | 条件 |
|---|---|---|
| trusted GPS / authentic location | attested receiver output under stated assumptions | 必须列出接收机实际认证对象 |
| OSNMA proves location authenticity | OSNMA authenticates navigation-message origin/integrity | 不外推到物理位置 |
| tamper-proof odometer | attested monotone odometer with bounded calibration error | 需说明 reset/repair/rollback |
| secure policy | authority-pinned versioned PolicyProfile | M0 verified 后使用 |
| fair fallback | odometer-backed fallback with stated honest-user bound | M1 verified 后使用 |
| formal upper bound | relaxation-certified upper bound with reported gap | M3 verified 后使用 |
| city-scale deployable | city-domain capacity demonstrated on the measured server configuration | 仅在 M4 S2 全矩阵通过后使用；当前只能写 local normalized capacity benchmark |
| anonymity set / pool size proves privacy | equivalence-pool metric under a stated observation model | 需补 route/cross-period attack |
| TEE is slower/less secure | measured comparison under matched functionality and threat model | 无完整 baseline 时删除 |

## Claim → evidence 门禁

| 候选主张 | 必要假设 | 必要证据 | 来源状态 |
|---|---|---|---|
| proof 遵循权威收费政策 | authority registry 与 charger 未失陷 | M0 所有 profile mutation 负测拒绝 | verified local gate |
| withholding 无少缴收益 | canonical `r_max`、可信单调 odometer | M1 定理 + attack property tests | verified local gate；等待 M4 S1 全量 |
| 停车 outage 不被虚构收费 | `Δodo=0` 可被认证 | M1 parking tests | verified local gate；等待 M4 S1 全量 |
| 对诚实用户更公平 | 数据/费率/缺失模型代表目标场景 | full-corpus paired median/P95/P99 + user-cluster CI | M4 S1 planned |
| 支持城市 tariff domain | 10,000+ cell artifact 与 depth 14/16 | 16-config × 10 real prove/verify + concurrency | M4 S2 planned |
| E3 接近最坏攻击 | 模型覆盖论文 threat model | full canonical corpus LB/UB/gap/certificates | M4 S3 planned |
| 真实部署可行 | 具体 receiver/odometer 能力存在 | field trial + calibration/reliability | not scheduled as core gate |
| 隐私泄漏边界可量化 | observation schema 与 user-disjoint split 现实 | route inference + cross-period/opening tests | M4 S4 planned |

## 推荐论文结构

### 1. Introduction

- 问题：usage-based road charging 需要收费正确性，但完整轨迹不应集中暴露。
- 难点：证明不仅要绑定测量，还要绑定权威政策；定位缺失会造成收益与公平冲突。
- insight：用 authority profile commitment 固定结算语义，用单调 odometer 统一距离并只对未知 tariff 取 `r_max`，而不是对未知距离取 `v_max × Δt`。
- 贡献只列已通过门禁的项目。

### 2. System and Trust Model

- policy authority、measurement source、charger、vehicle/client 分开。
- 单列 trusted / untrusted / out-of-scope。
- 说明 OSNMA、receiver attestation、odometer attestation 分层能力。
- 说明 DoS、月度 attestation 缺失、行政异常和 policy key compromise。

### 3. Policy-bound Settlement

- `PolicyProfile` canonical serialization/commitment；
- proof relation 与 charger acceptance relation；
- replay、rollback、revocation、jurisdiction/version lifecycle；
- measurement root 与 pricing policy 分离。

### 4. Odometer-backed Fallback

- normal/outage/month-close 三层公式；
- Revenue Soundness、Honest-user Fairness、No-benefit Withholding；
- calibration、rounding、reset 与 double-count 细节。

### 5. Security and Privacy

- 定理全部写成条件式。
- 明确 ZK 隐藏哪些 public/private fields。
- fallback flag、distance delta、period commitment 的 linkability 单列。

### 6. Evaluation

- RQ1 M0 攻击拒绝；
- RQ2 M1 收益/公平；
- RQ3 M2 depth/fixes 规模；
- RQ4 M3 certified bounds；
- RQ5 真实输入、route privacy、camera/TEE 仅在完成后加入。

### 7. Limitations

- 物理传感器与 authority compromise；
- 月度证明缺失的行政依赖；
- 多辖区、key rotation/revocation 与 trusted time；
- map matching/tariff boundary；
- 未完成的真实硬件和跨期隐私证据。

## 当前可写与不可写

### 可立即写

- 精确的 threat model 草案；
- V5 failure analysis；
- V6 方法定义和待证明 theorem statements；
- 实验协议、门禁、artifact 路径；
- limitations。

### 暂不可写成正式全量结果

- “full-corpus odometer fallback is fair”；
- “independent Linux server demonstrates city-scale deployability”；
- “E3 is globally bounded over all real trajectories”；
- “real receiver deployment works”；
- “WayBill provides route anonymity”。

## 图表计划

- Figure 1：measurement authority、policy authority、vehicle/prover、charger 的分离信任图。
- Figure 2：normal interval、outage interval、month-close reconciliation 的时间线。
- Table 1：PolicyProfile 字段与每字段攻击测试。
- Figure 3：M4 S1 全量 V5 time fallback vs V6 odometer fallback 的 paired surcharge CDF/boxen。
- Table 2：M4 S2 16 配置 × 10 trials 的 constraints/latency/memory/key size。
- Figure 4：M4 S3 全量实例的 LB/UB/gap 与 timeout CDF。
- Figure 5：M4 S4 route inference/linkability 随 horizon/opening 的变化。
- Table 3：claim、assumption、artifact 和 evidence status。

## 写作检查门禁

- 每个 security/fairness/privacy claim 都能链接到 [[Results/Reports/V6方法门禁与实验台账-2026-07]] 的 verified receipt。
- 全文搜索并人工复核 `authentic`, `trusted`, `tamper-proof`, `fair`, `upper bound`, `optimal`, `city-scale`, `deployable`, `anonymous`, `TEE`。
- 数值只从 aggregate artifact 自动接入；legacy 设计文档不作为最终数字源。
- bibliography、artifact availability、ethics/limitations 和 reproducibility 完整。
