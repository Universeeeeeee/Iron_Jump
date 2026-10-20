# 视频解码与 MediaPipe 共同子进程：保存输入交付门

承接真实1000Hz复核 `247a001`。本阶段只使用已保存Walk视频和既有严重原版GUI窗口的实际动态选择序列，不打开相机、SDK、USB、GUI或人体，不评价性能收益。

候选边界为：子进程拥有MJPEG/CSV读取、JPEG解码、原`_PreviewAdapter`缩放/RGB转换/MediaPipe推理及模型关闭；父进程只接收有界、带序号的预览帧身份和pose结果。它不同于已停止的“只迁移模型、父进程预先传图像”候选。

先从既有 `session_gui_comparison/aa01` 保留证据提取实际视频提交ID及417个真实推理的frame ID、sample time、timestamp_ms和调用顺序。提取只读同一归档，保存源文件SHA。随后两臂分别执行同进程参考和视频+模型子进程；必须核对：

- 源MJPEG/CSV哈希、offset/length连续、实际解码帧ID和像素SHA；
- 全部预览选择序号，全部推理frame/timestamp严格一致；
- 完整`FootPoseSample`规范哈希逐次一致，None/error位置一致；
- 子PID/TID真实不同，模型调用被父RPC边界包围，所有包序号/背压/错误传播闭合；
- 模型close、子进程、Pipe/reader/writer均确认退出，失败不自动杀死或重试。

保存输入交付通过不表示实际相机录像或GUI/SDK工作已等价，也不是1000Hz修复。下一阶段才可把相同协议接入实验GUI的相机代理，并再次验证实际视频、tracking决策、队列和报告。正式程序、原NumPy/滤波/Processor/绘图均不修改。
