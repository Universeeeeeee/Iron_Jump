# beam_layer 三种 brush / pen 状态实验

基线：`codex/ground-throughput-diagnosis`，`e9be8a5f8f8b531d4ccc1e06bacef176190873ed`。实验分支：`codex/beam-painter-state`。

## 修改边界

唯一改变既有代码的位置是 `experiments/runtime_single_frame_fusion/fixed_geometry_cache.py::beam_layer`：每次重建图层预建三种 QBrush，颜色状态变化时才 setBrush；有效活动束画线后恢复 NoPen。循环中原有“两侧圆角标记、再横线”的顺序、几何、颜色、透明度及缓存键不变。`baseline_renderer.py` 是基线原件。

新增目录只提供像素验证、隔离 GUI 回放、独立顺序 oracle、采样和验收工具。正式 `hardware/`、`engine/`、Processor、滤波、UI 文件均以原 458 文件清单校验。使用原 NumPy，没有移植或合并，也不处理计步正确性。

## 像素验证

`pixels.py` 为新旧独立 widget / QPixmap 比较每个 RGBA 字节，无容差。Mac Qt 6.11.0、Windows Qt 6.11.1 各 1152 项全部相同，详见 `pixels_mac.json`、`pixels_windows.json`。

覆盖 96/768 束、DPR 1/1.25/1.5/2、两种尺寸、集成/独立背景、两个方向、详情/全程布局，以及空场、全活动、连续活动、边缘活动、坏点、交替状态、全坏、短 validity 数组、再次空场。DPR 显式绑定到 pixmap 的实际物理尺寸，同时验证缓存命中返回同一对象。

## 固定条件与证据

- 全新 Windows 目录：`E:/OptoJump/IronJump-beam-painter-state-20261015`，本地独立 worktree `/Users/vae/.codex/worktrees/beam-painter-state/Iron_Jump`。
- 复制上一轮 `live_walk_07` / `live_run_02` 原始光束及 MJPEG/索引。每份输入的大小、SHA-256 记录在 `input_manifest.json`。旧目录保持只读。
- Windows native Qt `windows` 平台；真实 ExecutionView、SessionController、原 inbox / 质量 / 算法 / 绘图链路。GUI enabled，相机录制原件预览、真实 SDK 全身跟踪控制、实际关节点/骨架 paint 同时工作。物理云台会执行 SDK 指令。
- 光束按原接收时序播放；相机按原索引和原时间对齐，原回放器选择至少 1/30 秒间隔的 JPEG（100 fps 归档约得到 25 fps）。保留过期帧计数、实际解码数、骨架绘制数和 SDK 指令证据。
- 从冻结自检点之前 3500 帧开始，保留所有原本接受的正式帧和运动后的恢复段。短准备段不冒充原现场完整准备历史；新片段的独立原 NumPy oracle 必须与 GUI 的完整报告/质量状态完全相同，且运动总结必须与原现场报告完全相同。
- 仅在固定文件 EOF 后免除“传感器持续断流”的定时停止，排空队列后手动结束。该协议同时用于所有轮次；不更改光束、算法事件、质量历史和报告内容。
- 报告只先核对、再归一化两处实际自检帧接收时钟。其余完整报告、质量快照、runtime counts/transitions/window、事件审计、timeline、mirror events、原始归档哈希逐项一致。保存实际交付的 bits/wire/validity/计数/顺序，并核对 stream/flags/drop 元数据哈希。
- 每次必须有完整 SystemExit(0) / serialization / SDK 关闭证据。仅在这些证据齐全后，允许结束退出阶段仍等待原生遥测的子进程；不把此等待计入性能。

## 校准、指标与决策

性能前冻结 `plan.json` / `plan.sha256`，功能检查后冻结 `frozen_sources.json`。不根据结果修改阈值。每模式先做功能检查，不用于性能结论。

A/A 每模式 6 对，LP/PL 交错，两边都是原绘图器 A。共同 L 仅在 inbox 批处理末尾跨越 64 个设备采样的桶时记录一次完成点；P 额外每批记录一次完成点，不记录逐帧/嵌套调用时间，不开 profiler。A/A 的两边都用共同稀疏点计算，避免观测分辨率不同形成偏差。这只能校准 P 相对共同证据探针的增量扰动，不能证明所有共同观察器零成本。

A/A 配对差中位数的绝对上限：密集消费 fps 3%、年龄斜率 5 ms/设备秒、脚印 P95/max 各 25 ms、恢复时间 0.15 s。缺失恢复不算通过，任一模式失败则不开始 A/B。

只有两个模式均通过，才进行 A/B：每模式 6 对 AB/BA 交错，均用 P。至少一个主指标的 6 对收益全部同向，配对收益中位数超过 A/A 绝对差的 P90，且超过 fps 5%、年龄斜率 10 ms/设备秒或脚印 P95 25 ms 的实用下限；其余指标不得超过相同的退化上限。六对同向仅作预先定义的复现筛选，不宣称多指标选择后的统计显著性。

指标口径：

- 以固定设备采样范围划分阶段，沿用上一轮原始数据的一秒窗口标签：屏蔽原已知坏点后，接触帧比例 >=50% 为 dense，<=1% 为 empty，其余 mixed。`empty` 是低接触窗口，允许极少短脉冲；进场前与离场后分别报告。
- 消费 fps = 完成采样计数差 / 主机完成时间差。年龄 = 最后帧接收到该批处理完成，包含队列等待及本批计算；不是纯 Qt 调度时间，也不用于嵌套成本归因。
- 年龄对设备秒做线性拟合。脚印延迟从对应 touch_sample 主机接收至 confirmed 脚印 Qt paint 完成；包括算法确认、消费、GUI 排队和绘图，不代表显示器物理扫描。走路每轮 9 个、跑步每轮 8 个既有发表事件。
- 恢复时间从最后可用原始接触的计划到达时刻开始，到首个随后年龄 <=10 ms、且后续 500 设备毫秒内持续满足（至少覆盖 450 ms）的消费点。无恢复记缺失，不记零；同时保留源线程迟到，以防把源供给迟到误认为队列改善。

## 复核方式

使用 Qt / NumPy 及项目依赖；Windows 原 SDK 硬件必须可用。所有 trial 输出目录必须不存在。

```sh
QT_API=pyside6 QT_QPA_PLATFORM=offscreen python experiments/beam_painter_state/pixels.py
```

Windows 隔离根目录内先运行 `batch.py oracles`，再运行 `batch.py smoke --suffix <新后缀>`，核验原始帧、报告、SDK 和绘图证据。源文件冻结后运行 `batch.py calibration`；仅当 `calibration.json` 两模式 pass 均为 true 才可运行 `batch.py AB`。`analyze.py calibration` / `analyze.py AB` 可从已保存 runs、inputs、oracles 独立复算。

大体积 inputs、runs、oracles、截图和日志保留在独立证据目录，不提交 Git；提交像素逐项结果、冻结计划/源清单、输入清单和性能汇总。最终结论见 `RESULTS.md`。
