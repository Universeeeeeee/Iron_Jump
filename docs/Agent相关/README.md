# Agent 文档索引

> 更新日期：2026-11-12

本目录包含当前实现文档、实施记录和早期研究方案。不同文件不具有同等事实优先级。

## 当前事实源

1. `ReportAgentArchitecture_0808.md`：当前 Report Agent 架构、可信边界和生产默认。
2. `ReportAgentMVPImplementationPlan_0808.md`：MVP 实施追踪记录和验收来源。
3. `../../benchmark_results/README.md`：真实模型合成 Benchmark、消融结果和限制。
4. `../../docs/architecture.md`：Config Agent、Report Agent、数据层和 UI 的系统级依赖关系。

发生冲突时，优先级为：当前代码与测试结果 → `benchmark_results/README.md` → `ReportAgentArchitecture_0808.md` → 实施记录 → 其他历史方案。

## 历史研究方案

以下文件用于保留设计演进、论文素材来源或外部讨论，不应直接作为当前实现说明：

- `new Agent分析报告方案.md`
- `运动测试_AI_智能分析与报告生成优化方案.md`
- `面向运动测试的Agent编排式可信分析与报告系统_完整版.md`
- `面向运动测试的Agent编排式可信分析与报告系统_完整版.docx`
- `面向运动测试的Agent编排式可信分析与报告系统_去除素材版.docx`
- `AI 在运动测试系统报告生成与分析中的角色与边界.docx`

当前生产分析使用 AnalysisSketch + Compact Series、按测试类型加载领域 Skill，并通过单步 `AnalysisDecision` 序贯循环执行。当前已实现重点发现与证据图、报告内追问、回答历史恢复、最近一次同协议个人历史比较，以及用户备注和完整测试均值复测目标。范围与接口见架构文档的“2026-11 报告交互扩展”。团队横向分析、任意多次历史趋势和自动训练处方属于后续范围。文献建议仍受独立发布审查约束。

## 维护规则

- 新的生产决策先更新架构文档和 Benchmark 说明，不逐份同步所有历史文档。
- 合成数据结论必须明确标为工程验证，不能表述为真实运动员、训练或医学有效性。
- DOCX 若用于正式交付，应由确认后的 Markdown 事实源统一生成；不手工维护多份互相冲突的正文。
