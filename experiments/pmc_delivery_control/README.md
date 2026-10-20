# 硬件计数实际交付门：单次有限正控制

目的只验证WPR是否能实际交付退休指令、核心周期和参考周期；不新增现场、GUI、SDK、原处理链或模型窗口。可枚举、配置成功及普通cycle回读都不算通过。

使用微软WPR文档的HardwareCounter/Counters/Event路径，在CSwitch事件上附加3个计数；没有CPU周期采样、调用栈或采样间隔设置。唯一原生工作完整复用旧cpu_execution_probe的固定字节码/六段规模/正控制/返回与释放检查，原文件和旧失败不变。这是独立计数器交付门，不重启失败的GUI阶段主动探针，也不解释为GHz。

固定一次启动请求；启动失败就不运行原生工作，不更换计数器/参数再试。成功才执行一次固定控制，随后停止唯一owned instance，保留ETL、命令、锁及故障。启动/停止或清理未确认时不宣称清理完成，不取消其他会话。

后续仅在同一既有ETL上解码验证：三个实际计数非零、来源/顺序可验证、PID/TID/生命周期/时钟/丢失通过，且已知指令规模与计数增量一致。配置成功、全零或仅有OScycle都不晋级。即使通过交付，观察器扰动与真实慢/快同窗证据仍需另外验证，不计算现场CPU/GIL份额，不以硬件名称推频率。

来源：https://learn.microsoft.com/en-us/windows-hardware/test/wpt/hardwarecounter 、https://learn.microsoft.com/en-us/windows-hardware/test/wpt/counters 、https://learn.microsoft.com/en-us/windows-hardware/test/wpt/counter 。

## 实际结果

唯一采集已完成。WPR启动/原生控制/停止均返回0；独立logman与owned status确认会话结束，timer interval前后均10000。锁及原ETL保留。不得把capture01中的pmc_delivery_verified=false覆盖成通过：它是采集当时尚未解码的状态。

同一ETL完整离线解码发现6382条CSwitch v5事件，每条携带一个24字节PMC扩展，实际3项非零；PerfInfo配置事件给出的顺序与InstructionRetired/UnhaltedCoreCycles/UnhaltedReferenceCycles请求一致。全部6374个相邻逐CPU区间的线程链闭合、计数无回退；目标PID13080/TID12820生命周期和原生before/after线程身份吻合。QPC10MHz，时钟类型1，报告的events/buffers/consumer丢失均0。

六段循环已知退休指令合计2160000012；它们全部落在CPU2上同一个连续目标运行区间，外包络指令增量2213434936，还包含约17ms尾部和Python/记账等边界工作。每个单循环均没有完整包含的CSwitch计量区间，无法验证逐段四倍工作量比例。因此**实际计数交付=true，逐段已知工作校准=false，硬件归因资格=false**。不能用总量近似代替逐段门槛；不由core/reference比值换算GHz，参考计数的架构语义/单位仍未独立认证。

### 解码失败保全与纠正

v1/v2/v3在遇到零长度空指针载荷时调用Marshal.Copy，引发ArgumentNullException。v1一度被误判为元数据写出问题；v2仅改变字典键未解决。v3增加独立异常类型/消息/栈文件，定位到回调异常重新抛出。v4仅跳过零长度的复制，保持非零载荷/扩展解码，完整读取同一ETL。先前版本、失败目录、部分输出及现有ReadStacksBase独立读取结果全部保留，未重录或运行新的原生控制。

ReadCounters04、元数据、全事件及所有失败文件保存在第二份独占归档，SHA见decoder_transport01.json。原始归档与第二归档均逐项哈希核验。5项控制器故障测试与3项计数差分测试通过。下一阶段若需要精确边界，应先设计独立校准协议（明确控制边界/空白控制），不能默默重复当前控制或在原失败结果上补点。旧3%/1%和原栈门槛保持，当前没有启动任何真实消费链、模型或现场负载。
