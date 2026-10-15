"""Sequential native Windows GUI A/A; no simultaneous trials or source writes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'experiments/runtime_single_frame_fusion'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--first', type=int, default=1)
    parser.add_argument('--last', type=int, default=6)
    args = parser.parse_args()
    plan = json.loads((HERE / 'plan.json').read_text())
    assert hashlib.sha256((HERE / 'plan.json').read_bytes()).hexdigest() == (HERE / 'plan.sha256').read_text().strip()
    for block in range(args.first, args.last + 1):
        order = plan['calibration']['orders'][block - 1]
        offset = plan['calibration']['sample_offsets'][block - 1]
        for mode in ('run', 'walk'):
            for level in order:
                name = f'aa_{mode}_{block:02d}_{level}'
                output = HERE / 'runs' / name
                assert not output.exists(), 'Retain and inspect existing trial; do not overwrite'
                command = [sys.executable, str(HERE / 'probe.py'), '--level', level,
                           '--sample-offset', str(offset), '--source', 'offline',
                           '--input', str(ROOT / 'exports/ground_boundary_latency_20261014' / plan['inputs'][mode]),
                           '--mode', mode, '--paint', 'gui_final_v2', '--cache-file', str(OLD / 'fixed_geometry_cache.py'),
                           '--cadence', 'recorded', '--camera-replay', '--output', str(output)]
                print('START', name, flush=True)
                with (HERE / (name + '.log')).open('xb') as stream:
                    completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=90)
                (HERE / 'progress.json').write_text(json.dumps({'completed': name, 'returncode': completed.returncode,
                                                               'host_ns': time.perf_counter_ns()}))
                if completed.returncode:
                    print((HERE / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
                    raise SystemExit(completed.returncode)
                result = json.loads((output / 'timing.json').read_text(encoding='utf-8'))
                assert result['finished'] and not result['errors']
                print('DONE', name, result['received_to_paint_ms'], flush=True)
                time.sleep(1)
