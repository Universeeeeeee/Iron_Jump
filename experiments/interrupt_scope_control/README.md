# 中断/DPC记账范围的单次空闲控制

目的仅验证新的DPC/ISR事件实际交付、结构及QPC区间，并与另一条只读的系统处理器端点记账粗核对。承接c8ef572的83.612ms差异，不重跑/修补旧四窗，也不从空闲控制推断旧窗口原因。

唯一目标仅Sleep2秒，前后读取SystemProcessorPerformanceInformation(8)的8CPU原始累计字段和QPC锚点；不运行模型、计算循环、GUI/SDK/设备或人体。WPR只收ProcessThread/CSwitch/DPC/Interrupt，无PMC、栈或采样间隔设置；唯一owned实例按原故障保全控制器停止。

解码器复用已验证读取器；事件schema独立参考Microsoft PerfView源码并保留源SHA/原文：ISR opcode50/67、DPC68/69、ThreadedDPC66。x64 v2 ISR20bytes、DPC16bytes，InitialTimeQPC@0、routine@8，以header QPC为结束。版本/长度不符、负区间或时钟不符则失败，不猜测解码。原始核地址保留hex，不赋予无证据符号名。

独立解析规则先测试：同CPU嵌套ISR/DPC按时间并集，不双计；ThreadedDPC属于已调度线程执行，单列，不能再从另一线程的CSwitch驻留扣掉。OS累计DPC/Interrupt字段可能粗粒度或不交付，0值不得认证精确计时；只列原值/单调性及31.25ms粗范围差，不改变旧门槛，不把ISR事件数与共享中断硬件计数强行等同。

固定一次控制：没有DPC/ISR则未交付/不覆盖，不重采。即使结构/粗计时通过，也不证明旧83ms由中断导致、真实观察扰动合格或慢态根因。完整证据/失败/锁保留；无正式文件、电源、优先级、亲和性或线程结构修改。
