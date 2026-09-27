# RAG 地面场景与降级验证（2026-09-26）

## 本轮范围

本轮完成 knowledge 层的地面场景检索隔离，以及既有报告界面的建议、引用和失败状态自动化验证。未完成地面报告的确定性分析适配、真实云端推荐生成或人工 Groundedness 复审；不能把这些结果称为地面模式的生产端到端验收。

## 实现与证据边界

- Planner/Retriever 升级为 1.1，地面查询显式包含测试协议；协议在 Dense 候选加载和 FTS5 排序之前过滤。片段协议缺失时不匹配，其他人口、指标、支持类型和推荐许可过滤继续生效。
- 地面走路使用现有允许的 `overground_walk` 文献。已读取本地 `data/knowledge/raw/pmc3927048.xml` 的摘要：研究场景为健康青年在步道上的步行测量。它可作为测量方法复核的候选文献，不能证明本项目算法或 8 段设备的精度，也不能授权临床建议。
- 地面跑步不继承跑台测量或中长跑训练证据。现有对比文献 `pmc7069922` 的 `recommendation_allowed` 为 false；保持此限制，不擅自提升为已审核建议来源。
- 规划异常产生 `planning_failed` 降级结果；未形成适用查询产生 `no_supported_query`；形成查询但未命中产生 `no_matching_evidence`。三种情况都不调用推荐生成器，保留上游确定性结论。

## 自动化验证

命令：

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_knowledge*.py tests/test_report_analysis_ui.py \
  tests/test_report_analysis_service.py
```

结果：104 passed。覆盖地面步行与跑步的隔离、无协议/错误协议片段排除、临床人群与空 Claim 拒绝、规划异常、无命中、引用协议白名单、建议限制展示，以及降级/无证据时已验证 Claim 仍显示。发布门测试使用临时合成审查工件，并验证旧 Planner 版本被拒绝；这些测试工件不用于生产发布。

## 本地索引复测

使用已缓存的真实 fastembed 模型、`data/knowledge/knowledge.sqlite3` 和冻结 30 问，设置 `HF_HUB_OFFLINE=1`，没有调用云端模型。机器可读记录：[rag_protocol_canary_20260926.json](../benchmark_results/rag_protocol_canary_20260926.json)。

| 指标 | 本轮结果 |
| --- | --- |
| Recall@5 / Recall@10 | 1.000 / 1.000 |
| Precision@5 | 0.5333 |
| MRR | 0.900 |
| nDCG@10 | 0.9283 |
| 冻结基准回归 | 无 |

地面走路的 measurement_review / retest 均只返回 `pmc3927048`，协议均为 `overground_walk`。地面跑步无适用查询。此处检索测试使用构造的已验证 Claim 输入，未经过地面报告适配器，不能证明应用整链已接通。

## 发布状态及后续验收

当前 `v1_release_status()` 返回 `invalid`：旧冻结工件记录 Planner/Retriever 1.0，本轮运行版本为 1.1。未修改旧 Gate JSON、指纹或人工审查记录冒充通过。当前版本生产 RAG 建议暂不可用，既有确定性报告分析保留。

恢复生产前需要：

1. 为新版本重新运行真实模型 Benchmark 并完成人工 Groundedness 审查，使用既有 promotion 流程发布匹配工件。
2. 地面模式先补齐 `reporting.models.TestType`、ReportDataPackageBuilder、指标和质量语义、服务入口及 UI 智能分析可用性，不能通过伪装成跑台报告接入。
3. 新增包含实际段数、有效/排除记录及左右未知的地面端到端 Fixture；审核地面跑步适用来源后才扩展支持矩阵。
4. 发布门通过后，在应用内用持久化报告验证实际建议、可追溯引用、无证据与失败状态，并保存独立验收记录。当前 Qt 自动化展示检查不代替此项。
