# Iron_Jump 系统架构文档

> 最后更新: 2026-08-10

## 1. 项目概述

OptoJump 兼容的步态/纵跳分析系统。硬件是两根分别放置在两侧的条形装置，每根包含 96 个红外 LED，通过 USB 连接 PC，以 1000Hz 采样率实时上报每个 LED 的遮挡状态。

软件负责：接收原始数据 → 算法检测触地/腾空事件 → UI 实时展示 → 生成测试报告。

## 2. 技术栈

| 层 | 技术 | 说明 |
|:---|:---|:---|
| **语言** | Python 3.11 | 统一环境，不再分 dayu / pydantic_ai 两个 conda 环境 |
| **UI** | PySide6 6.11 + qtpy + dayu_widgets | dayu_widgets 为纯 Python 库，本地源码放在项目根 |
| **图表** | pyqtgraph (可选) | 降级为 QLabel 占位（`_PG_AVAILABLE` 检查） |
| **硬件通信** | ctypes + CyUsbInterface.dll (stdcall) | Windows-only |
| **AI Agent** | pydantic-ai + DeepSeek v4-flash | 通过 .env 配置 API 地址和密钥 |
| **数据导出** | openpyxl (Excel) | |
| **数据持久化** | SQLite (内置 sqlite3) | 受试者管理 + 测试记录 |
| **相机** | OpenCV + OBSBOT SDK (ctypes) | DirectShow 后端，独立窗口 |

**采样率固定 1000Hz** — 硬件约束，代码中不应出现采样率可配置的逻辑。

## 3. 目录结构

```
Iron_Jump/
├── hardware/                 # L1 层：硬件通信
│   ├── CyUsbInterface.dll    # Cypress USB 驱动 DLL
│   ├── protocol.py           # 协议解析器（帧头帧尾、CRC8、分包重组）
│   ├── receive.py            # DLL ctypes 封装
│   └── usb_worker.py         # QObject Worker，管理 USB 读取线程，发射 Qt Signal

├── engine/                   # L2 层：算法引擎
│   ├── gait_engine.py        # 核心引擎：接收原始帧 → 检测事件 → 发射高级信号
│   ├── single_foot_tracker.py  # 纵跳模式：单足触地/腾空状态机
│   ├── contact_tracker.py    # 步态模式：基于接触区域的步态事件追踪
│   ├── spatial_clusterer.py  # 空间聚类：将 96 位数据聚类为脚印
│   └── extra_parameter.py    # 高阶步态参数计算（步长、步速等）

├── config/                   # 配置层
│   ├── Iron_parameters.json  # OptoJump 参数定义（4 层结构，含联动规则）
│   ├── param_schema.py       # JSON Schema 加载器 + 校验器
│   ├── test_config.py        # TestConfig dataclass：一次测试的完整运行时参数
│   └── test_report.py        # TestReport frozen dataclass：不可变测试结果快照

├── data/                     # 数据持久化层
│   └── subject_store.py      # SQLite 用户、团队、成员关系、Session 与分析运行记录

├── agent/                    # AI Agent 模块
│   ├── common/               # Config / Report 共用模型提供器和基础设施
│   ├── config/               # 测试前智能配置、结构化模型和独立 prompts
│   ├── report/               # 测试后分析 Agent、Kernel、Validator 与 Renderer
│   ├── worker.py             # 单 Worker，多业务路由和状态隔离
│   ├── rule_engine.py        # 离线模式：规则引擎 → TestConfig
│   └── gait_agent.py         # 兼容 Facade 和生命周期入口

├── reporting/                # 面向 UI 与 Agent 的确定性报告语义层

├── vision/                   # 可拒识左右脚参考、Session 录制、标注与 Replay
├── tools/                    # 诊断、Benchmark、Vision 录制/标注/Replay CLI
├── benchmark_results/        # Report Agent 固定合成案例结果与审计说明

├── ui/                       # UI 层
│   ├── main_window.py        # 入口：多视图路由 (QStackedWidget)
│   ├── session_controller.py # 会话控制器：管理 QThread + UsbWorker + GaitEngine 生命周期
│   ├── param_panel.py        # 动态参数配置面板（Schema 驱动）
│   ├── camera.py             # OpenCV 相机（独立线程，独立窗口）
│   ├── led_con.py            # LED 状态可视化
│   ├── led_panel.py          # LED 面板组件
│   ├── data_show.py          # 旧版单页 Demo（回退方案）
│   └── views/
│       ├── setup_view.py         # 配置页：ParamPanel + AgentConfigPanel + 受试者选择
│       ├── agent_config_panel.py # Agent 智能配置面板（在线 LLM / 离线规则引擎）
│       ├── execution_view.py     # 执行页：MetricCard 仪表盘 + 实时图表
│       └── report_view.py        # 报告页：统计汇总 + Excel 导出

├── camera/                   # 相机模块
│   ├── logi_camera.py        # 通用 USB 摄像头 (OpenCV MSMF)
│   ├── tinyse_camera.py      # OBSBOT Tiny SE 摄像头 (DirectShow + SDK 控制)
│   └── tinyse_dshow_capture.py  # DirectShow 采集 DLL 封装

├── tests/
│   ├── test_rule_engine.py     # 规则引擎 14 个测试
│   ├── test_llm_test_config.py # LLMTestConfig 转换 5 个测试
│   └── test_subject_store.py   # SubjectStore 7 个测试

├── docs/
│   └── architecture.md       # 本文档
├── path_utils.py             # DLL 路径查找工具
├── vision_app.py             # Windows 视觉数据统一 QtPy 启动器
├── IronJumpVisionTools.spec  # PyInstaller onedir 配置
├── build_vision_app.bat      # Windows 一键构建入口
├── AGENTS.md                 # 代码编写行为准则
├── plan.md                   # 开发计划
├── .env                      # DeepSeek API 配置
└── requirements.txt          # Python 依赖
```

## 4. 分层架构

```
┌─────────────────────────────────────────┐
│ UI 层 (Qt)                               │
│  main_window.py → views/                 │
│  session_controller.py                   │
├─────────────────────────────────────────┤
│ Agent 层                                 │
│  Config Agent + Report Agent             │
│  ├── common/ 共享模型连接                 │
│  ├── config/ Fast Gate + Parallel Clarify│
│  ├── report/ Plan + Kernel + Validator   │
│  └── worker.py 单进程多路由                │
├─────────────────────────────────────────┤
│ 配置层                                   │
│  param_schema.py + test_config.py        │
├─────────────────────────────────────────┤
│ 算法引擎层 (L2)                           │
│  gait_engine.py + trackers               │
├─────────────────────────────────────────┤
│ 硬件通信层 (L1)                           │
│  usb_worker.py + protocol.py             │
├─────────────────────────────────────────┤
│ 数据持久化层                              │
│  subject_store.py (SQLite)               │
└─────────────────────────────────────────┘
```

**关键约束**:
- GaitEngine 不 import 任何 QtWidgets — 在 Worker 线程中运行
- 所有 UI 更新通过 QueuedConnection 回到主线程
- UI 层不直接 import agent（AgentConfigPanel 通过 gait_agent Facade 访问）

## 5. 核心信号流

### 5.1 测试生命周期

```
用户点击"准备就绪"
  → SetupView.ready_signal.emit(SessionSetup)
  → MainWindow._on_ready(setup)
      → ExecutionView.reset() + configure(config)
      → SessionController.prepare(config)
          → 创建 QThread + UsbWorker + GaitEngine
          → moveToThread
          → 连接信号: L1→L2 (DirectConnection), L2→Controller (QueuedConnection)
      → 切到 ExecutionView

用户点击"开始"
  → ExecutionView.start_requested
  → SessionController.start() → thread.start()
```

### 5.2 实时数据流

```
后台线程:
  UsbWorker.raw_contact_signal
    →[DirectConnection]→ GaitEngine.process_raw_frame()
    →[产生事件]→ hop_event / gait_step_event
    →[QueuedConnection]→ SessionController → ExecutionView

测试结束 (自动/手动):
  GaitEngine.test_finished.emit(reason)
  → SessionController._on_engine_finished()
      → 200ms 延迟 → stop()
      → build_report(engine, reason) → TestReport (frozen dataclass)
      → session_finished.emit(TestReport)
  → MainWindow → ReportView.load_report(report)
      → SubjectStore.record_session() 归档
```

### 5.3 受试者选择与配置回填

```
SetupView 受试者搜索/选择
  → _refresh_subject_results(query)
  → SubjectStore.search_subjects()

"加载上次参数"
  → SubjectStore.get_last_session(subject_id)
  → param_panel.set_config(session.config)

Agent 生成配置 (AgentConfigPanel)
  → config_selected(TestConfig)
  → param_panel.set_config(config)
  → _update_summary()
```

正式用户进入测试准备时还会冻结身份快照：

```text
subject_id + subject_snapshot
  + 用户主动选择的 team_id / 无团队身份
  + team_snapshot（仅团队身份测试）
  → SessionSetup
  → test_sessions 单条记录
```

### 5.4 Report Agent 分析流

```text
ReportView(session_id)
  → 用户点击“智能分析”
  → Worker report route
  → ReportRepository 按 session_id 重建不可变报告与允许数据范围
  → ReportDataPackageBuilder / AgentObservationBuilder
  → Report Agent 每轮生成一个 AnalysisDecision
  → ActionValidator
  → AnalysisToolGateway 执行一个白名单 Tool 与确定性分析方法
  → Evidence 状态归约与 Checkpoint
  → 下一轮决策或停止并综合
  → ClaimValidator + Numeric Binding
  → AnalysisPackage 持久化
  → ReportView 展示只读结果
```

正式报告先于智能分析生成；模型不可用、超时或 Claim 被拒绝都不会改变已有报告。当前 MVP 默认只分析本次 session，个人历史纵向和团队横向能力尚未开放。

## 6. 线程模型

```
┌─────────────────────────────────────────────┐
│ 主线程 (GUI)                                  │
│  MainWindow, SetupView, ExecutionView,        │
│  ReportView, SessionController                │
│  (所有 Qt Widget 操作必须在此线程)              │
└──────────────┬──────────────────────────────┘
               │ QueuedConnection (低频 ~2-5Hz)
┌──────────────▼──────────────────────────────┐
│ Worker 线程 (QThread)                         │
│  UsbWorker → GaitEngine                      │
│  DirectConnection (高频 1000Hz)               │
│  [USB 读取在 daemon 子线程，回调到此线程]        │
└─────────────────────────────────────────────┘

Agent LLM 调用线程 (QThread):
  WarmupWorker → warmup_online()
  LLMWorker → chat_online_stream()
```

**关键约束**:
- `SessionController.prepare()` 中严格遵循: 创建对象 → moveToThread → 连接信号 → start
- `stop()` 必须在 `build_report()` 之前停线程，否则竞态

## 7. 参数配置系统

参数配置有 3 种方式，输出完全一致的 `TestConfig`:

| 方式 | 入口 | 说明 |
|:---|:---|:---|
| **手动配置** | `ParamPanel.get_config()` | Schema 驱动的动态表单 |
| **规则引擎** (离线) | `GaitAgent.configure_offline()` | 按 AthleteProfile 自动推荐 |
| **LLM** (在线) | `GaitAgent.chat_online()` | 自然语言对话 → 结构化输出 |

### 参数分层 (来自 Iron_parameters.json)

| Layer | 内容 | 示例 |
|:---|:---|:---|
| 1 | 测试类型选择 | test_macro_type, test_type |
| 2 | 主配置参数 | stop_type, number_of_jumps, test_length |
| 3 | 滤波参数 | min_contact_time, min_flight_time, max_flight_time |
| 4 | 可选反馈 | metronome_enabled, metronome_bpm |

### 参数联动规则

- `stop_type = "Status change"` → `number_of_jumps` 和 `finish_position` 可见
- `stop_type = "End of Time"` → `test_length` 可见
- `External impulse` 不属于当前硬件能力，已从活动参数 Schema 移除

### 术语说明

项目中"参数"一词有四种不同含义，代码和文档使用以下对照关系：

| 中文术语 | 代码类型 | 含义 |
|:---|:---|:---|
| 配置参数 | `TestConfig` | 测试前由用户或系统设定，参与采集、停止、过滤、计算 |
| 会话元数据 | `SessionMetadata` | 测试开始时冻结的受试者或环境信息，不一定是算法阈值 |
| 结果参数 | `ResultMetric` | 测试后从事件和配置计算出的逐步或逐周期结果 |
| 汇总统计 | `MetricSummary` | 对结果参数做 min/max/mean/std/CV、左右脚、不对称性统计 |

数据库中的配置快照称为"配置快照"，报告快照称为"报告快照"。

## 8. Agent 模块设计

### 8.1 两个业务域

```text
测试前：自然语言需求
  → Config Agent
  → LLMTestConfig
  → TestConfig + ParamSchema 校验

测试后：不可变 TestReport + session_id
  → ReportDataPackage / AgentObservation
  → Report Agent 生成单步 AnalysisDecision
  → ActionValidator
  → 确定性 Analysis Kernel
  → Evidence 状态归约 / ClaimValidator
  → AnalysisPackage
  → 确定性 Renderer + 报告页智能分析区域
```

Config Agent 与 Report Agent 业务状态隔离，但共用模型提供器和单一 Worker 进程。Report Agent 不复用 Config Agent 的对话历史，也不能修改测试配置或正式报告数值。

### 8.2 Fast Gate + Parallel Clarify

**Fast Gate**：确定性关键词检测（`_is_config_request()`），三级词表（强配置短语 / 动作词 / 约束词）。它只选择调用成本路径，不拥有否决 AI 合法结构化配置的权力。Gate 漏判但首次模型返回配置时，复用首次结果并补两次采样，再按现有一致性规则裁决。

**Parallel Clarify**：命中 gate 后，从同一个 `message_history` 快照并行发起 3 次 `agent.run()`，所有 sample 地位平等。用 `_cluster_configs()` 按关键字段值聚类：
- 1 组一致 → 随机选代表，转 TestConfig，校验通过后输出
- 多组分歧 → `_find_disagreements()` + `_generate_clarification()` 追问
- 有效配置不足 2 个 → 追问，请用户补充信息

**History 更新策略**：
- 非配置路径：使用该次调用的 `result.all_messages()`
- 配置成功：使用被选中代表 sample 的 `result.all_messages()`
- 分歧/不足：使用第一个 ChatResponse 的 history，否则用第一个 sample

**Warmup**：`warmup()` 发送真实 API 请求预热 TCP/TLS 连接和服务端 GPU 实例，在后台线程执行，不阻塞 UI。

### 8.3 LLM 结构化输出层

```
LLM 输出 JSON → Pydantic 校验 → LLMTestConfig (BaseModel)
  → .to_test_config() → TestConfig (dataclass, 系统通用)
  → ParamSchema.validate() → 业务逻辑二次校验
```

`LLMTestConfig(BaseModel)` 是中间层：通过 `Field(description=..., ge=..., le=...)` 和 `Literal[...]` 将约束编码进 JSON Schema，让 LLM 输出更准确。`@field_validator("test_length")` 归一化 `"2m"`、`"120s"` 等格式为 `"02:00"`。

### 8.4 规则引擎

`PROFILE_RULES` 是 `list[tuple[Callable, dict]]`，数据驱动。多规则命中同一字段时取最保守值（`min_contact→MAX`, `number_of_jumps→MIN`, `max_flight→MIN(非零)`），与规则添加顺序无关。

### 8.5 Report Agent 可信边界

- `TestReport` 是不可变事实源；Builder 只能转换和补充稳定引用，不能改变正式结果。
- Agent 只能从 `AnalysisToolRegistry` 选择已启用 Tool，并从 `AnalysisMethodRegistry` 选择该 Tool 所属的确定性分析方法；不能访问通用 SQL、任意 Python 或原始 1000Hz 数据。
- PlanValidator 根据测试类型、数据可用范围、参数和预算校验计划。
- Kernel 负责所有聚合、分组、趋势、敏感性和跨指标比较；模型不得自由计算正式数值。
- 每个 Claim 必须绑定 Fact、Evidence Ref、Predicate 和 Numeric Binding。错误数字、无证据结论、越权范围、因果或医学语言由 Validator 拒绝。
- 生产默认采用 AnalysisSketch + Compact Series，关闭 Screening Cues 和 Replan；两项能力保留为显式实验开关。

### 8.6 用户、团队与分析数据范围

```text
subjects ↔ team_memberships ↔ teams
   ↓
test_sessions(subject_id, team_id, subject_snapshot, team_snapshot)
   ↓
个人历史按 subject_id 查询
团队历史按测试时 team_id 查询
```

每次测试只保存一条 session。正式用户测试始终带有 `subject_id`；选择团队身份时额外保存 `team_id` 和测试时团队快照。个人历史与团队历史是同一条记录的不同查询视图，不复制报告。Report Agent 的历史或团队能力必须从当前 session 推导允许范围，不能把私人个人测试静默混入团队分析。

## 9. 关键设计决策

| 决策 | 结论 | 原因 |
|:---|:---|:---|
| **采样率** | 固定 1000Hz | 硬件约束 |
| **TestConfig** | dataclass, 不改为 BaseModel | 全系统通用 (engine/ui/controller) |
| **LLM 输出** | 新增 `LLMTestConfig(BaseModel)` 转换层 | 不改 TestConfig，但给 LLM 更好的约束 |
| **TestReport** | frozen=True dataclass | ReportView 不持有 GaitEngine 引用 |
| **Python 版本** | 3.11 统一环境 | 消除 agent/ui 间的版本边界 |
| **Agent 集成方式** | AgentConfigPanel 嵌入 SetupView | 从 agent_test_ui 独立测试工具 → 主 UI 配置组件 |
| **LLM 调用模式** | Fast Gate + Parallel Clarify | 非配置请求不浪费并行采样，配置请求样本地位平等 |
| **相机** | TinySE 预览嵌入 ExecutionView；Vision 数据工具独立运行 | 主 UI 负责预览/录像，独立工具负责真值数据闭环，二者不同时占用设备 |
| **Report Agent** | 单步序贯决策 + 确定性 Kernel + 强 Validator | 每轮只执行一个已校验动作，同时确保数字、证据和权限可复现 |
| **Report Agent 默认配置** | Sketch + Compact Series；按需 Skill Reference；最多 5 次 Tool 调用 | 序贯合成 Benchmark 满足既定有效率、Recall 与 P95 门槛 |
| **视觉输出** | `Left / Right / Unknown` | 允许拒识；双脚落地和纵跳不属于视觉模块目标 |
| **旧 data_show.py** | 保留不动 | 回退方案 |
| **dayu_widgets** | 本地源码，.gitignore 排除 | 不提交到 Git |

## 10. 常见陷阱

1. **不要在 GaitEngine 中 import QtWidgets** — 在 Worker 线程中运行
2. **不要假设采样率可配置** — 固定 1000Hz
3. **不要删除 data_show.py** — 回退方案
4. **不要让 ReportView 持有 GaitEngine 引用** — 通过 TestReport (frozen) 传递
5. **不要在模块导入时初始化 LLM** — 使用延迟初始化 (`_ensure_agent()`)
6. **不要把 TestConfig 改为 BaseModel** — LLM 输出用 `LLMTestConfig` 转换层
7. **stop() 必须在 build_report() 之前停线程** — 否则竞态
8. **SessionController.prepare() 中信号连接顺序**: 先 moveToThread，再连接信号
9. **ParamSchema.validate() 会检查 Layer 1 参数** — agent 调用时需补充 test_macro_type
10. **camera 控制链 stop 后复用** — 只在 closeEvent 释放，Start/Stop 循环保持控制链存活


### 五模式智能配置扩展（2026-09-27）

地面走路与跑步沿用同一链路，分别使用 `LLMWalkingConfig` / `LLMOvergroundRunningConfig` 和独立 Prompt，转换成 `WalkingConfig` / `OvergroundRunningConfig`，再经统一运行时校验。两者仅暴露 `stop_type`、`starting_foot` 与固定类型判别字段，拒绝额外字段；设备段数由硬件识别，检测阈值使用各模式运行时默认值，不套用纵跳档案规则。

`agent/config/modes.py` 统一声明五种配置模式；UI 选定模式后，语音转写与打字共用 ConfigService 和确认流程。模式选择不由自然语言自动切换。地面 Prompt 对跨模式或当前不支持的时长/距离要求进行解释与澄清，代码拒绝未知模式及跨模式结构化输出。切换模式期间到达的旧回复仅归入原对话，不恢复待确认配置或播报为当前建议。
