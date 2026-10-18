本目录是隔离的动态持有者与原生暂停交付控制，基于同分支9d8033e。没有修改正式程序、原NumPy、滤波、Processor、线程或绘图，没有启动人体、设备、USB、GUI、Run、优化A/B或ETW/WPR。

已执行唯一一个新冻结窗口，plan01.json在采样前冻结源码及二进制SHA；没有重采。目标PID20476，持有者TID2480/9340，Python心跳TID20772；另一原生心跳TID7248由CreateThread创建，不调用Python API、不获取GIL。两个Python工作线程通过PyDLL交替进入带seqlock标记的原生等待，Python帧分别为hold_a/hold_b。观察器在同一外层Process.lock中读Python身份和两条原始原生调用链，并在锁内前后读取原生心跳；恢复后才解析符号和写文件。Activity标志仍无效，不能用作调度状态。

冻结总验收 **失败**，见result01.json；保留Windows active.lock及完整失败窗口。控制器退出成功只表示原始采集正常完成，不代表测量验收通过。离线派生说明failure_review01.json不改写失败结果，也不作为新验收。

| 项目 | 本轮观察及边界 |
| --- | --- |
| 暂停内原生心跳 | 40/40内层前后值相同；不依赖GIL的原生心跳在16/16未暂停对照中增长，目标恢复后继续增长。这是对该原生线程的独立交付检查，不给所有线程标注Running/Ready/Waiting。 |
| 时间对齐 | 完整QPC读取括号及不确定性均保留；QPC映射不确定性9.8微秒，不按采样序号或中点插值。 |
| 动态持有者 | 34个完整外部epoch括号内，owner TID和Python函数全部一致，其中hold_a12个、hold_b22个；6个过渡／空闲样本保留未知。计数不代表时间占比。 |
| 原生栈 | 34个可对齐样本均保留初始context IP、全部StackWalk地址和两条匹配PDB的线程根；不能由StackWalk结束本身推断闭合。 |
| 未通过项 | 5个可对齐样本的请求线程仍在pysleep→NtWaitForSingleObject，未进入take_gil/PyEval_RestoreThread，故不满足冻结检查器“每个可对齐样本均具备GIL等待链”的要求。其它29个可对齐样本具备该链。 |
| 符号 | 5个系统/Python模块的PE、解析PDB和实际加载GUID/age一致；DynamicOracle.dll、ffi.dll、_ctypes.pyd无匹配PDB，函数名不作为证据，保留同SHA模块+RVA。没有内核栈。 |
| 开销 | 完整读取括号中位5.4354ms、最大6.6755ms；锁内两次心跳读取间隔中位5.40425ms。都不是GIL持有时间，也未完整覆盖暂停开始；实际启动间隔中位50.3899ms、最大50.5924ms。尚无该工具的实际负载扰动通过结论。 |
| OS核对与清理 | 4条保留句柄的PID/TID/创建时间稳定，GetThreadTimes与cycles单调，原生心跳有独立CPU/cycles进展。目标与观察器退出0，无stderr；失败验收锁继续保留。 |

失败的5次可对齐样本为ordinal4、7、15、18、29。未把普通休眠当作GIL等待，未放宽CPU/CSwitch或本轮总验收门槛。既有现场TID3816仍未知，不能用本合成目标的持有者解释历史现场。

原始归档位于被忽略的experiments/native_stack_capture/runs/gil_coherent_dynamic01/evidence01.zip，SHA见transport01.json；30个文件逐项哈希核验。Windows独立目录为E:/OptoJump/IronJump-gil-coherent-dynamic-20261018-01。源码冻结快照、原始40行样本、oracle、计数器、日志、离线解析及锁均保留。首次构建失败是Rust默认路径不能执行；打印日志时又遇到GBK编码错误。修正为显式RUSTC路径后构建完成，SSH等待超时发生在57秒构建期间，之后只查验完成日志和二进制，没有重复启动构建或采样。初始源码ZIP与两次构建日志保留。

post01.json确认458个正式文件、旧现场源码、上一恒定控制和故障控制源码均未变化；全部旧故障锁仍在，采样间隔仍为10000×100ns。旧CPU/CSwitch失败验收SHA保持原值。

下一阶段应先设计能保证请求线程确实进入GIL获取边界的独立控制，并与普通原生休眠明确区分；不能让一个间歇sleep线程在每次快照中都必然处于take_gil。现有数据可以解释本次失败，但不能将旧计划重命名为成功。新的控制需独立冻结和独立证据，保留本失败窗口；随后仍须对最终拟用于现场的准确二进制校准负载扰动，GUI与SDK子进程分开。当前不部署现场入口、不要求新增Walk、不输出GIL占比或责任函数结论。

复核（输出文件必须不存在；检查JSON中的总验收布尔值，脚本正常退出不等于验收通过）：

```sh
python experiments/gil_coherent_dynamic/verify.py --root "$PWD" --raw experiments/native_stack_capture/runs/gil_coherent_dynamic01/evidence01 --resolved experiments/gil_coherent_dynamic/symbols01.json --output /tmp/dynamic-check.json
python -m unittest discover -s experiments/gil_coherent_dynamic
```

源文件已冻结，请保留Windows原始CRLF证据；使用git -c core.whitespace=cr-at-eol检查差异，不能为消除换行提示改写已认证的JSON字节。
