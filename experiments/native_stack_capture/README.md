# 原生 CPU / 等待栈：采集工具与合成校准

2026-10-17，基于 `codex/native-stack-symbol-preflight` 的 `c85612f0aa14b77e240b10485a1f88b40ebc6d26`；本阶段分支 `codex/native-stack-capture-calibration`。

**前一阶段的六对合成校准通过冻结门槛；最终外部观察器的后续验收见 [EXTERNAL_RESULTS.md](EXTERNAL_RESULTS.md)。现场定量归因尚未就绪。** 本轮没有新增人体测试，没有启动正式 GUI、USB、相机或 OBSBOT 服务，没有 Run 模式测试、优化 A/B、库替换或正式程序修改。合成进程只使用 Python 算术、Qt 等待对象和系统等待；双进程外部观察冒烟中的 `gui/sdk` 是路由标签，两者都是新建的 Python 定时等待进程，不是真实 GUI/SDK。

## 工具和验证顺序

1. `cpu.wprp`：只启用 ProcessThread、Loader、SampledProfile，且只采 SampledProfile 栈。`record.py cpu` 在自有 WPR 会话启动后，用公开 `TraceSetInformation(TraceSampledProfileIntervalInfo)` 将 timer source 设为 **10 ms / 100 Hz**；同时保存原值、API 回读和 ETL SetInterval。停止后恢复原值。配置值、回读值、实际样本/CPU 账本三者分别检查。
2. `wait.wprp`：只启用 ProcessThread、Loader、CSwitch、ReadyThread，且只采 CSwitch 栈；**没有 CPU 采样，也没有 ReadyThread 唤醒者栈**。等待栈不是低频采样，可能比 CPU 方案扰动更大。两套配置均为 128 KiB × 256 buffers、file mode，短窗默认 6 s，上限 10 s。
3. `record.py` 每次只接收一种模式，使用唯一 WPR instance 和实验目录排他锁，拒绝已知用户内核录制会话；不会取消别人的记录。异常也尝试停止自己的会话、恢复采样间隔并保存日志。不得自动删除遗留锁；先检查锁指向的记录和自有会话。修改栈开关、间隔、缓冲、观察器或负载都要重新校准。
4. `fixture.py` 是四线程合成见证：两条 Python 算术线程制造计算/GIL 竞争，另两条分别 `QWaitCondition::wait` 和经 ctypes 调用 `Sleep`。`GetThreadTimes`、线程 creation time、cycles、TID、QPC/FILETIME 都由实际 Windows API 读取，未把 Python `thread_time` 或调度驻留冒充 CPU。没有 Q(Core)Application、设备对象或 NumPy 运算。
5. `ReadStacks.cs` 使用 `OpenTrace/ProcessTrace` 读取已保存 ETL；原始 QPC 与 Windows 转换 FILETIME 两遍交叉核验。保留原始 payload、provider/opcode/version、header PID/TID 和 CPU。只接受本机已核验的 x64 SampleProf v2/16、StackWalk v2、CSwitch v5/28、ReadyThread v2/8；未知事件形状不能套结构继续归因。
6. `symbolize.py` 用实际 Image Load/rundown 的 base/size/checksum/path 对照当前 PE，记录 SHA。通过 `QueryDosDeviceW` 映射设备路径，不按同名 DLL 猜路径。离线 DbgHelp 不侵入目标进程，不执行目标 DLL；要求 PE RSDS、PDB 独立 GUID/DBI age、DbgHelp GUID/age 全部一致、SymPdb 且 PdbUnmatched=false；不使用 LOAD_ANYTHING，不将导出符号当匹配 PDB。
7. `analyze.py` 检查事件关联、线程生命周期、用户栈闭合、未知帧、内核段、歧义、时钟、计数与 CPU/cycles。`split_field.py` 现在强制执行独立 tracerpt 全扫描、双边主机时钟映射、起止线程身份检查和原 ETL 前后 SHA 复核，分别保存每个 PID 的报告及总 `acceptance.json`；任何一步失败都不能产生验收通过。`verify_runs.py` 另用 `tracerpt -o NUL -summary` 全扫描，`report.py` 比较独立事件计数和冻结门槛。`results02.json` 是当前接受结果；`rejected/` 是初始分析，不用于验收。

## 校准和验收门槛

`plan.json` 在六对测量前冻结，SHA 见 `results02.json`。CPU 与 wait 各三对，顺序分别 OFF/ON、ON/OFF、OFF/ON，每次全新合成进程、6 s。每对独立保存 CPU 执行工作量、GetThreadTimes CPU 和 cycles；三项变化均要求绝对值 ≤15%，双向比较，不把“变快”当作负扰动直接放行。这里只是工具合成负载验收，没有改变任何业务候选。

逐 ETL 必须满足：

- 文件头 EventsLost、BuffersLost、consumer loss 均为 0，tracerpt 全扫描 loss 为 0；Stack/SampleProf/CSwitch/ReadyThread 的独立计数与 reader 完全一致。
- PID/TID 与 Start/End 或 rundown 生命周期相符，线程 creation time 不变。经典事件 header PID/TID 可能无效，身份取经过核验的 payload；ReadyThread header 不是锁持有者/唤醒者证明。
- 实际栈关联率 ≥95%，用户栈到达 `RtlUserThreadStart` / `BaseThreadInitThunk` 的比例 ≥95%，多用户段/多内核段歧义为零。**到达入口是用户栈闭合的操作性检查，不代表所有内部函数有符号或内核完整。** 未闭合、缺段、未知符号、深度分布分别报告，不能合并成“全栈成功”。本轮没有依靠补栈或函数猜测凑完整率。
- CPU 样本总数 ≥100，实际 SetInterval=100000（100 ns 单位），样本 IP 与关联栈相符；NonProcess 的 ISR/DPC 样本单列并从线程执行 CPU 估计中剔除。两条高 CPU 见证线程的采样 CPU 与 GetThreadTimes 误差 ≤max(20%,30 ms)。低 CPU/短窗线程不能套用相对误差做精确热点判断。
- wait 逐线程 in/out 交替、运行区间 CPU 一致；调度驻留与 CPU 账本误差 ≤max(10%,30 ms)，cycles 必须有真实增量。cycles 不按固定频率换算秒，也不将驻留强行缩放到 CPU。10% 是本轮工具门槛，不是二者相等的证明。
- 原始 QPC 与独立 ProcessTrace FILETIME 转换符合所有观察时钟括号，最大越界残差 ≤1 ms。宽 ctypes 括号可能包含 GIL 重新调度，不能把宽括号的中点当真值。最终外部观察器另用双边 perf/QPC 括号生成到既有 `host_ns` 的映射；`align_clock.py` 拒绝旧版单边 perf 锚点或大于 1 ms 的映射不确定性。

**现场还必须重新做两套分开的扰动验收。** 后续 `external_plan.json` 专门冻结最终 `--targets` 外部观察模式，使用两个合成进程各四条工作线程，分别做 CPU 与 wait 各三对校准；结果与保留失败见 `EXTERNAL_RESULTS.md`。 冻结版本 `harness_versions/calibration01/` 保存本次合成测量使用的 observer/controller；最终外部目标模式采用保留线程句柄与更完整的时钟括号，已另作双进程冒烟。合成 workload 和外部冒烟均不能替代正式单 USB、相机/有效骨架/SDK 实际负载下的校准。现场比较必须同时保留实际接触负载、批次进度、pending/在途、延迟以及有效骨架和 SDK 状态；人体输入不可控时，只能给差异和不确定性，不宣布无扰动。

## 当前结果

|检查|CPU 三轮 ON|CSwitch 三轮 ON|
|---|---:|---:|
|目标线程事件 / 已关联栈|1815 / 1815|11757 / 11757|
|用户栈到达线程入口|1808 / 1815，99.61%|11757 / 11757，100%|
|含内核段的事件|12|11757|
|用户帧未知符号 / 用户帧总数|10 / 33510|7605 / 269119|
|用户地址无法映射模块 / 关联歧义|0 / 0|0 / 0|
|最大用户深度|27|35|
|时钟最大越界残差|2.8 µs|2.8 µs|
|高 CPU 线程与 CPU 账本最大相对差异|8.83%（采样 CPU）|9.30%（调度驻留）|
|事件/缓冲丢失及独立计数差异|0|0|
|各三对合成扰动及 trace 门槛|全部通过|全部通过|

CPU 三对工作量变化约 -2.41%、-4.03%、-0.25%；wait 约 +0.24%、-0.51%、+1.13%。CPU/cycles 的对比原值和双向门槛见 JSON。接近 15.625 ms 粒度的低 CPU 线程不能作百分比解释。

真实交付栈已验证以下可辨认路径（均限于合成进程）：

- `NtWaitForSingleObject → WaitForSingleObjectEx → _PyCOND_WAIT_MS → take_gil → ... → RtlUserThreadStart`。
- `NtWaitForSingleObject → WaitForSingleObjectEx → QWaitCondition::wait → QtCore.pyd+RVA → ... → RtlUserThreadStart`。
- `NtDelayExecution → RtlDelayExecution → SleepEx → ffi.dll+RVA → ... → RtlUserThreadStart`。
- CPU 算术路径可展开至 CPython 执行、整数运算和分配函数。

六轮均对 Python、QtCore、ntdll、kernel32、KernelBase、ucrtbase 的匹配 PDB 作了实际地址解析和独立身份检查。未知包装层依旧保存模块+RVA。**没有验证原 NumPy、MediaPipe/OpenCV 内部计算函数或内核内部符号已完整**；无符号 Windows 内核也保存实际映像、base 和 RVA，无法映射时保留原始绝对地址。SDK 精确 PDB 的静态能力沿用上一阶段，真实 SDK 等待栈仍待现场。

早期 CPU 探针 `cpu_probe02` 虽然所有 612 个样本都有栈，仍有一个内核采样 IP 未出现于关联栈，严格 IP 门槛失败。该探针没有被三轮正式合成校准的成功覆盖、删除或解释成“已完全通过”。首个 `cpu_probe01` 的权限结构对齐错误在负载开始前失败；会话已停止，没有改变采样间隔。初始 Image opcode 10 遗漏、设备路径未映射、宽时钟中点及 OldThreadID 栈关联尝试均保留为被拒绝的方法。

外部模式另用两个合成定时进程完成 PID 所有权、保留句柄读取、短窗、分 PID 导出和闭合栈冒烟，两份报告均通过；`external_smoke_verification.json` 保存结果。最终 QPC→host_ns 映射不确定性为 **16.1 µs**。这不证明真实 SDK 的全部线程或正式消费者已有完整栈。

`runtime_preservation02.json` 最终复核 **50 个运行映像、458 个冻结源文件、10 个缓存 PDB** 未变化，并再次核验旧 ETL SHA。只检查了 43 个早期 inventory 条目的第一次复核不是完整验收，以 50 个模块的 compact inventory 二次复核为准。新分支只新增本目录。

## 等待与计算的解释规则

本机交付的 CSwitch 栈 payload TID 对应 **NewThreadID / 切入线程**，栈的原始关联时间来自 StackWalk payload，不能用晚到的 StackWalk header 时间，也不能直接归到同一 CSwitch 的 OldThreadID。先把同一 TID 的上次切出（state=Waiting）与本次切入配对，再解释已恢复的等待调用链。`paired_wait_chain_counts` 只记有闭合见证的配对区间数，不把该次数变成 GIL 等待百分比。

若以后需要 Waiting/Ready 持续时间，必须用配对区间内的 ReadyThread 分割；没有 ReadyThread 不得把整个未运行区间当 Waiting。本工具当前报告调度驻留和调用链见证，不输出按来源拆分的等待秒数。CPU 采样中偶见等待链，也不能把它当等待占比。

只有低层等待 API、`take_gil` 和闭合的上层链同时出现，才支持该处 GIL 等待；仅 RestoreThread、普通系统等待函数、5 ms 周期或模块名不够。Qt/系统等待同样要看上层链。等待者栈不自动给出锁持有者、GIL 所有者或持有时间。不同 PID 不共享 CPython GIL，不得把 OBSBOT SDK 的栈合入 GUI GIL 统计。

**任何校准/身份/时间/丢失门槛失败，或目标调用链不完整，只报告证据质量和未决项，不作定量根因归因。** 不使用平均耗时、阈值调整或绘图/滤波候选替代缺失证据。

## 下一次现场的最小操作

现在无需任何人体操作。等正式单 USB Walk 人体负载能够复现积压时，才按以下顺序执行。原 NumPy、滤波、Processor、绘图候选和显示/相机/SDK 条件保持原样。

1. **负载开始前**重做原始冻结源与 50 个映像的校验；准备匹配符号缓存，确认磁盘空间、管理员权限及无其他用户 WPR/kernel recorder。使用现有 **WALK-ETW-OFF** 入口启动已冻结现场 harness；不要并开旧 schedule profile。按既有步骤确认全身、单 USB、有效骨架和 SDK 就绪。先保留未跟踪基线。
2. 读取本轮 `formal_started.json` 建立新鲜 PID/TID 清单；`prepare_targets.ps1` 校验三个 GUI TID，并从该 GUI 的直接子进程和实际加载的 `libdev.dll` / `obsbot_c_api.dll` 识别 SDK，列出其所有当前原生线程。SDK 新建线程仍会出现在原 ETL；录制后需核对生命周期，窗口中新出现但没有 CPU/cycles 起止快照的线程不参与定量比较。
3. 在可比较的实际负载下**分开**执行 CPU OFF/ON 和 wait OFF/ON 扰动校准，沿用 `plan.json` 的短窗/顺序/质量门槛，同时审查接触、pending、在途、延迟、骨架和 SDK 差异。输入不等价或门槛失败时停止定量分析，不能以本轮合成成功代替。不要为了校准引入第二 USB、固定回放、Run 或优化 A/B。
4. 只有确认接触样本消费不足、pending/在途积压后，分别记录一次 CPU 短窗和一次等待短窗；两窗不重叠，每窗默认 6 s，停止并复核后才开始下一窗。待积压已被接触样本消费完成窗覆盖即可，不为凑样本反复新增人体轮次。
5. 停止后保存原 ETL、record、targets、原始 queue_common/queue_samples、raw_frames、measurement/native_cpu 和相机/SDK 证据。先离线验收和分 PID 导出，再把 QPC 映射到既有 host_ns。对齐的是**消费批次与已消费接触样本的完成括号**，不是只取输入密集窗；pending=0 也可能有 popped/inflight。`queue_samples` 不能制造算法精确发布时间。批次内没有逐帧进度，不补造 Python 函数独占耗时。

管理员 PowerShell，在本实验 Windows 根执行（占位路径均换成本轮新目录，命令不会启动业务程序）：

```powershell
Set-Location E:/OptoJump/IronJump-native-stack-capture-20261017-01
.\prepare_targets.ps1 -FormalStarted '<本轮>/formal_started.json' -Output '<新目录>/targets.json'
# 分开选择 cpu 或 wait；每次新目录。off 用于对应实际负载的未跟踪账本窗口。
D:/conda/python.exe record.py cpu '<新目录>/cpu_window' --targets '<新目录>/targets.json' --seconds 6
# CPU 窗完全停止并验收、下一等待窗口条件满足后再执行：
D:/conda/python.exe record.py wait '<新目录>/wait_window' --targets '<新目录>/targets.json' --seconds 6
# 负载结束后离线验收：一次执行全扫描、时钟映射、分 PID 栈/账本检查。
D:/conda/python.exe split_field.py '<新目录>/cpu_window' '<新目录>/cpu_split'
D:/conda/python.exe split_field.py '<新目录>/wait_window' '<新目录>/wait_split'
```

查看两个输出根的 `acceptance.json` 以及各 PID 的 `quality.json`、`tracerpt_summary.txt`、`clock_mapping.json`。`measurement_acceptance_pass` 汇总测量门槛，`quantitative_field_attribution_ready` 仍固定为 false；`quality_pass` 只表示该进程的基础测量质量；还需独立扫描、实际负载扰动、SHA/PDB 和批次/接触对齐全部验收，才可能讨论有限的定量归因。多线程 SDK 中完全休眠且无栈的线程会保留“未验证”，不能虚报完整。

## 保存和复核

Windows 独立根：`E:/OptoJump/IronJump-native-stack-capture-20261017-01`。原 ETL、解码原载荷、每地址解析、tracerpt 全扫描和失败尝试都保留该处；Mac 对应 `runs/`、zip/exe/ETL 忽略 Git。`scan_manifest.json` 保存八份合成 ETL 的路径、大小、SHA 和派生物 SHA，`results02.json` 保存详细验收、见证调用链和每对原值变化。缓存 PDB 沿用只读的上一阶段目录，没有网络自动换符号。

```sh
python -m unittest discover -s experiments/native_stack_capture -p test_quality.py -v
python experiments/native_stack_capture/report.py <新的结果.json>
```

12 个跨平台工具测试覆盖截断链、RestoreThread 误判、分离内核段、多用户段歧义、未知地址、Qt/系统链、两 profile 隔离、时钟失配/宽括号/缺失证据和双边 host 映射；Mac 和 Windows 均通过；另有 3 个 Windows 原生句柄测试，覆盖 PID/TID 错配、GUI/SDK 同 PID 拒绝及 SDK 多线程分别观察。它们不是现场 Run 测试。结果复算拒绝覆盖；前一阶段源/工具 SHA 及清理状态见 `validation_manifest.json`（对应 `73e04cd`）；本轮交付见 `external_validation_manifest.json`。

公开实现依据：[Microsoft SystemProvider/WPR schema](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/systemprovider)、[TRACE_QUERY_INFO_CLASS](https://learn.microsoft.com/en-us/windows/win32/api/evntrace/ne-evntrace-trace_query_info_class)、[Microsoft TraceEvent 的采样间隔设置](https://github.com/microsoft/perfview/blob/main/src/TraceEvent/TraceEventSession.cs)、[KernelTraceEventParser 的事件载荷与 NonProcess 位定义](https://github.com/microsoft/perfview/blob/main/src/TraceEvent/Parsers/KernelTraceEventParser.cs)。源码文档用于校核结构；实际交付仍以上述 raw payload、独立 scan、PE/PDB 身份、时钟和 CPU/cycles 为验收依据。
