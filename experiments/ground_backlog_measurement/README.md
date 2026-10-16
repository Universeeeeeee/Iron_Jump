# 实际队列测量与现场负载匹配

本目录用于诊断。基于 `codex/beam-painter-state` 的 `3020bb1`，沿用原 NumPy、A/B 绘图器原件和独立语义 oracle；未更改正式程序。最终判断见 [RESULTS.md](RESULTS.md)。

## 测量定义

定义和门槛在 [plan.json](plan.json) 固定，文件 SHA-256 在 [plan.sha256](plan.sha256)。六轮初始负载检查之后、任何新 A/A 之前，增加真实 USB 后台采集负载；原计划另存于 `harness_versions/scout_v2/`，没有调整验收阈值。所有负载检查均用原绘图器 A、详细观察器 P，不能当作 A/A 或候选收益。

- `queue_probe.py` 对实际 `_GroundFrameInbox._pending` 加既有锁取长度和队首接收时钟，保留已弹出但尚未调用 consume 的交接状态及正在处理的批次。`pending=0` 不能单独表示消费完成。
- `unfinished_at_batch_boundary` 是最新接收 sample 减去最后完整消费批次 sample；扣除 pending 后得到弹出/批内数量。它可能包含当前批内已经处理的帧，不能解释为逐帧剩余工作量。固定输入 sample 连续、没有 issue，才适用此差值。
- L/P 共同在消费批次跨过 64 sample 桶时记录快照，并记录最终 EOF 完成点。P 额外由独立 Python 线程约 10 Hz 记录状态，没有逐帧时钟、嵌套阶段计时或 CPU profiler。该线程仍受 GIL 调度，采样空档必须保留。
- “排空”改为最后有效接触计划到达之后，首次观测到 `pending=0 && unfinished=0` 的快照时间。它是首次实际排空的观测上界，不是未观测到的精确排空时刻；不存在则记为删失。稀疏快照之间可能漏掉排空或峰值。
- 最后接触之后的完成年龄 P95/max、空队列见证点中超过 25 ms 的完成年龄另报为短时延迟观察，不用“连续 500 ms 年龄小于 10 ms”替代排空。
- 每阶段消费 fps、实际到达 fps、相对 1000 Hz/实际到达的吞吐缺口、年龄斜率、pending P95/max、最老待处理年龄、估算队列面积、采样最大间隔一起保留。超过 1000 fps 的有限窗口可来自追赶和边界，不能视为设备容量提升。

13 列快照顺序：`host_ns, completed_sample, completed_receipt_ns, pending_count, oldest_pending_receipt_ns, latest_sample, latest_receipt_ns, unfinished_at_batch_boundary, popped_or_inflight, phase, batch_first, batch_last, batch_size`。原有 `common` 三列仅为前面三列的兼容视图。

## 受控负载

Windows 原生 enabled GUI，归档光束与原始 MJPEG 是主算法/视觉的唯一输入；真实 SDK 全身追踪开启，核对非零速度调用及实际有效骨架绘制。预览选择规则与上轮保持一致。没有人为延迟消费者、复制推理、增加解码或伪造接触数据。

| profile | 增加的实际工作 |
|---|---|
| fixed | 固定光束/图像回放、GUI、推理、真实 SDK、骨架 |
| capture | fixed + 原 TinySeDShowCapture 1080p、请求 100 fps，含原生到 Python 字节复制回调 |
| record | capture + 原生 MJPEG/CSV 录像 |
| hardware | record + 原 UsbWorker、原 DLL、真实光束设备读取/解析/组帧；实时帧另存，禁止进入主算法 |

原程序预览选择上限也是 30 Hz，归档 100 Hz 图像经时间选择约 25 Hz；因此不能把之前回放缺失的负载简单归咎于预览少了 100 fps。原生采集回调、录像、真实 USB 输入和实际图像压缩复杂度需要分开核对。后台相机拍摄内容与归档内容不同，记录实际 fps、字节率和 writer drop，不能宣称负载完全相同。

所有运行使用新独立目录。失败、功能检查、负载检查不覆盖、不混入 A/A；`harness_versions/` 保留源代码修订。`packet_source.py` 仅验证归档 payload 通过原解析器/组帧器；封装格式来自 9 月 29 日独立协议夹具，缺少 10 月 15 日实际包边界，故从未用它制造 GUI 压力。

## 顺序与核验

1. 栅栏测试确认交接间隙、空 deque 的忙碌批次、并发到达、实际队首年龄及最终 EOF 空见证。Mac/Windows 分别运行 `QT_API=pyside6 python experiments/ground_backlog_measurement/test_queue_probe.py`。
2. 功能检查后执行预定负载检查。只有同一负载在走路、跑步各三轮都满足冻结的持续不足门槛，才允许新 A/A。初始单轮即失败的 profile 不满足此条件。
3. 新 A/A 若启动：仅 A，走路/跑步交错，各六对 LP/PL；冻结代码哈希后运行；任何指标失败或排空见证缺失即停止 A/B。共同观察器的开销仍未被 L/P 增量校准排除。
4. A/B 若获准：仅已有 beam_layer 候选，六对 AB/BA；比较预先固定的吞吐缺口、队列面积、最老待处理年龄、脚印延迟。收益须超过 A/A 噪声和实际门槛；不要求突破 1000 Hz 上限。
5. 每轮检查完整 bits/wire/validity、sample/frame counter、stream/flags/drop、原始归档、质量历史、runtime/window、完整报告、事件 audit/timeline/mirror 和脚印发表集合，对比独立原 NumPy oracle。仅核对后归一化两个自检接收时钟。458 个基线文件及 A/B 绘图器逐哈希核对。

`windows.py` 同步到隔离 Windows 根目录并启动交互式任务，试验中不进行三秒任务查询或截图。`batch.py` 的驱动进程只检查完成标记；SDK 关闭和成功序列化之后才能处理原生退出遥测阻塞。`analyze.py` 必须先通过 `semantics.verify` 才产出指标。

Windows 根目录：`E:/OptoJump/IronJump-ground-backlog-measurement-20261016`。本地根目录：`/Users/vae/.codex/worktrees/ground-backlog-measurement/Iron_Jump/experiments/ground_backlog_measurement`。输入、原始输出与 oracle 被 Git 忽略；清单保留 SHA-256。较大原生相机 MJPEG 留在 Windows 对应试验目录，测量记录含大小与哈希。

## 解释边界

真实 USB 后台负载包含原生读取、原协议解析、原组帧、信号分发和单独原件保存；主算法输入仍由固定回放线程构造并发出。因此它是可重复性待检的受控竞争场景，并不逐周期等同于“同一个 USB 流直接进入主算法”的现场拓扑；两路帧对象/信号和保存开销的差异须单独验证。相机真实采集内容也不同。仅凭切换此组合负载后的队列变化，不能将全部差额归因给 GIL、USB 解析、相机录像或 Qt 调度中的某一项。

采样线程和 common 消费点共享 Python/GIL 调度。没有原生线程 CPU 时间、GIL 持有栈或 ETW ready-to-run 证据时，消费完成年龄只能定位延迟发生的区间，不能区分独占计算与等待。真实空场后台原件为后续解析成本和实际收包节奏提供独立输入；仍需遵守先校准、再做逐因素消融的顺序。
