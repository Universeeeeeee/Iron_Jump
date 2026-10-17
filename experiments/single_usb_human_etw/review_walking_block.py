"""Offline review of the four completed walking trials; never imported by capture."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('field_analysis', HERE.parent / 'single_usb_field/analyze.py')
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
spec = importlib.util.spec_from_file_location('trial_integrity', HERE / 'verify_trial.py')
integrity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integrity)
CASES = [
    '20261017_111818_dc83b931_walk_off',
    '20261017_112623_8416401b_walk_on',
    '20261017_113358_00ae9eca_walk_on',
    '20261017_113916_32a7af0d_walk_off',
]


def review(name):
    case = HERE / 'runs' / name
    folder = case / 'capture'
    read = analysis.read
    checked = integrity.verify(folder)
    m = read(folder / 'measurement.json')
    a = read(folder / 'analysis.json')
    points = sorted(m['queue_common'] + m['queue_samples'] + [m['queue_final']], key=lambda r: r[0])
    formal_points = [r for r in points if m['armed_ns'] <= r[0] < m['stop_request_ns']]
    with np.load(folder / 'raw_frames.npz') as z:
        samples, received = z['sample_indices'], z['received_ns']
    with np.load(folder / 'raw_archive.npz') as z:
        ticks = np.rint(z['device_timestamps'] * 1000).astype(np.int64)
    host = received[np.searchsorted(samples, ticks)]
    origin = ticks[np.flatnonzero(host >= m['armed_ns'])[0]]
    blocks = []
    for row in a['device_contact_bins']:
        if row['phase'] == 'dense':
            second = row['device_second']
            if not blocks or second != blocks[-1][-1] + 1:
                blocks.append([second])
            else:
                blocks[-1].append(second)
    snapshots = [{'host_ns': m['armed_ns'], 'visual': m['visual_start']}]
    snapshots += m['telemetry'] + [{'host_ns': m['stop_request_ns'], 'visual': m['visual_end']}]
    dense = []
    for block in blocks:
        if len(block) < 2:
            continue
        start = int(host[np.searchsorted(ticks, origin + block[0] * 1000)])
        end = int(host[np.searchsorted(ticks, origin + (block[-1] + 1) * 1000)])
        result = analysis.window(points, start, end)
        result['device_seconds_inclusive'] = [block[0], block[-1]]
        result['pose_intervals'] = [
            {'end_formal_s': (right['host_ns'] - m['armed_ns']) / 1e9,
             **{k: right['visual'][k] - left['visual'][k]
                for k in ('valid_pose_draws', 'valid_nodes_drawn', 'valid_links_drawn')}}
            for left, right in zip(snapshots, snapshots[1:])
            if right['host_ns'] > start and left['host_ns'] < end
        ]
        witness = next((r for r in points if r[0] >= end and r[3] == r[7] == 0), None)
        result['first_empty_witness_after_dense_end_ms'] = (witness[0] - end) / 1e6 if witness else None
        result['empty_witness_scope'] = 'Sampled upper bound from density-bin end, not exact physical passage end or exact drain time.'
        dense.append(result)
    duration = (m['stop_request_ns'] - m['armed_ns']) / 1e9
    native = read(folder / 'native_cpu.json')
    cpu = {}
    for role, begin in native['start'].items():
        finish = native['end'][role]
        assert begin['tid'] == finish['tid']
        cpu[role] = sum(finish[k] - begin[k] for k in ('kernel_100ns', 'user_100ns')) / 1e7
    primary = analysis.window(points, m['armed_ns'] + 3000000000, m['armed_ns'] + 19000000000)
    bracket = read(folder / 'camera_record_start.json')
    camera_origin = (bracket['before_ns'] + bracket['after_ns']) / 2
    with (folder / 'camera.csv').open() as f:
        camera = list(csv.DictReader(f))
    camera_count = sum(m['armed_ns'] + 3000000000 <= camera_origin + float(r['record_elapsed_seconds']) * 1e9
                       < m['armed_ns'] + 19000000000 for r in camera)
    receipt_mask = (received >= m['armed_ns']) & (received < m['stop_request_ns'])
    result = {
        'case': name, 'trace': read(case / 'case.json')['trace'],
        'integrity': checked, 'human_ground_truth': read(case / 'human_observation.json'),
        'duration_s': duration, 'initial_empty': a['windows']['initial_empty'],
        'primary_host_3_to_19_s': primary, 'dense_blocks': dense,
        'whole_formal': a['windows']['whole_formal'],
        'footprint_receipt_to_paint_ms': a['footprint_receipt_to_paint_ms'],
        'actual_visual_formal': a['visual_formal'],
        'whole_formal_render_fps': a['visual_formal']['renders'] / duration,
        'native_recorded_primary_fps': camera_count / 16,
        'camera_alignment_scope': 'Start perf bracket midpoint; no drift correction.',
        'formal_SDK_nonzero_speeds': m['SDK_end']['nonzero_speeds'] - m['SDK_start']['nonzero_speeds'],
        'native_thread_cpu_seconds': cpu,
        'native_cpu_scope': 'Only GUI, consumer and reader threads; approximately arm-to-stop. Not whole-process/system CPU or exclusive Python stage time.',
        'max_formal_receipt_gap_ms': float(np.max(np.diff(received[receipt_mask])) / 1e6),
        'last_formal_observed_pending': formal_points[-1][3],
        'last_formal_observation_before_stop_ms': (m['stop_request_ns'] - formal_points[-1][0]) / 1e6,
        'stop_request_to_callback_s': (m['stop_callback_ns'] - m['stop_request_ns']) / 1e9,
        'stop_callback_scope': 'Includes original stopping/draining work; not isolated queue drain cost.',
        'queue_final_empty': m['queue_final'][3] == m['queue_final'][7] == 0,
    }
    etw = case / 'schedule_trace_validation.json'
    result['ETW_validation'] = read(etw) if etw.exists() else None
    return result


def main(output):
    assert not output.exists(), 'Preserve earlier reviews; choose a new output path.'
    trials = [review(name) for name in CASES]
    pairs = []
    for off, on in ((trials[0], trials[1]), (trials[3], trials[2])):
        x, y = off['primary_host_3_to_19_s'], on['primary_host_3_to_19_s']
        delta = y['consumer_fps'] - x['consumer_fps']
        head_delta = y['oldest_pending_ms']['p95'] - x['oldest_pending_ms']['p95']
        pairs.append({'off': off['case'], 'on': on['case'],
                      'primary_consumer_delta_on_minus_off_fps': delta,
                      'primary_abs_consumer_delta_le_20fps': abs(delta) <= 20,
                      'primary_head_p95_increase_ms': head_delta,
                      'primary_head_p95_increase_le_20ms': head_delta <= 20,
                      'native_recorded_primary_fps_ratio': on['native_recorded_primary_fps'] / off['native_recorded_primary_fps'],
                      'whole_formal_render_fps_ratio': on['whole_formal_render_fps'] / off['whole_formal_render_fps'],
                      'calibration_status': 'Inconclusive: unmatched human input/bone load and incomplete whole-process CPU coverage; do not interpret numerical deltas as causal ETW overhead.'})
    result = {'scope': 'Frozen walking OFF/ON/ON/OFF block, offline review only. No production or algorithm edits.',
              'trials': trials, 'pairs': pairs, 'human_ETW_overhead_calibration': 'Not passed; differences exceed gate and inputs/load differ.',
              'conclusions': ['Sustained consumer shortage occurs with ETW disabled; tracing is not necessary for the anomaly.',
                              'Regular approximately 1000Hz enqueue coexists with dense-window consumer shortage; a purely upstream late-delivery explanation is insufficient.',
                              'ETW event presence/loss validation does not establish thread-state interpretation or GIL/GC root cause.',
                              'No new drawing A/B or optimization is justified by these captures alone.'],
              'limits': ['Raw receipt timing begins after USB reading/assembly; upstream wire timing remains unknown.',
                         'Near-camera clipping in reviewed ON samples prevents claiming continuous full-body equivalence.',
                         'CPU snapshots do not isolate DeviceQualitySession/filter/Processor computation or GIL waits.',
                         'One walking block does not prove repeatability across people or running loads.']}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for trial in trials:
        print(trial['case'], [(round(d['consumer_fps'], 1), d['sustained_shortage']) for d in trial['dense_blocks']], trial['footprint_receipt_to_paint_ms'])
    print(json.dumps(pairs, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    main(parser.parse_args().output)
