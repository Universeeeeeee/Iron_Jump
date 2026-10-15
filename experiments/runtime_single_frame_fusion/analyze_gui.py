"""Verify delivered evidence before calculating performance or adoption results."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIELD = ROOT / 'exports/ground_boundary_latency_20261014/field_run_20261015_02'


def stats(values):
    return dict(zip(('p50', 'p95', 'p99', 'max'), np.percentile(values, [50, 95, 99, 100]).tolist())) if len(values) else None


def first_diff(a, b, path=''):
    if type(a) != type(b): return path, repr(a)[:150], repr(b)[:150]
    if isinstance(a, dict):
        if a.keys() != b.keys(): return path, 'keys', str(a.keys() ^ b.keys())
        for key in a:
            difference = first_diff(a[key], b[key], path + '/' + str(key))
            if difference: return difference
    elif isinstance(a, list):
        if len(a) != len(b): return path, len(a), len(b)
        for i, (x, y) in enumerate(zip(a, b)):
            difference = first_diff(x, y, path + '/' + str(i))
            if difference: return difference
    elif a != b: return path, a, b


def verify(folder):
    timing = json.loads((folder / 'timing.json').read_text(encoding='utf-8'))
    probe = json.loads((folder / 'probe.json').read_text(encoding='utf-8'))
    report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    expected_report = json.loads((HERE / 'full_report_oracle.json').read_text(encoding='utf-8'))['report']
    assert timing['finished'] and not timing['errors'], (folder.name, timing['errors'])
    assert probe['compilation']['B']['generated_wrapper_releases_gil'] is False
    assert probe['compilation']['C']['generated_wrapper_releases_gil'] is True
    original_rows = json.loads((FIELD / 'timing.json').read_text(encoding='utf-8'))['rows']
    keys = ('contact_id', 'touch_sample', 'confirmed_sample', 'published_sample')
    assert [[r[k] for k in keys] for r in timing['rows']] == [[r[k] for k in keys] for r in original_rows]
    with np.load(folder / 'raw_frames.npz') as raw, np.load(FIELD / 'raw_frames.npz') as source:
        indices = raw['sample_indices']
        assert np.array_equal(indices, np.arange(94205, 108609))
        for key in ('frame_indices', 'wire', 'bits'):
            assert np.array_equal(raw[key], source[key][indices]), (folder.name, key)
        assert np.array_equal(raw['bits'], 1 - np.unpackbits(raw['wire'], axis=1, bitorder='little'))
        checked = int(raw['received_ns'][3500])
        for branch in (report['report_config_snapshot']['device'], report['report_config_snapshot']['beam_quality']['preflight']):
            assert branch['checked_monotonic_ns'] == checked
            del branch['checked_monotonic_ns']
        begin = int(raw['received_ns'][0])
    assert report['report_config_snapshot']['device']['checked_sample_index'] == 97705
    assert report['report_config_snapshot']['raw_buffer']['total_received_frames'] == 10903
    assert report['report_config_snapshot']['raw_buffer']['retained_frames'] == 10903
    assert report == expected_report, (folder.name, first_diff(expected_report, report))
    manifest = json.loads((HERE / 'baseline_manifest.json').read_text())
    assert probe['source_hashes'] == manifest['base_files'], 'Executed baseline differs'
    for name, sha in probe['artifact_hashes'].items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == sha, (name, 'Executed experiment differs')
    last = 94204
    for batch in probe['queues']:
        last += batch[2]
        assert last == batch[3], 'Consumed frames not in source order'
    assert last == 108608
    end = timing['source_exhausted_host_ns']
    stop = next(x[1] for x in probe['spans'] if x[0] == 'stop')
    assert all(row['ui_paint_completed_host_ns'] < stop for row in timing['rows'])
    spans = [x for x in probe['spans'] if begin <= x[1] < end and x[0] not in ('inference', 'stop')]
    active = [x for x in probe['queues'] if 104000 <= x[3] <= 107500]
    assert len(active) > 2
    overlay = [x for x in probe['samples'] if begin <= x[0] < end and x[4]]
    assert len(overlay) > 10, 'Overlay was not active'
    result = {
        'variant': probe['runtime'], 'raw_report_events_source_order_exact': True,
        'canonical_report_sha256': hashlib.sha256(json.dumps(report, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'receipt_to_paint_ms': timing['received_to_paint_ms'],
        'scheduled_to_paint_ms': stats([r['scheduled_event_to_paint_ms'] for r in timing['rows']]),
        'gui_ms_per_second': sum(x[2] - x[1] for x in spans) / 1e6 / ((end - begin) / 1e9),
        'active_age_slope_ms_per_device_second': float(np.polyfit([x[3] / 1000 for x in active], [x[4] for x in active], 1)[0]),
        'active_processed_fps': (active[-1][3] - active[0][3]) / ((active[-1][1] - active[0][1]) / 1e9),
        'active_age_ms': stats([x[4] for x in active]), 'peak_pending': max(x[1] for x in probe['samples']),
        'rendered_frames': sum(x[0] == 'preview_prepare' for x in spans),
        'inference_frames': sum(x[0] == 'inference' and begin <= x[1] < end for x in probe['spans']),
        'camera': timing['camera_replay_stats'], 'preheat_seconds': probe['preheat_seconds'],
        'environment': probe['environment'], 'compilation': probe['compilation']}
    print(folder.name, 'P95', round(result['receipt_to_paint_ms']['p95'], 1),
          'fps', round(result['active_processed_fps'], 1),
          'age slope', round(result['active_age_slope_ms_per_device_second'], 1), flush=True)
    return result


def main(action):
    if action == 'aa':
        runs = {p.name: verify(p) for p in sorted(HERE.glob('aa_*_A')) if p.is_dir()}
        assert len(runs) == 2
        output = {'runs': runs, 'all_evidence_equal_to_independent_original_oracle': True,
                  'scope': 'Two identical instrumented A runs; observer overhead is not independently measured by this pair.'}
        path = HERE / 'aa_verified.json'
    else:
        plan = json.loads((HERE / 'trial_plan.json').read_text())
        assert hashlib.sha256((HERE / 'trial_plan.json').read_bytes()).hexdigest() == (HERE / 'trial_plan.sha256').read_text().strip()
        runs = {p.name: verify(p) for p in sorted(HERE.glob('trial_*_*_*')) if p.is_dir()}
        assert len(runs) == 18
        assert len({json.dumps(r['environment'], sort_keys=True) for r in runs.values()}) == 1
        output = {'runs': runs, 'candidates': {}, 'hardware_acceptance': False}
        for variant in 'BC':
            pairs = []
            for block, sequence in enumerate(plan['blocks'], 1):
                a = runs[f'trial_{block:02d}_{sequence.index("A") + 1}_A']
                b = runs[f'trial_{block:02d}_{sequence.index(variant) + 1}_{variant}']
                pairs.append({'p95_reduction': 1 - b['receipt_to_paint_ms']['p95'] / a['receipt_to_paint_ms']['p95'],
                              'scheduled_p95_reduction': 1 - b['scheduled_to_paint_ms']['p95'] / a['scheduled_to_paint_ms']['p95'],
                              'a': a, 'candidate': b})
            med = lambda field, label: float(np.median([p[label][field] for p in pairs]))
            repeated = (sum(p['p95_reduction'] > 0 for p in pairs) >= 5
                        and np.median([p['p95_reduction'] for p in pairs]) >= .10
                        and med('active_processed_fps', 'candidate') >= med('active_processed_fps', 'a')
                        and med('active_age_slope_ms_per_device_second', 'candidate') <= med('active_age_slope_ms_per_device_second', 'a')
                        and med('gui_ms_per_second', 'candidate') <= 1.05 * med('gui_ms_per_second', 'a'))
            realtime = (all(p['candidate']['receipt_to_paint_ms']['p95'] <= 150 and p['candidate']['receipt_to_paint_ms']['max'] <= 250
                            and p['candidate']['active_age_slope_ms_per_device_second'] <= 10 for p in pairs)
                        and med('active_age_slope_ms_per_device_second', 'candidate') <= 5)
            output['candidates'][variant] = {'pairs': pairs, 'repeated_improvement_pass': bool(repeated),
                'short_realtime_pass': bool(realtime), 'improved_blocks': sum(p['p95_reduction'] > 0 for p in pairs),
                'median_p95_reduction': float(np.median([p['p95_reduction'] for p in pairs])),
                'median_active_processed_fps': med('active_processed_fps', 'candidate'),
                'median_age_slope_ms_per_device_second': med('active_age_slope_ms_per_device_second', 'candidate'),
                'median_gui_ms_per_second': med('gui_ms_per_second', 'candidate')}
        path = HERE / 'gui_summary.json'
    path.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('aa', 'trials'))
    main(parser.parse_args().action)
