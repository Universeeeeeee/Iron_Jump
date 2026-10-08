# 相机关节点识别工作进度

最后更新：2026-10-08（Asia/Shanghai），当前阶段为第 10 轮水平提速增量的独立回归，等待标准动作复测；接口见 6.5 节，固定候选独立回归见 6.10，Windows 准备见 6.11，首轮真人结果见 6.12，精确原帧及提速复核见 6.13。本文件由识别侧 Codex 对话维护；每完成一个重要阶段，更新状态、证据、修改、验证及协作事项。控制相机运动由另一个对话负责，本对话不修改 `control.md`。历史现场、离线复现及尚待验收的结论分别记录。

协作方向：用户要求逐步摆脱内置 AI，使用当前识别结果自行驱动 SDK 速度控制，最终以 `vae/iron_jump` 为主整合。本文件是双方主要交接依据；重大变更通过各自文档及主动互审同步。识别侧保留原模型、640 整图等比缩放及阈值；控制侧负责 SDK 速度、运动、取景和模式互斥。内置 AI 响应慢是用户现场反馈，本阶段没有完成同条件速度 A/B，不提前宣称 SDK 正式方案已更快或已上线。

## 1. 当前任务及完成状态

目标：在保留原模型、推理参数和识别阈值的前提下，查明主界面预览“正面稳定、侧面几乎没有骨架”的原因，随后验证运动中的识别连续性及左右脚触地核验。

用户明确要求：不要修改原来的模型；此前稳定的参考界面是映衡主界面中的相机预览。不要用独立 MediaPipe 工具的配置冒充主界面的历史配置。

| 阶段 | 状态 | 结论或剩余工作 |
| --- | --- | --- |
| 原模型及主界面识别流程核对 | 已完成当前版本核对 | 模型文件、适配器及识别阈值在本次对照中未修改；尚未完整复原用户记忆中的更早稳定版本 |
| 原始输出与显示层分离检查 | 已完成 | 最近一次隐藏低质量灰点的修改，没有改变有效点或连线判定，也不改变模型输出 |
| 下半身取景下的侧面问题复现 | 已完成 | `side_audit2` 的实际侧面片段中，膝、踝和脚部置信度低，部分预测位置明显错误 |
| 最大视野、标准跟踪及调整站位后的复测 | 已完成短时对照 | `side_audit5_wide` 的实际侧身片段 75/75 次返回姿态，8～10 个下肢点达到原阈值 |
| 严格单变量根因验证 | 未完成 | 跟踪模式、机位/朝向和站位同时变化，不能把改善独立归因于 FOV 或某一个设置 |
| 动态跟随中的完整取景、遮挡恢复 | 待验证 | 需控制侧提供稳定取景，再测沿跑道行走及双腿交叉 |
| 左右脚身份连续性及触地同步准确性 | 未验收 | “显示骨架”和“置信度达标”均不等于左右脚触地判断正确 |
| 跨分支接口与职责复核 | 已完成一轮只读检查 | 已确认坐标约定及数据结构一致；时间戳关联、控制模式切换和不同有效性指标仍需对接 |
| 原始姿态对控制目标条件的离线检查 | 已完成 | 对 572 次已有输出，控制目标有效 367 次，完整下肢入镜通过 75 次；不能用控制目标有效率代替识别验收 |
| 公共结果及原始帧元数据出口 | 已实现并通过离线回归 | `pose_updates` 发送姿态、身份、入镜及明确失效状态；保留原始时间/索引与时钟 epoch，见 6.5 |
| SDK 消费识别结果的协作审阅 | 第 8 轮准备工具复核完成 | 公共对象/JSON/有界交接及已发现生命周期故障在固定 r7 独立复验，见 6.10；现场工具显示/关闭/阶段提示已只读核对 |
| 正式 UI/SDK 接线与动态实机验收 | 首轮真人转动/识别运行完成，完整验收未通过 | `field_walk_01` 75秒录制和635非零调用可关联原始帧；原始图有头部裁切，慢快横移/离开恢复与正式App生命周期未验收，见 6.12 |

当前判断：证据优先指向取景完整性和侧面遮挡；暂没有必须更换模型的证据。本轮没有显示明显的识别结果排队，但不能据此宣布所有同步或端到端延迟问题已经解决。

版本基准：分支 `vae/iron_jump`，HEAD `cc0bc7f9f9bee2bf24867c18fa16e942d4489a96`。工作树存在大量此前未提交修改；现场代码不能仅用干净 HEAD 代表。当前公共出口代码在主工作树仍未提交，已纳入控制侧部署的独立验证候选，尚未合并正式控制增量。

## 2. 已证实的事实及对应代码位置

代码行号为本次更新时的定位提示，后续以函数名为准。

| 已证实事实 | 代码位置 / 证据 |
| --- | --- |
| 主界面使用 `pose_landmarker_full.task`，宽度超过 640 的推理输入会等比缩到 640 | `vision/live_walking.py:15` `_PreviewAdapter`，模型路径见第 63 行；640 缩放是否影响远距离侧面尚未验证 |
| 适配器使用 MediaPipe Tasks VIDEO、单人姿态，并保留原始 33 点 | `vision/mediapipe_pose.py:43` `open()`、第 65 行 `PoseLandmarkerOptions`、第 81 行 `infer_bgr()` |
| 单点质量为 `min(visibility, presence)`；当前相关质量阈值是 0.65 | `vision/foot_reference.py:64` `Landmark.quality`、第 29 行配置；`vision/pose_overlay.py:22` |
| 连线要求两端都达标；新版隐藏低质量点和对应 L/R 标签 | `vision/pose_overlay.py:56` `draw_pose_overlay()`，第 84、90、98 行。对 `side_audit2` 的全部 170 份非空输出，修复前后的有效点和连接规则一致 |
| 预览会隐藏年龄超过 250ms 的姿态；入镜检查还要求点有限、在图像内且质量达标 | `vision/live_walking.py:206` `display_state()`；`vision/framing.py:35` `check_framing()` |
| 默认主界面跟踪子模式仍是下半身 4；诊断窗口临时选择标准 0 | `ui/embedded_camera_panel.py:42`、第 373 行；发送入口为第 747 行 `_on_ai_go()`。本轮未永久更改生产默认模式 |
| 应用最大视野选项为 FOV=0，界面标签“86°”；这只是选项映射，不能当作实测光学角度 | `ui/embedded_camera_panel.py:35`、第 676 行 `_apply_control_settings()`；两轮都请求过 FOV=0，因此不能声称只是“从小视野改到最大”导致改善 |
| 左右脚触地核验还要经过身份、采样间隔、时钟及事件窗口检查 | `vision/live_walking.py:24` `classify_walking_contact()`、第 80 行 `submit_camera_frame()`；`vision/leg_identity.py:41` `LegIdentityAnalyzer` |

原模型 SHA256：

```text
models/pose_landmarker_full.task
5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1
```

当前本地与本轮 Windows 部署已核对一致；`side_audit2`、`side_audit5_wide` 各自采集前后哈希一致。MediaPipe 适配器与 2026-10-07 交接包源码清单一致；该历史清单没有模型文件哈希，不把本次核对扩展成“所有历史模型版本都完全相同”。

### 实机证据

证据根目录：[exports/tracking_diagnosis_20261008](../../exports/tracking_diagnosis_20261008/)。方向依据实际图像核对，不能直接用工具的阶段标签作为实际方向。

| 实际画面片段 | 推理返回姿态 | 原阈值下的下肢点 | 结果年龄 |
| --- | --- | --- | --- |
| `side_audit2` 正面 7.5～10.5s | 36/37 | 左右膝质量中位数 0.905/0.932，左右踝 0.913/0.890 | 见该轮 `analysis.json` |
| `side_audit2` 侧面 13～17s | 38/50 | 非空输出仅两髋达标；膝、踝、脚跟、脚尖均低于 0.65 | 中位数 37.1ms，最大 57.0ms |
| `side_audit5_wide` 正面 2～10s | 105/105 | 每次 10 点全部达标 | 中位数 35.0ms |
| `side_audit5_wide` 侧身 28～34s | 75/75 | 8～10 点达标，中位数 9 点 | 中位数 34.5ms，最大 41.3ms |
| `side_audit5_wide` 回正面 38～44s | 75/75 | 4～10 点达标，中位数 9 点，仍有瞬态低质量 | 中位数 35.2ms |

“结果年龄”是当前时间映射下的输入时间戳至推理结束，不是光学采集到屏幕显示的完整延迟；返回姿态比例和置信度统计不是坐标或左右脚分类准确率。

`side_audit2` 记录 151 张抽样图、226 次推理、170 份非空姿态。14.09s 的侧面样本中，预测踝 y=-0.054/-0.070，位于画面外，膝位置也明显不正确；不能降低阈值强制画线。

`side_audit5_wide` 记录 375 张抽样图、572 次推理，572 次均有姿态；保存队列丢帧 0。界面心跳最大间隔约 260ms，监测未见超过 2 秒停顿。只适用于观测时段，不代表长时间稳定性验收。头部重新入镜后侧身结果明显改善，但部分画面鞋底仍贴近底边。

- [下半身取景记录](../../exports/tracking_diagnosis_20261008/side_audit2/RESULTS.txt)、[原始输出](../../exports/tracking_diagnosis_20261008/side_audit2/audit.json)、[显示修复前后对照](../../exports/tracking_diagnosis_20261008/side_audit2/observed_side_paired.jpg)。
- [较完整取景记录](../../exports/tracking_diagnosis_20261008/side_audit5_wide/RESULTS.txt)、[统计](../../exports/tracking_diagnosis_20261008/side_audit5_wide/analysis.json)、[实际转身图像](../../exports/tracking_diagnosis_20261008/side_audit5_wide/side_sequence.jpg)、[同输入对应输出的骨架示例](../../exports/tracking_diagnosis_20261008/side_audit5_wide/side_overlay.jpg)。
- `side_audit1`：用户未完成动作，且工具结束时主动停止预览、留下最后一帧；已标记无效。
- `side_audit3_wide`：取景准备轮，未作为真人方向对照。
- `side_audit4_wide`：用户明确表示来不及采集，已标记无效；不能拿阶段标签或推理数量作为完成动作的证据。

## 3. 已修改文件及原因

以下是本对话相关阶段的修改记录，不是整个脏工作树的归属声明。首次建立文档只新增 `detect.md`；跨分支复核新增离线诊断；当前阶段新增公共出口及测试，不修改 `control.md` 或对方控制模块。

| 文件 | 修改原因及范围 |
| --- | --- |
| `vision/pose_overlay.py` | 隐藏低置信度灰点及对应左右标签，避免只剩散点的误导；原有有效骨架连线阈值不变 |
| `tests/test_pose_overlay.py` | 覆盖低质量姿态不留灰点/标签、可靠姿态正常连线 |
| `camera/control_service.py` | 此前跟踪修复新增控制队列空闲信号；属于控制侧交接背景，后续控制改动由另一对话统筹 |
| `ui/embedded_camera_panel.py` | 此前修复等待 SDK 初始化及默认设置完成后再启动采集，处理取消、切换和失败重试；异步等待不阻塞界面 |
| `tests/test_camera_control_service.py`、`tests/test_embedded_camera_panel.py` | 覆盖控制就绪前不启动采集及相关生命周期回归 |
| `exports/tracking_diagnosis_20261008/pose_audit.py` | 诊断工具：记录原画面和原始输出；后台有界保存；结束后保留预览；记录界面心跳和卡顿栈；增加远程开始、30 秒准备及每阶段 15 秒；最大视野/标准跟踪仅用于诊断 |
| `exports/tracking_diagnosis_20261008/analyze_side_audit.py` | 保存输出的统计及最近一次显示修复前后同输入对照，不重新推理 |
| `exports/tracking_diagnosis_20261008/analyze_wide_audit.py` | 根据实际方向片段统计，并用对应输入的原始输出绘制骨架示例，不重新推理 |
| 各轮 `audit.json`、`analysis.json`、`RESULTS.txt`、图像及 `INVALID.txt` | 保留可核查证据及无效轮次原因；不能删除无效标记后当作验收数据 |
| `exports/tracking_diagnosis_20261008/audit_control_handoff.py`、`control_contract_audit.json` | 本次新增的识别侧离线诊断；仅加载控制侧纯数学目标函数，重放已保存的原始姿态，不重新推理、不调用 SDK，不修改控制分支 |
| `vision/service.py` | 当前阶段新增 `PoseFrameMetadata`，绑定实际进入推理的图像；成功、无人体和错误结果保留同一输入元数据，旧调用兼容；此前 latest-only 修改保留 |
| `vision/live_walking.py` | 当前阶段新增 `LivePoseUpdate` / `pose_updates`；显式通知停止、时钟重置和降级，拒绝旧 epoch 在途结果；不改原模型、适配器处理和触地判定阈值 |
| `tests/test_live_pose_updates.py` | 当前阶段新增原始帧关联、latest-only 丢帧、触地分类兼容、无人/错误、并发停止及同步降级失效回归 |
| `tests/test_live_walking_vision.py` | 模拟服务兼容新增可选 metadata 参数；原有时间与事件测试保持 |
| `tests/test_pose_control_contract.py` | 第 4 轮新增可复跑联合回归：真实本侧公共对象经控制侧 JSON relay/runtime，到模拟 SDK；明确选择控制源码 worktree，避免模块缓存混版；不修改对方模块 |
| `exports/tracking_diagnosis_20261008/test_sdk_lifecycle_review.py` | 第 5 轮独立固定快照审阅：真实 Qt/模拟控制复现回放未立即停止、重启 SDK 拥有者重叠及旧 packet 跨线程重标当前会话；显式指定快照路径，不编辑控制侧实现或测试 |

此前六文件修复的精确范围、前后哈希及备份见 [changes.patch](../../exports/tracking_startup_fix_20261008/changes.patch)、[manifest.json](../../exports/tracking_startup_fix_20261008/manifest.json)、[阶段记录](../../exports/tracking_startup_fix_20261008/RESULTS.txt)。当时已核对 Windows 文件前置哈希并备份、部署；不代表另一对话后续未再修改这些共享文件。

## 4. 测试命令和结果

### 已执行：保存证据的离线重算

仓库根目录执行：

```bash
.venv/bin/python -m exports.tracking_diagnosis_20261008.analyze_side_audit
.venv/bin/python -m exports.tracking_diagnosis_20261008.analyze_wide_audit
```

结果：生成上述统计与叠加图；采集前后模型哈希一致。另一次只读断言检查覆盖 `side_audit2` 全部 170 份非空姿态，修复前后 `build_pose_overlay()` 结果全部相同。选定正面样本的前后渲染逐像素一致、均有 10 条连接；选定侧面样本前后均无有效连接，差别是灰点和标签。

### 已执行：Windows 真人诊断

工作目录 `E:\OptoJump\Iron_Jump`，实际应用环境 `D:\conda\envs\pydantic_ai\python.exe`；通过登录用户的交互式计划任务启动窗口，不能以 SSH 无桌面的启动替代 UI 验证。

```powershell
& 'D:\conda\envs\pydantic_ai\python.exe' -m exports.tracking_diagnosis_20261008.pose_audit side_audit2
& 'D:\conda\envs\pydantic_ai\python.exe' -m exports.tracking_diagnosis_20261008.pose_audit side_audit5_wide --wide --slow
```

这些是当时已执行的入口，不应直接用原运行名重跑覆盖证据。新一轮必须换新输出目录名；模型和实际取景就绪、真人确认站好后，再在该目录创建 `start` 文件启动倒数。`--slow` 为 30 秒准备加 45 秒采集。结果详见第 2 节。采集的是相机，不代表同时完成了 8 米光栅验收。

### 历史回归结果与复验边界

- 此前启动顺序回归在修复前复现了“控制未完成就创建采集”；低质量显示回归在修复前复现了残留灰点。
- 相关修复本地记录：64 passed、2 subtests passed；最终错误重试相关的 5 项另行复验通过。
- Windows 实际应用环境：[windows-tests.log](../../exports/tracking_startup_fix_20261008/windows-tests.log) 记录 **64 passed, 2 subtests passed in 24.80s**。该日志没有保存完整命令行，因此不补造完整历史 argv。
- Windows 当时缺少 pytest-qt，使用已有环境中的插件复制到独立 `exports/tracking_startup_fix_20261008/test_dependencies`，通过 `PYTHONPATH` 和 `-p pytestqt.plugin` 加载；未为此升级生产依赖。
- 以下为后续涉及这些文件时的建议局部复验命令，**不是本次文档维护中新运行的测试**：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_pose_overlay.py tests/test_live_walking_vision.py tests/test_vision_framing.py
```

首次文档建立只核查文件路径、行号、哈希和已保存统计。跨分支复核阶段额外执行了下列只读设备证据检查、离线重放和局部测试；没有启动相机或重新进行真人实验。

### 2026-10-08 跨分支复核新增验证

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m exports.tracking_diagnosis_20261008.audit_control_handoff \
  --control-worktree /Users/vae/.codex/worktrees/tinyse-gimbal-validation/Iron_Jump \
  --output exports/tracking_diagnosis_20261008/control_contract_audit.json

PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_camera_analysis_frames.py tests/test_live_walking_vision.py tests/test_vision_framing.py
```

识别侧测试 **79 passed, 2 subtests passed in 0.60s**。覆盖未镜像识别帧、时钟恢复、过期结果、左右身份/触地门控及入镜条件。不是新的实机准确率测试。

另在控制 worktree，只读运行其现有测试，使用本目录的 Python 环境，不改对方模块：

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py
```

结果 **28 passed in 0.50s**。复核时对方已有未提交的 `vision/gimbal_tracking.py` 与测试修改，新增了 visibility/presence 非法值过滤的 6 个参数化案例；不能把这次结果写成提交 `26881a9` 原样的测试结果，也不能拿它替代真实断线或运动测试。离线报告记录了实际加载目标函数的 SHA256，结束时再次核对未改变。

通过 SSH 只读 Windows 控制测试目录的 `report.json`、`commands.jsonl`，独立重算 `full_body_20261008_02`：478 次推理记录、428 次有效目标、73 条非零控制样本；帧到结果年龄中位数 46.676ms、最大 65.357ms，与控制交接文件相符。起始角度及结束角度也与报告相符。上述证明的是日志内容一致；本阶段没有重新逐帧审核控制录像，未把 `hardware_motion_verified=false` 改成 true，控制文件的物理跟随及方向结论保留其原证据边界。

当前 Windows 应用环境只读查询的 OpenCV 版本为 5.0.0；本对话早期记录为 4.13.0.92。说明依赖环境记录已有变化，不能把旧回归结果无条件用于当前环境，也不在缺少安装历史时判断由谁、何时更新。

## 5. 待验证假设与下一步

| 假设 / 风险 | 证据强度 | 验证方法 |
| --- | --- | --- |
| 下半身跟踪取景裁掉头和上身，影响原模型的侧面定位或时序跟踪 | 有现场关联证据，未独立证明唯一因果 | 固定机位、站位、光照和原模型，仅切换取景模式；核对实际图像裁切而非只读 SDK 返回值 |
| 侧身双腿遮挡导致远侧关节断线 | 与当前低质量点分布一致，仍需逐帧标注 | 保留头脚余量，分别左右侧身、转回正面及交叉迈步，标注可见性和恢复时间 |
| 640 宽缩放降低远距离脚部细节 | 仅代码机制支持，尚无 A/B 证据 | 如需验证，只在离线同源视频中比较输入处理；保留原模型和阈值，不直接修改线上配置 |
| 身体取景恢复后即可稳定核验左右脚触地 | 未证实 | 同步采集视频与光栅事件，人工标注触地和左右身份，统计未知、错判、交换及时间误差 |
| 跟踪启动修复已解释全部控制异常 | 未证实且归控制侧 | SDK 命令成功不代表硬件动作实现；由控制侧验证实际云台运动、取景和独立状态来源 |

优先顺序：先获得运动过程中稳定的完整身体取景，再验证遮挡恢复及左右身份连续性，最后验收触地同步。不要用降低置信度阈值或扩大超时掩盖错误点、排队或身份不确定。

## 6. 需要另一个 Codex 对话配合的事项

1. **给出已验证的取景方案。** 说明最大 FOV、实际缩放倍率、AI 子模式及云台姿态之间的关系，确保走动时头顶、髋、双膝和双脚持续有边界余量。应用的“86°”标签和命令返回 0 不等于实际视野已验证。
2. **提供控制侧修改清单与版本。** 特别是 `camera/control_service.py`、`camera/tinyse_camera.py`、SDK 包装及 `ui/embedded_camera_panel.py`；这些共享文件有本对话此前修改，合并前核对实际 diff，避免相互覆盖。
3. **确认生产默认取景决策。** 本轮诊断使用标准 0，生产默认仍为下半身 4。请控制侧明确如何在跟随时维持识别需要的完整身体取景，再协调是否更改默认值；不要把诊断设置当作已永久上线。
4. **提供可关联的控制时间记录。** 记录命令发出、完成及实际视野/运动变化的时间基准，便于识别侧区分失跟、裁切、运动模糊、原始推理失败和显示过期。不要在 UI 主线程高频同步查询 SDK，避免测试工具反过来扰动采集。
5. **协同安排硬件占用。** 任何新窗口或官方软件对照前，确认上一采集/控制进程已释放；不要同时运行两套相机控制实验。计划任务曾使用 `IronJumpTrackingCompare20261008`，输出位于 Windows 仓库的 `exports/tracking_diagnosis_20261008/`；当前是否运行必须重新检查，不能由本文推断。
6. **共同完成动态验收。** 控制侧负责实际跟随与完整取景；识别侧负责原始 33 点、质量、姿态间隙、左右身份和触地匹配评估。首轮验证不更换模型、不调整识别阈值。

### 6.1 跨分支复核：当前版本与重复范围

| 项目 | 识别侧 | 控制侧 |
| --- | --- | --- |
| 分支 | `vae/iron_jump` | `codex/tinyse-mediapipe-gimbal-validation` |
| HEAD | `cc0bc7f9f9bee2bf24867c18fa16e942d4489a96` | 开始时 `26881a96bd644ff0843dfd1a3dd75ec64692b0db`，结束时对方提交为 `92fc6b9b89649fcff29fd3fb76e52354a0260865` |
| 实际范围 | HEAD 加本目录大量未提交识别、采集和 UI 修复 | 复核期间对方新增目标质量校验及测试，结束时已提交 `92fc6b9`、工作树干净；离线使用的函数哈希提交前后相同 |
| 入口 | `ui/embedded_camera_panel.py` → `LiveWalkingVision` → `FootVisionService` | 独立 `tools/tinyse_gimbal_validator.py` → `MediaPipePoseAdapter` → `SpeedWatchdog` |
| 控制方式 | UI 自动/手动激活 Tiny SE 内置 AI，默认下半身子模式 4 | 关闭内置 AI，固定最宽 FOV 和 1 倍缩放，MediaPipe 目标驱动速度 |
| 推理输入 | 原始未镜像 BGR，宽度大于 640 时等比缩到 640 | 原始未镜像采集帧解码，直接送相同适配器；没有主界面的 640 缩放层 |

Git 已确认共同基点为 `cc0bc7f`。`git diff cc0bc7f..26881a9` 仅有 DLL、C/C++ 包装、`camera/gimbal_control.py`、`vision/gimbal_tracking.py`、独立工具、相关测试及包装 README 共 8 个路径；没有复制主工作目录的未提交识别修复。`vision/live_walking.py`、`vision/framing.py` 和 `camera/control_service.py` 在本侧属于未跟踪文件，普通 `git diff` 不显示它们，不能据此说不存在。

逐字比较两个实际目录：模型文件、`vision/mediapipe_pose.py`、`vision/foot_reference.py`、`camera/tinyse_dshow_capture.py` 一致；`camera/bin/obsbot_c_api.dll` 不同。不能直接在本侧调用控制侧新增缩放/速度 ABI，也不能整体替换对方旧版 `vision/service.py`、`vision/event_scheduler.py`、`vision/leg_identity.py` 或 UI，否则会丢失本侧未提交修复。

双方重复关注“最大视野、完整身体取景、遮挡、250ms 过期和设备占用”，目的相容，没有证据冲突。以下属于实质对接问题：

- 内置 AI 与 MediaPipe 速度控制是不同运行模式，不能同时写云台；本侧“标准子模式 0”是内置 AI 的取景选项，不等于控制侧的全身目标算法。
- 推理输入分辨率和推理节奏不同，控制侧 46.7ms 与本侧 34.5ms 不能直接当成同条件性能优劣。
- 控制目标有效、完整身体取景、完整下肢入镜、左右脚身份稳定和触地正确是不同指标，不能互相替代。
- 本侧仅请求 FOV=0；控制侧还显式设置 zoom=1.0。本侧尚没有生产缩放接口，不能假设已具备对方的固定缩放能力。

### 6.2 已对齐及尚缺少的接口约定

| 接口事项 | 当前代码事实 | 约定 / 缺口 |
| --- | --- | --- |
| 姿态结构 | 两侧 `FootPoseSample.landmarks_33` 及 `Landmark` 字段一致 | 复用原始 33 点；本侧尚未新增稳定全身中心或多人人员 ID 接口 |
| 坐标 | `TinySeCameraCapture._decode_preview_frame()` 在软件镜像前发送识别帧；640 缩放等比、无软件裁切 | x 向右、y 向下，归一化坐标对应整张实际采集图；软件镜像只影响显示，不交换解剖左右。若启用硬件镜像或实际裁切，需重新核对 |
| 原始时间 | `TinySeFrameTiming` 含 frame_index、sample_time_s、callback_time_s、decoded_at_s | 当前独立控制工具用该帧原始 callback_time_s，同主机 `perf_counter()`；不能用 decoded_at_s 或推理完成时间刷新陈旧指令 |
| 同步时间 | `LiveWalkingVision.submit_camera_frame()` 校准后向服务提交 aligned_time_s；`PoseInferenceRecord` 只保留该时间的毫秒化值及推理起止 | 映射时间和回调时间在同一主机单调时钟域，但时点不同。必须关联回原始 frame_index/callback_time_s；当前结果接口没有该关联。最终是否以映射采集时刻作看门狗起点，还需明确同步就绪/降级和时钟重置语义，不能无说明地替换原始时间 |
| 结果发布 | `pose_inference_ready` 是普通 Python EventHook，包含 None/错误结果，回调在推理线程；UI 用轮询显示 | 建议复用一个采集方和一个推理方；控制订阅只投递有界状态，不能同步调用 SDK 或触碰 UI，丢失/错误必须显式投递失效 |
| 质量与身份 | 显示/入镜与控制核心点门槛均为 0.65；左右腿身份分析核心质量门槛为 0.60，另有遮挡和交换检查 | 阈值针对不同职责，并非互相矛盾。姿态可用于云台居中但仍不能用于左右脚核验；双方不要合并成单一“有效”布尔量 |
| 换人 | 原适配器单人输出，不附持久人员 ID；`LegIdentityAnalyzer` 检查解剖左右连续性 | 不能当作完整的人员身份保持方案；换人后的选择、失效及恢复语义仍需共同定义 |

### 6.3 本阶段继续识别工作：离线重放发现

可复跑结果：[control_contract_audit.json](../../exports/tracking_diagnosis_20261008/control_contract_audit.json)。只读取对方的纯数学目标函数，不加载 SDK，不改变模型、阈值或任一控制模块。

| 已保存数据 | 推理数 | 控制目标有效 | 完整下肢入镜通过 | 控制目标有效但下肢入镜未通过 |
| --- | --- | --- | --- | --- |
| `side_audit2` | 226 | 22 | 21 | 1 |
| `side_audit5_wide` | 572 | 367 | 75 | 292 |
| `side_audit5_wide` 实际侧身 28～34s | 75 | 70 | 20 | 未单独作为控制验收 |

因此此前“75/75 返回姿态、8～10 个点置信度达标”仍成立，但不能扩展为“侧面每帧都完整入镜”或“左右身份稳定”。侧身同段离线身份分析：稳定 24、不可用 36、不确定 15；这只是从首条保存记录重新初始化后进行的因果重放，缺少采集前预热历史，不代表当时 UI 的逐帧状态，也不是身份准确率。

代码复现：`full_body_target()` 必须通过的是双肩、双髋、双踝；头部、脚跟、脚尖只在可靠时纳入范围。合成输入把所有头点和脚跟/脚尖设为出画且低质量，仍返回中心 `(0.5, 0.5)`。这证明其“有效全身目标”不能单独保证完整身体取景；是需要明确的控制目标语义，不以此否定其已记录的运动能力。

识别侧下一阶段优先量化边界裁切和身份恢复，保持原模型。待控制侧稳定提供原始帧及回调时间，再接入统一数据链路，测动态跟随中的入镜、丢失和触地事件。

### 6.4 更新后需要控制侧处理的事项

1. **明确控制模式互斥及退出恢复。** 速度控制期间抑制 UI 的 `_show_latest_frame()` 自动激活内置 AI；切回正式预览时明确谁恢复 AI、跟踪子模式与缩放。由控制侧负责 SDK 和运动策略，本侧不改这些模块。
2. **明确“全身目标”的可见性保证。** 是否要求头部、脚尖/脚跟及边界余量，或只需可靠中心；请结合近场和遮挡策略决定，不把六个核心点通过当作全身无裁切。SDK 最大视野和居中本身也不能保证近距离装得下全身。
3. **核对启动错误及线程边界。** `GimbalSdk.disable_ai()` 当前仅记录 FOV 返回码，未对其失败作 `_check`；请决定失败应中止还是明确降级。SDK 构造包含设备刷新，若接入 UI 需继续在后台执行，避免重新引入界面阻塞。
4. **在原始证据中补全时间与姿态关联。** 当前控制日志有 frame index、sample_time、target、age，但不保存原始 33 点、callback_time_s 和 identity 状态；请确定双方统一记录方式，识别侧再配合输出。丢帧或时钟重置时不得按“最新帧时间”给旧结果续期。
5. **协调分支与 DLL/接口合并。** 保留本侧未提交采集、调度和 UI 修复，仅选择控制侧新增实现；测试结果需写明 HEAD 加工作树状态。对方质量校验 diff 已在本轮离线检查中使用，随后由对方提交为 `92fc6b9`，并非本对话修改。
6. **共享环境与设备占用安排。** 当前 OpenCV 已为 5.0.0，联合测试前记录依赖版本；由唯一采集源同时供识别、预览、录制和控制，不在另一对话运动实验期间另开相机窗口。

协作约定：本对话将重要识别阶段持续写入本文件；控制侧进展以另一对话维护的 `control.md`、实际代码及原始证据为准。本阶段只更新自己的进度、识别侧离线诊断和结果，没有合并分支、修改对方模块或向其他 Codex 对话发送消息。

该阶段结束时重读控制文件：对方也已复算保存姿态，侧身段控制有效 70/75、入镜通过 20/75，与本侧一致；双方已共同指出取景余量和内置 AI 互斥问题。当时公共订阅及原始元数据关联尚未实现；下一阶段实现记录如下，不用后续结果改写历史验收状态。

### 6.5 SDK 自主跟踪协作：已实现的公共识别出口

当前识别代码基于 `vae/iron_jump` 的上述 HEAD 加工作树；控制侧核对 HEAD 为 `69ab8ecacaf5c67c12c40377d27c3800889c0ebd`，第 1 轮新增 `camera/pose_tracking.py` 与测试尚未提交。已读取其实际源代码，不仅依赖 `control.md`；本对话没有修改控制模块。双方已主动交换两轮接口/故障审阅意见，后续重大结果继续写各自文档。

**正式出口**：`LiveWalkingVision.pose_updates.connect(callback)` / `.disconnect(callback)`，回调参数为不可变 `LivePoseUpdate`。这不是 Qt 信号；SDK 和 UI 不能在回调中调用。一次推理复用于显示、左右身份、触地核验和控制，控制侧不能另开采集/模型实例。

| 字段 | 代码位置 | 语义 |
| --- | --- | --- |
| `LivePoseUpdate.status` | `vision/live_walking.py` `LivePoseUpdate` / `_publish()` | 只有精确等于 `pose` 才是控制候选，不等于取景或触地核验通过；其余状态一律失效 |
| `inference` | `vision/service.py` `PoseInferenceRecord` | 实际一次推理的 `pose`（原始 33 点）、`error`、映射帧时间及推理起止；状态通知可以没有 inference |
| `inference.frame_metadata` | `vision/service.py` `PoseFrameMetadata` / `_InferenceInput` / `submit_frame()` | 原始 `frame_index`、`sample_time_s`、`callback_time_s`、`decoded_at_s`、`clock_sync_status`、`clock_sync_uncertainty_ms`、`camera_clock_epoch`；与实际推理输入同一对象一起入队，不能拿最新帧时间补给旧结果 |
| `identity` | `vision/live_walking.py` `_update_pose()` | 当前原算法的因果左右腿身份状态；不是持久人员 ID，不保证触地准确 |
| `framing` | 同上；`vision/framing.py` `check_framing()` | 发布时的严格下肢入镜判定，与控制中心是否有效分开；不能仅靠它代表头顶余量 |

`FootVisionService.submit_frame(..., metadata=None)` 兼容原有调用，`PoseInferenceRecord` 的新增尾字段也有默认值。旧调用结果可能没有元数据；控制侧必须按失效处理，禁止猜测或刷新时间。latest-only 丢帧时连同其元数据一起丢弃，事件窗口仍消费原姿态样本，未改触地分类器或调度器。

**时间约定**：原始 sample 时间不是主机时间。同步 `ready` 时，`frame_timestamp_s` 为映射到同主机单调时钟的采集时间、经 VIDEO 推理毫秒取整；`warming_up` / `degraded` 输入回退到原始 callback 时间后取整。原始 `callback_time_s` 保持未取整，`decoded_at_s` 和推理结束不能用于延长控制有效期。warming_up 不代表同步校准已完成，也不能用 callback 新鲜证明 USB/曝光之前无延迟。

双方同意控制侧采用 `min(callback_time_s, frame_timestamp_s)` 保守判断 250ms 过期，保留两者用于审计；先检查有限性，原始 callback 来自未来时失效，映射时间仅允许 1ms 取整误差，未知同步状态及 degraded 应失效。warming_up 可用作临时居中候选；触地核验仍独立要求时钟 ready。控制线程需要自行持续看门狗：断流但没有新结果时，识别出口不会凭空生成一个新的过期事件。

**失效与顺序**：

- `loading`、`ready`、`no_pose`、`inference_error`（包括带错误文字的服务状态）、`unavailable: ...`、`clock_reset`、`stopped` 均不能生成非零速度；以后未知 status 也按失效处理。
- 模型加载完成会重置相机时钟并递增 epoch；同步降级后的下一帧恢复会递增 epoch。旧 epoch 的在途推理转换为 `clock_reset`，不发布身份/入镜状态，不更新 UI 姿态为旧结果。
- 同步在 `observe()` 中刚降级时立即通知 `clock_reset`，即便该帧因时间不递增被丢弃；当前 DEGRADED 期间的在途结果也失效。这是在测试中先复现失败、再修复的边界。
- `stop()` 先发一次终止通知，再等待推理服务退出；停止后的推理和服务状态不再发布。并发在途通知先完成，再发布终止通知；因此订阅者必须迅速完成有界投递，不能阻塞或在回调中执行启停/SDK 操作。LiveWalkingVision 是一次会话对象，重启使用新实例。
- 推理结果和模型状态通常在推理工作线程；采集提交引起的 reset 在采集处理线程；停止在调用线程。不能假设同一回调线程；通知通过发布锁串行化。控制側自行维护流实例/模式 generation，不能将 clock epoch 当作会话 ID。

**本阶段识别回归**：先新增公共 API 测试，接口不存在时收集失败（ImportError）；实现后首轮 90 项通过。再补同步降级/并发停止/触地兼容测试，出现 `1 failed, 10 passed`：被丢弃的重复帧没有发布 reset。修复后执行：

```bash
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_live_pose_updates.py tests/test_vision_service.py tests/test_live_walking_vision.py \
  tests/test_vision_framing.py tests/test_vision_event_scheduler.py tests/test_walking_vision_pipeline.py \
  tests/test_leg_identity.py tests/test_vision_time_sync.py tests/test_camera_analysis_frames.py
```

结果 **132 passed, 2 subtests passed in 0.67s**。覆盖成功/无人/错误的同帧元数据关联、latest-only 覆盖、原始回调不被完成时间替代、事件分类兼容、停止/旧 epoch/同步降级及现有时间与身份回归。均为离线输入，不等于动态跟踪或真人准确率验收。`git diff --check -- vision/service.py` 通过；模型、`mediapipe_pose.py` 和 `foot_reference.py` SHA256 与前阶段一致。

**对控制侧第 1 轮实际实现的只读复现**：在其 worktree 使用本侧 Python 运行现有 `tests.test_pose_tracking.update` 构造输入并调用 `PoseTrackingMailbox`，未加载 SDK、未改对方文件。

| 输入次序（均在 epoch 3） | 实际输出 | 需控制侧处理 |
| --- | --- | --- |
| submit(index20) → submit(index19) → command(10.1) | `tracking`，frame_index=19 | 水位只在消费时更新，尚未消费的新帧可被旧帧覆盖；高水位应在投递时维护 |
| consume(index20) → submit(clock_reset) → submit(index21) → command(10.1) | `tracking`，pan=57.6 | latest 状态吞掉 reset；必须保留取消待发速度的屏障，不能只有最后状态 |

复现入口及命令：在 `/Users/vae/.codex/worktrees/tinyse-gimbal-validation/Iron_Jump` 用 `PYTHONDONTWRITEBYTECODE=1 /Users/vae/Projects/Iron_Jump/.venv/bin/python` 导入 `camera.pose_tracking.PoseTrackingMailbox` 和 `tests.test_pose_tracking.update`，按表顺序执行；上述是第 1 轮未提交代码的结果，后续修复应重跑，不能拿旧失败代表新版本。

已反馈控制侧：失效/模式切换时递增独立 motion generation，保留待处理零速屏障；速度命令携 generation，SDK 执行前再次核验，已发非零命令应尽快停转。采用同一个 `CameraControlService` SDK 子进程串行执行速度和设置，保留现有启动 idle 等待；不要另开 GimbalSdk 与设置服务竞争。控制侧拥有 `camera/control_service.py`、`TinySeCameraControl` SDK 绑定及 `ui/embedded_camera_panel.py` 的运动接线；识别侧继续只维护公共出口、识别测试和本文件。

**联合验收剩余事项**：控制侧修复上述屏障/乱序并补未知同步状态、模式会话切换、待发指令撤销及 SDK 错误/退出回归；识别侧只读复核真实公共对象消费。正式 UI 必须抑制内置 AI 自动激活，且仅一个采集、一个推理和一个 SDK 拥有者。联合离线测试及两轮互审通过后，再邀请用户做完整取景下的正侧面、横移、遮挡/退出和走路同步现场实验；记录曝光/回调/推理/命令/实际运动的证据边界。通过后由控制侧按用户在其对话中的授权协调合并到 vae，保留本侧未提交修复，再处理验证分支；本阶段不合并、不部署、不删除分支。

### 6.6 第 3 轮：控制修复复核与真实公共对象联合测试

控制侧收到反馈后，自行修改 mailbox 并新增 `camera/tracking_runtime.py`；本侧只读重新运行其 worktree：

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_pose_tracking.py tests/test_tracking_runtime.py \
  tests/test_gimbal_tracking.py tests/test_tinyse_dshow_capture.py
```

结果 **59 passed in 0.55s**（对方前一消息的 55 项属于更早瞬时版本，不能把数量差异当作矛盾）。实读代码已在投递时维护水位，失效递增 motion generation、保留零速屏障，拒绝未知同步状态；第 1 轮两个复现不再代表此版本。SDK 函数返回错误由 `GimbalSdk` 的 `_check` 处理；runtime 记录调用起止，调用期间若失效会在返回后补零速。native 调用阻塞仍不能保证物理停止，这是待实机和进程生命周期处理的边界。

独立联合测试没有用控制侧 SimpleNamespace 冒充公共对象：在主工作树 Python 中只将两个 package 的搜索路径追加控制 worktree，使用本侧真实 `LiveWalkingVision` / `LivePoseUpdate` / `PoseInferenceRecord` / `PoseFrameMetadata`，推理服务及 SDK 模拟。通过以下序列：

1. loading/ready 先产生零速，再由真实 pose 产生非零 pan。
2. 同 epoch 的 frame20 → frame22 → frame21，未消费的新结果保留 frame22。
3. 真正 `pose=None` 的推理输出后立即接 frame24，首次消费仍零速，下一次才恢复。
4. 时间推进至输入 251ms 后停转，不使用推理结束或消费时刻续期。
5. ready 重置 epoch 后旧结果失效，新 epoch 先经过屏障再恢复。
6. `live.stop()` 后迟到输出被忽略，SDK 模拟命令保持零速。

全部断言通过，没有采集、打开设备或运行真实 SDK。加载文件 SHA256：

```text
camera/pose_tracking.py     8cc3882cd6042364e4e44252a7f6ab9d8766a9639db843e36fe0189beb72c5ef
camera/tracking_runtime.py  d01c67b9c379d9f894a631468eb54c1c9f47022e4cc8e7f93e6dccf61032337f
vision/gimbal_tracking.py   c9e1e8b924f4ef6b8d72d07a303af20691cde7c3567b15f09db1f56f46c53821
```

本轮再次发现的控制边界已发给对方：`setting()` 清空 mailbox，但未改变模式 generation，也没有保持设置完成时刻/旧帧水位。用控制侧测试 helper `runtime()` 和 `update(index=20, callback=10.0, mapped=10.0)`，执行 `start(1)` → 投递/消费该帧 → `setting('set_auto_focus', lambda: 0)` → 重新投递同一旧帧 → tick，仍输出 `(0, 57.6)`，即设置前结果能重新驱动。需要控制侧补帧时刻或 generation 屏障并回归，不能把“清空”写成“只接受设置后新帧”。本侧不代改 runtime。

当前公共出口已完成自身离线验证，模型和 640 输入处理未变；控制方案仍处于互审及接线阶段。进程传输、UI 互斥、错误退出和硬件响应速度还未验收；后续以双方最新文档、实际代码和证据继续迭代，不提前合并或部署。

控制侧要求补查“较新 epoch 已运行后，才收到附旧 epoch 的 reset”。使用真实 `LivePoseUpdate` / `PoseInferenceRecord`：先投递并消费 epoch4/frame20，再投递附 epoch2/frame99 的 clock_reset，随后 epoch4/frame21；首次消费零速、下一次恢复 epoch4，断言通过。旧 reset 不把最低 epoch 提到当前 epoch 以上，但仍撤销待发运动。该结论仅针对带旧结果元数据的重置，不代替进程传输及无元数据状态通知的并发验收。

### 6.7 第 4 轮：可复跑 JSON 传输契约与接线前复核

用户在本对话再次明确授权主动多轮协作，方案成熟后现场验证，验证通过再合并到 vae。已与控制侧继续互审；其控制服务和 UI 正在隔离 worktree 基于主工作树当前文件接线，不将开发中的半成品当作正式部署，也不在本侧直接覆盖共享控制文件。识别模型与配置仍不变。

新增 `tests/test_pose_control_contract.py`，使用本侧真实公共 dataclass 及 `LiveWalkingVision` 出口，显式加载控制 worktree 的四个纯模块；每项测试结束恢复 Python 模块注册，避免混用另一个分支的缓存。SDK、相机和推理服务模拟，不打开现场设备。未指定控制路径且主工作树尚无控制模块时明确 skip；联合验证必须设置路径，不能把跳过当通过。

```bash
IRON_JUMP_CONTROL_ROOT=/Users/vae/.codex/worktrees/tinyse-gimbal-validation/Iron_Jump \
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_pose_control_contract.py tests/test_live_pose_updates.py \
  tests/test_live_walking_vision.py tests/test_vision_framing.py
```

结果 **97 passed in 0.44s**，新增联合测试 10 项，全部实际执行。覆盖 33 点、原始元数据、身份/入镜状态的 JSON 保留；None→新 pose 合并仍先零速；带旧 epoch / 无来源 reset 后恢复当前 epoch；错误、不可用及终止状态撤销待发命令；JSON 延时不刷新年龄；旧模式 packet 拒绝；慢设置后拒绝旧帧、接受设置返回后的新帧。

如实记录失败和修正：初版 JSON 等值测试错误地再次调用身份分析器，改变因果状态，得到 `1 failed, 9 passed`；已改为比对同一次公共回调对象，未修改身份算法。首次组合运行遗漏 `QT_QPA_PLATFORM=offscreen`，得到 `96 passed, 1 failed`，失败来自无 Qt primaryScreen；设置 offscreen 后全部通过，不当作生产代码问题。协作消息曾错误报组合数量 89，随后更正为实际 97。

并行源码核对注意：首次读取中间 `PoseRelay` 只传 barrier_status，控制侧随后自行改为保留完整 barrier update。一次反馈发送时错误宣称当前 JSON 迟到 reset 失败，但实际工具已输出 `57.6 → 0 → 57.6`，立即向对方更正；本阶段没有证实当前版本存在该失败。新增真实 JSON 回归固化了这条边界，避免仅根据读取旧快照推断结果。

当前控制侧落实的接口与职责：relay 保留完整失效结果及元数据；无来源 reset 不推测 epoch+1，仅撤销 motion generation 并保留水位；有来源 reset 按原始来源处理。runtime 设置返回后建立时间屏障，不再把清空队列等同于新采集帧。测试结束后的源码快照为 mailbox `9e8b0dd1677ee920e286dfb0abdffb8aac67050ca42626947c393cae7fcf2b04`、relay `16ac0b1b610ee3fea7a771c2262c34cfb1abf098370b8cf5ff9e1633484675f8`、runtime `34376c4a106bbc483ca9f3849b344e473dddb31f3bbbba5febca87c3c33e9cfe`。这是 worktree 开发版本，不等于 HEAD 或已部署版；下一接线阶段需固定源清单后再跑。

随后扩充联合测试到 **12 passed in 0.34s**：新增对 `side_audit2` 226 次、`side_audit5_wide` 572 次保存结果逐次 JSON 重放，合计 798 次；JSON 前后目标有效性、坐标相同，消费丢失屏障后速度数值一致。日志没有原始 callback，测试明确构造 callback=保存 frame_timestamp，仅检验传输/纯决策，不用于证明实际延迟、时间同步正确或动态跟随准确率。该两项在缺少现场保存数据的 checkout 中会明确 skip。

最后以同一指定控制 worktree 运行本文件 6.5 节的九组识别回归，加 `tests/test_pose_control_contract.py`：**144 passed, 2 subtests passed in 0.78s**。本次所有 12 项联合测试均实际执行，保存证据两项没有跳过。该结果依然没有涵盖开发中的正式 QProcess/UI 接线。

接下来等控制侧提供临时集成目录及进程/UI 测试完成状态，本侧继续只读复核：QProcess 高速路径不能积压旧帧、失效不能被有界合并吞掉、一次会话只一个 SDK/推理/采集方、回放/停止/换相机/切模式/失败退出必须断开订阅并停转。联合离线通过后邀请用户现场验证正侧面、普通/快速横移、丢失恢复及完整取景；现场通过后才合并 vae，不能用当前 97 项模拟回归替代实机验收。

### 6.8 第 5 轮：固定集成快照及三项生命周期缺陷

控制侧提供冻结集成目录 `/private/tmp/tinyse-integrated-20261008-r4`。识别侧独立逐项验证 `control-manifest.json` 的 **224 项 Python 源码哈希全部匹配**，清单自身 SHA256 `af2843f53dc4a2d7e8e53317b112bd7f3247d37e8780bce06f2297b03244fb3b`。识别出口、模型适配器来自本工作树；控制服务/UI增量来自控制 worktree；该组合不是任何一个干净 HEAD。非代码资源及 exports 引用主目录，不能把它们称为全部冻结资产。

在该目录独立执行控制侧给出的命令：

```bash
IRON_JUMP_CONTROL_ROOT=/private/tmp/tinyse-integrated-20261008-r4 \
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py \
  tests/test_camera_control_service.py tests/test_embedded_camera_panel.py \
  tests/test_live_pose_updates.py tests/test_sdk_tracking_integration.py tests/test_pose_control_contract.py
```

**105 passed in 4.06s，无跳过**。包括真实 QProcess/serve 路径：模拟 SDK 启动、原始 33 点 JSON、250ms 停转、stop/EOF 零速；未收到停止应答会报告错误。仍不代表物理停转或真实 SDK 响应验收。

随后独立补查得到三个可重复的失败，区别于上述已通过覆盖：

| 固定 r4 的失败 | 代码位置 | 复现/责任 |
| --- | --- | --- |
| SDK启用后进入回放没有立即 end_tracking，订阅仍存在 | `ui/embedded_camera_panel.py` `open_recording()` | Qt 控制 spy 仅收到 start，没有 stop；应立即撤销、回到实时画面明确建立新会话，由控制侧处理 |
| 重启预览在旧SDK进程仍 Running 时创建第二个拥有者 | 同文件 `_release_control()` / `_restart_preview()`；`CameraControlService.close()` | 模拟旧进程 EOF 后延迟0.8s，观察到旧Running且created=2；应等待实际closed及停止确认后再启动，覆盖取消/切相机和旧sender回调隔离 |
| reader中已通过检查的旧packet被重新标记为新generation | `camera/tracking_runtime.py` `submit_packet()` | reader在pose_input log处暂停，owner stop/start(gen2)，reader恢复后旧gen1 packet调用self.submit(self.generation,...)产生pan57.6；应保留packet原generation并保护共享会话状态 |

可复跑的独立脚本已保存，不更改对方模块：

```bash
IRON_JUMP_INTEGRATION_ROOT=/private/tmp/tinyse-integrated-20261008-r4 \
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider \
  /Users/vae/Projects/Iron_Jump/exports/tracking_diagnosis_20261008/test_sdk_lifecycle_review.py
```

结果 **3 failed in 1.28s**，是上述三处实际断言，不是测试工具异常。测试初版清理访问已删除Qt对象、packet未做JSON roundtrip造成tuple/dict解码异常，以及迁移到仓库路径时误加载主工作树UI，均已修正：最终显式指定快照并检查导入路径、通过closed事件清理、用真实 JSON 包暂停线程。不将这些测试错误计作生产源码问题。控制侧已收到并自行修复，待下一固定快照再独立验收；此处失败结论只针对 r4，不能泛化到其后 worktree。

**取景控制策略协作**：控制侧新加 `BodyFraming` / `framing_velocity()`，报告鼻点、脚跟脚尖及可靠点边界；鼻点不是头顶，边界不是实际人体轮廓。可靠点贴近6%边缘时，该轴取消原中心死区；近场范围超0.88提示调整距离，保持最大视野，不改变识别模型/质量阈值。已读实际源码，识别侧原始输出/严格下肢入镜判定不改。

本侧 `tests/test_pose_control_contract.py` 更新至 **13 passed in 0.37s**（针对新 worktree）：保存输出重放在新策略使用 framing_velocity、旧固定版本显式使用旧策略；另加独立具体反例 bounds top=.1,bottom=1，中心(.5,.55)，旧中心死区速度(0,0)，新JSON→runtime速度(pitch4,pan0)，同时验证原始33点JSON不变。这证明控制策略改变，不能写成所有旧速度数值未变，也不是新物理跟随证据。r4冻结测试仍是旧12项。

下一步等待控制侧固定 r6 快照，对三项独立失败、停止确认、新取景策略及共享识别契约联合复验。现场邀请和合并仍在其后，当前本对话没有部署、打开设备、合并或修改 `control.md`。

### 6.9 第 6 轮：三项修复通过，异常退出停止确认尚需收敛

固定快照 `/private/tmp/tinyse-integrated-20261008-r6` 的 **226 项源码/DLL 哈希独立核对全部匹配**；清单 SHA256 `8671386e6114eb57d9374f1eb4388a4aec6d1400b1a747c30d9b5c189aacb7eb`，模型仍为原 SHA。识别侧独立运行 6.8 的联合命令，加 `tests/test_body_framing_control.py`，结果 **113 passed in 5.22s，无跳过**；独立生命周期脚本的前三项 **3 passed in 1.44s**。第 5 轮三个缺陷在该版本已验证修复，不拿旧失败代表 r6。

DLL 核对使用 PE 导出表而非仅查 Python 绑定或 SDK getter：主工作树/r4 的 DLL SHA `55708fa2de83b7a95c2370681e5bed0d83a8394f079c47f2a099f168e6dbb1a7` 有33项导出，缺 `obsbot_set_zoom` / `obsbot_get_zoom` / `obsbot_set_gimbal_speed` / `obsbot_get_gimbal_angles`；控制分支 DLL SHA `c05b4d551fd5ba178a3bfce2cef9f35c81fd2322c010756c53114d924415bfaf` 有37项导出，上述齐全。r6实际纳入后者及哈希清单；r4模拟测试通过不能扩展为其旧DLL原生可运行。PE检查仍不等于加载Windows依赖或实体相机测试。

**新增独立失败**：本侧生命周期脚本追加 `test_stop_ack_after_worker_crash_requires_a_native_zero`，r6 **1 failed in 0.58s**。真实QProcess/serve结合模拟native，将速度写入跨进程保留文件；非零命令后旧进程立即退出，无法执行finally。再调用 `end_tracking()` 会创建新child，其 `runtime is None` 的 tracking_stop 直接回复0，却没有native零速，模拟设备状态仍 `[0,57.6]`。这是已证实的“软件错误宣称停止确认”，不是相机真实速度或厂商超时行为的实证。

控制侧已收到并自行修复：无runtime的首次stop也必须attach当前唯一DLL缓存、实际发送零速才返回成功；旧进程已经死亡的end_tracking不得暗中创建新owner，明确报告无法确认。独立测试随语义收敛允许两种正确结果：成功应答且实际模拟native零速，或者明确未确认且保持进程停止、不伪报成功。等待固定r7再独立验收；当前 r6 的假成功仍不能视为修复。

**正式应用退出链已读代码确认**：`ui/main_window.py` `MainWindow.closeEvent()` → `ExecutionView.reset()` → panel.shutdown，随后直接 `event.accept()`；`ui/app_shell.py` 未重写退出逻辑。当前新增panel/control是异步退出，Qt主循环立即结束可能来不及收到SDK停止应答。已交控制侧处理正式退出生命周期，保持原voice/controller/其他相机清理职责；独立窗口壳等待close不能代替完整MainWindow验证。本侧没有改对方UI或控制文件，尚未做真实完整App退出实验。

控制侧反馈已提交验证分支 `336a3da`（后续停止修复仍在其工作树），并报告更广回归218项及2子测试通过；本侧此处只写自己运行的113项及3个独立回归，未将对方218项转作本侧新验收。现场Windows验证包由控制侧作为唯一采集/SDK应用拥有者准备，本侧负责读取证据及识别评估；需先关闭当前停止确认与App退出两条边界，再邀请用户现场。

### 6.10 第 7 轮收敛：固定 r7 可进入现场验收准备

固定候选 `/private/tmp/tinyse-integrated-20261008-r7`，**227 项源码/DLL 哈希全部独立匹配**；清单 SHA256 `18f73ed7ac3224283300ae509b24a3df372434a96d61129b2ae4bf0f7f9c49d5`。MainWindow 来自控制 worktree 的当前主工作树基线加最小退出guard，SHA `40345d526706cdc4ea648539293b05c8c198c9fb20926347a3648776b5493823`；原模型、适配器及640处理未改，新DLL仍为上述 c05b...。快照不同于 HEAD，合并前必须保留双方实际工作树和来源清单。

识别侧在 r7 独立运行：

```bash
IRON_JUMP_CONTROL_ROOT=/private/tmp/tinyse-integrated-20261008-r7 \
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen /Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_pose_tracking.py tests/test_tracking_runtime.py tests/test_gimbal_tracking.py \
  tests/test_body_framing_control.py tests/test_camera_control_service.py tests/test_embedded_camera_panel.py \
  tests/test_live_pose_updates.py tests/test_sdk_tracking_integration.py tests/test_pose_control_contract.py \
  tests/test_vision_service.py tests/test_live_walking_vision.py tests/test_vision_framing.py \
  tests/test_vision_time_sync.py tests/test_camera_analysis_frames.py tests/test_tinyse_camera_capture_recording.py \
  tests/test_main_camera_shutdown.py tests/test_main_window_navigation.py
```

结果 **236 passed, 2 subtests passed in 13.79s，无跳过**。另以 `IRON_JUMP_INTEGRATION_ROOT` 指定 r7 运行本侧独立生命周期脚本，结果 **4 passed in 1.40s**。不是只重复原通过项：新增的异常退出假stop和正式App退出边界也已闭合。此前 r4/r6 的失败保留作历史证据，不继续报告为 r7 当前缺陷。

已读实际代码确认：无runtime的stop先attach当前DLL并真正发送native零速才应答；旧child已经死亡时end_tracking明确报告未确认且不创建新owner。主窗口清理执行一次，SDK尚未closed时忽略关闭事件、继续处理Qt事件，确认停止后完成关闭；未确认则提示并保持窗口，之后用户再次主动关闭可以退出。保留原voice/controller/其他相机/LLM清理顺序。独立脚本证明模拟设备状态不再被错误宣称停止；实体相机物理停转仍需现场视频/动作核验。

**当前决定**：第7轮没有发现仍未处理的代码阻断，可以准备现场候选；不无理由重复已稳定的离线测试，也不宣称动态跟随或左右触地准确率通过。控制侧独占Windows包、进程和采集/SDK窗口；本侧不另开相机、不部署第二份。控制侧核对实际Windows依赖、新DLL/来源清单及原模型，关闭旧应用和官方软件冲突后，在候选画面就绪时由其唯一提示用户站位/动作；本侧配合读取保存证据。

现场验收：同一主界面原识别流程、最大视野/zoom1，头部和双脚留边界余量；正面→侧面→正面、普通与较快横移、短时遮挡/离开再恢复、显式停止、回放及重启/关闭。控制日志记录原始帧索引/回调/映射时间/epoch/模式generation、33点、SDK调用及停止应答；原始录像核对实际运动和裁切。本侧分别评估姿态存在、严格十点下肢入镜、身份状态及未知/交换恢复，不把控制中心有效替代识别准确率。若增加光栅走路触地，重新核对8米空场和坏点处理；此前用户授权屏蔽1束可继续降级，但坏点附近事件不能作正常验收。

现场通过后再按用户授权整合到 `vae/iron_jump`：保留现有未提交采集、调度、识别和UI修复，只选择本次控制增量；当前不合并、不覆盖主工作树、不删除验证分支。现场暴露新问题则继续双方互审并更新各自文档。

### 6.11 第 8 轮：Windows 准备轮证据与可见现场工具

控制侧部署位置为 `C:/Users/86150/TinySE-gimbal-validation-20261008/shared-tracking-924fe47`；本侧只读 SSH 曾确认目录及报告文件存在，随后一次读取20秒超时，仅记录为取证工具失败，不推断相机断连。控制侧取回的本地证据位于主工作树 `exports/control_integration_20261008/`，本侧实际读取了测试文本、preview报告/事件，查看 `preview_ready_01/end.jpg`，并用 `.venv/bin/python` 的 hashlib/zipfile 独立核对候选ZIP：234项清单全部匹配，ZIP SHA256 `ab7182ffe2662d46b0f3671ca78dd5b98e5a72ae11d14fc3e807cfffb281e334`。这核实本地候选内容；Windows逐文件哈希和四个ABI实际加载由控制侧执行，本侧没有重新加载SDK或打开设备。

`windows-offline-tests.txt` 实际记录 **79 passed in 8.68s**，属于控制侧 Windows 运行结果，不冒充本侧重复执行。此前缺少 pytest-qt 的12项错误经候选目录专用依赖补齐后补跑；当前没有理由重复稳定回归。

准备轮 `preview_ready_01` 日志显示 preview-only、duration=3，原模型SHA一致，收到 `recording_started`；4次 `set_speed` 均为零，tracking_stop成功应答，最后 `sdk_process_closed` stop_reply=true。report errors为空、stop_unconfirmed=false、hardware_motion_verified=false。实际图像为坐在桌前的人，双脚被桌/屏幕遮挡，不能验证全身取景、侧面识别、身份准确率或物理跟随。preview-only在 `_start_capture()` 中撤销SDK识别订阅，因此缺少 pose_input 是该准备模式的预期行为，不能据此诊断识别断流。停止应答仍不等于实测物理停止。

**工具互审与控制侧修复**：原 `tools/tinyse_shared_tracking_validator.py` 不调用 show，适合隐藏准备取证，不能让用户看到现场动作窗口。本侧指出后，控制侧薄工具增量提交 `7815713` 添加 `--show`、1280×800同一Panel、动作阶段标题/提示音以及关窗口后继续等待SDK closed的Qt循环。本侧读取实际源码并独立核对 `package-delta.json` 中该文件SHA `473256de4b9ee1b99168b7e2738a822f0af79e5cdac61e426f47fbca0dbde540` 与控制工作树一致，没有发现新阻断；本侧未修改工具或控制模块。本阶段本侧仅更新本文件。

计时由实际首个显示帧开始，**不等于模型ready或用户就位**；requested_phase只记录请求动作，须原始录像确认动作真实发生。双方确定先由控制侧唯一确认用户站位，回复就绪后才启动75秒现场任务，任务必须使用InteractiveToken真实桌面且不得继承offscreen。控制侧报告唯一手动任务 `IronJumpTinySESharedField20261008` 无定时触发器、尚未启动；本侧未独立启动/操作任务，不另开窗口，也不重复向用户提问。

**下一阶段职责**：控制侧独占现场启动、进程与SDK、动作提示、停止/关闭和取回原始录像/帧CSV/事件；本侧在收到 `field_walk_01` 证据后核对画面正侧面动作、33点及严格下肢入镜、身份状态、帧与控制时间关联，区分真实丢失、裁切与显示问题。左右触地正确性另需人工/光栅参考，不从速度日志或骨架存在推断。新问题继续双方有据互审，现场通过后才整合到 `vae/iron_jump`，保持现有未提交进展。

### 6.12 第 9 轮：首轮真人识别与时间证据，仍需取景及完整动作验收

原始来源：主工作树 `exports/control_integration_20261008/field_walk_01/{events.jsonl,capture.csv,report.json,start.jpg,end.jpg,samples/}`。控制侧独占Windows任务与SDK并取回证据；本侧没有开启相机或第二任务。报告实际 errors=[]、sdk_stop_reply=true、stop_unconfirmed=false，hardware_motion_verified=false；控制侧另记录用户反馈“转动一切正常”，属于现场操作者观察。7509个原始帧，CSV最后elapsed为75.0866084s；原始MJPEG留在Windows，sample图由原始CSV offset/length读取。本侧实看15帧联系图，不把requested_phase当真人动作真值。约5～25s全身直立、30s侧面，40s头顶贴上边界，45/55/65s弯腰、50s抬膝、60s直立头部裁切。5秒采样图不能证明两个采样点之间动作不变或全程物理运动。

新增可复跑只读分析，不改识别/控制实现：

```bash
/Users/vae/Projects/Iron_Jump/.venv/bin/python \
  /Users/vae/Projects/Iron_Jump/exports/tracking_diagnosis_20261008/field_walk_01/audit.py
```

输出 `exports/tracking_diagnosis_20261008/field_walk_01/metrics.json`。1243个pose_input含1202个pose packet，但去重后943个真实姿态，不能按重复传输包冒充推理次数。其中942个在录制中，按metadata.frame_index与CSV.capture_frame_index精确关联，sample_time差全部0；另1个发生录制前。全部保留33点。warming_up14、ready929，没有收到degraded/reset；本轮不能外推光栅事件同步已解决。

| 原始姿态至控制时间（943个去重姿态；毫秒） | 中位 | P95 | 最大 |
| --- | ---: | ---: | ---: |
| callback→decode | 9.62 | 15.03 | 37.48 |
| callback→推理开始 | 10.55 | 17.18 | 37.68 |
| 推理耗时 | 24.51 | 29.49 | 65.48 |
| 推理结束→SDK子进程收到JSON | 30.65 | 59.04 | 69.11 |
| callback→子进程收到JSON | 66.83 | 96.65 | 121.15 |
| 635次非零native调用开始时的原帧年龄 | 107.25 | 143.92 | 156.20 |

最后一行通过tracking_decision.captured_at精确匹配同一原始inference，再用SDK started_at减min(raw callback,mapped timestamp)，635次全部有来源，不使用父进程observed_at代替调用时间。没有stale_frame决策或超过250ms的非零调用；这证明本轮日志中的时龄门控正常，不是端到端真实曝光延迟测量，也不证明驱动内部从未缓存旧图。SDK调用及停止应答不能单独验收实体运动。

**识别与控制条件分开统计**：录制中942个独立姿态，严格下肢完整686（72.8%）、控制六核心点有效835（88.6%）、可靠点留6%边界438（46.5%）；身份stable780、unavailable115、ambiguous47。逐帧独立重算十点原阈值条件与日志framing.ready一致，0个矛盾。这些均是模型有效性/身份状态指标，不是人体解剖左右标注或触地准确率，严格下肢也没有检查头顶。

5～25s的253个姿态严格下肢253/253；28～32s邻近侧面采样的50个姿态严格39/50，失败11个均为右膝质量低（其中身份低质量6个）。此区间动作完整真值等待更密原帧，不能把50帧全部声明侧面。45～50s严格0/63，右脚跟质量低63/63、左脚跟低43/63，同时弯腰/双腿重叠，身份stable17、ambiguous16、unavailable30；这些低质量不是全部因脚越出图。50～55s严格24/63、55～60s34/64，右脚跟低质量仍主导。68～74s严格53/74，右膝低质量20次；等待更密侧身原帧核对。

**需要控制侧处理/验证的取景假设**：5～25s邻近采样推理的可靠点高度约0.806～0.836；40s为0.927，已超过控制fits阈值0.88，近场距离确实可能影响余量。但弯腰也使可靠点中心下移：55s邻近推理nose_y=.275、bounds_y=.229～.952、前一pitch指令+7.58；随后直立/抬膝时头部出框，50s鼻点y=-.076且质量.982，60s鼻点y=-.014且质量.998。这些推理与原采样帧索引差-1～+3，不冒充同一原图逐点精确标注。

控制 `vision/gimbal_tracking.py:body_framing()` 只将in-bounds可靠点纳入bounds；越界鼻点被排除，剩余肩/髋/踝仍可生成tracking。于是“弯腰后俯仰下移，直立时裁头，越界头部反馈恢复不足”与“近场高度超余量”均有机制/证据支持，尚不能断言单一根因；已要求控制侧结合35～65s时序评估历史站立身高/头部余量及俯仰恢复。该模块归对方，本侧不修改，原模型/阈值/640整图均保持。控制target有效和严格下肢ready不能代替真实头到脚入镜。

**下一轮协作**：控制侧按实际pose frame_index补抽27～34s及68～74s每秒原帧供本侧核对侧面；控制侧处理完整头脚取景策略。用户没有看见标题/听见提示音，自行做动作；控制侧按用户要求仅改自有工具为大字无声（提交e74a7b8），实际Windows可见性仍需确认。快慢横移、短时离开恢复及正式主窗口停止/回放/重启/退出未完整执行，不能提前通过、合并或删除分支。双方先分析保存证据再提出具体补测；本侧仅新增分析脚本/结果和更新detect.md，不修改control.md。

### 6.13 第 10 轮：精确原帧复核及水平提速独立验收

控制侧补抽28张 `field_walk_01/exact_samples/` 原始JPEG，本侧逐项关联其index.json与事件metadata，28项frame_index/sample_time全部精确匹配，结果保留本侧 `field_walk_01/exact_samples_metrics.json`（位于tracking_diagnosis证据目录）。本侧实际查看28/29/31/32/70/71/72/74秒等原图：28/29偏正面，31背侧，32背侧迈步，70～74侧/背侧且转头；不能把28～32整段标成纯侧面。31秒帧3126 right_knee quality=.62063，strict下肢false但identity stable；原因是strict原阈值.65与身份核心门控.60职责不同，非接口矛盾。74秒帧7423 right_knee quality=.36108并伴右踝低质量，strict false且identity unavailable。图中双腿部分遮挡/重叠，有机制支持质量下降，但没有完整人体关节真值，不声称模型位置或解剖左右已正确。

70/71秒实际头顶贴边或被裁，而同帧鼻点y仍约.093/.074；这再次直接说明可靠鼻点留边不是头顶留边。50/60原帧的裁头与原预测鼻点越界亦一致。控制侧核对48～54s在鼻子出框时pitch已向上恢复，55/62s弯腰时仍会向下；双方决定先以稍远且完整入镜的标准行走动作补测，暂不无证据增加历史身高/头顶估算策略。若标准距离自然行走仍裁头，再基于保存时序复现控制缺陷。已知靠近/大幅弯腰取景限制保留，原模型不改。

用户在控制对话反馈“检测效果非常好，追踪也不错”，并要求水平转动更快。控制侧提交 `88c630e` 的实际diff已由本侧读取：`vision/gimbal_tracking.py` 默认pan_gain由240到300、pan_max由90到120；同步独立CLI默认、自有测试预期及现场configuration记录速度参数和controller/tool SHA。pitch、质量、时龄、模型与识别公共出口没有改。本侧没有修改对方这五个文件。

针对新增差异运行，而非重复稳定全套：

```bash
IRON_JUMP_CONTROL_ROOT=/private/tmp/tinyse-integrated-20261008-r10 \
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen \
/Users/vae/Projects/Iron_Jump/.venv/bin/python -m pytest -q -p no:cacheprovider \
  /Users/vae/Projects/Iron_Jump/tests/test_pose_control_contract.py
```

本侧独立结果 **13 passed in 0.48s，无跳过**。另加载r10实际控制源码，以同一943个去重原始姿态分别调用旧TrackingSpeeds(240/90)与新默认，835个有效目标的pitch逐帧完全相同，所有非零pan比例1.25（浮点范围1.2499999999999998～1.2500000000000002），max81.14657→101.43322，新cap120触发0次。独立结果见 `exports/tracking_diagnosis_20261008/field_walk_01/faster_pan_independent.json`；controller源码SHA `e52b9f155ff6a78d96f6c82f5ffa8f80c0f03767c8054b56817263fd5fdc3c0e`。与控制侧重放报告相符，但共同输入同一保存姿态，不能独立证明实体速度增加25%或新的运动反馈仍稳定。

控制侧报告其相关92项本地回归通过，Windows90通过/2跳过；已解释两项为候选目录缺历史side_audit输出，本侧13项在主工作树含历史证据实际执行，不把Windows skip算通过。Windows新参数与5文件增量哈希由控制侧核对；本侧没有重复部署。大字无声工具属于自有控制工具改动，实际现场可见性仍需确认。

本轮没有识别接口新阻断，已主动通知控制侧可唯一邀请 `field_walk_02`。需验证：标准距离全身留边、正侧面、普通与较快横移、短时离开返回、提速后是否过冲/来回摆动；正式App停止/回放/重启/退出证据范围仍需补足。合并前核对主工作树既有修改与控制增量，现场未完成前不合并。本侧本阶段仅更新本文件与独立分析证据，不改control.md、识别模型或对方实现。

### 6.14 第二轮实机与合并依赖范围核对（仍未合并）

控制侧唯一启动 `field_walk_02`，主工作树已取回events/report/CSV及每3秒原始sample索引/图。本侧实际读取configuration：原模型5134...、pan_gain300/pan_max120、pitch80/max30、FOV请求0/zoom1，controller SHA e52b...，tool SHA `1f99460a72fc53b5353d2e45290e45ffc127585aff87e22987a6e2a92733915a`，不能由目录名924fe47推断当前源码。report errors为空、stop_reply=true、stop_unconfirmed=false。录制7505帧/75.044s。

为避免覆盖首轮，同一只读audit增加source/output参数：

```bash
/Users/vae/Projects/Iron_Jump/.venv/bin/python \
  /Users/vae/Projects/Iron_Jump/exports/tracking_diagnosis_20261008/field_walk_01/audit.py \
  --source /Users/vae/Projects/Iron_Jump/exports/control_integration_20261008/field_walk_02 \
  --output /Users/vae/Projects/Iron_Jump/exports/tracking_diagnosis_20261008/field_walk_02
```

结果保存独立metrics：945去重姿态，944在录制中与CSV精确frame_index/sample_time匹配（全部差0），1帧录制前；33点完整、strict重算与日志0差异。708次非零SDK调用都有精确原帧来源，调用开始时帧年龄P50=93.04ms/P95=130.36ms/max147.83ms，无超过250ms。推理耗时中位26.62/P9531.25/max79.60ms；推理结束至child receive中位30.16/P9558.59/max67.86ms。不能把与首轮的时龄变化独立归因于速度参数，两轮动作/站位不同。

录制中strict下肢831/944（88.0%）、control六核心913/944（96.7%）、可靠点余量645/944（68.3%）；identity stable796、unavailable76、ambiguous72（其中swap_suspected1/swap_detected2）。这些是模型/因果判定，不是解剖左右正确率。首轮边算边发给控制侧曾暂写strict829?，已立即按最终metrics纠正为831，不以猜测数值作为验收。

本侧实看25帧联系图：6/9/12、36/39/42与54/57/60有横向行走，18/21侧面，24～33正面；15/66/69靠近时头部仍贴边或裁切。57s人仍在远处图内，没有真正空画面；运行中的日志没有no_pose，与原图相容，不能验收完全丢失后恢复。

**侧面测量仍有独立瓶颈**：17～23s的74个独立姿态严格26/74，48次左膝低质量、43次身份核心低质量；25～35正面127/127 strict，35～45横移125/125 strict，50～62横移147/153 strict但有交换疑似/确认判定。原模型输出仍在持续，控制core不要求膝有效，所以能跟随与严格下肢/身份暂不可用并不矛盾。不能降低原阈值隐藏失败，也没有证据要求更换模型。此缺口不阻断“SDK相机跟随”集成，但仍阻断宣称左右触地准确性、全部侧面识别问题或全部失踪恢复已经解决。

**双方约定的最小剩余验收**：控制侧询问用户大字是否可见、速度是否满意、是否过冲，回复尚未由本侧读取；再自动用同一真实Panel/SDK验证显式停止→回放→回实时→重启→关窗，确认旧ownerclosed/零速应答及无双owner，无需再邀请75秒动作。正式MainWindow退出guard已有真实Qt模拟回归，完整App还牵涉USB/voice/其他主树工作，本轮不要求扩张到全App现场测试；合并报告必须明确完整App实体退出尚未复测。停止应答/画面静止也需区分，不扩宣物理制动保证。

**合并前实际源码范围（本侧仅检查，不stage或commit）**：主树下列识别/采集文件与固定r10逐字相同，已核SHA，不能用控制分支旧版本回退。候选经过测试但含主树既有未提交代码，不等于干净HEAD。

| 范围 | 必须保留/纳入的文件或增量 | 原因/边界 |
| --- | --- | --- |
| 新公共识别与帧来源 | `vision/live_walking.py`、`vision/framing.py`（新增），`vision/service.py`当前metadata/包装/latest_frame_only | SDK唯一消费当前主界面原识别；live模块整个文件含既有步态核验流程，不能只取声明遗漏适配器/时钟/状态 |
| 原识别调度和断流恢复 | `vision/event_scheduler.py`、`vision/leg_identity.py`主树已验证改动 | 此前同步/断流修复，现场候选依赖此版本；纯SDK控制可与光栅独立，但若声称交付与验证候选一致应保留/纳入，不能退回旧调度 |
| 采集与显示 | `camera/tinyse_camera.py`当前最新帧压缩输入、后台解码、capture-owned stop；`vision/pose_overlay.py`镜像及不画低质量点 | 本轮实测及原稳定显示依赖，control分支中tinyse旧代码不代表候选；显示条件不改变模型 |
| 既有未改识别资产 | `vision/mediapipe_pose.py`、`vision/foot_reference.py`、`vision/time_sync.py`、原模型 | 已被Git跟踪、当前无diff；核hash即可，模型不重写 |
| 正式走路视图识别接线 | `ui/views/execution_view.py`configure→set_vision_enabled、on_gait_snapshot→on_walking_snapshot两个增量 | 其余光栅UI提示文案属于此前UI优化，保留但不因SDK合并自动stage整文件 |
| 共享控制/UI | `camera/control_service.py`（主树已有untracked基线）、`ui/embedded_camera_panel.py`、`ui/main_window.py` | 需按当前main基线叠加control增量，不能按cc0bc7f整文件替换；mainwindow当前主树SHA ebc4...与控制原复制基线一致，panel当前SHA02087...，r10这两文件与main不同是预期控制改动 |
| 识别回归 | 新`tests/test_live_pose_updates.py`、`test_live_walking_vision.py`、`test_vision_framing.py`、`test_pose_control_contract.py`；现`test_pose_overlay.py`、`test_camera_analysis_frames.py`、`test_tinyse_camera_capture_recording.py`、`test_vision_event_scheduler.py`有关改动 | 新公共测试导入live_walking测试stub，必须一起跟踪；后续不以跳过历史保存证据冒充通过 |

控制新增纯模块、wrapper源码/DLL和其测试/工具由控制侧自列范围；本侧没有擅改。主树hardware/engine/agent/reporting/论文/led_con和其它UI任务不由本次控制集成自动认领；依旧保留未提交状态。大量exports录像/ZIP、现场人像、临时快照不应被git add全部提交。最终完整App运行若依赖其它主树既有dirty模块，须额外标明基线和交付范围，不能拿当前整个dirty环境通过当作干净checkout可复现证明。控制侧已收到具体范围及边界，现场最小剩余步骤结束后才决定整合。

### 6.15 用户验收范围收敛与识别提交准备

控制侧回传用户field02明确“一切正常，效果非常好”，并进一步确认极端裁头合理、优先髋部以下、再考虑上半身；“刚才的就挺好，不需要大规模改动”。本侧据此调整协作验收边界：近场/极端头裁不单独阻断本次相机跟随合并，不再要求新增历史身高/头顶估算，不换模型或调质量阈值。侧面膝部低质量和左右触地准确性缺口仍如实记录，不把用户对跟随满意扩成测量准确率验收。控制侧继续执行单次最小Panel生命周期，本侧不另开设备。

按双方职责，准备识别/采集依赖独立提交；主树索引经检查为空，双方约定本侧提交期间独占索引，控制侧只读备份/现场生命周期。明确内容：6个vision文件（live_walking/framing/service/event_scheduler/leg_identity/pose_overlay）、camera/tinyse_camera、有关camera/pose/scheduler/live/public测试、detect.md及execution_view仅configure/set_vision_enabled和snapshot/on_walking_snapshot两个接线hunk。tests/test_vision_landing_v2.py原有唯一改动为scheduler多事件分次pump兼容，随调度修复纳入。

为避免混入硬件引擎任务，**只选择索引内容，不改工作文件**：新增test_live_walking_vision排除两项WalkingSession实体snapshot测试，新增test_sync_regressions仅选择独立视觉缓存/截止/缺证据用例及其helper/import；完整工作文件保留原硬件/engine用例，提交后仍有剩余dirty内容。纳入纯test_walking_vision_pipeline（landing_pose helper、断流/身份/原始姿态回归），保证所选同步测试不依赖未跟踪helper。test_live_pose_updates及public契约所导入Service helper一并跟踪。没有抽新生产架构或重写已有算法，没有stage其它UI/hardware/engine/agent/论文、control.md、共享Panel/MainWindow/control_service或大exports。

另建 `/private/tmp/iron-jump-recognition-clean-20261008`：`git archive HEAD` 后仅覆盖上述明确识别内容/所选索引测试/execution两个hunk，以及待控制集成的7个明确文件（camera control_service/gimbal_control/pose_tracking/pose_transport/tracking_runtime、vision/gimbal_tracking、ui/embedded_camera_panel）。没有复制其它dirty主树源码。使用当前venv/offscreen/no-bytecode/no-cache，运行live_pose_updates/live_walking/framing/public_contract/service/scheduler/sync/walking_pipeline/leg_identity/overlay/camera_analysis/camera_recording/landing_v2，共 **162 passed、2 subtests passed、2 skipped in 1.01s**。skip是该干净副本缺历史side_audit输出；此前r10的13契约含这些输出实际通过。这证明选定识别加已审控制依赖的独立闭包，不等于识别提交单独包含控制UI或整个App已实机验收。

控制侧现场生命周期脚本已只读审阅：同一Panel独占SDK/DS，显式stop应答后再恢复、回放确认停速、新Vision、旧ownerclosed后再重启、关闭保持Qt到closed，没有发现新阻断。本侧不运行该硬件脚本。识别提交完成后立即回传hash并释放索引；控制侧再处理共享Panel必要既有基线和自己增量、MainWindow只close guard的三方/索引合并。任何双父合并都必须保留主树其它dirty内容，不能盲git add全部或把控制branch复制外观基线当作本次增量。
