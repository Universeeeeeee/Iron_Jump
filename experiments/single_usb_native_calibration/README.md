# 无人 WPR OFF/ON 校准

由用户明确授权的无人设备阶段。12 轮全部完成，6 对通过本目录 `plan.json` 启动前冻结的门槛；见 `results.json`、`pairs.csv`。只覆盖无人空场、单真实 USB、原生录像/预览、SDK 开启；12 轮有效骨架绘制为零，不外推有人密集负载，不是算法或绘图 A/B。

运行代码与冻结源保持一致。`field_runner.py` 是现场 revision 2 的逐字节副本；`calibration_runner.py` 明确旁路人体确认、20 s 自动停止，仅在起止读取 GetThreadTimes 与 FILETIME/perf 时钟。每轮独立进程，唯一 WPR 实例，不取消别人的记录。首次准备和关闭第三方 native 进程方式与现场实验一致。

复核：`analyze_offline.py` 使用冻结的 host 3–19 s 计算消费/年龄，预览实际计数和 native CSV 另算；消费者原生 CPU 是约完整 20 s 范围。六份 ETL 全扫描确有 CSwitch/ReadyThread，header EventsLost/BuffersLost 都为零。`validate_traces.py` 对 header 的 XML 导出只取首个完整事件、随后停止离线导出器；完整事件数量/丢失来自独立 `tracerpt -o NUL -summary`，原 ETL 完整保留。当前未解释 CSwitch v5 二进制载荷，不能输出可信 Running/Ready/Waiting 或 GIL/GC 根因。XML 显示 +07:59，与系统 +08:00 不一致；后续必须用原始 header FILETIME 和已保存的 perf/FILETIME 括号独立校验时间对齐，不能直接相信显示时区。

首对 CPU ON/OFF≈0.589，属状态波动证据，不能当作跟踪提速。冻结 CPU 条件仅限制 ON 增量；“全部门槛通过”不等于严格对称统计等价、没有任何扰动或有吞吐余量。

大文件保留 Windows `E:/OptoJump/IronJump-single-usb-field-20261016/experiments/single_usb_native_calibration`，由 `windows_evidence_manifest.json` 记录；Mac 的 `probe.xml` 是早期取回中断的非完整副本，始终排除 Git 与完整 XML 声明。微软 PerfView 源参考也不加入 Git。现场总结见 `../single_usb_field/RESULTS.md`。不移植或合并正式代码。
