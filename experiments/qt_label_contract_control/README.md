# QLabel包装调用的原生GIL契约控制

承接 `3757739`。此前旧等待轮已观察到QLabel基类绘制→Qt图像缩放→latch等待，并与消费者take_gil配对；精确公开包装入口没有显式SaveThread。本轮只检查这类包装调用是否实际能把GIL带入Qt原生代码，未做性能或修复A/B。

## 固定的一次合成控制

plan01在运行前绑定源码、已编译MessageOracle.dll及现场相同SHA的Python/Qt/PySide/Shiboken。只启动一个离屏Qt进程，创建一个最小QLabel和两个QPaintEvent，固定两次调用，不重试：

1. 通过原QLabel.paintEvent公开包装入口调用基类。
2. 在同一GUI线程、同一对象上，通过释放GIL的ctypes.CDLL调用相同Qt6Widgets原生导出，作为负控制。

两次都故意在有效paint事件之外调用，产生原生Qt无效绘制警告。它们不是合法图像渲染/缩放实验，不运行实际GUI负载、原程序、保存Walk、模型、SDK、设备、USB、Run或优化候选。

原生C消息处理器不使用ctypes的Python回调，不先获取GIL，也不读取Qt对象。它直接调用PyGILState_Check，记录本线程TID、phase、警告类型和QPC。32条固定容量，溢出/异常/错误线程/时刻/处理器未恢复都拒绝。恢复原消息处理器之后才复制数据。

## 实际契约数据

目标PID20216、GUI TID18412，两个阶段均收到5条原生警告，全部位于各自调用边界内、来自该GUI线程，类型均为QtWarningMsg。

| 调用方式 | 原生回调中的GIL检查 |
|---|---|
| 原PySide包装入口 | 1、1、1、1、1 |
| 显式释放GIL的原生负控制 | 0、0、0、0、0 |

这独立验证检测器不是恒定返回“持有”，也不是因为进入Python回调才临时获取GIL。**原包装调用内的这些原生位置实际观察到了GIL持有**，补强了此前仅由包装机器码得到的调用机制约束。

只能按这些回调位置陈述，不能宣称整个paint调用连续持有GIL，更不能把无效绘制警告位置冒充真实QImageScale/QLatch内部位置。具体现场控件、所有权时间贡献、实际缩放像素/结果、异常与对象生命周期等价性均未验证。负控制不是可直接采用的正式绘图替代方案。

## 整体执行验收仍未通过，原窗口不重跑

原始result01的passed=true只表示API契约检查通过。启动器的保留进程对象等待已确认目标退出，随后独立CIM检查也无该PID；原Qt消息处理器已恢复，但启动器记录的子进程ExitCode为null。

review01因此明确保持：

- contract_data_pass=true；
- original_exit_code_observed=false；
- overall_control_execution_acceptance_pass=false。

没有由“文件写完”“API契约成立”或“进程已退出”补造退出码0，没有第二次Qt控制。active.lock、launch.lock和原退出码缺失窗口全部保留。

launch02改用直接启动的Process对象，在等待之前保留句柄，结束后通过Win32 GetExitCodeProcess并与.NET读数交叉核验。独立的ExitProcess(7)控制中，两者均读到7，进程实际退出。这个修正仅为后续准备，不追认原窗口退出码，也不重新运行原计划。该启动器在旧锁/旧结果存在时拒绝启动；任何后续Qt控制仍须新的冻结计划和独立目录。

另一次较早的cmd exit7支持控制实际返回1、stderr为“The directory or file cannot be created.”；原始状态与日志保留，仍为失败，原因未由本控制确定。后续改用直接Win32 ExitProcess的目标，不复用cmd层来验证退出码。

## 预检、失败和保全

MSVC /W4 /WX构建成功，3项mock/故障测试在Mac及Windows通过：拒绝恒定持有/恒定不持有的检测数据，拒绝错误线程/时间/消息类型/未恢复处理器，并确保合成通过不升级为现场根因。

首次Windows unittest日志转发受PowerShell ErrorActionPreference影响，stderr进度被视为NativeCommandError，原日志为空，保留为未确认；只在新tests02.log中重新执行了mock测试，没有启动Qt控制或替换采集。原Qt控制始终只有一次。

首次SCP拿到Windows反斜杠归档路径而失败；改正传输路径后读取同一现有ZIP，未重建归档、未重跑目标。32个manifest文件和两个锁目录逐项核验，归档SHA为 `58341aae626be27e33deb06bbc9140928925e4f9ae4604012ee6154d021a5d4b`。完整二进制/归档仅留本地runs及独立Windows目录 `E:/OptoJump/IronJump-qt-label-contract-20261020-01`。

post01确认冻结源码、原Python/Qt/PySide/Shiboken和oracle均未变化。未修改正式绘图、原NumPy、处理链、线程结构或系统电源/优先级。旧CPU/CSwitch及实际负载3%/1%失败、全部历史窗口和计划不变。

下一步的核心缺口仍是实际有效绘制/缩放路径的同窗所有权与效应，而不是继续验证同一包装入口或追加警告控制。现有证据不支持正式修复或主导贡献结论；当前无需真人测试，完整根因目标仍未完成。
