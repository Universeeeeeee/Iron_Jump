# 相同Qt基类调用的有效绘制、异常及生命周期控制

承接 `9cdae18`。旧ETL显示QLabel基类绘制进入Qt缩放/latch同步，上一轮只在无效绘制警告内验证过包装调用的GIL契约。本阶段不比较速度，只在独立合成进程准备一个改变GIL调用边界的实验桥，并验证有限域内的行为一致性。没有修改正式程序、原NumPy、滤波、Processor、线程结构或已有绘图候选。

## 调用桥保留哪些语义

不能直接采用上一轮的裸ctypes负控制：原包装入口还建立PythonContextMarker，并在原生调用前后检查Shiboken保存的Python异常。

本轮bridge.py只用于合成控件，使用同SHA、同导出的QLabel::paintEvent，保持GUI线程以及self/event强引用。非法参数或已删除对象仍交原绑定处理；有效参数的桥执行：

1. 建立与原受保护入口一致的同步PythonContextMarker。
2. 先检查Shiboken错误状态，再通过CDLL调用同一Qt原生方法；CDLL负责这次调用边界的GIL释放/重新获取。
3. 使用原Sbk_ReturnFromPython_None完成异常检查；显式消耗新引用，避免ctypes的PyObject返回转换多留引用。
4. finally中销毁marker，恢复调用上下文。

没有给原Qt/Python类型打补丁。Marker构造/析构只操作TLS、不访问this对象存储的事实来自精确PE字节，目标进程又核对了实际函数机器码。GilState构造的独立反汇编显示其使用PyGILState_Ensure；不能凭上下文名字假定回调会自动持有GIL。

另一个允许释放GIL的Qt包装范围有setBlocking操作；这里保留原QLabel受保护入口的同步上下文策略，没有同时改变该策略。实际回调异常传播是门禁，不能只凭这项静态判断通过。

该实现依赖固定Shiboken ABI，仅为受控实验准备，不是可直接部署的通用绘图替代方案。

## 唯一一次固定正确性进程

Windows独立目录为 `E:/OptoJump/IronJump-qt-label-valid-paint-20261020-01`。plan01在运行前绑定8份源码/证据和6个已有库/扩展SHA，固定1个离屏进程、0次重试、6组输入。只使用程序生成的53×37像素图案，没有实际照片、视频、光栅、Walk、SDK、模型、人体、USB、Run、CPU采样或性能A/B。

每组比较三种实际输出：无Python paintEvent覆盖的原生QLabel参考、调用原绑定的合成子类、调用实验桥的同类子类。比较的是QWidget.render实际写入的完整ARGB字节，不是QLabel.pixmap属性或一个成功返回值。

| 合成输入 | 目标逻辑尺寸 | 源/目标DPR | 完整像素 |
|---|---|---|---|
| 两个不同不透明图案 | 233×151 | 1 / 1 | 三种输出逐字节相同；两个图案输出不同 |
| 透明度图案 | 257×173 | 1 / 1.25 | 相同 |
| 源/目标小数DPR | 311×211 | 1.5 / 1.5 | 相同 |
| 双倍DPR | 337×219 | 2 / 2 | 相同 |
| 不启用scaledContents | 239×157 | 1 / 1 | 相同 |

一个进程内的6组图像不是6次独立性能实验，也不提供统计精度或扰动资格。所有输出均改变了预填充哨兵，避免空绘制被误判一致。18份完整像素已保留，review.py重新从ZIP读取，检查尺寸、stride、字节数、完整SHA及三份实际字节相等。

## 异常、引用及生命周期结果

- 错误receiver、错误event、已删除receiver、已删除event共4组，桥与原绑定的异常类型和原文相同。
- QProxyStyle::drawItemPixmap实际回调注入同一个异常实例。两种基类调用各触发1次，均在合成paintEvent的基类调用位置捕获原实例；没有转移到外层render或stderr。取消注入后的完整恢复图像与新的原生参考相同。
- 合成回调都在GUI线程，event在调用前后有效且ownership不变；render之后的event有效性与原绑定相同。删除后label和父属style均确认无效。
- 16次None返回帮助函数的独立引用检查为5404→5404。这是有限的引用平衡检查，不是长时间内存泄漏或任意对象生命周期证明。
- 无意外Qt消息，原消息处理器恢复，目标stderr为空。目标PID10340由保留句柄的Win32与.NET读数共同确认退出码0，之后无该PID。两个锁保留。

6组主像素三联文件可独立复核。异常后的额外恢复图像仅在运行时比较完整字节，未另存这些图像；该部分证据以冻结脚本及当时记录为限。

3项故障门禁在Mac和Windows通过，覆盖像素/生命周期不一致、异常被移至stderr或未真正触发，以及正确性通过不能变成性能/现场通过。完整37文件归档及两个锁目录逐项核验，ZIP SHA为 `b844411b6049c182f7afe441669517520585c772ca09fe0df0ca0ad7cdc75ee5`；合成像素和归档仅存本地runs及Windows，不推送这些二进制。

## 对根因目标的影响

有限合成域的correctness_control_pass=true。现在具备一个经过像素、异常和生命周期检查的调用边界实验原型，后续不必依赖未经验证的裸原生调用来做反事实准备。

**尚未测实际GUI积压收益，未证明主因或正式修复。** 这不是实际AnnotationCanvas/骨架覆盖、完整保存Walk与模型/报告生命周期验证；也未覆盖任意多重继承、更新后的wheel或真实控件的所有回调。有效缩放内部的连续GIL所有权没有在本轮采集，不能把CDLL调用约定换成历史现场的owner时间占比。

原脚印/相机绘图代码和正式处理链没有变化。旧CPU/CSwitch、3%等效/1%精度失败，以及上一轮原Qt控制的未知退出码和所有故障锁均保持原状。performance_benefit_proven、actual_load_disturbance_pass、field_attribution_ready及root_cause_or_fix_complete仍为false。

后续若验证实际控件或保存负载，须另行冻结范围和有限预算，保留原绘制/模型语义及严重积压基线要求，不因当前像素一致就启动优化或宣布修复。当前无需真人测试。
