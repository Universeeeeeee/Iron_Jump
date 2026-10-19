# 完整原测量会话子进程：核心保存输入交付通过，尚非GUI代理或性能验收

延续 `72ed6a5` 的边界审查，独立实验进程运行原 `SessionController`、原QThread、保存Source、原inbox、quality、GaitEngine/filter/Processor、raw档案及原停止/报告流程。正式源文件与DirectConnection均未修改。父进程只接收数据值，当前发送prepare/start两个命令。只执行冻结的一次交付，不追加窗口。

## 实际交付与正确性

父PID23200，测量actor PID6336。子进程使用QCoreApplication，未创建QWidget、打开USB、相机或SDK，也没有视觉负载。保存Source的SDKready标志是明确的交付fixture，不能解释为真实SDK联动通过。

actor完整接收并消费 **33,188帧**，在原checked sample **48903**边界完成预检，再由父命令调用原start/arm_checked。收到保存源EOF后，子进程确认最后样本消费完成，调用原controller.stop('manual')，原freeze/drain/halt/flush、worker/thread退出和report构建仍由原代码执行。

运行中父端收到 **677条** 连续序号、同一actor PID的实际消息：74条readiness、294条snapshot、302条visual，以及actor_ready/prepared/ready_to_start/started/drained_eof/report_value/terminal各一条。Qt转发在最终报告前排空；没有以仅收到报告代替终止确认。父端接收的report值与child保存值相同。

两层验证通过：

1. Windows运行后，与**原有Windows oracle**比较所有输入sample/frame index、bits、wire、valid bits、dropped信息，完整规范化report及完整quality/runtime/audit/timeline/mirror/rawarchive状态完全相同。
2. 本地取回归档逐项SHA核验后，`review01.py` 独立与保留的严重GUI窗口 `pair01_default` 比较同样原始字段、完整报告和状态，仍完全相同。规范化仅删除两处本轮不同的preflight checked主机时刻，不删除事件、质量历史或物理位置。原接收QPC保留且单调，不冒充原历史时刻。

reader确实停止、原QThread的isRunning为false、controller引用已清理、actor实际exitcode=0，之后才记为完成。两把锁保留。此结果证明**核心原会话可放在独立进程中保持当前保存输入语义**，尚未证明吞吐改善、真实GUI输出完整代理或设备效果。

## 原计划边界与尚缺的功能

当前只实现父命令prepare/start；停止是保存源EOF后child内原controller.stop。**父发提前stop、pause/resume/discard还没有实现或验收。** source错误、布局变化、异常退出等真实故障路径也未执行。

当前转发readiness/visual/snapshot、started和report值；设备消息、布局、质量notice、step事件及其他原GUI信号尚未全部接入。677条序号检查证明本次已覆盖通道的有序交付，不证明所有生产信号都已转发。没有GUI、视觉/SDK并发、输出缓冲上限或1000Hz pending/contact→paint效果验证。

下一步只补齐会话命令与必要通知的交付、超时/故障保全及有界输出背压，继续使用保存输入做独立语义门；之后才能冻结真正GUI负载的对照。不能因本次通过就在正式代码重构线程/进程，或把旧GUI/QoS和主动探针失败改为通过。

## 预检、失败记录与证据保全

本地与Windows各5项测试通过，包括消息PID/顺序拒绝及真实QThread join后Qt排队转发的排空检查。启动前源码、输入、既有oracle和原生库哈希验证通过，父端绑定该plan与测试凭据。初次本地构造计划时发现Windows-only oracle未在本地，计划尚未部署、工作尚未启动；保留 `preparation_failure01.json`，随后绑定远端既有oracle SHA，未重建或覆盖基准。

本地独立复核最初按UTF8读取消息日志失败；原parent日志使用Windows默认cp936。只读查询确认cp936/utf8_mode=0后按该编码读取，原日志字节和SHA未改。`review_read_failure01.json`保留失败，未重跑会话。报告与state文件本身明确使用UTF8。

归档21文件逐项SHA核验，归档SHA256：`0df46d3088f4a23f45ed35ab306bb6659dbf8853a457a7272feb9adc5ee7d2a7`。collector确认无目标Python进程、reader及QThread退出；458正式文件、源码依赖、输入、既有oracle、Python/NumPy与原生库均未变。WPR未记录，采样间隔10000×100ns。

原始npz与实际输出消息日志只留本地/Windows归档，提交代码、计划、派生审计与结果。没有人体、USB、Run或优化A/B测试；历史失败窗口与校准门槛保持。根因及正式修复未完成。
