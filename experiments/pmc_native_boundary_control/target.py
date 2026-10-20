"""Launch one hash-bound native calibration child; no Python within measured blocks."""
import hashlib
import json
from pathlib import Path
import subprocess
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    plan=json.loads((HERE/'capture_plan02.json').read_text())
    assert hashlib.sha256((HERE/'target.exe').read_bytes()).hexdigest()==plan['executable_sha256']
    assert not (HERE/'native_target01.json').exists() and not (HERE/'target01.json').exists()
    code=subprocess.run([str(HERE/'target.exe')],cwd=HERE).returncode
    if (HERE/'native_target01.json').exists():
        data=(HERE/'native_target01.json').read_bytes()
        with (HERE/'target01.json').open('xb') as f:f.write(data)
    raise SystemExit(code)
