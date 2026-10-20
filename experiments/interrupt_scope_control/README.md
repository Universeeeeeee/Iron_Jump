# 中断/DPC记账范围的单次空闲控制

目的仅验证新的DPC/ISR事件实际交付、结构及QPC区间，并与另一条只读的系统处理器端点记账粗核对。承接c8ef572的83.612ms差异，不重跑/修补旧四窗，也不从空闲控制推断旧窗口原因。

唯一目标仅Sleep2秒，前后读取SystemProcessorPerformanceInformation(8)的8CPU原始累计字段和QPC锚点；不运行模型、计算循环、GUI/SDK/设备或人体。WPR只收ProcessThread/CSwitch/DPC/Interrupt，无PMC、栈或采样间隔设置；唯一owned实例按原故障保全控制器停止。

解码器复用已验证读取器；事件schema独立参考Microsoft PerfView源码并保留源SHA/原文：ISR opcode50/67、DPC68/69、ThreadedDPC66。x64 v2 ISR20bytes、DPC16bytes，InitialTimeQPC@0、routine@8，以header QPC为结束。版本/长度不符、负区间或时钟不符则失败，不猜测解码。原始核地址保留hex，不赋予无证据符号名。

独立解析规则先测试：同CPU嵌套ISR/DPC按时间并集，不双计；ThreadedDPC属于已调度线程执行，单列，不能再从另一线程的CSwitch驻留扣掉。OS累计DPC/Interrupt字段可能粗粒度或不交付，0值不得认证精确计时；只列原值/单调性及31.25ms粗范围差，不改变旧门槛，不把ISR事件数与共享中断硬件计数强行等同。

固定一次控制：没有DPC/ISR则未交付/不覆盖，不重采。即使结构/粗计时通过，也不证明旧83ms由中断导致、真实观察扰动合格或慢态根因。完整证据/失败/锁保留；无正式文件、电源、优先级、亲和性或线程结构修改。

## 实际结果与schema纠正（同一ETL，未重录）

唯一两秒Sleep控制完成，owned WPR停止成功，采样间隔前后10000。原始读取发现DPC68/v2/16bytes共772、TimerDPC69/v2/16bytes共69、**ISR-MSI50/v2/24bytes共112**，无报告事件/缓冲丢失。本轮没有交付普通ISR67或ThreadedDPC66实例，不把未观察形状当作实际认证。

原冻结analyze.py错误地把opcode50和67都按普通20字节ISR检查，按约定失败且保留source/plan/error（analysis_failure01.json），没有覆盖为成功。兼容解析analyze02.py仅按已独立证实的MSI24字节形状新增MessageNumber字段，并保留普通67的预期；数值门槛不变、没有重录或补事件。

独立系统tracerpt解码同一ETL，虽提示部分其他事件不匹配schema，但**全部953条DPC/TimerDPC/ISR-MSI**的CPU/顺序/字段与原始载荷逐项吻合。MSI的Routine、ReturnValue、Vector、Reserved、MessageNumber与原字节一致。InitialTime被系统解码为FILETIME，与独立API原生UTC/QPC锚点换算最大残差4.8µs。tracerpt格式化TimeCreated的时区标签呈+07:59，故未使用该显示时间作时长基准；始终使用原始QPC和API锚点。原始XML、警告、地址及全部事件保留，不由最近导出名推断内核函数。

### 有效范围与未通过项

兼容解析确认实际事件交付、v2结构及QPC区间有效；31.25ms端点粗范围差均在门内。**这不等于完整/精细中断占用认证。** 观测区间中8个CPU的DPC端点累计时间增量全为0，但ETW已记录非零DPC时间；CPU2/6的OS中断时间各跳15.625ms，而同区间的ISR-MSI事件时长分别仅约2.2/11.9µs。OS中断次数与共享中断handler事件数也不是同单位，不能将它们相减作为“漏采比例”。

这是记账粒度/范围差异的实证约束，不证明系统端点计数失效，也不证明ETW覆盖了所有中断。ThreadedDPC单列，嵌套ISR/DPC按并集处理；没有用双计/减空白修正旧窗口。scope_audit01.json明确：complete_interrupt_occupancy_qualified=false、fine_CPU_accounting_qualified=false、old_83ms_gap_explained=false。旧四窗CPU门及原3%/1%和栈失败均未升级。

SYS_PROCESSOR_PERFORMANCE_INFORMATION结构另用phnt原文核对，源SHA/字段见native_layout_source01.json；内部原生结构引用不保证当前系统细计时精度。12项mock/区间/独立MSI字段测试通过，包括错误MessageNumber和时钟不匹配拒绝。

21文件原归档逐项SHA通过，SHA256为9ebece1d1160aa1faf9444b234a7bcf11b0393f3af0acd9430e4732f4c49eca0，锁与原失败保留。正式程序未变，没有模型/计算负载/现场测试。该控制不能回填旧ETL缺失的中断事件，也不能将83ms差异直接命名为ISR/DPC或GIL；下一步必须保留“驻留、线程记账、硬件执行计数”三种量的不同范围，避免只追求记账数值相等而误判根因。
