# 原生 CPU / 等待栈诊断：离线符号准备

2026-10-17。基于 `19acc2f`，分支 `codex/native-stack-symbol-preflight`。本轮只完成用户约定的第一步：核对二进制、准备匹配符号、验证名字/地址解析及归因边界。

**Python GIL、普通 Python 锁、Qt 同步和 Windows 等待函数的符号基础已验证；NumPy、MediaPipe、OpenCV 内部计算函数的覆盖仍不足。不能宣布“所有内核可辨认”，更不能宣布已具备现场定量归因结果。**

没有启动正式 GUI、现场相机、SDK 控制服务、USB、WPR/ETW 跟踪、CPU 采样或等待栈录制；没有 Run 测试、平均耗时复测或优化 A/B。只在独立 Python 进程导入 NumPy/Qt 库以枚举依赖，没有构造 Q(Core)Application 或设备对象。正式程序、原 NumPy、阈值和 beam_layer 候选均未改变，也未安装/替换任何运行库。

## 已交付的符号能力

现场环境为 Windows x64、Anaconda Python 3.11.5 `he1021f5_0`、PySide6/Qt/shiboken6 6.11.1、NumPy 2.4.6。

|范围|核验结果|可以支持的后续辨认|保留限制|
|---|---|---|---|
|`python311.dll`|本地 PDB GUID `0E3943E6-7A68-4C05-BF0A-BAD24BF14D1E`、DBI age 2 匹配|`take_gil`、`drop_gil`、`PyEval_RestoreThread`、`PyThread_acquire_lock_timed`、解释器执行函数均可解析|尚未验证真实 ETW 栈能完整展开至这些函数；看到 RestoreThread 单帧不能自动认定 GIL 等待|
|`Qt6Core/Gui/Widgets.dll`|从官方 Qt 6.11.1 qtbase 符号包提取，三个 PDB GUID/age 均与实际 DLL 精确匹配|QtCore 的 `QWaitCondition::wait`、QMutex 相关函数与 Qt 执行路径可区分，保留源码行|PySide/Shiboken 包装层缺少匹配的内部符号，不能保证所有跨语言边界都有完整名字|
|`ntdll`、`KERNELBASE`|从 Microsoft 符号服务器按实际 RSDS key 取得，独立 DBI 身份与 DbgHelp 一致|`NtWaitForSingleObject`、`WaitForSingleObjectEx`、条件变量等系统等待函数可解析|系统等待 API 本身不能区分 GIL、Qt 或其他锁，必须看上层调用链|
|USB `CyUsbInterface.dll`|找到开发目录中的精确匹配 PDB，另存隔离缓存|可解析 `CCyUSBEndPoint::XferData`、`WaitForXfer` 等 native 地址|部分来自公共符号而无源码行；不代表内核 USB 驱动内部符号也已齐全|
|OBSBOT `libdev.dll`|仓库 SDK release PDB 与现场 DLL 精确匹配|SDK 原生函数、同步/通信相关地址可解析|它在独立控制子进程中，不能并入 GUI 进程的 GIL 所有权分析|
|`_multiarray_umath…pyd`|只有初始化导出、无 RSDS/COFF 函数表，未找到可验证的内部符号|保留精确二进制 SHA、模块 + RVA 和展开元数据|不能给实际数组内核命名，更不能把模块内驻留一概叫算法独占计算|
|`libmediapipe.dll`、`cv2.pyd`|有 RSDS 身份，但检查范围内无匹配 PDB；实际 DbgHelp 仅导出回退|模块 + RVA；MediaPipe 的部分 C API 导出边界|内部模型/XNNPACK/OpenCV 内核保持 unknown，不能用别的构建的 PDB 或重编译库代替|
|`tinyse_capture_v2.dll`、PySide 包装器|只获得导出级覆盖|API 边界与模块级位置|内部函数和内联边界仍不完整|

关键地址不仅执行了名字查询，还进行了 **符号起点→地址→名字** 的零偏移回读；有函数大小的私有函数还测试了地址 `+16` 的内部回读。例如 `take_gil` 对应 `Python/ceval_gil.h:214`，普通锁对应 `Python/thread_nt.h:309`；Qt 的多个 `QWaitCondition::wait` 对应 `qwaitcondition_win.cpp`。这些是静态符号解析验证，没有制造或测量任何实际等待。

`resolve_ready01.json` 是严格 PDB 模式；`resolve_exports01.json` 单独允许导出回退。没有使用 `SYMOPT_LOAD_ANYTHING`，没有把 `SymExport` 记为完整 PDB 成功。`readiness02.json` 只将正确模块 `.text` 中、名字/地址回读成立的函数列为可辨认位置，剔除了导入指针、RTTI/字符串等数据符号；所有成功 PDB 同时要求 DLL RSDS、独立 PDB GUID/DBI age、DbgHelp PdbSig70/PdbAge 一致且 PdbUnmatched=false。

## 避免符号测量层的假闭环

微软公共 PDB 的 **Info stream age 可因重写而高于用于匹配的 DBI age**。本次 kernel32/kernelbase、ntdll、ucrtbase 的 Info age 分别为 2/2、4、3，而 PE 与 DBI age 均为 1。最初只读 Info age 的检查会错误拒绝这些文件；本轮改为独立读取 DBI 头，并与 DbgHelp 的 PdbAge 交叉验证，未修改下载的 PDB 或 DLL。

四个测试覆盖 Info/DBI age 不同、相同 GUID 但 DBI age 错误、相同 age 但 GUID 错误、非 PDB 文件拒绝。文件名、版本号、下载成功、调试器“已加载”中的任一单项都不作为匹配结论。[Microsoft 的模块信息定义](https://learn.microsoft.com/en-us/windows/win32/api/dbghelp/ns-dbghelp-imagehlp_modulew64)明确区分 PDB 类型、DBI age、未匹配标志与行号能力。

## 现场模块拓扑的独立核对

读取已有两轮原始 ETL 的 Image_Load v3 与 Process v4 rundown，不录制新事件。Image v3 使用 Microsoft TraceEvent 对 >=v2 的稳定前缀：64 位 image base/size、payload PID、checksum、时间戳、56 字节起的 Unicode 路径；保留原始载荷供复核。进程 PID/parent 来自 payload，而非可能无效的 header PID。未知事件形状不强行套结构。

|轮次|GUI PID|SDK 控制子进程 PID|实际加载 SDK DLL 的进程|
|---|---:|---:|---|
|Walk ON2|13992|5548|5548：`obsbot_c_api.dll`、`libdev.dll`|
|Walk ON3|12344|20032|20032：同上|

进程开始/结束 rundown 的父子关系一致，也与 `camera/control_service.py` 的 QProcess 架构相符。GUI 内另有 `libmediapipe.dll`、`cv2.pyd` 与 `tinyse_capture_v2.dll`。因此未来不仅要准备 GUI 的 Python/Qt/NumPy，也必须保留模型、相机本地层和 SDK 子进程的模块图；**不同进程不共享同一个 CPython GIL**。这项拓扑事实不证明 SDK 对 CPU、I/O 或 GUI 通信没有间接影响。

两轮各有 96 条选定模块/SDK 载荷记录与当前磁盘文件的路径、image size、checksum 相容。**这些 v3 rundown 的 TimeDateStamp 实际为 0，不能作匹配时间戳，也没有历史 DLL SHA。** 因此仅声称兼容，不声称已证明历史模块逐字节相同。本轮冻结当前 50 个映像 SHA，未来录制前必须重新核对；原 ETL SHA 与已有校验记录一致。

Python、Qt、NumPy、MediaPipe、OpenCV 等均有结构有效、按起点排序的 x64 `.pdata` 展开表。这只能证明元数据存在，不能替代真实记录中用户/内核栈完整率、截断率和跨模块展开的验证。

来源：[Microsoft Image_Load 文档](https://learn.microsoft.com/en-us/windows/win32/etw/image-load)、[Microsoft TraceEvent 的 ImageLoadTraceData / ProcessTraceData 实现](https://github.com/microsoft/perfview/blob/main/src/TraceEvent/Parsers/KernelTraceEventParser.cs)。原始载荷及 reader 源码、二进制 SHA 均保存。

## 现场录制前的门槛：本轮没有执行第二步

1. **身份与栈可读性**：重新核验应用/子进程 PID、线程生命周期、实际加载文件 SHA 和 PDB GUID/DBI age。确认实际栈能展开到 take_gil / Qt 同步 / 系统等待调用链。CPython 3.11 原生栈不会自动列出 `_GroundFrameInbox._consume` 这样的 Python 函数；必须与既有批次状态证据对齐。
2. **扰动校准单独进行**：低频 CPU 执行栈与必要的 CSwitch 等待栈分别校准；不因为称为“低频”便视为低扰动。冻结采样设置、输入拓扑、相机/骨架实际负载和原队列/脚印指标，校准失败则不作定量归因。改变栈开关、采样间隔或缓冲配置应重新校准。
3. **复现后才录制短窗**：正式单 USB 输入、原 NumPy、原显示条件不变；确认实际接触样本消费不足和 pending/在途状态后，在预定窗口分别记录执行与等待栈。本轮不增加现场数据，不开展 Run，也不把固定回放加第二 USB 的结果当正式单输入。
4. **先交付证据质量，再解释原因**：核对有效采样间隔、丢事件、符号覆盖/未知帧/截断率、TID/PID、QPC 同步以及 CPU/cycles 与调度驻留差额。对齐滤波后接触样本完成括号，不能只按输入密集窗汇总。CPU 采样、Ready、Waiting 和调用栈含义分别保留。
5. **限制结论**：完整等待链中出现 take_gil 才能支持该处 GIL 等待；不能由 generic WaitForSingleObject、仅 RestoreThread、5 ms 间隔或某个模块名推出 GIL。等待者栈不自动提供锁持有者身份，也不能由其直接计算 GIL 所有权。NumPy/MediaPipe/OpenCV 内部未知帧继续报告为模块+RVA，不用平均耗时、阈值调整或无符号函数猜测补齐。

目前可以准备针对 **GIL / Qt / 系统同步来源** 的后续校准；尚不能承诺逐 NumPy/模型内核的函数级归因。若需要后者，仍须取得该精确二进制对应的发布方符号或可验证链接映射；本轮没有替换或重编译现场库。

## 保存、复核及未通过尝试

独立 Windows 根：`E:/OptoJump/IronJump-native-symbol-preflight-20261017-01`。

- 可用符号缓存：`symbols/`、`symbols/vendor/`。可供未来诊断进程单独设置符号搜索路径；没有修改系统全局环境或运行库目录。
- Python/USB PDB 从现有文件复制并核验 SHA；SDK PDB 来自现有 release 包；系统 PDB 按真实 RSDS key 下载；Qt PDB 来自[官方 Qt 6.11.1 MSVC2022 qtbase 调试符号包目录](https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6111/qt6_6111_msvc2022_64/qt.qt6.6111.debug_info.win64_msvc2022_64/)。Qt 压缩包核对发布的 SHA1，解出的每个 PDB再核对实际 GUID/DBI age 和 SHA256。PDB 身份和缓存校验均不依赖仅相同的版本号。[Python 符号说明](https://learn.microsoft.com/en-us/visualstudio/python/debugging-symbols-for-mixed-mode-c-cpp-python?view=visualstudio)也要求匹配解释器构建。
- 接受结果：`readiness02.json`、`resolve_ready01.json`、`resolve_exports01.json`、`inventory_compact01.json`、两份 `*_images03.json`、`downloaded_identity01.json`、`downloads01.json`、`verification01.json`、`validation_manifest.json`。
- 完整原始 inventory（包含导出表）在 Windows 根及本地忽略目录对应文件保留；compact 保存其 SHA 和远端路径。PDB/压缩包不进入 Git，Windows 与本地缓存均保留。阶段目录均新建，原始采集和前轮结果没有覆盖。
- 最终接受的 ETL reader 为 `ReadImages_v4.exe`，对应本目录 `ReadImages.cs`。早期路径/编译失败、只允许 Image v2 导致的零结果、初始 Info-age 误判均保留且不用于归因；零解码没有被解释为“现场没有加载模块”。初始全前缀目录枚举超时未用于断言 PDB 不存在，接受结果使用有界搜索、实际 PE 身份和实际符号解析。

离线复核只调用 `OpenTrace/ProcessTrace` 消费现有 ETL、读取 PE/PDB 元数据以及 DbgHelp 名字/地址解析；不调用启用跟踪的 API。`SymInitialize(..., invade=false)` 不附加到现场进程，`SymLoadModuleEx` 读取映像/符号，不执行目标 SDK/相机 DLL 的初始化。最终 50 个运行映像和 458 个冻结程序源文件再次核验未改变。

```sh
python -m unittest discover -s experiments/native_stack_symbol_preflight -p test_symbols.py -v
python experiments/native_stack_symbol_preflight/readiness.py <new-readiness.json>
```

`readiness.py` 使用已提交的 compact inventory 与原始 resolver 输出，拒绝覆盖结果。部署脚本也拒绝重用已有根；不要为复核重新部署、安装软件或启动任何现场入口。
