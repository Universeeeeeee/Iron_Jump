# 隔离消费者批量40候选

只把实验actor的GroundFrameInbox单次批量上限从20改为40；4ms检查、FIFO、原滤波、Processor、报告和输出协议不变。目标是减少0ms Qt timer重复唤醒，关闭已测得的约5%早期服务率缺口。无人体、USB、重启或正式修改。
