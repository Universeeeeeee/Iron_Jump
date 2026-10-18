"""Archive completed GUI feasibility evidence; never follows input/media junctions."""
import hashlib
import json
from pathlib import Path
import zipfile


here=Path(__file__).resolve().parent;root=here.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert (here/'runs/off_aa01/result01.json').is_file(),'Do not archive an active fixed queue'
status=read(here/'runs/off_aa01/result01.json')
# An aborted queue is evidence too. Do not require successful windows to archive it.
names=set(read(here/'frozen_sources.json')['files'])|set(read(here/'aa_frozen_sources01.json')['files'])
names.update(p.relative_to(root).as_posix() for p in here.iterdir() if p.is_file() and p.suffix not in ('.zip',))
names.update(p.relative_to(root).as_posix() for p in (here/'runs').rglob('*') if p.is_file())
manifest={n:sha(root/n) for n in sorted(names)}
with (here/'manifest01.json').open('x') as f:json.dump(manifest,f,indent=2)
with zipfile.ZipFile(here/'evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
    for n in manifest:z.write(root/n,n)
    z.write(here/'manifest01.json','manifest.json')
    for p in (here/'runs').rglob('active.lock'):z.write(p,p.relative_to(root).as_posix()+'/')
print(json.dumps(dict(archive_sha256=sha(here/'evidence01.zip'),manifest_files=len(manifest),fixed_cases_completed=len(status['cases']),errors=status['errors'])))
