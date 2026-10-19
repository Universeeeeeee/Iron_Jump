# 原版保存GUI的QLabel基类调用身份

承接 `92003cc`。本轮只回答“当前原版保存数据GUI中，谁调用了此前核验的QLabel公开paintEvent入口”。不安装GIL边界桥，不改正式程序、原NumPy、滤波、Processor、线程结构或原绘图候选；没有人体、物理相机/光栅、USB、Run、CPU/CSwitch/GIL栈采集或优化A/B。

## 一次原版保存负载与三个调用身份

复用已验证的session_local_baseline/gui、原SessionController/QThread/处理链/绘图、真实视觉模型与原CameraControlService协议。硬件输入为已保存数据，原生SDK明确替换为已验证的fake_sdk子进程；相机按钮禁用且panel._capture始终为None。任务使用与原GUI协议相同的交互会话、调度器参数和BelowNormal条件，不进行优先级/QoS干预。

新的GUI线程sys.setprofile观察只筛选：C调用、QLabel receiver、非空pixmap，以及独立核验的QtWidgets.pyd公开入口RVA0x1a8690。通过实际PyCFunction_GetFunction指针匹配，而不是仅按函数名猜测。前三次匹配完成后立即关闭；不安装其他线程的profile钩子。

每次记录实际receiver类型/Cpp指针、Python调用帧和文件SHA、父对象层级、父对象_preview是否就是receiver，以及像素图/控件尺寸与DPR。观察发生在原生调用之前，记录括号也不是原生绘制耗时或完整观察器开销。

plan02固定一个original窗口、3次观察、0重试。Windows原生交付测试还用4次合成render确认只记录前三次，随后钩子确实关闭。该测试是工具交付检查，不是性能或观察器扰动认证。

## 直接观察到的来源

目标GUI/测量PID20384，GUI TID764；模拟SDK独立PID17124。三条记录属于同一预览实例：

父对象路径为 `ExecutionView → … → EmbeddedCameraPanel → _AspectRatioContainer → AnnotationCanvas`。实际调用点为 `AnnotationCanvas.paintEvent:223 → super().paintEvent(event) → QLabel公开入口0x1a8690`。

两级_preview成员都在观察时直接与receiver按对象身份比较为同一对象。Python源文件SHA为 `ab573f096bc859ce2550821973abd508e1484e8bf90494b048c42dd8cc162df4`，与冻结原始文件匹配；QtWidgets.pyd仍为 `85cb6c2181b4b09887a7d8507dd950844d1b8f74a9c4002c7b71169f75bf6fda`。

因此，这三次有图像的基类调用在当前保存负载中可以直接命名为**相机预览AnnotationCanvas的基类绘制**，不再只是一个无实例的QLabel候选。这里不等于识别了旧现场ETL中的具体self，也不证明整个窗口只有这一种QLabel调用。

| 元数据 | 三次观察 |
|---|---|
| pixmap物理尺寸 / DPR | 784×441 / 1.0 |
| widget逻辑尺寸 / DPR | 784×441 / 1.25 |
| hasScaledContents | false |
| live pose | 前两次无，第三次有 |
| 相对原armed事件的观察时段 | 约0.083–0.086、0.118–0.121、0.231–0.237秒 |

这个DPR差异为下一步验证提供具体条件。不能只根据getter值宣布本次实际执行了多少缩放工作、损失多少CPU或GIL时间；本轮没有原生缩放栈或其耗时。hasScaledContents本来就是false，不能把“再关一次该开关”当作已验证修复。

## 这些身份记录不是积压归因点

重新读取同一原始帧流，保留原768束坐标，仅在分析掩码中排除原preflight坏束576。正式开始后首个非坏束有效位遮挡为sample53380，接收时间约在armed后4.557秒。三个身份记录都早于它，不是此前六个pending/20帧在途见证，也不是自然GIL所有权采样。

sys.setprofile及Qt/源文件身份读取会扰动GUI和启动帧选择。即使前三次之后钩子关闭，也不能把本轮延迟或吞吐追认为无观察器自然基线。performance_qualification、actual_load_disturbance_pass、field_historical_receiver_identified与root_cause_or_fix_complete保持false。

## 完整负载、退出和保全

唯一窗口完成33,188帧（含预检），原报告、完整quality/runtime状态与原始字段精确一致。真实模型与保存视频链路通过已有pipeline核验，未合并GUI和SDK的PID/GIL角色。原应用返回边界仍记录model cleanup未确认，额外尾部才确认最终关闭，没有改写前一状态。

GUI子进程Popen.wait确认退出码0；父控制器由保留句柄的Win32/.NET读数共同确认0。任务Ready/LastResult0且无本实验Python进程后，仅移除本次任务IronJump-label-call-identity01，5个锁全部保留。

44文件归档逐项核验，SHA为 `281ddbd1e8adcf25d38d700a0f2c109071a8d80c11f17d1e56b093a70e72a59a`。完整输入/输出及原始传感器文件只留本地runs和Windows忽略目录，不推送它们。调用身份、派生校验和哈希可推送。458个正式文件、冻结依赖、输入和原NumPy的检查通过。

准备阶段在执行前发现派生entry里用了未定义read helper，另一次冻结脚本错误引用了旧工具不存在的plan02；两者都发生在Windows负载启动之前。旧plan01未覆盖，匹配其全部原始SHA的准备源码在本地恢复保留；实际唯一窗口使用新plan02及显式json.loads。失败准备记录与前后diff保留，没有重跑窗口替换失败证据。

当前剩余工作是针对已观察到的真实AnnotationCanvas调用域验证实验桥的完整控件语义，再决定是否具备实际负载因果对照条件；不能以本次身份观察替代主要根因或性能收益。旧CPU/CSwitch、3%/1%失败及所有历史窗口不变，当前无需真人测试。
