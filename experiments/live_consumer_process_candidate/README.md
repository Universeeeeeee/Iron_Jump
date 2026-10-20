# 真实 USB 消费者进程候选

实验子进程直接构造原 `SessionController()` 和默认 `UsbWorker`，保持正式质量、滤波、Processor、报告和原始数据。父进程通过有界命令/输出协议接收原信号。唯一性能差异是在子进程内将 `_GroundFrameInbox` 批量上限设为40。失败不自动重启；stop/discard必须等待reader、QThread、输出writer和子进程确认结束。

本阶段先验证协议和无设备/假worker生命周期；尚未运行人体、USB或正式程序，也未把保存输入候选称为现场修复。
