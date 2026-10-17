"""Offline reconstruction. Scheduled residency is never renamed exclusive CPU time."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TRIALS = HERE.parent / 'single_usb_human_etw/runs'
NAMES = ['20261017_112623_8416401b_walk_on', '20261017_113358_00ae9eca_walk_on']
DT = np.dtype([('qpc', '<i8'), ('cpu', '<u2'), ('opcode', 'u1'), ('version', 'u1'),
               ('header_tid', '<u4'), ('header_pid', '<u4'), ('payload', 'u1', 24),
               ('length', '<u2'), ('flags', '<u2')])
SDT = np.dtype([('start', '<i8'), ('end', '<i8'), ('state', 'U12'), ('reason', 'i2')])
PDT = np.dtype([('start', '<i8'), ('end', '<i8'), ('state', 'i2'), ('reason', 'i2')])
STATES = ('Running', 'Ready', 'Waiting', 'Transition', 'Unknown')
spec = importlib.util.spec_from_file_location('queue_analysis', HERE.parent / 'single_usb_field/analyze.py')
queue_analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue_analysis)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def stats(values):
    return {'count': len(values), 'p95': float(np.percentile(values, 95)), 'max': float(np.max(values))} if len(values) else {'count': 0, 'p95': None, 'max': None}


def reconstruct(cs, ids, ready, tid, factor):
    """Pair in/out, then split nonrunning gaps at actual ReadyThread events.

    Standby/DeferredReady count as dispatch-eligible Ready. State=Running on an
    outgoing record is left Transition until ReadyThread, not silently relabeled.
    Ready events may precede the outgoing CSwitch during cross-CPU wakeup races.
    """
    indices = np.flatnonzero((ids[:, 0] == tid) | (ids[:, 1] == tid))
    segments, pauses = [], []
    rt = ready * factor
    for left, right in zip(indices, indices[1:]):
        start, end = int(cs['qpc'][left]) * factor, int(cs['qpc'][right]) * factor
        assert end >= start
        if ids[left, 0] == tid and ids[right, 1] == tid:
            assert cs['cpu'][left] == cs['cpu'][right], 'Running thread migrated without CSwitch'
            segments.append((start, end, 'Running', -1))
        else:
            assert ids[left, 1] == tid and ids[right, 0] == tid, 'Broken per-thread switch alternation'
            old_state, reason = map(int, cs['payload'][left, [14, 12]])
            j = np.searchsorted(rt, start)
            wake = int(rt[j]) if j < len(rt) and rt[j] <= end else None
            if old_state in (1, 3, 7):
                segments.append((start, end, 'Ready', reason))
            elif wake is not None:
                segments += [(start, wake, 'Waiting' if old_state == 5 else 'Transition', reason),
                             (wake, end, 'Ready', reason)]
            else:
                segments.append((start, end, 'Unknown' if old_state == 5 else 'Transition', reason))
            pauses.append((start, end, old_state, reason))
    result = np.array(segments, dtype=SDT)
    assert np.all(result['end'][:-1] == result['start'][1:]), 'Gap/overlap in reconstructed coverage'
    return result, np.array(pauses, dtype=PDT)


def summarize(segments, pauses, start, end):
    clipped = np.maximum(0, np.minimum(segments['end'], end) - np.maximum(segments['start'], start))
    seconds = {state: float(clipped[segments['state'] == state].sum() / 1e9) for state in STATES}
    assert abs(sum(seconds.values()) - (end - start) / 1e9) < 1e-7, 'Window not covered'
    result = {'seconds': seconds, 'fraction': {k: v / ((end - start) / 1e9) for k, v in seconds.items()}}
    for state in ('Running', 'Ready', 'Waiting'):
        mask = (clipped > 0) & (segments['state'] == state)
        result[state + '_interval_ms'] = stats((segments['end'][mask] - segments['start'][mask]) / 1e6)
    mask = (pauses['end'] > start) & (pauses['start'] < end)
    duration = (pauses['end'][mask] - pauses['start'][mask]) / 1e6
    result['nonrunning_pause_ms'] = stats(duration)
    result['pauses_ge_50ms'] = int((duration >= 50).sum())
    result['pauses_4_to_6ms'] = int(((duration >= 4) & (duration <= 6)).sum())
    result['waiting_seconds_by_raw_reason'] = {str(int(v)): float(clipped[(segments['state'] == 'Waiting') & (segments['reason'] == v)].sum() / 1e9)
                                             for v in np.unique(segments['reason'][segments['state'] == 'Waiting'])}
    return result


def join_batch_snapshots(segments, rows, start, end):
    matches = []
    for row in rows:
        if not (start <= row[0] < end and row[3] >= 100 and row[9] == 'batch'):
            continue
        index = int(np.searchsorted(segments['start'], row[0], side='right')) - 1
        segment = segments[index]
        assert segment['start'] <= row[0] < segment['end']
        margin = min(row[0] - int(segment['start']), int(segment['end']) - row[0])
        # Conservative 0.1 ms guard, larger than observed clock-anchor residuals.
        if margin >= 100000:
            matches.append({'host_ns': row[0], 'pending': row[3], 'state': str(segment['state']),
                            'state_boundary_margin_ms': margin / 1e6,
                            'batch': [row[10], row[11], row[12]]})
    return {'guarded_observations': matches,
            'scope': '100ms Python queue observer can itself perturb GIL scheduling. These are phase witnesses, not unbiased waiting fractions or proof of GIL ownership.'}


def validate_clock(meta, native):
    frequency = meta['qpc_frequency']
    assert meta['clock_type'] == 1 and 1000000000 % frequency == 0
    factor = 1000000000 // frequency
    offsets = [s['utc_filetime_100ns'] - s['qpc'] * 10000000 // frequency for s in meta['clock_samples']]
    assert max(offsets) == min(offsets), 'Windows raw/UTC conversion is not constant'
    offset = offsets[0]
    anchors = []
    for batch in native['clock_brackets']:
        for anchor in batch.values():
            predicted = (anchor['utc_filetime_100ns'] - offset) * 100
            middle = (anchor['perf_before_ns'] + anchor['perf_after_ns']) // 2
            anchors.append({'residual_ns': predicted - middle,
                            'perf_bracket_width_ns': anchor['perf_after_ns'] - anchor['perf_before_ns']})
    assert max(abs(v['residual_ns']) for v in anchors) < 1000000, 'Clock disagreement exceeds 1 ms'
    return factor, {'raw_to_perf_ns_factor': factor, 'windows_conversion_offset_filetime_100ns': offset,
                    'paired_raw_and_windows_UTC_events': len(offsets), 'conversion_offset_range_100ns': max(offsets) - min(offsets),
                    'saved_anchor_residuals': anchors, 'max_abs_anchor_residual_ns': max(abs(v['residual_ns']) for v in anchors),
                    'scope': 'Raw QPC versus Python perf and saved FILETIME brackets; XML timezone strings and header BootTime are not used.'}


def native_cpu_check(segments, pauses, native, role):
    windows = []
    for a in native['clock_brackets']:
        windows.append((a['before']['perf_before_ns'], a['after']['perf_after_ns']))
    before, after = native['start'][role], native['end'][role]
    assert before['tid'] == after['tid']
    midpoint_run = summarize(segments, pauses, sum(windows[0]) // 2, sum(windows[1]) // 2)['seconds']['Running']
    minimum_run = summarize(segments, pauses, windows[0][1], windows[1][0])['seconds']['Running']
    maximum_run = summarize(segments, pauses, windows[0][0], windows[1][1])['seconds']['Running']
    cpu = sum(after[k] - before[k] for k in ('kernel_100ns', 'user_100ns')) / 1e7
    return {'tid': before['tid'], 'GetThreadTimes_seconds': cpu, 'ETW_scheduled_residency_seconds': midpoint_run,
            'ETW_residency_boundary_bounds_seconds': [minimum_run, maximum_run],
            'residency_minus_CPU_seconds': midpoint_run - cpu, 'relative_difference': midpoint_run / cpu - 1,
            'within_5_percent_audit_indicator': abs(midpoint_run / cpu - 1) <= .05,
            'scope': '5% is an audit flag, not a changed trial acceptance gate. Residency is not exclusive CPU; no normalization or forced equality.'}


def trial(name):
    evidence, capture = HERE / 'evidence' / name, TRIALS / name / 'capture'
    meta, m, native = read(evidence / 'metadata.json'), read(capture / 'measurement.json'), read(capture / 'native_cpu.json')
    validation = read(TRIALS / name / 'schedule_trace_validation.json')
    assert meta['source_etl_sha256'] == validation['etl_sha256'] and sha(evidence / 'schedule.bin') == meta['binary_sha256']
    assert all(meta[k] == 0 for k in ('header_events_lost', 'buffers_lost', 'consumer_events_lost'))
    factor, clock = validate_clock(meta, native)
    x = np.fromfile(evidence / 'schedule.bin', dtype=DT)
    assert len(x) == meta['event_count'] and np.all(np.diff(x['qpc']) >= 0)
    cs, rt = x[x['opcode'] == 36], x[x['opcode'] == 50]
    assert len(cs) == validation['event_counts']['CSwitch'] and len(rt) == validation['event_counts']['ReadyThread']
    assert np.all(cs['version'] == 5) and np.all(cs['length'] == 28) and np.all(rt['version'] == 2) and np.all(rt['length'] == 8)
    ids = np.ascontiguousarray(cs['payload']).view('<u4').reshape(-1, 6)
    ready_ids = np.ascontiguousarray(rt['payload']).view('<u4').reshape(-1, 6)[:, 0]
    for cpu in np.unique(cs['cpu']):
        index = np.flatnonzero(cs['cpu'] == cpu)
        assert np.array_equal(ids[index[:-1], 0], ids[index[1:], 1]), 'Per-CPU scheduling chain broken'
    life = np.genfromtxt(evidence / 'thread_lifecycle.csv', delimiter=',', names=True, dtype=np.int64)
    points = sorted(m['queue_common'] + m['queue_samples'] + [m['queue_final']], key=lambda row: row[0])
    a = read(capture / 'analysis.json')
    armed, stop = m['armed_ns'], m['stop_request_ns']
    raw = np.load(capture / 'raw_frames.npz')
    bits = raw['bits'].copy()
    bits[:, a['bad_indices']] = 0
    beam_count = bits.sum(axis=1)
    samples, receipts = raw['sample_indices'], raw['received_ns']
    formal = (receipts >= armed) & (receipts < stop)
    origin = int(samples[np.flatnonzero(formal)[0]])
    dense_bins = [v['device_second'] for v in a['device_contact_bins'] if v['phase'] == 'dense']
    assert dense_bins == list(range(dense_bins[0], dense_bins[-1] + 1)), 'Review disjoint blocks separately'
    dense_start = int(receipts[np.searchsorted(samples, origin + dense_bins[0] * 1000)])
    dense_end = int(receipts[np.searchsorted(samples, origin + (dense_bins[-1] + 1) * 1000)])
    complete_start_index = next(i for i, row in enumerate(points) if row[1] >= origin + dense_bins[0] * 1000)
    complete_end_index = next(i for i, row in enumerate(points) if row[1] >= origin + (dense_bins[-1] + 1) * 1000)
    complete_start, complete_end = points[complete_start_index][0], points[complete_end_index][0]
    windows = {'whole_formal': (armed, stop), 'initial_empty': (armed, armed + 5000000000),
               'primary_3_19': (armed + 3000000000, armed + 19000000000),
               'input_dense': (dense_start, dense_end), 'completed_dense_sample_span': (complete_start, complete_end)}
    tids = {role: item['tid'] for role, item in native['start'].items()}
    role_results, schedules = {}, {}
    for role, tid in tids.items():
        records = life[life['tid'] == tid]
        assert set(records['pid']) == {m['pid']}, 'Thread ownership mismatch'
        assert not np.any((records['opcode'] == 2) & (records['qpc'] * factor < stop)), 'Target ended during formal capture'
        segments, pauses = reconstruct(cs, ids, rt['qpc'][ready_ids == tid], tid, factor)
        schedules[role] = (segments, pauses)
        long_order = np.argsort(pauses['end'] - pauses['start'])[::-1]
        longest = []
        for index in long_order:
            pause = pauses[index]
            if pause['start'] >= stop or pause['end'] <= armed:
                continue
            row = min(points, key=lambda r: abs(r[0] - int(pause['start'])))
            longest.append({'start_formal_s': (int(pause['start']) - armed) / 1e9,
                            'duration_ms': (int(pause['end']) - int(pause['start'])) / 1e6,
                            'old_state': int(pause['state']), 'old_wait_reason': int(pause['reason']),
                            'nearest_queue_pending': row[3], 'nearest_queue_snapshot_delta_ms': (row[0] - int(pause['start'])) / 1e6})
            if len(longest) == 12:
                break
        role_results[role] = {'tid': tid, 'owner_pid_verified': m['pid'],
                              'windows': {key: summarize(segments, pauses, *bounds) for key, bounds in windows.items()},
                              'CPU_cross_check': native_cpu_check(segments, pauses, native, role), 'longest_nonrunning_pauses': longest}
    snapshots = [{'host_ns': armed, 'visual': m['visual_start']}] + m['telemetry'] + [{'host_ns': stop, 'visual': m['visual_end']}]
    seconds = []
    for second in range(int((stop - armed) // 1000000000)):
        start, end = armed + second * 1000000000, armed + (second + 1) * 1000000000
        q = queue_analysis.window(points, start, end)
        incoming = (receipts >= start) & (receipts < end)
        rows = [row for row in points if start <= row[0] < end]
        first, last = rows[0][1], rows[-1][1]
        consumed = (samples > first) & (samples <= last)
        seconds.append({'second': second, 'queue': q,
                        'received_frames': int(incoming.sum()), 'input_contact_fraction': float((beam_count[incoming] > 0).mean()),
                        'completed_frames_from_snapshot_bounds': int(consumed.sum()),
                        'completed_contact_fraction': float((beam_count[consumed] > 0).mean()) if consumed.any() else None,
                        'completed_mean_active_beams': float(beam_count[consumed].mean()) if consumed.any() else None,
                        'threads': {role: summarize(*data, start, end) for role, data in schedules.items()}})
    visual_intervals = []
    for left, right in zip(snapshots, snapshots[1:]):
        visual_intervals.append({'start_formal_s': (left['host_ns'] - armed) / 1e9,
                                 'end_formal_s': (right['host_ns'] - armed) / 1e9,
                                 'actual_visual_delta': {k: right['visual'][k] - left['visual'][k] for k in left['visual']}})
    workload_windows = {}
    for label, (start, end) in windows.items():
        mask = (receipts >= start) & (receipts < end)
        internal = [r for r in visual_intervals if r['start_formal_s'] >= (start - armed) / 1e9
                    and r['end_formal_s'] <= (end - armed) / 1e9]
        observed = sum(r['end_formal_s'] - r['start_formal_s'] for r in internal)
        workload_windows[label] = {'received_frames': int(mask.sum()),
                                  'input_contact_fraction': float((beam_count[mask] > 0).mean()),
                                  'input_mean_active_beams': float(beam_count[mask].mean()),
                                  'input_max_active_beams': int(beam_count[mask].max()),
                                  'visual_internal_observed_seconds': observed,
                                  'visual_internal_totals': {k: sum(r['actual_visual_delta'][k] for r in internal)
                                                            for k in m['visual_start']},
                                  'visual_scope': 'Only fully contained existing 1Hz telemetry intervals, without interpolating or double-counting boundaries.'}
    return {'case': name, 'pid': m['pid'], 'decode_checks': {'CSwitch': len(cs), 'ReadyThread': len(rt),
            'per_CPU_chain_mismatches': 0, 'supported_shapes': meta['payload_shapes'],
            'ReadyThread_header_tid_unknown_fraction': float((rt['header_tid'] == 4294967295).mean()),
            'schema_note': 'Classic v5 28-byte CSwitch shares documented >=v2 prefix; unknown trailing 4 bytes not interpreted. ReadyThread v2 8-byte layout. First 24 bytes retained, source ETL untouched.'},
            'clock_validation': clock,
            'completed_dense_boundary_observation_brackets_formal_s': [[(points[i - 1][0] - armed) / 1e9, (points[i][0] - armed) / 1e9]
                                                                      for i in (complete_start_index, complete_end_index)],
            'window_formal_seconds': {k: [(s - armed) / 1e9, (e - armed) / 1e9] for k, (s, e) in windows.items()},
            'queue_windows': {k: queue_analysis.window(points, *v) for k, v in windows.items()},
            'workload_windows': workload_windows,
            'batch_phase_native_state_join': {k: join_batch_snapshots(schedules['consumer'][0], m['queue_samples'], *bounds)
                                              for k, bounds in windows.items()},
            'roles': role_results, 'per_second': seconds, 'actual_visual_intervals': visual_intervals,
            'source_hashes': {str(p): sha(p) for p in [evidence / 'metadata.json', evidence / 'thread_lifecycle.csv', capture / 'measurement.json', capture / 'native_cpu.json']}}


def main(output):
    assert not output.exists(), 'Never overwrite earlier analysis'
    output.mkdir(parents=True)
    results = [trial(name) for name in NAMES]
    result = {'scope': 'Offline existing Walk four-trial diagnosis. ETW thread-state evidence belongs only to ON2/ON3.',
              'ON_trials': results, 'four_trial_queue_load_review': read(HERE.parent / 'single_usb_human_etw/walking_block01_review.json'),
              'limits': ['No ISR/DPC intervals, call stacks, CPU samples, GIL or GC events were requested by the capture profile.',
                         'Scheduled CPU residency includes time not charged by GetThreadTimes; six comparisons are reported without forcing agreement.',
                         'ReadyThread header does not identify waker TID in these classic events; do not infer who held/released a lock.',
                         'Qt callback execution and mutex ownership are not captured; Waiting does not identify a particular blocking primitive.',
                         'Input-dense and consumer-completed-dense windows differ when backlog exists. Completion boundaries are batch observations.',
                         'No scheduler records exist for OFF1/OFF4. ON state patterns must not be copied onto OFF.' ]}
    (output / 'diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for trial_result in results:
        print(trial_result['case'], trial_result['clock_validation'])
        for role, r in trial_result['roles'].items():
            print(role, r['windows']['input_dense']['fraction'], r['CPU_cross_check'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    main(parser.parse_args().output)
