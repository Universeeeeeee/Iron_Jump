# Iron_Jump

Iron_Jump 是一套兼容 OptoJump 工作方式的运动测试与分析系统，面向纵跳、跑步机步态和跑步测试场景。系统通过两侧红外光栅采集脚部遮挡信号，实时识别触地、离地和步态周期，并提供测试配置、过程可视化、结果报告与历史记录管理。

> 项目目前处于原型验证阶段，适合研发、算法验证和受控测试，不应直接用于医疗诊断或临床决策。

## 产品演示视频

[在 Bilibili 观看产品演示视频](https://www.bilibili.com/video/BV1uobx6wESX/)

## 主要功能

- 纵跳测试：触地时间、腾空时间和跳跃表现分析。
- 跑步机步态测试：步态周期、支撑阶段、双支撑和对称性分析。
- 跑步机跑步测试：接触、腾空与跑步周期分析。
- 实时可视化：双侧 96 LED 状态、足迹时间线和测试指标展示。
- 测试报告：结果汇总、历史记录查询和 Excel 导出。
- 受试者管理：个人资料、团队关系和测试记录持久化。
- 相机与视觉工具：OBSBOT Tiny SE 录制、标注与离线 Replay，用于左右脚识别验证。
- 智能辅助：可选的自然语言测试配置与受控报告分析。

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
- 两根 96 LED 红外光栅；采样率固定为 1000 Hz。
- OBSBOT Tiny SE 为可选设备。

项目主要使用 PySide6、NumPy、OpenCV、MediaPipe、Pydantic、SQLite、pyqtgraph 和 openpyxl。完整 Python 依赖见 [`requirements.txt`](requirements.txt)，其中包含界面依赖 `dayu_widgets==1.1.1`。

## 安装

```bash
git clone git@github.com:Universeeeeeee/Iron_Jump.git
cd Iron_Jump

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

启动主程序：

```bash
python ui/main_window.py
```

可选的豆包 ASR/TTS + Pipecat 语音控制见 [语音使用说明](voice/README.md)。
安装语音依赖并配置 API Key 后，点击窗口右下角“开启语音”，支持配置、开始、暂停、继续、结束和报告分析。

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

- 已实现 Jump Test、Treadmill Gait Test 和 Treadmill Running Test。
- 当前仅支持一对一米段、每侧 96 LED 的光栅；多米段级联尚未实现。
- 跑步机步态与跑步算法已通过自动化合成数据验证，仍需要更多真实设备和人工真值对照。
- 左右脚视觉识别仍处于独立验证阶段，尚未写回主测试流程。
- `External impulse` 以及 Sprint、Tapping、Reaction Times、Static Test 等模式尚未实现。
- 智能报告的现有验证结果不代表真实运动训练效果或医学有效性。

## 文档

- [系统架构](docs/architecture.md)
- [当前开发计划](plan.md)
- [视觉模块说明](vision/README.md)
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
vision/      视频录制、标注和 Replay
tools/       诊断、验证与 Benchmark 工具
tests/       自动化测试
```
