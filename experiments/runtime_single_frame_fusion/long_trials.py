"""Conditional long GUI tests; preserve and expose the existing report cache limit."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import numpy as np
from windows_run import task, transfer, fetch, HOST, REMOTE, REL, HERE


def verify(folder, seconds):
    probe = json.loads((folder / 'probe.json').read_text())
    timing = json.loads((folder / 'timing.json').read_text(encoding='utf-8'))
    report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
    source = HERE / 'stress_sources' / str(seconds)
    assert timing['finished'] and not timing['errors'], (folder.name, timing['errors'])
    expected_count = 3501 + seconds * 1000
    with np.load(folder / 'raw_frames.npz') as raw, np.load(source / 'raw_frames.npz') as expected:
        for key in ('sample_indices', 'frame_indices', 'bits', 'wire'):
            assert np.array_equal(raw[key], expected[key]), (folder.name, key)
        assert len(raw['sample_indices']) == expected_count
        assert np.array_equal(raw['bits'], 1 - np.unpackbits(raw['wire'], axis=1, bitorder='little'))
        checked_ns = int(raw['received_ns'][3500])
    snapshot = report['report_config_snapshot']
    checked = snapshot['device']['checked_sample_index']
    for branch in (snapshot['device'], snapshot['beam_quality']['preflight']):
        assert branch['checked_monotonic_ns'] == checked_ns
        del branch['checked_monotonic_ns']
    raw_buffer = snapshot['raw_buffer']
    assert raw_buffer['total_received_frames'] == seconds * 1000
    assert raw_buffer['retained_frames'] == min(seconds * 1000, (64 * 1024 * 1024) // (768 + 64))
    assert raw_buffer['truncated'] == (raw_buffer['retained_frames'] < seconds * 1000)
    last = checked - 3501
    for batch in probe['queues']:
        last += batch[2]
        assert last == batch[3]
    assert last == checked + seconds * 1000
    assert probe['source_hashes'] == json.loads((HERE / 'baseline_manifest.json').read_text())['base_files']
    for name, sha in probe['artifact_hashes'].items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == sha
    # Fixed observation window declared before long measurements: omit first 5s
    # after arm and the final 1s, without using the EOF drain as a success signal.
    batches = [b for b in probe['queues'] if checked + 5000 <= b[3] <= last - 1000]
    assert len(batches) > 100
    x, age = np.array([b[3] / 1000 for b in batches]), np.array([b[4] for b in batches])
    middle = (x[0] + x[-1]) / 2
    result = {'variant': probe['runtime'], 'raw_source_order_exact': True,
              'canonical_report_sha256': hashlib.sha256(json.dumps(report, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
              'report_raw_buffer': raw_buffer, 'receipt_to_paint_ms': timing['received_to_paint_ms'],
              'age_slope_ms_per_device_second': float(np.polyfit(x, age, 1)[0]),
              'first_half_age_median_ms': float(np.median(age[x <= middle])),
              'last_half_age_median_ms': float(np.median(age[x > middle])),
              'first_half_age_peak_ms': float(max(age[x <= middle])),
              'last_half_age_peak_ms': float(max(age[x > middle])),
              'peak_pending': max(s[1] for s in probe['samples']),
              'last_pending_before_eof': next(s[1] for s in reversed(probe['samples']) if s[0] < timing['source_exhausted_host_ns']),
              'rendered_frames': sum(s[0] == 'preview_prepare' for s in probe['spans']),
              'inference_frames': sum(s[0] == 'inference' for s in probe['spans']),
              'camera': timing['camera_replay_stats']}
    assert all(r.get('ui_paint_completed_host_ns') is not None for r in timing['rows'])
    return result


def main(seconds, winner):
    short = json.loads((HERE / 'gui_summary.json').read_text())
    eligible = [v for v, c in short['candidates'].items()
                if c['repeated_improvement_pass'] and c['short_realtime_pass']]
    assert eligible, 'No candidate met both frozen short-window gates'
    if seconds == 300:
        assert winner in eligible
        prior = json.loads((HERE / 'long_60_summary.json').read_text())
        assert prior['candidates'][winner]['age_slope_all_runs_pass'], '60-second queue gate failed'
    for filename in ('prepare_stress.py', 'long_trials.py'):
        transfer(HERE / filename, f'{HOST}:{REMOTE}/{REL}/{filename}')
    sequence = list('ABCCBAABC') if seconds == 60 else ['A', winner, winner, 'A', 'A', winner]
    plan = {'seconds': seconds, 'sequence': sequence, 'steady_window': 'checked_sample+5000 through last_sample-1000',
            'source': 'labelled synthetic continuous 1000Hz, recorded JPEG loops at 30fps',
            'queue_gate': 'each slope <=1ms/device-second; also inspect halves/peaks and pending before EOF',
            'report_cache': 'existing 64MiB budget unchanged; all received raw frames separately verified against source'}
    (HERE / f'long_{seconds}_plan.json').write_text(json.dumps(plan, indent=2))
    task(f'prepare_stress_{seconds}', f"'{REMOTE}/{REL}/prepare_stress.py' {seconds}", platform='offscreen', minutes=3)
    source = HERE / 'stress_sources' / str(seconds)
    source.mkdir(parents=True, exist_ok=True)
    for filename in ('raw_frames.npz', 'construction.json'):
        transfer(f'{HOST}:{REMOTE}/{REL}/stress_sources/{seconds}/{filename}', source / filename)
    for filename in ('stress_gui_probe.py', 'stress_replay.py'):
        transfer(f'{HOST}:{REMOTE}/{REL}/{filename}', HERE / filename)
    runs = {}
    for index, variant in enumerate(sequence, 1):
        name = f'long_{seconds}_{index:02d}_{variant}'
        task(name, f"'{REMOTE}/{REL}/stress_gui_probe.py' --variant {variant} --source offline --input '{REMOTE}/{REL}/stress_sources/{seconds}' --mode run --seconds {seconds} --paint gui_final_v2 --cache-file '{REMOTE}/{REL}/fixed_geometry_cache.py' --cadence recorded --camera-replay --output '{REMOTE}/{REL}/{name}'", minutes=seconds // 60 + 4)
        fetch(name)
        runs[name] = verify(HERE / name, seconds)
        assert len({r['canonical_report_sha256'] for r in runs.values()}) == 1, 'Long full report differs'
        (HERE / f'long_{seconds}_progress.json').write_text(json.dumps(runs, indent=2))
    candidates = {}
    for variant in set(sequence) - {'A'}:
        subset = [r for r in runs.values() if r['variant'] == variant]
        candidates[variant] = {'age_slope_all_runs_pass': all(r['age_slope_ms_per_device_second'] <= 1 for r in subset),
                               'median_age_slope_ms_per_device_second': statistics.median(r['age_slope_ms_per_device_second'] for r in subset)}
    (HERE / f'long_{seconds}_summary.json').write_text(json.dumps({'runs': runs, 'candidates': candidates}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('seconds', type=int, choices=(60, 300))
    parser.add_argument('--winner', choices=('B', 'C'))
    args = parser.parse_args()
    main(args.seconds, args.winner)
