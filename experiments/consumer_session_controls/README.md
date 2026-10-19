# 会话命令与通知交付：三种原场景已覆盖，首队列记录失败永久保留

保留 `8de0fe6` 的原始成功交付，新实验扩展父命令stop/discard与其余原GUI通知信号。actor仍调用原SessionController及同一原处理链，没有改正式源文件、DirectConnection、滤波/Processor、Qt线程结构或坏束规则。

## 已验证事实

| 原定场景 | 执行及验证结果 | 限制 |
|---|---|---|
| 完整输入＋Walk pause/resume | 实际处理33188帧，完整report/quality/runtime/raw与既有GUI严重窗一致；pause/resume原方法保持无操作，明确返回unsupported；父stop确认对应命令5且真实资源已停止 | 首次父状态JSON记录失败，原队列仍failed；由原始档案独立复核核心事实，不修复旧状态、不重跑首窗 |
| 提前父stop | 输入9576帧为原输入精确前缀；接受至sample54975，正式接受6072帧，report raw计数/档案哈希一致；冻结后额外到达3帧也保留在入口档案中，未混入报告 | 已验证接受/冻结/存储边界，尚未建立独立的完整部分报告算法oracle |
| 准备后父discard | 3501帧预检前缀保留；无started和report，reader/QThread实际退出后才确认discard完成 | 保存Source的arm等待最终超时信息保留，不是生产USB停止时延验收 |

stop与discard不再以调用返回或controller清空引用作为完成依据，必须同时确认reader与原QThread停止，再发command_completed。各确认的command_sequence与父发送记录一致；报告数据和terminal在完成确认之后。

原Walk是单次物理通过，pause原本被忽略。这里没有新增暂停功能，也没有把无操作伪装成暂停成功。Walk pause/resume仍调用原方法并核验状态不变，父得到unsupported/applied=false。

## 通知覆盖

保留readiness、visual、snapshot、started和report值；另绑定原9类通知：hop、jump_quality、gait_step、device_message、device_state、device_layout、led_health、beam_quality、pause_state。每个回调保留原参数并以有序消息传出，最终报告前排空既有Qt转发。

本轮实际收到的新增通道是device_layout_changed、device_state_changed和beam_quality_notice。其他零出现通道仅有绑定测试，**不能称为真实硬件或其他模式的路径验收**；没有运行Run或其他模式。首完整窗693条实际消息，提前停止214条，丢弃89条，序号与actor PID均独立核验。

## 必须保留的首次失败

`plan01.json` 原预算三场景。首场景原始处理、退出及语义检查走到完成，但父finally写status时，保存的quality_key含DeviceLayout，默认json.dump失败，status.json被截断。外层队列停止，`runs/status.json`仍为complete=false，另外两个场景未启动。这是本次实现的记录层错误。

原始截断字节、失败源码/计划、锁及所有窗口文件原样归档。`review_first01.py` 不读取被截断状态来宣布成功，而从实际actor档案、消息、报告和真实GUI参考独立复核。`first_review01.json` 明确保留cohort_gate_remains_failed=true。

`json_values.py` 只修复证据JSON表示：用带原类型名的dataclass字段值表示DeviceLayout/BeamQualityPolicy，未知对象拒绝，不静默转字符串。**实际IPC仍传原始类型值，未把quality_key改成JSON字典。** 回归测试使用实际形状的8段启动键验证可记录，且原对象不变。

新 `plan02.json` 只执行原来未尝试的early_stop与discard_ready，写全新runs02；它绑定同一个actor源码SHA，父控制器仅新增JSON记录处理及新计划/目录选择。没有再次运行完整场景以替换失败，也没有把旧队列状态改为通过。

## 源fixture的取消限制

discard在ready边界取消，原保存Source正等待arm_ready；原stop只join有限时间，reader要等原arm等待结束才退出。actor没有伪造armed或提前清锁，而是继续等待真实reader退出；`source_arm_error='Arm/SDK readiness timeout'`如实保存在结果中。功能终态确认通过不等于这段fixture适用于低延迟生产取消。后续真实硬件/GUI接入需要另验取消与失联条件。

## 校验与保全

第一次Windows7项前置测试通过；记录修复后本地与Windows各9项通过，覆盖unsupported不伪造状态、状态漂移拒绝、stop不提前确认、运行中discard拒绝、活reader阻止完成、全部通知绑定、真实Qt排队转发及实际启动键JSON回归。源码、输入、原oracle和原生库哈希在各次启动前核验。

第一失败归档22文件SHA：`fde09ba7da5efd4c43241f9ec20e0a04aeb21bd39b0dc37626179852b67bf020`。第二归档47文件（包括旧失败原字节）SHA：`e7f41c0707edb0bcabbf3f18538c93c759d29a44f3a7b393d19ca010b125535a`。独立本地复核逐项哈希、输入前缀、报告/档案边界、消息顺序和命令确认。8把锁全部保留。

collector确认无目标进程，reader/QThread均停止；458正式文件、依赖、原输入、oracle及原生库未变。WPR未记录，采样间隔10000×100ns。原始npz和消息日志仅本地/Windows保留，提交代码、计划、审计与派生结果。

## 尚未达到GUI/性能验收

剩余条件是：完整部分报告oracle，父失联/坏命令/输出背压的实际故障与有界缓冲，GUI代理属性与交互时序，以及原GUI＋视觉/SDK负载下的1000Hz pending/contact→paint闭环。当前直接Pipe写仍可能受慢父端阻塞，不能带着这个缺口宣称吞吐保障通过。

本阶段没有人体、USB、视觉模型、实际SDK或GUI性能测试，没有正式程序修改。此前所有校准与候选失败结论不变，根因与正式修复目标未完成。
