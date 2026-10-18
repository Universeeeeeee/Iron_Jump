"""Preserve completed controls, exact source snapshots and post-exit PDB lookups."""
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
    plan=read(HERE/'plan01.json');status={}
    assert all(sha(HERE/n)==h for n,h in plan['sources'].items())
    for name in ('positive01','negative01'):
        r=read(HERE/f'runs/{name}/record.json');assert not r['target_still_running'] and not r['observer_still_running']
    for name,paths in [('positive',[HERE/f'runs/positive01/phase{i}/samples.jsonl' for i in (1,2)]),('negative',[HERE/'runs/negative01/samples.jsonl'])]:
        joined=HERE/f'{name}_samples01.jsonl'
        with joined.open('xb') as f:
            for p in paths:f.write(p.read_bytes())
        with (HERE/f'{name}_resolve01.log').open('xb') as log:
            p=subprocess.run([sys.executable,str(HERE/'resolve_raw.py'),'--samples',str(joined),'--output',str(HERE/f'{name}_symbols01.json'),'--preflight','E:/OptoJump/IronJump-native-symbol-preflight-20261017-01'],stdout=log,stderr=subprocess.STDOUT)
        status[name]=p.returncode
    with (HERE/'resolve_status01.json').open('x') as f:json.dump(status,f,indent=2)
    names=set(plan['sources']);names.update(('plan01.json','build01.json','positive_samples01.jsonl','negative_samples01.jsonl','positive_symbols01.json','negative_symbols01.json','resolve_status01.json','target/release/ironjump-gil-waiter-first.exe','positive_oracle.dll','negative_oracle.dll'))
    names.update(p.relative_to(HERE).as_posix() for sub in ('runs','dependency_sources') for p in (HERE/sub).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    names.update(p.name for p in HERE.iterdir() if p.is_file() and p.suffix in ('.log','.stdout','.stderr'))
    manifest={n:sha(HERE/n) for n in sorted(names) if (HERE/n).is_file()}
    with (HERE/'manifest.json').open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(HERE/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/'manifest.json','manifest.json')
        for n in ('runs/active.lock','runs/negative01/active.lock'):
            if (HERE/n).is_dir():z.write(HERE/n,n+'/')
    print(json.dumps(dict(archive_sha256=sha(HERE/'evidence01.zip'),manifest_files=len(manifest),resolver_status=status)))
