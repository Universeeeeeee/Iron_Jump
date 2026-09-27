# Iron_Jump 系统架构文档

> 最后更新: 2026-09-27；分支: `vae/iron_jump`，含本轮模式路由与设备质量更新

## 1. 项目概述

模式扩展必须遵守 [模式意图路由与异常光束容忍约定](mode-routing-and-beam-quality.md)：先解析模式再生成配置，统一自检与冻结故障清单，保留原始数据和质量快照；不能在某个新模式中绕过确认或自行放宽阈值。

OptoJump 兼容的纵跳、跑步机步态/跑步和地面走路/跑步分析系统。红外光栅每段包含 96 个光束，通过 USB 连接 PC，以固定 1000 Hz 采样率上报遮挡状态。正式硬件路径的五种模式均消费完整设备帧并经过统一质量门；纵跳与跑步机目前仍只支持单段。显式模拟源保留旧接触信号入口，不代表硬件自检通过。

软件负责：接收原始数据 → 算法检测触地/腾空事件 → UI 实时展示 → 生成测试报告。

## 2. 技术栈

| 层 | 技术 | 说明 |
|:---|:---|:---|
| **语言** | Python 3.11 | 统一环境，不再分 dayu / pydantic_ai 两个 conda 环境 |
| **UI** | PySide6 + qtpy + dayu_widgets | 依赖由 requirements.txt 管理，dayu_widgets 固定 1.1.1 |
| **图表** | pyqtgraph (可选) | 降级为 QLabel 占位（`_PG_AVAILABLE` 检查） |
| **硬件通信** | ctypes + CyUsbInterface.dll (stdcall) | Windows-only |
| **AI Agent** | pydantic-ai-slim[openai] + DeepSeek v4-flash | 独立 Worker，通过 .env 配置服务 |
| **RAG** | SQLite FTS5 + fastembed + RRF | 确定性检索、建议校验及发布指纹 |
| **语音** | Pipecat + 豆包 ASR/TTS + WebRTC AEC3 | 可选依赖、独立进程、显式开启麦克风 |
| **RFID** | ctypes + OUR_MIFARE.dll | Windows RC200U 读卡与身份绑定 |
| **数据导出** | openpyxl (Excel) | |
| **数据持久化** | SQLite (内置 sqlite3) | 受试者管理 + 测试记录 |
| **相机** | OpenCV + OBSBOT SDK (ctypes) + MediaPipe | Tiny SE 预览嵌入主 UI；Windows 数据工具和 Mac 身份验证器独立运行 |

**采样率固定 1000Hz** — 硬件约束，代码中不应出现采样率可配置的逻辑。

## 3. 目录结构

```
Iron_Jump/
├── hardware/                 # L1 层：硬件通信
│   ├── CyUsbInterface.dll    # Cypress USB 驱动 DLL
│   ├── protocol.py           # 协议解析器（帧头帧尾、CRC8、分包重组）
│   ├── receive.py            # DLL ctypes 封装
│   ├── usb_worker.py         # USB 读取、完整帧信号与单段兼容信号
│   ├── sensor_frame.py       # DeviceLayout / SensorFrame、分包组装与采样时钟
│   ├── walking_preflight.py  # 空场自检与不可变 PreparedDevice
│   ├── beam_quality.py       # 人工阈值、连续束判定及冻结屏蔽规则
│   ├── simulated_worker.py   # 演示用原始信号源
│   └── rc200u.py             # RFID 厂商 DLL 包装与读取线程

├── engine/                   # L2 层：算法引擎
│   ├── gait_engine.py        # 核心引擎：接收原始帧 → 检测事件 → 发射高级信号
│   ├── single_foot_tracker.py  # 纵跳模式：单足触地/腾空状态机
│   ├── contact_tracker.py    # 步态模式：基于接触区域的步态事件追踪
│   ├── spatial_clusterer.py  # 空间聚类：将 96 位数据聚类为脚印
│   ├── extra_parameter.py    # 高阶步态参数计算（步长、步速等）
│   ├── overground_session.py # 地面准备、自检、布防、异常与报告生命周期
│   ├── device_quality_session.py # 五模式正式硬件共用的准备/运行质量门
│   ├── walking_session.py    # 地面走路兼容入口
│   └── modes/               # Jump / Treadmill / Walking / Overground Running processors

├── config/                   # 配置层
│   ├── Iron_parameters.json  # OptoJump 参数定义（4 层结构，含联动规则）
│   ├── param_schema.py       # JSON Schema 加载器 + 校验器
│   ├── test_config.py        # TestConfig dataclass：一次测试的完整运行时参数
│   ├── test_report.py        # JumpTestReport / 地面走路 GaitTestReport
│   ├── treadmill_config.py / treadmill_report.py
│   ├── walking_config.py    # 地面走路配置
│   └── overground_running_config.py / overground_running_report.py

├── data/                     # 数据持久化层
│   └── subject_store.py      # SQLite 用户、团队、成员关系、Session 与分析运行记录

├── agent/                    # AI Agent 模块
│   ├── common/               # Config / Report 共用模型提供器和基础设施
│   ├── config/               # 测试前智能配置、结构化模型和独立 prompts
│   ├── report/               # 测试后分析 Agent、Kernel、Validator 与 Renderer
│   ├── worker.py             # 单 Worker，多业务路由和状态隔离
│   ├── rule_engine.py        # 离线模式：规则引擎 → TestConfig
│   └── gait_agent.py         # 兼容 Facade 和生命周期入口

├── reporting/                # 确定性报告语义、本地步态问答和地面跑步导出
├── knowledge/                # 文献摄取、检索、建议校验、审计与 RAG Release Gate
├── voice/                    # ASR/TTS 协议、Pipecat pipeline、音频与 AEC3

├── vision/                   # 可拒识左右脚参考、Session 录制、标注与 Replay
├── tools/                    # 诊断、Benchmark、Vision 录制/标注/Replay CLI
├── benchmark_results/        # Report Agent 固定合成案例结果与审计说明

├── ui/                       # UI 层
│   ├── main_window.py        # 入口：多视图路由 (QStackedWidget)
│   ├── session_controller.py # 会话控制器：管理 QThread + UsbWorker + GaitEngine 生命周期
│   ├── param_panel.py        # 动态参数配置面板（Schema 驱动）
│   ├── llm_client.py         # QProcess 管理 Agent Worker，HTTP 业务请求
│   ├── voice_bridge.py       # QProcess 语音消息与主线程业务路由
│   ├── voice_panel.py        # 主界面固定语音栏、上下文提示与折叠诊断
│   ├── demo.py               # 模拟光栅、真实引擎与独立数据库入口
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
│   ├── test_sensor_interface.py
│   ├── test_overground_walking.py / test_overground_running.py
│   ├── test_voice_session.py / test_rc200u.py
│   └── ...                   # 算法、Agent、RAG、UI、生命周期及数据回归

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
│  ├── report/ 序贯决策 + Kernel + 校验      │
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
- UI 不加载 Agent 业务实现；`AgentWorkerClient` 启动独立 Worker 并通过 HTTP 请求，Qt 请求线程避免阻塞界面。语音由另一独立进程处理，通过 JSON 行消息交回主线程。

## 5. 核心信号流

### 5.1 测试生命周期

```text
SetupView.ready_signal(SessionSetup)
  → MainWindow → SessionController.prepare(config)
  → 创建或复用 UsbWorker + QThread，创建 GaitEngine 并连接信号
  → 准备阶段启动线程、连接设备，切到 ExecutionView

五种模式：准备时连续采集 → DeviceQualitySession 空场观察
  → 健康就绪 / 阈值内待人工降级确认 / 超限阻止开始
  → 开始命令在处理帧的同一线程重新核对，再冻结本次质量快照
```

默认连续观察 3 秒，每段异常比例不超过 2.5%、相邻连续异常不超过 2 束；阈值由设置页人工管理。就绪信息超过 500 ms 失效。开始时冻结 `PreparedDevice`（布局、stream_id、自检样本序号、阈值、疑似坏点及类型），沿用同一个采集流。地面模式首次有效接触回溯到首帧作为测试时间零点；单次通过不接受暂停/继续，物理停步仍参与整趟时长。

### 5.2 实时数据流

```text
USB Python 读取线程 → 协议解析 / 组帧 / 布局映射
  → sensor_frame_received(SensorFrame) + acquisition_issue
  → QueuedConnection → DeviceQualitySession（Qt Worker 线程）
  → 原始帧保留；冻结屏蔽点生成处理帧，不确定区间切断事件连续性
  → GaitEngine.process_quality_frame → 单段 processor / OvergroundSession
  → 事件 / 低频快照 / FootprintVisualFrame
  → SessionController → 主线程 ExecutionView

测试结束 → 停止处理与 USB、退出采集线程
  → build_report(engine, reason) → 不可变的模式专属报告
  → session_finished → MainWindow → ReportView + SubjectStore 归档
```

`DeviceLayout` 保存每段线序、方向、光束位置和有效位掩码；`SensorFrame` 同时保存原始载荷、物理顺序遮挡、质量标志和设备帧号。五种正式硬件模式的接触计时采用设备序号；主机接收时间用于延迟和超时诊断，定时停止仍由会话时钟管理。显式模拟/兼容接触入口保留原有时间基准。

短暂缺帧、无效数据、接触邻近屏蔽点或新增疑似持续遮挡/高频变化会切断事件连续性，不补造指标。运行中不改变屏蔽清单，也不因光学异常程度自动结束；设备断连、布局/流变化、计数回退或持续 1 秒无数据仍结束测试。原始帧保持采集值，地面缓存受 600000 帧及约 64 MiB 预算限制；历史库保存质量快照和回放，不永久保存全速原始帧。完整采样审计应在本次报告页导出，不能把历史回放当成全速原始数据。

`beam_quality` 保存冻结阈值、位置、类型、人工确认和运行中事件，进入报告、历史、Excel 设备质量表以及已支持模式的 Report Agent 质量标记。新增模式必须复用该契约，不能仅使开始按钮可点击。

地面走路以接触中心为距离参考；地面跑步以稳定脚尖代理计算 Tip-to-Tip。空间信息不足时保留缺失原因，不补零或改用另一种参考。配置未指定首脚或身份失效后仅保留 A/B，不能视作独立视觉识别的左右脚。详见 [采集接口](采集数据接口.md)、[地面走路](地面走路算法.md) 和 [地面跑步](地面跑步算法.md)。

### 5.3 受试者选择与配置回填

```
SetupView 受试者搜索/选择
  → _refresh_subject_results(query)
  → SubjectStore.search_subjects()

"加载上次参数"
  → SubjectStore.get_last_session(subject_id)
  → param_panel.set_config(session.config)

Agent 生成配置 (AgentConfigPanel)
  → config_confirmed(模式配置)
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
  → Release Gate 校验后的 Deterministic RAG（文献建议，可独立降级）
  → AnalysisPackage 原子持久化
  → ReportView 展示只读结果
```

正式报告先于智能分析生成；模型不可用、超时或 Claim 被拒绝都不会改变已有报告。当前只分析本次 session，支持纵跳、跑步机步态/跑步；地面报告、个人历史纵向和团队横向分析尚未开放。跑步机步态页面另提供 `reporting/gait_insights.py` 本地专项问答，直接引用报告明细，不调用 LLM。

### 5.5 语音与 RFID

```text
麦克风 → 本地 AEC3 → 豆包 ASR → Pipecat 语音进程
  → JSON 行 IPC → ui/voice_bridge.py（Qt 主线程）
      ├─ 控制命令 → SessionController → 执行确认
      ├─ 配置请求 → AgentConfigPanel → 原有 Config Worker → 用户确认配置
      └─ 报告请求 → 本地步态问答或 Report Worker → 已验证回复
  → JSON 行 IPC → 豆包 TTS → 播放队列 → 扬声器
```

控制命令不经过 LLM，仅处理最终分句并校验当前业务状态；插话取消旧播报、丢弃过期语音回复。语音断连停止语音进程，手动测试入口继续可用。默认关闭麦克风，用户点击后才启动服务。实际播放 PCM 同时作为 AEC3 回声参考，详细协议与验收见 [语音说明](../voice/README.md)。

主界面的主操作区以 `QStackedWidget + VoicePanel` 纵向排列，语音栏独立于页面切换且不可浮动。地面测试和报告额外显示右侧全高跑道栏，跨越主操作区与语音栏两行；其他模式隐藏该栏并恢复原布局。`VoiceBridge` 更新可见识别/回复与诊断；配置请求成功提交时显示现有助手对话，报告问答使用现有证据区域。停止播报发送 `interrupt` 消息、推进语音轮次并取消播放，不关闭采集；关闭语音后忽略迟到识别事件。地面模式的暂停/继续请求在业务路由处拒绝，开始请求提示操作者核对段数并点击确认按钮。

`GroundTrackPanel` 共享地面自检、实时和回放的连续跑道绘制；`positions_m` 决定刻度与落脚位置，96 路对应一个可选设备段。段边界仅在侧边标注，不将跨段接触切成多只脚。旁侧详情按所选段切片显示光束、有效位和段内异常编号。全程与局部均复用 `FootprintChannelWidget` 的双侧灯点、圆角通道、遮挡线和足迹绘制，局部显示所选段 96 路及当前脚印；历史标记只来自已完成且有效的接触，报告按播放时间过滤。左右脚复用 `left_foot.png` / `right_foot.png` 和原有足迹绘制逻辑，历史脚印淡化，总览保留最低可辨尺寸；未知左右脚仍居中匿名显示。图标大小不代表实测足长或足底压力。

准备阶段约 10 Hz 发布光束与有效位状态，不把 1000 Hz 原始帧直接送到 UI。沿用的 `ground_start_requested` 信号现供五种模式携带布局/流、阈值、坏点清单和确认结果；`arm_checked` 在处理线程复核。不可用光束以未知状态显示，接触证据不足时清除旧脚印；有效且远离坏点的脚印继续显示。历史回放使用自己的质量快照，不随当前设置改变。

`hardware/rc200u.py` 在线程中轮询厂商 DLL，`AthletesView` 在主线程处理卡号；`SubjectStore` 保存唯一绑定并支持解绑。读到 UID 后选择对应档案，不替用户选择团队身份或启动采集。Windows 已有单卡及页面/数据库联调记录，完整主窗口和热插拔仍需验收。

## 6. 线程与进程模型

| 执行域 | 职责与边界 |
| --- | --- |
| Qt 主线程 | 所有 Widget、SessionController、报告展示、语音业务路由 |
| USB Python 读取线程 | 协议解包、完整帧输出；旧单段 DirectConnection 回调在该线程同步执行 |
| 采集 QThread | UsbWorker/GaitEngine 的 Qt 事件循环；地面帧、异常与布防命令串行入队，避免就绪复核竞态 |
| Agent Worker 进程 | Config/Report 路由、模型调用、分析持久化；UI 请求线程仅做 HTTP 转发 |
| 语音 Worker 进程 | Pipecat 异步任务、ASR/TTS 连接、音频回调与 AEC3 |
| 相机 / RFID 工作线程 | 采集或轮询，结果通过信号回到主线程 |

**关键约束**：

- `SessionController.prepare()` 创建或复用设备对象，先设置线程归属，再连接信号。准备阶段已启动线程，不在点击开始时重复启动。
- DirectConnection 不会自动切到接收对象所属线程，不能把 USB 回调误写成 Qt Worker 事件。
- 生成报告前停止帧处理、USB 和采集线程；地面模式先在其线程执行 `halt`，再释放资源。

## 7. 参数配置系统

参数最终转换为 `AnyTestConfig` 对应的模式 dataclass，并通过 `validate_runtime_config()`。手动入口覆盖全部五种模式；离线规则与在线 Config Agent 当前覆盖纵跳、跑步机步态和跑步机跑步：

| 方式 | 入口 | 说明 |
|:---|:---|:---|
| **手动配置** | `ParamPanel.get_config()` | Schema 驱动的动态表单 |
| **规则引擎** (离线) | AgentConfigPanel 离线建议入口 | 按 AthleteProfile 自动推荐 |
| **LLM** (在线) | AgentWorkerClient → ConfigService | 自然语言对话 → 模式专属结构化输出 → 确认后应用 |

### 参数分层 (来自 Iron_parameters.json)

| Layer | 内容 | 示例 |
|:---|:---|:---|
| 1 | 测试类型选择 | test_macro_type, test_type |
| 2 | 主配置参数 | stop_type, number_of_jumps, test_length |
| 3 | 滤波参数 | min_contact_time, min_flight_time, max_flight_time |
| 4 | 可选反馈 | metronome_enabled, metronome_bpm |

### 参数联动规则

- 纵跳 `stop_type = "Status change"` → `number_of_jumps` 和 `finish_position` 可见；地面模式使用自己的出口结束规则
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

- 1 组一致 → 稳定选择该组首个有效代表，转模式配置并校验后输出
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

地面走路与跑步沿用同一链路，分别使用 `LLMWalkingConfig` / `LLMOvergroundRunningConfig` 和独立 Prompt，转换成 `WalkingConfig` / `OvergroundRunningConfig`，再经统一运行时校验。两者仅暴露 `stop_type`、`starting_foot` 与固定类型判别字段，拒绝额外字段；设备段数由硬件识别，检测阈值使用各模式运行时默认值，不套用纵跳档案规则。

`agent/config/modes.py` 统一声明五种配置模式；UI 选定模式后，语音转写与打字共用 ConfigService 和确认流程。模式选择不由自然语言自动切换。地面 Prompt 对跨模式或当前不支持的时长/距离要求进行解释与澄清，代码拒绝未知模式及跨模式结构化输出。切换模式期间到达的旧回复仅归入原对话，不恢复待确认配置或播报为当前建议。

### 8.4 规则引擎

`PROFILE_RULES` 是 `list[tuple[Callable, dict]]`，数据驱动。多规则命中同一字段时取最保守值（`min_contact→MAX`, `number_of_jumps→MIN`, `max_flight→MIN(非零)`），与规则添加顺序无关。

### 8.5 Report Agent 可信边界

- `TestReport` 是不可变事实源；Builder 只能转换和补充稳定引用，不能改变正式结果。
- Agent 只能从 `AnalysisToolRegistry` 选择已启用 Tool，并从 `AnalysisMethodRegistry` 选择该 Tool 所属的确定性分析方法；不能访问通用 SQL、任意 Python 或原始 1000Hz 数据。
- 生产 `ActionValidator` 按测试类型、数据范围、参数和预算校验每个动作；`PlanValidator` 保留旧 DAG 兼容用途。
- Kernel 负责所有聚合、分组、趋势、敏感性和跨指标比较；模型不得自由计算正式数值。
- 每个 Claim 必须绑定 Fact、Evidence Ref、Predicate 和 Numeric Binding。错误数字、无证据结论、越权范围、因果或医学语言由 Validator 拒绝。
- 生产使用 `AnalysisSketch + Compact Series` 和按需 Skill 加载，最多 5 次 Tool 调用、3 次 Reference 加载、9 个 Agent 决策步骤。旧 DAG 的 Screening Cues/Replan 为实验选项。
- 服务端默认总预算 90 秒、预留 20 秒综合；客户端默认 105 秒。超时返回结构化错误，保存 Checkpoint/partial metrics 后以 failed 结束，不显示部分 Draft；终止运行不恢复，重试创建新 Run。

### 8.6 RAG 发布与降级

`knowledge` 在 Claim 校验后执行确定性 QueryPlanner、元数据硬过滤、FTS5 + Dense 检索与 RRF 合并，再生成文献建议。引用由代码依据 Evidence 构造，文献不能代替本次测试数值的证据。Schema v4 增加建议、文献引用与审计，同时兼容旧报告读取。

Planner/Retriever 1.1 增加地面场景限制：QuerySpec 的 `protocols` 同时约束 Dense 候选和 FTS5 候选；地面走路仅接受 `overground_walk`，地面跑步仅考虑地面/跑台对比或地面跑步协议，仍须满足推荐许可等所有原有过滤条件。目前地面跑步无获准来源，返回 `no_supported_query`；有查询但无命中时返回 `no_matching_evidence`。规划异常返回 `planning_failed` 降级审计。

旧 `v1_release_gate.json` 的启用标志仍为 true，但旧冻结审查工件只覆盖 1.0；2026-09-26 升级后的 `v1_release_status()` 为 `invalid`。需重新完成真实生成与人工审查并 promotion，不能改写旧工件冒充通过。生产建议暂不启用，确定性分析继续保留。验证记录见 [RAG 验证记录](rag_validation.md)。

地面检索规划已具备协议隔离，但 `reporting.models.TestType`、`ReportDataPackageBuilder` 和报告 UI 智能分析入口仍仅支持纵跳与两种跑台模式。地面报告进入完整 RAG 前必须补齐确定性报告适配及其验证，不能将地面模式重命名为跑台模式绕过限制。

### 8.7 用户、团队与分析数据范围

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
| **dayu_widgets** | requirements.txt 固定 1.1.1 | 按项目依赖安装 |

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

## 11. 当前验证边界

2026-09-26 合并基线 `86ff8ae` 已在 macOS / Python 3.11.15 / Qt offscreen 下通过全量自动化回归：1048 项测试、12 项子测试。详细状态与历史实验见 [项目计划](../plan.md)。

多段地面算法仍需真实布局标定和同步真值；语音仍需真人口令、插话及 Windows 声卡验证；RC200U 的实机单卡和页面业务验证不替代完整主程序验收。Mac MediaPipe 验证器只检查解剖左右腿身份连续性，Windows Vision Session 工具用于录制、标注与 Replay，两者均未将视觉标签写回主测试报告。
