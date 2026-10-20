# 真实 USB 消费者进程候选

实验子进程直接构造原 `SessionController()` 和默认 `UsbWorker`，保持正式质量、滤波、Processor、报告和原始数据。父进程通过有界命令/输出协议接收原信号。唯一性能差异是在子进程内将 `_GroundFrameInbox` 批量上限设为 40。失败不自动重启；stop/discard 必须等待 reader、QThread、输出 writer 和子进程确认结束。

真实 USB 空场 readiness/discard 已通过；完整保存 Walk 的原始帧、事件、步态汇总和清理也已通过。`START_STEADY_WALK.cmd` 用于一次稳定通电状态下的单 USB Walk 验收，包含真实相机、骨架、SDK、GUI paint、FIFO 和报告一致性证据。冷启动性能和更多设备重启不属于验收范围。
