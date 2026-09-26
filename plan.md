# Iron_Jump 统一项目计划

> 最后更新：2026-08-25
>
> 本文件是项目唯一的计划类文档。已完成事项、当前实现状态和后续待办都集中在这里；具体参数定义、架构说明和实验诊断仍放在各自的参考文档中。

状态说明：

- **已实现**：代码和数据结构已经落地，不等于真实设备准确性已经验证。
- **自动化已验证**：相关自动化或合成数据检查通过。
- **真机验证中**：已有部分真实设备结果，但尚未覆盖完整验收矩阵。
- **已接入正式流程**：已经进入主 UI、报告或历史记录链路。

### 当前开发基线

- 当前分支为 `vae/iron_jump`。2026-08-12 已将此前工作区改动按 Report Agent、纵跳与 LED 健康检测、UI 和文档拆分为可追溯提交。
- `vision.__all__` 保持小型稳定公共 API；`PoseInferenceRecord`、`VisionSessionRecorder` 和 `NullVisionSessionRecorder` 属于内部按需访问类型，不进入稳定导出集合。
- 2026-08-12 使用 `/Users/vae/miniconda3/envs/Iron_Jump/bin/python` 和 `QT_QPA_PLATFORM=offscreen` 运行全量测试：`659 passed`、`12 subtests passed`。
- 2026-08-25 完成 Report Agent 工程生产化收尾；全量回归为 `791 passed`、`12 subtests passed`。
- 提交前审计未发现 `.env`、模型文件、真实受试者数据库或本地日志进入版本控制；本地对话记录和驱动压缩包已加入忽略规则。

## 1. 当前已完成能力

### 1.1 基础测试流程

- Jump Test 已形成完整流程：配置 → 采集 → 实时分析 → 报告。
- Setup → Execution → Report 多视图流程已接入主 UI。
- `GaitEngine` 通过模式 processor 运行，保留 Qt 生命周期和兼容入口。
- `ui/data_show.py` 作为旧版回退方案保留，不能删除。

### 1.2 Agent 参数配置

- 离线规则引擎和在线 LLM 配置助手均已实现。
- `LLMTestConfig`、Pydantic 校验、`to_test_config()` 转换已实现。
- ClarifyGPT 风格的多采样、一致性检查和澄清追问已实现。
- Agent 已嵌入 `SetupView`，不再只依赖独立测试窗口。
- Windows 启动阶段不再加载项目未使用的 `logfire-plugin`；依赖已改为 `pydantic-ai-slim[openai]`，避免完整 Logfire 成为不必要的传递依赖。
- Jump、Treadmill Gait、Treadmill Running 已分别使用独立 prompt：
  - `agent/config/prompts/jump.md`
  - `agent/config/prompts/treadmill_gait.md`
  - `agent/config/prompts/treadmill_running.md`

### 1.3 受试者和历史记录

- `SubjectStore` 已接入主 UI。
- 已支持受试者搜索/新建、疑似重复提示、加载上次参数、测试结束自动存档和历史记录回填。
- 已实现用户与团队的多对多成员关系；用户可以同时加入多个团队，也可以处于“未加入团队”状态。
- 正式用户开始测试前必须选择已加入团队或“不以团队身份测试”。每次测试只保存一条 session：始终归属用户，选择团队时同时带有测试时团队身份快照。
- 用户主档案与测试会话快照已经分离；测试页临时修改不会静默覆盖主档案。
- 跑步机报告的配置快照、报告摘要和报告详情已接入存储。

### 1.4 跑步机模式

- `Treadmill Gait Test` 和 `Treadmill Running Test` 已实现独立配置模型、processor、累积器和报告模型。
- `GaitEngine` 已按 `test_type` 分发到 `TreadmillProcessor`。
- 已实现跑带位移与触地参考点位置变化联合计算步长/步幅、起始脚、逐步结果、有效性和统计过滤。
- 默认跑步机速度为 `3.0 km/h`，默认方向为 `Opposite side`。
- 已实现同侧触地到同侧触地的步态周期、边界片段、周期阶段、左右独立统计和实时/报告显示；当前结论只覆盖合成事件和自动化验证，真实准确性仍待原始帧对照。
- 已接入参数面板、Agent prompt、报告页、历史记录和测试覆盖。
- 仍需注意：旧方案文档中的 Task 复选框已失真，不能作为当前进度依据。

### 1.5 足迹可视化

- 已实现统一的 `FootprintVisualFrame` 和固定 cadence 记录器。
- 执行页已使用双 96-LED 通道和足迹绘制。
- 步态/跑步机报告已支持 `visual_timeline` 回放。
- 旧设计中关于“引擎生成 canonical frame、UI 只负责渲染”的所有权边界已落地。
- 相关实现和测试包括：
  - `engine/footprint_visualization.py`
  - `ui/footprint_channel.py`
  - `tests/test_footprint_visualization.py`
  - `tests/test_footprint_channel.py`
  - `tests/test_execution_view_footprint.py`
  - `tests/test_report_view_footprint.py`

### 1.6 Tiny SE 相机

- OBSBOT C wrapper 已实现设备查询、格式查询、录制参数、镜像、AI 模式和自动对焦接口。
- `TinySeCameraControl` 已接入 `tinyse_camera.py` 和 UI。
- DirectShow 采集、录制和统计链路已实现并有测试。
- 停止录制后的 DirectShow 收尾和 MJPEG→AVI 转换已放入后台线程；保存期间 UI 显示 `Saving...`，关闭路径会等待收尾完成。
- Tiny SE 预览已嵌入执行页，采用 16:9 内容区、右上角齿轮参数入口以及与足迹/竖向剩余时间对齐的布局。
- 纵跳执行页复用同一相机区和控制布局，右侧只保留跳跃高度图，不再显示步频柱状图。
- 当前未完成的是：验证 UVC 实际输出是否达到 1920×1080@100fps，以及是否需要进一步的设备模式切换。

### 1.7 Report Agent 智能分析

- 已实现独立的 Report Agent 数据层、Observation、三个受控分析 Tool、五种本次记录确定性分析方法、Analysis Kernel、Plan/Claim Validator、Renderer、持久化和报告页入口。
- `AnalysisToolRegistry` 固定注册 `analyze_current_session`、`compare_longitudinal` 和 `compare_cohort`；当前只启用本次记录 Tool，纵向与团队 Tool 保持注册但禁用，且在查询历史或团队明细前拒绝请求。
- `PlanValidator` 一次校验完整 DAG，`AnalysisToolGateway` 按稳定拓扑序串行执行节点，不按 Tool 分组；上游失败时终止计划，不返回部分分析。
- Tool、确定性分析方法和 Analysis Kernel 使用独立版本，并分别写入 `ToolRunRecord`。Schema v2 只写入新字段；旧 `operator` 数据可兼容读取且不重算既有 `output_digest`。
- 正式数值和比较结果只由确定性代码生成；Agent 负责提出小型分析计划、选择证据并组织结论，不能访问通用 SQL，也不能修改 `TestReport`。
- 12 类固定合成案例的 A～D 消融已完成。生产默认采用 B：`AnalysisSketch + Compact Series`，关闭 Screening Cues 和 Replan；Cues 与 Replan 仅保留为实验开关。
- 初始消融中的 B 组为 `35/36` 有效运行，Expected Predicate Recall 为 `0.879`。三工具边界迁移后使用 Prompt v2.0 重新执行 B 组，结果为 `34/36` 有效运行（`94.44%`）、Expected Predicate Recall `0.879`、P95 `29.004 s`；两次失败均发生在结构化输出或 Claim 占位符校验阶段。这些结果只属于 12 类固定合成案例的工程验收，不代表真实运动员分析准确率、训练效果或医学有效性。

### 1.8 视觉数据闭环与 Windows 工具

- 已实现可回放 Vision Session：保存视频、相机时间元数据、Pose 序列、光栅 contact、人工标注和 Replay 结果。
- 已实现录制、标注、Replay 三个工具以及统一 QtPy 启动器 `vision_app.py`。
- 已提供 PyInstaller `onedir` 配置和 `build_vision_app.bat`；Windows EXE 构建、TinySE 和 USB 实机验收仍未完成。

## 2. 当前仍需推进的工作

### 2.1 工作区收敛与可追溯提交（P0）

跑步机长度语义已经在当前实现中收敛：步长结合跑带位移与相邻落点位置修正，步幅由同侧两次触地形成的完整周期计算；不再使用 `step_length × 2` 作为正式结果，缺少可靠空间参考时不生成伪步幅。

本轮工作区收敛已经完成：

- [x] 确定 `vision.__all__` 的稳定公共 API，并消除公共 API 边界测试失败。
- [x] 按“Report Agent / Vision Session 工具 / 纵跳与 LED 健康检测 / UI 与文档”拆分提交。
- [x] 每个功能组运行聚焦测试；全部拆分完成后再次运行全量测试。
- [x] 检查 `.env`、模型文件、真实受试者数据和本地日志均未进入版本控制。

完成结果：工作区改动均有明确归属，当前实现可以从提交历史恢复；全量自动化测试为 `659 passed`、`12 subtests passed`。

### 2.2 Report Agent 序贯假设验证迁移（P0）

**目标**：将当前生产使用的“一次性 `SmallAnalysisPlan` + DAG执行 + 默认不Replan”迁移为渐进式领域Skill指导的单步序贯假设验证循环。Agent每轮只决定下一项最值得验证的分析命题；三个受控Analysis Tool继续作为数据权限边界，五种现有确定性分析方法及其Kernel数值逻辑保持不变。

目标数据流：

```text
ReportDataPackage
  → AgentObservation（默认B：AnalysisSketch + Compact Series）
  → 系统按test_type加载唯一根领域Skill
  → Agent输出一个AnalysisDecision
      ├─ LoadSkillResource
      ├─ NextAnalysisAction
      └─ StopAnalysis
  → ActionValidator
  → AnalysisToolGateway.execute_action()
  → Tool → Analysis Method → 现有Analysis Kernel
  → Evidence / Typed Failure
  → 确定性State Reducer
  → Checkpoint
  → 下一轮或Claim综合
  → ClaimValidator → Renderer → 原子发布AnalysisPackage
```

**已确认的实施边界**：

- [x] 新分析运行完全切换为单步`NextAnalysisAction`循环；旧Plan/DAG只保留兼容读取和非生产测试入口，不再进入生产分析路径。
- [x] 根领域Skill由系统根据Jump、Treadmill Gait或Treadmill Running确定；Skill正文只提供分析方法论，细分`quality`、`side`、`temporal`、`cross-metric`和`exclusion`资料按需加载。
- [x] 权限、Tool预算、Evidence约束、禁止因果/诊断/处方和输出Schema继续由Always-on Prompt与确定性代码强制，不能依赖可选Skill。
- [x] 每次运行最多5次确定性Analysis Tool调用、3次Skill Reference加载和9个Agent决策步骤；重复语义请求拒绝，接近HTTP时限时必须停止调查并保留综合时间。
- [x] `AnalysisState`显式保存假设目标及`active`、`supported`、`not_supported`、`inconclusive`状态。样本不足或质量不允许比较时只能进入`inconclusive`，Tool执行失败不能作为假设不成立的证据。
- [x] 每个Predicate Evidence拥有稳定引用；新Claim绑定精确Predicate Evidence，而不是只按`increase`等Predicate名称匹配。指标、RecordSet、侧别或分段不一致时Validator必须拒绝。
- [x] 运行结果统一为`EvidenceProduced`、`ActionRejected`或`ToolExecutionFailed`；只有`EvidenceProduced`可以更新假设证据状态。
- [x] 在Skill加载、Action接受、Evidence生成和State更新后保存Checkpoint。相同session、scope、package digest与版本组合下遗留的`running`记录可在再次请求时恢复；终止运行不恢复。
- [x] 当前记录分析不得查询或向Agent暴露未授权的个人历史、团队候选数或明细。纵向与团队Tool继续注册但禁用。
- [x] 新分析写入Schema v3及后续兼容Schema；旧Schema v1/v2只读兼容，不原地重写。五种现有确定性分析结果的数值、Predicate语义、Evidence内容与`output_digest`保持不变。
- [x] 最终报告只能描述实际检验范围；没有对应负向Evidence时，不得把“没有继续发现高价值假设”写成“本次测试没有异常”。

**错误恢复默认策略**：

- 模型传输瞬时错误和SQLite临时锁定执行有限重试；LLM结构化输出允许一次修正。
- Agent生成的非法Action作为可修正拒绝返回，运行级最多允许两次Action修正。
- 样本不足和质量限制返回结构化`inconclusive Evidence`，不是系统错误。
- Kernel程序错误、快照损坏和版本不兼容属于硬错误，不交给Agent解释，不进行无意义的相同重试。
- Claim校验失败时保留全部已验证Evidence，只允许修正Claim一次；最终报告仍然原子发布，不显示部分结果。

**运动表现 RAG V1（Deterministic RAG）**：

RAG 已按独立 `knowledge` 子系统实现。它只在确定性 Claim 校验完成后执行，用文献 Evidence 生成一般行动建议；不得替代 Analysis Tool 证明本次记录中的数值、趋势、侧别差异或跨指标关系。生产启用由版本化 Release Gate 控制，真实 DeepSeek 输出的人工 Groundedness 审查未通过前保持关闭。

```text
Analysis Evidence
  → 证明本次记录中存在什么模式

Literature Evidence
  → 支撑如何理解该模式及其适用限制
```

- [x] 独立实现扁平 `KnowledgeSource / Document / DocumentVersion / Chunk / QuerySpec / Evidence / Citation / Recommendation / RAGAudit`，Retriever 与 Agent 解耦。
- [x] 稳定 `document_id` 与独立 `version_id`；`chunk_id` 使用 `document_id + chunker_version + logical_position + content_hash`。摄取改为事务式增量 upsert，未变化内容不重新 Embedding。
- [x] 确定性 QueryPlanner 在 ClaimValidator 后运行；先按 domain、metric_codes、population、support_type、recommendation_allowed 硬过滤，再执行 FTS5 + Dense Top-20 和 RRF(k=60)。LLM 不决定检索、不改写 Query、不访问网页。
- [x] PydanticAI + DeepSeek 推荐生成器配置 `retries=0`；只允许单次生成，Validator 失败的建议直接删除并审计，不 regenerate。
- [x] Citation 完全由代码从 Evidence 和来源目录生成；模型 Schema 不接受 URL/DOI/Citation 字段。URL 仅允许 HTTP(S)，UI 对标题与链接做 HTML 转义和协议白名单检查。
- [x] `analysis-schema/4.0` 增量增加 `literature_evidence / recommendations / references / references_markdown / rag_audit`，旧字段及 v1-v3 读取兼容。
- [x] RAG 异常只生成 `degraded` 审计和空建议，不影响确定性 Claim、Kernel digest 或报告发布。
- [ ] 完成真实 DeepSeek 输出的逐条人工 Groundedness 审查，将不受 Evidence 支持的建议数确认到 0 后，才把 `knowledge/v1_release_gate.json` 切换为启用。

**2026-08-14 RAG V1 实施进展**：

- [x] 核心全文由 6 篇扩展到 9 篇，新增健康青年步态效度、纵跳训练 Meta-analysis 和跑步力量训练 Meta-analysis；当前 508 个结构化 Chunk。
- [x] 冻结 30 问 Retriever baseline：Recall@5/10 1.000、Precision@5 0.533、MRR 0.900、nDCG@10 0.928。后续改动不得低于 `knowledge/retrieval_baseline.json`。
- [x] 五个当前启用的 domain/intent 场景 Evidence Coverage 为 100%，metadata leakage 与禁止人群 leakage 均为 0；未覆盖场景保持 disabled。
- [x] 增加 30 个跨三种报告模式的固定端到端 Fixture，覆盖正常、无 Evidence、非法引用、禁止剂量、错误人群、解析失败和重复执行。
- [x] 完成 30 个合成 Fixture 的真实 DeepSeek 导出：30/30 调用成功，Validator 放行 48 条、删除 35 条；67 条 Citation 全部可解析。抽检发现 Introduction 研究动机可能被模型误当成当前结论，故 Groundedness 门继续关闭。
- [x] `chunker/2.2` 已把 Introduction/Background 从 Recommendation Evidence 中排除；修复后本地 Evidence Coverage 仍为 100%，泄漏仍为 0。第二轮真实模型复测受账户用量上限阻塞，待恢复后重跑。
- [x] 完整回归通过：717 passed、12 subtests passed。
- [ ] 唯一未通过的 Release Gate 是真实模型输出的人工 Groundedness 复核；因此代码与 UI 已具备 Schema v4 能力，但 Worker 暂不启用生产 RAG Pipeline。

**2026-08-15 证据链与 RAG 可靠性修复**：

- [x] Kernel 语义 ID 显式绑定 `package_id + package_digest`、方法/Kernel 版本、规范化输入和依赖 Evidence；同快照重试稳定，不同请求或快照不碰撞，五种 Kernel 的既有 `output_digest` 保持不变。
- [x] 序贯与旧循环增加跨轮次 Action/Question/Node 唯一性约束；Checkpoint 升至 `sequential-checkpoint/1.1`，旧运行中 Checkpoint 不恢复。
- [x] Claim 强制 NumericBinding 来源、Evidence/ToolRun 精确绑定、重复 ID 拒绝和严格模板解析；Renderer 与 RAG 共用三位有效数字文本渲染，V1 `citation_refs` 固定为空。
- [x] RAG 使用已渲染 Claim；Pipeline 初始化失败独立降级，运行期故障仍走原有降级路径；Recommendation 增加 URL、DOI、Markdown 和伪引用令牌表面校验。
- [x] 增加规范化冻结审查工件 promotion、完整 Release fingerprint 和 fail-closed Gate；生产 Gate 仍保持关闭，不生成虚假审查工件。
- [x] 内置 Agent 的 decision/synthesis/repair Prompt 使用内容指纹，自定义 Agent 保持旧版本兼容；失败指标从异常状态或最新 Checkpoint 恢复已完成工作量。
- [x] Claim Repair 按错误码白名单和指标集合不变量约束；首次 Skill 加载错误纳入统一 `ReportAnalysisError` 边界。
- [x] UI 展示 RAG degraded/no-evidence 状态及 Recommendation limitations；本轮补强后的全量回归为 756 passed。
- [x] Numeric Repair 逐位置校验原数值/单位与绑定后的规范渲染结果，禁止借同一 Evidence 改写数值；旧 AnalysisLoop 失败保留 partial metrics，AnalysisPackage 暴露完整 Prompt digest。
- [x] Groundedness promotion 强制完整覆盖冻结 benchmark case，并绑定 catalog、manifest、Recommendation Prompt 与 case 内容摘要；Gate 主动关闭与启用后校验失败使用不同状态。

**实施顺序与完成标准**：

1. 冻结五种Kernel现有Fixture与`output_digest`；先修复Evidence四态语义和精确Predicate绑定。
2. 建立渐进式Skill Registry、单步Action Schema、ActionValidator与确定性State Reducer。
3. 将`AnalysisLoop`和Gateway生产路径切换为单步执行，保留旧DAG兼容入口。
4. 增加Typed Failure、Checkpoint和透明恢复，再接入Service、Prompt与Schema v3 Renderer。
5. 运行权限Spy、故障注入、旧Schema读取、HTTP/UI回归和联网多轮Benchmark。

完成门槛：未授权外部数据读取为0；Evidence/Fact引用准确率100%；不受支持Claim放行率0；`inconclusive`误判为`not_supported`为0；Checkpoint关键恢复案例全部通过；五种Kernel旧`output_digest`逐字节不变；默认B合成Benchmark有效运行率不低于90%、Expected Predicate Recall不低于0.80、P95低于120秒。

**2026-08-11 当前实施进展**：

- [x] `EvidenceItem`已增加`conclusive / inconclusive`状态；当前Plan兼容循环不再把样本不足产生的false Predicate写入`rejected_predicates`。
- [x] 每个新生成的Predicate Evidence已有稳定ID；新Claim使用精确ID加可读Predicate名称绑定，名称与精确引用不一致时Validator拒绝。
- [x] 新增Predicate ID与Evidence状态明确排除在旧结果语义摘要外；五种Kernel固定`output_digest`回归保持通过。
- [x] Renderer开始写`analysis-schema/3.0`；Schema v2旧Predicate Binding仍可只读解析，不修改历史JSON。
- [x] 本轮Report Agent相关聚焦回归为`99 passed`；其中Qt测试使用`QT_QPA_PLATFORM=offscreen`。
- [x] 已建立评测态`report-analysis-skill/0.2-eval`：根`SKILL.md`保持精简，Jump、Treadmill Gait、Treadmill Running与Evidence指南按引用文件拆分；Benchmark加载器根据`test_type`只披露一个领域文件并记录内容Digest，尚未接入生产Prompt。
- [x] 已为12类固定合成案例保存无Skill决策轨迹，并增加单步边界、首项方法可接受性、首轮不得做排除稳健性、跨指标输入均应有变化四类断言。单次运行中，无Skill断言通过率为43.75%，Skill v0.2为91.67%；两者首项方法可接受率均为100%，主要改善来自抑制无价值的附加节点。该结果仅用于Skill工程迭代，样本量不足，不能作为稳定性或真实运动分析准确率结论。
- [x] Skill v0.2仍有3/12案例输出两个节点，证明单步语义不能只靠提示词保证，必须由后续`NextAnalysisAction` Schema和Validator结构化约束。旧一次性循环下Skill组Expected Predicate Recall下降不解释为Skill发现能力下降，因为当前执行器没有在每个Evidence后继续下一轮。
- [x] 已增加`HypothesisTarget`以及`NextAnalysisAction / LoadSkillResource / StopAnalysis`判别联合Schema；Agent动作中不存在`data_scope`、权限或版本字段。
- [x] 已增加轻量`ActionValidator`：单动作适配为内部一问一节点计划，复用现有Tool启用状态、系统推导权限、Method归属、输入与成本校验；另外拒绝重复语义请求、耗尽的Tool/Skill预算、未知或重复Skill Reference，以及Hypothesis和Action指标不一致。
- [x] `AnalysisToolGateway.execute_action()`通过旧DAG执行器兼容执行一个已验证动作；固定Fixture证明单动作入口与旧计划入口生成完全相同的Evidence和`output_digest`。该入口尚未切换到生产`AnalysisLoop`。
- [x] `HypothesisTarget`已增加目标Predicate；五种Analysis Method在内部Registry声明各自可产生的Predicate集合，`ActionValidator`拒绝方法与目标Predicate不匹配。该目录暂不进入旧`AgentObservation`，避免改变当前生产Prompt输入。
- [x] 已建立独立`SequentialAnalysisState`与确定性`AnalysisStateReducer`。动作开始时登记`active`假设并消耗决策/Tool预算；精确匹配Action、Hypothesis、Method、Predicate和指标的Evidence到达后，只能归约为`supported`、`not_supported`或`inconclusive`。重复假设ID、相同语义请求、重复Evidence消费和错配Evidence均被拒绝。
- [x] 旧`AnalysisState`字段集合保持逐字不变；当前生产Agent发送给模型的State JSON没有因新状态实现而增加字段。Skill加载与Stop决策可以更新新状态但不消耗Tool调用。
- [x] 已增加`EvidenceProduced / ActionRejected / ToolExecutionFailed`判别联合结果。动作校验失败在Tool执行前返回`ActionRejected`；`inconclusive`仍属于`EvidenceProduced`；Tool异常不会生成Evidence。
- [x] 已建立`SequentialActionBoundary`：瞬时Tool错误最多自动重试一次，成功时在Outcome和State记录实际尝试次数；重试耗尽返回transient failure；其他程序错误返回hard failure且不重试。当前只有显式`TransientAnalysisToolError`进入瞬时路径，禁止把任意Kernel异常猜测为可重试错误。
- [x] `SequentialAnalysisState`记录Action修正次数、Tool重试次数和失败审计。最多允许两次Action修正；耗尽后停止。Tool失败对应的Hypothesis保持`active`且不写入`not_supported`，硬错误或重试耗尽设置明确停止原因。
- [x] 已增加只读生产级`ReportAnalysisSkillLoader`：初始阶段仅加载根`SKILL.md`和与`test_type`精确匹配的一个领域Reference；Evidence指南只能通过白名单按需加载，重复、跨领域或未知Reference均失败关闭；运行结果记录Skill版本与合并内容Digest。
- [x] 已增加独立`SequentialAnalysisLoop`，由Fake Agent验证`Observation + Skill + State + Evidence → NextAnalysisAction / LoadSkillResource / Stop`的逐轮语义。每轮只验证并执行一个动作，继续复用现有Gateway、五种Kernel方法和Evidence结构；旧`AnalysisLoop`、Service、HTTP和UI尚未切换。
- [x] 新循环已覆盖多轮假设验证、Skill渐进披露、无结论证据、最多两次Action修正、瞬时Tool失败自动重试一次、硬失败原子终止和五次Tool调用预算。硬失败和修正耗尽均不调用综合阶段，不返回部分草稿。
- [x] 已增加`SequentialLoopCheckpoint`，保存运行阶段、State、累计Evidence、Skill与四层运行版本；`action_accepted`阶段额外保存系统已验证的`pending_action`。恢复该阶段时直接完成确定性Tool调用，不重新请求Agent规划；恢复`evidence_recorded`阶段时不会重复已完成Tool。
- [x] Checkpoint按照Skill加载、Action接受、Evidence归约、Action拒绝状态更新和进入综合阶段等完整边界写入。Session、Scope、Package Digest、Skill内容或运行版本不匹配时拒绝恢复。
- [x] `ReportRepository`已增加追加式Checkpoint表、写入身份校验和可恢复运行查询。只有仍为`running`且模型、Prompt、Scope、快照及全部版本完全匹配的运行可被发现；`validated / rejected / failed`运行保留审计记录但不能恢复。该查询尚未接入生产Service。
- [x] Report Analysis Skill输出契约已从旧一问一节点Plan改为单步`NextAnalysisAction / LoadSkillResource / StopAnalysis`，并通过Skill Creator校验脚本。联网测试先后发现Agent可能在Stop前不主动加载综合所需Evidence指南，以及可能重复请求系统已经加载的领域Reference：前者由系统在综合阶段按需加载；后者进入与非法Action共享的两次结构化修正预算，不执行Tool也不越权。生产Skill版本相应提升至`report-analysis-skill/0.5`。
- [x] 真实`ReportAgent`已增加`decide()`单步结构化输出，并使用独立`report-agent-sequential-system/3.0` Always-on Prompt。旧Plan Prompt v2继续独立保留，避免兼容入口被新指令污染；Agent初始化仍不发起网络请求。
- [x] 序贯综合调用会重新显式注入当前完整Skill Context，避免无状态模型在调查阶段加载Evidence指南后，综合阶段实际看不到该指南。没有新接口的Fake/兼容Agent继续使用原三参数`synthesize()`。
- [x] `ReportAnalysisService`对实现`decide()`的Agent启用新序贯循环、Checkpoint Sink和可恢复运行查询；旧Agent对象继续走旧Plan循环作为兼容入口。HTTP `/report/analyze`、`/report/latest`、Worker路由和UI协议未改变。
- [x] Service已验证跨请求恢复：数据库预留`running + action_accepted`后，新请求复用同一Run ID，先执行待处理确定性动作，再继续决策与原子发布；不会创建第二条分析运行。
- [x] Renderer保持既有AnalysisPackage字段兼容，并增量暴露可选完整`prompt_content_digest`；序贯Tool调用数兼容映射到现有`cycle_count`，`replan_count`为零。运行审计使用独立Sequential Prompt版本。
- [x] 已完成一次真实模型首决策烟雾测试：对固定Jump合成记录返回`NextAnalysisAction`，选择`analyze_current_session + verify_temporal_change + contact_time_s + increase`，结构化联合Schema解析成功。
- [x] 已完成一次真实模型完整序贯烟雾测试：3次Agent决策、2次确定性Tool调用，假设状态分别为`supported`和`not_supported`，以`no_high_value_hypothesis`正常停止，生成1条Draft Claim并通过ClaimValidator。该单案例只证明运行闭环，不代表Benchmark效果或领域准确率。
- [x] Claim阶段Checkpoint已扩展到`draft_generated`与`claim_repair_pending`。中断恢复复用原State、Evidence和Draft，不重复Tool或首次综合；Validator引导修正仍最多一次，修正后的Draft再次Checkpoint后再验证。跨请求故障注入证明同一Run只综合一次、只修正一次并最终原子发布。
- [x] 序贯Benchmark已迁移到v2：记录每轮判别联合决策及Draft/Repair轨迹，不再用旧`SmallAnalysisPlan`评分新循环。旧案例中的`comparison_supported`经Kernel能力核查后不再当作隐藏模式：均值相同但离散度变化当前无对应Method Predicate；排除前后反转只能得到`remains_after_exclusion=false`；质量标记案例改为期望实际的`increase`。这是可验证性修正，不是根据模型输出删减失败样本。
- [x] B配置正式联网Benchmark完成12类固定合成案例×3次，结果保存于`benchmark_results/report_agent_sequential_b_12x3_20260811.json`：有效运行率`100% (36/36)`，Expected Predicate Recall `92.59% (25/27)`，决策断言通过率`96.53%`，P50 `17.875 s`，P95 `47.931 s`，满足既定三项发布门槛。`co_change`和排除稳健性各有一次未召回；存在一次`239.524 s`极端延迟，虽不改变P95结论，但需要独立的生产超时控制。
- [x] 本阶段Report Agent、Service、Worker与UI聚焦回归为`147 passed`；Qt用例通过`QT_QPA_PLATFORM=offscreen`执行。
- [ ] 工程生产化已经完成；仍需完成去标识化真实记录和专家标注实验。合成Benchmark不能解释为真实运动分析准确率。

**2026-08-19 Agent 模块当前待办（本节为后续实施入口）**：

### Config Agent / 参数配置

- [x] 节拍器暂不属于当前硬件和 Agent 能力范围。Config Agent 不生成
  `metronome_enabled / metronome_bpm`，默认保持关闭；后续若硬件接入，另立
  参数、UI、运行时和验收任务。
- [x] 离线 RuleEngine 已覆盖三种已支持测试：`Jump Test`、`Treadmill
  Gait Test`、`Treadmill Running Test`。按测试类型返回对应的
  `TestConfig / TreadmillGaitConfig / TreadmillRunningConfig`，使用参数 Schema
  的测试类型默认值；Jump 的年龄/训练水平规则继续保留，跑步机使用明确的
  3.0/6.0 km/h 模式默认值，三种输出统一通过 `validate_runtime_config()`；未知
  测试类型不再静默降级为 Jump。规则引擎和服务层回归已覆盖三种模式及档案规则。
- [x] `External impulse` 已从 Agent Jump 结构化输出、活动参数 Schema 和 UI
  生成路径删除，默认停止改为 `Status change`；历史配置若仍携带该值会在统一
  运行时校验中明确拒绝。`config/Opto_parameters.json` 仅作为原始厂商资料保留，
  不属于 Iron Jump 的活动能力声明。
- [x] 三次并行采样不再随机选择。三次都必须生成配置，且用户意图字段一致才
  采用第一份确定性结果；停止方式、次数/时长、位置/起跳脚、跑步机速度和方向
  等意图字段不一致时追问。底层滤波、足长过滤和自动过滤等技术字段不参与追问，
  模型输出会被基于运动档案的 RuleEngine 策略覆盖。已增加“滤波值三份不同仍
  采用规则值”和“用户意图不同必须追问”的回归测试。
- [ ] 完成 Config Agent 指令矩阵（建议首轮 30 条，三种模式各 10 条）：
  明确需求、缺停止条件、缺速度/方向、模糊自然语言、互相冲突、非法范围、
  时间格式、已移除能力请求、跑步机步态/跑步模式混淆和当前配置查询。每条冻结
  期望测试类型、关键字段、允许追问与禁止输出；统计配置成功率、关键字段
  完全正确率、追问必要性/有效率、非法配置拦截率和 P50/P95 延迟。三次采样
  的每个候选配置与最终决策均保存，保证结果可复核。
- [x] Config Agent 和规则引擎已有模式级默认工厂，不再以 Jump 默认配置作为
  跑步机配置基底；未知测试类型会明确失败。

### Report Agent / 报告生成

- [x] 完成旧 DAG 与序贯路径的同条件延迟对照。2026-08-25 使用12类固定合成
  案例×3次、B配置、逐案例成对交错且交替先后顺序运行：旧DAG有效率
  `31/36 (86.11%)`、Expected Predicate Recall `0.852`、P50 `19.526 s`、
  P95 `29.083 s`；序贯路径有效率`36/36`、Recall `0.889`、P50 `15.642 s`、
  P95 `25.750 s`。两组均无90秒超限。结果保存于
  `benchmark_results/report_agent_production_paired_compare_12x3_20260825.json`。
- [x] 增加生产级服务端总截止时间：以当前 P95 和极端值实测为依据，默认
  `REPORT_ANALYSIS_DEADLINE_SECONDS = 90`。调查阶段最多使用约70秒，至少保留
  20秒给综合、一次 Claim Repair 和原子持久化；达到 deadline 后停止新的 Agent
  决策，保存最新 Checkpoint/partial metrics，并返回结构化 `analysis_timeout`。
  Worker/客户端 timeout 应略高于服务端 deadline（建议105秒）以保留响应传输和
  清理时间。实现必须同时使用单次模型请求 timeout 和整个运行的 wall-clock
  cancellation：PydanticAI 官方说明 `ModelSettings.timeout` 只限制单次模型请求，
  整体 `agent.run()` 需要 `asyncio.timeout()`/取消令牌；LangGraph 的公开设计也将
  run timeout、node timeout 与 step limit 分开。不能只在同步 Service 外层事后
  检查时间。同步 HTTP 网关常见约29–30秒上限，因此若未来经 API Gateway 部署，
  90秒任务必须改为流式或异步作业；当前本地 Worker 不受该网关上限。参考：
  https://github.com/pydantic/pydantic-ai/blob/main/docs/timeouts.md 、
  https://docs.langchain.com/oss/python/langgraph/fault-tolerance 、
  https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html 。
  后续若真实 Benchmark 显示 P95 漂移，必须重新冻结该值并更新验收。
- [x] 完成 Repository 权限 Spy 验收：使用记录所有读取调用的 SubjectStore/
  Repository spy，验证当前记录分析只读取目标 session 的 snapshot、当前 scope
  和必要能力信息；不得读取其他 session 明细、subject history、team candidates
  或执行任意 SQL。组合注入模型异常、Tool 异常、Checkpoint 恢复和 RAG 降级，
  仍须保持未授权读取数为0，并保存调用审计。已完成最小 Service Spy：当前
  session 分析不再调用会统计历史/团队候选的 `get_scope_availability()`；成功、
  模型异常、Tool瞬时/硬故障、三类Checkpoint恢复、RAG降级和两类deadline场景
  共10项验收未授权读取均为0。冻结审计位于
  `benchmark_results/report_agent_access_audit_20260824.json`。

**2026-08-25 工程生产化完成结果**：服务端默认90秒、调查阶段保留20秒综合
预算，模型调用同时使用`ModelSettings.timeout`和`asyncio.timeout()`；HTTP超时
返回504与结构化`analysis_timeout`，客户端默认105秒并区分
`analysis_client_timeout`。超时Run保存Checkpoint和partial metrics、按`failed`
原子结束且不可恢复，重试创建新Run；UI不显示部分Draft。独立序贯发布门为
`34/36 (94.44%)`、Recall `0.815`、P50 `16.788 s`、P95 `22.848 s`、P99
`26.073 s`，0个90秒超限。该轮结果保存于
`benchmark_results/report_agent_production_sequential_12x3_20260824.json`；早期按组
顺序运行且受连接状态污染的对照工件已显式标记`comparison_valid=false`，不用于
结论。
- [ ] 完成去标识化真实运动数据验证。每条记录至少需要：不可逆受试者 ID、
  测试类型、完整 config snapshot、原始/处理后 Report snapshot、package digest、
  质量与缺失标记、测试时间段和设备/版本信息。Jump、Treadmill Gait、Treadmill
  Running 各建立覆盖正常、质量不足、左右差异、时序变化、跨指标变化和无结论
  的样本；建议每种模式先收集不少于30条作为工程试验集，正式稳定性估计再扩展
  到50–100条。每条由两名独立运动/生物力学专家按 Claim、数值、Evidence 来源、
  支持状态和限制条件标注，分歧经第三人裁决，并冻结标注协议和版本。
- [ ] 真实数据验收指标至少包括：Claim 发现率、数值绝对/相对误差、Evidence/
  Fact 引用准确率、unsupported Claim 放行率、`inconclusive` 误判率、专家间
  一致性、重复运行稳定性、P50/P95/P99 延迟和失败恢复后的指标完整性。合成
  Benchmark 只作为工程门，不替代该验收。

### RAG 生产启用门

- [ ] RAG 确定性表面校验、Release fingerprint 和人工 Groundedness 审查全部
  通过后，才允许开启 `knowledge/v1_release_gate.json`。必须先完成冻结 30 个
  benchmark case 的逐条人工审查，所有 review 行为 `supported`、unsupported 数
  为0，catalog/manifest/Prompt/case digest 与当前运行一致，再执行 promotion 和
  fingerprint 校验。
- [ ] 开启前执行一次 canary：仅对内部或显式启用的报告生成 RAG 建议，确认
  `degraded/no_evidence` UI、审计、引用协议和确定性 Claim 不受影响；canary
  回归通过后再将 gate `enabled=true`。任何内容漂移、审查缺失或运行期故障都必须
  自动回退为 degraded，不得静默生成无来源建议。

### 2.3 论文主实验（P0）

- 设计步态参数准确性验证方案：参考标准、对照数据、评价指标。
- Config Agent：完成 10–30 条典型指令，覆盖明确、缺参数、模糊、冲突和格式场景；评价配置生成成功率、关键参数正确率和澄清有效率。
- Report Agent：在固定合成模式之外，设计去标识化真实记录与人工专家独立标注方案；评价发现率、数值与证据正确性、无支持声明率、稳定性和延迟。
- 论文中明确两个 Agent 的不同角色：Config Agent 处理开放自然语言配置；Report Agent 主导受限分析计划和证据综合；确定性算法、Kernel 与 Validator 保证正式数值和结论边界。
- 合成 Benchmark 只能作为架构与工程可行性实验，不能替代真实运动员结果分析实验。
- `素材.md` 暂不修改；后续按 `writing.md` 的规则，在第四章记录系统设计、第五章记录关键实现与方案取舍、第六章记录可复现实验数据，并明确区分“已实现”“自动化验证”和“真实准确性验证”。

### 2.4 纵跳算法验证

- 按当前“统计边界时间与确认时间分离”的准则继续离线验证。
- 三组人工标注数据的当前对比为：生产算法 contact MAE `94.4 ms`、air MAE `99.2 ms`；`associated` 为 `57.1 ms` / `42.1 ms`；`touch_associated` 为 `58.1 ms` / `43.2 ms`。
- `associated` 在第二组数据出现过 1 次事件时间倒退，因此当前只作为离线候选，不修改生产 `SingleFootDetector`。
- 至少覆盖多个独立 session 后，再决定是否修改 `SingleFootDetector` 的时间戳语义。
- 当前诊断依据见 `docs/步态参数相关/纵跳计时误差诊断与方案验证.md`，该文档保留。

### 2.5 硬件和设备扩展

- `External impulse` 已确定不会由当前硬件支持，并已从产品配置能力中永久移除；
  不再规划 `E_STATUS_REPORT` 转发或自动停止链路。
- 多米段级联：参数化 LED 数量、空间坐标、距离映射和聚类逻辑，替换单段 96 LED 假设。

### 2.6 相机路线

- 在 Windows 设备上完成 UVC 格式列表和实际帧率验证。
- 根据验证结果决定是否继续 SDK 模式切换，或退回较低帧率方案。
- 相机已经嵌入主分析界面；下一步验证长时间预览、录制、后台保存和关闭程序时的 Windows 稳定性。

#### 2.6.1 左右脚视觉参考标签（P1）

**目标**：当前阶段只在 `Treadmill Gait Test` 和 `Treadmill Running Test` 中，使用视觉结果为单次光栅触地事件提供 `left`、`right` 或 `unknown` 参考标签。光栅继续负责精确的触地/离地时刻；视觉标签属于可拒识的参考结果，不作为绝对真值。双脚同时落地和纵跳分类不再属于本模块的正式目标。地面直线往返跑只保留后续设计，不进入本阶段开发。

**当前状态**：

- 核心层、MediaPipe 适配、独立 Worker、TinySE 时间映射、事件调度、诊断界面和真实光栅验证器均已实现；视觉同步主体对应 `d3dc711`，当前分支之后仍有其他修复提交。
- 当前仍是独立验证模块，没有把视觉结果写回 `GaitEngine`、报告、历史记录或主 UI。
- 受控单脚踩入已经得到人工已知动作结果：左脚 `10/10`、右脚 `10/10`。这只证明简单、清晰、单脚动作下可以工作。
- TinySE 最近有效会话的同步状态为 `ready`，不确定度通常约 `1–10 ms`；当前主要瓶颈已经从时钟同步转为关键点质量、事件特征和真实数据覆盖。
- 随机顺序、连续同脚、设备外移动、交叉腿、轻微踉跄、遮挡、多受试者和不同机位尚未形成独立真值验收，因此不能宣称算法已经稳定。
- 录制、人工标注、离线 Replay 和统一 Windows 桌面工具已经实现；当前优先级是建立真实数据闭环，不继续凭单次演示手工调权重。

**已确认方案**：

- 模型：MediaPipe Tasks `Pose Landmarker Full`（BlazePose GHUM Full）。
- 运行方式：CPU + `VIDEO` 模式，单人，关闭分割掩码。
- 关键点：左右髋、膝、踝、脚跟和 foot index；foot index 只作为足部方向参考，不解释为精确鞋底触地点。
- 执行边界：视觉推理放入独立 Worker，不在相机 UI 回调或 1000Hz 光栅处理链中同步执行。
- 可选开关：用户不启用视觉、模型初始化失败或推理超时时，完全保留现有光栅逻辑。
- 本轮范围：只为 TinySE 完成精确采样时间同步，并继续在独立验证器中验证；不接入主程序融合，也不修改 `GaitEngine`、光栅事件时间或报告语义。

**TinySE 采样时间同步**：

- “相机和光栅都调用 `time.perf_counter()`”只说明目标时钟域相同，不代表 DirectShow 帧的实际采样时间已经对齐。TinySE 必须先把 DirectShow `sample_time_s` 映射到主机 `time.perf_counter()` 时钟域，再把帧送入视觉窗口。
- TinySE 每个分析帧保留帧序号、DirectShow 采样时间、Python ctypes 回调入口（复制 MJPEG 前）时间和旧版解码后时间；新增带时间元数据的兼容信号，原预览、录制和 `analysis_frame_ready` 接口保持不变。
- 映射器每次会话重新暖机。至少收集 30 帧且覆盖不少于 0.8 秒后，以 `callback_time_s - sample_time_s` 的第 5 百分位冻结本会话偏移；对齐后的时间戳必须严格递增，不允许运行中重算偏移造成回跳。
- 同步状态为 `warming_up`、`ready` 或 `degraded`。非有限时间、采样时间不递增、P95-P5 不确定度超过 40 ms，或 10 秒窗口漂移超过 40 ms 时进入 `degraded`，并在本会话内保持拒识。
- TinySE 验证器必须等到同步 `ready` 才启动光栅会话；运行中退化时，相关视觉事件输出 `unknown/clock_sync_degraded`。不得把旧版解码后时间作为临时补偿混入已对齐时间线。
- Logitech 精确同步不在第一版范围内；它仍可走旧兼容通道，但其结果不得用于证明本方案的时间同步质量。

**毫秒窗口和全局顺序**：

- 不固定推理帧数。事件 `e` 在单调时钟 `t_e` 上的视觉窗口为 `[t_e - pre_event_ms, t_e + post_event_ms]`。
- `pre_event_ms`、`post_event_ms` 和 `inference_interval_ms` 是独立可配置项；独立验证器默认使用 `250 ms + 200 ms` 窗口、`60 ms` 推理间隔和 `500 ms` 决策超时，优先验证触地前后各至少 2 个成功姿态的覆盖率。
- 相机帧和光栅事件必须进入同一单调时钟域，而且相机采样时间必须先完成上述映射。环形缓冲保存未镜像原始帧及对齐时间戳，UI 镜像只影响显示。
- 事件调度器按 `t_e` 排序，并等待窗口右边界进入相机缓冲后再提交推理。
- 全局只维护一条严格递增的推理时间线和一个按时间戳索引的姿态结果缓存。`VIDEO` 模式不得再次提交小于或等于已推理游标的旧时间戳。
- 多个事件窗口重叠时，重叠帧只推理一次：已有时段复用全局姿态缓存，只对游标之后的新帧按时间戳递增推理，最后再按各事件的毫秒窗口分发结果。
- 推理游标、事件队列和姿态缓存都是 session 级状态；测试开始/结束时显式初始化和释放，不复用上一个 session 的姿态结果。
- 如果事件过晚到达、所需旧姿态已过期，或 CPU 积压导致无法在延迟目标内完成，该事件输出 `unknown` 并回退光栅结果，不得倒序重放帧。

**数据流**：

```text
TinySE 采集（原始帧 + DirectShow sample time + 回调时间）
  → 会话级自动时间映射（warming_up / ready / degraded）
  → 原始帧 + 对齐后的 perf_counter 时间戳
  → 按时间保留的环形帧缓冲
光栅触地事件（event_id + 绝对单调时间）
  → 毫秒事件窗口队列
  → 全局递增 VIDEO 推理 + 姿态结果缓存
  → 按 event_id 取回窗口内关键点序列
  → 质量门 + 时序一致性 + 事件级置信度
  → left / right / unknown
  → 独立参考标签输出
  → 后续薄适配器可做高置信融合；否则保留光栅判断
```

**模式约束**：

- 跑步机/步态模式的左右交替只作为异常提示和拒识依据，不得反向覆盖高质量视觉结果。
- Jump 模式继续使用原有光栅逻辑；视觉模块不承担双脚落地识别。
- 任一关键链路缺失、置信度不足、窗口结果矛盾、左右身份有歧义或视觉延迟超标时输出 `unknown`。

**当前开发阶段：Vision-assisted Foot Phase Resynchronization**：

当前生产边界不再是“视觉独立决定并逐步覆盖左右脚”，而是“设备为主、视觉校验整体相位”。光栅继续提供唯一权威 `t_contact`，现有 A/B 交替状态机继续生成不可修改的 `raw_device_label`；视觉在每个触地窗口输出 `left/right/unknown` 与两侧 evidence，`FootPhaseManager` 仅在观察到覆盖两个相反设备标签的完整交叉反证后切换 `phase_offset`：

```text
Device: L → R
Vision: R → L
→ phase_offset toggle
```

`LL/RR`、同设备标签的两次 mismatch、单次视觉错误、设备间隔异常、Pose 低质量或只有 `unknown` 均不得自动翻转。第一次 mismatch 后允许跨最多 2 个连续 `unknown`，确认必须在从第一次 mismatch 起的 4 个 contact 内完成；一次高质量 agreement 立即取消 SUSPECT。确认后只回填短 pending 窗口，不修改更早的 Session 历史。所有事件分别保存 `raw_device_label`、`effective_device_label`、`final_label`、`phase_offset`、`phase_epoch` 与 flip 起止事件。

首版只接入独立验证器与 Replay，不修改 `hardware/`、`GaitEngine`、报告或主程序。验证器提供会话级跑带后端/前端两点标定和“校正左右脚相位”手动按钮；`landing_v1` 完整保留。Replay 支持 `landing-v1`、`visual-evidence-v2`、`phase-resync-v1` 和 phase-slip injection。上线安全门仍是 frozen test 中 false automatic phase flip 为 0，至少 100 次可恢复注入的恢复率不低于 95%，且恢复所需 contact 数 P95 不超过 4。

实现状态：

- [x] 建立 `landing_v2` 图像平面非正交坐标、`peak_phase / velocity_turn / post_backward` 证据和保守拒识门。
- [x] 实现严格 `NORMAL / SUSPECT` 状态机、相反设备标签双证据确认、TTL、短窗口回填、manual flip 和 phase epoch。
- [x] 扩展 Session 原始/有效/最终标签、证据、异常、phase provenance 与 Replay diagnostics。
- [x] 接入独立验证器的两点标定、手动phase校正和退出安全flush。
- [x] 增加 V1/V2/phase Replay 与不修改原Session的 phase-slip injection。
- [ ] 在 Windows TinySE 真机完成 tuning dataset、frozen test 与运行Gate验收；通过前自动phase flip不得进入主程序。

**历史研究草案：逐事件 `landing_v2` 直接分类（已被上述phase重同步方案取代，不作为首版生产路径）**：

当前 `landing_v1` 主要比较事件前后 `foot_y - hip_y` 的变化，并要求触地后足部下降和稳定。该特征没有利用跑步机前后方向，而且触地后的 200 ms 内，膝关节缓冲和跑带后移可能使腿部伸展量保持不变或减小。因此下一版保持模型、时间同步和事件调度不变，只替换事件级特征与左右身份质量判断。

参考 [Automated Gait Analysis Based on a Marker-Free Pose Estimation Model](https://pmc.ncbi.nlm.nih.gov/articles/PMC10384445/) 及其开源复现 [gaitanalyzer](https://github.com/abishekmuthian/gaitanalyzer) 的“髋部—foot index 相对轨迹与步态相位”思路，但不直接复制其离线全视频峰值搜索、XYZ 欧氏距离、高阶滤波或 AGPL-3.0 源码。Iron_Jump 已由光栅提供 `t_contact`，只需判断事件附近哪一侧更符合触地相位。

本阶段目标数据流：

```text
跑步机方向会话标定
  → 将关键点投影到“跑步机纵向 + 人体垂直”二维坐标
光栅触地事件 t_contact
  → 读取 [t_contact - 250 ms, t_contact + 200 ms] Pose
  → 左右身份连续性与观测质量检查
  → 左右脚事件局部轨迹特征
  → left_evidence / right_evidence
  → left / right / unknown
```

跑步机方向标定规则：

- 每次相机位置变化后，用户在预览中按固定顺序标记跑带后方和前方，得到二维跑步机纵向；首版不要求从人体动作中全自动猜测相机方向。
- 受试者自然站立 1～2 秒，以骨盆中点到双踝中点的稳健中位方向估计人体垂直方向。计算方向时先把归一化坐标还原为像素坐标，避免 16:9 画面中 X/Y 比例不同造成角度失真。
- 跑步机纵向与人体垂直方向构成二维非正交基，通过解线性方程得到纵向和垂直分量；不得直接假定画面 X 轴等于跑步机方向。
- 质量门检查的是两个方向在**二维画面中的投影**是否可分。近侧视或斜侧视可接受；接近跑步机正前方/正后方、纵向投影过短、两个投影接近平行或双腿长期重叠时，视觉保持禁用并回退光栅。
- 标定结果只在当前相机会话内使用；相机移动、重新打开或流重启后必须失效并重新标定。

`landing_v2` 每侧特征：

- 以 ankle 为核心观察点，foot index 和 heel 作为足部方向、贴近跑带及结果增强；任一增强点短暂低质量不应单独废掉整条腿。
- 使用同侧脚相对骨盆/髋部的有方向纵向轨迹，不使用无方向的 XYZ 欧氏距离，也不再把触地后伸展量继续增大作为必要条件。
- 触地前提取稳健的前摆速度和纵向位移；`t_contact` 附近计算前向局部极值接近程度；触地后用于检查相对速度下降、方向转变和进入支撑轨迹。
- 垂直方向只作为接近跑带和运动一致性的辅助证据；膝角及其变化作为低权重辅助特征，不作为单独决定条件。
- 当前窗口的成功 Pose 数较少，不直接采用论文或 `gaitanalyzer` 的 10 阶双向 Butterworth。首版优先使用中位数去异常和基于真实时间戳的低阶稳健斜率/局部拟合。

判定与拒识规则：

- 分开计算 `observation_quality`、`identity_quality` 和 `contact_evidence`，MediaPipe 的 visibility/presence 不能解释为“该腿解剖身份正确的概率”。
- 一侧存在高质量、高身份可靠性的强正触地证据时，即使另一侧因遮挡缺少触地证据，也允许输出该侧。
- 只有在“光栅确认本事件恰有一只新触地脚、A 侧观测与身份均可靠、A 侧得到强负证据”时，才能以排除法判为 B 侧；A 侧看不清或身份歧义不属于强负证据。
- 通过踝、膝位置连续性、速度连续性和腿长突变检测疑似左右交换。首版检测到歧义直接输出 `unknown/identity_ambiguous`，不强制交换、不强制左右交替。
- `confidence` 在完成真实数据校准前只作为 `raw_score` 使用，不解释为正确率概率；正式融合阈值必须依据独立真值的 risk-coverage 结果确定。

`landing_v2` 开发顺序：

- [ ] 定义会话级跑步机方向标定数据结构、失效条件和质量诊断，不修改相机预览与录制接口。
- [ ] 在独立验证窗口中增加跑带后方/前方两点标定、站立垂直估计、方向箭头和可用性提示。
- [ ] 为 Pose 样本生成纵向/垂直相对轨迹，并在 Session 数据中保存标定参数、原始坐标和变换后坐标，保证旧数据仍可 Replay。
- [ ] 实现基于真实时间戳的局部稳健轨迹特征：触地前前摆、事件附近前向极值、触地前后速度转变、触地后支撑趋势和辅助垂直证据。
- [ ] 分离左右侧观测质量、身份质量和触地证据，放宽 ankle 核心、heel/foot index 增强的质量门。
- [ ] 实现轻量左右身份异常检测；身份歧义只拒识，不在首版自动交换 MediaPipe 标签。
- [ ] 将新算法作为版本化 `landing_v2` 接入离线 Replay；保留 `landing_v1`，对同一 Session 输出逐事件差异和 reject reason，不直接替换在线默认值。
- [ ] 在 Windows 上按正常交替、随机左右、连续同脚、设备外动作、交叉腿、轻微踉跄和短暂遮挡采集独立人工真值，分别统计 accepted accuracy、coverage、unknown rate、直接正证据错误率和排除法错误率。
- [ ] 只有 `landing_v2` 的高置信错误率和覆盖率通过预先冻结的验收门槛后，才将其设为独立验证器默认分类器；主程序融合仍另行评审。

**后续阶段：地面直线往返跑（暂不开发）**：

地面布置时，运动员可沿同一直线双向通过设备。场地直线本身保持固定，但运动员的当前前进方向会在每一趟之间翻转，因此不能沿用跑步机的固定有向纵轴，也不能把画面左/右解释为解剖左/右。

后续方案保留以下边界：

- 会话开始时标定一条无方向的场地轴；沿轴的正负只用于坐标表达，不代表运动员当前朝向。
- 对骨盆沿场地轴的位置序列做稳健斜率估计，得到每一趟的 `+1/-1` 运动方向，再用 `forward_position = travel_direction × relative_position` 把去程和返程统一为“身体前方为正”。
- 使用 `FORWARD / TURNING / BACKWARD` 方向状态机，要求方向持续稳定后才切换；转身、停止、方向速度不足或状态不确定期间的事件输出 `unknown/direction_transition`。
- 若运动员在设备外完成转身，下一趟方向稳定后重新启用视觉；若在检测区域内转身，不用普通触地相位规则强制分类。
- 方向翻转后清空或重新初始化短期左右身份轨迹，等待若干高质量 Pose 后再恢复视觉，避免近侧腿变化和遮挡关系反转污染旧状态。
- 该模式必须独立验证去程、返程、转身邻近事件、临时变向和踉跄；跑步机 `landing_v2` 的通过结果不能直接视为地面模式已经通过。

启动地面模式开发的前置条件：跑步机 `landing_v2` 已完成真机验收，方向标定与轨迹变换接口稳定，并已取得包含去程、返程和转身的同步视频及人工事件真值。在此前不新增地面方向状态机，不修改普通 `Sprint and Gait Test`。

**开发与验证任务**：

- [ ] 冻结 Python、Qt 绑定、MediaPipe、OpenCV 和 PyInstaller 的 Windows 版本矩阵。
- [x] 为 TinySE 分析帧保留 DirectShow 采样时间、复制前回调入口时间、帧序号和旧版解码后时间，同时保持旧信号兼容。
- [x] 实现 TinySE 会话级自动时间映射、状态转换、偏移冻结、严格递增输出和退化拒识。
- [x] 实现毫秒窗口调度器、全局递增推理游标和可复用的姿态结果缓存。
- [x] 在独立 Worker 中接入 Pose Landmarker Full `VIDEO` 模式，只暴露帧输入、事件输入、结果输出和生命周期接口。
- [x] 实现视觉质量门和可拒识的事件级参考标签；当前正式目标只保留 `left`、`right`、`unknown`。高置信融合及光栅安全回退另立薄适配任务，不进入首版模块。
- [ ] 增加测试前入镜质量检查，覆盖髋、膝、踝、脚跟和 foot index 的可见性。
- [ ] 对 Full 与可选 Lite 分别标定置信阈值；不允许未验证的静默降级。
- [x] 补充稳定映射、回调抖动、时间回退、流重启、漂移、严格递增、窗口重叠、采样诊断和退化拒识的自动化测试。
- [ ] 在无独显 Windows CPU 设备上进行端到端压测：光栅帧无丢失、队列不积压、UI 无明显停顿，从触地事件到视觉结果的 P95 延迟（包含等待 `post_event_ms`）目标不超过 350ms。
- [ ] 按受试者、机位和 session 分组验证已输出标签的精确率与覆盖率，单独统计交叉步、设备外踩踏、踉跄、遮挡和近同时接触。
- [x] 完成受控左脚和右脚各 10 次基础检查。
- [ ] 使用 Vision Session 工具完成跨受试者、跨 session 和困难场景的独立真值验收。

**Windows 自动同步验收与后续校准门槛**：

- 第一阶段分别执行正常交替、随机顺序、连续同脚、设备外移动、交叉腿、轻微踉跄和遮挡场景；按受试者与 Session 隔离训练、校准和最终测试数据。
- 自动方案通过条件：同步在 2 秒内进入 `ready`；同步不确定度 P95 不超过 40 ms；干净动作中触地前后姿态均充足的事件覆盖率不低于 80%；视觉决策 P95 不超过 350 ms。
- 如果同步内部指标稳定，但至少 10 个高质量事件持续存在超过一个实际 Pose 采样周期的固定偏移，下一阶段才开发“三次踩踏校准”。
- 如果偏移抖动本身超过一个实际 Pose 采样周期，三次踩踏无法修复随机抖动；继续输出视觉拒识并诊断相机采集链路，不自动切换校准方案。

**当前实现边界**：

- `vision/` 保持为独立模块，只暴露帧输入、触地事件输入、事件级结果和生命周期接口；模型、依赖、队列或时间戳异常只产生 `unknown`。
- TinySE 新增未镜像分析帧和原始时间元数据通道，原预览、录制和兼容信号保持不变；Logitech 精确同步不在当前范围内。
- 独立验证器只借用 `SessionController` 获取真实光栅事件并输出诊断 CSV，不修改 engine、报告或主 UI。
- 只有完成 Windows 依赖、CPU 延迟和真人准确率验收后，才讨论高置信融合、A/B 映射更新和 UI 开关。

视觉模块的当前接口、Session 数据结构、标注/Replay 流程和 Windows 验收入口见 `vision/README.md`；旧 Superpowers 阶段计划已被本计划和该 README 吸收，不再作为事实源。

### 2.7 跑步机步态周期检测与显示

**当前状态**：算法、检测页、报告、Excel 和历史记录开发已经完成，并通过合成事件与自动化测试验证；顶部参数卡裁切、周期倒序排列和自动定位到最新周期也已修复。当前缺口是跑步机步态/跑步原始帧及 OptoJump 或人工标注真值，尚不能声明真实检测准确性。

**当前范围**：

- 第一阶段只覆盖 `Treadmill Gait Test` 和 `Treadmill Running Test`。
- 检测过程和报告中的步态周期相关术语统一使用中文；内部字段继续使用稳定的英文标识。
- 步态周期采用 OptoJump 的同侧脚语义：同一只脚从一次触地到下一次触地形成一个周期，左、右脚分别生成周期记录；左右脚仅在计算步时间、单支撑和双支撑等跨侧指标时关联。
- 普通地面 `Sprint and Gait Test` 暂不接入；跑步机模式验证可靠后，再复用已验证的周期计算能力扩展普通地面模式。
- 第一阶段以用户的起始脚配置作为真实左右映射锚点，随后沿用当前左右脚交替推断原则；不等待视觉模块，已有的高置信视觉确认或纠正方案作为后续增强接入。

**边界片段与统计规则（已确认）**：

- 原始触地、离地事件全部保存，边界片段可以保存和回放。
- 单次接触的触地与离地边界完整时，可以计算接触时间等该次接触自身的指标。
- 只有同一只脚的前后两次触地都齐全时，才生成一条**步态周期记录**。
- 测试首尾未形成完整同侧周期的片段标记为**边界不完整片段**，不能伪装成完整步态周期。
- 边界不完整片段中的缺失字段显示 `N/A`，不能填 `0`。
- 边界不完整片段不进入完整周期的均值、标准差、变异系数和不对称统计。
- 左右脚的有效周期数允许不同，不通过删除有效周期或补造周期强行对齐。
- 不建立左右周期一一配对记录，也不引入 `paired_count` 或“有效配对数”概念。

**检测过程显示规则（已确认）**：

- 实时检测页优先显示最大 16:9 相机、倒计时和足迹通道；不再显示已完成周期列表。
- 当前未完成周期状态只在最大相机之外仍能容纳 72px 摘要栏时显示，空间不足时自动隐藏。
- 当前未完成周期状态是临时、可变的运行时状态，可以显示左脚支撑、右脚摆动、双支撑、腾空及已持续时间。
- 当前未完成周期不进入正式表格、统计、报告或导出。
- 下一次同侧触地到达、周期边界完整后，才把临时状态转换为不可变的**步态周期记录**，追加到已完成周期列表。
- 已完成周期记录提交后不再被后续实时事件原地修改；若需要过滤或人工修正，应保留原记录并单独记录纳入状态或修正来源。

**正式报告结构（已确认）**：

- 概览层分别显示左、右有效周期数和主要周期指标的汇总值。
- 周期图按同侧周期逐条绘制横向阶段时间条，不把左右脚合并成一个周期。
- 明细表逐周期显示所属脚、周期时间、各阶段秒数和百分比、有效性及统计纳入状态。
- 边界不完整片段只用于回放或独立诊断明细，不进入正式周期图和完整周期统计。

**首期周期指标范围（已确认）**：

- 首期计算并显示：步态周期、支撑相及占比、摆动相及占比、步时间、单支撑及占比、总双支撑及占比、负荷反应期及占比、摆动前期及占比。
- `Treadmill Running Test` 另外显示腾空时间；没有左右接触重叠且数据完整时，双支撑相关结果为真实的 `0`。
- 着地相、全足支撑期和推进相虽然已有预留字段，但当前缺少可靠的足底内部事件检测，首期统一显示 `N/A`。
- 在独立验证前，不得使用质心位置或估算的足跟/足尖位置近似生成着地相、全足支撑期和推进相。

**不对称统计规则（已确认）**：

- 不进行左右周期一一配对；左、右侧分别使用各自全部有效周期计算汇总值，左右样本数允许不同并同时展示。
- 各指标的不对称率统一按 `|左侧均值 - 右侧均值| / ((左侧均值 + 右侧均值) / 2) × 100%` 计算。
- 首期对步态周期、支撑相、摆动相等主要周期指标分别计算不对称率，不使用单一模糊的“不平衡指数”代替所有指标。
- 统一实时页和报告页口径，移除当前“实时页显示相对差百分比、报告仅保存有符号秒差”的不一致。

**分阶段验证方式（已确认）**：

- 第一阶段使用合成事件序列完成算法、检测页和报告开发，验证全部时间关系、统计公式、边界语义及显示/导出一致性。
- 第一阶段通过只表示逻辑和数据语义自洽，不宣称真实检测准确性已经完成验证。
- 开发完成后提醒用户提供 `Treadmill Gait Test` 和 `Treadmill Running Test` 原始帧数据，再与 OptoJump 结果或人工标注对照完成准确性验证。

**开发顺序**：

- [x] 打通已有 `starting_foot_override` 配置，让处理器以用户配置映射首个有效触地及后续交替事件，移除周期计算中 `A=left`、`B=right` 的固定假设。
- [x] 定义左右脚触地/离地事件到同侧完整步态周期的归属与关联规则，并隔离首尾边界不完整片段。
- [x] 在不依赖 Qt 的算法层计算步态周期、支撑相、摆动相、单支撑和双支撑等结果，避免由 UI 根据事件自行推断。
- [x] 保持着地相、全足支撑期和推进相为 `N/A`，另立独立验证任务后再实现，禁止以质心近似填值。
- [x] 将进行中的可变周期状态与不可变步态周期记录分开建模，以同侧下一次触地作为唯一提交点。
- [x] 在跑步机检测页以自适应摘要显示当前未完成周期；运行页不显示已完成周期列表，临时状态不得进入正式表格、统计、报告或导出。
- [x] 在跑步机报告中实现概览、逐周期阶段时间条和明细表，并保持屏幕显示、报告数据与 Excel 导出语义一致。
- [x] 按左右独立有效周期汇总值计算各主要指标的不对称率，同时展示左右样本数，并统一报告和导出口径。
- [x] 使用合成事件序列验证同侧周期边界、跨侧事件关联、步行双支撑、跑步腾空及 `0` / `N/A` 语义；补充真实采集回放和参考数据后，再完成准确性验证。
- [ ] 收集跑步机步态和跑步原始帧及 OptoJump/人工标注结果，统计触地/离地事件误差、周期指标误差、拒识率和异常事件分布，完成第二阶段真实准确性验证。

### 2.8 架构分层

按风险从低到高推进，不进行一次性大搬家：

- [x] 抽取不依赖 Qt 的步态周期核心层。
- [ ] 将 USB bytes → bits、分包合并和 `contact_bits` 转换抽为可测试模块。
- [ ] 让报告完全由结果快照生成，消除 View 对 engine 私有字段的剩余读取。
- [ ] 将 Excel 导出移出 `ReportView`。
- [ ] 引入 `DeviceTopology(segment_count, leds_per_segment, spacing_cm)`。
- [ ] 清理模块启动时的路径 hack，并补充依赖边界检查。

### 2.9 文档一致性（P1）

- [x] 更新 `README.md` 中仍把 LED 足迹和相机嵌入写成未来工作的旧状态。
- [x] 更新 `docs/architecture.md` 中已经不存在的 `CLAUDE.md` 引用和过时模块树。
- [ ] 核对并处理 `docs/步态参数相关/步态周期定义.md` 的未提交修改，保持“不建立左右周期配对”和“无法拆分双支撑子阶段时使用 N/A”的语义一致。
- [ ] 跑步机长度算法收敛后，同步 `docs/treadmill_architecture.md`、参数定义和算法说明，避免文档分别描述两套实现。

### 2.10 未来测试类型

暂未实现：Sprint and Gait、Tapping、Reaction Times、Static Test (Sway) 等。新增模式应沿用配置 → processor → report → UI 的分发模式，不污染 Jump Test 和现有跑步机模式。

### 2.11 主 UI 信息架构与组件迁移（P1）

**目标**：在当前 UI 截图右侧重建可编辑的 Figma 桌面端界面，并以此作为后续 PySide6 主界面改版依据。画布尺寸和当前 UI 截图保持一致；文字、按钮、输入框、卡片和导航均使用独立图层及 Auto Layout，不把新方案再次做成不可编辑位图。

Figma 设计文件：

- [Untitled / IronJump UI redesign](https://www.figma.com/design/zBCAGNwx0gTZthfKf7aF21/Untitled?node-id=0-1)

业务行为和交互实施以 [docs/ui_business_behavior_spec.md](docs/ui_business_behavior_spec.md) 为准。Figma 原型只确定视觉方向；当静态原型与现有业务时序冲突时，先按该规格完成行为确认，不能按控件数量直接迁移。

**已确认的信息架构**：

- 左侧采用应用级导航，不设置“首页”。
- 一级入口固定为“运动员”“测试”“结果”“设置”：
  - “运动员”负责本地用户和运动档案管理。
  - “测试”负责参数配置、设备准备和测试启动，作为本轮设计的当前选中页面。
  - “结果”负责测试记录、报告查看和后续纵向对比。
  - “设置”负责设备与本地系统配置。
- 侧栏顶部保留紧凑的图标和 `IronJump` 标识，不再显示完整的“步态分析系统”名称。
- 首版使用约 184px 的固定展开侧栏，显示图标和文字；本轮不制作折叠交互。后续为结果报告增加“仅图标”折叠状态，使图表和报告获得更大的沉浸式空间。
- 系统采用本地数据存储，当前默认单一操作者，不增加登录、账号、密码恢复、权限控制或云端同步。

**已确认的测试页布局与交互**：

- 删除原页面顶部居中的“IronJump 步态分析系统”及其状态副标题。
- 主内容区保留左对齐的页面级标题“测试”，辅以较小的说明文字“配置测试参数并连接设备”。
- 顶部右侧显示紧凑设备状态，不显示登录按钮。设备状态建议使用 12px 字号：已连接时使用绿点，未连接时使用橙色警告，并允许进入设备设置。
- 主工作区由原来的三栏简化为两栏：
  - 左侧主栏承载受试者选择、运动档案、配置方式和配置助手/手动参数。
  - 右侧摘要栏承载建议配置、关键参数和配置应用操作。
- 保留“智能配置 / 手动配置”分段切换，默认进入智能配置。智能配置显示配置助手、快捷指令和建议参数；手动配置在相同区域显示参数表单；两种方式共享右侧摘要和最终启动入口。
- 允许不关联正式运动员的“临时测试”：
  - 使用可编辑的默认人体参数，如 30 岁、70kg、170cm。
  - 结果明确标记为“临时测试”，不进入正式运动员趋势统计。
  - 测试完成后允许把结果重新归属给正式运动员。
  - 启动前提示默认人体参数可能影响分析准确性。
- 配置页只保留一个橙色主操作“进入测试准备”；“应用建议配置”降为次级描边按钮。两阶段启动已经确认：参数配置完成后进入测试界面，执行设备准备、站位或相机预览，但不能自动开始；设备就绪后，用户仍必须点击独立的“开始采集”才进入运行。参数或设备失败时停留在可重试状态并显示原因。

**已确认的视觉方向**：

- 保留深色主题和 IronJump 橙色品牌色，但减少卡片套卡片、重复描边和重阴影。
- 使用一层主卡片配合分组标题、留白、细分隔线和统一的输入控件高度；橙色只用于当前导航、选中状态和关键操作。
- 参考组合为“shadcn 的简洁结构 + Tabler 的专业数据密度 + OptoJump 的业务导航”，不直接复制任何模板：
  - [shadcn/ui Dashboard 与 Sidebar](https://ui.shadcn.com/blocks?category=dashboard)：应用外壳、页面标题、紧凑导航和未来的图标折叠模式。
  - [Tabler Admin](https://tabler.io/admin-template)：深色表单、低对比描边、留白和专业数据界面密度。
  - [OptoJump 操作指南](https://sens.exeter.ac.uk/v8media/facultysites/hls/phss/documents/Optojump_User_guide.pdf)：运动员—测试—结果的领域信息架构。
  - [TailAdmin GitHub](https://github.com/TailAdmin/free-react-tailwind-admin-dashboard)：开源深色侧栏、表单和基础 Figma 组件的可实现性参考。

**Dayu 组件迁移决策**：

- 长期不再以 `dayu_widgets` 作为新界面的基础组件库，但本轮不进行一次性删除。
- 新的应用外壳、侧栏和改版页面不新增 Dayu 依赖，优先使用标准 PySide6 控件和集中式 QSS。
- 相机窗口、旧报告页和回退界面暂时保留现有 Dayu 控件，避免 UI 改版扩大为全项目重写。
- 核心页面迁移和回归完成后，再分批替换 `MLabel`、`MPushButton`、`MSpinBox`、`MSectionItem`、`MSwitch`、`dayu_theme` 和 Dayu `application()`，最终移除未进入 Git 和依赖清单的本地第三方源码。

**开发与验收任务**：

- [x] 审计当前测试流程、状态、设备/算法接口、持久化和报告关联，形成业务行为与交互规格。
- [ ] 在 Figma 原截图右侧完成测试页高保真、可编辑设计，检查图层命名、Auto Layout、间距、对齐、文本和控件独立性。
- [ ] 为侧栏、按钮、输入框、状态标签、分段选择器和卡片建立最小必要的组件及状态，不提前制作未确认的页面和复杂组件库。
- [ ] 设计“正式运动员已选择”和“临时测试”两种关键状态，以及设备已连接/未连接、开始测试可用/禁用状态。
- [x] 将固定展开的应用外壳落到 PySide6，提供运动员、测试、结果和设置四个一级入口。
- [ ] 为新的 PySide6 主题集中定义背景、表面、边框、文字、橙色主色、成功/警告状态、圆角和间距 token，避免各 View 继续复制大段 QSS。
- [x] 迁移测试页并验证智能/手动配置切换、临时测试、统一配置校验、设备门控和“进入准备后再次点击开始采集”的两阶段流程。
- [x] 接入独立运动员、全局结果和只读设置/诊断页面；结果支持临时测试关联运动员、历史参数复用和历史报告重开。
- [x] 为运行中跨模块导航提供“留在测试 / 结束并保存 / 结束并标记异常”保护；准备阶段可返回配置且不生成报告。
- [x] 为 USB 连接与采集建立结构化状态，并验证配置确认不会提前启动采集。
- [x] 为临时测试执行 SQLite 可空归属迁移，保存会话快照、真实采集起止时间和完整报告详情。
- [ ] 结果页稳定后实现侧栏折叠和状态持久化；本轮按已确认范围保持固定展开。
- [ ] Dayu 全量移除前运行 UI 与相机相关回归，确认应用启动、主题、报告、图表、相机控制和回退界面均不依赖残留行为。

## 3. 已确认的业务和架构决策

- 配置参数、会话元数据、结果参数、汇总统计分层保存。
- 跑步机累计距离由设定速度和时间反算；单步长度当前还叠加方向修正后的脚位置漂移。最终步长/步幅模型须完成 2.1 的分支收敛后再作为稳定业务规则。
- 跑步机报告使用独立 `TreadmillGaitReport` / `TreadmillRunningReport`，不压入普通 `GaitTestReport`。
- 步态周期按同侧脚相邻触地划分，左右脚分别生成周期记录；跨侧事件关联只用于步时间、单支撑和双支撑等指标。
- 原始事件与边界不完整片段全部保留，但只有两次同侧触地齐全时才生成步态周期记录；边界不完整片段不进入完整周期及不对称统计，左右有效周期数允许不同且不强制配对。
- 不建立左右周期一一配对记录，也不引入 `paired_count` 或“有效配对数”概念；步时间、单支撑和双支撑仍按实际跨侧事件关系计算。
- 不对称率基于左右各自全部有效周期的指标均值计算，不做逐周期配对；公式统一为两侧均值绝对差除以两侧均值的平均值，并同时展示左右样本数。
- 检测页采用“当前未完成周期状态 + 已完成周期列表”两层显示；临时状态不进入正式输出，只有周期闭合后才转换为不可变步态周期记录并追加到列表。
- 跑步机正式报告采用“概览 + 逐周期阶段时间条 + 明细表”三层结构；边界不完整片段仅用于回放或诊断，不进入正式周期图和统计。
- 首期只生成触地、离地及左右接触重叠事件能够可靠支持的周期指标；着地相、全足支撑期和推进相在独立验证前保持 `N/A`，不得使用质心近似。
- 跑步机周期功能首期以用户起始脚配置为左右映射锚点，并沿用当前交替推断原则；高置信视觉结果对左右映射的确认或纠正按已有方案后续接入，不作为首期前置条件。
- 足迹回放使用固定 cadence 的 canonical timeline，不由 UI 根据 touch/lift 事件自行推断。
- 左右脚视觉模块首版使用 MediaPipe Pose Landmarker Full + CPU + `VIDEO` 模式；TinySE 先通过会话级自动映射把 DirectShow 采样时间对齐到光栅使用的 `time.perf_counter()` 时钟域，再进入可配置毫秒事件窗口和全局递增推理缓存。视觉只输出可拒识的参考标签和时间一致性诊断，不替代或改写光栅触地/离地时序。
- `Suspended` 等未来状态可以保留枚举，但当前第一阶段不生成该状态。
- 暂不接入 Gyko/IMU、跑步机控制器自动读速、BioFeedback 正式模式。
- 暂不添加 overload 的能量/功率计算，除非补充体重输入和公式依据。

## 4. 文档和参考资料分工

- `README.md`：Agent onboarding、运行方式和核心约束。
- `docs/architecture.md`：通用系统架构；代码演进后需要同步，但不作为计划清单。
- `docs/treadmill_architecture.md`：跑步机架构和数据契约。
- `docs/参数相关/跑步机模式参数.md`：跑步机配置参数与结果参数定义。
- `docs/参数相关/代码步态参数汇总.md`：理论指标到代码实现的映射。
- `docs/步态参数相关/optojump参数汇总.md`：OptoJump 领域参数参考。
- `docs/步态参数相关/纵跳计时误差诊断与方案验证.md`：纵跳离线诊断历史和当前准则。
- `docs/步态参数相关/步态周期定义.md`：面向用户的周期术语、阶段关系和结果解释。
- `vision/README.md`：视觉参考标签、TinySE 时间同步、Windows 验证命令和验收字段。
- `camera/obsbot_sdk_wrapper/README.md`：相机 wrapper 编译和设备实测记录。
- `素材.md`：毕业论文素材库，按第四章设计、第五章实现、第六章测试组织，不承担项目进度管理。
- `writing.md`：Markdown 文档定位、准确性和论文素材写作规则。

## 5. 验证入口

建议在具备项目测试依赖的环境中运行：

```bash
python -m pytest -q
```

如果当前解释器缺少 `pytest`，只能执行语法检查和基于 `unittest` 的局部回归，不能据此声称全量测试通过。测试结论应同时记录日期、提交、操作系统、Python 环境和被跳过/排除的测试。

重点回归范围：

```bash
python -m pytest \
  tests/test_treadmill_config.py \
  tests/test_treadmill_report.py \
  tests/test_treadmill_processor.py \
  tests/test_mode_runtime.py \
  tests/test_subject_store.py \
  tests/test_footprint_visualization.py \
  tests/test_execution_view_footprint.py \
  tests/test_report_view_footprint.py \
  tests/test_tinyse_camera_widget.py -q
```

## 6. 论文相关资料

以下文件属于论文、研究或写作辅助资料，本次不修改：

- `素材.md`
- `writing.md`
- `chatgpt.md`
