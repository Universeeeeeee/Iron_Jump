# 光栅处理优化离线实验结论

本轮完成 E0、E1、E2a、E2b、E3、E4 影子验证、入选候选组合及 Windows 离线复核。实验仅写独立目录和专用 Git 分支；没有修改生产程序，没有 USB／相机／SDK／人体现场采集。

| 方向 | 主要证据 | 本轮决策 |
|---|---|---|
| E1 整帧解码复用 | 真实记录的解码阶段 CPU 降约 93–96%；消费者专用计时未通过收益门槛 | 作为读端候选保留；不把读端节省归为消费者提速 |
| E1 逐段差分 | 高频全变化压力输入的解码成本明显退化，未胜过简单整帧复用 | 不选入组合 |
| E2a 质量窗口贡献抵消 | Mac 跑／走消费者 CPU 降 6.12%／9.44%；Windows 三输入复核跑／走降 3.58%／2.44% | 语义等价、计算有收益，幅度依赖平台 |
| E2b 严格结算空场路径 | Windows 空场省 15.57%，真实跑／走只省 2.88%／1.36% | 主要降低空闲期成本 |
| E3 稀疏簇缓存 | 簇提取变快，但 Mac 完整消费者在走路记录中退化 13.07% | 未通过整体收益门槛，排除组合 |
| E4 单向退役 | 七组撤销反例通过；未证明能节省足够的独占 CPU | 仅影子标记，不启用实际退役 |

## 组合结果

组合为 E2a + E2b，并保留 E1 作为单独读端缓存。稀疏簇缓存和实际米段退役未加入。

Mac 的消费者专用计时排除读端解码，空场省 22.23%、稀疏遮挡省 9.92%、跨段省 12.18%；真实跑／走仅省 3.35%／3.70%。收益不能简单相加。119,330 次逐帧对照一致；423 项领域回归通过，零失败、零错误、零跳过、零未捕获 Qt 回调错误。

## Windows process + batch40

仅用固定保存走路数据和 JPEG 录像，组合启用 E2a + E2b；解码缓存不在 GUI 对照中。原版／候选各四轮，按 AB、BA、AB、BA 执行，先另做两次不计分校准。

- 每轮均解码 741/741 个到期 JPEG；因最新帧预览机制，实际显示约 627–632 帧。无姿态推理／SDK 负载。
- 候选 P95 118.03–122.30ms，最大≤124.28ms；含排队和在途 batch 的未完成帧上界 78–92，数据龄增长斜率门槛通过。
- 完整原始输入、归档、报告、质量窗口、候选、事件与时间线一致；三处主机准备时间单独核对来源再排除跨进程差异。
- 四对 P95 改善分别为 18.54%、−0.78%、1.45%、−1.05%，中位数仅 0.34%。未达到至少三对改善且中位数≥20%的稳定提速门槛。

因此：本轮证明了部分计算成本可减少，且所测离线组合可以保持测量语义；未证明稳定改善端到端延迟、消除历史积压或改善消费者等待/GIL/调度问题。绝对时延达标不等于相对提速成立。

GUI 使用 PyQt5 5.15.2 offscreen，统计终点是 Qt 绘制返回，不能当作实际屏幕呈现、真人准确率或完整现场负载验收。未扩展设备等间隔 GUI／更多负载／真人矩阵：已完成的原到达节奏对照未通过稳定提速门槛，候选继续保留在实验分支。

## 证据和复现

- E0_RESULTS.md、E1_RESULTS.md、E2a_RESULTS.md、E2b_RESULTS.md、E3_RESULTS.md、E4_RESULTS.md：各单项结果；旧串行计时口径修正见 CONSUMER_SCOPE_CORRECTION.md。
- COMBINED_RESULTS.md、combined_correctness.json、combined_consumer.json、regression_combined.xml：组合等价和性能证据。
- E5v2_E2a_RESULTS.md、E5v2_E2b_RESULTS.md、E5_GUI_RESULTS.md、E5_GUI_audit.json：Windows 原生和离线全链路证据。
- manifest.json、input_package.json、combined_tooling_manifest.json：源文件、输入和测试工具 SHA；baseline/ 为冻结源码，inputs/ 为保存输入。Python／NumPy／Qt 等外部依赖需要目标环境提供。
- final_verification.json、native_windows/cleanup.json：本地 126 份生产源和输入不变；Windows plan16 生产 SHA 不变，16 个记录的实验 PID 均已退出。
- publish_ledger.json：各实验独立提交和推送记录。

复现 CPU 计时：项目 Python 执行 `consumer_bench.py one <case> baseline <output.json>`；组合版本另设置 `IRON_SPARSE_FEATURES=runtime,idle,decode_full`，将 variant 换为 `combined`。`consumer_bench.py combined combined` 执行四对完整矩阵。逐帧检查用 `per_experiment_checks.py <label> <variant>`，领域回归用 `regression.py <variant>`。所有脚本位于本实验目录；Windows GUI 入口要求保存 fixture 且拒绝物理设备构造，使用前须核对硬编码目标路径和 SHA。

未合并生产。后续若要判断剩余停顿原因，应继续围绕实际消费者执行／等待区间取证；这些计算优化本身不能给出等待原因。
