# 地面走路：识别步数与步态指标

| 字段 | 含义 |
| --- | --- |
| `walking_summary.recognized_steps` | 当前仍 active 的可靠触地事件，按 `(epoch, contact_id)` 去重后的落脚次数。重复发布只保留最新 revision；最新 revision 撤回后不计数。 |
| `walking_summary.footfalls` | 每次可靠落脚一条记录，包括未能形成有效步间或周期的落脚。条目数等于识别步数。 |
| `valid_steps`、`steps`、`valid_step_times` | 原有时间/身份证据支持的步间关系及其数量。含义、计算条件和阈值保持不变。 |
| `valid_cycles`、`cycles` | 原有周期关系。不能为匹配落脚次数复制或补造。 |

GUI 主卡片显示“识别步数”；报告同时展示识别落脚、有效步间和周期。12 次可靠落脚可以只有 7 条有效步间关系和 4 个周期。未知左右脚、缺失位置、接触连续性及支撑时间不会阻止一条已可靠发布的落脚记录保留，但对应指标继续缺失并保留原因。

逐次落脚字段包括稳定的 `event_id`、`contact_id`、`epoch`、`revision`、设备触地/发布采样序号、设备绝对时间 `sample_time_s`、相对本次行走起点的 `timestamp_s`。`raw_landing_position_m` 来自发布瞬间冻结的 `landing_positions_m`，保留安装后的物理坐标；它不自动升级为可信步长中心。`centre_m` 仍由独立位置证据决定。`source_ref` 指向原始接触记录，`step_refs` 只引用实际存在的步间关系，原事件审计和 `ambiguous_contacts` 不删除。

新明细标记 `footfall_schema_version = walking-footfalls/1.0`；保存的 gait 报告 schema 为 2，报告分析包为 1.2。旧报告仍按原 schema 读取，不从旧步间数据补造落脚。Excel 新增 `Walking footfalls`；原 `Walking steps` / `Walking cycles` 保持原含义。

正式默认入口暂时恢复原本的本地 SessionController；地面走路子进程仍保留，可由实验显式注入 MeasurementController 使用。默认恢复不撤回识别步数、逐次落脚记录或已登记坏束配置。原本本地 inbox batch 上限为 20，保留的子进程方案为 40；对照时需另做相同 batch 的本地控制，不能把批量差异归因于进程边界。IPC 的有界队列和报告校验逻辑保持不变，历史验收和失败证据继续保留。当前不宣称正式现场的实时性问题已解决。
