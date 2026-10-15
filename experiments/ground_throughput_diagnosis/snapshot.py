"""One bounded native snapshot per GUI replay; accepted only after semantic verification."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(mode):
    phase = json.loads((HERE / 'phases.json').read_text())[mode]
    source = ROOT / 'exports/ground_boundary_latency_20261014' / phase['source']
    first = next(w for w in phase['windows'] if w['phase'] == 'dense')['start']
    with np.load(source / 'raw_frames.npz') as raw:
        ns, indices = raw['received_ns'], raw['sample_indices']
        delay = int(ns[np.searchsorted(indices, first)] - ns[np.searchsorted(indices, phase['checked'])])
    output = HERE / 'runs' / ('snapshot_' + mode + '_01')
    assert not output.exists()
    command = [sys.executable, str(HERE / 'external_target.py'), '--level', 'M', '--source', 'offline',
               '--input', str(source), '--mode', mode, '--paint', 'gui_final_v2',
               '--cache-file', str(ROOT / 'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py'),
               '--cadence', 'recorded', '--camera-replay', '--output', str(output)]
    with (HERE / ('snapshot_' + mode + '_target.log')).open('xb') as stream:
        target = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 35
            while not (output / 'armed.json').exists():
                assert target.poll() is None
                assert time.monotonic() < deadline
                time.sleep(.01)
            arm = json.loads((output / 'armed.json').read_text())['host_ns']
            while time.perf_counter_ns() < arm + delay + 300_000_000:
                assert target.poll() is None
                time.sleep(.005)
            start = time.perf_counter_ns()
            with (output / 'native_dump.json').open('xb') as stdout, (output / 'native_dump.log').open('xb') as stderr:
                sample = subprocess.run([str(HERE / 'tools/py-spy.exe'), 'dump', '--pid', str(target.pid),
                                         '--native', '--json', '--full-filenames'],
                                        stdout=stdout, stderr=stderr, timeout=20)
            end = time.perf_counter_ns()
            result = target.wait(timeout=120)
            record = {'mode': mode, 'native_result': sample.returncode, 'target_result': result,
                      'request_ns': start, 'return_ns': end, 'snapshot_wall_ms': (end-start)/1e6,
                      'scope': 'One invasive native snapshot, not a performance trial. Full raw/report semantics must pass before considering its stack evidence.'}
            (output / 'snapshot_marker.json').write_text(json.dumps(record, indent=2) + '\n')
            print(json.dumps(record), flush=True)
        finally:
            if target.poll() is None:
                target.terminate()
                target.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('run', 'walk'), required=True)
    args = parser.parse_args()
    main(args.mode)
