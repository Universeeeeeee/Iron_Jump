"""Collapse exclusive measurements into disjoint component groups."""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GROUPS = {
    'quality_gate_including_runtime': {'quality', 'runtime_evidence'},
    'stability_filter_including_mirror': {'filter', 'filter_numeric', 'filter_render', 'mirror_guard'},
    'processor_frame_work': {'processor', 'ownership', 'ownership_recover', 'commit',
                             'publications', 'record_visual', 'clusters'},
    'processor_summary': {'summary'},
    'session_forward_archive_publish': {'engine_forward', 'session', 'filtered_consume',
                                         'raw_archive', 'snapshot', 'visual_emit'},
}


if __name__ == '__main__':
    data = json.loads((HERE / 'summary.json').read_text())
    rows = []
    for name, run in data['runs'].items():
        if run['level'] != 'D':
            continue
        for phase, part in run['phases'].items():
            stages = part['exclusive_stages']
            assert not (set(stages) - set.union(*GROUPS.values()))
            total_cycles = sum(s['cpu_cycles_per_sampled_input'] for s in stages.values())
            for group, members in GROUPS.items():
                selected = [s for label, s in stages.items() if label in members]
                cycles = sum(s['cpu_cycles_per_sampled_input'] for s in selected)
                rows.append({'run': name, 'mode': run['mode'], 'phase': phase, 'group': group,
                             'sampled_input_roots': part['sampled_roots'],
                             'exclusive_wall_us_per_sampled_input_gross': sum(s['wall_us_per_sampled_input'] for s in selected),
                             'exclusive_cpu_cycles_per_sampled_input_gross': cycles,
                             'fraction_of_sampled_root_cycles_gross': cycles / total_cycles if total_cycles else None})
    with (HERE / 'grouped_stages.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
