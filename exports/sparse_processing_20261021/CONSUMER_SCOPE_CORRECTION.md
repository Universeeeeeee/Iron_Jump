# 消费者 CPU 计时口径修正

此前 `target=pipeline` 是解码、质量、滤波、Processor 和停止 flush 在同一线程内依次执行的串行模型。其线程 CPU 可用于比较完整串行计算成本，不能直接当作生产消费者线程 CPU：实际 SensorFrameAssembler 在接收路径解码，消费者从 inbox 取得已经解码的 SensorFrame。

因此，E1 已发布的真实跑步 11.50%、走路 10.13% 应标为“含接收端解码的串行处理链路 CPU 改善”，不是已证明的消费者线程改善。原结果、原提交和原数据保留，不重写历史。

新增 `consumer_bench.py` 将输入解码、SensorFrame 构造及输入读取全部放在计时之外；计时仅覆盖原质量门、正式滤波、Processor、发布及停止 flush。E1 用相同输入分别准备原版解码帧和缓存解码帧，检查消费者本身是否存在可测收益。接收端成本继续由 E1 的解码/assembler 实验评价。

两种本地计时都不包含真实 Qt inbox 唤醒、IPC、相机负载或生产 GIL 竞争，因此不生成 FIFO 或 contact-to-paint 的性能结论。是否值得进入组合实验，以消费者专用测量及逐帧等价性为依据；读端缓存可独立列为接收端候选。
