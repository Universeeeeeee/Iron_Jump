"""Resolve preserved addresses after synthetic exit and archive the exact evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


root=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(root/'plan01.json');record=read(root/'run01/record.json')
assert read(root/'exit01.json')['returncode']==0 and record['capture_complete'] and not record['errors']
assert record['plan_sha256']==sha(root/'plan01.json')
assert not record['observer_still_running'] and not record['target_still_running']
assert all(sha(root/n)==h for n,h in plan['sources'].items())
assert sha(root/'WaiterOracle.dll')==plan['oracle_dll_sha256']
tool=root/'target/release/ironjump-gil-waiter-control.exe';tool.parent.mkdir(parents=True,exist_ok=False)
shutil.copy2(root.parent/'observer.exe',tool);assert sha(tool)==plan['observer_sha256']
with (root/'all_samples.jsonl').open('xb') as f:
    for phase in (1,2):f.write((root/f'run01/phase{phase}/samples.jsonl').read_bytes())
with (root/'resolve01.log').open('xb') as log:
    subprocess.run([sys.executable,str(root/'resolve_raw.py'),'--samples',str(root/'all_samples.jsonl'),'--output',str(root/'symbols01.json'),'--preflight','E:/OptoJump/IronJump-native-symbol-preflight-20261017-01'],stdout=log,stderr=subprocess.STDOUT,check=True)
names=set(plan['sources'])|{'plan01.json','WaiterOracle.dll','target/release/ironjump-gil-waiter-control.exe','exit01.json','controller01.log','symbols01.json','all_samples.jsonl','resolve01.log','collect01.py'}
names.update(p.relative_to(root).as_posix() for p in (root/'run01').rglob('*') if p.is_file())
manifest={n:sha(root/n) for n in sorted(names)}
with (root/'manifest01.json').open('x') as f:json.dump(manifest,f,indent=2)
with zipfile.ZipFile(root/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
    for n in manifest:z.write(root/n,n)
    z.write(root/'manifest01.json','manifest.json');z.write(root/'active.lock','active.lock/')
print(json.dumps(dict(archive_sha256=sha(root/'evidence01.zip'),manifest_files=len(manifest))))
