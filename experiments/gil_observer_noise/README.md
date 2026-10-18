本阶段基于c48d0cc，在用户离场期间仅做隔离、无设备的原Walk接触链回放。正式程序、原NumPy、滤波、Processor、线程及绘图未改；没有人体、USB、GUI/视觉/SDK、Run或优化A/B。所有新计划独立冻结，旧失败、锁、15%硬门槛及CPU/CSwitch闭合验收不变。

先做A/A，再评估工具偏置。OFF/OFF与ON/ON各预声明8对（16个新进程回放），不同区块只作为相关终点，不冒充额外独立样本。两组都已完成，原始流/输出/源SHA/时钟/保留句柄/GetThreadTimes/cycles核对通过，归档SHA见*_transport.json。原始证据被忽略于experiments/native_stack_capture/runs/gil_observer_noise01。

现有20Hz工具完整读取括号中位3.8517ms、最大7.0537ms；恢复后符号处理最大125.92ms。括号不等于GIL持有/等待时间，不能用这些数值直接推导原现场根因。新候选不改二进制（SHA02e367c7ca0b1cda5f1067b03125a770a502f10fcabb99fa5925b4265050d615），仅改为250ms/4Hz、回放8次；更少采样牺牲见证密度，不能因此放宽栈闭合和时间关联要求。

A/A已揭示测量噪声：

- OFF/OFF整段成对log比值SD约3.23%，一对整段差约5.62%，首个1000输入区块差约26.55%。没有采样器也有大区块波动。
- ON/ON整段成对log比值SD约1.45%；其整段95%家族同时区间约[-2.44%,+1.66%]。
- 这些区间是whole-pair log比值Student t、10个预声明终点Bonferroni家族95%区间，依赖适用的独立性/平稳性，不能当作无分布假设保证。完整数值和漂移筛查见off_aa_result01.json、on_aa_result01.json。
- 因此旧+15.6007%区块超限仍保留为失败，但不能将它全部指认为采集器开销。A/A先回答自然/协议波动，OFF/ON才衡量加入采集后的变化。不得用后验去趋势、剔除异常、cycles归一化或重复取成功窗口掩盖波动。

statistics_plan01.json在结果分析前冻结终点和规则：新目标3%家族等效区间，另保留每个原始试次/区块绝对变化<=15%的硬限制；不能平均掉既有坏窗口。目标同时log区间半宽1%，从两组A/A估计方差，一次选择8–24对，不能中途加轮。precision_decision01.json选择24对上限，但预测精度仍不足，达到上限并非通过。

confirmation_plan01.json是一次固定24对OFF/ON确认，顺序交替平衡。A/A有7或8次读取完全落入ROI；确认组在target go后等20ms再启动采集，并要求8/8完整括号都在ROI。目标/二进制/频率/样本数不变。ON A/A只作为该相位的近似规划先验，确认组区间用自己的完整成对数据，不能声称两个启动相位完全匹配。确认期间不另起助手的Windows状态/归档/测试进程，进度仅由现有控制器在每个回放完成后输出；普通系统背景未受控制。A/A阶段曾有助手状态/归档活动，不能把其方差当成纯硬件本底。

gc_plan01.json另冻4个OFF诊断，用预分配数组记录稀少GC start/stop事件，不禁用GC、不强制收集、不改阈值。原链完整输出核对通过。新增回调自身未做扰动资格认证，可能影响GC调度；不能回溯解释旧慢窗口，不能将callback括号当作独占GC CPU成本。gcreview仅配对原始时间/线程/代际事件。所有诊断与确认组顺序执行，不并行争用Windows负载。

统计分析依赖单独的临时环境/private/tmp/ironjump_stats_20261018，版本固定于stats_requirements.txt；没有安装进项目/Windows程序环境，没有更换正式NumPy。

本阶段尚不允许定量现场归因。FIELD_STANDBY.md是未启动的现场草案；field_rate01和cpu_delivery01中的准备源只有独立冻结/实际验证后才能形成资格结果，文件存在不代表通过。用户回来前不启动任何人体/设备任务，不部署自动开启正式程序的入口。

复核A/A（输出必须不存在）：

```sh
/private/tmp/ironjump_stats_20261018/bin/python experiments/gil_observer_noise/analyze.py --raw experiments/native_stack_capture/runs/gil_observer_noise01/off_aa01 --plan off_aa_plan01.json --stage off_aa01 --output /tmp/off-aa-recheck.json
/private/tmp/ironjump_stats_20261018/bin/python -m unittest discover -s experiments/gil_observer_noise -p test_noise_stats.py
```
