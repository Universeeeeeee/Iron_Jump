## E1：独立阶段与完整消费者 CPU 对照

每项输入执行 AB、BA、AB、BA 四组配对，每次新进程。下表为消费者专用 CPU 的配对改善中位数。范围：原质量、滤波、Processor、发布和停止 flush；解码、输入构造及保存位于计时之外。负值表示退化。

| 输入 | 候选 | 消费者专用 CPU 改善 | 改善配对 |
|---|---|---:|---:|
| empty | decode_full | -0.35% | 2/4 |
| sparse | decode_full | -0.60% | 1/4 |
| cross | decode_full | 0.49% | 2/4 |
| plateau | decode_full | -0.95% | 0/4 |
| stress | decode_full | 0.44% | 3/4 |
| field_run_20261015_02 | decode_full | 0.19% | 2/4 |
| field_walk_full_02 | decode_full | 2.12% | 4/4 |

- decode_full：本地 CPU 门槛未通过。

这些是本地 macOS、无节奏、无 GUI/硬件的计算成本结果；不能据此声称 Windows FIFO、显示延迟或现场积压已经改善。

E1 的主要作用于读端。消费者计时是否通过与解码计时是否通过分别报告；旧串行模型数据保留在 E1_serial_pipeline.json，计时口径修正见 CONSUMER_SCOPE_CORRECTION.md。
