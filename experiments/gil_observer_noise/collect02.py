"""Archive completed diagnostic evidence without overwriting an earlier collection."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main(a):
    root=Path(__file__).resolve().parent
    stages={'gc_diagnostic01':'gc_plan01.json','cpu_delivery01/diagnostic01':'cpu_delivery01/plan01.json'}
    plan_path=root/stages[a.stage];stage=root/a.stage
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    plan=read(plan_path);result=read(stage/'run01/result.json')
    assert read(stage/'exit.json')['returncode']==0 and not result['errors'] and result['capture_protocol_complete']
    assert result['plan_sha256']==sha(plan_path)
    sources={str((plan_path.parent/n).relative_to(root)):h for n,h in plan['sources'].items()}
    assert all(sha(root/n)==h for n,h in sources.items())
    assert sha(root/'observer.exe')==plan['observer_sha256']
    names=set(sources)|{plan_path.relative_to(root).as_posix(),'observer.exe','collect02.py'}
    names.update(p.relative_to(root).as_posix() for p in stage.rglob('*') if p.is_file())
    manifest={n:sha(root/n) for n in sorted(names)}
    stem=a.stage.replace('/','_')
    with (root/(stem+'_manifest.json')).open('x') as f:json.dump(manifest,f,indent=2)
    with zipfile.ZipFile(root/(stem+'.zip'),'x',zipfile.ZIP_DEFLATED) as z:
        for n in manifest:z.write(root/n,n)
        z.write(root/(stem+'_manifest.json'),'manifest.json')
        z.write(stage/'active.lock',a.stage+'/active.lock/')
    print(json.dumps(dict(archive_sha256=sha(root/(stem+'.zip')),manifest_files=len(manifest))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=('gc_diagnostic01','cpu_delivery01/diagnostic01'),required=True);main(p.parse_args())
