# 实际队列测量已补齐；负载重复性未通过，停止在 A/A 之前

本轮完成测量修正和无人后台负载检查，未实施新性能优化，未运行新的 A/A 或 A/B，暂不建议移植已有 `beam_layer` 候选。补回真实 USB 采集后出现持续积压，但同一条件三轮中走路仅 2 轮、跑步仅 1 轮达到预先冻结的代表性负载门槛；不能挑选严重积压轮次继续比较候选。

分支 `codex/ground-backlog-measurement`，基于 `3020bb1`。Windows 原生 enabled GUI；固定原始光束与 MJPEG 是主输入，真实 SDK 全身追踪和实际关节点/骨架绘制保持开启。用户重新连接设备后，执行无人光束后台采集，没有进行真人走跑。正式程序、原 NumPy、滤波、Processor 和绘图候选均未修改。

## 修改与验证

- 新增实验 `queue_probe.py`：实际待处理队列深度、最老待处理帧接收年龄、批次及弹出/消费交接状态。L/P 共同约每 64 sample 桶记录一次完成快照，包含 EOF；P 额外约 10 Hz 后台采样。没有逐帧计时或嵌套阶段计时。
- 排空改为最后有效接触计划到达之后，首次观测到 pending 与批边界 outstanding 同时为零；短时完成年龄峰值另报。未观测的排空转变/峰值可能被跳过，必须看采样间隔。定义、资格和 A/A/A/B 门槛见 [plan.json](plan.json)。
- 栅栏控制的原 inbox 单元检查在 Mac 和 Windows 均通过，覆盖弹出后尚未 consume、空 deque 中仍有在途批次、并发到达和队首时钟、最终真空状态及采样线程关闭。初次功能检查发现同一 64 sample 桶内 EOF 完成点可能遗漏，已在任何新 A/A 前补齐并加入回归检查；原功能检查记录保留、不进入性能资格统计。
- 新增四种真实 GUI 负载及独立输出保存。固定回放、相机原生采集、相机原生录像先各测走路/跑步一轮；之后增加原 UsbWorker/DLL 实际读取、解析、组帧，走路/跑步各三轮。没有消费者 sleep、重复推理/解码、阈值调整或包格式压力伪造。
- 本地对 **12 轮有效负载检查**逐轮重算，原始 bits/wire/validity、sample/frame counter、drop、stream/flags、完整原始归档、事件 audit/timeline/mirror、质量历史、runtime/window、完整报告及脚印发表集合均与独立原 NumPy oracle 一致。仅核对后归一化两处自检接收时钟。9 个走路/8 个跑步既有发表脚印保持原样，计步正确性不在本轮处理。
- 458 个基线文件及全部复制输入哈希无变化；A/B renderer 哈希未变，沿用上轮 Mac/Windows 各 **1152/1152** 精确像素证明，见 [retained_pixel_proof.json](retained_pixel_proof.json)。这些证明不代表性能校准已通过。

Mac 与 Windows 独立复算结论一致，2272 个数值叶子的最大绝对差 6.06e-12；浮点容差只用于指标复算，原始数据、报告、质量和像素均要求精确相同，见 [reanalysis_check.json](reanalysis_check.json)。

所有变化仅在新增实验目录；[README](README.md) 解释字段、限制及执行方法，[runtime_source_check.json](runtime_source_check.json) 核对 13 个成功 GUI 运行（含一次独立功能检查）的实际加载源文件与归档版本。源版本保存在 `harness_versions/`。

## 受控负载结果

下表为密集阶段共同采样点指标，年龄斜率单位 ms/设备秒；排空为最后有效接触计划到达至首次真空见证的时间，不能解释为精确排空时刻。均为原绘图器 A、探针 P，**不是候选 A/B 收益**。

| 负载 | 走路消费 fps | 跑步消费 fps | 代表性持续不足 |
|---|---:|---:|---|
| 固定回放 | 996.4 | 1013.7 | 均未达到 |
| 加原生相机采集 | 997.0 | 1010.2 | 均未达到 |
| 加原生相机录像 | 997.5 | 1153.8 | 均未达到 |

原生相机采集/录像这些单轮并没有稳定制造消费不足。超过 1000 的值可能是追赶/窗口边界；录像跑步实际发出 1067.2 fps、年龄斜率为 -109.1，不能当成处理容量提升。正式相机预览选择本来就限于约 30 Hz，之前回放约 25 Hz，主要缺失项不能概括成“预览没有运行 100 fps”。

下表是再补回真实 USB 后台采集、同时保留原生相机录像的完整三轮；同一 profile 两模式均须三轮全部通过，规则未调整。

| 模式/轮次 | 消费 fps | 实际发出 fps | 年龄斜率 | pending P95 | 最老 pending P95 ms | 脚印 P95/max ms | 排空见证 ms | 资格 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 走路 1 | 463.2 | 999.5 | +963.9 | 15208.7 | 16449.8 | 16173.3 / 16262.2 | 18045.9 | 通过 |
| 走路 2 | 982.3 | 999.9 | +12.8 | 152.8 | 141.5 | 230.6 / 239.0 | 116.2 | 未通过 |
| 走路 3 | 938.5 | 999.4 | +19.2 | 495.4 | 458.9 | 561.0 / 577.6 | 113.8 | 通过 |
| 跑步 1 | 949.4 | 997.4 | +83.9 | 359.7 | 371.1 | 362.3 / 366.5 | 678.6 | 通过 |
| 跑步 2 | 1020.2 | 1250.4 | +112.0 | 955.5 | 946.1 | 945.4 / 948.8 | 1242.9 | 未通过 |
| 跑步 3 | 1001.0 | 999.4 | +42.3 | 176.7 | 177.8 | 171.4 / 172.3 | 804.8 | 未通过 |

跑步 2 虽有显著积压，未满足冻结的消费 <970 fps 条件；不能把“未通过代表性资格”写成“没有积压”。其密集输入线程迟到 P95/max 为 **462.8/601.9 ms**，随后追赶使实际窗口发出约 1250 fps。这是主输入交付节奏发生变化的证据，不能与均匀 1000 Hz 的吞吐容量混用。走路 3 源迟到 P95/max 亦达 182.3/418.7 ms。逐阶段数据见 [source_cadence.json](source_cadence.json)。这些事后诊断没有替换门槛或删除轮次。

完整结果与空场/混合阶段、吞吐缺口、队列面积、采样最大间隔、后接触完成年龄均在 [final_results.json](final_results.json)、[final_results.csv](final_results.csv)、[final_phases.json](final_phases.json)。相机回调、writer、SDK 调用及骨架绘制证据随每轮结果保存。

## 无人真实采集是否有效

设备重新连接前曾启动失败：原 UsbWorker 打不开 VID `04B4` / PID `1004`；独立 Windows PnP 查询当时无设备，且无其他 Python 占用。保留失败目录 `runs/scout_hardware_walk/`，不计入有效检查。重新连接后的目录使用 `_connected` 新名称，不替换失败记录。

六轮后台采集共保留 **282365 帧**、768 束真实光束原件。全程接收均速约 999.99–1000.00 Hz；所有 sample 连续、drop 为零、无 acquisition issue，bits 与 wire 反解一致，stream 身份一致；原 DLL 哈希与诊断分支原件一致，见 [post_reanalysis_device.json](post_reanalysis_device.json)。停止后原 worker 的 discard gate 生效且设备已关闭。实际空场帧每帧接触位中位数为 1、最大 2，不能把这些静态遮挡自动当作真人接触。见 [native_usb_recheck_final.json](native_usb_recheck_final.json)。

同时真实相机回调正式阶段约 97.57–100.03 fps，六轮 writer drop 均为零，原始 MJPEG/CSV 的字节数、SHA-256 保留于各轮 native 结果。相机拍摄内容与归档预览不同；未证明二者图像压缩负载逐帧相同。

Python 组帧接收时钟存在数百毫秒到秒级间隔，帧计数仍连续。它说明 Python 可见交付不均匀，**不能证明 USB 总线停顿或 GIL 单独负责**；需要原生读取时间线和线程调度证据交叉验证。

## 按证据排序的判断与剩余假设

1. **确认：旧“排空”观察存在缺口。** 新 12 轮共观测到 **338 次** pending deque 已空但仍有未完成批次/交接的状态。旧连续低年龄判据又把短时峰值混入恢复时间。现在有实际队列和批次证据，但新 P 的增量扰动尚未通过 A/A 校准，不能宣称测量已零扰动。
2. **强线索：原生 USB 采集是此前回放缺少的重要竞争负载。** 补回后能出现明显持续积压；仅相机采集/录像六轮未达到资格。但这不是交错、已校准的单因素因果实验。真实 USB 帧另存、归档主输入继续构造/发信号，与现场同一 USB 流直接进入主算法的拓扑有差异，不能将全部损失归因于 USB 解析。
3. **确认：输入线程交付节奏本身会迟到并追赶。** 跑步 2 的 1250 fps 和迟到证据说明消费 fps、pending 和上游源迟到要同时看；输入端尚未交付的帧不属于 inbox pending。缺少该分离会产生“消费已达 1000，为什么还有积压”的错误解释。
4. **未决：独占计算、GIL 竞争和 Qt 调度各占多少。** 当前没有线程 CPU/ready-to-run 或 GIL 持有栈，不能从共同年龄曲线推算这些占比，也不能用微基准替代。相机回调/原生录像、USB 解析/组帧、主输入线程、GUI/推理/SDK 的竞争以及运行次序/预热均仍是待验证因素。

本轮没有足够证据更改 DeviceQualitySession、GroundStabilityFilter 或 Processor，也没有证据证明 `beam_layer` 缓存能改善该竞争场景。

## 下一步

保留现有 `beam_layer` 候选，暂不移植。下一轮最小工作仍是诊断：先固定预热和交错顺序，检查计划到达/实际发出/实际完成三条时间线，并用独立原生线程 CPU 与调度证据判断严重波动来自哪里；新增探针先做低扰动 A/A。随后在真正稳定的到达节奏下冻结资格再试 A/B，不用人为降低消费者速度制造空间。

若需要验证现场拓扑差异，应另开现场阶段，让单一真实 USB 流直接进入原链路并保留原件，再与固定回放的输入迟到、收包/组帧节奏、相机回调字节率对照。当前授权的无人后台采集已完成；本轮未要求真人重复通过。

现阶段最值得保留的一个最小性能候选仍是原 `beam_layer` brush/pen 状态缓存；没有新证据支持换成其他优化，更不支持引入 Numba、C++、多进程、微批量或算法阈值变更。

## 证据与清理

- [final_audit.json](final_audit.json)：Windows 两个本阶段任务均 result=0，无活动实验/SDK Python；本轮任务已注销；458 个正式源文件、复制输入哈希全部一致，A/A/A/B 目录数为零。较早阶段审计 [post_run_audit.json](post_run_audit.json) 保留原件。
- [plan.json](plan.json) 与原 `harness_versions/scout_v2/plan.json` 比较仅新增 hardware profile 和修订说明；队列定义、资格、A/A、A/B 门槛未改。初始六轮摘要 [scout_results.json](scout_results.json) 保留当时设备缺失状态；最终结论以 [final_results.json](final_results.json) 为准。
- [final_evidence_manifest.json](final_evidence_manifest.json) 保存本地原始输出、oracle 和日志的字节数/SHA-256。全部输入与现场旧证据不覆盖；旧删除的跑步记录未使用。
- Windows 完整现场后台原件：`E:/OptoJump/IronJump-ground-backlog-measurement-20261016/experiments/ground_backlog_measurement/runs/`。较大原生相机视频留在各轮目录；本地保留完整光束原件、主输入光束和输出元数据；主输入相机原件保留于 Windows。
- 本地：`/Users/vae/.codex/worktrees/ground-backlog-measurement/Iron_Jump/experiments/ground_backlog_measurement/`。
