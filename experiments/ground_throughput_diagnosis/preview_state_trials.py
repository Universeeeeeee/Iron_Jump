"""Counterfactual E/O/E pilot: camera-widget state only, original NumPy and M observer."""
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


if __name__ == '__main__':
    for mode, source in (('run', 'field_run_20261015_02'), ('walk', 'field_walk_full_02')):
        for order, state in enumerate(('enabled', 'disabled', 'enabled'), 1):
            name = f'preview_{mode}_{order:02d}_{state}'
            output = HERE / 'runs' / name
            assert not output.exists()
            command = [sys.executable, str(HERE / 'state_target.py'), '--preview-state', state,
                       '--level', 'M', '--source', 'offline', '--input',
                       str(ROOT / 'exports/ground_boundary_latency_20261014' / source),
                       '--mode', mode, '--paint', 'gui_final_v2', '--cache-file',
                       str(ROOT / 'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py'),
                       '--cadence', 'recorded', '--camera-replay', '--output', str(output)]
            print('START', name, flush=True)
            with (HERE / (name + '_target.log')).open('xb') as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                complete = None
                terminated = False
                deadline = time.monotonic() + 75
                try:
                    while time.monotonic() < deadline:
                        if (output / 'external_delivery.json').exists():
                            try:
                                delivery = json.loads((output / 'external_delivery.json').read_text())
                            except json.JSONDecodeError:
                                time.sleep(.05)
                                continue
                            timing = json.loads((output / 'timing.json').read_text(encoding='utf-8'))
                            assert delivery['system_exit_code'] == 0
                            assert timing['finished'] and not timing['errors']
                            assert all((output / f).is_file() for f in ('diagnostic.json', 'report.json', 'raw_frames.npz'))
                            complete = time.perf_counter_ns()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                # GUI, raw drain, report, camera shutdown, and observer serialization are finished.
                                # Do not wait for unrelated native interpreter-exit telemetry between trials.
                                process.terminate()
                                process.wait(timeout=10)
                                terminated = True
                            break
                        if process.poll() is not None:
                            raise RuntimeError((name, 'Exited before complete evidence', process.returncode))
                        time.sleep(.1)
                    assert complete is not None, 'No completed evidence before deadline'
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
            marker = {'preview_state': state, 'evidence_complete_host_ns': complete,
                      'process_exitcode': process.returncode, 'terminated_after_complete_evidence': terminated,
                      'scope': 'E/O/E diagnostic pilot, not optimization adoption or a new successful M/D calibration. Termination, if needed, occurs only after successful GUI SystemExit, raw/report/camera teardown and all evidence files are closed.'}
            (output / 'state_marker.json').write_text(json.dumps(marker, indent=2) + '\n')
            print('DONE', name, timing['received_to_paint_ms'], flush=True)
