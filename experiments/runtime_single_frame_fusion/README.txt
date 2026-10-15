单帧数值融合实验

目标：比较原 NumPy(A)、单帧融合且保留 GIL(B)、同一融合函数且释放 GIL(C)。
正式程序不默认启用任何候选。所有替换只在本目录的实验入口中发生。

先读 results.txt，再读 gui_runs.csv；gui_summary.json 保留各轮及配对指标。
trial_plan.json 和 trial_plan.sha256 是正式性能测量前冻结的采用规则。

基线单独保存为实验分支的第一条提交。baseline_manifest.json 记录旧验收归档与实际叠加源码。
prepare_baseline.py 是归档重建工具，已有基线时拒绝覆盖；不要在已有实验目录重复运行。
source_reference.json 记录原目录路径与制定计划时的参考文件哈希。

环境：与测试记录一致的 Python 3.11、NumPy 2.4.6、Numba 0.67.0、qtpy/PySide6。
Numba 只用于实验；正式 requirements 未新增依赖。

功能检查：
  QT_API=pyside6 QT_QPA_PLATFORM=offscreen python experiments/runtime_single_frame_fusion/check_equivalence.py
  QT_API=pyside6 QT_QPA_PLATFORM=offscreen python experiments/runtime_single_frame_fusion/run_tests.py B
run_tests.py 的 A/B/C 参数在独立进程中使用；同一组生产回归测试用于三个候选。

Windows 回放：windows_run.py 将独立目录部署到已授权的 Windows 主机，使用登录桌面的临时任务。
deploy/checks/aa/trials 分阶段运行，目标目录和任务存在时拒绝覆盖；当前目录已完成，不能原地重跑。
复现实验需使用新的输出目录及任务名，并保留本轮原件。
gui_probe.py 预热两个内核后新建会话；fixed_replay.py 是原已核对入口的冻结副本。
analyze_gui.py aa 和 analyze_gui.py trials 先核对原始帧、完整报告与执行源，再计算指标。

数据及证据：
两份近期真实录制、六份历史资料、旧完整报告 oracle、逐轮原始帧/报告/截图以及全部日志保留在工作区。
大型输入、oracle、逐轮原件及压缩包作为本地实验资料，不重复加入本目录的源码提交。
源数据位置及哈希见 source_reference.json、baseline_manifest.json 和逐轮 provenance/probe 文件。
独立工作区内 exports/ground_boundary_latency_20261014/field_run_20261015_02 和 field_walk_full_02 为冻结输入副本。
Windows 媒体来自旧隔离目录的既有录制，复制后核对哈希；不打开真实相机或 USB。

长测入口：prepare_stress.py、long_trials.py 只在候选同时通过两个短窗门槛后使用。
它们不改变采样状态机或正式缓存预算，循环输入标注为合成压力数据。
是否实际执行以 results.txt 与 long_*_summary.json 为准；源码存在不代表通过长测或现场验收。

已保留部署初期缺少测试依赖的失败日志；本地首次命令中的测试文件名已纠正，最终 Windows 通过记录使用 tests2_A/B/C.log。
观察指标不等同于全进程 CPU，也不等同于物理屏幕呈现；每轮仅有 7 次触地。
