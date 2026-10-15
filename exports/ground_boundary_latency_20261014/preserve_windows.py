"""Archive the existing Windows application's source/assets without modifying it."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path('E:/OptoJump/Iron_Jump');OUT=Path(__file__).resolve().parent
files=set(ROOT.glob('*.py'))
for directory in ('config','engine','hardware','reporting','ui','camera','vision','voice','agent','data','tools'):
    files.update(p for p in (ROOT/directory).rglob('*.py') if '__pycache__' not in p.parts)
files.update(p for p in (ROOT/'ui/assets').rglob('*') if p.is_file())
files.update((ROOT/'hardware').glob('*.dll'))
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
archive=OUT/'old_windows_source.zip'
assert not archive.exists()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(files):z.write(p,str(p.relative_to(ROOT)))
    z.writestr('rollback_manifest.json',json.dumps(manifest,indent=2))
assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in manifest.items())
(OUT/'rollback_manifest.json').write_text(json.dumps({'original_root':str(ROOT),'archive':str(archive),
    'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':manifest,
    'rollback':'Close the validation window and start the existing original application. No original file or shortcut was replaced.'},indent=2))
print('Original source archived and untouched:',len(manifest),flush=True)
