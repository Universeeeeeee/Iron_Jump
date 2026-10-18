本次在新隔离目录完成一次原生持有者边界控制，不是重做或替换现场失败轮次。正式程序和既有观察器没有修改，没有启动GUI、SDK、USB、人体、Run或优化A/B。

原生夹具由CreateThread创建线程，直接调用该Windows Python3.11.5二进制的PyGILState_Ensure。拿到GIL后才发布独立seqlock标记，在C中Sleep5秒，清除标记后才释放GIL；没有调用Python回调或进入Python求值帧。另一Python心跳线程在该标记区间不进展，释放后恢复。使用同SHA观察器，60次实际读取全部有完整独立oracle括号，60次都准确报告该原生TID为owner且Python帧为空；原生句柄/创建时间稳定，进程正常退出，QPC映射保留15.8微秒不确定性。完整原始数据和每个检查见result01.json及被忽略的原始归档。

这证明“持有GIL但无Python帧”在当前二进制上可以真实出现。py-spy对Python3.11从gilstate.tstate_current读身份，再从cframe.current_frame读Python链，两者不是同一项证据。空链不一定是读取损坏，也不能因此给它补一个业务函数名。实际fieldTID3816的原因仍不明：它可能处于原生阶段，也可能落在其它未保存的读取边界，不能用合成线程替代其身份。

原现场protocol对空owner帧继续返回false，字段验收仍不通过，故障锁不解除。控制通过只证明这一机制反例；没有输出GIL比例、持有时长、责任函数或实际负载扰动通过结论。此前Python-marker失败窗口、原生CPU/CSwitch失败验收和所有原计划保持原SHA。

下一阶段的观测方案需要在同一个可校准的一致性窗口内补齐无Python帧owner的原生调用链及独立原生线程身份，不能仅删除空帧条件或改为忽略该样本。实际负载扰动仍需单独验收。本次尚未实现或部署新的现场采集方式，不要求用户再走。

本轮另对发布边界完成了一项测量层修正，见相邻现场目录publication_boundary02。Windows和Mac原链重放均与完整报告、质量、事件审计、timeline及原始归档精确一致，40977行映射二进制逐字节相同。11次published_sample都需到其后第10个raw样本才送进Processor。用错误索引查询会改变contact4/11/12的完成括号，旧review01.json保留，发布分解以后续bounds01.json为准。

最后两步从最初接触样本收件至所需外层输入收件约82.780/78.376ms；所需输入已经收到后，仍分别至少349.575/427.208ms才进入发布。后者是主机排队/处理边界，不能再由60ms接触确认窗口或10帧滤波转交独自解释；也不能给这段时长贴上CPU、GIL或Qt锁标签。对应总收件至绘制仍为475.470/636.918ms。根因和修复仍未完成。

复核：使用项目Python运行verify.py --root <worktree> --raw <worktree>/experiments/native_stack_capture/runs/native_owner_gap01/evidence01 --output <全新文件>；测试python -m unittest discover -s <本目录> -p test_native_only.py。源/计划和原始数据SHA均保留，已有失败数据未覆盖。
