# Tiny SE 相机运动控制进度

最后更新：2026-10-08（Asia/Shanghai）。维护方：本控制对话。

本文件作为两个 Codex 对话的控制侧交接记录。每完成重要阶段，更新完成状态、代码位置、验证证据及待办。识别侧由另一对话维护；本对话只维护 `control.md`，不修改 `detect.md`。2026-10-08 已结合识别侧实际代码、diff 和保存输出完成首次交叉核对，细节见第 6 节；未复验的现场判断仍保留为待验证；双方成果已于第12轮整合到vae/iron_jump，详见当前状态与最终记录。

协作约定（2026-10-08，按用户最新要求）：以识别侧 [detect.md](/Users/vae/Projects/Iron_Jump/docs/codex-camera/detect.md) 为主要协作依据，通过各自文档沟通重大修改。

- 每次重大实现修改、部署、实机验证或合并前，先读取最新 `detect.md`，核对相关接口、职责和待办，并结合双方实际分支、工作树 diff 与原始证据判断；文档中的结论不自动成为已验证事实。
- 每完成重要阶段，在本文件更新任务状态、修改文件及原因、分支和提交、测试命令及结果、待验证假设，以及对识别侧请求的处理结果和需要对方配合的事项。尚未部署或合并的改动明确注明。
- 接口或技术决策存在分歧时，将证据、差异和待对方确认的问题写入第 6 节。控制侧继续负责运动控制；识别侧文档与其负责模块由对方维护，不直接覆盖其改动。

以下历史记录按当时提交/部署状态保留；当前实现与合并状态以第1节、第12轮为准。

后续授权（2026-10-08）：用户要求双方主动多轮对话协作；重大结果继续落各自文档，以 `detect.md` 为主要依据。方案迭代成熟并通过离线验证后，请用户配合现场验收；现场通过后合并到 `vae/iron_jump`，再删除 `codex/tinyse-mediapipe-gimbal-validation` 分支。现场通过前不合并或删除。本侧已主动向识别对话发送接口审阅与实现范围协商，不再沿用此前“未发送消息”作为当前状态。

## 1. 当前任务及完成状态

目标：验证 Tiny SE SDK 是否支持可调速的水平/俯仰控制，让 MediaPipe 识别结果驱动云台；按用户最新要求使用全身目标，保持最大视野，水平响应需要较快。

| 阶段 | 状态 | 结果或边界 |
| --- | --- | --- |
| 建立隔离验证分支 | 验证、合并及清理完成 | 从cc0bc7f建立，现场接受后真实双父合并ae17a6c；worktree已可恢复归档，验证分支已安全删除 |
| 确认 SDK 两轴速度接口 | 完成 | 已封装并实测，现有 SDK 足够完成本轮控制验证 |
| Windows 编译环境 | 完成 | 原有 Qt MinGW/clang-cl，缺少完整 MSVC；经用户授权补齐 Build Tools 2022，实际构建成功 |
| 两轴脉冲、水平快慢及方向验证 | 完成 | 输入 30/60 的等时水平脉冲，平均转动量约 7.32°/13.75°；图像独立核对方向 |
| 最大视野、全身目标 | 完成当前实现 | 启动关闭内置 AI，设置最宽 FOV 枚举 0、缩放 1.0；运行只控制云台，不请求自动放大 |
| MediaPipe → SDK 实机闭环 | 完成一轮普通行走验证 | 45 秒内识别到全身并实际跟随；靠近相机、脚部遮挡仍会丢失有效目标 |
| 与另一对话识别成果对接、接入正式 UI | 协作及两轮联合实机完成，已合并 | 复用panel/640出口和唯一SDK；用户接受300/120，大字无声及Panel生命周期通过；完整MainWindow实体退出未复测 |
| 跨分支接口与证据核对 | 公共接口、时间和职责已对齐 | 原始33点/metadata/epoch/generation全链路，Windows与双方独立回归通过；实体完整动作和取景边界按现场另验 |
| 快速跑跳、遮挡、长时间稳定性 | 待验证 | 不能从普通行走短测推断这些场景已通过 |
| 固件升级对比 | 未执行 | 当前固件 6.4.3.4；用户提供 6.4.4.1 包，尚未刷入 |

当前代码位置：`/Users/vae/Projects/Iron_Jump`，分支vae/iron_jump，功能合并ae17a6c。下方代码链接已指向正式主工作树；历史控制worktree为 `/Users/vae/.codex/worktrees/tinyse-gimbal-validation/Iron_Jump`，清理状态见第12轮。

已提交控制实现：

- `ee4a04e`：独立两轴速度通道、目标到速度控制器、验证工具及测试。
- `cd5f626`：实机方向校准、Windows DLL 和脉冲记录。
- `26881a9`：改为全身目标、固定最宽视野及闭环测试记录。
- `92fc6b9`：逐项检查 visibility/presence 的有限性与范围，修复控制目标错误接纳非法置信度的问题；已含于联合Windows候选，早期独立实机对应26881a9。
- `69ab8ec`：按识别侧补充反馈，最大 FOV 设置失败时中止启动并增加回归；已含于联合Windows候选。
- `336a3da`：有界公共姿态/JSON传输、单一 SDK 速度运行器、取景余量辅助和 panel 运动接线。
- `924fe47`：修复实际零速应答及正式主窗口退出屏障，增加独立现场记录工具；Windows原始候选包基于该提交与识别侧冻结源码。
- `7815713` / `e74a7b8`：可见同一Panel、阶段提示；按用户反馈改成窗口内大字无声。
- `88c630e`：水平增益300、上限120，CLI/回归预期和候选参数来源记录同步。最终控制分支HEAD，Windows薄增量已现场接受；已合入vae/iron_jump的ae17a6c。

## 2. 已证实的事实及对应代码位置

| 事实 | 代码位置 | 证据与限制 |
| --- | --- | --- |
| SDK 可独立设置 pitch、pan 速度，零速度用于停止 | [C++ 封装](/Users/vae/Projects/Iron_Jump/camera/obsbot_sdk_wrapper/obsbot_c_api.cpp:650)、[SDK 声明](/Users/vae/Projects/Iron_Jump/camera/sdk/libdev_v2.1.0_8/include/dev/dev.hpp:1831) | 调用 `aiSetGimbalSpeedCtrlR(pitch, pan, 0.0)`，已观察到实际两轴转动；手动实验先关闭内置 AI |
| 角度反馈顺序为 roll、pitch、pan | [角度封装](/Users/vae/Projects/Iron_Jump/camera/obsbot_sdk_wrapper/obsbot_c_api.cpp:663) | 用 `gimbalGetAttitudeInfoR`；反馈与截图/录像结合使用，SDK 返回成功本身不是物理运动证据 |
| 水平输入增大确实提高短时转动量 | [脉冲工具](/Users/vae/Projects/Iron_Jump/tools/tinyse_gimbal_validator.py:48) | 约 0.306 秒脉冲，30/60 的平均位移约 7.32°/13.75°，比值 1.88；含启动与制动，不是稳态角速度，也不是对内置 AI 速度的比较 |
| 当前相机方向校准为 pan_sign=+1、pitch_sign=+1 | [方向与参数](/Users/vae/Projects/Iron_Jump/vision/gimbal_tracking.py:7) | 正水平指令使画面内容左移，正俯仰指令使画面内容上移；脉冲截图、ORB/RANSAC 图像匹配与角度反馈共同确认。早期 pitch_sign=-1 已修正 |
| 启动时请求最宽视野、1 倍缩放 | [启动设置](/Users/vae/Projects/Iron_Jump/camera/gimbal_control.py:35)、[缩放封装](/Users/vae/Projects/Iron_Jump/camera/obsbot_sdk_wrapper/obsbot_c_api.cpp:621) | 实机 FOV 设置返回 0，第二轮开始和结束后缩放均读回 1.0；未标定实际视场角，也没有持续抵御其他应用更改缩放的机制 |
| 当前控制目标包含全身可见关键点 | [full_body_target](/Users/vae/Projects/Iron_Jump/vision/gimbal_tracking.py:29) | 使用 33 点中可靠点的范围中心，包括可用头、手、脚；双肩、双髋、双踝必须有效，visibility/presence 分别须在 0.65～1 且有限。非必要点可被忽略，目标有效不等于头顶和所有脚部点完整入镜 |
| 水平响应参数可单独调整 | [控制器](/Users/vae/Projects/Iron_Jump/vision/gimbal_tracking.py:9)、[CLI 参数](/Users/vae/Projects/Iron_Jump/tools/tinyse_gimbal_validator.py:17) | 当前默认pan_gain=300、pitch_gain=80，上限120/30，中央死区半宽.06；首轮为240/90，第二轮300/120已由用户接受，参数不能直接当实测转速 |
| 推理过期和无目标时停止 | [原始帧时间与控制更新](/Users/vae/Projects/Iron_Jump/tools/tinyse_gimbal_validator.py:75)、[看门狗](/Users/vae/Projects/Iron_Jump/camera/gimbal_control.py:63) | 保留采集回调原始单调时钟时间；超过 250 ms 不继续运动，控制线程约每 50 ms 更新。SDK 自身阻塞时不能保证及时停止，只能报告失败 |
| 采集和 SDK 云台控制可并行 | [独立工具入口](/Users/vae/Projects/Iron_Jump/tools/tinyse_gimbal_validator.py:127) | 全身行走测试约 100 fps 采集，录制 0 丢帧；推理约 10.6 次/秒，不能称为 100 fps 识别 |

Windows 主机：`LAPTOP-N03I4GMH`，地址 `100.116.17.121`。独立目录：`C:/Users/86150/TinySE-gimbal-validation-20261008`，没有覆盖正式项目。

Build Tools 位于 `D:/BuildTools/VS2022`，版本 17.14.41；实际编译器 MSVC 19.44.35229，Windows SDK 10.0.26100.0。安装退出码 0，无需重启。Python 为 `D:/conda/envs/pydantic_ai/python.exe`，环境已有 OpenCV 5.0.0、MediaPipe 0.10.35。

当前实测固件为 6.4.3.4。用户提供的 `Obsbot_tinyse_OA_E_PW107_6.4.4.1_release.bin` 尚未刷入；[官方说明](https://www.obsbot.com/download/obsbot-tiny-se)仅列出 Switch 2 模式及已知问题修复，未明确说明水平速度或跟踪改善。

## 3. 已修改文件及原因

以下控制实现已由验证分支整合至vae/iron_jump，链接指向当前主树。识别依赖由对方独立提交e88c3c1，本侧未修改其模块或detect.md；本侧修改控制实现/必要共享Panel与MainWindow guard、本进度文件和自有验证证据。

| 文件 | 修改原因 |
| --- | --- |
| [camera/obsbot_sdk_wrapper/obsbot_c_api.h](/Users/vae/Projects/Iron_Jump/camera/obsbot_sdk_wrapper/obsbot_c_api.h:124) | 声明纯 C 的两轴速度、角度与缩放接口供 ctypes 调用 |
| [camera/obsbot_sdk_wrapper/obsbot_c_api.cpp](/Users/vae/Projects/Iron_Jump/camera/obsbot_sdk_wrapper/obsbot_c_api.cpp:621) | 桥接现有 SDK，检查非法速度、缩放和空输出指针 |
| [camera/bin/obsbot_c_api.dll](/Users/vae/Projects/Iron_Jump/camera/bin/obsbot_c_api.dll) | 保存 Windows 实际重编译并实测的新接口产物 |
| [camera/gimbal_control.py](/Users/vae/Projects/Iron_Jump/camera/gimbal_control.py:10) | ctypes 通道、关闭 AI 与最宽视野设置、带超时的控制线程和退出停止；本轮对 FOV 设置失败增加强制错误检查 |
| [vision/gimbal_tracking.py](/Users/vae/Projects/Iron_Jump/vision/gimbal_tracking.py:29) | 将全身目标偏差转换为独立 pitch/pan 速度，水平增益更高；替换早期下半身目标；本轮补齐原始置信度非法值检查 |
| [tools/tinyse_gimbal_validator.py](/Users/vae/Projects/Iron_Jump/tools/tinyse_gimbal_validator.py:127) | 独立脉冲/MediaPipe 闭环入口，记录原始录像、命令、角度、帧率、截图和清理状态 |
| [tests/test_gimbal_tracking.py](/Users/vae/Projects/Iron_Jump/tests/test_gimbal_tracking.py:12) | 验证方向、全身范围、质量过滤、速度边界、超时停止及失败清理；本轮新增 6 项单字段非法置信度回归 |
| [camera/obsbot_sdk_wrapper/README.md](/Users/vae/Projects/Iron_Jump/camera/obsbot_sdk_wrapper/README.md:3) | 保存运行说明、实际编译路径及验证记录；后续本对话的阶段进度统一维护在本文件 |

复用但未修改：`camera/tinyse_dshow_capture.py`、`vision/mediapipe_pose.py`、`vision/foot_reference.py` 及原模型。模型通过已有适配器输出 `landmarks_33`，控制工具直接使用原始采集帧。

本轮主项目新增的控制侧证据：[replay.py](/Users/vae/Projects/Iron_Jump/exports/control_cross_review_20261008/replay.py)、[control_replay.json](/Users/vae/Projects/Iron_Jump/exports/control_cross_review_20261008/control_replay.json)。脚本只读取识别侧已保存的输出，调用本分支控制器与识别侧当前入镜检查，保存输入 SHA256 和复算结果，不重新推理或驱动硬件。

## 4. 测试命令和结果

### 自动测试与编译

在验证 worktree 中执行：

```sh
python3 -m pytest -q -p no:cacheprovider tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py
git diff --check
```

结果：22 项通过，差异格式检查通过。覆盖缺失/非法目标、全身范围、方向、速度饱和、看门狗过期、SDK 错误及启动/运行异常时停止清理。看门狗故障测试使用模拟 SDK，不代表已完成真实断线测试。

本轮新增置信度检查的复验：

```sh
# 修复前：5 failed、1 passed、19 deselected，复现合成 quality 漏过非法原始字段。
python3 -m pytest -q -p no:cacheprovider tests/test_gimbal_tracking.py -k individual_confidence
# 修复后：28 passed in 0.52s；git diff --check 通过。
python3 -m pytest -q -p no:cacheprovider tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py
```

修复仅影响非法输入，保持识别模型、0.65 阈值和原有必要点集合。本轮离线复算的每份选定有效历史输入，与 `26881a9` 控制器输出一致。Windows 最新实机测试仍是前述版本的 19 项结果，未把新的本地 28 项结果算成 Windows 通过。

识别侧并行复核后补充的 FOV 回归：

```sh
# 修复前：1 failed、25 deselected；FOV 返回 -1 时没有抛错。
python3 -m pytest -q -p no:cacheprovider tests/test_gimbal_tracking.py -k widest_view --tb=short
# 修复后最终结果：29 passed in 0.54s；git diff --check 通过。
python3 -m pytest -q -p no:cacheprovider tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py
```

`69ab8ec` 在 `GimbalSdk.disable_ai()` 中检查 FOV 返回码，失败则中止启动，不继续报告已设置最宽视野。新增测试使用模拟 DLL，不是新的硬件实验。Windows 尚未部署 `92fc6b9` 或 `69ab8ec`，没有将本地 29 项测试冒充远程结果。

在主项目根目录执行本轮控制侧离线复算：

```sh
.venv/bin/python exports/control_cross_review_20261008/replay.py
```

结果：成功，重新计算的区间推理总数和非空姿态数与识别侧保存统计一致；控制与入镜判定结果见第 6 节。区间使用 `record.frame_timestamp_s - audit.state.start`，不使用推理结束时记录的 `t`，避免边界样本计数偏差。

macOS 原生编译命令：

```sh
clang++ -std=c++14 -dynamiclib \
  -I camera/sdk/libdev_v2.1.0_8/include \
  camera/obsbot_sdk_wrapper/obsbot_c_api.cpp \
  -L camera/sdk/libdev_v2.1.0_8/macos/arm64-release -ldev \
  -Wl,-rpath,/Users/vae/.codex/worktrees/tinyse-gimbal-validation/Iron_Jump/camera/sdk/libdev_v2.1.0_8/macos/arm64-release \
  -o /private/tmp/libobsbot_full_body_validation.dylib
```

结果：成功。通过临时 ctypes 脚本完成早期 7 项速度/角度 C ABI 检查及新增 7 项缩放非法输入/无设备检查，无硬件命令；该临时脚本未作为仓库测试文件保存。

Windows 在独立目录执行：

```powershell
cmake -S camera/obsbot_sdk_wrapper -B build -G "Visual Studio 17 2022" -A x64
cmake --build build --config Release
& 'D:/conda/envs/pydantic_ai/python.exe' -m pytest -q tests/test_gimbal_tracking.py
```

结果：实际构建成功，19 项控制测试通过；早期 Windows 速度/角度 C ABI 7 项检查通过。最新 DLL 已取回验证分支。

### 实机验证

以下命令均在 Windows 独立目录运行，输出目录已存在，重跑应换用新的目录名。

```powershell
& 'D:/conda/envs/pydantic_ai/python.exe' -m tools.tinyse_gimbal_validator --mode pulse --pulse-pan 60 --output exports/pulse_20261008_01
& 'D:/conda/envs/pydantic_ai/python.exe' -m tools.tinyse_gimbal_validator --mode track --no-preview --duration 15 --output exports/track_20261008_01
& 'D:/conda/envs/pydantic_ai/python.exe' -m tools.tinyse_gimbal_validator --mode track --no-preview --duration 45 --output exports/full_body_20261008_01
& 'D:/conda/envs/pydantic_ai/python.exe' -m tools.tinyse_gimbal_validator --mode track --no-preview --duration 45 --output exports/full_body_20261008_02
```

| 输出目录 | 结果 |
| --- | --- |
| `pulse_20261008_01` | 两轴正反向短脉冲完成；水平 30/60 位移比约 1.88；采集 544 帧约 100 fps，录制 556 帧、0 丢帧。角度、前后截图、ORB/RANSAC 匹配核对真实运动 |
| `track_20261008_01` | 采集启动报 `IMediaControl::Run failed (hr=0x800705AA)`；独立采集也失败，同期另一相机诊断进程运行。清理已发送停止。不能据此判断 MediaPipe 与 SDK 不兼容 |
| `full_body_20261008_01` | 用户确认其他相机程序退出后采集恢复。约 45 秒、471 次推理、0 有效全身目标、0 非零控制样本；截图未见完整人体。录制 4527 帧、0 丢帧，停止正常 |
| `full_body_20261008_02` | 用户就位后完成 45.12 秒行走验证：478 次推理、428 次有效目标、73 次非零控制样本。图像到结果延迟中位数 46.68 ms、最大 65.36 ms，无超过 250 ms 结果；采集约 100 fps，录制 4521 帧、0 丢帧，停止正常 |

第二轮水平角从 -3.60° 到 -61.44°，俯仰从 12.70° 到 7.42°。开始、结束及 5/10/20/30/40 秒原始抽帧确认背景随云台转动，并观察到行走时的全身取景；最后靠近相机、椅子遮挡阶段有无效目标。428/478 是本轮有效控制目标比例，不是识别准确率；73 是非零控制日志样本数，不是 SDK 发送次数。

Windows 每轮证据保存在 `C:/Users/86150/TinySE-gimbal-validation-20261008/exports/<目录名>/`：`report.json`、`commands.jsonl`、`capture.mjpg`、`capture.csv` 和截图。工具的 `hardware_motion_verified` 默认仍为 false，日志状态要求图像复核；本文上述结论来自后续图像与反馈核对，不是该字段自动判定。

最近一次测试结束时已发送停止，工具未恢复内置 AI。正式使用需要由正式程序重新启用对应 AI 模式；不要让另一程序在本工具控制过程中同时写云台或缩放。

## 5. 待验证假设

- 提高 pan_gain/pan_max 是否能改善快速横移，又不会产生过冲、抖动；当前只证明水平速度可调及普通行走闭环有效。
- 全身目标是否比下半身目标在统一距离、轨迹和速度下更稳定：用户现场反馈全身更好，但尚未做可量化的配对对照。
- 双踝被遮挡或出画时，是否由识别侧提供可靠的全身中心/跟踪状态，降低停转次数；当前必须满足双肩、双髋、双踝质量门槛。
- 最宽 FOV 的实际角度、近距离完整取景边界，以及其他应用/手势是否会改变缩放：当前只验证设置结果、起止缩放读回和录像，没有连续缩放监控或实际视场角标定。
- 长时间运行、真实 USB 断开/重连、SDK 阻塞后的停止与恢复；当前模拟故障测试不能替代实机故障验证。
- 新固件 6.4.4.1 是否改善控制或跟踪；需保持相同条件做升级前后比较，本轮没有升级或证明改善。
- 接入正式程序后，预览、模型推理、录制和控制服务是否争用相机或增加延迟；独立目录测试结果不能代替正式程序集成测试。
- 当前范围中心加固定死区是否能让头顶、脚尖持续留有余量：已有“控制目标有效但入镜检查失败”的离线证据，后续应由控制侧验证取景余量，不能将该责任全部归给识别侧。

## 6. 需要识别侧 Codex 对话配合的事项

通过各自进度文件交换结果；本轮已读取 `detect.md`，未向另一对话发送消息，也未修改该文件。

1. 给出识别侧当前分支、提交、入口和已验证证据位置，确认是否仍使用 `FootPoseSample.landmarks_33`，以及是否已有更稳定的全身目标/身份保持方案。
2. 明确输入坐标是否来自未镜像原图、是否经过裁切或缩放，归一化坐标如何回到完整采集画面；控制方向校准依赖这个约定。
3. 保留原始采集回调的单调时钟时间戳，而不是推理完成时间。当前控制接口是 `SpeedWatchdog.update(pitch, pan, captured_at)`；250 ms 过期检查必须使用同一主机的同一时钟域。
4. 提供有效/丢失/遮挡/换人状态及关键点 visibility、presence。当前质量为两者最小值，门槛 0.65；若改为新的目标格式，需要双方确认失效时的停止语义。
5. 协调 Windows 实机测试时段和唯一相机采集方。优先评估复用同一原始帧源供识别、预览和控制使用；不要同时启动两套 DirectShow 采集或让内置 AI 与 SDK 控制竞争。
6. 对同一段录像/同一次动作给出识别质量、推理延迟、目标跳变与丢失区间；控制侧对应检查画面中心误差、运动方向、超时停转及实际角度，区分识别失效与云台响应不足。
7. 联合验证普通横移、快速横移、跑跳和遮挡后，再决定正式程序集成及参数；当前验证分支尚未自动合并到主项目。

### 2026-10-08：分支、代码与保存证据交叉核对

核对基准：识别侧 `vae/iron_jump` 的 HEAD 为 `cc0bc7f`，但实现包含未提交及未跟踪文件；控制侧核对前为 `26881a9`，两项控制修复后为 `69ab8ec`。两边不是相同的运行版本，不能只做 HEAD 对 HEAD 比较。

识别侧已有修改包括 `camera/tinyse_camera.py`、`ui/embedded_camera_panel.py`、`vision/pose_overlay.py`、`vision/service.py`、`vision/event_scheduler.py`，以及未跟踪的 `camera/control_service.py`、`vision/live_walking.py`、`vision/framing.py` 等。控制分支相对 `cc0bc7f` 的已提交改动集中在 8 个控制验证文件，未改主界面、采集包装和识别显示模块。两边修改的职责有衔接，但当前没有直接重叠编辑同一实现文件；合并时应保留主项目的相机启动就绪等待和采集生命周期修复。

首次核对时，识别侧启动修复 manifest 中的 6 个本地文件均与记录的 after_sha256 匹配；不据此推断远程当前部署未变化。`detect.md` 快照 SHA256 为 `4554fd2d8bd319d602818cb6360284bf5670676740c2fb2b30938ff22e49a9f3`。

| 对比事项 | 独立检查结果 | 判断与责任 |
| --- | --- | --- |
| 模型及基础姿态数据 | 两个本地模型哈希均为 `5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1`；两边 `mediapipe_pose.py`、`foot_reference.py`、`time_sync.py`、`tinyse_dshow_capture.py` 内容相同；保存输出含 33 点 | 数据结构兼容，尚不代表整个运行链路一致 |
| 推理图像处理 | [主界面适配器](/Users/vae/Projects/Iron_Jump/vision/live_walking.py:15) 将宽度缩至 640；控制独立工具解码原始 1080p 后直接交给适配器 | 保留识别侧现有处理；未来控制应消费其结果，避免把独立工具的延迟/识别结果当成主界面基准 |
| 相机运动决策 | 识别诊断使用内置 AI 的标准子模式 0，正式 UI 仍默认子模式 4；控制实验关闭内置 AI，由 MediaPipe 输出速度 | 两条方案尚未统一，不能同时开启，也不能声称正式默认已改为全身。共同目标是完整取景；控制侧负责方案与正式接入设计 |
| 坐标与镜像 | [采集输出](/Users/vae/Projects/Iron_Jump/camera/tinyse_camera.py:562) 先发原图 analysis 信号，之后才软件镜像预览；640 缩放为等比整图，不裁切 | 当前归一化坐标可供控制使用；未来不得把镜像显示坐标直接作为控制输入 |
| 时间基准 | [识别输入](/Users/vae/Projects/Iron_Jump/vision/live_walking.py:80) 在同步就绪时用映射后的采集时间，未就绪时用 callback 时间；控制实验直接用 callback perf_counter | 两者处于主机单调时钟域，但“结果年龄”的起点不同。集成应明确传入 frame_timestamp_s，保留原始 callback/sample 时间和同步状态供关联，不用推理结束时间刷新控制有效期 |
| 结果出口 | [PoseInferenceRecord](/Users/vae/Projects/Iron_Jump/vision/service.py:53) 包含帧时间、推理开始/结束、pose 与 error，并通过 worker 的 EventHook 发出；当前无原始 frame_index/callback 字段 | 可作为非 UI 控制接入候选；需要识别侧提供稳定公共订阅/元数据约定，不能依赖 UI 轮询状态或只接 pose_ready（后者不发送 None） |
| 控制进程接口 | [METHODS](/Users/vae/Projects/Iron_Jump/camera/control_service.py:9) 当前仅允许低频设置及 AI 模式，没有速度、缩放、角度接口；TinySeCameraControl 也未绑定新增 ABI | 与独立 GimbalSdk 不可直接互换。扩展服务、速度看门狗及停止/退出确认由控制侧负责，不能让识别侧直接高频同步调用 SDK |
| 质量与可用状态 | 识别统计的“8～10 点达标”检查质量；[check_framing](/Users/vae/Projects/Iron_Jump/vision/framing.py:35) 还检查全部 10 个下肢点在图像内；控制目标只强制 6 个核心点 | 不构成测量结果矛盾，但有接口语义差异。“姿态存在 / 控制目标有效 / 入镜合格 / 触地可核验”必须分开，任何一种都不等于识别准确率 |
| 最大视野与模型改善 | 核对两份分析脚本、原始输出和代表图像；两轮均请求 FOV=0，较完整取景轮同时改变 AI 模式、机位和站位 | 与控制侧现有结论一致：不能单独证明 FOV 或某一模式的因果效果，也不能用界面“86°”标签当标定值 |

只读复算结果（区间沿用识别侧保存分析，已抽查 14.09s 与 30.04s 的实际原图，未重新逐帧标注全部方向）：

| 数据与输入时间区间 | 姿态 / 推理 | 控制目标有效 | 完整下肢入镜合格 | 控制有效但入镜不合格 |
| --- | --- | --- | --- | --- |
| `side_audit2` 7.5～10.5s | 36/37 | 14 | 13 | 1 |
| `side_audit2` 13～17s | 38/50 | 0 | 0 | 0 |
| `side_audit5_wide` 2～10s | 105/105 | 105 | 25 | 80 |
| `side_audit5_wide` 28～34s | 75/75 | 70 | 20 | 50 |
| `side_audit5_wide` 38～44s | 75/75 | 41 | 2 | 39 |

侧面旧片段的 38 份非空姿态双踝均未通过控制质量/坐标检查；较完整取景轮 28～34s 的 5 次控制拒绝来自右踝，回正面阶段双踝也仍有失效。控制目标可用却入镜不合格，主要说明核心点可见不能代替脚跟/脚尖完整可见；这些数字是对保存输出的判定复算，不能当作在线闭环改善率。

本轮发现并修复的控制侧问题：`min(visibility, presence)` 可能掩盖另一字段的 NaN/无穷大/超范围值，原控制器却仅检查合成 quality。使用故障输入复现后，改为逐字段有限性和 0.65～1 范围检查，与识别侧严格入镜检查的输入要求一致。这项修复只修改本分支 `vision/gimbal_tracking.py` 与其测试；后续 FOV 修复仅涉及 `camera/gimbal_control.py` 及同一测试文件。没有修改识别模型、适配器、显示、采集或 UI。

### 需要识别侧处理或确认的具体事项

1. 明确公共姿态输出接口是否采用 `PoseInferenceRecord`；若采用，提供原始 frame_index、sample_time、callback_time 与映射时间/同步状态的关联方式，并明确停止、None、error 的输出语义。请在识别侧文件中记录已实现部分；控制侧不擅自修改 `vision/service.py` 或 `vision/live_walking.py`。
2. 在识别侧报告中分别标明“质量达标”与“在图像内且所有 10 点合格”，避免把 `side_audit5_wide` 的高置信度统计解释为测量取景已通过。本次复算表可作为对照；不是要求降低阈值或强制绘制错误点。
3. 为已有失败区间补充或指向脚踝遮挡、出画、左右身份不确定的证据，确认是否有可靠的控制目标状态可供消费；头脚余量和运动控制调整由控制侧承担，不要求识别侧代改云台模块。
4. 确认正式接入继续使用原模型与主界面 640 整图缩放；若以后做 A/B，单独标识输入处理与时钟差异。不要直接比较两边 35/47ms 的统计来宣布模型或控制更快。
5. 记录主项目共享启动/采集文件的后续实际 diff 和部署版本，保留已有 idle 就绪等待；与控制侧协调由唯一 SDK 控制方接入速度通道，避免内置 AI 与手动速度竞争。

控制侧后续责任：明确完整取景余量的验收条件；基于同源姿态回放验证方向/响应与目标失效；设计单一控制进程中的速度、时间记录和停止确认；再安排快速横移及联合实机测试。本轮没有启动相机、部署新提交或更改生产默认模式。

### 识别侧并行更新后的确认与剩余责任

识别侧在本轮进行中自行更新了 `detect.md`；后续已重读新增部分，快照 SHA256 为 `0826574090ef06e0ed6eddbe8c143374b504cf7a724d23bfbb08b763c00393cb`，此前记载的 `4554...` 是首次读取快照。本侧没有写入该文件；两份原始 `audit.json` 输入哈希在复算结束后仍与控制证据中记录一致。

- 双方区间复算均得到控制有效 70/75、完整下肢入镜 20/75。本侧另用相同数据逐条复算整轮：`side_audit2` 为 22/226 控制目标有效、21 入镜通过；`side_audit5_wide` 为 367/572 控制目标有效、75 入镜通过，292 份控制有效但入镜未通过，与对方新增统计一致。不是新的识别或硬件验收。
- 稳定公共订阅、原始帧元数据关联、None/error/停流语义由识别侧继续明确；控制侧接收有界状态、负责速度策略与停止。双方均建议复用同一采集和推理出口，但尚未实现跨模块接线，不能写成已接入。
- 已检查主项目 [自动跟踪启动](/Users/vae/Projects/Iron_Jump/ui/embedded_camera_panel.py:595)：`_show_latest_frame()` 检测到 pose 后可能调用 `_on_ai_go()`。未来 MediaPipe 速度模式须由控制侧实现互斥，防止 UI 重开内置 AI；当前独立工具没有使用这套 UI。
- 已落实对方提出的 FOV 错误处理，见 `69ab8ec`。SDK 初始化含 5 秒设备发现，未来仍须在后台执行；未改主项目控制服务的就绪等待。
- 控制日志当前没有 SDK 每次调用的实际开始/返回时刻，也没有直接保存原始 33 点、callback_time_s 和身份状态。补齐命令时间记录属于控制侧；识别侧配合输出可关联的帧标识及状态。SDK 返回时刻也不能当作物理运动完成时刻，仍需视频与角度反馈核对。
- 识别侧新增的身份重放、79 项测试和依赖环境说明，本侧没有重新运行同一套识别测试或完整身份重放，不将这些交接文字认定为本侧新验收结论。控制侧前轮实机读取的 OpenCV 5.0.0 与其当前记录一致，安装历史不在本轮证据范围内。

本轮控制分支最终 HEAD 为 `69ab8ec`，工作树干净；最新变更尚未部署或合并。下一阶段优先对齐原始元数据与失效结果出口，再在单一控制方下验证完整取景余量与较快水平响应。

### 主动协作第 1 轮：公共姿态到速度的有界交接

识别侧正在新增 `LiveWalkingVision.pose_updates` / `LivePoseUpdate`、`PoseFrameMetadata`；已读取当前实际代码，尚待其阶段文档与互审收敛。控制侧新增验证分支 [pose_tracking.py](/Users/vae/Projects/Iron_Jump/camera/pose_tracking.py) 与 [test_pose_tracking.py](/Users/vae/Projects/Iron_Jump/tests/test_pose_tracking.py)，回调只保留最新结果，不调用 SDK 或 Qt；由控制方取出并检查原始时间、帧顺序及时钟 epoch 后生成速度。

本地执行 `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_pose_tracking.py tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py`：44 项通过。新增覆盖显式失效、停止后迟到结果、乱序/旧 epoch、未来或非法时间、元数据缺失、同步降级，以及 1000 次更新只消费最新结果。使用模拟公共数据；尚未作为真实公共出口接线或硬件验收。实现此时尚未提交、部署或合并。

送识别侧审阅：确认毫秒取整的映射时间与原始 callback 时间关系；采用二者较早者判定 250 ms 过期，映射时间仅允许 1 ms 取整误差，原始 callback 不允许来自未来。请确认停止、clock_reset 及旧 epoch 的发布顺序，复核有界交接会否吞掉必须保留的失效屏障。

下一轮控制侧负责：在现有 SDK 子进程内串行处理速度与低频设置，补充启动/停止确认、互斥及调用时间记录；识别侧负责公共出口与元数据，不改其模块。正式 UI 接线前先协调共同基线，保留主分支现有采集/启动修复；取景余量仍待定义和验证。

### 主动协作第 2 轮：失效屏障与 SDK 所有者

已读取 `detect.md` 第 6.5 节及实际公共接口。识别侧只读审阅复现了本侧第 1 轮实现的两个问题：未消费的新帧能被旧帧覆盖，clock_reset 能被后续 pose 覆盖。本侧已按反馈修正：投递时维护 `(clock_epoch, frame_index)` 水位；每次失效递增独立 motion generation，并保留必须消费的零速屏障；停止为终止状态，重置后拒绝旧 epoch。未知同步状态和 degraded 均失效，仅 ready/warming_up 可作控制候选。

新增验证分支 [tracking_runtime.py](/Users/vae/Projects/Iron_Jump/camera/tracking_runtime.py) 与 [test_tracking_runtime.py](/Users/vae/Projects/Iron_Jump/tests/test_tracking_runtime.py)。SDK 所有者 start 前先零速，再关 AI 并设置最大视野；运行时拒绝内置 AI/FOV 竞争，其他慢设置先停转并清空旧目标。模式 generation 阻止上一会话恢复，执行前核验 motion generation；原生调用中发生失效时，在返回后立即补零速。记录 SDK 实际调用起止与错误，但不把 SDK 返回视作物理完成。原生 SDK 阻塞仍无法保证停止，不作已解决声明。

`GimbalSdk.attach(dll, index)` 已实现复用现有控制服务的 DLL 和设备缓存；尚未接到正式进程/UI。当前命令 `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py`：59 项通过；`git diff --check` 通过（新增未知同步状态检查前为 55 项）。其中一次修改测试时错误要求已消费的失效屏障再停一次，出现 5 个失败，修正该测试预期；独立的“未消费屏障不被新 pose 吞掉”回归仍保留。未提交、部署、合并或运行相机。

双方已确认职责：本侧负责 `camera/control_service.py`、`TinySeCameraControl` SDK 方法和 `ui/embedded_camera_panel.py` 运动接线；识别侧负责公共出口及识别测试。下一轮用真实公共对象联合离线测试，随后补进程传输与 UI 生命周期；现场验收仍须完成这些接线及取景策略后安排。

### 主动协作第 3～4 轮：真实公共对象、JSON 与进程/UI 集成

已读取识别側 `detect.md` 第 6.5～6.7 节及实际新增测试；双方多轮主动审阅均未启动设备。本侧已修复对方实际复现的慢设置后旧帧恢复问题：设置返回时记录 `_resume_after` 并再次清空状态，拒绝原始 callback/映射帧时间早于返回时刻的在途结果；另覆盖设置执行期间到达的旧结果。JSON 的 relay 保留完整失效对象（含其原始元数据）与累计屏障序号，不只传 status；无来源 reset 只取消待发命令、不猜测 epoch。带旧来源 reset 不会使当前较新 epoch 长期失效。

控制分支新增 `camera/pose_transport.py`；从主工作树复制当前控制服务/UI基线后，在本分支接线 `camera/control_service.py` 和 `ui/embedded_camera_panel.py`。基线 SHA256 分别为 `0522f8f953b201335b8de25600a1abab3d22322b670e40629492d09849007c40`、`02087fd116a81e4a38e12bad27da7c1c38f25b34fc6bb2b756b05204c9278f36`。保留原 idle 启动等待及采集生命周期；主工作树实现未改，`camera/tinyse_camera.py` 也无需改，直接 attach 现有 DLL/设备缓存。

初版接线：SDK 子进程的主线程唯一调用 SDK；stdin 线程只投递有界姿态，250 ms 自动过期。父进程每 50 ms 发送最新状态，保留失效序号和模式 generation，写队列超过 64 KiB 时合并等待。UI 新增“SDK 全身跟随”，复用原识别实例、关闭内置 AI 自动及直接激活、锁定最大视野；停用后 AI 保持关闭，用户可显式激活原模式。进程关闭异步等待零速应答；退出未收到应答会报无法确认停止，3 秒超时再报告并终止进程，不把终止进程当作物理停转证据。`tracking_event` 输出原始 33 点/全部元数据、决定及速度调用起止，供联合记录。

可复跑生成器：[prepare_tinyse_integration.py](/Users/vae/Projects/Iron_Jump/tools/prepare_tinyse_integration.py)。固定快照 `/private/tmp/tinyse-integrated-20261008-r4` 冻结双方 Python 源码，`control-manifest.json` 列来源/哈希，非代码资产及原始证据为只读引用；它是明确的主工作树识别代码加控制分支增量，不能声称控制分支已包含全部识别成果。

在上述固定目录执行：

```sh
IRON_JUMP_CONTROL_ROOT=/private/tmp/tinyse-integrated-20261008-r4 PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py tests/test_camera_control_service.py tests/test_embedded_camera_panel.py tests/test_live_pose_updates.py tests/test_sdk_tracking_integration.py tests/test_pose_control_contract.py
```

结果：105 项通过，无跳过。包含识别侧新增的 12 项真实公共对象/JSON契约回归及两份保存数据共 798 次输出。首次临时目录漏掉验证工具、异步退出测试仍断言同步退出，另一次模拟子进程遗漏导入路径；修正快照/测试后通过。此前路径未指定导致 10 项跳过，后指定路径但缺 exports 导致 2 项失败，均已在固定快照补齐再实际执行，未拿跳过作为通过。

### 第 5 轮在研：可靠点的取景余量

控制侧新增 `BodyFraming` / `framing_velocity()`，保留原模型及 0.65 质量门槛。核心点中心仍不代表全身完整：分别报告鼻点可靠、四个脚跟/脚尖可靠、可靠点范围、是否能留出每边 6% 余量及当前是否满足余量。鼻点不是头顶，可靠点边界也不是实际人体轮廓，这些是控制辅助指标，需原始图像现场核验。

可靠点接近边缘时，仅该轴取消中心死区，避免“中心在死区但头脚贴边”仍不修正；无法装入余量的近场目标继续居中并提示调整距离，固定最大视野，不请求放大、不降低质量门槛。仅中心位置的 `full_body_target()` 结果保持；新速度策略在边缘场景会与旧 `tracking_velocity()` 不同，识别侧历史 JSON 速度断言需要按新策略审阅，不能默认为完全未改变。

本地纯控制回归（另加 `tests/test_body_framing_control.py`）65 项通过。该新增取景策略尚未加入 r4 快照或现场验证；r4 的 105 项结果仅代表其固定源码。下一步生成新快照、双方复审 UI 启停/模式互斥及余量策略，再决定是否达到邀请现场的条件。所有本阶段控制改动尚未提交、部署或合并，验证分支保留。

### 第 5～6 轮：独立生命周期复现与固定快照回归

识别侧在 r4 独立复跑 105 项通过后，另用真实 Qt/模拟 SDK 复现三项原测试未覆盖的缺陷；本側已读取其临时测试及实际代码，并将三项加入自己的集成回归：进入回放未立即断订阅/停转；异步关闭尚未结束就创建第二 SDK 进程；reader 在日志处暂停期间模式切换，旧 packet 被用 `self.generation` 重新标成新会话。以上是 r4 的已复现问题，不拿 105 项通过覆盖这些失败。

本侧修复：回放立即停止原识别会话并 detach/end_tracking，回实时画面新建会话；`_closing_control` 屏障使重启、取消、换相机等待旧拥有者 closed/停止应答，停止未确认时阻止自动重启；旧 sender 的错误、结果及日志不影响当前会话。runtime 永远使用 packet 自己的 generation，并以短状态锁保护 generation/mailbox/屏障/设置完成时间；日志和原生 SDK 调用不持该锁，执行前和返回后再次检查原 mailbox、motion generation、模式与原始年龄。设置返回非零也视为失败停止，不继续跟随。

中间 r5 回归曾出现 5 项失败：新增复制测试漏 import 的 2 项、packet retag 的真实 1 项、采用新边缘策略但识别侧测试还冻结旧速度预期的 2 项。随后补齐测试 import、修复 retag；识别侧自行更新其速度预期，并增加独立“旧中心速度为 0，新边缘修正 pitch=4，原始 33 点不变”的回归，未改模型。这些修复均已纳入固定 r6。

固定新快照 `/private/tmp/tinyse-integrated-20261008-r6`，生成命令同 r4，仅改 output；`control-manifest.json` 包括源码及验证分支的 wrapper DLL 来源/哈希（DLL 没有新原生变更）。在此目录执行：

```sh
IRON_JUMP_CONTROL_ROOT=/private/tmp/tinyse-integrated-20261008-r6 PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py tests/test_body_framing_control.py tests/test_camera_control_service.py tests/test_embedded_camera_panel.py tests/test_live_pose_updates.py tests/test_sdk_tracking_integration.py tests/test_pose_control_contract.py tests/test_vision_service.py tests/test_live_walking_vision.py tests/test_vision_framing.py tests/test_vision_time_sync.py tests/test_camera_analysis_frames.py tests/test_tinyse_camera_capture_recording.py
```

结果：**218 passed、2 subtests passed，5.74 秒，无跳过**。这是显式混合源码的离线集成回归，包含真实 QProcess/serve 协议及模拟 native SDK；尚未部署、实机验收或正式合并。已将 r6 路径、来源清单和审阅范围发给识别侧，等待其第 6 轮独立复验；若无新的阻断问题，下一阶段准备现场验证包及验收动作。验证分支仍保留，主工作树控制实现与 `detect.md` 未由本侧改动。

控制侧上述接线已固定提交 `336a3da`，包含当前控制服务/UI基线及控制增量；识别新接口仍来自明确的主工作树快照，没有自动复制/提交其模块到控制分支。r6 的 226 项 manifest 本侧独立逐项核对全部匹配；wrapper SHA256 为 `c05b4d551fd5ba178a3bfce2cef9f35c81fd2322c010756c53114d924415bfaf`。旧 r4 的资产引用主分支旧 DLL，不含新增速度/缩放 ABI，模拟通过不能证明它能实机运行；r6 已显式选用新 DLL，尚未在 Windows 执行此组合。

### 第 6～7 轮：假停止应答与整个应用退出

识别侧在 r6 独立确认此前三项缺陷已修复，又通过真实子进程与跨进程持久模拟设备状态复现：旧 worker 非零速度后崩溃；`end_tracking()` 无意重开子进程；新 worker 的 `tracking_stop` 在 runtime=None 时不调用零速却回复 0，模拟速度仍非零。本侧实读代码确认该路径，并修复为：任何 tracking_stop 必须 attach 当前同一 DLL 并实际零速后应答；父进程发现 SDK 进程已退出时明确报告停止未确认，不自动重开拥有者。停止应答只证明命令返回，不证明物理完成。

同时核对正式退出链：`MainWindow.closeEvent()` → `ExecutionView.reset()` → panel.shutdown() → 原代码 event.accept。异步 SDK 退出尚未结束便退出 Qt，存在提前销毁进程的路径。本侧仅在控制 worktree 复制主窗口当前基线（SHA256 `ebc4f66b9d7130cb528c4fe9efa5098c8bcd2f8f21b6a4cabb743b86502d35f8`），增加退出屏障；原声音、会话、采集及其它资源清理顺序保持且只执行一次。SDK 尚未 closed 时忽略窗口关闭，保留 Qt 事件循环处理停止应答；已确认后完成关闭，未确认则提示并保留窗口，操作者检查后再关闭。主工作树 `ui/main_window.py` 未改。

新增控制回归：首条 stop 也实际 native zero、end_tracking 不在死进程后自动重开，以及真实 MainWindow 的延迟关闭/失败提示；文件为 `tests/test_sdk_tracking_integration.py`、`tests/test_main_camera_shutdown.py`。固定快照 `/private/tmp/tinyse-integrated-20261008-r7` 包含这些增量。沿 r6 测试命令将两个 ROOT 和 cwd 改为 r7，再追加 `tests/test_main_camera_shutdown.py tests/test_main_window_navigation.py /Users/vae/Projects/Iron_Jump/exports/tracking_diagnosis_20261008/test_sdk_lifecycle_review.py`，另设 `IRON_JUMP_INTEGRATION_ROOT=/private/tmp/tinyse-integrated-20261008-r7`。

结果：**240 passed、2 subtests passed，15.08 秒，无跳过**。包含识别侧持久的四项独立生命周期复现；没有原生相机/模型推理/现场测量。`336a3da` 后的停止/主窗口增量此时尚未提交或部署，r7 固定代码已送对方独立复核。下一阶段由本侧准备唯一 Windows 验证包，识别侧不同时开设备；现场通过后才按用户要求合并 vae、删除验证分支。

### 第 7 轮收敛与 Windows 候选准备

已读取识别侧 `detect.md` 第 6.10 节；对方独立核对 r7 的 227 项哈希、运行 236 项及 2 子测试，并另运行四项持久失败复现后全部通过。此前代码阻断已关闭，可准备现场验收；这与本侧含四项复现的 240 项结果相容，不把两边数量重复相加。双方不再无理由重复已稳定的本地套件。

控制侧停止/主窗口增量已提交 `924fe47`。新增 [tinyse_shared_tracking_validator.py](/Users/vae/Projects/Iron_Jump/tools/tinyse_shared_tracking_validator.py)：直接运行真实 EmbeddedCameraPanel 与原识别出口，记录 raw MJPEG/CSV、`events.jsonl`（33 点/原始时间/epoch/generation/身份/入镜与 SDK 调用）、首尾图及 report，等待 SDK closed/应答再退出。`--preview-only` 在采集前撤销速度订阅并停跟随，固定最宽取景做准备画面；不是再次使用独立 1080p 推理适配器，也不冒充完整正式 MainWindow。该工具完成 `--help`/语法核对及 Windows panel 导入/构造；实际采集运行结果另记，不能仅凭工具代码宣布实机通过。

唯一 Windows 候选目录：`C:/Users/86150/TinySE-gimbal-validation-20261008/shared-tracking-924fe47`，未覆盖 `E:/OptoJump/Iron_Jump`。上传 ZIP 9,725,286 字节，SHA256 `ab7182ffe2662d46b0f3671ca78dd5b98e5a72ae11d14fc3e807cfffb281e334`；234 个包文件逐项远程哈希全部通过，原模型一致，新 wrapper 在 Windows 实际加载且四个新增 ABI 符号齐全（没有调用设备刷新/运动）。来源与包哈希见 [package-manifest.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/package-manifest.json)。

Windows 实际依赖：Python 3.11.15 / PySide6 / OpenCV 5.0.0 / MediaPipe 0.10.35。首次离线回归 `67 passed、12 errors`，原因是没有 pytest-qt 的 qtbot fixture；只在候选目录 `test-deps` 安装 `pytest-qt==4.5.0 --no-deps`，不改正式环境。补跑通过：

```powershell
# cwd 为上述候选目录；PYTHONPATH 指向其 test-deps。
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& 'D:/conda/envs/pydantic_ai/python.exe' -m pytest -q -p no:cacheprovider -p pytestqt.plugin tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py tests/test_body_framing_control.py tests/test_camera_control_service.py tests/test_sdk_tracking_integration.py
```

结果：**79 passed，8.68 秒，无跳过**，全部为模拟硬件的 Windows 控制/Qt/协议回归。原始输出已取回 [windows-offline-tests.txt](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/windows-offline-tests.txt)。offscreen 构造有 Qt 缺字体目录提示，未阻止构造/测试；不据此判断实际可见桌面的字体或显示质量。

唯一现场安排由本侧提示用户就位；识别侧不部署或开设备，只读候选录像/日志评估严格下肢入镜及身份。准备阶段只读进程检查未列出匹配的已知相机进程；并非证明所有未知应用不存在。3 秒 preview-only 准备轮已启动，结果待记录；没有发起新的非零跟随测试。现场候选成功并经用户动作/视频验收后，核对共享文件基线只合入控制增量，保留主工作树全部既有识别/采集/调度及其他改动，再删除验证分支。

### 第 8 轮：实际准备画面与可见现场工具

3 秒准备轮已真实完成，命令：`python -u -m tools.tinyse_shared_tracking_validator --preview-only --duration 3 --output exports/preview_ready_01`（上述 Windows 候选 cwd、offscreen）。报告无错误、录制开始成功、收到 SDK 停止应答、进程正常退出；取回原始 `events.jsonl` 逐条复算：四次速度调用全为 `[0,0]`，非零为 0。证据：[report.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/preview_ready_01/report.json)、[events.jsonl](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/preview_ready_01/events.jsonl)、[实际末帧](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/preview_ready_01/end.jpg)。图像已查看：人坐在桌前，屏幕/桌面遮挡腿脚；当前不是全身测试站位。此轮没有证明非零闭环、身份准确或物理停止，仅证明新组合可采集、记录并完成零速退出路径。

识别侧第 8 轮指出记录工具尚无 show。原准备轮确为隐藏取证，现新增 `--show` 在当前交互桌面显示同一 panel（1280×800），不另开采集；窗口标题/提示音依次请求正面10s、侧面10s、回正面10s、慢横移15s、较快横移15s、短时离开/返回15s，共75s。阶段标签只是动作请求，以实际图像核对完成，不能拿标签充当真值。必须用户准备后才启动非零跟随，避免来不及动作。

薄工具增量已提交 `7815713`（当前控制 HEAD，核心控制与 r7/Windows 79 项已验源码相同）；已更新独立候选，增量 SHA256 `473256de4b9ee1b99168b7e2738a822f0af79e5cdac61e426f47fbca0dbde540`。保留原包清单，并以 [package-delta.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/package-delta.json) 区分新工具，不宣称旧 ZIP 已含增量。窗口关闭先 shutdown，Qt 循环仍等 SDK closed 再写报告退出。help/差异格式检查通过，交互式 show 路径尚待现场。

Windows 既有诊断任务 principal 已只读核对为用户86150 / InteractiveToken；quser 在该环境不存在，不将该命令失败解释为无人登录。新任务 `IronJumpTinySESharedField20261008` 只作手动启动候选，使用独立 launcher、明确 cwd、IgnoreNew，无定时触发器，不运行跟随。待用户到画面左侧蓝墙前、离相机稍远且无遮挡处，让头到脚入镜后，由本侧启动唯一75秒现场轮；成功后交识别侧只读评估，再按验收结果合并/清理。

已核对 explorer 在 SessionId=1；现场 launcher 显式设 `QT_QPA_PLATFORM=windows`、`PYTHONUTF8=1`，不继承准备轮 offscreen。已在本控制对话发出唯一现场就位请求，等待用户确认；未启动手动任务、未开始75秒非零跟随、未合并或删除分支。

### 第 9 轮：首轮联合实机结果与动作提示修正

用户回复就绪后，本侧手动启动唯一任务，实际执行 `python -u -m tools.tinyse_shared_tracking_validator --show --duration 75 --output exports/field_walk_01`。任务正常结束（LastTaskResult=0），报告录制开始成功、errors=[]、sdk_stop_reply=true、stop_unconfirmed=false；75.087s 保存7509帧原始MJPEG/CSV，Windows原录像1,132,129,533字节保留。SDK停止应答仍不是独立物理停转测量。用户随后明确反馈“转动一切正常”，这作为操作者现场观察记录，不代替遗漏动作的验证。

本地原始证据见 [field_walk_01](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_01/report.json)；已取回 events.jsonl、首尾图、capture.csv。每5s按CSV offset/length直接读取原始JPEG，保存15帧及 [索引](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_01/samples/index.json)、[联系图](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_01/samples/contact_sheet.jpg)。实看画面：开始仍坐桌前，约5～35s站立/转身，约40s之后有弯腰、抬腿及更近站位；50/60s头部被上边界裁切。背景取景确有改变，与实体云台转动相符；没有按预设时间确认快慢横移或离开恢复。

事件逐项复算 [control_metrics.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_01/control_metrics.json)：1243个控制决策，1063 tracking、138 invalid_target、42 loading/ready/no_pose；1202 pose输入；635次非零速度调用，pan最大绝对值81.147、pitch11.334；最后两次SDK速度调用为零。tracking日志观察时间减原始captured_at的中位112.814ms、最大158.701ms（含日志传输时间，不标为原生调用前的精确年龄）；速度调用返回时长最大5.091ms。可靠点余量546/1063、容纳余量835/1063，严格下肢ready876/1202、身份stable994/1202；这些是各自日志判定，不能互相替代、不能宣称头顶真实完整或左右身份准确。

用户反馈本轮没有看到标题或听到声音，自行做了正侧面与走路。日志六个requested_phase确有发出，只证明程序内部设置，不能证明用户看到或执行。用户现要求“标题放大，不需要提示音”；仅修改本侧 `tools/tinyse_shared_tracking_validator.py` 的 --show：在同一Panel顶部插入32px高对比动作/秒数大字，去掉winsound调用，保留原相机/控制/识别路径。已在本地offscreen真实Panel构造检查：label可见、布局首项、1270×73，预览1270×717，最长阶段文字可容纳；[截图](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/large_phase_label.png)已实看；help及git diff --check通过。该大字路径尚待Windows实际显示确认，未用本地截图冒充现场。

已发送识别侧只读复核请求及证据路径，请其独立核对实际动作、33点/帧时间、侧面质量、严格下肢和身份状态，尤其裁切是距离/视野不足还是控制问题；对方不打开相机、不部署第二进程。待验证：大字是否现场可见、最大视野下距离足够时的快慢横移/短时丢失恢复、正式应用停止/回放/重启及退出；不以本轮未执行动作提前验收。识别侧结论回传后再决定补测/修改，本侧只维护control.md，未修改detect.md或识别模块，尚未合并或删分支。

大字无声工具现已提交 `e74a7b8` 并上传同一Windows候选；远端实际读取与 [package-delta-large-label.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/package-delta-large-label.json) 哈希完全匹配，文件SHA256 `204a2cd2a8d88bd40fba9b7a100a3e9c0e77a1f238015e2b68c80f6332d847cf`，远端compile语法核对通过，未启动新的相机进程。旧ZIP及781薄增量的证据清单保留，当前工具以此新清单为准；核心跟随策略未变。

识别侧独立脚本 [audit.py](/Users/vae/Projects/Iron_Jump/exports/tracking_diagnosis_20261008/field_walk_01/audit.py) 已实读：按epoch/frame_index去重943姿态，942与录制CSV精确匹配且sample_time差0，1帧录制前；635非零SDK调用全部按captured_at关联到原始帧，原始callback/mapped较早值至SDK started_at年龄P50 107.247ms、P95 143.917ms、最大156.197ms。与本侧较粗的日志观察年龄统计相容，二者不可混称。5～25s严格下肢253/253；45～50s为0/63，控制core门槛更宽，没有矛盾。

对方指出另一待验证机制：弯腰可靠点边界中心下移，云台随之下俯，重新直立后头部可能出框；高置信但越界的鼻点被 `_visible` 排除，剩余可见边界不能保证头顶恢复。实际40s可靠点高度已.927>.88，说明更近站位也可能参与，不能归因唯一原因。本侧核对决策：48～54s鼻不可见时pitch主要-3.2～0，已有小幅向上恢复；55/62s弯腰pitch可达+7.6/+11.3，支持俯仰跟随低姿态。尚不添加未经验证的历史身高/头顶估算，先双方确认补测站位和目标动作，以图区分限制与闭环缺陷。

已按具体pose.frame_metadata.frame_index在原始MJPEG中取28张精确推理帧（27～34、68～74s及关键裁切/弯腰时刻），每帧assert CSV sample_time等于原metadata，并保留请求和索引；提取操作只读取录像、不打开设备。用于下一轮双方复核，不能把按时间最近选择的帧当连续完整视频。

### 第 10 轮：按现场反馈加快水平跟随

用户认可本轮“检测效果非常好，追踪也不错”，另要求水平速度更快。本侧最小调整 `vision/gimbal_tracking.py:TrackingSpeeds` 默认pan_gain **240→300（+25%）**、pan_max **90→120**；俯仰80/30、死区.06、原33点质量/250ms时龄/模式与停止屏障不变。上一轮实测请求最大pan81.147低于旧cap，单加cap不起作用，因此同时加gain；同误差下命令增幅不能直接当实体响应精确增幅。

同步 `tools/tinyse_gimbal_validator.py` 独立CLI水平默认，更新自己的 `tests/test_gimbal_tracking.py`、`tests/test_pose_tracking.py` 的明确速度预期；`tools/tinyse_shared_tracking_validator.py` configuration新增实际TrackingSpeeds和controller/tool源码SHA，防止旧包目录名误认版本。共5文件13增8删，提交 **88c630e**，控制worktree干净。大字无声e74增量已包括其中；未修改识别侧模块或detect.md，主工作树实现尚未合入。

新固定快照 `/private/tmp/tinyse-integrated-20261008-r10`（当前主工作树识别源码加控制增量）已回归：

```bash
# cwd=/private/tmp/tinyse-integrated-20261008-r10
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
IRON_JUMP_CONTROL_ROOT=/private/tmp/tinyse-integrated-20261008-r10 \
/Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider -p pytestqt.plugin \
 tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py \
 tests/test_tinyse_dshow_capture.py tests/test_body_framing_control.py tests/test_camera_control_service.py \
 tests/test_sdk_tracking_integration.py tests/test_pose_control_contract.py
```

结果 **92 passed，4.32s，无跳过**。对field01原始pose按epoch/frame_index去重后，943帧中的835有效控制目标逐帧新旧计算：pitch完全一致、非零pan全为旧值1.25，最大81.147→101.433、零速判定不变；见 [faster_pan_replay.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_01/faster_pan_replay.json)。旧值未触顶；重放不模拟更快相机产生的后续新图像，现场超调与实际响应仍待验证。

Windows 5文件增量ZIP 11,899字节，SHA256 `004ac39b559b281cbda5ec48cde85ee65895e1848f267d0bd848bd4ac34bb9be`，现部署至原候选目录；远端包哈希、逐文件哈希、import默认300/120全部通过。来源：[package-delta-faster-pan.json](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/package-delta-faster-pan.json)。相同8个测试文件，Windows用原D:/conda Python及候选test-deps执行：**90 passed、2 skipped，8.10s**；原始输出：[windows-faster-pan-tests.txt](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/windows-faster-pan-tests.txt)。两项为识别侧历史side_audit2/side_audit5_wide重放，候选未包含这些历史证据而skip；实读 `test_pose_control_contract.py` 的缺文件跳过条件已确认，本地这两项执行通过，不把Windows跳过说成通过。

已读识别侧detect.md6.12及双方消息：默认pan未被识别模块冻结，pitch边缘回归仍4；对方同意先以标准距离、大字、明确动作补测，不立即加入未经验证的历史身高/头頂估算。若合适距离自然行走仍裁切或恢复不足，再基于保存时序修控制。更近/大幅弯腰的裁顶风险仍保留，不能宣称所有姿态全身取景已通过。另一方正在复核28张精确推理帧及新增参数的public/JSON契约，不打开相机。

下一轮拟唯一手动任务 `IronJumpTinySESharedField02_20261008`、输出 `exports/field_walk_02`，75s、windows平台、InteractiveToken、同一Panel大字无声；准备任务不等于启动，仍须用户确认就位。标准站位头脚有余量，按大字完成正侧面、普通/较快横移、离开返回，核对新水平速度/停止。现场与剩余生命周期证据收敛后才整合vae并删除验证分支。

识别侧独立完成r10 public契约 **13 passed，0.48s**，并独立实际源码重放943去重姿态，835目标、pitch不变、pan1.25且未触120cap，与本侧重放一致。已回传28张精确原帧的侧身膝/踝质量问题（strict.65和identity.60门槛不同，不是矛盾），70/71s鼻在画面内但头顶裁切，证实可靠鼻点不是实际头顶；没有新代码接口阻断。任务准备后已核对XML无Triggers、InteractiveToken、State=Ready。用户再次明确“已就位，可以开始”，本侧现在手动启动唯一field02；现场结果待采集，未宣称新速度已验收、未合并。

### 第 11 轮：提速实机验收与用户确定的范围

field_walk_02已完成：7505帧/75.044s，原始MJPEG 1,130,540,577字节保留Windows；report errors=[]、sdk_stop_reply=true、stop_unconfirmed=false。configuration实际记录300/120及controller e52b9f...、tool1f9946...、原模型5134...，与已部署增量一致。1240控制决策1160 tracking、40 invalid_target、30loading/8ready/2no_pose；708非零SDK调用，maxpan101.049，末两次实际速度调用为零。证据 [report](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_02/report.json)、[events](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_02/events.jsonl)、[25张每3s样本](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_02/samples/contact_sheet.jpg)。实看横移和到门边再返回，仍可见人，未真正空画面；启动后的no_pose恢复不作现场已验。

用户对“大字可见/横移返回/新速度/过冲摆动/停止”整体回复“**一切正常，效果非常好**”，接受更快水平跟随。后续明确两次：极端情况下裁头合理，优先髋部以下再上半身；“刚才的就挺好，头裁不当作失败就好了，不需要大规模改动”。因此保持已验算法、模型、阈值，不添加历史身高或头顶估计。正常最大视野尽量全身、极端裁头不单独阻断；距离近到髋以下也无法容纳仍是物理限制，不能保证任意距离完整脚部。

识别侧独立field02精确分析：945去重姿态，944录制内CSV/index/sample_time一致；708非零调用都有原帧，年龄P50 93.04/P95 130.36/最大147.83ms。严格下肢831/944、core913/944、可靠点余量645/944、身份stable796/unavailable76/ambiguous72。17～23s侧身左膝低质量明显（strict26/74），50～62s含swap_suspected/swap_detected，保持为识别侧限制，不误称左右触地准确性已验收；原模型不变、头裁不作为额外失败。双方此阶段接口/职责一致，识别效果反馈与这些逐帧指标并不互相替代。

合并前仅补一轮本侧自动真实Panel/SDK生命周期：显式停止→恢复→回放停跟随→返回实时新Vision→旧owner closed后重启新owner→关窗。脚本 [run.py](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/panel_lifecycle_01/run.py)，90个field02原始帧生成短AVI fixture并保留索引，记录SDK PID/活跃集合/停止应答/所有原生调用；独立候选执行，不需用户再做动作、无产品算法修改。完整MainWindow实体退出未复测，guard有真实Qt模拟回归证据，不能等同独立Panel实机退出。

识别侧现独占主树索引准备必要public/识别/采集依赖提交；本侧只读共享基线，三个SHA仍完全匹配0522/02087/ebc4。主树其它hardware/engine/agent/thesis/LED和混合测试改动保留，不git add全部；控制侧尚未操作主索引或合并，等生命周期完成及对方范围提交后以三方控制增量整合，保留其它脏改。

自动生命周期已在Windows完成exit0：错误为空，SDK PID24976/5380，最大同时owner=1，4个tracking_stop成功应答，两个owner closed均确认零速，stop_unconfirmed=false。旧owner closed时间72048.1927077，新owner started72048.1984884，顺序正确。实际阶段含explicit_stop、resumed_live、entering_replay、replay_hold、returned_live、restarting、restarted_live、closing；实读原始日志复算：回放进入前最后速度为零，2.064s回放持有期间没有新的速度调用；runtime inactive不持续重复发零是预期，不能要求回放期间必须有zero call。证据 [report](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/panel_lifecycle_01/report.json)、[audit](/Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/panel_lifecycle_01/audit.json)。没有打开完整MainWindow或测实体停止瞬间，用户停止/转动满意反馈另记。

为保留既有主树UI工作，已备份4个共享文件至 `exports/control_integration_20261008/merge_preservation/before/` 并记录SHA。MainWindow的控制guard补丁由“当前main基线→验证branch最终文件”生成，实际可直接apply到Git HEAD原文件；准备索引只纳此guard，当前MainWindow其它5增10删的既有UI修改保持dirty。Panel基线中的原识别出口和异步SDK启动是本次必要运行依赖，随控制融合保留，不回退HEAD旧同步SDK/无vision版本。尚未操作主索引，待识别侧提交完成后开始合并。

### 第 12 轮：真实合并、干净交付验证与分支清理

识别侧先提交必要依赖 **e88c3c1**（20文件），仅纳public/帧metadata/640适配器/调度与身份恢复/采集显示、对应独立回归，以及execution_view两个识别接线hunk；其它hardware/engine/agent/论文/LED/视图文案及混合测试均保留未提交。对方提交完成后明确释放索引，本侧再执行控制合并，不并发stage。

为避免重叠主树未提交文件被覆盖，仅对Panel/MainWindow/control_service/test_camera_control_service四文件做专用targeted stash，另完整字节备份至merge_preservation/before，记录原SHA；其余159个dirty/untracked文件在合并前后SHA全部一致，识别侧又独立复算changed/missing为空。正常 `git merge --no-ff --no-commit codex/tinyse-mediapipe-gimbal-validation` 无冲突；不是假ours merge。Panel旧识别/异步SDK基线是功能必要依赖，完整保留。MainWindow索引先恢复mainparent再apply仅20行closeguard，工作文件仍保留原启动入口/设备质量文案5增10删，未混入控制提交。

主工作树运行第7轮17组与4项独立生命周期脚本（两个ROOT改为main）：**240 passed、2 subtests，15.12s，无跳过**。再通过write-tree/archive导出不含其它脏工作的纯索引副本 `/private/tmp/tinyse-indexed-merge-20261008`，运行同组加vision_event_scheduler：发现2个旧Panel测试不适配已纳入的必要基线（Record旧文案、同步SDK假mock），其余240通过/2子测试/2历史证据skip。只从现有正确工作文件选择这两个测试函数到索引，保持其它104行新增Panel测试dirty；无新产品实现。不能把工作区通过代替干净交付证据。

修正后纯索引副本 `/private/tmp/tinyse-indexed-merge-20261008-r2` 重跑同18组：**242 passed、2 subtests、2 skipped，13.64s**，skip仅因干净副本没有side_audit2/side_audit5_wide历史exports，已有本地含证据契约实际通过。测试命令用第7轮17组（不含exports独立脚本），追加tests/test_vision_event_scheduler.py；cwd/IRON_JUMP_CONTROL_ROOT设该r2，venv保持main、QT_QPA_PLATFORM=offscreen/PYTHONDONTWRITEBYTECODE=1/no:cacheprovider。最终索引tree **a363001c16098d4088ef338373dc10b6bfa488d9**，与真实提交树逐字一致。

功能真实双父合并 **ae17a6c0d3af9fa3dfeff70571fdd5bae369e2e3**，parents **e88c3c1** + **88c630e**；23文件控制/必要共享基线/两既有测试修正，没有混入MainWindow其它文案或其它未提交任务。Git ancestor核对通过，测试树与commit树一致。对方独立核对cached范围、原模型SHA、识别父提交及shared当前源码，未发现新阻断。专用stash仅在完整备份及保留核对后删除，原四文件备份仍在本地exports。

验收结论限定相机SDK二维跟随及共享识别运行链：现有SDK足够，最大视野/zoom1不放大，水平300/120已现场接受，俯仰不改；用户要求极端裁头可以接受、髋以下优先，保留刚才方案，无历史身高/头顶估算等大改。Panel实机停止/回放/重启/关窗通过；完整App实体退出、真正空画面恢复、左右触地准确率和全部侧面识别不扩宣已验收。Windows独立候选及原录像保留，正式E:/OptoJump/Iron_Jump未覆盖；固件未刷入。

Codex app现已确认archived_worktree（原root身份保留，可恢复），git worktree list仅剩main；ancestor核对后安全 `git branch -d codex/tinyse-mediapipe-gimbal-validation` 已删除88c630e验证分支，git branch列表再次确认不存在。控制实现历史通过ae17a6c双父合并保留。识别侧仅提交detect.md完成收尾后已释放索引，本侧再提交本文件最终状态。

2026-10-08 用户要求直接push：执行 `git push origin vae/iron_jump` 成功，远端由cc0bc7f更新至7ba8f07，包含已验收的相机集成与双方进度记录。`git rev-parse HEAD origin/vae/iron_jump` 两者一致，索引为空；其它未提交改动未纳入推送。此操作未更新Windows正式运行目录，完整主界面现场检查仍待进行。
