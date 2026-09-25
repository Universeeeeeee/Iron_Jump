# 步态与语音验收

## 本地运行

使用 Python 3.11，安装 `requirements-dev.txt`；语音部分另装 `requirements-voice.txt`。
运行 `python -m tools.check_runtime` 检查基础依赖，再运行 `python -m ui.demo`。
演示默认提供步态手动配置、独立数据库和明显的模拟数据标识，不调用云服务。

1. 选择临时测试或演示受试者，确认配置，进入准备页。
2. 开始采集至少 15 秒；暂停，确认计时与数据停止变化；继续。
3. 结束后检查周期、支撑/摆动阶段和足印回放。
4. 在“步态专项问答”询问左右差异、稳定性、前后变化与排除数据；点击证据编号进入对应明细。
5. 返回历史记录，重新打开同一报告，检查模拟标识与回放。
6. 导出 Excel，检查周期/逐步数据及“数据来源”工作表。

模拟器生成交替 600 ms 接触、400 ms 摆动的 96 路原始信号；算法滤波会带来数毫秒偏差。
固定足印仅验证接触时序，不模拟真实人体运动，也不验证硬件测量精度。

## 统计口径

- 周期与逐步记录分开统计；侧别比较每侧至少 3 个有效样本。
- 稳定性报告总体标准差和 CV，不自行设置“正常/异常”阈值。
- 前后段按完整周期覆盖时间范围的中点划分；跨中点记录排除，各组至少 3 条。
- 分段不对称率要求每段每侧至少 3 个有效周期；公式为左右均值差绝对值除以两侧均值平均值。
- 暂停切断尚未完成的接触和周期配对；暂停时长不计入采集时间。暂停前后完整数据仍可比较，但不用于推断原因。
- 缺失值、非有限值与排除记录不参与计算；零值保留，零分母不计算比率。
- 变化幅度排名使用前半均值为基准的相对变化，仅比较本页可计算的指标，不代表临床重要性。
- 问答由确定性计算生成，证据来自当前报告；不做疲劳、疾病或因果判断。

## 离线自动验证

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  tests/test_gait_demo.py tests/test_gait_insights.py \
  tests/test_subject_store.py tests/test_treadmill_processor.py \
  tests/test_treadmill_report.py tests/test_gait_cycle.py tests/test_mode_runtime.py \
  tests/test_session_controller_lifecycle.py tests/test_voice_clients.py \
  tests/test_voice_pipeline.py tests/test_voice_protocol.py tests/test_voice_session.py \
  tests/test_report_view_footprint.py tests/test_main_window_navigation.py \
  tests/test_execution_view_footprint.py
```

2026-09-16：新增原始信号 → 真实引擎 → Qt 控制 → SQLite 保存/重开验证；
专项问答覆盖对称、非对称、恒定、变化、缺失、零值与暂停数据，另验证证据定位和 Excel 模拟标识。
基础依赖检查已通过。既有速度默认值测试仍期待单一 3.0，现已按参数定义区分
步态 3.0 和跑步 6.0，未修改运行参数。完整回归通过 819 项测试和 12 项子测试；
后续增加无完整周期时仍能回答有效步频的边界测试，单独验证专项问答。
界面已使用离屏 Qt 启动并渲染检查；未将此记为真实麦克风或设备验证。

## 本轮复验（2026-09-22）

- 当前工作区完整回归：835 项测试、12 项子测试通过（24.11 秒）；保留两项既有警告。
- 此后新增单次会话集成测试 `test_voice_gait_session_persists_answers_and_exports`，单独通过（9.46 秒）。
  从 ASR 最终文本事件入口执行准备、开始、重复开始、暂停、继续、结束，使用模拟原始信号和真实引擎；
  检查暂停期间帧数不增加、结束后采集线程释放、仅保存一份报告、暂停边界持久化。
  再通过历史报告入口重开，验证左右差异、步频稳定性、前后变化和追问的语音回复与页面正文一致，
  并实际导出、读取 Excel，确认模拟数据来源标识。模态导出确认由测试自动回答。
- `python -m voice --check` 与 `python -m tools.check_runtime` 均通过。
- 增加两项本地真实 WebSocket 传输测试，语音客户端共 4 项通过（0.09 秒）。
  使用 aiohttp 本地服务端在 ASR 协议握手后强制断开 TCP，确认客户端报告断连；
  在 TTS 等待音频期间取消任务，由服务端确认连接关闭。使用虚构凭证，不访问云端。
  这覆盖客户端传输行为，不替代应用整体断网和真实声卡释放验收。
- 生产 `run_worker` 编排新增 3 项测试通过（0.24 秒）：播报中收到 stop、stdin EOF、ASR 断连。
  使用真实 Pipecat runner，检查合成任务取消、播放队列清空、ASR 关闭和音频流上下文退出；
  服务和声卡由测试替身提供，未证明物理设备释放。
- 新增集成测试直接注入识别文本，不连接 ASR/TTS，不录音，也不证明真实语音、云端分析模型或 Windows USB 验收通过。

## 云端智能配置复验（2026-09-22）

使用虚构档案（30 岁、70 kg、175 cm）调用现有 ConfigService 的 treadmill_gait 模式，
实际发现软件命令结束配置被转换时丢失必填但可为空的 test_length，产生 TypeError。
步态、跑步模型均可由离线测试复现；修复为显式传递该字段，相关 24 项测试通过。
修复后重新实际调用云端，2.15 秒返回 TreadmillGaitConfig，速度 3.6 km/h、
Software command、test_length=None，运行参数校验无错误。
这是服务层配置实测，不是麦克风到 UI 确认的全链路验收，也未验证云端报告分析。
仅使用本地配置的凭证，未将凭证或服务端原始错误写入验收记录。

## 云端回环实测（2026-09-16）

已使用同一豆包语音 API Key 实际调用 ASR 2.0 和 TTS 2.0，合成音频以实时节奏送入 ASR。
服务地址、资源 ID、鉴权头及默认音色已核对官方文档。Key 仅保存在 Git 忽略的本地 `.env`，
该文件权限为仅当前用户读写；文档不记录其值。

| 指令 | 最终识别 | 结果 | TTS 首包 ms | 从音频发送开始到 ASR 最终结果 ms |
| --- | --- | --- | ---: | ---: |
| 开始测试 | 开始测试 | 通过 | 635 | 1705 |
| 暂停测试 | 暂停测试 | 通过 | 561 | 1938 |
| 继续测试 | 继续测试 | 通过 | 574 | 1780 |
| 结束测试 | 结束测试 | 通过 | 547 | 1704 |

以上为一次合成音频回环，不是识别准确率基准，也不是“人说完话到实际播音”的延迟。
本机音频枚举已发现 MacBook Air 麦克风与扬声器；枚举成功不等于实际录音/播音验收通过。

官方参考：[ASR 流式识别](https://docs.volcengine.com/docs/6561/2630027?lang=zh)、
[TTS 双向流式合成](https://docs.volcengine.com/docs/6561/2532486?lang=zh)。

## 待现场联调（尚未通过）

2026-09-16 接入 `pywebrtc-audio==0.2.0`（WebRTC AEC3）。本机 ARM64 预编译包约 367 KB。
46 项语音相关测试通过，其中 4 项验证 AEC 原生处理、实际播放参考、16 kHz 输出和缓冲溢出。
固定 50 ms 延迟、0.4 倍增益的合成语音回声实验，稳态能量衰减约 57 dB；
双讲阶段与独立处理的近端语音相关系数约 0.90，电平比约 0.88，证明该测试未靠静音消回声。
这些是确定性离线实验，不代表真实房间效果；尚待本机外放/麦克风和 Windows 声卡验证。

实现依据：[pywebrtc-audio](https://github.com/strands-labs/pywebrtc-audio)。

- **应用内链路**：在真实 Pipecat/Qt 进程中重复语音控制及报告追问，核对界面状态与实际回复。
- **真实音频**：实际麦克风说开始、暂停、继续、结束；验证豆包识别与播音、插话中断、否定句、重复命令、断网和退出释放。测量说话结束到动作确认及实际播放的延迟。
- **Windows 硬件**：连接真实光栅与驱动，用完整测试流程验证采集、暂停边界、自动结束、报告保存、历史重开与导出。

上述离线结果不能替代云端、音频或硬件验收。Key 不写入此文档、源码或测试数据。

配置完成后，可用 `python -m ui.demo --voice` 对模拟采集进行真实麦克风/ASR/TTS 联调。
须再点击“开启语音”才会连接语音服务；此模式仍使用模拟光栅与本地报告问答，
云端智能配置/报告 Agent 使用正式入口单独验收。

## 全量回归复验（2026-09-23）

提示词修复后的全量自动化回归为 870 项测试、12 项子测试通过（30.69 秒），保留两项既有警告。

## 云端报告分析复验（2026-09-23）

使用现有 Report Agent、报告分析 Skill 和合成步态报告 `left_late_change` 做一次真实模型调用。
首次调用在确定性验证阶段发现模型将数值 Evidence 绑定到了未被同一 Claim 引用的来源，
被 `numeric_fact_source_unbound` 拒绝；没有放宽校验器，而是在报告分析系统提示中补充来源绑定规则。
修复后重试耗时约 14.7 秒，状态 `validated`，发现 `increase`、`concentrated_on_side`、
`transient` 三个受支持谓词，四项决策断言全部通过。
相关配置转换、报告 Agent 合约、端到端、语音会话和 worker 回归共 30 项测试通过。
数据为合成报告，结论验证通过不代表真人语音或 Windows 硬件验收。

## 最终软件审计（2026-09-23）

- `git check-ignore` 确认 `.env` 被 Git 忽略；本轮检查只输出配置变量名，没有读取或输出凭证值。此项不是整个仓库的密钥泄漏扫描。
- 可复现入口已核对：`python -m ui.demo`（模拟演示）、`python -m ui.demo --voice`（手动开启 ASR/TTS）、
  `python -m voice --check`（语音依赖检查）、`python -m tools.check_runtime`（基础运行环境检查）。
- 本机系统为 macOS；运行时检查明确提示 USB 采集须在 Windows + CyUsbInterface.dll 环境验收。
- 模拟流程、配置转换、报告证据校验、Pipecat 播报打断与 worker 清理均有自动化证据；
  真实声卡、真人插话、物理 AEC、Windows 硬件和断网后的完整 UI 恢复仍标为未验收。

## 本机物理声卡 AEC 实测（2026-09-23）

经用户确认后运行：

```bash
python -m voice.aec_probe tests/fixtures/voice/tts_start.wav --seconds 12
```

使用本机默认 MacBook Air 麦克风和扬声器，未保存或上传录音。WebRTC AEC3 处理 1198 个十毫秒帧，
设备估计延迟 74 ms；外放固定测试语音期间，麦克风原始 RMS 为 4.52，处理后 RMS 为 3.22，
总体能量下降 2.94 dB。该下降同时包含降噪，不能当作严格 ERLE，也不能证明真人插话时 ASR 一定不被打断。
物理音频链路和设备时序已通过；真人说“开始/暂停/继续/结束”、打断播报和断网恢复仍需应用内人工验收。

## 工具与环境恢复复验（2026-09-23）

续接任务已验证终端、文件读取与补丁工具可用。此前直接运行 `python` 使用的是 Conda base，
缺少 pytest 和语音依赖；不能据此判断项目环境缺失。沿用原任务的 `.venv/bin/python`（Python 3.11.15）。
本机 `.venv` 启用了 `include-system-site-packages`，基于 Conda `Iron_Jump` 环境，二者并非完全隔离。
本轮补装了该 Conda 环境的 `requirements-voice.txt`；NLTK `punkt_tab` 已安装到用户数据目录。
下载时仅对该次官方数据下载启用了 `NLTK_ALLOW_PROXIED_URLOPEN=1`，未修改持久代理或应用设置。

复现检查：

```bash
.venv/bin/python -m pip check
.venv/bin/python -m tools.check_runtime
.venv/bin/python -m voice --check
.venv/bin/python -m voice --devices
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

- 项目环境依赖一致性、基础运行时和语音本地配置检查均通过。
- 全量回归：870 项测试、12 项子测试通过（30.74 秒），保留两项既有警告。
- 当前默认输入/输出是 OPPO Enco Air3，另可枚举 MacBook Air 内置麦克风和扬声器。
  PortAudio 格式查询支持默认设备的 24 kHz、单声道、int16；未打开录音/播放流，不代表物理双工验收通过。
- 本轮未修改 Key，未调用云端 ASR/TTS，也未执行 Windows 硬件验收。

### 2026-09-23：模拟模式智能配置入口

- 完整服务联调入口：`.venv/bin/python -m ui.demo --voice --agent`。`--agent` 使用当前解释器启动既有 Agent 服务；不带此选项保持离线配置演示。
- 模拟配置页默认选择跑步机步态 Agent，避免口述步态要求被送入纵跳配置模型。
- 智能建议播报包含测试类型、速度、时长或停止方式，仍需“确认配置”后应用。
- 针对性回归：`tests/test_voice_session.py`、`tests/test_gait_demo.py`，16 passed。覆盖现有语音配置提交/确认及新增播报、启动入口；不等同真人麦克风验收。
- 真实语音配置、真人插话及 Windows 硬件仍待现场验证。
