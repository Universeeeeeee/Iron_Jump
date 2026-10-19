# 定位到QLabel基类绘制桥与Qt缩放latch同步路径

承接 `b46dfac`，本轮复用旧等待ETL、原始队列记录及精确二进制，并在无Qt对象的新进程核对公开描述符与加载后的IAT地址。未启动GUI回放、模型、人体、USB、Run、优化A/B或任何新跟踪；正式程序、NumPy、绘图及历史计划未改。

## 更具体的阻塞路径

旧等待PID17752、GUI TID20420保留了以下完整、无歧义且关键函数PDB匹配的链：

`NtWaitForAlertByThreadId → RtlWaitOnAddress → WaitOnAddress → QLatch::waitInternal → qt_qimageScaleAARGBA_up_xy → qSmoothScaleImage → QImage::smoothScaled → QImage::transformed → QPlatformPixmap::transformed → QPixmap::scaled → QLabel::paintEvent → QtWidgets.pyd+0x1a8777 → Python解释器 → … → 系统线程根`。

这确认GUI曾同步等待Qt图像缩放任务。这里是QLabel基类绘制路径，不是此前另轮cv2.resize CPU见证，也不能把另轮的4条Qt worker按相同TID接到这轮任务。

## 公开包装入口并未显式让出GIL

精确QtWidgets.pyd SHA为 `85cb6c2181b4b09887a7d8507dd950844d1b8f74a9c4002c7b71169f75bf6fda`。独立新进程只import QtWidgets，不创建QApplication/任何Qt对象；按实际CPython3.11.5头文件读取 `QLabel.paintEvent` 方法描述符，核对owner、name、descriptor大小和实际方法指针。

公开入口位于 `[0x1a8690,0x1a87a3)`，覆盖现场返回RVA `0x1a8777`。没有用反汇编器邻近的PyInit标签充当私有函数名。

| 精确指令位置 | 已核验调用/行为 |
|---|---|
| wrapper 0x1a875e | 调用Shiboken::Errors::occurred |
| wrapper 0x1a8764～0x1a8771 | 检查错误、条件跳转、设置参数；没有中间释放GIL调用 |
| wrapper 0x1a8771 | IAT直接调用QLabel::paintEvent，返回至现场0x1a8777 |
| wrapper 0x1a8777 | Sbk_ReturnFromPython_None |
| 整个公开入口 | 没有显式PyEval_SaveThread/PyEval_RestoreThread调用 |

同SHA的Shiboken公开导出还确认：PythonContextMarker构造/析构为无调用、无分支的叶函数，只调整TLS数据；不能把这个名字当成隐含的GIL释放器。Errors::occurred末尾转至PyErr_Occurred；实际加载的稳定ABI IAT已与CPython导出地址独立比对。

因此，**按正常CPython方法入口持GIL的调用约定，这个QLabel基类绘制桥没有先显式让出GIL，Qt原生缩放/同步不能被笼统视为GIL之外的工作。** 这是精确调用路径的机制约束；本轮没有读取旧目标的实时GIL所有权，也没有证明该路径在所有内部回调和历史时间段都保持同一所有权。不能将静态边界陈述升级为直接owner快照。

## 同一旧窗口内，Qt latch与消费者GIL等待重叠

仅在原三角色CPU计数共同内区间、同一QPC时钟中，分别配对Waiting切出、ReadyThread和切入，并重新检查切入所关联的完整用户栈。GUI要求上述latch/缩放/QLabel链及公开wrapper返回点；消费者TID5376要求匹配PDB的系统等待和take_gil。Ready到切入的尾部始终不算Waiting。

得到59条GUI latch等待、26,350条满足本局部筛选的消费者GIL等待。两侧各保留100µs保护后有59组共同before-Ready区间，涉及59条消费者见证，覆盖PyEval_RestoreThread及PyGILState_Ensure两类边界。这些计数不是独立实验数、等待占比或完整覆盖率；没有用它们计算根因贡献。

原有6个pending/20帧在途观测点均未直接命中GUI latch等待，结果明确保留为0，不能改称同一个观测点。新关联另以完整旧队列记录给出保守边界：

- 收到前缀与批次完成前缀均须单调，原始样本/帧计数连续且无丢帧标记。
- snapshot内的时间戳在实际字段读取之前，不能单凭“时间戳早于等待”就认定整次读取已结束。前侧只能采用被同一生产者下一次snapshot开始所包围、且整个读取已经在等待之前完成的记录；后侧使用整个共同等待区间之后才开始的snapshot。
- 将完整QPC映射不确定性纳入host时间包络，用前侧收到前缀减后侧批次完成前缀给下界，不做最近点匹配或线性插值。

59组的批次完成前缀滞后下界均超过100个样本，最小为154。它可能包括同批次中已经处理但尚未更新完成前缀的样本，**不是精确deque pending或逐帧未处理数，也没有命名唯一的活动20帧批次**。完整边界、两个原始snapshot和各自生产者/索引见qt_wait_queue_bounds01.json。

## 当前可以推进到哪里

现在已有比“GUI可能参与竞争”更具体的路径：带Python调用桥的QLabel基类绘制进入Qt缩放与latch同步；同窗消费者确实在take_gil等待，并能保守关联到批次完成前缀仍落后的阶段。CPU计算、GIL获取与Qt/系统同步不能再被当作互斥的三选一解释，它们可以嵌套在同一条工作链中。

尚未确认具体QLabel实例或现场Python函数。仓库AnnotationCanvas.paintEvent里的super().paintEvent与这类桥相容，但未保存实例身份和Python函数帧，不能唯一命名相机预览，更不能直接修改该控件或脚印绘图。旧低延迟CPU轮的线程入口也不能解释近期startup慢/快CPU差异。

**尚不能证明该桥是积压主因。** 原CPU/CSwitch整体资格、实际负载3%/1%扰动失败不变；没有自然owner的独立时序快照、该路径的合格时间贡献或单变量修复收益。当前不实施绘图、库、线程结构、预分配或正式程序修复，也不重复失败协议获取成功窗口。后续验证应围绕这个具体桥及同窗执行状态，不再扩大IPC或泛化采集框架；当前无需真人测试。

## 保全与验证

14项单元检查通过。新增检查覆盖Ready尾部排除、双侧保护、未匹配符号拒绝，以及snapshot时间戳早但读取可能晚的情况、生产者间不能借用读取结束边界、缺少两侧时不外推。

独立verify_qt_label.py再次读取原始调度payload，核对118条参与见证各自Waiting状态切出、下一次切入、第一条Ready及栈哈希/关键模块，59个共同保护区间和59个完整读取边界全部吻合。它没有只相信派生JSON中的通过标志；源/结果绑定也全部匹配。

首版离线检查错误要求PyErr_Occurred直接从python311.dll导入，实际精确PE经python3.dll稳定ABI转发；断言失败、当时源码及反汇编保留在qt_label_preparation_failure01.json及本地runs。修订增加实际IAT与CPython地址核验，旧文件未覆盖，没有因此重跑任何目标或采集。此失败不是CPU/CSwitch门槛调整。

完整派生结果含全部26,350条闭合消费者链，约243MB，只保留在忽略目录；字节数和SHA见qt_label_raw_preservation01.json。Git摘要保留全部59组时间关联、GUI区间、实际参与的消费者索引/栈哈希，并按观测顺序保留两类入口的首个完整栈，未挑选最长或最短等待。原二进制、反汇编、原始输入及视频不入Git。全部结果绑定源码与原证据SHA，旧失败、旧锁、旧窗口和冻结计划不变；完整根因与正式修复仍未完成。
