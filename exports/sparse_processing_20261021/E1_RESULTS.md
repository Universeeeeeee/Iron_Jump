## E1：独立阶段与完整消费者 CPU 对照

每项输入执行 AB、BA、AB、BA 四组配对，每次新进程。下表为完整消费者线程 CPU 的配对改善中位数，含同样的原始解码、质量、滤波、步态处理和停止 flush；不含输入构造与结果保存。负值表示退化。

| 输入 | 候选 | 完整消费者 CPU 改善 | 改善配对 |
|---|---|---:|---:|
| empty | decode_full | 11.06% | 4/4 |
| sparse | decode_full | 9.79% | 4/4 |
| cross | decode_full | 11.11% | 4/4 |
| plateau | decode_full | 11.65% | 4/4 |
| stress | decode_full | -0.15% | 2/4 |
| field_run_20261015_02 | decode_full | 11.50% | 4/4 |
| field_walk_full_02 | decode_full | 10.13% | 4/4 |

- decode_full：本地 CPU 门槛通过。

这些是本地 macOS、无节奏、无 GUI/硬件的计算成本结果；不能据此声称 Windows FIFO、显示延迟或现场积压已经改善。
