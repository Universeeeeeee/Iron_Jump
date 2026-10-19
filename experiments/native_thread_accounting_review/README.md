# 既有全线程账本与CPU原生记录：拆清角色，补回被筛掉的旧事件

承接 `1d5b81b`。本阶段只读取保留记录及原ETL，不新增人体、USB、Run、GUI回放或采集；原程序、NumPy、滤波、Processor、线程结构和绘图不改。原不合格窗口和全部质量/扰动失败继续保留，未将局部证据追认成整体通过。

## 全线程CPU账本不能按gui标签直接归给绘图

两份旧窗口各保留88条线程起止计数：GUI进程67条，独立SDK进程21条。逐一检查PID/TID/creation、active和CPU/cycles单调性后，用原armed marker识别GUI主线程、消费Qt线程、保存光栅读取线程，再用实际模型inference及service_submit事件识别模型调用和保存视频提交线程。

原 `gui_native_*` 只是GUI进程成员标签，既不表示GUI主线程，也不证明某个库的worker。模型调用和视频线程不能埋进“GUI绘图CPU”；余下62个线程仍称未归属，不按CPU大小或线程ID猜来源。

| 原始窗口 | GUI主线程CPU ms | 消费线程CPU ms | 模型调用线程CPU ms | 保存视频提交线程CPU ms | 同进程未归属62线程CPU合计ms | SDK独立21线程CPU合计ms |
|---|---:|---:|---:|---:|---:|---:|
| finalization protocol01 | 2562.500 | 2109.375 | 546.875 | 1906.250 | 4281.250 | 156.250 |
| metadata failed02 | 2218.750 | 2171.875 | 359.375 | 1187.500 | 2593.750 | 78.125 |

各线程有自己的起止读取包围，合计不等于原子进程快照，不计算CPU/GIL份额。两窗共同内区间约4.974/4.981秒，消费进度界分别3000～3120/4936～5072帧，区间观测pending峰值2309/64。它们不是严格A/B，不能拿上述差值分配函数贡献。

视频提交线程运行保存JPEG读取/解码、原vision提交、可选mirror及预览排队等，不能将其全部CPU命名为imdecode；光栅/视频回放线程也不能冒充正式USB/相机驱动线程。SDK PID始终单列，不合入GUI GIL持有者判断。

原始record的protocol_case_pass与更严格的归档验收并非同一层：protocol01 record为true，但原result01仍因saved_workload_links失败而不具备完整观测资格；failed02仍失败。本次完整嵌入/绑定原判断，不改写它们。3项角色/冲突回归检查通过。

## 找到可以离线补齐的CPU事件覆盖缺口

旧ReadStacks解析器对目标PID保留全部StackWalk和映像/线程生命周期，但只为传入的TID清单保留SampledProfile。原GUI CPU导出只有3个指定线程的Profile事件，不能由此说其他线程没有运行。

当前原ETL仍在Windows，SHA256 `21cfa5343598550b0313d695cf093b83c1cca29851c5e6f4c8e7d052786a4dee`；原解析器exe SHA256 `edfb9e4f9f6c9ffdc51ff0aa5513d33f585efe0558b596c45bd14ca73c6cd1df`，其源码SHA与现场记录完全相同。没有重新编译解析器或重新录制。

从原目标PID11948的已存生命周期/StackWalk清单取得74个TID，用同一解析器对同一ETL写入全新输出目录。离线Profile事件从1010扩展至1767，总导出4743条；原来的全部Profile事件仍保留，StackWalk/映像/生命周期逐事件字节指纹完全一致。远端和本地导出SHA匹配，双遍事件数/时间转换、clock type/frequency及原trace start一致；新增时间转换对原时钟包围的最大残差0.0118ms，丢失元数据为0。

这只修复离线筛选覆盖，不是CPU质量或实际负载扰动验收通过。在原计数共同内区间保留1136条Profile事件，其中37条NonProcess、3条IP不在关联栈的记录仍显式保留。新TID缺少原CPU/cycles起止快照，不作采样CPU估计或热点百分比。

## 精确原生计算见证：不根据模块名猜算子

扩展后可以看到其他线程的root-complete、IP-matched、无歧义、非NonProcess个别见证，包括libmediapipe.dll、cv2.pyd及Qt路径。仅对libmediapipe的几个见证做精确PE静态核对：当前Windows文件与旧映像SHA均为 `aa8e6c1b618c30cd3a6ad584dee1b2f2c99c3f3025d683bada36e1566d9092b7`。

通过PE的AMD64异常表定位唯一运行时函数范围，离线反汇编并核对指令字节。例如：

| 原采样RVA | 精确指令 |
|---|---|
| 0xfe5fe5 | vfmadd231ps |
| 0xfe5ff9 | vfmadd231ps |
| 0xfe6009 | vfmadd231ps |
| 0xfe84e0 | vfmadd132ps |
| 0xfe8579 | vmaxps |

这些特定IP在向量算术/访存路径，不能将它们本身命名为take_gil或纯pause等待。它们不排除别处存在等待/忙等，更不证明这就是首窗慢态主因。

**不接受objdump最近导出名作私有函数名。** 工具会显示很远的 `TfLiteXNNPackDelegateDelete+位移`，本次明确忽略该标注，不宣称样本在Delete，也不把未知函数命名为卷积/GEMM/XNNPACK某算子。PDB函数名仍为null，只保留精确SHA、RVA、异常表范围和机器码证据。

无符号内核地址另见kernel_frames01：保留19组见证中的绝对地址及唯一可映射的模块/SHA/RVA，未知映射保持unknown，不声称内核符号完整。

## 不能跨窗口拼接成根因占比

CPU账本两窗PID23008/14620，与旧CPU ETL的PID11948不是同一时刻、同一线程生命周期。严禁把前者未归属线程的CPU毫秒，配到后者某个libmediapipe地址，制造“模型CPU/GIL贡献”。新模块见证只证明那些原生计算路径实际出现，不识别同一账本窗口中的具体原生worker、业务函数或GIL所有者。

总体根因和正式修复仍未完成。已有CPU账本与现场真实GIL等待均有效，但CPU交付、实际原生执行/内存路径、同步等具体贡献没有闭合。下一步只能针对“未归属worker的同窗身份/活动及对应原生路径”或“实际执行交付”的明确缺口；优先复用已有记录，不能以重复等待者统计、改标签、降门槛或扩大泛用工具代替因果证据。

原ETL前后SHA一致，旧验收文件未改；新输出全部独立创建。二进制、完整事件和反汇编原文只留用户本地/Windows忽略目录，仓库提交代码、派生见证、哈希与旧失败判断。没有启动业务进程/采样器或改变系统策略。

进一步将一处内部GIL等待核对到NumPy数组创建路径，详见 [allocation_boundary_update01.md](allocation_boundary_update01.md)。这是等待者路径升级，不是主因、持有者、PDB或优化资格升级。
