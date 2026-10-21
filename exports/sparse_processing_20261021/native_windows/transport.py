"""Transport an isolated, hardware-free CPU experiment to the known Windows host."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

HERE=Path(__file__).resolve().parent
LAB=HERE.parent
HOST='86150@100.116.17.121'
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/exports/sparse_processing_20261021'


def remote(code,label):
    encoded=base64.b64encode(code.encode()).decode()
    cmd='D:\\conda\\python.exe -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=8','-o','ConnectionAttempts=1','-o','ControlMaster=no',
        '-o','ControlPath=none','-o','ControlPersist=no',HOST,cmd],capture_output=True,text=True)
    (HERE/(label+'.stdout')).write_text(result.stdout)
    (HERE/(label+'.stderr')).write_text(result.stderr)
    if result.returncode:raise RuntimeError((label,result.returncode,result.stderr))
    return result.stdout


def main():
    action=sys.argv[1]
    if action=='upload':
        archive=Path('/tmp/ironjump_sparse_processing_20261021.tar')
        files=[LAB/n for n in ('experiment.py','candidates.py','run_suite.py',
                              'per_experiment_checks.py','manifest.json','input_package.json')]
        files += [p for parent in ('baseline','inputs') for p in (LAB/parent).rglob('*')
                  if p.is_file() and p.suffix!='.pyc']
        files += [HERE/'compute.py']
        with tarfile.open(archive,'w') as tar:
            for p in files:tar.add(p,arcname=str(p.relative_to(LAB)),recursive=False)
        sha=hashlib.sha256(archive.read_bytes()).hexdigest()
        code='''from pathlib import Path
import hashlib,json,platform,sys
root=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01')
plan=json.loads((root/'experiments/live_consumer_process_candidate16/plan16.json').read_text(encoding='utf-8'))
checks={n:hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in plan['formal_sha256'].items()}
assert all(checks.values()),checks
folder=root/'exports/sparse_processing_20261021'
if folder.exists():
 assert (folder/'native_preflight.json').exists(),'Unowned existing output directory'
else:folder.mkdir(parents=True)
result={'host':platform.node(),'platform':platform.platform(),'python':sys.version,'formal_plan16_hashes':checks,'target':str(folder),'scope':'offline saved data only; no USB, camera, SDK or human capture started'}
(folder/'native_preflight.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
'''
        remote(code,'preflight_retry')
        subprocess.run(['scp','-q',str(archive),HOST+':'+REMOTE+'/package.tar'],check=True)
        code=f'''from pathlib import Path
import tarfile,hashlib
p=Path({REMOTE!r})
assert hashlib.sha256((p/'package.tar').read_bytes()).hexdigest()=={sha!r}
with tarfile.open(p/'package.tar') as tar:
 assert all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts and not m.issym() and not m.islnk() for m in tar.getmembers())
 tar.extractall(p)
print({sha!r})
'''
        assert sha in remote(code,'extract_retry')
        (HERE/'transport.json').write_text(json.dumps({'archive_sha256':sha,
            'remote_verified_same_sha':True,'files':len(files),
            'scope':'Offline algorithm CPU validation; no GUI, IPC, hardware or capture.'},indent=2))
        print('uploaded and SHA verified',len(files),flush=True)
    elif action=='run':
        label,variant=sys.argv[2:4]
        code=f'''import subprocess,sys
from pathlib import Path
p=Path({REMOTE!r})
with (p/{(label+'.driver.stdout')!r}).open('w') as out,(p/{(label+'.driver.stderr')!r}).open('w') as err:
 r=subprocess.run([sys.executable,str(p/'native_windows/compute.py'),{label!r},{variant!r}],stdout=out,stderr=err)
print('native computation returncode',r.returncode)
raise SystemExit(r.returncode)
'''
        remote(code,label+'_remote_driver')
    elif action=='download':
        label=sys.argv[2]
        # Download completed evidence only; no application or capture is started.
        remote(f'''from pathlib import Path
import tarfile,hashlib,json
p=Path({REMOTE!r});f=p/{(label+'.evidence.tar')!r}
paths=[p/'native_preflight.json',p/{(label+'.native.json')!r},p/{(label+'.driver.stdout')!r},p/{(label+'.driver.stderr')!r}]
paths+=list((p/'benchmarks').glob('*'+{label!r}+'*'))
with tarfile.open(f,'w') as tar:
 for path in paths:
  if path.exists():tar.add(path,arcname=str(path.relative_to(p)),recursive=False)
print(json.dumps({{'archive_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'files':len(paths)}}))
''',label+'_package')
        target=HERE/(label+'.evidence.tar')
        subprocess.run(['scp','-q',HOST+':'+REMOTE+'/'+target.name,str(target)],check=True)
        expected=json.loads((HERE/(label+'_package.stdout')).read_text())['archive_sha256']
        assert hashlib.sha256(target.read_bytes()).hexdigest()==expected
        folder=HERE/label;folder.mkdir(exist_ok=False)
        with tarfile.open(target) as tar:
            assert all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in tar.getmembers())
            tar.extractall(folder)
        print('downloaded SHA-verified',label,flush=True)
    else:raise SystemExit('upload | run LABEL VARIANT | download LABEL')


if __name__=='__main__':main()
