# TSIP Settlement-Core 设计说明

更新时间：2026-05-31

当前工程只保留 charger-centered `settlement-core`。旧 heatmap/ESA 原型、
Shuffler、Aggregator A/R、Decoder、客户端模拟器和 `tsip_main` 历史电路已移除。
历史实验 CSV 与论文材料仍保留，作为研究记录，不再作为可运行入口。

## 1. 当前运行路径

`docker-compose.yml` 只启动 Charger。设备提交固定大小的 period submission：

1. Charger 验证设备注册公钥与 `device_attestation_commitment`。
2. Charger 验证 Groth16 period proof。
3. Charger 用签名 fixes 和 tariff 表重算公开 statement。
4. Charger 按 `period_id` 去重。
5. Charger 将公开费用、公开里程和 fallback 计数累加进 `month_id` 对应账本。

当前月账单采用 accepted period proofs 的直接累加，不使用递归 SNARK。

## 2. 固定电路规格

| 参数 | 当前值 |
|---|---:|
| fixes per proof | 25 |
| intervals per proof | 24 |
| 默认 cadence | 300s |
| 默认 proof 覆盖时长 | 2h |
| tariff Merkle depth | 8 |
| shipped profile | `settlement_period_v5_k6` |

cadence 改为 `120s` 或 `60s` 时，固定电路仍然包含 24 个 intervals，因此每个
proof 分别覆盖 48 分钟或 24 分钟。月度 proof 数相对 `300s` 分别放大为
`2.5x` 和 `5x`。

## 3. 代码入口

| 模块 | 文件 |
|---|---|
| Docker 编排 | `docker-compose.yml` |
| Charger API | `services/charger/app.py` |
| Settlement 逻辑 | `common/settlement.py` |
| 评估 harness | `common/eval_harness.py` |
| E2/E3 评估函数 | `common/eval_experiments.py` |
| 轨迹预处理 | `common/trajectory_preprocess.py` |
| OSM tariff 工具 | `common/osm_vectors.py` |
| 基础电路 | `circuits/settlement_period_v5_base.circom` |
| k6 profile | `circuits/settlement_period_v5_k6.circom` |
| 构建脚本 | `script/build_settlement_period_v5.sh` |
| prove/verify 脚本 | `script/prove_settlement_period_v5.py` |
| 几何绑定审计 | `script/audit_geometric_binding.py` |

## 4. 月度成本口径

设月驾驶小时数为 `H`，固定电路包含 `24` 个 intervals，cadence 为 `c` 秒：

```text
period_hours        = 24 * c / 3600
monthly_periods     = ceil(H / period_hours)
monthly_prove_cost  = monthly_periods * period_prove_cost
monthly_verify_cost = monthly_periods * period_verify_cost
monthly_upload      = monthly_periods * period_upload_bytes
```

E6 应 sweep `{60s, 120s, 300s}`，与 E2 诚实 fallback penalty 和 E3 residual
一起形成统一 cadence trade-off 表。

## 5. Submission gate 证据与边界

- Terminal fix 已补齐几何绑定：`x[24] = fix_cell_x[24] * 100`、
  `y[24] = fix_cell_y[24] * 100`。最后一个签名 cell 不能再与跨 period
  continuity 使用的末端米制坐标分离。
- 真实 `snarkjs wtns calculate` 回归覆盖 terminal `(99, 99)` 控制例：
  相对上一个 fix `(23, 0)`，`distSq = 155,770,000 > 98,010,000`，
  两维 cell 仍满足 `< 100`。witness 在 `stepTierLE` continuity 约束拒绝。
- `odometer_delta` 与 cell 几何距离没有强等式绑定。当前电路只约束
  `odometer_delta <= dt * tier_vmax`；billing 距离完整性依赖设备侧 odometer
  attestation。路网距离与格点直线距离并不相等，加入松弛几何绑定前必须先用
  物理 odometer 数据完成 detour factor 标定。

## 6. 当前未完成项

- `SETTLEMENT_PERIOD_MAX_HOURS` 尚未在 Charger 提交路径显式 enforce。
- Charger API 原型仍上传原始 fixes。
- 几何绑定 proxy audit 不能替代物理 odometer 校准数据。
- 递归月度 proof 聚合尚未实现；论文主结果应使用直接累加口径。

## 7. 常用命令

```bash
make test-fast
make build-settlement
make setup-settlement
make prove-settlement
python3 script/audit_geometric_binding.py --cadence-sec 60 120 300
docker compose up -d --build charger
```
