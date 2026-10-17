"""Bound actual filtered-contact consumption with consumer-thread witnesses."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('schedule', HERE.parent / 'walk_etw_offline_diagnosis/analyze_schedule.py')
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)
sys.path.insert(0, str(HERE))
from replay import NAMES, read


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([int(start), int(end)])
    return result


def aggregate(segments, pauses, windows):
    parts = [schedule.summarize(segments, pauses, a, b) for a, b in windows]
    seconds = {state: sum(p['seconds'][state] for p in parts) for state in schedule.STATES}
    duration = sum(b - a for a, b in windows) / 1e9
    return {'duration_s': duration, 'seconds': seconds, 'fraction': {k: v / duration for k, v in seconds.items()},
            'longest_nonrunning_pause_intersecting_ms': max(p['nonrunning_pause_ms']['max'] or 0 for p in parts),
            'pauses_4_to_6ms': sum(p['pauses_4_to_6ms'] for p in parts),
            'waiting_seconds_by_raw_reason': {reason: sum(p['waiting_seconds_by_raw_reason'].get(reason, 0) for p in parts)
                for reason in set().union(*(p['waiting_seconds_by_raw_reason'] for p in parts))},
            'scope': 'Union of bracketed consumption intervals; Running is scheduled residency, not exclusive computation.'}


def schedules(name):
    evidence = HERE.parent / 'walk_etw_offline_diagnosis/evidence' / name
    capture = ROOT / 'experiments/single_usb_human_etw/runs' / name / 'capture'
    native = read(capture / 'native_cpu.json')
    meta = read(evidence / 'metadata.json')
    factor, clock = schedule.validate_clock(meta, native)
    assert schedule.sha(evidence / 'schedule.bin') == meta['binary_sha256']
    data = np.fromfile(evidence / 'schedule.bin', dtype=schedule.DT)
    cs, rt = data[data['opcode'] == 36], data[data['opcode'] == 50]
    ids = np.ascontiguousarray(cs['payload']).view('<u4').reshape(-1, 6)
    ready_ids = np.ascontiguousarray(rt['payload']).view('<u4').reshape(-1, 6)[:, 0]
    result = {}
    for role, item in native['start'].items():
        result[role] = schedule.reconstruct(cs, ids, rt['qpc'][ready_ids == item['tid']], item['tid'], factor)
    return result, clock


def analyze(name, maps):
    capture = ROOT / 'experiments/single_usb_human_etw/runs' / name / 'capture'
    m = read(capture / 'measurement.json')
    common = sorted(m['queue_common'] + [m['queue_final']], key=lambda r: r[0])
    assert all(r[9] != 'batch' for r in common), 'Only completed consumer witnesses are safe lower bounds'
    done = np.array([row[1] for row in common])
    host = np.array([row[0] for row in common])
    # Map outer raw sample -> actual processor frame after optical/mirror delay.
    values = np.load(maps / (name + '_output_map.npy'))
    raw = np.load(capture / 'raw_frames.npz')
    assert np.all(np.diff(values[:, 1]) == 1)
    assert len(values) == read(capture / 'report.json')['report_config_snapshot']['raw_buffer']['retained_frames']
    contact = values[:, 2] > 0
    edges = np.diff(np.r_[False, contact, False].astype(int))
    spans = list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1))
    def bracket(sample):
        j = int(np.searchsorted(done, sample, side='left'))
        assert 0 < j < len(done)
        return int(host[j - 1]), int(host[j])
    runs = []
    for first, last in spans:
        a, b = bracket(values[first, 0]), bracket(values[last, 0])
        runs.append({'processor_samples': [int(values[first, 1]), int(values[last, 1])],
                     'outer_raw_samples': [int(values[first, 0]), int(values[last, 0])],
                     'start_bounds_ns': a, 'end_bounds_ns': b})
    possible = union([(r['start_bounds_ns'][0], r['end_bounds_ns'][1]) for r in runs])
    interior = union([(r['start_bounds_ns'][1], r['end_bounds_ns'][0]) for r in runs])
    envelope = [[runs[0]['start_bounds_ns'][0], runs[-1]['end_bounds_ns'][1]]]
    envelope_inner = [[runs[0]['start_bounds_ns'][1], runs[-1]['end_bounds_ns'][0]]]
    windows = {'contact_union_outer': possible, 'contact_union_inner': interior,
               'contact_span_outer': envelope, 'contact_span_inner': envelope_inner}
    result = {'case': name, 'contact_frames': int(contact.sum()), 'contact_runs': len(runs),
              'max_filter_forwarding_lag_samples': int(np.max(values[:, 0] - values[:, 1])),
              'runs': runs, 'windows_formal_s': {k: [[(a - m['armed_ns']) / 1e9, (b - m['armed_ns']) / 1e9] for a, b in v] for k, v in windows.items()},
              'boundary_bracket_max_ms': max((r[k][1] - r[k][0]) / 1e6 for r in runs for k in ('start_bounds_ns', 'end_bounds_ns')),
              'contact_input_receipt_span_formal_s': [(int(raw['received_ns'][values[np.flatnonzero(contact)[i], 1]]) - m['armed_ns']) / 1e9 for i in (0, -1)],
              'queue_at_common_points_in_contact_span': [r for r in common if envelope[0][0] <= r[0] <= envelope[0][1]],
              'visual_intervals': []}
    snapshots = [{'host_ns': m['armed_ns'], 'visual': m['visual_start']}] + m['telemetry'] + [{'host_ns': m['stop_request_ns'], 'visual': m['visual_end']}]
    for left, right in zip(snapshots, snapshots[1:]):
        if right['host_ns'] < envelope[0][0] or left['host_ns'] > envelope[0][1]:
            continue
        result['visual_intervals'].append({'formal_s': [(v['host_ns'] - m['armed_ns']) / 1e9 for v in (left, right)],
                                           'delta': {k: right['visual'][k] - left['visual'][k] for k in left['visual']},
                                           'fully_inside_contact_span_inner': envelope_inner[0][0] <= left['host_ns'] and right['host_ns'] <= envelope_inner[0][1]})
    if name.endswith('_on'):
        roles, result['clock'] = schedules(name)
        result['threads'] = {role: {key: aggregate(*data, w) for key, w in windows.items()} for role, data in roles.items()}
        result['backlog_batch_state_witnesses'] = schedule.join_batch_snapshots(roles['consumer'][0], m['queue_samples'], *envelope_inner[0])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('maps', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert not args.output.exists()
    value = {'scope': 'Filtered usable-contact samples, not device-second input-density bins. Exact frame mapping; host completion times are brackets from consumer-thread batch completion only. No ETW extrapolation to OFF.',
             'trials': [analyze(name, args.maps) for name in NAMES]}
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
