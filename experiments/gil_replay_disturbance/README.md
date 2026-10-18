本阶段基于6074610，使用通过确定性等待者控制的同一二进制：02e367c7ca0b1cda5f1067b03125a770a502f10fcabb99fa5925b4265050d615。目标是检查观察器本身对已有Walk接触态原处理链的扰动。没有修改正式程序、原NumPy、滤波、Processor、线程和绘图，没有启动人体、设备、USB、GUI事件循环、视觉、SDK、Run或优化A/B；OFF/ON仅指采集工具关闭/开启。

结论：**确定性等待者控制已通过；接触链回放扰动总验收未通过；完整实际负载校准仍未通过。** 不进行现场定量归因，不声明根因或修复已完成。

所有回放使用已保存的20261018_131910_3eef864f_walk_off输入。预声明测量原始样本42237–49060（6824帧），使用完全相同的原质量/滤波/Processor链和配置；前后完整回放严格核对全报告、质量运行态、事件审计、未掩蔽timeline、mirror和raw archive。没有使用候选算法或替代NumPy。仅每1000输入记录粗粒度区块计时，不加入逐帧计时。目标为原同步消费链，无真实读取队列/pending、GUI绘图、视觉回调或真实SDK子进程；不能将其结果推广为完整负载通过。

plan01.json预声明三对顺序OFF/ON、ON/OFF、OFF/ON。每个ON窗口40次、50ms间隔，ORACLE_ADDRESS=0，合成心跳读取禁用，但同一外层暂停/Python读/原始栈读取路径不变。每个ON必须至少38个完整QPC括号落在接触测量段内；全部读取保留原始时间边界和不确定性，不按序号/中点插值。外部保留句柄核对PID/TID/创建时间、GetThreadTimes和cycles，并交叉检查目标thread_time计时。总段wall、thread CPU、cycles及每个固定1000输入区块wall的绝对相对变化都须<=15%，没有平均或剔除区块的例外。

初始cohort保留为失败：

- 首个pair1_off已完成原链及语义核验，随后因缺少部署的align_clock.py而分析中止，错误结果和第一份failure01.zip原样保留。
- completion02_plan.json只补齐分析依赖，并继续五个未执行窗口；首个OFF从原始数据离线复核，没有重跑。第一对通过，总段wall变化+6.53%。
- pair2_on完成后，pair2_off的控制器读到了刚创建但未写完的roi.json，发生JSONDecodeError；缺少after-counter和完整终止报告，不能作为有效校准。pair3未启动。该目标当时仍运行，现已没有匹配进程；未保留足够证据判断其具体退出原因，不能补造成功退出。

这两个异常属于采集工具交接流程。旧target.py、control.py、verify.py、原计划、日志、结果、窗口和锁均未覆盖。

原子发布修复见atomic_io03.py、target03.py、control03.py：仅将JSON写入独占.partial文件，flush/fsync并关闭后，再通过同目录NTFS rename发布。读者在完整数据发布前看不到成功路径；写入、同步、重命名失败均保留.partial；旧结果和失败.partial阻止覆盖/重试。Windows实际运行8项故障测试，覆盖写入中读取及目标文件冲突，全部通过。prepared03_plan.json是修复准备快照；后续采集另冻plan03.json，没有覆写它。

plan03.json是修复后独立cohort，仍为相同三对、同输入、同二进制和同15%门槛；不与初始失败cohort合并，不替换任何失败证据。六个窗口全部正常完成并通过单窗语义、完整流、时间括号、身份和CPU/cycles核对；三个ON各40次，共120个采样。总验收仍失败：

| 对 | ON相对OFF的总段wall变化 | 最大区块wall变化 | 该对扰动验收 |
| --- | ---: | ---: | --- |
| 1 | +7.3929% | +15.6007% | 失败 |
| 2 | +6.6065% | +10.8127% | 通过 |
| 3 | +4.6870% | +14.0037% | 通过 |

唯一超限区块为第一对raw45237–46236。其+15.6007%超过15%，不按四舍五入、总段平均或其它通过对替换。不再采样寻找通过结果。cohort_result03.json保留false，完整重算见review03.json及recompute03.py。上述变化是本固定回放条件的OFF/ON比较，不是现场GIL等待占比、某函数成本或原现场积压的根因。

原始证据位于被忽略的experiments/native_stack_capture/runs/gil_replay_disturbance01：failure01.zip保存首个异常窗口；evidence03.zip保存全部初始/修复后窗口、源快照、计数器、时间括号、失败结果、Windows故障测试及锁。132个manifest文件逐项哈希验证，归档SHA见transport03.json。所有Windows原始JSON换行字节保留。

post03.json确认正式458文件、回放副本458文件、旧现场及旧动态源、确定性等待者源、原/修复后冻结源、6个输入文件、首次失败manifest均无变化；回放helper SHA和观察器SHA一致，采样间隔仍为10000×100ns；旧锁和两组失败锁均保留，已无本阶段测试进程。旧CPU/CSwitch失败验收继续false，未改变栈闭合门槛。回放原始流检查也不将StackWalk结束自动认证为PDB闭合，不能据此做函数归因。

本轮验证包含120项不同测试：Mac119项通过、1项NTFS专属测试跳过；Windows原子发布8项通过，包含该NTFS测试。19项确定性控制测试使用显式类名执行，避免导入导致重复计数。

复核（输出文件必须不存在）：

```sh
python experiments/gil_replay_disturbance/recompute03.py --raw experiments/native_stack_capture/runs/gil_replay_disturbance01/evidence03 --output /tmp/replay-disturbance-recheck.json
python -m unittest discover -s experiments/gil_replay_disturbance
```

下一步应先降低并验证工具扰动，再独立冻结完整GUI/视觉/SDK并发的实际负载校准。当前无需新增现场Walk；新增人体输入不能补救本工具扰动门槛失败。actual_load_disturbance_pass、field_attribution_ready、root_cause_or_fix_complete全部false。
