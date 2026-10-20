"""Collect one completed or failed cohort without starting or retrying it."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan_path=HERE/'plan05.json';plan=json.loads(plan_path.read_text())
    assert all(sha(HERE/name)==digest for name,digest in plan['sources'].items())
    assert (HERE/'runs'/'active.lock').is_dir() and (HERE/'runs'/'status.json').is_file()
    output=HERE.parent/'vision_video_process_delivery_plan05_evidence';output.mkdir(exist_ok=False);(output/'active.lock').mkdir()
    files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    manifest=dict(plan='plan05.json',plan_sha256=sha(plan_path),source_sha256=plan['sources'],
        target_status=json.loads((HERE/'runs'/'status.json').read_text()),
        files={p.relative_to(HERE).as_posix():sha(p) for p in files},collector_started_target=False,collector_retried_target=False)
    manifest_path=output/'manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2))
    archive=output/'evidence.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in files:bundle.write(path,path.relative_to(HERE).as_posix())
        bundle.write(manifest_path,'manifest.json')
        for lock in sorted(p for p in HERE.rglob('active.lock') if p.is_dir()):
            bundle.writestr(lock.relative_to(HERE).as_posix().rstrip('/')+'/',b'')
    status=dict(complete=True,manifest_sha256=sha(manifest_path),archive_sha256=sha(archive),file_count=len(files),target_started=False,target_retried=False)
    (output/'status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status))
