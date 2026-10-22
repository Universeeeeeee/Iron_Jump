"""Frozen four-case control; preserve failures and all original source files."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / 'measurement_boundary_replay_20261022'
ROOT = Path('E:/OptoJump/Iron_Jump')
SOURCE = ROOT / 'data/capture_logs/measurements/20261022_085545_9550a923'

if __name__ == '__main__':
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=False)
    cases = [('qt', 'process40'), ('python', 'process40'), ('python', 'process40'), ('qt', 'process40')]
    names = subprocess.check_output(['git', 'ls-files', '*.py'], cwd=ROOT, text=True).splitlines()
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    plan = dict(head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                source_report_sha256=hashlib.sha256((SOURCE / 'actor/report.json').read_bytes()).hexdigest(),
                source_exports_sha256=hashlib.sha256((SOURCE / 'actor/exports.npz').read_bytes()).hexdigest(),
                source_python=hashes,
                experiment_python={str(p.relative_to(HERE.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for folder in (HERE, BASE, HERE.parent / 'wire_boundary_replay_20261022') for p in folder.glob('*.py')},
                cases=cases, trace=True, hardware_opened=False, causal_control='PySide6 process40 only: quality.frame_ready Qt signal versus direct Python callback to the same process_quality_frame on the same verified thread. Fixed qt/python/python/qt order; no further trials or percentages.', input_signal_topology='One Qt DirectConnection from source to inbox; diagnostic validation hop is Python-only. Previous two-signal matrix retained.', binding_control='Desktop launcher specifies pyside6. Verify actual imported binding and QtCore binary in every parent/child. Fixed four windows, no quantitative causal attribution.',
                control='Same retained frames; synthetic one-based per-segment DATA packets, CRC, fixed 2048-byte reads, 20 frames/20ms. Not real USB timing or packetization.',
                limits='Camera/MediaPipe/SDK/DLL absent. No perturbation equivalence or statistical performance ranking. QPC alignment independently bounded. Verification assertions add observer work in wire path.')
    (out / 'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    with (out / 'clock.log').open('w') as log:
        subprocess.run([sys.executable, str(BASE / 'clock_check.py'), str(out / 'clock.json')], stdout=log, stderr=subprocess.STDOUT, check=True)
    statuses = []
    for number, (dispatch, mode) in enumerate(cases, 1):
        binding = 'pyside6'
        name = f'{number:02d}_{binding}_segmented_{mode}_{dispatch}'
        env = dict(os.environ, IJ_WIRE_SHAPE='segmented', QT_QPA_PLATFORM='offscreen', QT_API=binding, IJ_EXPECTED_QT=binding, IJ_QUALITY_DISPATCH=dispatch)
        with (out / (name + '.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, str(HERE / 'run_quality.py'), str(ROOT), str(SOURCE), str(out / name), '--mode', mode, '--trace', '1'], env=env, stdout=log, stderr=subprocess.STDOUT)
        statuses.append(dict(case=name, exit_code=result.returncode))
        (out / 'status.json').write_text(json.dumps(statuses, indent=2))
        print(name, result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
    assert all(hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in hashes.items())
    (out / 'source_verified_after.json').write_text(json.dumps(dict(unchanged=True, files=len(hashes))))
