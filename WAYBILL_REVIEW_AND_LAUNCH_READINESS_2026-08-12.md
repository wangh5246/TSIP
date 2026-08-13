# WayBill 全面审阅与 M4 启动就绪报告（2026-08-12）

## 执行结论

**论文：Major Revision。M4：Conditional No-Go。**

2026-08-13 跟进：本报告发现的源代码级 P0 已进入
`waybill-formal-readiness-v3` 本地不可变发布；四个 Linux/amd64 OCI、绑定
SBOM/Trivy 报告和自校验 release bundle 已按 V3 重建。安全刷新同时将
`cryptography` 从 48.0.1 升至 50.0.0，并再次通过完整本地 CI。旧
`waybill-formal-readiness-v2` 仍禁止用于 M4。正式试验继续保持 No-Go，直至在
实际 Linux x86-64 目标生成只读 SIF、通过 RG2/RG6、完成全量
prepared/canonical corpus、materialized plan 和逐阶段 smoke。

2026-08-13 目标机跟进：Ubuntu 24.04 x86-64（80 logical CPU、314 GiB RAM、
约 1.35 TiB 可用）已安装 Apptainer 1.5.3；V3 SIF 已按 root:root/0555 冻结，
SHA-256 为 `156450284f60daf89c65c91b93e062d6e95bb1fdb1b561107111334963ecb607`。
目标 RG2 已通过：29,029 files、4,597,898,795 bytes，四个 tree hash 与本地一致，
PTAU 精确校验通过。真实 RG6 同时发现 V3 探测缺陷：`snarkjs 0.7.6
--version` 正常打印 `snarkjs@0.7.6` 但返回 99，通用 helper 将其误判为缺失。
因此 V3 仍不可用于 `init-run`；V4 以精确 exit-99 + version 双重检查修复并
作为后继发布重新冻结，绝不手改 RG6 receipt。

Go 规则为：

```text
local_full_verification
AND successor_release_verified
AND target_RG6_passed
AND plan.materialized
AND all_stage_smokes_passed
```

任一条件不满足，禁止 `init-run`。线性操作卡见 `WAYBILL_TOMORROW_RUNBOOK.md`。

## 本轮已闭环的工程问题

1. S2 concurrency 与 S5 corpus 不再创建会被 artifact validator 拒绝的 symlink；正式 attempt 内只保留实体文件及递归哈希。
2. S5 的 100 个 corpus attestation 形成合法连续 device chain；handler 作业在 proof-only 请求前逐条 anchor。
3. S5 `charger` 过强命名改为 `handler`，证据范围固定为 FastAPI TestClient + SQLite 进程内功能并发，不推断 TLS/Uvicorn/PostgreSQL/server capacity。
4. S3 以 `(dataset, period, radius)` 四桶一组运行，恢复 fine-to-coarse incumbent；strict merge 要求 main representative gap ≤1%、至少 95% 全实例 gap ≤5%。
5. S3 checker、bound direction、small-oracle 等 soundness failure 一票否决，不能混入允许的 5% 执行未决份额。
6. S1 bootstrap 必须具有 vehicle/device identity，拒绝缺失身份的 period，不再退化为 period-level resampling。
7. S2 新增 P99；n=10 的 P95/P99 明确为描述性 nearest-rank 最大值。
8. 失败 stage result 也绑定 attempt receipt；resource-rejected 不再被笼统归为 nonzero exit。
9. strict merge 新增哈希绑定的 `failure-summary.json` 和 `scientific-aggregate.json`，保留分母、失败分类、资源数据、selected attempt/receipt 身份、每个 seed 与跨 seed median/min/max。
10. protocol 中注册 primary endpoint 和 cross-seed reporting 规则；当前协议哈希为 `fb75b2f092c83ded2b115c4a23d1625cf3afdf5e218ffc2ea55cb784159467b0`。

## 数据恢复与 RG2

- Rome 原始文件：1,608,435,716 bytes；SHA-256 `ea282cd631b66ebbb79680939293956301be769282c9c02d0d989ecdf53e0cc1`。
- 四数据集合计：29,029 files；4,597,898,795 bytes；T-Drive、GeoLife、Porto、Rome 全部 `complete=true`。
- canonical manifest identity：`6239ad7bffbcd159e9b62e0bd8fa0263901904c840fbb3bad4676e65393b7f2f`。
- manifest 文件 SHA-256：`64e8cbe7b4ed5e551ce9a6da0e6427c5e2809b51600c76417cb4a700845c1308`。
- raw-files ledger SHA-256：`e9c5061ddf7ef64fbef4e29bb406c4994a3cfa24121bb2424d3f674b28fc04c5`。
- `validate-data-manifest`：RG2 passed。

该本地清单不能代替目标侧重新验证，也不能代替 uncapped prepared/canonical materialization。

## 验证证据

- focused formal regression：46 passed；新增失败回执/S3 gate 定向回归：3 passed。
- 完整 `script/ci_local.sh`：compileall、flake8、mypy、config validation 全部通过；安全升级后全仓 **548 passed、3 skipped、0 failed**，耗时 231.98 s。
- `validate-config`：RG7 protocol shape、RG3 tariff registry、RG5 entrypoints 全部 passed。
- V3 bundle 通过独立自校验；V2 bundle 的自校验仍只证明旧字节完整，不证明其 M4 runner 语义正确。
- `git diff --check`、CLI help 与 `bash -n script/check_deploy_host.sh` 通过。
- LaTeX/BibTeX 构建：7 页，无 undefined citation/reference、无 overfull；仅有不裁切内容的 underfull warning。
- 最终 PDF：`WayBill/output/pdf/WayBill_RUC_manuscript.pdf`；SHA-256 `a3ae8e841108a5d7734d4a8ace0928f793d192179b0e22a0498e58a34de3eadc`。已逐页检查，无重叠、裁切或孤立参考文献页。

3 个 skip 均已定位：2 个历史 V5 witness 负测缺少 materialized V5 WASM，1 个 PostgreSQL parity 测试未设置 `WAYBILL_TEST_POSTGRES_URL`。它们不能替代目标 PostgreSQL 或正式容器证据；V3 的目标机 checkout 和目标 PostgreSQL 环境仍须重跑同一套验证。

## 五角论文评审综合

| 维度 | 综合分 |
|---|---:|
| Originality | 73/100 |
| Methodological rigor | 68/100 |
| Evidence sufficiency | 42/100 |
| Argument coherence | 84/100 |
| Writing quality | 84/100 |
| 综合 | 约 65/100 |

评审共识是 Major Revision；EIC 与 Devil's Advocate 倾向“当前拒稿，完成 M4 后重投”。证据分低的根因是 M4 未执行，而不是本轮文稿润色不足。

文稿已完成：标题收窄为 disclosure-minimizing；TCB 明确包含 acquisition logic；`position_valid` 改为 receiver-sealed origin-label/profile admissibility；定理改为 successful-close conditional economic conservatism；显式解释“最高费率基线减去验证折扣”；S1 限定为公式级 trace sensitivity；S3 限定为 bounded cell/trajectory displacement；S5 限定为进程内 handler；补充最接近替代方案、14 篇相关文献、申诉状态机、公平/可用性/治理限制。

Canonical receipt 只支持一次 25-fix V6 reference/circuit 一致、一次 Groth16 prove/verify，以及 TestClient 路径上的 anchor、replay、signal tamper 和 month close。它不支持四数据集总体结论、tail scaling、GNSS 物理真实性、群体隐私、生产 PostgreSQL/HTTPS 或修复后 runner 的大规模可运行性。

## 仍阻塞正式启动的 P0

1. **目标运行时**：V3 SIF/RG2/PTAU 已完成；需完成 V4 不可变发布、V4 SIF 和机器 RG6。
2. **目标 RG6**：实际 Linux x86-64、32 vCPU、128 GiB、1 TiB 起步盘、精确 PTAU/SIF、≥500 GiB 加计划安全余量的 workspace；macOS 不得代签。
3. **全量物化**：在唯一共享根完成 uncapped preprocessing 和 canonical corpus；生成 `materialized=true`、非空 `expected_job_count` 的最终 plan。
4. **逐阶段 smoke**：S1、S2-main、S3 group、S4、S2-concurrency、S5-corpus、S5-verifier、S5-handler 各一项通过并验证 receipt。
5. **严格聚合**：M4 全矩阵及限定重试完成，`aggregate.status=passed` 且 S3 aggregate gate passed，方可回填结果槽。

## 投稿前但不阻塞实验的作者输入

`WayBill/submission_declarations.tex` 仍保留 author-only 占位：机构伦理/豁免、CRediT、资助、利益冲突和 AI 使用披露。目标 venue、页数和匿名政策也需作者确认。这些内容不能由工程审阅者代填，但不阻塞 M4 技术启动。

## 最终裁决

源代码级已知语义缺陷、本地验证和 V3 不可变发布已闭环；目标 SIF/RG2/PTAU 已完成，但真实目标发现的 RG6 probe 缺陷需要 V4 后继发布，materialized plan 与八类 smoke 也尚未闭环。因此当前仍是具有明确关闭路径的 **Conditional No-Go**。这些目标条件全部满足后才可转换为 Go；否则应顺延正式 `init-run`，不能用旧 V2/V3 或缩小实验替代。
