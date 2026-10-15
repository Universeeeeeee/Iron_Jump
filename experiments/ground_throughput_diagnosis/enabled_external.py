"""Independent profiler runs; do not use sampled/native rounds as baseline latency."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'experiments/runtime_single_frame_fusion'


def main(mode, kind, sequence):
    source = {'run': 'field_run_20261015_02', 'walk': 'field_walk_full_02'}[mode]
    name = f'enabled_external_{mode}_{kind}_{sequence:02d}'
    output = HERE / 'runs' / name
    assert not output.exists()
    phase = json.loads((HERE / 'phases.json').read_text())[mode]
    dense = [w for w in phase['windows'] if w['phase'] == 'dense']
    with np.load(ROOT / 'exports/ground_boundary_latency_20261014' / source / 'raw_frames.npz') as raw:
        ns = raw['received_ns']
        indices = raw['sample_indices']
        start_delay_ns = int(ns[np.searchsorted(indices, dense[0]['start'])] - ns[np.searchsorted(indices, phase['checked'])])
    duration = len(dense)
    command = [sys.executable, str(HERE / 'state_target.py'), '--preview-state', 'enabled', '--level', 'M', '--source', 'offline',
               '--input', str(ROOT / 'exports/ground_boundary_latency_20261014' / source),
               '--mode', mode, '--paint', 'gui_final_v2', '--cache-file', str(OLD / 'fixed_geometry_cache.py'),
               '--cadence', 'recorded', '--camera-replay', '--output', str(output)]
    started = time.perf_counter_ns()
    sampler = None
    with (HERE / (name + '.log')).open('xb') as stream:
        target = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while not (output / 'pid.json').exists():
                if target.poll() is not None:
                    raise RuntimeError('Replay exited before PID marker')
                if time.monotonic() > deadline:
                    raise TimeoutError('PID marker')
                time.sleep(.02)
            marker = json.loads((output / 'pid.json').read_text())
            assert marker['pid'] == target.pid
            if kind == 'gil':
                # Sample the scheduled dense phase, using the already-existing arm marker.
                while not (output / 'armed.json').exists():
                    assert target.poll() is None
                    assert time.monotonic() <= deadline
                    time.sleep(.01)
                armed = json.loads((output / 'armed.json').read_text())
                while time.perf_counter_ns() < armed['host_ns'] + start_delay_ns:
                    assert target.poll() is None
                    time.sleep(.005)
            profiler = [str(HERE / 'tools/py-spy.exe'), 'record', '--pid', str(target.pid),
                        '--format', 'speedscope' if kind == 'gil' else 'chrometrace',
                        '--full-filenames', '--threads', '--idle',
                        '--rate', '49' if kind == 'native' else '99',
                        '--output', str(output / 'profile.json')]
            if kind == 'gil':
                profiler += ['--gil', '--nonblocking', '--duration', str(duration)]
            elif kind == 'all':
                profiler += ['--nonblocking', '--duration', '35']
            else:
                profiler += ['--native', '--duration', '35']
            sample_start = time.perf_counter_ns()
            with (output / 'sampler.log').open('xb') as sample_stream:
                sampler = subprocess.Popen(profiler, stdout=sample_stream, stderr=subprocess.STDOUT)
                target_result = target.wait(timeout=90)
                sampler_result = sampler.wait(timeout=30)
            (output / 'external_marker.json').write_text(json.dumps({
                'kind': kind, 'started_ns': started, 'sampler_request_ns': sample_start,
                'finished_ns': time.perf_counter_ns(), 'target_pid': target.pid,
                'target_result': target_result, 'sampler_result': sampler_result,
                'command': profiler,
                'sample_phase': 'scheduled_dense' if kind == 'gil' else 'whole_replay',
                'dense_start_delay_ns_after_arm': start_delay_ns,
                'requested_dense_duration_seconds': duration,
                'scope': 'External corroboration only. GIL Speedscope weights count captured samples, not continuous occupancy; Chrome traces bridge filtered/missed samples and are not used to calculate GIL-held durations. Nonblocking samples may race; native samples suspend the target and can perturb timing. Attach offset and arm-marker lag are not assumed zero.'
            }, indent=2) + '\n')
            print(name, 'target', target_result, 'sampler', sampler_result, flush=True)
            assert target_result == 0 and sampler_result == 0
        finally:
            if target.poll() is None:
                target.terminate()
                target.wait(timeout=10)
            if sampler is not None and sampler.poll() is None:
                sampler.terminate()
                sampler.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('run', 'walk'), required=True)
    parser.add_argument('--kind', choices=('gil', 'all', 'native'), required=True)
    parser.add_argument('--sequence', type=int, default=1)
    args = parser.parse_args()
    main(args.mode, args.kind, args.sequence)
