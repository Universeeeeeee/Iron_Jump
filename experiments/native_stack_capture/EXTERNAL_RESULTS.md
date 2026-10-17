# 最终外部观察器：校准与验收结果

2026-10-17。沿用 `codex/native-stack-capture-calibration`，基于已推送的 `73e04cd`。仅修改独立实验目录，没有新增分支、人体、Run、正式 GUI/SDK/USB 启动或优化 A/B；原 NumPy、滤波、Processor、绘图候选保持不变。

**等待模式三对合成校准通过；CPU 模式为两对通过、一对未通过，不能宣布整体通过。现场定量归因仍未就绪。** 当前结果以 `external_results03.json` 为准。

## 已补齐的流程

- `split_field.py` 一次执行：起止观察行完整性/PID/TID/creation time 检查、双边 QPC→host_ns 映射、独立 tracerpt 全扫描、分 PID 解码与严格 PDB 地址解析、CPU/cycles 及栈验收、原 ETL 前后 SHA 复核。输出根的 `acceptance.json` 汇总测量质量。单项命令成功或基础 `quality_pass=true` 不再足以表示整个窗口验收通过。
- 起止行数缺失、线程身份变化和旧版单边时钟，原入口都能静默继续，现已用先失败后通过的回归测试复现并修复。全扫描失败会保存失败状态；独立事件数不一致即使基础 quality 为 true，也不能通过。
- CPU 间隔检查现在要求实际 SetInterval 覆盖整个线程计数窗口，窗口内改变间隔会拒绝；不能仅凭 ETL 中曾出现 10 ms 就放行。
- 总体验收与每 PID 报告中的 `quantitative_field_attribution_ready` 继续为 false。现场负载扰动、批次/接触对齐和完整目标调用链仍是额外前提。

## 合成设计与保存

使用两个独立的 Python 合成进程，分别标记 `gui`、`sdk`，各包含两条 CPU/GIL 竞争线程、一条 QWaitCondition 线程和一条系统 Sleep 线程。**这些标签不是真实 GUI/OBSBOT SDK，不构造 QApplication 或设备对象，不证明真实 SDK 栈已验证。** 两进程分别读取和分析，不共享 GIL；进度观察只存在合成夹具内，不注入业务程序。

最终 `record.py --targets` 从进程外保留原生线程句柄，实际读取 GetThreadTimes、cycles、creation time；CPU 10 ms 与 CSwitch 两种模式从不同时启用。各三对，顺序 OFF/ON、ON/OFF、OFF/ON，每窗 6 s。沿用 `plan.json` 的 15% 工作量/CPU/cycles 双向扰动限制，以及原来的 95% 用户栈闭合、20% CPU 采样账本、10% 驻留账本等门槛，没有放宽数值。

工作量使用单调进度在计数起止括号两侧的上下界，只有 ON/OFF 的整个可能变化区间都在 ±15% 内才通过；不以中点抹掉不确定性。父进程与两个子进程分别保存 QPC/perf 锚点，先验证三者映射区间相交，再比较进度。

保留两个完整系列：

1. `external_plan_initial01.json` / Windows `external_runs/`：首次最终观察器系列。OFF 尾部进度证据不足，无法给部分工作量提供上界，整体验收未通过。`external_results_initial01.json` 保存原结果；没有补造进度。
2. `external_plan.json` version 2 / Windows `external_runs_v2/`：仅在停止合成夹具前增加一条窗口结束后的进度快照，测量窗内工作循环、采集器、间隔、缓冲和数值门槛不变；重新冻结后完成各三对。初始分析为 `external_results02.json`；随后只读修正左边界分析，形成 `external_results03.json`，未重采或替换失败 CPU 窗口。

原始数据、旧报告、失败源版本和每次冻结计划均保留。首次 CPU 冒烟另存 Windows `external_runs/cpu_probe01/`；它使用更早的跨进程时钟格式，不列入正式系列。

## 实际交付质量

以下为 version 2 三个 ON 窗口、两个合成进程所有被观察线程的合计；“闭合”只指用户栈到达线程入口，不代表内核栈或所有函数符号完整。

|检查|CPU 模式|等待模式|
|---|---:|---:|
|事件 / 已关联栈|3606 / 3606|29814 / 29814|
|用户栈到达线程入口|3581 / 3606（99.31%）|29705 / 29814（99.63%）|
|未知符号用户帧 / 用户帧总数|29 / 66459|17132 / 666836|
|无法映射模块的用户地址|0|0|
|QPC→host_ns 三进程映射最大宽度|15.0 µs|9.4 µs|
|QPC/FILETIME 最大越界残差|16.5 µs|11.1 µs|
|高 CPU 线程与 GetThreadTimes 最大相对差异|9.35%（采样 CPU）|9.12%（调度驻留）|
|事件/缓冲丢失、独立事件计数差异|0|0|
|三对完整合成验收|2 通过、1 未通过|3 通过|

所有进程的独立全扫描均通过；Python、QtCore、系统等待相关符号仍按精确 PE/PDB 身份解析。无符号内核及包装层保留模块、原始地址和 RVA，不补造函数名。未将调用链见证次数换成 GIL 等待比例或持有者时间。

CPU 第三对的 `sdk` 合成进程 PID **14560** 未通过 `user_root`：`qt_wait` 三个样本仅两个用户栈闭合，`system_wait` 两个样本仅一个闭合，均含只有内核段的情况，也有单列的 NonProcess 样本。全局 99.31% 不能覆盖这些线程自己的失败；低采样数也不足以定量分析等待线程。没有降低分母、剔除失败窗口或补采一轮取代它。CPU 实际 SetInterval、窗口覆盖、样本 IP、账本交叉核验、丢失等其他检查通过。

全部六对、每个进程的工作量/CPU/cycles 扰动界限通过 15% 门槛，这不等于没有扰动：例如 CPU 第一对的工作量变化区间约为 GUI -8.55% 至 -4.63%、SDK -8.85% 至 -4.19%。不能把这种合成结果外推到正式人体积压。

## 调度左边界修正依据

原分析器假设目标线程在 ETW 开始后创建；对录制前就已运行的线程，首条事件可能是切出，原代码将其计为 `out_without_in`。这是外部模式的测量层误报。

`boundary_crosscheck.json` 使用原生 reader 的原始 CSwitch v5 payload，对照独立 GetThreadTimes creation time、ETL header FILETIME 和实际外部计数 QPC 括号。例：首轮等待窗口中 cpu_b 的首个切出发生在计数窗口前约 **455.11 ms**，线程创建也早于 ETL 起点。

新分析只允许**首条、已在录制前存在的线程、切出明确早于计数窗口**这三个条件同时成立时，将其保留为 `schedule_left_boundary_events`；不把这段未知的早期 Running 补入计数窗口。窗口内首切出、内部重复切出、运行中 CPU 迁移仍拒绝，五个回归测试覆盖这些边界。原始 ETL、计数、解码、符号输出和旧 quality 没有修改。`recheck_external.py` 先核对 ETL SHA，再使用同一份独立全扫描和解码输入，只写新报告目录 `split_rechecked03/`。

## 下一次现场的最小操作

现在不需要新增人体数据。正式单 USB Walk 能复现接触样本消费不足和 pending/在途积压后，再按 README 准备新鲜 GUI/SDK PID/TID 清单并做**实际负载**下的两套独立扰动校准。

- 等待模式目前仅通过合成工具校准，仍需实际负载校准和目标调用链闭合后才可讨论定量结果。
- CPU 模式目前没有整体合成验收通过结论。不能用高 CPU 线程的好结果覆盖等待线程的缺栈，也不能直接进入现场定量归因；下一次实际短窗仍逐线程验收，不完整时只保留证据。
- 每个获准窗口采完后执行一次 `split_field.py <window> <new-output>`，读取总 `acceptance.json` 和分 PID `quality.json`。再将其中的有界 host_ns 映射用于对齐原队列批次完成、已消费接触样本与 pending/在途，不能只取输入密集窗或编造逐帧完成时刻。

## 复算与版本

```sh
python -m unittest discover -s experiments/native_stack_capture -p 'test_*.py' -v
python experiments/native_stack_capture/external_report.py <external_runs_v2副本> <新结果.json> --analysis-subdir split_rechecked03
```

Windows 全部 **33** 个工具测试通过；Mac 29 个通过、4 个 Windows 专属测试跳过。没有运行正式程序或 Run 模式测试。

`external_plan.json` 保存录制时的冻结源 SHA，不因录制后的只读分析修正而回写。复算使用该录制计划；若需要再次发起合成录制，应另建与当时源匹配的新计划并使用 `external_calibration.py --plan <新计划>`，不要覆盖现有计划或重用输出目录。

最终交付 SHA、原始证据路径与清理状态见 `external_validation_manifest.json`、`external_evidence_manifest.json`。完整原 ETL 保留 Windows 独立实验根；本地忽略目录保存结构化副本，未将二进制 trace/PDB 加入 Git。
