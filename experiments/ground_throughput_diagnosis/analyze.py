"""Verify independently, then analyze non-overlapping costs and paired calibration."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PHASES = json.loads((HERE / 'phases.json').read_text())


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def stats(values):
    return dict(zip(('count', 'mean', 'p50', 'p95', 'max'),
                    (len(values), float(np.mean(values)), *np.percentile(values, [50, 95, 100]).tolist()))) if len(values) else None


def canonical(report, checked_ns=None):
    for branch in (report['report_config_snapshot']['device'],
                   report['report_config_snapshot']['beam_quality']['preflight']):
        if checked_ns is not None:
            assert branch['checked_monotonic_ns'] == checked_ns
        del branch['checked_monotonic_ns']
    return report


def phase(mode, sample):
    source = PHASES[mode]
    window = next((w for w in source['windows'] if w['start'] <= sample < w['end']), None)
    if window is None:
        return 'outside'
    if window['phase'] == 'empty':
        dense_start = min(w['start'] for w in source['windows'] if w['phase'] == 'dense')
        return 'empty_before' if sample < dense_start else 'empty_after'
    return window['phase']


def verify(folder):
    data = read(folder / 'diagnostic.json')
    mode = data['mode']
    source = PHASES[mode]
    timing = read(folder / 'timing.json')
    assert timing['finished'] and not timing['errors'], (folder.name, timing['errors'])
    baseline = read(ROOT / 'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert data['baseline_hashes'] == baseline
    provenance = read(folder / 'provenance.json')
    cache = ROOT / 'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py'
    assert provenance['cache_sha256'] == hashlib.sha256(cache.read_bytes()).hexdigest()
    assert provenance['input_sha256'] == source['raw_sha256']
    assert provenance['cadence'] == 'recorded' and provenance['camera_replay'] is True
    assert all(baseline[name] == sha for name, sha in provenance['source_hashes'].items())
    allowed_probes = [HERE / 'probe.py']
    if (HERE / 'enabled_probe.py').exists():
        allowed_probes.append(HERE / 'enabled_probe.py')
    assert data['probe_sha256'] in {hashlib.sha256(p.read_bytes()).hexdigest() for p in allowed_probes}
    assert data['thread_ids']['consumer'] != data['thread_ids']['gui']
    assert data['thread_ids']['consumer'] == data['thread_ids']['measurement']
    field = ROOT / 'exports/ground_boundary_latency_20261014' / source['source']
    with np.load(field / 'raw_frames.npz') as original, np.load(folder / 'raw_frames.npz') as delivered:
        indices = delivered['sample_indices']
        expected = np.arange(source['checked'] - 3500, source['last'] + 1)
        assert np.array_equal(indices, expected), folder.name
        selected = np.searchsorted(original['sample_indices'], indices)
        for key in ('bits', 'wire', 'frame_indices'):
            assert np.array_equal(delivered[key], original[key][selected]), (folder.name, key)
        assert np.array_equal(delivered['bits'], 1 - np.unpackbits(delivered['wire'], axis=1, bitorder='little'))
        received = delivered['received_ns'].copy()
        checked_ns = int(received[3500])
        source_offsets = original['received_ns'][selected] - original['received_ns'][selected[0]]
    report = canonical(read(folder / 'report.json'), checked_ns)
    expected_report = read(HERE / 'oracles' / mode / 'report.json')
    assert report == expected_report, (folder.name, 'independent full report differs')
    if mode == 'run':
        parent_oracle_path = Path('/Users/vae/.codex/worktrees/runtime-single-frame-fusion/Iron_Jump/experiments/runtime_single_frame_fusion/full_report_oracle.json')
        if parent_oracle_path.exists():
            assert report == read(parent_oracle_path)['report'], 'Independent parent oracle differs'
    keys = ('contact_id', 'touch_sample', 'confirmed_sample', 'published_sample')
    source_timing = read(field / 'timing.json')
    assert [[r[k] for k in keys] for r in timing['rows']] == [[r[k] for k in keys] for r in source_timing['rows']]
    state = data['final_state']
    runtime = read(HERE / 'oracles' / mode / 'runtime.json')
    for a, b in (('runtime_counts', 'counts'), ('runtime_transitions', 'transitions'),
                 ('runtime_healthy_samples', 'healthy_samples'), ('runtime_window_sha256', 'window_sha256')):
        assert state[a] == runtime[b], (folder.name, a)
    assert state['quality'] == read(folder / 'report.json')['report_config_snapshot']['beam_quality']
    del state['quality']['preflight']['checked_monotonic_ns']
    summary = report['walking_summary' if mode == 'walk' else 'running_summary']
    assert state['processor_audit_sha256'] == digest(summary['event_audit'])
    assert state['touch_events'] == summary['event_publications']
    milestones = data['milestones']
    last = source['checked'] - 3501
    for _, sample, _, count in milestones:
        last += count
        assert sample == last, 'Consumer sample order mismatch'
    assert last == source['last']
    return data, timing, indices, received, source_offsets, digest(report), digest(state)


def metrics(folder):
    data, timing, indices, received, source_offsets, report_sha, state_sha = verify(folder)
    mode, source = data['mode'], PHASES[data['mode']]
    milestones = data['milestones']
    result = {'name': folder.name, 'mode': mode, 'level': data['level'],
              'raw_report_runtime_quality_audit_exact': True,
              'canonical_report_sha256': report_sha, 'canonical_evidence_sha256': state_sha,
              'receipt_to_paint_ms': timing['received_to_paint_ms'],
              'scheduled_to_paint_ms': stats([r['scheduled_event_to_paint_ms'] for r in timing['rows']]),
              'camera': timing['camera_replay_stats'], 'phases': {},
              'environment': data['environment'], 'tree_conservation_exact': True}
    anchor = data['source_clock']['anchor_ns']
    for group in ('empty_before', 'dense', 'empty_after', 'all'):
        match = lambda n: source['checked'] < n <= source['last'] and (group == 'all' or phase(mode, n) == group)
        points = [p for p in milestones if match(p[1])]
        if len(points) < 2:
            continue
        ages = [(p[0] - p[2]) / 1e6 for p in points]
        fps = (points[-1][1] - points[0][1]) * 1e9 / (points[-1][0] - points[0][0])
        slope = float(np.polyfit([(p[1] - points[0][1]) / 1000 for p in points], ages, 1)[0])
        mask = np.array([match(int(n)) for n in indices])
        positions = np.flatnonzero(mask)
        lags = (received[mask] - source_offsets[mask] - anchor) / 1e6
        part = {'consumer_fps': fps, 'age_slope_ms_per_device_second': slope,
                'completion_age_ms': stats(ages), 'batch_observations': len(points),
                'reader_scheduled_lag_ms': stats(lags.tolist()),
                'original_receipt_fps': (indices[positions[-1]] - indices[positions[0]]) * 1e9 /
                                        (source_offsets[positions[-1]] - source_offsets[positions[0]])}
        if data['level'] == 'D':
            batches = [b for b in data['batches'] if match(b[5])]
            count = sum(b[3] for b in batches)
            wall = sum(b[1] - b[0] for b in batches)
            cpu = sum(b[2] for b in batches)
            region_wall = batches[-1][1] - batches[0][0]
            part['batch_cost'] = {'frames': count, 'wall_us_per_frame': wall / count / 1000,
                                  'cpu_cycles_per_frame': sum(b[8] for b in batches) / count,
                                  'coarse_cpu_us_per_frame_unreliable': cpu / count / 1000,
                                  'region_wall_ms': region_wall / 1e6,
                                  'consume_wall_fraction_of_region': wall / region_wall,
                                  'outside_consume_wall_ms': (region_wall - wall) / 1e6,
                                  'scope': 'Callback wall coverage, not CPU occupancy; includes any GIL/OS waits inside callbacks',
                                  'cpu_ns': cpu, 'wall_ns': wall}
            trees = [s for s in data['spans'] if match(s[3])]
            roots = [s for s in trees if s[2] is None]
            by_id = {s[0]: s for s in trees}
            for root in roots:
                descendants = [s for s in trees if s[3] == root[3]]
                assert sum(s[7] for s in descendants) == root[5] - root[4]
                assert sum(s[8] for s in descendants) == root[6]
                assert sum(s[10] for s in descendants) == root[9]
            stages = defaultdict(lambda: [0, 0, 0, 0, 0])
            for s in trees:
                assert s[7] >= 0 and s[10] >= 0, 'Negative exclusive wall/cycle measurement'
                stage = stages[s[1]]
                stage[0] += s[7]
                stage[1] += s[8]
                stage[2] += 1
                stage[3] += s[5] - s[4]
                stage[4] += s[10]
            part['sampled_roots'] = len(roots)
            part['exclusive_stages'] = {label: {'wall_us_per_sampled_input': w / len(roots) / 1000,
                                               'cpu_cycles_per_sampled_input': cyc / len(roots),
                                               'coarse_cpu_us_per_sampled_input_unreliable': c / len(roots) / 1000,
                                               'calls': calls, 'inclusive_wall_us_per_sampled_input': incl / len(roots) / 1000}
                                        for label, (w, c, calls, incl, cyc) in sorted(stages.items())} if roots else {}
            drains = data['drains']
            gaps = []
            for previous, current in zip(drains, drains[1:]):
                if previous[8] > previous[7]:
                    last_batch = data['batches'][previous[8] - 1]
                    if match(last_batch[5]) and previous[4] > 0:
                        gaps.append((current[0] - previous[1]) / 1e6)
            part['backlog_drain_gap_ms'] = stats(gaps)
            part['backlog_drain_gap_total_ms'] = sum(gaps)
            active_drains = [d for d in drains if d[8] > d[7]
                             and match(data['batches'][d[8] - 1][5])]
            part['drain_wall_ms'] = stats([(d[1] - d[0]) / 1e6 for d in active_drains])
            part['peak_pending_at_drain'] = max((d[3] for d in active_drains), default=0)
        result['phases'][group] = part
    print(folder.name, 'P95', round(result['receipt_to_paint_ms']['p95'], 2),
          'dense fps', round(result['phases']['dense']['consumer_fps'], 2),
          'slope', round(result['phases']['dense']['age_slope_ms_per_device_second'], 2), flush=True)
    return result


def main():
    plan = read(HERE / 'plan.json')
    assert hashlib.sha256((HERE / 'plan.json').read_bytes()).hexdigest() == (HERE / 'plan.sha256').read_text().strip()
    folders = sorted(p for p in (HERE / 'runs').glob('aa_*') if (p / 'diagnostic.json').exists())
    runs = {p.name: metrics(p) for p in folders}
    output = {'runs': runs, 'calibration': {}}
    for mode in ('run', 'walk'):
        pairs = []
        for block in range(1, 7):
            m = runs.get(f'aa_{mode}_{block:02d}_M')
            d = runs.get(f'aa_{mode}_{block:02d}_D')
            if not m or not d:
                continue
            assert m['canonical_report_sha256'] == d['canonical_report_sha256']
            assert m['canonical_evidence_sha256'] == d['canonical_evidence_sha256']
            pairs.append({'block': block,
                          'fps_fraction_change': d['phases']['dense']['consumer_fps'] / m['phases']['dense']['consumer_fps'] - 1,
                          'slope_change': d['phases']['dense']['age_slope_ms_per_device_second'] - m['phases']['dense']['age_slope_ms_per_device_second'],
                          'p95_change_ms': d['receipt_to_paint_ms']['p95'] - m['receipt_to_paint_ms']['p95']})
        if pairs:
            medians = {k: float(np.median([p[k] for p in pairs])) for k in ('fps_fraction_change', 'slope_change', 'p95_change_ms')}
            limits = plan['calibration']['limits']
            passed = len(pairs) == 6 and (abs(medians['fps_fraction_change']) <= limits['median_paired_fps_absolute_change_max_fraction']
                                        and abs(medians['slope_change']) <= limits['median_paired_age_slope_absolute_change_max_ms_per_device_second']
                                        and abs(medians['p95_change_ms']) <= limits['median_paired_p95_absolute_change_max_ms'])
            output['calibration'][mode] = {'pairs': pairs, 'paired_medians': medians, 'pass': passed,
                                            'scope': 'Incremental D versus M observer disturbance, not absolute zero-observer overhead or statistical equivalence'}
    (HERE / 'summary.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output['calibration'], indent=2))


if __name__ == '__main__':
    main()
