"""Post-controller archive only. Never launch, stop or replace a performance window."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');status=read(HERE/'runs/status.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    root=Path(plan['replay_root'])
    base=read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(sha(root/n)==v for n,v in base.items())
    files={p.relative_to(HERE).as_posix():sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.zip'}
    locks=[p.relative_to(HERE).as_posix() for p in HERE.rglob('*.lock') if p.is_dir()]
    manifest=dict(files=files,locks=locks,formal_files_unchanged=len(base))
    with (HERE/'manifest01.json').open('x') as f:json.dump(manifest,f,indent=2)
    archive=HERE.parent/'slow_state_context-evidence01.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n in files:z.write(HERE/n,n)
        for n in locks:z.write(HERE/n,n+'/')
        z.write(HERE/'manifest01.json','manifest01.json')
    print(json.dumps(dict(archive=str(archive),sha256=sha(archive),manifest_files=len(files),locks=locks,formal_files_unchanged=len(base),controller_pid=status['controller_pid'])))
