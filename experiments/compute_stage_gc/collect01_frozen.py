import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=json.loads((HERE/'plan01.json').read_text());status=json.loads((HERE/'runs/status.json').read_text())
    assert 'unconfirmed_pid' not in status
    cmd="@(Get-Process python -ErrorAction SilentlyContinue|Where-Object {$_.Id -ne "+str(os.getpid())+"}|Select-Object -ExpandProperty Id)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,check=True);assert not p.stdout.strip()
    root=Path(plan['replay_root']);base=json.loads((root/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    assert all(sha(root/n)==v for n,v in base.items()) and all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
    paths=[p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.stdout','.stderr') and '__pycache__' not in p.parts];manifest={p.relative_to(HERE).as_posix():sha(p) for p in paths}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for p in (HERE/'runs').rglob('active.lock'):z.write(p,p.relative_to(HERE).as_posix()+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),baseline_files_unchanged=len(base),inputs_unchanged=True,no_python_targets=True)))
