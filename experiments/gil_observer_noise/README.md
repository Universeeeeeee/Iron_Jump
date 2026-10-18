本阶段离线准备已完成：4Hz/5秒确定性等待者控制通过，但固定24对扰动确认未通过3%等效与1%精度要求，仍不具备定量现场归因资格。基于c48d0cc、延续2bf0cec，在用户离场期间只做隔离的已保存Walk原链回放及合成控制。正式程序、原NumPy、滤波、Processor、线程及绘图未改；没有人体、USB、GUI/视觉/SDK、Run或优化A/B。所有新计划独立冻结，旧失败、锁、15%硬门槛及CPU/CSwitch闭合验收不变。

先做A/A，再评估工具偏置。OFF/OFF与ON/ON各预声明8对（16个新进程回放），不同区块只作为相关终点，不冒充额外独立样本。两组都已完成，原始流/输出/源SHA/时钟/保留句柄/GetThreadTimes/cycles核对通过，归档SHA见*_transport.json。原始证据被忽略于experiments/native_stack_capture/runs/gil_observer_noise01。

现有20Hz工具完整读取括号中位3.8517ms、最大7.0537ms；恢复后符号处理最大125.92ms。括号不等于GIL持有/等待时间，不能用这些数值直接推导原现场根因。新候选不改二进制（SHA02e367c7ca0b1cda5f1067b03125a770a502f10fcabb99fa5925b4265050d615），仅改为250ms/4Hz、回放8次；更少采样牺牲见证密度，不能因此放宽栈闭合和时间关联要求。

A/A已揭示测量噪声：

- OFF/OFF整段成对log比值SD约3.23%，一对整段差约5.62%，首个1000输入区块差约26.55%。没有采样器也有大区块波动。
- ON/ON整段成对log比值SD约1.45%；其整段95%家族同时区间约[-2.44%,+1.66%]。
- 这些区间是whole-pair log比值Student t、10个预声明终点Bonferroni家族95%区间，依赖适用的独立性/平稳性，不能当作无分布假设保证。完整数值和漂移筛查见off_aa_result01.json、on_aa_result01.json。
- 因此旧+15.6007%区块超限仍保留为失败，但不能将它全部指认为采集器开销。A/A先回答自然/协议波动，OFF/ON才衡量加入采集后的变化。不得用后验去趋势、剔除异常、cycles归一化或重复取成功窗口掩盖波动。

statistics_plan01.json在结果分析前冻结终点和规则：新目标3%家族等效区间，另保留每个原始试次/区块绝对变化<=15%的硬限制；不能平均掉既有坏窗口。目标同时log区间半宽1%，从两组A/A估计方差，一次选择8–24对，不能中途加轮。precision_decision01.json选择24对上限，但预测精度仍不足，达到上限并非通过。

confirmation_plan01.json是一次固定24对OFF/ON确认，顺序交替平衡。A/A有7或8次读取完全落入ROI；确认组在target go后等20ms再启动采集，并要求8/8完整括号都在ROI。目标/二进制/频率/样本数不变。ON A/A只作为该相位的近似规划先验，确认组区间用自己的完整成对数据，不能声称两个启动相位完全匹配。确认期间不另起助手的Windows状态/归档/测试进程，进度仅由现有控制器在每个回放完成后输出；普通系统背景未受控制。A/A阶段曾有助手状态/归档活动，不能把其方差当成纯硬件本底。

48个新进程已全部完成，原链完整输出、源/输入SHA、时钟、保留PID/TID句柄、GetThreadTimes/cycles及8/8读取括号位于ROI内的协议核验通过。confirmation_result01.json使用完整24对，独立单位始终是24对，不是区块或样本数。每对均固定计算ON/OFF，AB/BA不会因反向比值抵消；test_orientation.py覆盖这一分析边界。

| 固定确认结果 | 整段wall | 线程CPU | cycles |
| --- | --- | --- | --- |
| 几何均值变化 | -2.42% | -4.02% | -3.99% |
| 家族95%同时区间 | [-9.01%, +4.64%] | [-10.31%, +2.72%] | [-10.39%, +2.88%] |
| 最大原始成对绝对变化 | 41.30% | 40.91% | 41.85% |

首对OFF=3809.727ms、ON=2236.3565ms，全7区块同时变慢，原始数据不裁剪、不归一化、不重复。10个终点均未完成要求的等效认证，旧15%硬限制也有失败。整段同时log半宽约6.99%，高于1%目标。在同一参数模型下，整段80%检测灵敏度对应约9.41%的正向变化；这不是实际GIL效应大小，也不是等效通过证明。普通背景、独立性/平稳性和重尾限制仍存在，未触发单调漂移标志不能取消这些限制。负的均值不能解释成“采样使程序加速”。

gc_plan01.json另冻4个OFF诊断，用预分配数组记录稀少GC start/stop事件，不禁用GC、不强制收集、不改阈值。原链完整输出核对通过。新增回调自身未做扰动资格认证，可能影响GC调度；不能回溯解释旧慢窗口，不能将callback括号当作独占GC CPU成本。gcreview仅配对原始时间/线程/代际事件。所有诊断与确认组顺序执行，不并行争用Windows负载。

gc_result01.json中4轮均为接触ROI内24个配对事件，最长单个括号约2.995–3.103ms。另有cpu_delivery01/plan01.json独立冻结的4轮OFF只读诊断，完整原链输出均匹配：

| 新诊断 | wall ms | 线程CPU ms | 同轮最长GC括号 ms |
| --- | --- | --- | --- |
| cpu01 | 3805.399 | 3796.875 | 3.064 |
| cpu02 | 3850.526 | 3843.750 | 3.004 |
| cpu03 | 2196.802 | 2171.875 | 1.998 |
| cpu04 | 2135.361 | 2125.000 | 2.122 |

这些新增回放慢轮的CPU计数同样增加，不能只靠线程未获调度解释。SDK声明的GetCurrentProcessorNumberEx与GetSystemCpuSetInformation保留粗边界位置、原始结构字节和SDK字段偏移；读到的efficiency_class均为0，PowerThrottling策略位为0。它们不能证明物理CPU交付、频率不变或完整迁移轨迹，也不能回溯解释旧现场。没有设置亲和性、优先级、电源、计时器或GC；两类新增探针均未完成自身扰动认证。GC括号不支持独占CPU占比，未观测到长GC事件不能排除分配/释放/其它原生成本。

field_rate01/plan01.json使用相同观察器，250ms间隔、每阶段20次；只将合成owner持有期由2.5秒延长到7秒以包住拟用5秒窗口。40/40持有者和原生等待者完整闭合，零未知；独立请求/获取标记、16个未暂停对照、原生心跳暂停/恢复、保留句柄及PDB GUID+age全部通过。实测间隔250.066–250.622ms，时钟映射不确定性16.3/22.8微秒。完整读取括号中位7.337ms、最大8.807ms，不是GIL持有/等待时长或已校准扰动。未匹配PDB的模块保留原地址、模块SHA和RVA，没有内核栈。原冻结verify.py的终止心跳比较缺陷仍保留，沿用此前已经测试的verify_recovery02修正，不重采；新结果同时报告原recovered=false及修正后true。

证据归档均保留。CPU归档首次Mac核验遇到Windows反斜杠manifest路径与ZIP正斜杠路径不一致，失败记录见cpu_delivery01_diagnostic01_transport02.json。原ZIP、manifest、collector02及数据均未重写；archive_review01仅在离线读取时规范分隔符，拒绝绝对/越界/路径及大小写碰撞，逐文件SHA校验通过。没有因此重跑或重采。6份原始ZIP共988个manifest文件逐项核验，SHA见local_preservation01.json；原始输入不进入Git。

统计分析依赖单独的临时环境/private/tmp/ironjump_stats_20261018，版本固定于stats_requirements.txt；没有安装进项目/Windows程序环境，没有更换正式NumPy。

final_audit_windows01.json确认正式与回放各458个文件、所有6份新计划源、旧现场/动态/等待者源及失败manifest未变；13个历史或本轮锁保留，原NumPy扩展SHA仍为4fb4c5d62a6bd766eea716350eaf5396580e33cf7dc159e305488d1b7d72dad2，采样间隔10000×100ns，无遗留诊断进程。旧CPU/CSwitch失败验收SHA原样保留。tests_result01.json记录226项不同测试，Mac通过221项、跳过5项Windows专用测试；这5项按windows_unit_plan01.json另在Windows实际通过，日志见windows_unit01.log。合计226项均至少在适用平台通过，没有把导入的同一测试类重复计数。构建均在Windows以/W4 /WX通过。

本阶段尚不允许定量现场归因。FIELD_STANDBY.md是未启动的现场草案；现场20次读取与离线8次读取不是同一个负载资格。用户回来前不启动任何人体/设备任务，不部署自动开启正式程序的入口。准备好的控制、归档、原始数据离线复核流程可以复用，但实际GUI/视觉/SDK并发负载和3%扰动门槛仍是缺口，不能靠新增人体轮次绕过。

| 阻塞/耗时位置 | 对应代码或边界 | 证据等级与候选来源 | 缺失证据及最小验证 |
| --- | --- | --- | --- |
| 原现场消费者重新获取GIL | PyEval_RestoreThread→take_gil；原链DeviceQualitySession.on_frame中的array_equal及GroundStabilityFilter._feed中的归约族 | 既有6个在途见证证明等待机制；独立公开入口/机器码及离线调用来源见../native_stack_capture/field_reviews/gil_boundary01/review01.json。没有把离线Python帧补成现场帧 | 同一完整时间括号内的实际持有者完整Python/原生栈、对应batch/contact/pending；实际负载校准后才补证 |
| PySide信号桥进入Python | SignalInstance.emit→Qt→PyGILState_Ensure | 信号桥调用边界已证实；具体信号实例、回调与竞争持有函数仍未知 | 同进程GUI/视觉/消费者/读取线程关联；SDK单独PID，不能把其独立GIL当GUI进程持有者 |
| 新增同步回放慢轮 | 原实现不变的同一接触链 | wall与线程CPU同时增加，新增4轮粗位置/策略元数据已保留；计算、分配、CPU交付差异仍是候选 | 下层实际交付或完整计算栈尚缺；不得用cycles推频率或以策略getter替代实际交付验证 |
| GC事件 | 新增诊断callback时间括号 | 同轮慢/快数据均只有毫秒级单个事件；不构成GC主因或排除分配/释放的证明 | 仅描述这些诊断事件；不改GC，不追溯旧现场，不计算独占GC占比 |
| Qt/系统同步与CPU比例 | 原CPU/CSwitch窗口 | 旧验收仍失败，定量贡献未知；Ready与Waiting必须分开 | 原完整率、PDB、时间/线程/丢事件门槛全部通过后才能定量；无符号内核保留模块+偏移 |
| 测量层扰动 | 本目录固定OFF/ON确认 | 48例协议有效，3%等效/1%精度失败；A/A本底已有波动 | 不追加成功轮、不后验去趋势或剔除；先建立可比较实际负载和足够精度，才讨论GUI与消费链贡献 |

复核A/A（输出必须不存在）：

```sh
/private/tmp/ironjump_stats_20261018/bin/python experiments/gil_observer_noise/analyze.py --raw experiments/native_stack_capture/runs/gil_observer_noise01/off_aa01 --plan off_aa_plan01.json --stage off_aa01 --output /tmp/off-aa-recheck.json
/private/tmp/ironjump_stats_20261018/bin/python -m unittest discover -s experiments/gil_observer_noise -p test_noise_stats.py
/private/tmp/ironjump_stats_20261018/bin/python experiments/gil_observer_noise/confirmation_review.py --raw experiments/native_stack_capture/runs/gil_observer_noise01/confirmation01 --output /tmp/confirmation-recheck.json
python experiments/gil_observer_noise/field_rate01/review01.py --root "$PWD" --raw experiments/native_stack_capture/runs/gil_observer_noise01/field_rate01 --output /tmp/field-rate-recheck.json
python experiments/gil_observer_noise/cpu_delivery_review01.py --raw experiments/native_stack_capture/runs/gil_observer_noise01/cpu_delivery01_diagnostic01 --output /tmp/cpu-diagnostic-recheck.json
```
