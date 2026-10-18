本目录是基于761132b独立冻结的确定性GIL等待者控制。没有修改正式程序、原NumPy、滤波、Processor、线程或绘图，没有人体、设备、USB、GUI、Run、优化A/B或ETW/WPR测试，也不替代gil_coherent_dynamic失败窗口。

新二进制SHA为02e367c7ca0b1cda5f1067b03125a770a502f10fcabb99fa5925b4265050d615。与上一候选相比，仅增加ORACLE_ADDRESS=0时跳过合成标记读取；非零地址用于本控制。Python身份及原始原生栈仍在同一个Process.lock内读取，恢复后才解析符号/写文件；保留context IP、重复首帧和原生线程根，activity标志仍不作调度状态。同SHA二进制仍须独立进行负载扰动校准，尚未部署现场入口。

计划只执行两个预声明阶段，每阶段20次、50ms间隔，无重复采样。Python工作线程通过PyDLL分别持有GIL进入hold_a/hold_b；CreateThread创建的原生等待者直接请求PyGILState_Ensure，同时发布请求/获取阶段标记，不经过Python sleep。另一完全不依赖GIL的原生线程持续增加心跳。

| 检查 | 实测结果 |
| --- | --- |
| 身份/完整时间括号 | PID18152；owner TID19504/17392，waiter17540，native heartbeat10988。40/40完整QPC括号位于独立稳定epoch内，requested=当前phase、acquired<当前phase，零未知；时钟不确定性9.4微秒。 |
| 原生等待 | 40/40持有者TID和hold_a/hold_b一致，等待者无Python evaluation frame，具有闭合的NtWaitForSingleObject→take_gil→PyGILState_Ensure路径，无pysleep。两条原生栈每次都闭合至匹配PDB的BaseThreadInitThunk→RtlUserThreadStart。 |
| 暂停交付 | 40/40锁内原生心跳值相同，16/16未暂停对照增长，采集结束后继续增长。不据此标注任意线程的调度状态。 |
| 恢复/OS核对 | 两阶段释放后等待者均成功获取GIL；目标和观察器均退出0，无stderr。每阶段3个保留句柄的PID/TID/创建时间稳定，GetThreadTimes/cycles单调。 |
| 符号 | PE CodeView、独立解析PDB与实际加载GUID/age匹配。无匹配PDB的WaiterOracle.dll、ffi.dll、_ctypes.pyd保留同SHA模块+RVA；没有内核栈。 |
| 开销 | 完整读取括号中位4.18815ms、最大5.2328ms。这不是GIL持有/等待时间，亦非实际负载扰动通过证明。 |

result01.json最初仅因recovered=false判失败：冻结verify.py错误要求完成心跳大于倒数第二个oracle读数，但原生线程在写complete.json前已停止，多个采后读数可以相等。原verify.py、result01.json与plan01.json全部原样保留，源SHA未变，没有重采。

review02_plan.json独立冻结了同一原始数据的离线修正：心跳须在完整采集窗口结束后仍有进展，完成时刻须在窗口后，两个阶段都须发布获取成功标记。verify_recovery02.py只修正恢复比较边界，其余40个完整括号、零未知、身份、闭合、PDB及请求/获取条件原样检查。result02.json通过确定性控制，旧动态失败不变。新增5项用例覆盖终止后计数相等、无恢复进展、过早完成、缺少获取标记及其它栈失败仍拒绝。

原始归档被忽略于experiments/native_stack_capture/runs/gil_waiter_control01/evidence01.zip；SHA见transport01.json，34个manifest文件逐项核验。Windows目录E:/OptoJump/IronJump-gil-waiter-control-20261018-01的锁继续保留。构建62秒完成，SSH先在60秒等待超时；随后只查验已完成日志与二进制，没有重复构建或采样。构建源ZIP与日志保留。

post01.json确认458个正式文件、旧现场及动态控制源未变，全部旧失败锁保留，采样间隔10000×100ns。原始JSON保留Windows换行字节。

下一步对同SHA工具做扰动校准。旧Walk同步原处理链回放不包含真实排队、GUI绘图、视觉和SDK并发，即使通过，也须保持actual_load_disturbance_pass与field_attribution_ready=false。现场TID3816仍未知，不能输出GIL占比、责任函数或已修复结论。

复核（输出文件必须不存在）：

```sh
python experiments/gil_waiter_control/verify_recovery02.py --root "$PWD" --raw experiments/native_stack_capture/runs/gil_waiter_control01/evidence01 --output /tmp/waiter-reviewed.json
cd experiments/gil_waiter_control
python -m unittest test_waiter.WaiterChecks test_recovery.RecoveryBoundaryChecks
```

上面是19项不同测试。discover会重复运行test_recovery导入的14项，不能将重复执行计入新增测试数。
