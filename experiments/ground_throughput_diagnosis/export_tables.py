"""Readable tables derived only from the verified per-run evidence."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write(name, rows):
    if not rows:
        return
    with (HERE / name).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    summary = json.loads((HERE / 'summary.json').read_text())
    runs, phases, stages = [], [], []
    for name, run in summary['runs'].items():
        runs.append({'run': name, 'mode': run['mode'], 'probe': run['level'],
                     'touches': run['receipt_to_paint_ms']['count'],
                     'receipt_p95_ms': run['receipt_to_paint_ms']['p95'],
                     'receipt_max_ms': run['receipt_to_paint_ms']['max'],
                     'scheduled_p95_ms': run['scheduled_to_paint_ms']['p95'],
                     'dense_consumer_fps': run['phases']['dense']['consumer_fps'],
                     'dense_age_slope_ms_per_device_s': run['phases']['dense']['age_slope_ms_per_device_second'],
                     'raw_report_quality_runtime_audit_exact': run['raw_report_runtime_quality_audit_exact']})
        for phase, data in run['phases'].items():
            batch = data.get('batch_cost', {})
            gaps = data.get('backlog_drain_gap_ms') or {}
            phases.append({'run': name, 'mode': run['mode'], 'probe': run['level'], 'phase': phase,
                           'consumer_fps': data['consumer_fps'],
                           'age_slope_ms_per_device_s': data['age_slope_ms_per_device_second'],
                           'completion_age_p95_ms': data['completion_age_ms']['p95'],
                           'reader_scheduled_lag_p95_ms': data['reader_scheduled_lag_ms']['p95'],
                           'batch_wall_us_per_input': batch.get('wall_us_per_frame'),
                           'batch_cpu_cycles_per_input': batch.get('cpu_cycles_per_frame'),
                           'backlog_dispatch_gap_p95_ms': gaps.get('p95'),
                           'backlog_dispatch_gap_max_ms': gaps.get('max'),
                           'sampled_roots': data.get('sampled_roots')})
            for label, stage in data.get('exclusive_stages', {}).items():
                stages.append({'run': name, 'mode': run['mode'], 'phase': phase, 'stage': label,
                               'sampled_input_roots': data['sampled_roots'], 'stage_calls': stage['calls'],
                               'exclusive_wall_us_per_sampled_input_gross': stage['wall_us_per_sampled_input'],
                               'exclusive_cpu_cycles_per_sampled_input_gross': stage['cpu_cycles_per_sampled_input'],
                               'inclusive_wall_us_per_sampled_input_do_not_sum': stage['inclusive_wall_us_per_sampled_input']})
    write('runs.csv', runs)
    write('phases.csv', phases)
    write('stages.csv', stages)
