# GUI 适用性审查：启动会话与优先级不同，尚不能外推 QoS 收益

`06444b6` 的四对固定工作显示消费墙钟下降 18.11%，但原生吞吐联合门槛失败。本阶段不重跑性能窗口、不部署候选，只审查它与既有 GUI 回放的运行环境是否相同。

## 已核验的差异

同一份 `read_context.py` 分别通过 SSH 和原 GUI 使用的交互式、Highest 权限计划任务方式启动。程序不创建窗口、不加载 IronJump/模型/SDK，只读取本进程与本线程状态，输出哈希一致。

| 观测 | SSH 启动 | 交互式计划任务启动 |
|---|---|---|
| Session ID | 0 | 1 |
| Process priority class | 32，Normal | 16384，BelowNormal |
| QT_QPA_PLATFORM | offscreen | windows |
| 进程 QoS ControlMask / StateMask | 0 / 0 | 0 / 0 |
| 主线程 QoS ControlMask / StateMask | 0 / 0 | 0 / 0 |
| 前台窗口 PID | 无 | 有其他前台进程 |

窗口后端是本次按原启动脚本设置的环境变量，未实际创建 Qt 窗口，不能用它证明 GUI 行为。前台 PID 只描述查询时刻，也不是旧 GUI 前后台记录。

只读构造 `New-ScheduledTaskSettingsSet` 得到默认任务 Priority=7。原 `gil_boundary_ab/start01.ps1` 没有指定 `-Priority`，`launch01.ps1` 的 Start-Process 与 cohort 的 Popen 也没有显式设置优先级。新任务按同样默认设置启动出的 Python 实际报告 BelowNormal，这比只检查配置更直接地支持**启动环境不同**。原 `process_qos_candidate` 则从 SSH 启动。`RunLevel Highest` 是权限等级，不代表高 CPU 调度优先级。

**限制：历史 GUI 目标的实际优先级没有被采到，真实桌面人工入口也没有被采到。** 本次是匹配启动方式的短命探测，不把当前读数倒填给历史目标；动态 GUI/视觉线程策略可能在后续改变。调度优先级与执行速度 QoS 是两个不同维度，不能因为读到 BelowNormal 就宣布已找到根因。

## 对下一步的约束

目前无法把 SSH 固定任务的 18.11% 改善直接转换成 GUI 或现场收益，也不能把原联合门槛失败改写为通过。之前的 GUI A/B 两组共用同一启动方式，当前发现不会自动否定其内部比较；但其结论对真实桌面入口的适用范围需要保留。

下一份 GUI 协议应明确记录和固定：实际 target 的 Session ID、进程优先级、进程/消费/模型线程 QoS、窗口前后台状态，以及原始输入投递、pending 与 contact→paint。不能同时更改优先级和 QoS，也不能静默把旧回放的 BelowNormal 改成 Normal，再把变化归给 QoS。真实桌面入口状态须另有证据，不能假定等于 SSH 或计划任务。

先解决这个可比性边界，再决定一个单变量协议。当前没有新 GUI/人体/USB/Run 性能测试、全局策略更改或正式程序修改；全部旧窗口与失败判定保留。

## 执行保全

两份输出均独占创建；查询源 SHA256 相同、所有 QoS API 成功返回。交互任务原始状态 Ready、LastTaskResult=0，输出已读取后才删除本次拥有的已完成计划任务。删除任务不删除证据。`task01.json` 保存终态，`review01.json` 保存原启动链源码及新证据哈希。没有重启原性能队列。
