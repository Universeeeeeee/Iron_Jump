# 硬件计数实际交付门：单次有限正控制

目的只验证WPR是否能实际交付退休指令、核心周期和参考周期；不新增现场、GUI、SDK、原处理链或模型窗口。可枚举、配置成功及普通cycle回读都不算通过。

使用微软WPR文档的HardwareCounter/Counters/Event路径，在CSwitch事件上附加3个计数；没有CPU周期采样、调用栈或采样间隔设置。唯一原生工作完整复用旧cpu_execution_probe的固定字节码/六段规模/正控制/返回与释放检查，原文件和旧失败不变。这是独立计数器交付门，不重启失败的GUI阶段主动探针，也不解释为GHz。

固定一次启动请求；启动失败就不运行原生工作，不更换计数器/参数再试。成功才执行一次固定控制，随后停止唯一owned instance，保留ETL、命令、锁及故障。启动/停止或清理未确认时不宣称清理完成，不取消其他会话。

后续仅在同一既有ETL上解码验证：三个实际计数非零、来源/顺序可验证、PID/TID/生命周期/时钟/丢失通过，且已知指令规模与计数增量一致。配置成功、全零或仅有OScycle都不晋级。即使通过交付，观察器扰动与真实慢/快同窗证据仍需另外验证，不计算现场CPU/GIL份额，不以硬件名称推频率。

来源：https://learn.microsoft.com/en-us/windows-hardware/test/wpt/hardwarecounter 、https://learn.microsoft.com/en-us/windows-hardware/test/wpt/counters 、https://learn.microsoft.com/en-us/windows-hardware/test/wpt/counter 。
