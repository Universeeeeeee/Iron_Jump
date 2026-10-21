## E2a：独立阶段与完整消费者 CPU 对照

每项输入执行 AB、BA、AB、BA 四组配对，每次新进程。下表为完整消费者线程 CPU 的配对改善中位数，含同样的原始解码、质量、滤波、步态处理和停止 flush；不含输入构造与结果保存。负值表示退化。

| 输入 | 候选 | 完整消费者 CPU 改善 | 改善配对 |
|---|---|---:|---:|
| empty | runtime | 6.56% | 4/4 |
| sparse | runtime | 3.57% | 3/4 |
| cross | runtime | 4.37% | 4/4 |
| plateau | runtime | 4.02% | 4/4 |
| stress | runtime | -1.68% | 1/4 |
| field_run_20261015_02 | runtime | 4.26% | 3/4 |
| field_walk_full_02 | runtime | 2.40% | 4/4 |

- runtime：本地 CPU 门槛通过。

这些是本地 macOS、无节奏、无 GUI/硬件的计算成本结果；不能据此声称 Windows FIFO、显示延迟或现场积压已经改善。
