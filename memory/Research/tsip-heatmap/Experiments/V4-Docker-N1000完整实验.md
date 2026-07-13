---
type: experiment
project: tsip-heatmap
updated: 2026-07-14
status: verified
tags: [tsip-heatmap, docker, n1000, groth16, experiment]
---

# V4 Docker N=1000 完整实验

## 目标

在完整 Groth16 V4 路径上运行 5 个数据集、3 个 seeds、每单元 1000 clients、6 warmup rounds 和 10 evaluation rounds，验证 proof generation/verification、A/R routing、aggregation、reconstruction 和 DP release 的 paper-scale 可执行性。

## 配置

| 项目 | 值 |
|---|---|
| datasets | tdrive, geolife, porto, rome, synthetic |
| seeds | 101, 202, 303 |
| clients | 1000 |
| warmup rounds | 6 |
| evaluation rounds | 10 |
| total units | 15 |
| concurrency | 2 |
| round timeout | 7200 s |
| condition | clean |

启动命令：

```bash
cd /Users/wanghao/Desktop/risefl_mvp/TSIP_heatmap_version/runtime/experiments-heatmap
caffeinate -dimsu python -u run_v4_docker_n1000_scale.py \
  --launch \
  --jobs 2 \
  --round-timeout-sec 7200
```

## 前置门禁

- compose config: pass
- datasets 1000: pass
- disk/resource/Docker capacity: pass
- Docker images: pass
- manifest artifacts: pass
- ports: 启动前 pass；运行中占用属于预期
- protocol/static/utility: pass

## 已验证 pilot

T-Drive seed 101 于 2026-07-10 12:56 至 16:21 +0800 完成：

- 16/16 rounds，6 warmup 加 10 evaluation。
- 15,000 client proofs generated。
- 15,000 shuffler proof attempts，15,000 verified，0 failed。
- 总 rejected=0；10 个 evaluation rounds 均为 A/R 1000/1000。
- reconstruction 10/10，DP 10/10。
- wall time 3h25m37s，约 1.216 proofs/s。

## 当前矩阵状态

| Seed | T-Drive | GeoLife | Porto | Rome | Synthetic |
|---|---|---|---|---|---|
| 101 | pass | pass | pass | pass | pass |
| 202 | pass | pass | pass | pass | pass |
| 303 | pass | pass | pass | pass | pass |

执行矩阵已为 15/15 pass。`launch_status.json` 于 2026-07-13 23:24:37 +0800 收敛为 `state=pass`、`completed_units=15`、`failed_units=0`、`total_units=15`。2026-07-14 strict aggregate 已逐单元验证并返回 `status=verified`。

## 2026-07-13 首次中断诊断（历史）

- 无 `run_v4_docker_n1000_scale.py`、`run_v4_docker_protocol_smoke.py` 或对应 `caffeinate` 进程。
- 两个 status mtime 均为 2026-07-12 12:18:11 +0800。
- 8 秒重复查询 health endpoint，proof total 均保持 3000，不再增长。
- client containers 内只有 `sleep infinity`。
- Docker 服务 healthy 不能改变上述中断判断。

## 2026-07-13 续跑状态

- 新 launcher 于 2026-07-13 19:11:51 +0800 写入 `started_at` 并仅调度两个非 pass 单元。
- 19:37 +0800：launcher PID 9233，Synthetic/303 worker PID 9353，Rome/303 worker PID 9354。
- Rome/303 与 Synthetic/303 均为 2/16；相较本次启动后的 1/16 已发生推进。
- 两组 client/shuffler 容器均有持续 CPU 使用，当前判断为真实计算中。
- 运行期间禁止 compose down 或重复执行 launcher；只有进程消失且 receipt 未 pass 才使用恢复流程。
- 22:47 +0800 只读复核：launcher/两个 worker 进程仍存在；Rome/303 与 Synthetic/303 均推进到 14/16，`state=running` 且 `failure=null`。`launch_status.json` 仍只登记 13/15 completed，因此不提前计为 pass。
- 23:24:37 +0800：Rome/303 与 Synthetic/303 均返回 `state=pass`、`returncode=0`；launcher 写入 15/15 pass 后正常退出，宿主机不再有 launcher、worker 或 caffeinate 进程。

## 续跑流程

当前恢复流程已启动，不再执行本段操作。若本次进程异常退出且两个 receipt 仍非 pass，才对 `v4n1000_rome_303` 和 `v4n1000_synthetic_303` 执行 compose down，再运行原启动命令；启动器会根据 receipt 跳过所有已通过单元。

## 完成判据

见 [[01-Plan]]。执行矩阵、strict aggregate、paper-evidence 与 manuscript checker 都已通过；只剩最终构建和视觉门禁。
可引用数字、timing exclusion 和 artifact hashes 见 [[Results/Reports/V4实验结果-2026-07]]。

## 2026-07-14 Final-scale 接管检查

- 只读检查确认 launcher 为 15/15 pass，Rome/303 与 Synthetic/303 均为 16/16 pass。
- 无 launcher、worker、`caffeinate` 进程，也无活动 v4n1000 容器；这是已完成后的正常状态，不是中断。
- 接管分类为 `COMPLETE`，因此未启动 Docker 恢复路径。当时尚缺 strict aggregate artifacts；该缺口已由下一节关闭。

## 2026-07-14 Strict aggregate

- `script/summarize_v4_n1000_scale.py` fail closed 验证 manifest、launch plan/status、15 个 unit hashes、artifact hashes、config/gates、16 轮语义和逐轮 proof/route/reconstruction/DP 字段。
- 功能总账为 15 units、240 rounds、225,000 client proofs generated、225,000 shuffler proofs verified、0 failed、150,000/150,000 A/R receipts、150/150 reconstruction 与 150/150 DP release。
- Rome/101 与 Synthetic/101 的 `round_id` 各出现约 62,962 秒宿主休眠间隔，超过 7,200 秒 round-timeout；两单元功能证据保留，但不进入时间统计。
- 13 个连续计时单元的 per-unit end-to-end throughput 为 `1.000 +/- 0.069 proofs/s`，单元 wall time 均值约 4.183 h；每数据集仍至少有两个 timing seeds。
- 生成路径：`docker_n1000_v4/aggregate_summary.json`、`aggregate_by_dataset.csv`、`TSIP/tables/tab_v4_n1000_scale.tex`。对应 SHA-256 为 `2ad8e3...16a95`、`11050a...bbe4`、`d16120...af43`。
- 确定性重生成哈希一致，33 summarizer tests 和 202 combined Heatmap tests 全部通过；临时 paper-evidence build 已返回 `scale.status=verified`。
- Strict aggregate 实现与 receipts 已提交为 `248f858c`。
- Final-scale paper evidence 已返回 `scale.status=verified`；三组合同测试合计 220 passed，实验无需重跑。
