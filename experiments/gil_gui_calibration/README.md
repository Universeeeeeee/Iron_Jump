本阶段完成一次GUI功能核验和预声明4对OFF/OFF可比性检查。8轮完整输出和原生计数协议通过，但整段视频输入身份的必要条件有3对失败，不能确认3%扰动或定量归因；没有启动真人Walk。用户确认现场就绪后，先检查Windows无IronJump/SDK/采样器进程、WPR未录制。只余两个旧入口PowerShell进程，没有重开旧入口。没有Run、优化A/B或物理光栅采集；没有修改正式程序、原NumPy、滤波、Processor、线程结构或绘图实现。

本夹具复用ground_backlog_measurement已保存的Walk光栅/原始视频与独立语义基准，启用原ExecutionView、骨架绘制和真实OBSBOT SDK。原夹具的两种绘图安装分支完全移除，实际调用生产GroundChannelWidget.paintEvent，SHA为9b902ace875bfb1b253e0b4653dd790d70b204385471578d0781498d77e5f527；保留的A仅为旧命令行标签，不比较任何候选。现场单USB与原生相机采集、软件录屏负载没有纳入，因此不能直接视为完整现场校准。

独立Windows目录为E:/OptoJump/IronJump-gil-gui-calibration-20261018-01。正式458个源文件及25个依赖按SHA复制，不修改原目录；553115702字节、22个输入文件及独立oracle经哈希冻结，通过只读使用的NTFS junction供回放读取，没有把视频/照片/原始传感器文件放进Git。原始数据归档只放在被忽略的native_stack_capture/runs下。

首次部署在任何GUI/SDK启动前缺少baseline_manifest父目录而失败。setup01.py与deployment_failure01.json保留；finish_setup02.py只验证已经复制的文件、补齐目录并完成余下步骤，没有覆盖旧源或重复任何采集。

functional_smoke01仅做一次功能核验，没有观察器或性能通过判断。进程正常退出、SDK启停正常；627次有效骨架绘制、732个实际解码帧、471次SDK tracking决策、395次非零速度调用。完整报告、质量/runtime、审计/timeline/mirror、原始位图/wire/validity/stream/drop、archive和全部脚印发布与旧独立基准精确一致。该结果不是采样扰动通过。

aa_plan01.json在执行前冻结4对、8个新进程OFF/OFF可比性检查，全部同一Walk/原绘图/原处理链。增加的replay02.py只记录实际送入视觉链的归档frame_index，并将既有pid/armed握手改成已经验证的原子发布；旧replay01及smoke冻结源不覆盖。每轮armed后12–17秒，用保留句柄读取GUI、consumer、reader与独立SDK进程当时所有线程的GetThreadTimes/cycles，保存QPC/perf括号、创建时间及实际端点迟到量；SDK模块及父进程拓扑由prepare_targets.ps1独立核对。此队列完全没有开启4Hz采样器。记录中SDK线程可能很多，不能把它们当独立重复，也不把其独立GIL当成GUI进程的持有者。

analysis_plan01.json冻结6个描述性终点：consumer/gui/sdk三组各自CPU与cycles，独立单位为完整新进程对。4对用于可行性检查，不能证明3%等效或1%精度；零计数端点报告不可用，不加入epsilon。送入视觉链的视频帧ID完全一致只是可比负载的必要条件，实际推理选择、绘制及SDK决策仍可能不同。所有不匹配和慢轮保留，不剔除、不归一化、不追加成功轮。

8轮全部完成，独立SDK模块/父PID核对、全部保留句柄身份、GetThreadTimes/cycles单调、完整语义均通过；时钟映射不确定性8.7–15.2微秒。结果见aa_result01.json。

| 对 | 解码帧数A/B | 整段视觉输入frame_index序列相同 | 有效绘制A/B | SDK tracking决策A/B |
| --- | --- | --- | --- | --- |
| 1 | 740/740 | 否 | 580/638 | 474/477 |
| 2 | 739/740 | 否 | 625/638 | 477/478 |
| 3 | 741/741 | 是 | 635/636 | 477/478 |
| 4 | 740/740 | 否 | 635/634 | 476/478 |

相同解码帧数仍可能遗漏不同的视频帧；video_identity_diff01.json保留具体集合差异。这只定位整段回放输入/调度的可比性缺口，尚未证明不一致发生于12–17秒ROI，也不能将一帧差异直接换算成CPU差异。第3对送入视觉链的帧序列相同，但绘制和SDK决策数仍不完全一致；这些下游结果也不是实际推理帧身份的证明。

既有队列与首次绘制时间进一步提供了一次无采样器的严重积压窗口：pair01_a在继承的59904–65904接触样本段实际输入约999.70fps、批次完成进展约649.87fps，精确待处理队列峰值3391帧、最老pending约3386.68ms；输入接收至首次确认绘制最大3472.67ms。这个区间按完成样本归属统计，可能延伸到输入的后续空场，不能冒充相同5秒host窗口或现场身体动作时刻。

后7轮同一旧输入整场pending峰值62–81帧、输入接收至首次确认绘制最大约160–168ms。queue_descriptive01.json、publication_descriptive01.json保留8轮全部数值。由此无需新增人体就保存了一次同类主机积压；未证明稳定复现、唯一根因或旧现场等价，也不能将设备供电/温升认作所有现象的必要原因。

counter_work_alignment01.json用真实QPC不确定性界限对齐批次完成见证，不按采样索引插值：首轮5秒原生counter窗口前后的完成样本分别约60495–60555与63235–63315，对照pair01_b约60883–60933与65865–65939。相同host窗口内消费者实际推进的样本范围不同，还须保留在途20帧的不确定性。因此原生CPU/cycles均值接近不能证明单帧成本相同，也不能直接给GIL/CPU/Qt分配比例。contact_mix_descriptive01.json只描述这些近似样本范围的接触束数，不以接触密度代替实际计算量。

保留全部4对后的描述性、6终点家族95%同时区间：consumer CPU约[-15.30%,+29.02%]、consumer cycles约[-1.20%,+3.99%]，GUI CPU约[-10.70%,+6.09%]，SDK CPU约[-85.30%,+255.24%]。这是没有采样器的所选原生线程计数差异，不是采样器开销，更不是GIL等待/持有或函数贡献。GUI角色仅代表GUI线程，不能代替包含推理/解码线程的整个GUI进程CPU。小样本、动态视觉工作及SDK负载均限制这些区间，cycles不能用于推算物理频率。

固定队列比预估更久；助手在第4对B仍活动时做过一次Windows状态/CIM查询。精确查询与ROI的重叠没有独立QPC括号，故保留潜在扰动标记status_query_caveat01.json，不声称整组是纯本底，不剔除该轮、不补采。前三对完成前没有这次状态查询，但它们仍不代表背景受控；前两对的视觉帧身份差异不能归咎于这次末轮查询。

post01.json确认正式/隔离GUI各458个源文件、25个依赖、22个输入、oracle及两份冻结源均未变；原NumPy SHA未变，采样间隔仍10000×100ns。旧13个锁与新2个锁均保留，所有回放和SDK进程已退出。134个manifest文件及ZIP SHA逐项核验通过，transport01.json绑定原始归档；完整失败/不匹配窗口均在归档中。

旧24对确认、3%/1%失败、15%单轮硬限制、CPU/CSwitch失败验收、旧故障锁及原先全部冻结计划不变。没有ETW或调用栈采集的本阶段不产生PDB、栈闭合或ETW丢事件通过结论。actual_load_disturbance_pass、field_attribution_ready与root_cause_or_fix_complete保持false。

离线核验源码覆盖SDK/PID混用、创建时间变化、计数倒退、重复/缺失线程和过大时钟不确定性；10项测试通过。第一版测试对旧mapping的异常类型期望写成AssertionError，实际已有ValueError先行拒绝；只更正测试期望，未改验收门槛。

observability_source_map01.json确认原FootVisionService已发布带frame_metadata及起止时刻的pose_inference_ready，且使用latest_frame_only/maxlen1；送入的帧可以被合并，不能替代实际推理身份。原PoseRelay.packet带完整元数据，而tracking_decision只带generation/captured_at，不带frame_index；没有唯一匹配时仍未知。这是既有源码路径图，未加任何新回调，也不证明GUI序列化或推理是责任函数。

此时最小的现场操作为零：不再启动Walk，也不重开任何旧入口。下一步优先分析已保留的pair01_a严重积压及其快轮，并补齐视频ID→实际推理→绘制/SDK边界的观测，分别核对原生计数与所代表工作；不可强制改变原绘图/推理丢帧策略来制造“相同负载”。本轮尚无实际持有者/等待者完整栈，无法补造，根因未锁定。后续任何新控制/采集须新冻结，旧计划与失败原样保留；真正的单USB人体窗口仍须另行明确开始。
