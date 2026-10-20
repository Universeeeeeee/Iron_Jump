# 视频解码与 MediaPipe 子进程：保存输入 GUI 语义门

承接 `vision_video_process_delivery/plan05`。本阶段把已通过的 822 个预览帧和 417 次完整 pose 序列接入原实验 ExecutionView、AnnotationCanvas、测量子进程和 SDK tracking 协议。子进程拥有保存 MJPEG 读取、JPEG 解码、原 `_PreviewAdapter` 与模型关闭；GUI 仅接收单槽共享内存预览和普通字典 pose。

唯一窗口使用保存 Walk 光栅与视频、模拟原生硬件 SDK 后端。它不打开相机、USB 或人体测试，不修改正式程序、NumPy、滤波、Processor、绘图、优先级或电源设置。每个预览像素身份和 pose 哈希必须逐条匹配 `plan05` oracle；同时要求原脚印发布全部绘制、骨架实际绘制、SDK tracking 决策、原始报告、quality/runtime 状态和 raw 字段一致，并确认四个 PID、模型关闭、子进程退出与共享内存释放。

这是语义交付门。固定选择序列不等同于实时 latest-only 调度，模拟 SDK 不等同于现场硬件，相机录像链尚未合格，也不产生性能或积压修复结论。通过后才能冻结带真实时序的原版/进程版 A/A 与 AB/BA；必须重新满足严重原版积压、输入质量、FIFO、contact-to-paint 和完整报告门槛，不能用快态或追加窗口代替。

`plan01` 在负载前因测试进程缺少仓库根导入路径失败并保留。`plan02` 的唯一 GUI 窗口本身退出 0，随后旧 verifier 因模拟 SDK 成功结果没有可选 `error` 字段而失败。完整窗口由 collector 封存；`plan03` 只读复核该不可变窗口，不重跑 GUI。

`plan03` 复核通过：822 个预览像素身份、417 个 pose 哈希、816 次有效骨架绘制、9 个 active publication、879 次 SDK tracking 决策、718 次非零速度、四个独立 PID，以及原报告/quality/raw 和全部清理门成立。结论只支持保存输入语义可行性；固定选择序列没有实时 latest-only 时序资格，模拟 SDK 与无相机录像也没有现场资格。下一步只能冻结带时序的原版/进程版 A/A 与 AB/BA，不能直接合入正式程序。
