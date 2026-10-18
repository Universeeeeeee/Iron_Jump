"""Resolve only after both synthetic processes exited; bind every retained file."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    plan=read(HERE/'plan01.json');statuses={}
    assert all(sha(HERE/n)==h for n,h in plan['sources'].items())
    assert sha(HERE/'PauseOracle.dll')==plan['oracle_dll_sha256'] and sha(HERE/'PauseOracle.pdb')==plan['oracle_pdb_sha256']
    for name in plan['cases']:
        folder=HERE/'runs'/name;record=read(folder/'record.json')
        assert not record['errors'] and not record['target_still_running'] and not record['observer_still_running'] and not record['owner_pause_outstanding']
        with (folder/'resolve.log').open('xb') as log:
            p=subprocess.run([sys.executable,str(HERE/'resolve_raw.py'),'--samples',str(folder/'samples.jsonl'),'--output',str(folder/'symbols.json'),'--preflight','E:/OptoJump/IronJump-native-symbol-preflight-20261017-01'],stdout=log,stderr=subprocess.STDOUT)
        statuses[name]=p.returncode
    with (HERE/'resolve_status01.json').open('x') as f:json.dump(statuses,f,indent=2)
    names=[p for p in HERE.rglob('*') if p.is_file() and p.suffix not in ('.zip','.pyc') and p.name not in ('manifest.json','evidence01.zip') and '__pycache__' not in p.parts]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in sorted(names)}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for name in plan['cases']:z.write(HERE/'runs'/name/'active.lock',f'runs/{name}/active.lock/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),resolver_status=statuses)))
