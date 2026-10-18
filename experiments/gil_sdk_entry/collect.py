"""Archive an existing control, including failures and every retained lock."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    number=sys.argv[1];plan=json.loads((HERE/('plan'+number+'.json')).read_text())
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    paths=[p for p in HERE.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.stdout','.stderr','.txt') and '__pycache__' not in p.parts and not p.name.startswith('manifest')]
    manifest={p.relative_to(HERE).as_posix():sha(p) for p in paths}
    manifest_name='manifest'+number+'.json';archive=HERE/('evidence'+number+'.zip')
    with (HERE/manifest_name).open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(HERE/n,n)
        z.write(HERE/manifest_name,manifest_name)
        for p in HERE.rglob('active.lock'):z.write(p,p.relative_to(HERE).as_posix()+'/')
    print(json.dumps(dict(archive_sha256=sha(archive),manifest_files=len(manifest))))
