"""Read-only post-control preservation and archive; original evidence stays put."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    plan=read(HERE/'plan01.json');old=read(ROOT/'experiments/gil_sdk_workload/plan01.json');status=read(HERE/'runs/status.json')
    assert status.get('complete') and not status['errors']
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert all(sha(ROOT/n)==v for n,v in old['existing_sources'].items())
    formal=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')['baseline_files']
    assert all(sha(Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')/n)==v for n,v in formal.items())
    assert sha(Path('D:/conda/python311.dll'))==old['python_dll_sha256']
    assert sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==old['numpy_pyd_sha256']
    command="@(Get-Process python -ErrorAction SilentlyContinue|Where-Object {$_.Id -ne "+str(os.getpid())+"}|Select-Object -ExpandProperty Id)|ConvertTo-Json -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,check=True);assert not p.stdout.strip()
    audit=dict(formal_files_unchanged=len(formal),prior_dependencies_unchanged=True,original_Python_NumPy_unchanged=True,no_remaining_python_targets=True,locks=[str(x.relative_to(HERE)) for x in (HERE/'runs').rglob('active.lock')])
    with (HERE/'audit01.json').open('x') as f:json.dump(audit,f,indent=2)
    paths=[p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.stdout','.stderr') and '__pycache__' not in p.parts];manifest={p.relative_to(HERE).as_posix():sha(p) for p in paths}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for p in (HERE/'runs').rglob('active.lock'):z.write(p,p.relative_to(HERE).as_posix()+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest))))
