## E3：独立阶段与完整消费者 CPU 对照

每项输入执行 AB、BA、AB、BA 四组配对，每次新进程。下表为消费者专用 CPU 的配对改善中位数。范围：原质量、滤波、Processor、发布和停止 flush；解码、输入构造及保存位于计时之外。负值表示退化。

| 输入 | 候选 | 消费者专用 CPU 改善 | 改善配对 |
|---|---|---:|---:|
| empty | clusters | -1.58% | 1/4 |
| sparse | clusters | -0.01% | 2/4 |
| cross | clusters | 3.13% | 3/4 |
| plateau | clusters | 5.62% | 4/4 |
| stress | clusters | 63.65% | 4/4 |
| field_run_20261015_02 | clusters | 14.26% | 3/4 |
| field_walk_full_02 | clusters | -13.07% | 0/4 |

- clusters：本地 CPU 门槛未通过。

这些是本地 macOS、无节奏、无 GUI/硬件的计算成本结果；不能据此声称 Windows FIFO、显示延迟或现场积压已经改善。
