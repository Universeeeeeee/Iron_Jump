# 旧CPU窗口的原生线程入口与Qt缩放工作身份

承接 `420c468`。本轮只读既有PID11948事件及Windows本机WMI事件定义，没有启动GUI、模型、采集器、人体、USB、Run或优化A/B。正式程序、原NumPy、绘图及所有旧失败窗口不变。

## 先核验事件结构，再解释入口

旧CPU ETL已经保留74条线程的DCStart/DCEnd记录，共148条。Windows本机 `root/wmi:Thread_V3_TypeGroup1` 的独立结构定义确认provider GUID、version 3、WmiDataId顺序与pointer属性；原始事件的64位标志与之匹配。按定义计算的固定部分为72字节，Win32StartAddr位于48字节处。

本机定义没有声明固定部分之后的字段，本轮保留全部尾部十六进制，不将看似字符串的尾部冒充已核验的线程名称。查询源和完整结构见read_thread_schema01.ps1、thread_start_schema01.json。

每条线程都只有一对保留的rundown记录，入口、TEB、用户栈界在两端一致；入口唯一映射到旧同PID映像，且该映像的两端rundown范围一致。这是保留窗口内的身份检查，不是创建时间证明。只有原先三个目标角色具备原CPU/cycles快照，其他线程仍未获得CPU计数资格；不能借此宣布完整生命周期或CPU栈验收通过。

## 新获得的库入口身份

| 入口所在映像 | 保留线程数 | 入口RVA | 能证明的边界 |
|---|---:|---|---|
| libmediapipe.dll | 30 | 0x1320424 | 这些线程的Win32入口在该精确映像内；部分同线程旧CPU见证已核验为向量算术路径 |
| OpenBLAS DLL | 7 | 0x257700 | 存在该库内入口；没有合格CPU见证不能推断它们空闲，也不能推断BLAS造成积压 |
| cv2.pyd | 4 | 0x48aeb64 | 有别于GUI主线程及通用CRT入口的OpenCV内入口；其中3条线程有旧同PID执行见证 |
| Qt6Core.dll | 6 | 0x26d580 | 通用Qt线程入口；必须继续结合原角色marker或实际执行栈区分工作 |

其他入口继续保留python.exe、CRT、系统线程池及DirectShow等模块身份，不按线程ID或CPU大小命名业务函数。完整74条记录与全部映像身份/SHA/RVA见thread_entries01.json。

这30/7/4/6是存在的线程数，不是同时运行数、独立实验数、CPU份额或过度并行证据。入口在某库内也不证明它当时一直执行该库，更不识别具体模型算子或Python调用来源。

## Qt原生缩放worker已能定性命名

同一PID11948的既有合格单个CPU见证中，以下四条线程在采样IP处均有匹配PDB的闭合栈：

| TID | Qt6Gui采样RVA |
|---:|---|
| 7952 | 0x1963c0 |
| 14440 | 0x1963b0 |
| 14780 | 0x1963d0 |
| 20456 | 0x196423 |

栈中包含 `qt_qimageScaleAARGBA_up_xy` 的lambda、`QImageScale::multithread_pixels_function` helper、`QThreadPoolThread::run`、`QThreadPrivate::start`和系统线程根。这里使用原精确Qt PDB命名，区别于无私有PDB的OpenCV/MediaPipe入口。对应全部帧仍在expanded_cpu_review01.json的individual_examples中，由新结果哈希绑定。

因此，这四条线程当时执行的是Qt线程池中的图像缩放工作，不能继续只叫“未知GUI进程线程”。但worker栈没有保留发起任务的Python栈，不能唯一归给相机预览、脚印或其他控件，也不能证明四条同时运行、阻塞消费者、持有GIL或主导慢态。Qt线程池与OpenCV内入口是两组不同身份，不能只凭模块数量推断原OpenCV单线程候选失败的原因。

## 对下一步判断的实际约束

1. 同进程工作至少包括模型原生执行、OpenCV内部线程及Qt图像缩放worker。将所有非消费者CPU归给GUI主线程、绘图或模型中的任一项都不成立。
2. PID11948是旧低延迟CPU轮。它不能填补PID17752数组创建等待时刻的持有者，也不能配到PID23008/14620或近期startup慢/快窗的CPU毫秒。尤其TID13080在两轮中重复，不构成同一线程身份。
3. 现有等待轮没有可恢复的同刻GIL所有权记录，旧持有者快照的暂停顺序/转移限制也未被本分析修复。继续为等待者起名不能闭合持有者缺口。本轮没有再次运行这些失败协议。
4. 后续如补慢/快执行证据，应保留这种入口、原角色和实际工作栈的区分，针对同窗的执行路径/交付与同步缺口冻结有限观察；不再扩大IPC或从本线程数直接实施线程限制/预分配优化。当前无需真人测试。

8项单元检查通过，覆盖原角色/公开入口测试及新增64位pointer布局、错误version/flags/opcode、截断payload、结构定义不匹配、映像重叠和半开区间。旧CPU/CSwitch、3%等效/1%精度失败及全部原始证据保持不变。根因贡献、GIL持有者与正式修复仍未完成。
