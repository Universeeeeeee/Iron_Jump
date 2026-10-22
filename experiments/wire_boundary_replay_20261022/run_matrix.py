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
    cases = [('decoded', 'local20'), ('segmented', 'process40'), ('segmented', 'local20'), ('decoded', 'process40')]
    names = subprocess.check_output(['git', 'ls-files', '*.py'], cwd=ROOT, text=True).splitlines()
    hashes = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in names}
    plan = dict(head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                source_report_sha256=hashlib.sha256((SOURCE / 'actor/report.json').read_bytes()).hexdigest(),
                source_exports_sha256=hashlib.sha256((SOURCE / 'actor/exports.npz').read_bytes()).hexdigest(),
                source_python=hashes,
                experiment_python={str(p.relative_to(HERE.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for folder in (HERE, BASE) for p in folder.glob('*.py')},
                cases=cases, trace=True, hardware_opened=False,
                control='Same retained frames; synthetic one-based per-segment DATA packets, CRC, fixed 2048-byte reads, 20 frames/20ms. Not real USB timing or packetization.',
                limits='Camera/MediaPipe/SDK/DLL absent. No perturbation equivalence or statistical performance ranking. QPC alignment independently bounded. Verification assertions add observer work in wire path.')
    (out / 'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    with (out / 'clock.log').open('w') as log:
        subprocess.run([sys.executable, str(BASE / 'clock_check.py'), str(out / 'clock.json')], stdout=log, stderr=subprocess.STDOUT, check=True)
    statuses = []
    for number, (shape, mode) in enumerate(cases, 1):
        name = f'{number:02d}_{shape}_{mode}'
        env = dict(os.environ, IJ_WIRE_SHAPE=shape, QT_QPA_PLATFORM='offscreen')
        with (out / (name + '.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, str(HERE / 'run_wire.py'), str(ROOT), str(SOURCE), str(out / name), '--mode', mode, '--trace', '1'], env=env, stdout=log, stderr=subprocess.STDOUT)
        statuses.append(dict(case=name, exit_code=result.returncode))
        (out / 'status.json').write_text(json.dumps(statuses, indent=2))
        print(name, result.returncode, flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)
    assert all(hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in hashes.items())
    (out / 'source_verified_after.json').write_text(json.dumps(dict(unchanged=True, files=len(hashes))))
