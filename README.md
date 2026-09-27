# Iron_Jump

Iron_Jump 是一套兼容 OptoJump 工作方式的运动测试与分析系统，面向纵跳、跑步机步态/跑步和地面走路/跑步场景。系统通过两侧红外光栅采集脚部遮挡信号，实时识别触地、离地和步态周期，并提供测试配置、过程可视化、结果报告与历史记录管理。

> 项目目前处于原型验证阶段，适合研发、算法验证和受控测试，不应直接用于医疗诊断或临床决策。

## 产品演示视频

[在 Bilibili 观看产品演示视频](https://www.bilibili.com/video/BV1uobx6wESX/)

## 主要功能

- 纵跳测试：触地时间、腾空时间和跳跃表现分析。
- 跑步机步态测试：步态周期、支撑阶段、双支撑和对称性分析。
- 跑步机跑步测试：接触、腾空与跑步周期分析。
- 地面走路与跑步：多段设备空场自检、单人单向通过、逐步与同脚周期分析。
- 实时可视化：LED 状态、足迹时间线和测试指标展示；地面模式支持完整设备宽度回放。
- 测试报告：结果汇总、历史记录查询和 Excel 导出。
- 受试者管理：个人资料、团队关系和测试记录持久化。
- RFID 身份选择：RC200U 读卡、运动员绑定/解绑和刷卡选人。
- 相机与视觉工具：OBSBOT Tiny SE 录制、标注与离线 Replay，用于左右脚识别验证。
- 智能辅助：可选的自然语言测试配置与受控报告分析。
- 语音交互：可选的豆包 ASR/TTS、Pipecat 和本地 AEC3，复用已有配置、测试控制与报告入口。

## 系统组成

```text
红外光栅（1000 Hz）
  → USB 数据采集
  → 触地 / 离地与步态事件识别
  → 实时界面
  → 测试报告与历史记录

相机视频
  → Session 录制
  → 人工标注 / 离线 Replay
  → 左右脚识别验证
```

视觉模块目前是独立验证工具，不会修改光栅采集到的事件时间。

## 运行环境

- Python 3.11
- Windows 10/11：连接 USB 光栅、加载 `CyUsbInterface.dll` 以及使用 Tiny SE 高帧率采集时必需。
- macOS/Linux：可用于部分界面、算法和自动化测试开发，但不能直接使用 Windows DLL 硬件链路。
- 红外光栅每段 96 个光束；采样率固定为 1000 Hz。采集接口支持可变段数，地面模式使用完整布局；纵跳与跑步机仍使用单段兼容通道。
- OBSBOT Tiny SE 为可选设备。

项目主要使用 PySide6、NumPy、OpenCV、MediaPipe、Pydantic、SQLite、pyqtgraph 和 openpyxl。完整 Python 依赖见 [`requirements.txt`](requirements.txt)，其中包含界面依赖 `dayu_widgets==1.1.1`。

## 安装

```bash
git clone git@github.com:Universeeeeeee/Iron_Jump.git
cd Iron_Jump
git switch vae/iron_jump

python -m venv .venv
```

Windows：

```powershell
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

macOS/Linux：

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

如需使用智能配置或报告分析，在项目根目录创建 `.env`：

```dotenv
OPENAI_BASE_URL=<兼容 OpenAI API 的服务地址>
OPENAI_API_KEY=<API 密钥>
```

不配置上述变量时，硬件采集、规则算法和不依赖在线模型的功能仍可独立开发与测试。

## 使用方法

先检查基础运行依赖：`python -m tools.check_runtime`。

无需 USB 和 Key 的步态演示：

```bash
python -m ui.demo
```

演示默认使用手动步态配置，选择本次测试身份后依次准备、开始、暂停、继续、结束。
建议采集至少 15 秒，报告页可使用“步态专项问答”并点击证据定位明细。
演示使用独立的 `data/demo.sqlite3`；报告、重开的历史记录与 Excel 都标明模拟数据。
此入口不启用云端助手或麦克风，模拟信号仍经过真实算法引擎；不能替代真实设备验收。
完整验收步骤见 [步态与语音验收记录](docs/gait_voice_validation.md)。

模拟光栅下联调语音和既有 Agent 服务可运行 `python -m ui.demo --voice --agent`；仍需手动点击“开启语音”，并配置相应服务凭证。

启动主程序：

```bash
python ui/main_window.py
```

可选的豆包 ASR/TTS + Pipecat 语音控制见 [语音使用说明](voice/README.md)。
安装语音依赖并配置 API Key 后，点击窗口右下角“开启语音”，支持配置、开始、暂停、继续、结束和报告分析。
语音栏嵌入主界面底部；配置和报告复用现有页面，“停止播报”保留聆听与测试，“关闭语音”释放麦克风，诊断记录默认收起。
智能配置和 Report Agent 当前覆盖纵跳、跑步机步态和跑步机跑步；地面模式使用手动配置与独立报告，单次通过不提供暂停/继续。

地面模式的设备启停、段数与排列设置见 [采集接口](docs/采集数据接口.md)，操作与指标定义见 [地面走路](docs/地面走路算法.md) 和 [地面跑步](docs/地面跑步算法.md)。主程序默认启用 0918 FPGA 采集命令及 10ms/2048 字节读取；无需该命令的旧固件可设置 `DAYU_CAPTURE_COMMAND=0`。

启动视觉数据工具：

```bash
python vision_app.py
```

常用诊断入口：

```bash
python hardware/receive.py
python tools/vision_diagnostic.py --help
python tools/vision_event_validator.py --help
```

运行自动化测试：

```bash
python -m pytest -q
```

Qt 自动化测试需要先安装 `python -m pip install -r requirements-dev.txt`。

## Windows 视觉工具打包

在 Windows 中运行：

```bat
build_vision_app.bat
```

构建产物位于：

```text
dist/IronJumpVisionTools/IronJumpVisionTools.exe
```

录制数据和日志默认保存在：

```text
%USERPROFILE%\Documents\IronJump\vision_sessions
%USERPROFILE%\Documents\IronJump\app_logs
```

## 当前状态与限制

- 当前开发基线为 `vae/iron_jump`，已汇总语音、多段采集、地面算法和 Mac MediaPipe 开发进展；`main` 保持原有版本。
- 已实现 Jump Test、Treadmill Gait Test、Treadmill Running Test、地面走路（配置标识 `Sprint and Gait Test`）和 `Overground Running Test`。
- 多段协议支持 1..255 段，这是软件协议范围；实际级联能力、几何标定、段间同步和 Windows 完整流程仍需实机验收。
- 跑步机步态与跑步算法已通过自动化合成数据验证，仍需要更多真实设备和人工真值对照。
- 左右脚视觉识别仍处于独立验证阶段，尚未写回主测试流程。
- 标准距离冲刺计时、往返地面测试、Tapping、Reaction Times、Static Test 尚未实现；`External impulse` 不受当前硬件支持。
- RAG 发布门及冻结审查工件已纳入仓库，内容指纹校验通过后才启用；初始化或运行失败时保留确定性分析并降级。
- 2026-09-26 合并基线 `86ff8ae` 在 macOS / Python 3.11.15 / Qt offscreen 下全量回归：1048 项测试、12 项子测试通过。该结果不替代真实音频或硬件验收。
- 智能报告的现有验证结果不代表真实运动训练效果或医学有效性。

## 文档

- [系统架构](docs/architecture.md)
- [当前开发计划](plan.md)
- [视觉模块说明](vision/README.md)
- [语音使用说明](voice/README.md)
- [步态与语音验收](docs/gait_voice_validation.md)
- [可变段数采集接口](docs/采集数据接口.md)
- [RC200U 接入与验证](docs/RC200U接入与验证.md)
- [Benchmark 结果](benchmark_results/README.md)

## 目录概览

```text
hardware/    USB 通信与协议解析
engine/      运动事件与步态分析引擎
config/      测试参数和报告数据模型
ui/          PySide6 桌面界面
data/        受试者、团队和测试记录
agent/       智能配置与报告分析
reporting/   报告语义与确定性分析
knowledge/   文献检索、建议校验与 RAG 发布门
voice/       ASR/TTS、Pipecat 语音进程与 AEC3
vision/      视频录制、标注和 Replay
tools/       诊断、验证与 Benchmark 工具
tests/       自动化测试
```
