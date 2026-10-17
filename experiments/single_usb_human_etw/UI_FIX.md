# 第一轮 OFF 的界面故障与修复

现场样本 `20261017_110109_a6595b80_walk_off` 保留原样，排除于修复后的人体 OFF/ON 校准基线。原始正式档案 45,705 帧，包含准备的 SensorFrame 96,480 帧；录像 8,661 帧、1,304,384,653 字节、writer drop=0。完整报告 touch_count=10，仅报告原值，未与人工步数核对。

`field01_archive_audit.json` 验证设备/帧计数连续、wire 与 bits、原正式档案与 retained frames、事件顺序、质量历史及报告 audit 一致；最终队列排空、USB reader 为空、SDK 停止。录像 CSV 帧/字节/偏移完整。正常 complete 标记缺失，controller_result 保留失败状态，没有伪造成功标记或修改原报告。

两个缺陷位于新增的实验 HumanRun：

1. operator_clear 之后，原 progress 保留尾段文字；新增状态每秒在现有 banner 后追加，导致顶部区域增长。现先取独立的阶段文字，再替换唯一一条骨架状态；尾段空场不把无骨架标为异常。
2. close event filter 无条件忽略窗口 Close，包括程序自身退出时的关闭请求，导致 app.exec 无法正常返回。现 self.closing 时放行事件；用户主动关闭仍先请求采集/SDK 清理。

前一版硬件隔离 UI 检查只调用 processEvents，没有真正运行 app.exec，遗漏了退出问题。新增 check_ui_regression.py 在实际事件循环中触发取消并验证退出，另外连续执行 40 次尾段更新，核对行数和高度。旧版在 Windows 离屏环境复现：40 行、标签 37→817 px、只能被测试超时强制退出；修复版：1 个换行、固定高度、正常返回 0。原 11 项协议检查与启动只读检查继续通过；另保留 Windows 实际桌面的回归结果。

按现场反馈，将不显眼的勾选文字改为有边框、可切换的确认按钮：未确认时蓝灰底“点击确认”，选中后绿底“已确认”，再点可取消；开始握手后仍锁定确认状态，USB/录像/全身/骨架检查不变。

仅改实验 human_runner.py 的提示、确认控件与 Close 处理，更新本轮冻结源清单。原 field_runner.py、QueueProbe、原 NumPy、正式代码、ETW profile、原生边界 CPU 观测和算法参数不变。旧运行源保存在本地 harness_versions/field01/ 及 Windows 样本 sources_at_capture/，仅供存档，不作为独立启动入口。

第一轮保存/SDK/USB teardown 均已确认后，仅结束其仍挂起的 GUI PID 10508；外部 controller 据实记录失败并释放锁。退出状态与原始数据分开保存。本轮没有启动任何真实 ETW/USB 新试验，回归检查均拦截设备入口。

下一次请重新从 WALK-ETW-OFF 开始，再 ON→ON→OFF。旧轮次保留为故障/正确性复核证据，不能因档案完整就将变化过的 GUI 工作负载当作修复后匹配基线。真实吞吐及人体负载结论仍待四轮数据检查。
