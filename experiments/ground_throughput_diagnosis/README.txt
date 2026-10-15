地面 1000 Hz 吞吐诊断（实验分支，不启用性能候选）

基线：codex/runtime-single-frame-fusion 的 5e1686469e789e5bae0e3c2fd47a5a1d191fd60d。
原 hardware.walking_preflight.RuntimeBeamEvidence（NumPy）保持不变；不导入或安装上一轮 Numba 候选。
本目录脚本仅在隔离进程中观察正式类；部署包校验后，逐轮核对实际原程序源码的 458 项哈希。

顺序：plan.json/.sha256 → phases.json → Windows 独立同步 oracle → M/D 六组交错 A/A → 独立外部采样。
M/D 的算法完全相同。M 只保留既有回放事件观察和批次完成里程碑；D 增加批次、Qt 与 1/64 抽样调用树。
校准衡量 D 相对 M 的增量扰动，不能证明零观察开销，也不构成统计等价性检验。
帧完整、事件、报告、质量历史与运行时计数核对在计算性能指标之前进行。

probe.py：每个被抽到的 quality 根调用记录完整同步子树，独占成本=本次调用总量-直接子调用总量。
每棵树分别验证墙钟、GetThreadTimes 计数、QueryThreadCycleTime 周期三种量的加法守恒。
包含嵌套层次的 inclusive 列不能相加。阶段样本均值包含抽中帧自身的测量成本；稀有 summary 调用可能方差很大。
observer_check.py 是空调用测量下限，不用于机械扣除真实 GUI 的成本，更不是应用优化收益。

Windows GetThreadTimes 实测粒度 15.625 ms，尽管 get_clock_info 声明 100 ns。它不支持逐调用 CPU/非 CPU 时间分解。
QueryThreadCycleTime 使用 PyDLL 保持查询时的 GIL；周期只作为原始计算量，不能换算为 CPU 毫秒。
墙钟-GetThreadTimes 差值不用于计算 GIL 等待。已有积压时的 drain 间隔也不是纯 Qt 延迟。
Qt awake/aboutToBlock、零/5ms timer 状态与线程 ID 保留用于交叉检查。

external.py/external_target.py：GIL 持有者样本、全部 Python 线程、原生栈分开运行。
GIL 采样使用 Speedscope 的实际样本数；Chrome trace 在未捕获该线程时会延长上一段，不能据此计算 GIL 持锁时长。
外部轮会额外记录骨架实际绘制、保存第一张 live_overlay.png，并计量低频 summary/snapshot 调用。
原生采样会暂停进程、截图也会额外绘制，因此外部轮不进入基线性能或 M/D 校准。
外部采样失败必须保留并报告，不冒充已得到原生等待归因。

场景：从录制数据预先冻结一秒设备窗。仅为分析标签应用既有坏点掩码（576），不改原始帧。
接触占比 >=50% 为 dense，<=1% 为 empty，其他为 mixed；空场前后分列。
步行末端空场只有 173 ms，不能据此声称长期恢复能力。每轮跑步/步行仅 7/10 次触地，P95 是小样本描述。
消费 fps 与设备队列年龄斜率同时报告；额外报告原录制到达率和回放 reader 计划迟到，避免把供给变慢算作消费提升。

录像：跑步沿用上轮 raw MJPEG+CSV；步行仅有历史 MJPEG AVI 和相对 timestamps.npy。
prepare_walk_media.py 从现存 AVI 无损解封装 JPEG 包，不再编码；旧原始 JPEG 和首帧精确偏移已不可恢复。
每个模式的各轮均使用相同字节及索引。此回放不覆盖真实 USB、相机驱动和录像写盘。
沿用旧回放的固定采样号准备协议、有限 EOF 后排空规则与已验收的 GUI 几何缓存。

结果入口：results.txt、runs.csv、phases.csv、stages.csv、summary.json（以实际存在的完成记录为准）。
原件：本工作区 runs/、oracles/、*.zip、*.log；Windows E:/OptoJump/IronJump-throughput-diagnosis-20261015。
大型逐轮报告/原帧/采样原件不重复加入 Git；evidence_inventory.json 应保留路径、大小与 SHA256 便于复核。

复现：独立新的 Windows 目录与任务名，不能覆盖已完成输出。windows.py 中路径为本次固定隔离目录。
部署前先准备对应的录制资料；旧目录是只读来源。不要对现存完整目录再次运行 deploy/media/oracles/calibration。
核验：python analyze.py → python export_tables.py；外部核验入口以最终记录为准。

准备阶段保留的失败：首次部署发现历史步行 raw JPEG 已不存在，转而核对并解封装既有 AVI；
首次同步 oracle 逐帧解压 NPZ 导致不必要耗时，已停止，改为一次读入选定数组；随后修正了同步 oracle 的未来接收时钟导致的自检拒绝。
这些均在 GUI 计时之前，不属于应用吞吐结果。最终 oracle 必须与独立旧报告及 GUI 报告一致。
SSH 间歇中断，改用本次专用复用连接；远程任务按实际完成文件和状态核验，不把断线当作试验成功或失败。

测量定义：
https://docs.python.org/3.11/library/time.html#time.thread_time
https://learn.microsoft.com/en-us/windows/win32/api/realtimeapiset/nf-realtimeapiset-querythreadcycletime
https://github.com/benfred/py-spy
https://github.com/benfred/py-spy/blob/v0.4.2/src/chrometrace.rs
https://github.com/benfred/py-spy/blob/v0.4.2/src/speedscope.rs

补充：回放工具自身的显示状态问题
父回放在 offline 时禁用整个 camera panel；Qt 会生成 disabled icon 图像，实际视频为灰度。
原生快照与像素核对互相印证；该额外负载不代表正式 enabled 预览。enabled_replay.py 只改这一行。
preview_state_* 是 enabled/disabled/enabled 的探索试验，原 NumPy、原始帧、完整报告均核对一致。
它未替代失败的 D/M 校准；enabled 跑步仍有 660 fps 慢轮，不能宣称吞吐问题已解决。

补充：真实现场
用户随后确认现场可测，要求 SDK 全身追踪和关节点绘制均开启。
live_plan.json 冻结现场条件；live_replay.py 使用真正 UsbWorker，SDK 成功应答是开始门槛，
显式打开 show_pose_action，保留 Tiny SE 原始录像；默认 30 秒，开始后 5 秒空场再单次通过。
机位准备等待上限延长至 600 秒，测量仍为 30 秒。现场 M + SDK/实际骨架绘制旁路证据没有单独 A/A，
仅用于复现和一致性核对，不提供正式阶段 CPU 分解、干预收益或长期 1000 Hz 保证。
采集证据增加 valid_bits、dropped_frames_before、quality_flags、stream/layout、issue 与帧顺序；
这些只追加到实验归档，正式帧、质量判断、算法参数和报告未改变。
live_target.py 保留原 Qt 槽，额外旁路订阅 CameraControlService 信号；统计真实绘制的有效节点/连线。
analyze_live.py 用原收到的所有帧/issue、设备布局、有效性/缺帧标记、冻结准备点和停止边界，
在独立同步生产引擎中重算完整报告/质量/运行时证据，先相等后计算一秒设备窗口的性能。
Python dataclass 的 tuple 与 JSON list 经 JSON round-trip 统一表示，不删报告字段，也不改数值时钟。

现场准备失败均不纳入正式性能结果：
  live_walk_01：隔离目录缺 USB DLL，未开始。只从现有正式 Windows 目录只读复制驱动到新隔离目录，
                SHA256 相同，独立加载检查成功。live_driver.json 保留来源和哈希。
  live_walk_02：新增 readiness 记录含 DeviceLayout，JSON 序列化失败；SDK 探针 Qt 绑定也不兼容。
  live_walk_03 / 04：确认是探针替换 Qt 槽时名称/绑定冲突，CameraControlService 的 tracking_event.connect
                     报 im_func/SystemError；已保留原槽，改为旁路信号，不改正式程序。
  live_walk_05：SDK 实际成功，但 readiness 的 device_key 也含 DeviceLayout，状态记录/最终记录失败。
  live_walk_06：记录修正后 SDK 成功，相机开关与少量部分节点可见；机位朝桌椅、未正式开始，准备超时。
  live_walk_07：调整机位后全身/下肢状态通过、实际骨架可见，首轮完成的 30 秒走路现场试验。
close_preflight.py 只关闭指定本实验、未 armed 的准备窗口；没有强杀活动采集，也不操作正式程序。
首次走路独立重算保存成 JSON 后逐字段零差异；内存 tuple/JSON list 比较方式修正为统一 JSON 表示后通过。
这属于核验表示层修正，不是修改算法或放宽报告验收。
原始录像保留在 Windows 隔离 runs 中；大录像的整包下载曾中止，不能据此声称文件丢失。
metadata 包已独立下载；最终原件以 evidence_inventory.json 和 Windows 清单的 SHA256 为准。

最终现场与录屏补充：
用户未录屏的 live_run_01 已按明确要求删除整个输出目录及该轮 wrapper 日志/脚本，不纳入结果；
discarded_trial.json 仅保留删除缘由。正式跑步采用 live_run_02。
用户提供 /Users/vae/Projects/Iron_Jump/现场测试/10.15晚 两个录屏，并明确只看去程；
review_screens.py 只抽取去程边界内的画面，来程不计步、不当漏检证据。screen_sources.json 保存原件 SHA。
此前含来程的临时抽帧和 montage 已删除，仅保留去程抽帧；用户原始录屏没有改动。
人工步数 10/8 与脚印发布 9/8、界面有效步间隔 5/6 分开报告；独立同步重算没有把物理漏检变成正确。
analyze_live.py 记录具体缺失相邻区间、ownership barrier epoch、末步未知触地，以及跑步时间指标排除原因。
实际停止请求为走路 29.676 秒、跑步 23.512 秒；计划 30 秒不能冒充实际稳态观测长度。
inventory_windows.py 在两轮均完整结束后逐包核对原录像 CSV 的偏移/JPEG边界和完整字节数，保存 SHA。
final_audit.py 校验正式/旧目录与基线，windows_task_cleanup.json 确认没有本实验残留任务/进程。
