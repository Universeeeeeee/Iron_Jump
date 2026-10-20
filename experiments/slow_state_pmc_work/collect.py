"""After owned recorder/controller terminate, archive all original andfailed evidence."""
import hashlib
import json
from pathlib import Path
import zipfile
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');capture=read(HERE/'capture01.json');assert capture['cleanup_confirmed']
    assert all(sha(HERE/n)==v for n,v in p['sources'].items()) and sha(HERE/'boundary.dll')==p['boundary_dll_sha256']
    root=Path(p['replay_root']);base=read(root/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(sha(root/n)==v for n,v in base.items())
    files={f.relative_to(HERE).as_posix():sha(f) for f in HERE.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.zip'}
    locks=[f.relative_to(HERE).as_posix() for f in HERE.rglob('*.lock') if f.is_dir()]
    with (HERE/'manifest01.json').open('x') as f:json.dump(files,f,indent=2)
    archive=HERE.parent/'slow-state-pmc-work-evidence01.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for name in files:z.write(HERE/name,name)
        for name in locks:z.write(HERE/name,name+'/')
        z.write(HERE/'manifest01.json','manifest01.json')
    print(json.dumps(dict(archive=archive.as_posix(),sha256=sha(archive),files=len(files),formal_files_unchanged=len(base),directory_locks=locks)))
