"""Collect the frozen GUI window without starting, stopping or retrying it."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=Path(HERE/'plan02.json');frozen=json.loads(plan.read_text());assert (HERE/'active.lock').is_dir() and (HERE/'status01.json').is_file()
    assert all(sha(HERE/name)==digest for name,digest in frozen['sources'].items())
    output=HERE.parent/'vision_gui_process_proxy_evidence02';output.mkdir(exist_ok=False);(output/'active.lock').mkdir()
    files=sorted(p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    manifest=dict(plan_sha256=sha(plan),source_sha256=frozen['sources'],status=json.loads((HERE/'status01.json').read_text()),
        files={p.relative_to(HERE).as_posix():sha(p) for p in files},collector_started_target=False,collector_retried_target=False)
    manifest_path=output/'manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2));archive=output/'evidence.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in files:bundle.write(path,path.relative_to(HERE).as_posix())
        bundle.write(manifest_path,'manifest.json')
        for lock in sorted(p for p in HERE.rglob('active.lock') if p.is_dir()):bundle.writestr(lock.relative_to(HERE).as_posix().rstrip('/')+'/',b'')
    status=dict(complete=True,manifest_sha256=sha(manifest_path),archive_sha256=sha(archive),file_count=len(files),target_started=False,target_retried=False)
    (output/'status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status))
