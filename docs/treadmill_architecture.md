# 跑步机模式架构文档

> 基于 Iron_Jump 系统架构，新增 Treadmill Gait Test 和 Treadmill Running Test 两类测试模式。
> 最后更新: 2026-09-26；代码基线: `86ff8ae`

## 1. 模式概述

跑步机模式下，OptoJump 光栅条安装在跑步机**两侧**。受试者总体位置相对光栅条固定，带速由操作者手动输入。

与地面步态的关键差异：跑带速度提供测试期间的基础位移，但受试者会在光栅区域内前后漂移，因此距离不能只用带速反算。当前实现将跑带位移与相邻触地参考点的位置变化结合；LED 空间信息参与步长和步幅修正，也继续用于触地/腾空时序、toe/heel 方向、足长过滤和左右脚判定。

当前跑步机仍使用单段 `raw_contact_signal` 兼容通道。地面走路/跑步已通过 `OvergroundSession` 接入完整多段 `SensorFrame`，按设备序号计时；该扩展不代表跑步机已支持多段，也不改变本文件的跑带速度语义。共同线程与数据边界见 [系统架构](architecture.md)。默认步态速度为 3.0 km/h，默认跑步速度为 6.0 km/h。

支持两种测试类型：

| 类型 | 说明书名称 | 说明 |
|:---|:---|:---|
| `Treadmill Gait Test` | Treadmill Gait Test | 跑步机步态分析，含 `min_step_length` 和 `automatic_data_filter` |
| `Treadmill Running Test` | Treadmill Running Test | 跑步机跑步分析，含 `min_gap_between_feet` |

## 2. 分层架构

```
┌─────────────────────────────────────────────────┐
│ UI 层 (Qt)                                       │
│  main_window.py → views/                         │
│  session_controller.py (经 build_report wrapper 委托) │
├─────────────────────────────────────────────────┤
│ 配置层                                           │
│  test_config.py (AnyTestConfig 类型别名)          │
│  ├── TestConfig (纵跳, 保持不变)                  │
│  ├── treadmill_config.py (TreadmillGaitConfig,   │
│  │     TreadmillRunningConfig)                   │
│  └── treadmill_report.py (MetricSummary,         │
│        TreadmillStepResult, TreadmillReport)     │
├─────────────────────────────────────────────────┤
│ 算法引擎层 (L2) — GaitEngine(facade)              │
│  ├── engine/modes/base.py (ModeProcessor 协议)    │
│  ├── engine/modes/jump_processor.py (迁出或包裹现有纵跳) │
│  ├── engine/modes/treadmill_processor.py          │
│  │     (聚类→触地/腾空检测→累积器)                  │
│  └── engine/modes/treadmill_accumulator.py        │
│        (逐步结果累积、过滤、统计、起始脚解析)        │
├─────────────────────────────────────────────────┤
│ 硬件通信层 (L1) — 跑步机使用单段兼容通道           │
│  usb_worker.py + protocol.py                     │
├─────────────────────────────────────────────────┤
│ 数据持久化层                                      │
│  subject_store.py (新增 measured_foot_length_cm,  │
│    report_detail_json, report_summary 分支)       │
└─────────────────────────────────────────────────┘
```

**关键约束**:
- 跑步机 processor 不 import Qt，在 Worker 线程中运行
- 所有模式通过 `GaitEngine(facade)` 统一访问，UI/Controller 不感知具体 processor
- `SessionController` 保留公共生命周期接口；地面模式的连续自检和布防另有明确分支，跑步机仍复用原有准备/开始/暂停/结束路径
- 跑步机配置字段名与 `Iron_parameters.json` 和 Jump `TestConfig` 的公共字段保持一致；模式专属字段只放在对应 treadmill config 中

### 2.1 配置与结果单位契约

配置字段名不带单位后缀，单位由 schema / Pydantic `Field` 明确声明；结果字段保留单位后缀，避免报告计算时混用。

| 字段 | 单位 / 格式 | 使用约束 |
|:---|:---|:---|
| `test_length` | `mm:ss` 字符串 | 说明书范围 `00:01-59:59`；算法层通过 `get_test_length_seconds()` 转为秒。 |
| `treadmill_speed` | `km/h` | 跑带基础速度输入；算法层用 `/ 3.6` 转为 `m/s`，并结合足部参考点位置变化计算距离。 |
| `min_contact_time` / `min_flight_time` / `max_flight_time` | `ms` | 与结果 `contact_time_s` / `flight_time_s` 比较前必须除以 `1000`。 |
| `min_foot_length` / `min_step_length` / `min_gap_between_feet` | `cm` | 均为算法过滤阈值，不等于受试者足长快照。 |
| `filter_gaitr_in` / `filter_gaitr_out` | LED 数 | GaitR 进入/离开接触状态的 LED 阈值。 |
| `automatic_data_filter` | `%` | gait 专用；`0` 表示关闭，`10-90` 表示均值上下百分比阈值。 |

结果字段后缀约定：`_s` 表示秒，`_cm` 表示厘米，`_m_s` 表示米/秒，`_steps_per_s` 表示步/秒，`_percent` 表示百分比。

## 3. 新增/修改文件

### 3.1 新增文件

| 文件 | 职责 |
|:---|:---|
| `config/treadmill_config.py` | 跑步机枚举、`TreadmillGaitConfig`、`TreadmillRunningConfig`(frozen dataclass)、`TreadmillSessionContext`、`get_test_length_seconds()`、`_is_mmss()` |
| `config/treadmill_report.py` | `MetricSummary`、`summarize()`、`TreadmillStepResult`、`TreadmillGaitReport`、`TreadmillRunningReport` |
| `engine/modes/__init__.py` | 模式包入口 |
| `engine/modes/base.py` | `ModeProcessor` 协议 (Protocol)：`name`、`display_mode`、`reset()`、`process_raw_frame()`、`build_report()` |
| `engine/modes/jump_processor.py` | 从 `GaitEngine` 迁出或先以 legacy adapter 包裹的纵跳处理器，行为不变 |
| `engine/modes/treadmill_processor.py` | 跑步机处理器：聚类→触地/腾空事件→累积器→build_report |
| `engine/modes/treadmill_accumulator.py` | 逐步结果累积：行状态标记、起始脚解析、阈值过滤、automatic_data_filter、MetricSummary 生成 |
| `tests/test_treadmill_config.py` | 跑步机配置校验 + schema 过滤测试 |
| `tests/test_treadmill_report.py` | 跑步机报告 + MetricSummary + report view 行转换测试 |
| `tests/test_treadmill_processor.py` | 累积器 + processor + 距离反算测试 |
| `tests/test_mode_runtime.py` | GaitEngine facade 模式分发测试 |

### 3.2 修改文件

| 文件 | 修改方式 |
|:---|:---|
| `config/test_config.py` | 新增 `AnyTestConfig` 类型别名 + `config_from_dict()` 工厂函数 |
| `config/test_report.py` | `TestReport` union 扩展；`build_report()` 委托 `engine.build_report()` |
| `config/Iron_parameters.json` | 拆分 `min_step_length` / `min_gap_between_feet` 适用 test type |
| `config/param_schema.py` | 复用 `get_visible_params(test_type, values)` 按模式和联动条件过滤 |
| `engine/gait_engine.py` | 缩为 facade：`mode`/`processor_name`/`build_report()` 委托 processor；模式选择路由 |
| `ui/session_controller.py` | 生命周期不按模式复制；`prepare()` 增加模式无关 `session_context` 透传，用于冻结足长等会话输入 |
| `ui/param_panel.py` | 按当前 test type 调用 `get_visible_params()` 渲染；构建 config 用 `config_from_dict()` |
| `ui/views/report_view.py` | 新增 `_load_treadmill_report()` 分支 |
| `data/subject_store.py` | 新增 `measured_foot_length_cm` 列、`report_detail_json` 列、`_report_summary()` treadmill 分支 |
| `agent/models.py` | 新增 `LLMTreadmillGaitConfig` / `LLMTreadmillRunningConfig` (Phase 1 先做结构预留) |
| `agent/llm_agent.py` | 按 test type 选择 prompt (Phase 1 先不开放跑步机 LLM 入口) |

## 4. 核心数据流

### 4.1 测试生命周期

```
用户选择 Treadmill Gait/Running Test + 配置参数 + 受试者足长快照
  → SetupView.ready_signal.emit(SessionSetup)
  → MainWindow._on_ready(setup)
      → 冻结 foot_length_cm_snapshot / foot_length_source
      → SessionController.prepare(config, session_context)
          → 创建 QThread + UsbWorker + GaitEngine(config, session_context)
          → GaitEngine 根据 config.test_type 选择 TreadmillProcessor
          → moveToThread → 连接信号 → 切到 ExecutionView

用户点击"开始"
  → SessionController.start() → thread.start()
  → [若配置自动停止] 倒计时结束 → engine 发射 test_finished

用户点击"停止" (或自动停止触发)
  → SessionController.stop()
      → _do_stop(): 标记 engine 完成 → worker.stop() → thread.quit()/wait()
      → build_report(engine, reason) 兼容 wrapper
          → engine.build_report(reason)
              → processor.build_report() → TreadmillGaitReport / TreadmillRunningReport
      → session_finished.emit(report)
  → MainWindow → ReportView._load_treadmill_report(report)
      → SubjectStore.record_session() 归档
```

### 4.2 实时帧处理流

```
后台线程:
  UsbWorker.raw_contact_signal
    →[DirectConnection]→ GaitEngine.process_raw_frame()
        → TreadmillProcessor.process_raw_frame(contact_bits, rel_time, abs_time)
            → extract_clusters(bits) → 空间聚类
            → foot candidate classification (foot_length_cm_snapshot + direction)
            → 触地/腾空事件检测
            → TreadmillAccumulator 累积 step rows
    →[QueuedConnection]→ SessionController → ExecutionView (实时事件)
```

### 4.3 停止与报告生成

```
停止触发 (手动 stop / End of Time 自动停止)
  → [自动停止] engine.test_finished.emit(reason)
  → [自动停止] SessionController._on_engine_finished() → 200ms 延迟 → stop()
  → SessionController._do_stop(reason)
      → 标记 engine 完成 → worker.stop() → thread.quit()/wait()
      → build_report(engine, reason) 兼容 wrapper
          → engine.build_report(reason)
              → processor.build_report(reason, export_frames, export_timestamps)
                  → accumulator.finalize()
                      → 应用阈值过滤 → 标记 row_status
                      → [gait] 应用 automatic_data_filter
                      → 生成 metric_summaries (min/max/mean/std/CV)
                  → 构造 TreadmillGaitReport / TreadmillRunningReport
      → session_finished.emit(report)
```

## 5. 模块接口

### 5.1 ModeProcessor 协议

`__init__` 不在 Protocol 中约束，但所有 processor 约定接收 `(config, session_context)`，由 `GaitEngine` 在构造时传入。

```python
class ModeProcessor(Protocol):
    name: str              # 内部 ID: "jump" / "treadmill_gait" / "treadmill_running"
    display_mode: str      # 中文显示: "纵跳" / "跑步机步态" / "跑步机跑步"

    def reset(self) -> None: ...
    def process_raw_frame(self, contact_bits: list[int], rel_time: float, abs_time: float) -> list[object]: ...
    def build_report(self, reason: str, export_frames: tuple, export_timestamps: tuple) -> TestReport: ...
```

### 5.2 多态配置类型

```python
# config/test_config.py
AnyTestConfig = Union[TestConfig, TreadmillGaitConfig, TreadmillRunningConfig]

def config_from_dict(data: dict[str, Any]) -> AnyTestConfig:
    """根据 test_type 分发构造对应配置对象。所有字段名与 JSON/UI 一致，无需映射。"""
```

### 5.3 跑步机会话上下文

`foot_length_cm_snapshot` 不属于测试前算法阈值配置，而是运动员/会话输入。它应在测试开始前从运动员档案或人工输入冻结，报告中保留快照，避免历史结果随档案更新而变化。`starting_foot_override` 同理，是会话级的起始脚人工覆盖，不属于算法配置。

```python
TreadmillSessionContext:
    measured_foot_length_cm: float | None  # 从受试者档案读出的长期记录值（DB 来源）
    foot_length_cm_snapshot: float | None  # 本次测试冻结的足长（复制自 measured 或人工输入）
    foot_length_source: Literal["captured", "manual", "unknown"]
    starting_foot_override: Literal["left", "right"] | None  # 人工覆盖起始脚
```

`foot_length_cm_snapshot` 是本次测试算法实际使用的值；`measured_foot_length_cm` 是档案值，用于下一次加载时预填。`SessionController` 把 `TreadmillSessionContext` 作为 session metadata 传入 `GaitEngine` / processor；不要把它和 `min_foot_length` 合并。

### 5.4 TreadmillReport 结构

```python
# 逐步结果
TreadmillStepResult:
    index, side, row_status, is_event_valid, is_included_in_statistics,
    correction_source, event_invalid_reason, statistics_exclusion_reason,
    time_s, distance_cm, contact_time_s, flight_time_s, step_time_s,
    gait_cycle_s, step_length_cm, stride_length_cm, speed_m_s, cadence_steps_per_s,
    # 步态扩展: double_support_s, single_support_s, stance_phase_s, swing_phase_s, ...
    # 跑步扩展: imbalance_percent

# 报告
TreadmillReportBase:
    finish_reason, touch_count, lift_count,
    foot_length_cm_snapshot, foot_length_source,
    resolved_starting_foot, starting_foot_source,
    per_step_results, metric_summaries,
    left_right_results: dict[str, MetricSummary],
        # 左右脚拆分统计: {"left": MetricSummary(...), "right": MetricSummary(...)}
        # 每个 MetricSummary 聚合该侧的 contact_time_s、step_length_cm 等核心指标
    asymmetry_metrics: dict[str, float],
        # 不对称性指标: {"step_length_asymmetry_percent": 3.5, ...}
        # 按 (|left - right| / max(left, right)) * 100 计算
    report_config_snapshot, export_frames, export_timestamps
```

### 5.5 距离/速度计算

```text
speed_m_s = treadmill_speed / 3.6
belt_displacement_cm = speed_m_s * interval_s * 100

step_length_cm
  = 相邻异侧触地间的跑带位移
  + 按行进方向修正的前后参考点位置变化

stride_length_cm
  = 同侧两次触地间的跑带位移
  + 按行进方向修正的同侧参考点位置变化

cadence_steps_per_min = 有效触地步数 / 有效采集时长 * 60
```

参考点由配置选择 `Tip-to-Tip` 或 `Heel-to-Heel`。步幅的权威记录来自同侧两次触地形成的完整 `GaitCycleRecord`，不能使用 `step_length × 2` 近似，也不能只用带速乘周期时间。缺少可靠参考点、完整同侧周期或方向语义时，不生成伪步幅；旧报告中的近似字段只用于兼容读取，不作为正式显示依据。

### 5.6 报告统计与展示

- 概览按模式选择约 9～12 个高优先级指标，不为填满布局展示空值。
- 跑步机步态优先展示步长、步幅、步频、步态周期、接触时间、支撑相、摆动相和双支撑时间；样本满足门槛时再显示不对称性。
- 明细页分为“统计汇总 / 周期明细 / 逐步数据”三个内部分页。
- 周期与逐步表支持“已纳入 / 已排除 / 全部”筛选；Excel 仍导出完整数据和排除原因。
- 时间类概览中步态周期使用秒，接触/腾空/双支撑时间使用毫秒，支撑相和摆动相使用周期百分比。

### 5.7 起始脚解析

```text
1. starting_foot_override 存在 → 采用人工覆盖 (source=manual_override)
2. START 后第一只触地脚 → 起始脚 (source=auto_first_contact)
3. START 时双支撑 → 用 direction 判断跑步机前方脚 (source=auto_double_support_front)
4. 测试后人工修正 → 更新 resolved_starting_foot (source=manual_correction)
```

## 6. 线程模型

与现有架构一致，跑步机 processor 在 Worker 线程运行：

```
┌─────────────────────────────────────────────────┐
│ 主线程 (GUI)                                      │
│  MainWindow, ExecutionView, ReportView,           │
│  SessionController                                │
└──────────────┬──────────────────────────────────┘
               │ QueuedConnection (低频 ~2-5Hz)
┌──────────────▼──────────────────────────────────┐
│ Worker 线程 (QThread)                             │
│  UsbWorker → GaitEngine(facade)                   │
│    → TreadmillProcessor.process_raw_frame()       │
│    → TreadmillAccumulator                         │
│  DirectConnection (高频 1000Hz)                   │
└─────────────────────────────────────────────────┘
```

## 7. 关键设计决策

| 决策 | 结论 | 原因 |
|:---|:---|:---|
| **速度/距离来源** | 从 `treadmill_speed` 反算，不用 LED 位移 | 跑步机上人体相对光栅条位置固定，LED 空间位移不代表真实步长 |
| **Processor 独立新建** | 跑步机 processor 不与纵跳/地面步态共用 | 算法输入不同（带速、方向、无空间位移），强行复用会污染两种模式 |
| **GaitEngine 改 facade** | 保留 Qt signals + 导出缓存，算法委派 processor | UI/Controller 层不感知模式切换；支持未来继续扩展 |
| **SessionController 不按模式复制** | 只增加通用 `session_context` 透传 | 生命周期（prepare/start/stop/pause）与模式无关，但跑步机需要冻结足长等会话输入 |
| **字段名与 JSON Schema 对齐** | 公共字段名统一：`min_contact_time`、`test_length` 等 | 消除映射层，Pydantic 模型可继承公共字段；新添模式时零摩擦复用 |
| **test_length 保留 mm:ss 格式** | `str\|None`，与 Jump TestConfig 一致 | `ParamPanel` 和 `Iron_parameters.json` 统一字段名和类型 |
| **Suspended 状态预留** | `RowStatus` 含 `suspended`，Phase 1 不生成 | 说明书支持暂停-恢复，先留枚举值，后续实现时不改 schema |
| **Phase 1 不接入 Gyko/IMU** | 纯光栅 MVP | Gyko 属扩展分析，非跑步机核心 |
| **Agent 先做结构预留** | prompt/model 文件创建，UI 入口暂不开放 | 降低 Phase 1 复杂度，聚焦配置+算法+报告主链路 |
| **不混入 BioFeedback** | 独立训练模式，不保存测试结果 | 与正式检测模式生命周期不同 |

## 8. 常见陷阱

1. **不要用 LED 空间位移计算距离** — 跑步机上人体不前进，step_length 必须从 treadmill_speed × step_time 反算
2. **不要混淆 `direction` 含义** — 跑步机 direction 表示行走方向相对接口鼓位置（`Interface side`/`Opposite side`），不是地面步态的 entry point
3. **不要给跑步机 processor 传纵跳配置** — `GaitEngine` 根据 `config.test_type` 路由 processor，错误的 test_type 会导致 processor 读不到 `treadmill_speed`
4. **不要省略 `foot_length_cm_snapshot`** — 跑步机模式下足长快照参与 toe/heel 参考点计算和簇分类，缺少它会导致左右脚判定不稳定
5. **不要在 `build_report()` 中读 engine 私有字段** — 改为委托 `engine.build_report()` → `processor.build_report()`
6. **跑步机报告不要套用 `GaitTestReport`** — 跑步机有独立的 `TreadmillGaitReport` / `TreadmillRunningReport`，含逐步结果、有效性和 MetricSummary
7. **`stop()` 必须在 `build_report()` 之前停线程** — 否则 accumulator 中的 row 数据可能被并发修改
