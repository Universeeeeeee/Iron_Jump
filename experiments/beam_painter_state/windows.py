"""New-root Windows deployment; old diagnosis artifacts remain read-only."""
import hashlib,importlib.util,json,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('prior_windows',ROOT/'experiments/ground_throughput_diagnosis/windows.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
PRIOR=w.REMOTE
w.REMOTE='E:/OptoJump/IronJump-beam-painter-state-20261015'
w.REL='experiments/beam_painter_state'
w.HERE=HERE
ssh,transfer,task,fetch=w.ssh,w.transfer,w.task,w.fetch
HOST,REMOTE,REL=w.HOST,w.REMOTE,w.REL

def sync():
    paths=[*HERE.glob('*.py'),*HERE.glob('plan*.json'),*HERE.glob('plan*.sha256'),HERE/'phases.json',*HERE.glob('frozen_sources.json')]
    paths.append(ROOT/'experiments/runtime_single_frame_fusion/fixed_geometry_cache.py')
    with zipfile.ZipFile(HERE/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in paths:archive.write(path,str(path.relative_to(ROOT)))
    transfer(HERE/'source.zip',f'{HOST}:{REMOTE}/source.zip')
    sha=hashlib.sha256((HERE/'source.zip').read_bytes()).hexdigest()
    print(ssh(f"if((Get-FileHash '{REMOTE}/source.zip').Hash.ToLower() -ne '{sha}'){{throw 'Archive mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source.zip' '{REMOTE}';exit $LASTEXITCODE"),flush=True)

if __name__=='__main__':
    if sys.argv[1]=='deploy':
        baseline=json.loads((ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
        paths=[ROOT/name for name in baseline]
        paths += [ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json',ROOT/'experiments/ground_throughput_diagnosis/enabled_replay.py']
        with zipfile.ZipFile(HERE/'baseline.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for path in paths:archive.write(path,str(path.relative_to(ROOT)))
        print(ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing experiment directory'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null"),flush=True)
        transfer(HERE/'baseline.zip',f'{HOST}:{REMOTE}/baseline.zip')
        sha=hashlib.sha256((HERE/'baseline.zip').read_bytes()).hexdigest()
        print(ssh(f"if((Get-FileHash '{REMOTE}/baseline.zip').Hash.ToLower() -ne '{sha}'){{throw 'Baseline mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/baseline.zip' '{REMOTE}';New-Item -ItemType Directory '{REMOTE}/{REL}/inputs' -Force|Out-Null"),flush=True)
        inputs={}
        for mode,source in [('walk','live_walk_07'),('run','live_run_02')]:
            old=f'{PRIOR}/experiments/ground_throughput_diagnosis/runs/{source}'
            new=f'{REMOTE}/{REL}/inputs/{mode}'
            print(ssh(f"New-Item -ItemType Directory '{new}'|Out-Null;Copy-Item '{old}/*' '{new}'"),flush=True)
            inputs[mode]=json.loads(ssh(f"Get-ChildItem '{new}' -File|ForEach-Object {{@{{name=$_.Name;sha256=(Get-FileHash $_.FullName).Hash.ToLower();bytes=$_.Length}}}}|ConvertTo-Json -Compress",timeout=90))
        (HERE/'input_manifest.json').write_text(json.dumps(inputs,indent=2)+'\n')
        sync()
    else:sync()
