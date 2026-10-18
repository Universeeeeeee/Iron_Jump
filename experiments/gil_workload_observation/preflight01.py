"""Read-only runtime/input/source identities before any GUI case starts."""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    old=read(ROOT/'experiments/gil_gui_analysis/stack_plan01.json')
    versions={}
    for name in ('numpy','mediapipe','opencv-python','opencv-contrib-python','PySide6','QtPy'):
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]=None
    native={}
    for name in ('mediapipe','cv2'):
        spec=importlib.util.find_spec(name);assert spec and spec.origin
        for p in Path(spec.origin).parent.rglob('*'):
            if p.is_file() and p.suffix.lower() in ('.pyd','.dll'):native[str(p)]=sha(p)
    ps="@{active=@(Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe')}|Select-Object ProcessId,Name,CommandLine);devices=@(Get-CimInstance Win32_PnPEntity|Where-Object {$_.Name -match 'OBSBOT.*StreamCamera'}|Select-Object Name,Status)}|ConvertTo-Json -Depth 5 -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,check=True);state=json.loads(p.stdout.decode('utf-8-sig'))
    assert not state['active'] and state['devices'] and all(d['Status']=='OK' for d in state['devices'])
    expected=dict(old['baseline_files']);expected.update(old['frozen_sources']);expected.update(old['dependencies'])
    mismatch=[n for n,v in expected.items() if sha(ROOT/n)!=v];assert not mismatch
    assert all(sha(Path(old['input_root'])/n)==v for n,v in old['input_sha256'].items())
    assert sha(Path('D:/conda/python311.dll'))==old['python_dll_sha256'] and sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))==old['numpy_pyd_sha256']
    result=dict(versions=versions,native_sha256=native,python_dll_sha256=old['python_dll_sha256'],numpy_pyd_sha256=old['numpy_pyd_sha256'],existing_files=len(expected),existing_mismatches=mismatch,processes_and_devices=state,input_hashes_exact=True)
    with (HERE/'preflight01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
