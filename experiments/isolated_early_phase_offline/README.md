# 隔离消费者早期输入离线分块

只读取已完成隔离窗口的 raw/report/state，在原滤波、WalkingProcessor和会话链中按1000样本分块执行三次。每次核对完整event audit、timeline和raw archive SHA。DeviceQualitySession、GUI、IPC、模型和设备不在本计时范围；结果只判断当前输入前后阶段的相对复杂度，不能替代现场服务率或CPU/GIL份额。
