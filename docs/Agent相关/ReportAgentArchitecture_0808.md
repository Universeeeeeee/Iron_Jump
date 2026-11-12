# Iron_Jump 智能分析与报告 Agent 架构方案

> 版本：v3.1（2026-11-12 报告交互扩展回写）
> 状态：单步序贯循环、证据图表、报告追问、最近一次同协议比较与用户复测目标已实现
> 适用范围：Iron_Jump 的 AI 智能参数配置与智能报告分析模块
> 核心原则：**确定性算法负责数值，Agent 负责分析路径选择、Tool 编排、证据综合与自然语言表达。**

---

## 2026-11 报告交互扩展

本节记录当前分支已实现的范围。后文初版设计中的多次历史、团队比较及其他长期设计，按本节所列实现边界理解。

| 能力 | 当前行为 | 主要实现 |
| --- | --- | --- |
| 重点与证据图 | 最多三项重点，合并重复发现，总结与图表使用已验证证据；图点可定位原始记录 | `reporting/presentation.py`、`reporting/charts.py`、`ui/report_analysis.py` |
| 当前报告追问 | `/report/ask` 接收问题、父分析和所选发现；指标、侧别、记录序号与时间范围解析后固定记录引用 | `reporting/questions.py`、`ReportAnalysisService.ask` |
| 回答历史 | `/report/history` 与 `/report/saved` 恢复已验证回答，并支持从较早回答继续提问 | `ReportRepository`、`ReportView` |
| 个人历史 | 正式用户可比较最近一次同协议测试，游客跳过；按相同条件分别选取两次有效记录，计算各自均值和本次减上次 | `reporting/longitudinal.py`、`compare_longitudinal/compare_session_records` |
| 备注与目标 | 用户为具体发现填写备注及完整测试均值目标；每次修改追加版本，后续同协议测试追踪原始基线；支持完成、归档和冲突检测 | `reporting/annotations.py`、`ui/report_annotations.py` |

跨测试 Evidence 绑定两份 session、数据包摘要、协议和各自记录范围。ClaimValidator 重算比较结果并核对证据与审计；历史记录修改、删除或最近匹配基线变化后，旧回答失效。相同快照的中断运行可通过 checkpoint 恢复。

纯换图继承原记录范围与分组。前后半程默认按各自有效记录数划分；历史追问的均值为所选记录均值，完整报告对比表直接读取正式摘要均值。备注为用户记录，复测数值目标由用户设置。建议按已有 `claim_refs` 关联发现，文献建议的运行发布检查和人工审查沿用 `knowledge/release_artifacts/README.md`。

数值绑定、样本与质量条件继续由代码校验。显示的限制来自实际证据及运行状态，通用免责声明和重复的限制段落已清理。Excel、PDF 和旧版报告读取通过对应回归验证，工程回放使用合成或明确标注为模拟的记录。

## 1. 文档目的

Iron_Jump 当前已经具备三类运动测试：

1. 纵跳测试（Jump）
2. 跑步机步态测试（Treadmill Gait）
3. 跑步机跑步测试（Treadmill Run）

系统通过红外光电阵列采集数据，并由确定性算法计算运动学与时序指标。

当前需要增加两类 AI 能力：

- **测试前 AI 智能参数配置**
- **测试后 AI 智能分析与报告生成**

这两类能力都可以复用 PydanticAI，但业务性质不同，因此应当在架构上解耦。

本文件整理当前已经确认的整体方案，并区分：

- 当前确定方案
- MVP 实现范围
- 未来演进模块

当前实现与本文初稿存在两项重要收敛。观察输入采用 `AnalysisSketch + Compact Series`，关闭 Screening Cues；执行器不再一次生成完整 Plan/DAG，而是按测试类型加载领域 Skill，每轮只生成并校验一个 `AnalysisDecision`，根据新 Evidence 更新状态后再决定下一步。旧 Plan/DAG 仅用于兼容读取和非生产测试入口；详细结果见 `benchmark_results/README.md`。

---

# 2. 总体架构原则

## 2.1 Agent 不负责计算正式数值

系统中所有正式数值必须来自：

- 现有确定性运动测试算法
- 确定性统计函数
- 确定性比较 Tool
- 明确定义的规则与兼容性策略

Agent 不允许：

- 自己做正式算术
- 自己创造公式
- 任意执行 Python
- 使用开放式 SQL
- 直接访问数据库自由查询
- 根据自然语言“估算”正式结果

Agent 的职责是：

1. 理解用户分析目标
2. 判断应该分析哪些维度
3. 调用合适的领域 Tool
4. 根据 Tool 返回的证据更新判断
5. 必要时重新规划分析方向
6. 将经过验证的事实综合成自然语言分析

---

## 2.2 两个 AI 模块解耦

建议整体结构：

```text
Iron_Jump
│
├── Config Agent
│   ├── PydanticAI
│   ├── Prompt
│   ├── LLMTestConfig
│   ├── Pydantic Validation
│   └── TestConfig
│
└── Report Analysis Agent
    ├── PydanticAI
    ├── ReportManifest
    ├── Analysis Loop
    ├── Analysis Tools
    ├── AnalysisState
    ├── Validators
    └── Final Analysis
```

两者可以共享：

- 模型 Provider
- API Key / 网络配置
- 日志
- 通用 Pydantic 模型基础设施
- Agent 调用封装

但不共享具体业务流程。

---

# 3. 测试前 AI 智能参数配置

该模块本质上属于：

> Natural Language → Structured Configuration

当前方案可以继续保持简单。

流程：

```text
用户自然语言
    ↓
PydanticAI Agent
    ↓
LLMTestConfig(BaseModel)
    ↓
Pydantic Validation
    ↓
转换
    ↓
TestConfig(dataclass)
    ↓
用户确认 / 应用配置
```

该模块没有必要引入：

- Analysis Loop
- Tool Planning
- Hypothesis
- Replan
- 复杂 Workflow

因此现有参数配置 Agent 可以基本保持不变。

---

# 4. 智能报告分析的核心问题

目前 UI 已经可以展示：

- 统计卡片
- 图表
- 步态足迹
- 表格
- 中文结果说明

但这些属于：

> Presentation Layer

并不是适合 Agent 使用的：

> Semantic Evidence Layer

Agent 真正需要知道的不只是“平均值是多少”，还包括：

- 指标叫什么
- 指标定义是什么
- 单位是什么
- 数据属于哪次测试
- 每条记录顺序
- 左右侧
- 时间
- 是否有效
- 是否被纳入统计
- 为什么被排除
- 是否存在质量问题
- 当前协议版本
- 当前指标定义版本
- 当前设备与配置
- 历史比较是否兼容
- 该结论来自哪个原始事实
- 哪个 Tool 生成了这个比较结果

因此必须建立独立的报告语义层。

---

# 5. 推荐的数据层级

最终推荐：

```text
Immutable TestReport
        ↓
ReportDataPackage
        ↓
ReportManifest
        ↓
Bounded Domain Tools
        ↓
Analysis Agent
        ↓
AnalysisPackage
        ↓
Validator
        ↓
UI Rendering
```

---

# 6. TestReport：事实源

现有 `TestReport` 继续作为系统事实源。

要求：

- 保持不可变
- 不为了 Agent 强行修改原有业务结构
- 不让 TestReport 同时承担 Agent DTO、数据库模型、UI ViewModel 等所有职责

应通过独立 Builder 转换：

```text
TestReport
    ↓
ReportDataPackageBuilder
    ↓
ReportDataPackage
```

---

# 7. ReportDataPackage：完整语义证据层

## 7.1 设计目标

ReportDataPackage 应尽可能接近“语义无损”。

需要保留：

1. 原始数值
2. 记录顺序
3. 左右侧
4. 时间或 ordinal
5. inclusion / exclusion
6. missing / invalid
7. 指标定义
8. 单位
9. 协议版本
10. 指标版本
11. 设备配置
12. 数据质量
13. 来源关系
14. 可重复计算所需信息

ReportDataPackage 是一个**逻辑数据包**，不意味着必须全部塞进一个巨大的 JSON。

---

# 8. RecordSet 优先，而不是 Series 优先

逐跳、逐步、周期数据必须首先保留为行级 RecordSet。

例如一步的数据：

```text
step_id
step_ordinal
timestamp
side
contact_time
flight_time
step_length
stride_length
cadence
speed
valid
included
exclusion_reasons
quality_flags
```

原因：如果分别维护 `contact_time_series`、`flight_time_series`、`side_series`、`included_series`，在过滤、缺失、排除后容易发生错位。

因此：

> RecordSet 是权威数据，Series 是 RecordSet 某一字段的可查询投影。

---

# 9. 推荐核心对象

## 9.1 Metadata

```python
class ReportMetadata(BaseModel):
    report_id: str
    package_id: str
    test_type: str
    subject_ref: str
    team_ref: str | None
    tested_at: datetime
    schema_version: str
    protocol_version: str
    metric_definition_version: str
    configuration_snapshot_id: str
    device_configuration_id: str
    source_report_digest: str
    package_digest: str
```

## 9.2 MetricDefinition

```python
class MetricDefinition(BaseModel):
    metric_code: str
    name_zh: str
    canonical_unit: str
    definition: str
    applicable_test_types: list[str]
    direction: Literal[
        "higher_is_better",
        "lower_is_better",
        "target_range",
        "descriptive_only",
        "context_dependent",
    ]
    source_type: Literal[
        "sensor_observation",
        "deterministic_algorithm",
        "deterministic_comparison",
    ]
    has_sequence: bool
    supports_side_comparison: bool
    supports_longitudinal: bool
    supports_cohort: bool
```

## 9.3 ScalarFact

```python
class ScalarFact(BaseModel):
    fact_id: str
    metric_code: str
    statistic: str
    value: float | None
    unit: str
    status: Literal[
        "present",
        "missing",
        "invalid",
        "not_applicable",
    ]
    missing_reason: str | None
    sample_count: int | None
    source_series_id: str | None
    provenance_id: str
    quality_flag_ids: list[str]
```

## 9.4 RecordSetDescriptor

```python
class RecordSetDescriptor(BaseModel):
    record_set_id: str
    record_type: Literal[
        "jump_trial",
        "step",
        "gait_cycle",
        "boundary_cycle",
        "contact_event",
        "lift_event",
        "raw_frame",
        "footprint_frame",
    ]
    schema_version: str
    row_count: int
    primary_key_field: str
    ordering_fields: list[str]
    storage_ref: str
    content_digest: str
```

## 9.5 SeriesDescriptor

```python
class SeriesDescriptor(BaseModel):
    series_id: str
    metric_code: str
    record_set_id: str
    value_field: str
    ordinal_field: str
    timestamp_field: str | None
    side_field: str | None
    total_count: int
    observed_count: int
    valid_count: int
    included_count: int
    excluded_count: int
    ordering_semantics: str
    temporal_profile_ref: str | None
```

---

# 10. 按测试类型区分 Payload

不要把三个测试强行塞进一个巨大 Optional Schema。

推荐：

```text
ReportDataPackage
│
├── common
│   ├── metadata
│   ├── metric_catalog
│   ├── facts
│   ├── record_sets
│   ├── series_index
│   ├── quality
│   └── provenance
│
└── payload
    ├── JumpPayload
    ├── TreadmillGaitPayload
    └── TreadmillRunPayload
```

Pydantic 中可以使用 discriminated union。

---

# 11. ReportManifest：Agent 首次读取的数据

Agent 不应该一开始读取完整 ReportDataPackage。

第一步只读取：

> ReportManifest

ReportManifest 是紧凑索引和分析入口。

## 11.1 Manifest 应包含

- package_id
- test_type
- tested_at
- protocol_version
- metric_definition_version
- snapshot digest
- total / valid / included / excluded records
- overall quality
- critical / limiting flags
- metric code / name / unit / direction
- key facts
- series inventory
- temporal / side / longitudinal / cohort 能力
- deterministic inspection cues
- available tools
- tool / token limits

## 11.2 不应直接放进 Manifest

- 所有逐步记录
- 所有逐跳记录
- 1000Hz 原始帧
- 完整 footprint replay
- 所有历史报告
- cohort 成员级原始数据
- 完整 provenance graph
- UI 格式化文本

---

# 12. Recoverability 与 Discoverability

需要区分两个问题。

## Recoverability

只要 stable reference 存在：

```text
Manifest
 → Series ID
 → RecordSet ID
 → Exact Row
```

就可以保证完整数据可恢复。

## Discoverability

任何压缩摘要都不能保证 Agent 自动发现任意隐藏模式。

因此需要引入：

> Deterministic Screening Profile

它不是最终结论，而是帮助 Agent 知道“哪里值得继续看”。

---

# 13. MVP Screening Profile

第一版只需要非常基础的确定性筛查：

- global statistics
- quartile statistics
- first 25% vs last 25%
- left / right statistics
- outlier count
- with / without outlier difference
- included vs all-valid difference
- missing distribution
- exclusion distribution

可识别的候选模式：

- 后程波动增加
- 前后阶段水平变化
- 单个异常点影响过大
- 持续左右不对称
- 不对称主要来自少数样本
- 均值相同但离散程度不同
- 排除样本后方向发生变化
- 边界周期造成假象

Manifest 中只暴露触发的 cue。

---

# 14. Tool 设计原则

Tool 必须是：

> 有边界、确定性、可复现、可审计的领域查询函数。

不提供：

- arbitrary Python
- arbitrary SQL
- arbitrary expression
- unrestricted cohort filtering

Report Agent 只面对三个语义级分析 Tool。Tool 是权限、数据访问和失败语义的边界；确定性分析方法是 Tool 内部可选择的计算语义；Analysis Kernel 提供共享统计、筛选、稳定 ID 和规范化摘要函数。三者不能使用同一版本号替代。

---

# 15. 三个分析 Tool 与确定性分析方法

| Tool | 数据范围 | 版本 | 当前状态 |
|---|---|---|---|
| `analyze_current_session` | `current_session` | `analyze-current-session-tool/1.1` | 启用 |
| `compare_longitudinal` | `longitudinal` | `compare-longitudinal-tool/1.0` | 历史追问绑定两份快照后启用 |
| `compare_cohort` | `cohort` | `compare-cohort-tool/0.1-disabled` | 注册但禁用 |

`analyze_current_session` 当前提供六种确定性分析方法，另由 `compare_longitudinal` 提供 `compare_session_records`：

- `summarize_records`
- `verify_temporal_change`
- `verify_side_segment_difference`
- `verify_cross_metric_cochange`
- `verify_exclusion_robustness`
- `quality_scope_check`

Agent 只能选择能力目录中已启用 Tool 及其可用方法，不能注册 Tool、创建方法、声明权限或填写版本。一个 Agent 可见方法可以在 Kernel 内部执行筛选、分段、均值、方差、异常记录排除和重算等多个统计步骤，这些内部步骤不增加分析计划节点数。

---

# 16. Tool、Method 与 Kernel 三层版本

三层版本分别进入 `ToolRunRecord` 审计信息：

```text
Tool Version：接口、权限、数据访问和返回契约
Analysis Method Version：分段、样本量、判定、容差和异常值语义
Kernel Version：共享统计、规范化、稳定 ID、精度和 Evidence 结构
```

当前版本为：

```text
analysis-method-registry/1.0
analysis-kernel/1.0
```

修改单个方法不得提升其他方法版本；单纯重命名、移动代码或增加 Tool 包装不得提升 Kernel 版本。Registry 目录版本只用于能力缓存和诊断，不能替代上述三层版本。

---

# 17. Longitudinal 与 Cohort 不写死在单次 ReportDataPackage 中

历史比较和团队比较依赖：

- 当前目标
- baseline
- 时间范围
- protocol
- metric version
- cohort snapshot
- strata
- compatibility policy

因此比较应由 Tool 动态生成：

```text
Current Report
+
Reference Snapshot
+
Compatibility Policy
+
Comparison Method
    ↓
ComparisonResult
```

---

# 18. CompatibilityResult

```python
class CompatibilityResult(BaseModel):
    status: Literal[
        "compatible",
        "conditionally_compatible",
        "incompatible",
        "unknown",
    ]
    policy_version: str
    compared_fields: list[str]
    reason_codes: list[str]
    allowed_claim_levels: list[str]
```

兼容性判断由确定性规则完成，不交给 LLM 自由判断。

---

# 19. Provenance 与稳定引用

每个 Agent 可引用的事实必须拥有稳定 ID。

建议前缀：

```text
rpt_   Report
rs_    RecordSet
s_     Series
f_     Fact
cmp_   Comparison
qf_    QualityFlag
prov_  Provenance
run_   Tool Run
clm_   Claim
```

不要使用数组 index 作为稳定 ID。

可以通过：

```text
package_id + semantic identity
```

生成 UUIDv5 或 SHA-256 截断 ID。

---

# 20. Provenance

采用轻量 provenance 即可，不需要 RDF。

```python
class ProvenanceRecord(BaseModel):
    provenance_id: str
    activity_type: str
    implementation_name: str
    implementation_version: str
    parameter_digest: str
    input_refs: list[str]
    output_refs: list[str]
    output_digest: str
    executed_at: datetime
```

Tool Run 需要记录：

- tool_run_id
- tool_name
- tool_version
- input_digest
- source_snapshot_ids
- output_digest
- cache_hit

当前 `ToolRunRecord` 还分别记录 `analysis_method`、`analysis_method_version`、`kernel_version`、`data_scope`、输入输出引用和参数。`output_digest` 延续迁移前的确定性输出 payload，只摘要 Predicate、数值、样本数、记录引用、质量引用和限制，不包含 Tool、Method、Kernel、Prompt、Registry、运行 ID、执行时间或缓存状态。旧 `operator` 与 `operator_version` 字段只在兼容读取层分别映射为 `analysis_method` 与 `analysis_method_version`；旧记录没有独立 Kernel 版本时保持为空，既有 `output_digest` 不重算。

理想目标：

```text
same snapshot
+ same tool version
+ same canonical params
= same output digest
```

---

# 21. Missing、Exclusion、Quality 必须显式表示

不要使用 `NaN` 作为 Agent JSON 的语义表达。

推荐：

```json
{
  "value": null,
  "status": "missing",
  "missing_reason": "sensor_gap"
}
```

建议区分：

### Missing

- not_collected
- sensor_gap
- not_computable
- insufficient_sample
- excluded_source_records
- privacy_redacted
- not_applicable

### Inclusion

- included
- valid_not_included
- excluded
- invalid

### Quality

QualityFlag 至少包含：

```text
quality_id
code
severity
effect
affected_refs
prohibited_claim_types
details
```

其中 effect 可以是：

- informational
- limits_claim_strength
- exclude_affected_records
- invalidates_metric
- invalidates_report

---

# 22. UI 与 Agent 共用数据源，但不互相依赖

推荐：

```text
TestReport
    ↓
ReportDataPackageBuilder
    ↓
ReportRepository / ReportQueryService
        │
        ├── UI Presentation Adapter
        │      ↓
        │   ViewModel
        │      ↓
        │   Cards / Charts / Table / Footprint
        │
        └── Agent Tool Facade
               ↓
            Manifest / Tools
```

原则：

- Agent 不读取 QWidget
- Agent 不解析 UI 表格
- UI 不依赖 Prompt
- UI 与 Agent 从同一个语义数据源读取

该模块应放在 application / reporting / analysis 等业务层中，不应侵入 `hardware/` 和 `engine/`，除非确认现有底层存在真正能力缺失或 Bug。

---

# 23. Tool、确定性分析方法、Kernel、Agent 与 Validator 的职责分离

## Tool

负责：

- 数值读取
- deterministic filtering
- segmentation
- statistics
- side comparison
- temporal profile
- longitudinal comparison
- cohort comparison
- compatibility
- evidence refs

## 确定性分析方法

负责一种明确的分析计算语义并返回规范化计算结果，不生成自然语言 Claim。

## Analysis Kernel

负责共享确定性统计、筛选、稳定 ID 和摘要函数，不理解用户目标，也不选择 Tool 或分析方法。

## Agent Logic

负责：

- 理解用户目标
- 选择分析方向
- 选择 Tool
- 决定是否需要更多证据
- 综合多个结果
- 遇到矛盾时调整方向
- 最终撰写自然语言分析

## Validator

负责：

- Fact ID 是否存在
- Tool Run 是否属于当前 snapshot
- 单位是否一致
- protocol 是否允许该比较
- 样本量是否足够
- claim strength 是否越界
- 是否引用了 invalid / excluded 数据
- 是否出现 unsupported claim
- 是否超过 Tool budget

---

# 24. 关于 Pydantic Validator

需要区分两个概念。

## Pydantic 本身

可以使用：

- BaseModel
- field_validator
- model_validator

进行数据结构和字段约束。

## PydanticAI

负责：

- Agent
- structured output
- tool calling
- retry / output validation integration

因此“报告 Validator”不是简单等同于某个 PydanticAI 自带模块。

它可以同时包含：

1. Pydantic Schema Validation
2. 业务 Validator
3. Evidence Validator
4. Claim Validator

---

# 25. 智能报告单步序贯循环

生产实现过程：

```text
AgentObservation + 领域 Skill + AnalysisState
→ Agent 生成一个 NextAnalysisAction / LoadSkillResource / StopAnalysis
→ ActionValidator 校验权限、方法、指标、Predicate、重复语义和预算
→ AnalysisToolGateway 执行一个确定性动作
→ EvidenceProduced / ActionRejected / ToolExecutionFailed
→ AnalysisStateReducer 更新假设状态并保存 Checkpoint
→ 下一轮决策，或停止后综合 Claim
→ ClaimValidator → 原子发布 AnalysisPackage
```

每轮只允许一个确定性 Tool 动作。Tool 失败不会生成 Evidence，也不会把假设归约为不成立；样本不足和质量限制以 `inconclusive` Evidence 表达。运行在 Skill 加载、Action 接受、Evidence 归约和综合阶段保存 Checkpoint，满足身份与版本约束的 `running` 记录可以恢复。

---

# 26. 旧 AnalysisPlan 兼容边界

以下 AnalysisPlan 类型只保留用于旧 Schema 读取、固定 Fixture 和非生产兼容测试。新分析运行不再从该入口进入生产路径。权限仍不由 Agent 声明，而由系统根据 `tool_name` 查询 Tool Registry 后推导。

```python
class AnalysisQuestion(BaseModel):
    question_id: str
    description: str
    dimensions: list[str]
    metric_codes: list[str]
    reason: str
    stop_condition: str

class AnalysisNode(BaseModel):
    node_id: str
    tool_name: Literal[
        "analyze_current_session",
        "compare_longitudinal",
        "compare_cohort",
    ]
    analysis_method: str
    inputs: dict
    dependencies: tuple[str, ...]
    question_id: str
    purpose: str
```

第一版建议：

```text
MAX_ANALYSIS_QUESTIONS_PER_CYCLE = 3
MAX_AGENT_LEVEL_NODES_PER_CYCLE = 3
```

分析优先级：

1. 用户明确问题
2. 数据质量风险
3. AnalysisSketch 与 Compact Session Series 中值得验证的组合模式
4. 已获用户授权的纵向或团队数据域
5. Screening Cue（启用时仅作辅助线索）

---

# 27. AnalysisState

MVP 不需要 Hypothesis Graph。

```python
class Hypothesis(BaseModel):
    description: str
    status: Literal[
        "active",
        "supported",
        "rejected",
    ]
    evidence: list[str] = []


class AnalysisState(BaseModel):
    hypotheses: list[Hypothesis] = []
    findings: list[str] = []
    step_count: int = 0
    replan_count: int = 0
```

---

# 28. Replan ≠ Reset

如果后续证据推翻前面的判断：

错误方式：

```text
清空历史
↓
从头开始
```

正确方式：

```text
Hypothesis A
↓
REJECTED
↓
保留已有 Evidence
↓
Replan
↓
提出 Hypothesis B
```

> 被证据否定的是某个假设，不是整个分析历史。

---

# 29. MVP Loop

```python
observation = build_observation(...)
plan = agent.propose_plan(observation)
validated = plan_validator.validate(plan)
evidence = gateway.execute_plan(validated)
review = agent.review_evidence(evidence)
if replan_enabled and review.requires_replan:
    evidence += gateway.execute_plan(validate(review.replan))
draft = agent.synthesize(evidence)
result = claim_validator.validate(draft)
```

架构最多允许两个 investigation cycles；生产默认 B 为：

```text
include_analysis_sketch = True
include_compact_series = True
include_screening_cues = False
MAX_REPLANS = 0
```

后续根据 benchmark 调整。

---

# 30. Stop Condition

不依赖 LLM 单纯回答“我觉得分析够了”。

停止条件包括：

- 所有计划问题已有确定性结果
- 没有未处理的关键冲突或质量限制
- 每个主要 claim 都已有 evidence
- 继续调用 Tool 不会增加新的证据类型
- 达到 Tool budget

只有以下情况才继续：

- 证据冲突
- 需要精确定位
- Quality 可能影响结论
- compatibility 尚未确定
- 已启用 Screening Cue 且存在需要验证的高优先级线索

---

# 31. 防止 Agent 无限 Tool Call

第一版建议：

```text
Manifest: 1500–3000 tokens
MAX_ANALYSIS_QUESTIONS_PER_CYCLE: 3
MAX_AGENT_LEVEL_NODES_PER_CYCLE: 3
MAX_PLAN_COST: 9
MAX_REPLANS: 0（生产默认）/ 1（保留能力）
Compact rows per RecordSet: 最多 80
Observation token budget: 12k
```

这些值是初始工程预算，不是长期固定标准。

同时增加 Duplicate Request Hash：

```text
Tool 语义标识
+ Analysis Method 语义标识
+ canonical params
+ input snapshot refs
+ Method version
+ Kernel version
```

相同请求直接返回缓存结果。

Progressive Detail：

```text
Manifest
↓
Profile
↓
Window
↓
Exact Rows
```

---

# 32. 分析节点必须说明目的

每次 Tool request 应包含：

```text
question_id
purpose
analysis_method
inputs
dependencies
```

这样服务端可以拒绝无目的的数据扫描。

---

# 33. AnalysisPackage

Agent 最终不能只返回一段自由文本。

```python
class AnalysisClaim(BaseModel):
    claim_id: str
    claim_type: Literal[
        "descriptive",
        "temporal",
        "longitudinal",
        "cohort",
        "quality_limitation",
        "synthesis",
    ]
    text_template: str
    evidence_refs: list[str]
    tool_run_ids: list[str]
    strength: Literal[
        "observation",
        "suggestive",
        "supported",
        "strongly_supported",
    ]
    limitations: list[str]
```

---

# 34. Numeric Binding

为了降低 LLM 编造数字的风险，最好避免让 Agent 直接在自由文本中输入最终数值。

```python
class NumericBinding(BaseModel):
    placeholder: str
    fact_id: str
    formatting: str
```

Agent 生成：

```text
后半程触地时间波动高于前半程，
标准差由 {early_sd} 增至 {late_sd}。
```

确定性 Renderer 再通过 Fact ID 注入真实数值。

---

# 35. MVP 目标

第一版只需要证明三个核心能力：

```text
1. Agent 能提出合理的分析问题
2. Agent 能调用正确 Tool 验证这些问题
3. Agent 能在时间、侧别、多指标和质量维度之间形成受证据约束的综合
```

---

# 36. MVP 必须实现的部分

## Phase 1：Evidence Schema

实现：

- ReportMetadata
- MetricDefinition
- ScalarFact
- RecordSetDescriptor
- SeriesDescriptor
- QualityFlag
- ProvenanceRecord
- JumpPayload
- TreadmillGaitPayload
- TreadmillRunPayload
- ReportDataPackage

并实现：

```text
TestReport
↓
ReportDataPackageBuilder
↓
ReportRepository
```

成功标准：

- 三类测试均能转换
- 引用可以解析
- 顺序保留
- side 保留
- inclusion / exclusion 保留
- missing 保留
- quality 保留

## Phase 2：AgentObservation

实现：

- ManifestBuilder
- AnalysisSketch
- Compact Session Series
- Quality Summary
- 可选 Screening Cues

第一版 Screening：

- global
- quartile
- early / late
- side
- outlier influence
- included / valid difference
- missing / exclusion distribution

## Phase 3：Registry、三个 Tool 与五种确定性分析方法

```text
AnalysisToolRegistry
AnalysisMethodRegistry
AnalysisToolGateway
Analysis Kernel
```

## Phase 4：Analysis Loop

一个 PydanticAI Report Agent，只实现：

```text
Plan
Validate DAG
Execute
Evidence Review
Synthesize
```

不做 Graph。

## Phase 5：AnalysisPackage + Validator

实现：

- claim structure
- evidence refs
- tool run refs
- numeric binding
- deterministic rendering
- protocol validation
- unsupported claim rejection

最后显示到固定的报告智能分析区域。

---

# 37. MVP 暂时不做

以下内容全部延后：

- Hypothesis Graph
- Tree Search
- Multi-Agent
- Pydantic Graph
- 通用 Workflow Engine
- 多阶段 recursive Skill
- 任意次数 Replan
- 长期 Memory
- RAG 知识库
- Vector Database
- 动态 Tool 注册
- Arbitrary Python
- Arbitrary SQL
- 高级 Context Manager
- Agent 自动反思
- Agent 自动改 Prompt
- Agent 自动创建 Tool
- 多模型协作
- 完整 token scheduler
- 高级 change-point detection
- adaptive temporal windows
- 大规模 cohort strata
- cross-device normalization
- Arrow / Parquet 专门存储层
- raw 1000Hz 数据直接送 LLM

---

# 38. 未来演进模块

以下模块不属于当前 MVP，但应保留演进空间。

## 38.1 Advanced Temporal Analysis

未来可以加入：

- change-point detection
- adaptive windows
- fatigue trend detection
- rhythm regime detection
- local instability detection
- sequence motif detection

这些仍然必须由确定性算法完成，Agent 只调用 Tool 和解释结果。

## 38.2 Longitudinal Analysis

后续支持：

```text
当前测试 vs 历史兼容测试
```

baseline 可包括：

- previous compatible report
- first compatible report
- median of compatible history
- fixed historical window

输出可包括：

- absolute change
- relative change
- direction
- variability change
- compatibility status
- evidence refs

## 38.3 Cohort Analysis

后续加入：

```text
Athlete vs Cohort Snapshot
```

只允许权限控制后的 `stratum_id`，不允许 Agent 自由写 cohort SQL。

Tool 返回：

- sample count
- median
- quartiles
- percentile
- current athlete position
- inclusion rules
- cohort snapshot ID

## 38.4 Cross-Dimension Synthesis

未来允许 Agent 综合：

```text
temporal
+
left/right
+
longitudinal
+
cohort
+
quality
```

形成更高层结论，但每一个高层结论仍必须保持：

```text
Claim
↓
Evidence Refs
↓
Tool Runs
↓
Underlying Facts
```

## 38.5 Hypothesis Graph

只有在简单 AnalysisState 明显不够时再引入。

适用于：

- 多个竞争假设
- 支持与反驳证据并存
- 复杂因果或逻辑关系
- 多轮交叉验证

不属于 MVP。

## 38.6 Pydantic Graph / Workflow Engine

只有出现以下需求时再考虑：

- 很多固定阶段
- 分支数量明显增加
- 多种恢复路径
- 人工审批节点
- 长时间任务
- 多 Agent 协作

当前薄 Analysis Loop 更合适。

## 38.7 Knowledge / RAG

未来知识库适合存放：

- 指标含义
- 运动训练理论
- 常见运动表现解释
- 测试协议说明
- 报告语言知识
- 建议模板

不应该用来存：

- 正式数值
- 运动测试原始数据
- Series
- Comparison Result
- Fact

数值证据仍然进入结构化语义数据层。

## 38.8 Vector Database

未来如有 RAG 需求，可以用于：

- 文献
- 指标定义说明
- 训练知识
- 报告写作知识

不用于数值证据检索核心链路。

## 38.9 Multi-Agent

只有未来出现明确独立角色时再考虑，例如：

```text
Analysis Planner
Evidence Analyst
Report Writer
Safety / Validation Agent
```

当前阶段单 Agent + Tool + Validator 足够。

## 38.10 Multi-Model

未来可以按成本和能力拆分：

```text
Small Model:
- triage
- classification
- simple structured output

Large Model:
- complex synthesis
- conflict resolution
- report generation
```

必须通过 benchmark 证明收益后再增加复杂度。

---

# 39. Token / Latency 控制

核心策略不是简单压缩 Prompt，而是：

> 分层读取 + 有目的调用。

建议：

```text
第一层：Manifest
第二层：Metric / Temporal Profile
第三层：Small Record Window
第四层：Exact Row
```

Agent 永远不要默认读取：

- 完整报告 JSON
- 所有历史报告
- 所有逐步数据
- 1000Hz 原始采样

---

# 40. 数据表示与生产默认的最终结论

## A. Full JSON

用途：archive / debug / test fixture / offline replay。
不作为生产 Agent 常规输入。

## B. Summary Only

适合作为 Manifest 的一部分，但不能单独承担完整分析。

## C. Markdown / UI Text

适合展示与 debug，不作为正式证据核心。

## D. Hierarchical + On-Demand

作为保留的扩展能力，不是当前生产默认。需要真实纵向、团队数据域或明确证据冲突案例证明其收益后，再考虑启用 Replan。

最终组合：

```text
A → Archive / Replay
B → Manifest + AnalysisSketch + Compact Series（当前默认）
C → Presentation
D → 可选的分层 Evidence Access / Replan
```

2026-08-08 固定合成案例消融结果：

| 配置 | 输入与循环 | 有效运行 | Expected Predicate Recall |
|---|---|---:|---:|
| A | 基础摘要 | 34/36 | 0.424 |
| B | A + AnalysisSketch + Compact Series | 35/36 | 0.879 |
| C | B + Screening Cues | 35/36 | 0.818 |
| D | C + 最多一次 Replan | 34/36 | 0.879 |

所有有效运行的 Replan 次数均为 0。因此当前证据只支持 Sketch/Series 的价值，不支持 Cue 或 Replan 必然提升发现率。以上数据全部来自人工构造的已知模式，不代表真实运动员分析准确率。

---

# 41. 定量验证方案

## 41.1 数据转换验证

验证：

- Field Coverage
- Numeric Consistency
- Sequence Preservation
- Status Preservation
- Reference Resolution Rate
- Replay Consistency

其中：

```text
Reference Resolution Rate 目标：100%
Replay Consistency 目标：100%
```

## 41.2 Agent Benchmark

建立真实报告、人工构造报告和 planted-pattern 数据。

至少覆盖：

- late variability increase
- single outlier
- persistent asymmetry
- transient asymmetry
- same mean / different variance
- local change
- exclusion reverses trend
- protocol incompatibility
- low sample
- boundary cycle artifacts

指标：

- Hidden Pattern Recall
- Hidden Pattern Precision
- F1
- Numeric Accuracy
- Unsupported Claim Rate
- Evidence Resolution Rate
- Protocol Misuse Rate
- Tool Call Count
- Duplicate Call Rate
- Token Usage
- P50 latency
- P95 latency
- Replay Consistency

同一报告应重复多次运行，用于评估 Agent 稳定性。

---

# 42. Ablation Test

当前固定合成案例已比较：

```text
A: 基础摘要
B: A + AnalysisSketch + Compact Series
C: B + Screening Cues
D: C + 最多一次 Replan
```

生产采用 B。后续若实现纵向与团队 Tool，应另行设计数据访问范围、兼容性和跨 Tool DAG 的消融，不能把当前本次记录合成案例结果外推到历史或团队比较。

---

# 43. 当前代码模块结构

```text
agent/
├── common/
│   ├── model_provider.py
│   └── logging.py
│
├── config/
│   ├── agent.py
│   ├── models.py
│   ├── prompts/
│   └── service.py
│
└── report/
    ├── agent.py
    ├── models.py
    ├── tools.py
    ├── analysis_loop.py
    └── prompts/

reporting/
├── models.py
├── builders.py
├── observation.py
├── tools.py
├── kernel.py
├── validators.py
├── renderer.py
└── repository.py
```

`agent/report/tools.py` 实现 Gateway 与三个 Tool 门面；`reporting/tools.py` 保存 Tool Registry；`reporting/kernel.py` 保存 Method Registry 和共享 Kernel。这样业务编排依赖确定性 reporting 层，而 reporting 层不反向依赖 Agent。

---

# 44. 当前阶段的最终系统定义

> Iron_Jump 保持不可变 TestReport 作为事实源，通过 ReportDataPackageBuilder 构建结构化语义证据层，并以 AgentObservation 的 AnalysisSketch 与 Compact Session Series 作为生产输入。系统按测试类型加载唯一根领域 Skill；PydanticAI Report Agent 每轮只生成一个 AnalysisDecision，ActionValidator 校验 Tool 权限、方法归属、指标、Predicate、重复语义和预算后，由 AnalysisToolGateway 调用已启用的受控 Tool。确定性 State Reducer 根据 Evidence 更新假设状态，运行边界保存 Checkpoint。最终 AnalysisPackage 中的每个 Claim 必须绑定 Fact ID、精确 Evidence Ref、Predicate 和 Numeric Binding，并通过权限、数值、证据及禁用语义校验后原子发布。

---

# 45. 当前 MVP 一句话版本

```text
TestReport
    ↓
ReportDataPackage
    ↓
AgentObservation
    ├── Manifest / Authoritative Facts
    ├── AnalysisSketch
    └── Compact Session Series
    ↓
PydanticAI Report Agent
    ↓
单步 AnalysisDecision
    ↓
ActionValidator
    ↓
AnalysisToolGateway（单动作）
    ↓
Tool → Analysis Method → Analysis Kernel
    ↓
Evidence → AnalysisStateReducer → Checkpoint
    ↓
下一轮决策或 StopAnalysis
    ↓
AnalysisPackage
    ↓
Claim / Numeric / Permission Validator
    ↓
报告智能分析区域
```

生产默认：`include_analysis_sketch=True`、`include_compact_series=True`、`include_screening_cues=False`、`max_replans=0`。

当前最重要的不是复制 Claude Code、OpenCode 或复杂 Agent Framework，而是验证：

```text
Agent 是否能：
发现值得分析的问题
→ 调用正确 Tool
→ 根据证据更新判断
→ 被推翻后换方向
→ 最终只输出可追溯结论
```

这就是 Iron_Jump 智能报告模块第一阶段的核心。
