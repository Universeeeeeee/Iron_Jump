"""New source freeze after the preserved pre-replay import failure; no retry traces."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_workload_observation'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    old=read(HERE/'plan01.json');transport=read(HERE/'transport01.json')
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    assert sha(HERE/'failed_entry01.py')==old['sources']['entry01.py']
    paths=[p for p in HERE.iterdir() if p.suffix in ('.py','.ps1')];sources={p.name:sha(p) for p in paths}
    with zipfile.ZipFile(HERE/'source02.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p.name)
    w.transfer(HERE/'source02.zip',f'{w.HOST}:{REMOTE}/source02.zip');archive_sha=sha(HERE/'source02.zip')
    print(w.ssh(f"if(Test-Path '{REMOTE}/plan02.json'){{throw 'Plan02 already exists'}};if((Get-FileHash '{REMOTE}/source02.zip').Hash.ToLower() -ne '{archive_sha}'){{throw 'Source mismatch'}};if(@(Get-CimInstance Win32_Process|Where-Object {{$_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe'}}).Count){{throw 'Processes live; do not change sources'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source02.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    plan=dict(old);plan['sources']=sources;plan['previous_plan_sha256']=sha(HERE/'plan01.json');plan['preserved_failed_archive_sha256']=transport['archive_sha256'];plan['scope']+=' Corrected import bootstrap, first actual replay observations in observation02; observation01 failed before GUI/input startup and remains unchanged.'
    with (HERE/'plan02.json').open('x') as f:json.dump(plan,f,indent=2)
    w.transfer(HERE/'plan02.json',f'{w.HOST}:{REMOTE}/plan02.json')
    print(json.dumps(dict(plan02_sha256=sha(HERE/'plan02.json'),sources=len(sources),preserved_failed_archive_sha256=transport['archive_sha256'])))
