"""Produce a compact, auditable result table after the frozen GUI trial sequence."""
import csv
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent


def main():
    summary = json.loads((HERE / 'gui_summary.json').read_text())
    rows = []
    for name, run in summary['runs'].items():
        rows.append({'run': name, 'variant': run['variant'],
                     'receipt_p95_ms': run['receipt_to_paint_ms']['p95'],
                     'max_ms': run['receipt_to_paint_ms']['max'],
                     'scheduled_p95_ms': run['scheduled_to_paint_ms']['p95'],
                     'active_fps': run['active_processed_fps'],
                     'age_slope_ms_per_device_second': run['active_age_slope_ms_per_device_second'],
                     'gui_ms_per_second': run['gui_ms_per_second'],
                     'rendered_frames': run['rendered_frames'], 'inference_frames': run['inference_frames'],
                     'decoded_frames': run['camera']['decoded_frames']})
    with (HERE / 'gui_runs.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    lines = ['Iron_Jump 单帧融合：Windows 同源回放结果', '',
             '分支：codex/runtime-single-frame-fusion；本实验未合入原工作目录或正式 Windows 程序。',
             '正确性：同一组 483,997 帧在 Mac 与 Windows 上逐帧核对通过，另核对 1000/3000 帧窗口的中间告警区间。',
             '这些是既有录制及合成数据的重复验证，不是新增独立真人样本。',
             '回归：Windows A/B/C 各 139 项通过；部署包初次缺少旧测试依赖的失败日志保留，补齐后重跑通过。',
             '18 轮完整原始帧、来源顺序、脚印触地/确认/发布采样号及 TestReport 与旧独立 oracle 一致。',
             '仅规范化两个逐轮对照真实接收帧验证过的主机时钟字段。', '',
             '版本 | 接收至 paint P95 中位 ms | 各轮最大延迟的最大值 ms | 计划发送至 paint P95 中位 ms | 接触消费 fps 中位 | 队列年龄斜率中位 ms/设备秒']
    for variant in 'ABC':
        subset = [r for r in rows if r['variant'] == variant]
        median = lambda field: statistics.median(r[field] for r in subset)
        lines.append(f"{variant} | {median('receipt_p95_ms'):.2f} | {max(r['max_ms'] for r in subset):.2f} | {median('scheduled_p95_ms'):.2f} | {median('active_fps'):.2f} | {median('age_slope_ms_per_device_second'):.2f}")
    lines += ['', 'A=原 NumPy；B=融合且保留 GIL；C=相同融合函数且释放 GIL。',
              '数值编译均为 nopython；B/C 生成包装的 GIL 释放调用已从 LLVM 核对，预热使用独立状态。', '']
    for variant, candidate in summary['candidates'].items():
        lines.append(f"{variant}：6 块中 {candidate['improved_blocks']} 块 P95 改善，配对降幅中位数 {candidate['median_p95_reduction'] * 100:.2f}%；重复改善门槛 {candidate['repeated_improvement_pass']}；短窗实时门槛 {candidate['short_realtime_pass']}。")
        subset = [r for r in summary['runs'].values() if r['variant'] == variant]
        lines.append(f"  队列斜率最大 {max(r['active_age_slope_ms_per_device_second'] for r in subset):.2f}ms/设备秒；门槛为每轮<=10且中位数<=5。")
    lines += ['', '配对降幅中位数与“两个版本 P95 中位数的比值”不是同一指标，采用判定使用前者。']
    eligible = [v for v, c in summary['candidates'].items()
                if c['repeated_improvement_pass'] and c['short_realtime_pass']]
    if not eligible:
        lines += ['', '结论：两个候选均未同时通过预设重复改善与短窗实时门槛。本轮不采用，保留原 NumPy。',
                  '按计划的失败停止点结束本轮；60 秒、5 分钟 GUI 长测及真人现场验收未开展。',
                  '长负载输入生成器已准备，但未将准备状态冒充完成测量。']
    else:
        lines += ['', '结论：存在通过重复改善门槛的候选；长稳验证尚需独立核对，当前不宣称持续实时达标或完成硬件验收。']
    lines += ['', '测量范围：相同真实录制的 Windows 原生 GUI，实际姿态推理与骨架绘制；不包含真实 USB/相机驱动、SDK 跟随及持续录像写盘。',
              '每轮只有 7 次触地，P95 为小样本分位数；不宣称统计显著性。GUI 指标是四项墙钟合计/输入时间，不是进程 CPU 使用率。',
              'A/A 验证了同源可复现及原报告等价，不能单独量化全部探针扰动。Qt paint 返回也不等于物理屏幕扫描。',
              '内核微基准只说明隔离数值成本；不替代完整 GUI 采用门槛。所有反向轮次均保留。',
              '来源：trial_plan.json/.sha256、baseline_manifest.json、逐轮 probe/timing/report/raw_frames、equivalence 与 windows_production_equivalence.json、tests2_A/B/C.log。']
    benchmark = HERE / 'benchmark_win32.json'
    if benchmark.exists():
        data = json.loads(benchmark.read_text())
        medians = {v: statistics.median(r['microseconds_per_frame'] for r in data['runs']
                                       if r['modules'] == 8 and r['variant'] == v) for v in 'ABC'}
        lines += ['', f"Windows 8 段隔离运行时计数及告警掩码：A/B/C 单帧中位耗时 {medians['A']:.2f}/{medians['B']:.2f}/{medians['C']:.2f} 微秒。该环境没有 GUI、视觉及竞争线程，收益比例不外推到完整应用。"]
    audit = HERE / 'windows_final_audit.json'
    if audit.exists():
        data = json.loads(audit.read_text())
        assert not data['experiment_source_changed'] and not data['prior_isolated_source_changed']
        assert all(v['original'] == v['experiment'] for v in data['media'].values())
        lines.append(f"末次核对：实验基线 {data['experiment_source_files']} 个文件无变化；旧隔离源码无变化；正式源码相对旧备份差异 {len(data['formal_source_changes_since_old_backup'])} 个；原始光束与相机媒体哈希一致。")
    pixels = HERE / 'final_track_pixels.json'
    if pixels.exists():
        data = json.loads(pixels.read_text())
        lines.append(f"18 个末帧总览跑道截图区域共有 {data['unique_pixel_hashes']} 种像素结果；这不单独证明全过程无闪烁。")
    (HERE / 'results.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
