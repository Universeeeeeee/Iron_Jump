# 有界输出接入原测量actor：数据保全有证据，原父验证队列仍失败

将 `bfb0f29` 的输出组件接入新的实验actor，保留旧版文件、计划和窗口。只执行固定3个保存输入场景：正常完整会话、started后关闭父端通道、started后父端固定停读15秒。没有模型、GUI、SDK或USB，也没有优化A/B。

## 实际结果

| 场景 | 原父验证器判定 | actor实际行为与保全 | 尚未证明 |
|---|---|---|---|
| normal | contract_pass=true | 33188帧入口、29687帧正式数据；完整原report/state/raw与GUI基准一致；688条实际消息有序收齐；reader/QThread/writer停止，actor退出0 | GUI并发吞吐、真实设备 |
| peer_disconnect | contract_pass=true（预定故障处理） | 会话complete=false，actor退出1；入口3507帧，正式接受4帧，报告/质量/原始档案本地保存，reader/QThread停止；未声称父应用收到 | 强制父进程死亡和完整部分报告算法oracle |
| parent_stall | **contract_pass=false**，父poll抛BrokenPipe | actor先因128条上限进入失败，停止测量并保存入口10077帧/正式6575帧；报告、质量状态和128个未确认包保存；actor退出1 | 原父验证器没有完成停读分支验收，writer停止确认也保留false |

停读数据的 `accepted_resident_messages` 峰值128，字节峰值727168，均未越过128条/8MiB上限；在途包被计入。normal报告较大，接受字节峰值4654380，仍低于8MiB，不能据此声称任意会话报告都能放入此限额。

故障窗口report.finish_reason为 `ipc_transport_failure`，不是普通正常结束。原先“只有complete才保存report/state”的条件已在本实验版改为“只要原报告生成就本地保存”，避免输出失败导致证据也被跳过。raw入口和已接受原始档案分开核对，停止冻结后到达的尾部仍保存，不混入已接受计数。

## 完成和清理不再混为一谈

生产者只序列化、入有界队列，writer负责写Pipe；首次故障由主事件线程观察，并通过原controller.stop或discard有序停止。命令端EOF也显式abort输出，不能因writer暂未报错而宣布成功。Qt回调中的后续输出失败不会把会话恢复为正常状态。

`payload_end` 仅表示生产者数据结束，明确带 `transport_unconfirmed=true`；它不是成功确认。正常父端必须实际接收序号和report、确认actor退出0及本地完整状态之后才能通过。组件自身始终不把“写入调用返回”当作应用接收证明。

停读窗口写出记录时，writer仍在未返回的原生写中，因此 `writer_stop_confirmed=false` 和未确认快照原样保留。随后actor进程实际退出，collector确认无活目标，不覆盖此前writer未确认状态，也不删除锁。原reader/QThread确实停止，与输出writer是否确认是不同结论。

## 原验证器错误与修复边界

原 `parent.py` 只在recv处捕获管道关闭，Windows关闭通道后也可能直接在poll处抛BrokenPipe。因此它在恢复停读后报错，原 `runs/status.json` 保持complete=false，原停读case也保持contract_pass=false。该错误和全部文件保留，没有重跑或延长15秒停读来替换结果。

`review01.py` 从原始档案独立核验正常全量语义、两个故障窗口的入口前缀/已接受档案、原资源退出及未确认包SHA。它保留 `original_validation_cohort_pass=false`，不把独立观察当作原队列通过。

未来版 `polling.py` 同时处理poll/recv的EOF或OS错误，解码/数据异常仍失败；`parent02.py`仅是待后续计划绑定的修复源码，要求尚不存在的新计划和凭据，不能使用旧门禁重跑。原运行源SHA不变。修复后本地和Windows各24项测试通过（含实际原生关闭管道），未启动新actor窗口。

## 预检与归档

原运行前本地/Windows各19项测试和源码/输入/oracle/原生库检查通过，另行核对原Python及NumPy二进制哈希。窗口执行后collector确认无目标进程、原reader/QThread退出、458正式文件及原依赖/输入/oracle/库未变，WPR未记录，采样间隔10000×100ns。

173文件归档逐项SHA核验，SHA256：`f4f740f82ac7fe14d560803a427d90a874896bd67b1032f2358361a930c3c11b`。7把锁、所有原始npz/消息及未确认包保留在本地/Windows，仓库提交代码、计划、失败状态和派生复核。

## 下一步

先用已有故障窗口建立完整部分报告的原实现离线oracle，再准备GUI代理属性/时钟/SDKready握手与实际界面负载。当前只有端点断连，不是强制GUI父进程崩溃试验；故障安全观察没有解决原Walk积压，也没有提供GIL等待或CPU责任份额。后续GUI验收仍要求1000Hz pending、接触至绘制以及严重基线可复现，旧质量门槛不能放宽。

没有人体、USB、Run或正式程序改动。根因及正式修复目标未完成。
