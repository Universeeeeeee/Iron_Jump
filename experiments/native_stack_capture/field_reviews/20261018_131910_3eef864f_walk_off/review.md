本轮完成 11 个接触发布和绘制，原始帧、设备计数、wire 解码、归档及报告变换检查通过，最终队列排空、读取线程退出、SDK 已停止。控制器为 valid_capture=true；子程序返回码仍是 1，不能写成干净进程退出。报告 touch_count=11，valid_steps=8 是原程序的另一统计口径，不能把它改写成人体只走了 8 步。用户仅报告“识别准确”，未明确报告骨架全程连续。

低延迟感受与后程积压同时存在。在本次观测条件下，主行走 raw 块 sample42237–49060，主机接收在正式开始后8.325–15.161秒；输入约997.25帧/秒，消费约923.18帧/秒，pending观测最高598。该局部窗口满足原 sustained-shortage 判断；整场平均约1000帧/秒及把稀疏尾部脉冲并入接触包络所得的阴性结论，均不能否定此主段积压。该主段选择和100sample清空间隔规则均保存在复核脚本中，不是更改栈验收门槛。稀疏脉冲未删除、未解释为人体接触。坏束576只在离线usable分析中排除，物理6米坐标保留，原程序和坏束处理均未改动。

主机收到接触样本到首次脚印绘制，前6个约144–203ms，最后两个475.470/636.918ms。最后一个发布样本的消费边界表明，在它被处理之前已经过至少505.584ms；从发布处理到绘制的上界为131.333ms。边界来自queue_common/queue_final，不能解释成单函数耗时。它包含确认所需后续样本、排队和处理；主机接收前的设备/USB年龄未知，不能称为完整动作到屏幕延迟。

主段逐秒骨架绘制计数均大于0；这只支持每个观测区间存在有效绘制，不能证明每帧正确或全程无中断。已检查录屏93–102秒的10张稀疏画面：可见向前行走、相机取景更新及脚印继续更新；没有与QPC共享的录像时钟锚，不能靠画面精确归因延迟。

持有者观测完整写出了120次读取及init/complete，无error行，进程已退出、日志为空。但ordinal31的TID3816报告owns_gil=true而Python帧为空，原protocol明确拒绝整轮。因此完整性、现场归因都不通过，故障锁保留；另外9次无owner状态全部保留，不当作丢失。QPC对齐保留8.9µs不确定性，全部实际读取括号约1.524–4.390ms，真实间隔约50.06–50.68ms，没有按序号插值。现场读取括号比合成控制长，不能把合成扰动通过移植为实际负载通过。

GUI PID4308的GUI/consumer/reader分别TID4688/22056/16016；保留句柄的生命周期、GetThreadTimes和cycles检查通过，CPU计数位于独立正式程序快照之间。SDK PID7192单独保留21条原生线程计数，不能把SDK的GIL当作GUI的GIL。相机和视觉额外线程只有trace报告的ID，缺少独立生命周期句柄，线索等级更低。未通过整轮的候选路径见evidence_matrix01.json；不能将其指认为历史6个take_gil见证的持有者，不能输出等待占比、热点百分比或修复已完成。

下一步先离线处理空Python帧持有者的可观测性及实际负载扰动验收缺口。TID3816的本轮Python栈无法事后补造；若需要新原生补证，应形成单独冻结、先校准的新方案，同时保留本轮失败和锁。当前无需用户再走，不自动重开或重采，不放宽门槛。正式程序、NumPy、滤波、Processor、线程及绘图均未修改；未启动Run或优化A/B。

原始证据（含全部失败记录）保留在Windows `E:/OptoJump/IronJump-gil-timestamped-20261018-01/field_evidence01.zip`，以及本工作树被忽略的 `experiments/native_stack_capture/runs/gil_timestamped_field01/`。归档SHA见verification01.json。历史失败控制锁及本轮故障锁均保留。

离线复算（项目Python3.11及NumPy）：

```sh
python experiments/native_stack_capture/field_reviews/20261018_131910_3eef864f_walk_off/verify.py --root "$PWD" --raw experiments/native_stack_capture/runs/gil_timestamped_field01/evidence01 --supplement experiments/native_stack_capture/runs/gil_timestamped_field01/supplement01 --output /tmp/ironjump-owner-review-fresh.json
python -m unittest discover -s experiments/gil_timestamped -p 'test_*.py'
```

输出路径必须是新文件；复算结果应与review01.json完全相同。35项既有测试通过，其中已有owner无Python帧拒绝测试；没有更改该检查。新增的只有离线分析，冻结采集源SHA未变，因此不生成或覆盖采集计划。
