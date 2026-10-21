## E2b：独立阶段与完整消费者 CPU 对照

每项输入执行 AB、BA、AB、BA 四组配对，每次新进程。下表为消费者专用 CPU 的配对改善中位数。范围：原质量、滤波、Processor、发布和停止 flush；解码、输入构造及保存位于计时之外。负值表示退化。

| 输入 | 候选 | 消费者专用 CPU 改善 | 改善配对 |
|---|---|---:|---:|
| empty | idle | 16.19% | 4/4 |
| sparse | idle | 6.96% | 4/4 |
| cross | idle | 7.64% | 3/4 |
| plateau | idle | 2.95% | 3/4 |
| stress | idle | 0.17% | 2/4 |
| field_run_20261015_02 | idle | 2.42% | 3/4 |
| field_walk_full_02 | idle | -0.01% | 2/4 |

- idle：本地 CPU 门槛通过。

这些是本地 macOS、无节奏、无 GUI/硬件的计算成本结果；不能据此声称 Windows FIFO、显示延迟或现场积压已经改善。
