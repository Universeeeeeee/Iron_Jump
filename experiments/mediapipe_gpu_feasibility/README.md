# MediaPipe负载与Windows GPU可行性：证据边界

承接用户新增目标，使用既有固定工作结果、当前上下文四窗、正式源码及Windows只读环境信息；没有GPU委派创建、模型推理新测试、驱动/软件安装或正式改动。

## CPU负载已经支持到哪一步

既有`fixed_overlap_comparison`固定4对完整工作，仅改变原消费者与220次真实模型调用是否重叠；图像、逻辑时间和完整结果一致。串行条件的消费墙钟四对均较短，几何平均下降25.374%，达到当时预声明方向判据。串行使整体工作完成更晚，是诊断控制，不能直接成为正式方案。

这支持**视觉模型流水线并发是消费者变慢的一个贡献因素**，不等于“MediaPipe纯推理CPU占积压25.4%”。真实入口`_PreviewAdapter.infer_bgr`包含OpenCV缩放、BGR→RGB/复制、MediaPipe VIDEO推理和Python结果转换；尚未将它们的贡献分开，也未排除缓存、执行交付与同步等效应。旧OpenCV线程1候选失败仍失败，不重新提出为修复。

持续慢态还需要另一层解释：历史串行窗口自身也慢后转快；当前`slow_state_context`中，首次交互进程前3个消费段仍较慢，后3段已靠近下一快窗，而本进程正式220次推理此时尚未释放。因此“消费者当前与正式模型推理同时竞争”不足以解释全部持续慢态。模型已经初始化，仍不能排除初始化/原生空闲线程/背景活动或先前系统负载的影响。没有已认证的CPU/GIL份额。

## 当前Windows能否直接改GPU

Windows实际安装MediaPipe **0.10.35**，安装源码`BaseOptions`的文档原句为：

> GPU support is currently limited to Ubuntu platforms.

当前官方主干同文件仍有该说明；`sources01.json`保存官方来源和下载字节SHA，`installed01.json`保存实际安装版本、文件SHA和读取范围。正式`MediaPipePoseAdapter.open()`明确选择CPU委派。系统枚举显示GTX1650，但**枚举到GPU、存在Delegate.GPU枚举或参数转换成功，都不证明此Windows wheel实际交付GPU执行**。本次未尝试初始化GPU，不声称测得特定运行错误。

因此，现有Windows Python Tasks方案不能视作支持直接切换GPU。GPU推理在Windows是可研究的工程路线，例如另行验证支持Windows的ONNX Runtime CUDA/DirectML等后端，但本项目模型转换、算子兼容和实际交付尚未验证。`.task`包含的模型、人体检测/ROI裁剪、坐标还原、VIDEO跟踪状态、阈值及33点结果语义需要完整保留或重新验收，不能只换一个模型文件/枚举便视为等价。

即使真实交付GPU，缩放、颜色转换、数据传输、后处理、Qt回调和原消费链仍可能使用CPU；不能承诺它会消除当前慢→快状态波动。下一步先区分“并发流水线增量成本”和“初始化后无正式推理时已有的持续慢态”，再决定是否值得开展独立GPU迁移验证。当前不修改正式代码、不安装后端，不启动GPU优化A/B。

来源：[MediaPipe官方BaseOptions源码](https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/tasks/python/core/base_options.py)、[官方Python环境说明](https://ai.google.dev/edge/mediapipe/solutions/setup_python)。后者支持Windows桌面，并不等于支持Windows GPU。所取主干源码仅作当前文档证据，不冒充安装wheel的构建配置。
