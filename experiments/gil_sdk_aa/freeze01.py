"""Freeze a two-case OFF/OFF comparability gate, prior to variance/ON runs."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_sdk_aa'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    old=json.loads((HERE.parent/'gil_sdk_workload/plan01.json').read_text());plan=dict(old)
    plan['existing_sources']=dict(old['existing_sources']);plan['existing_sources'].update({'experiments/gil_sdk_workload/'+n:v for n,v in old['sources'].items()})
    plan.update(sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.ps1')},cases=['pair01_a','pair01_b'],scope='Exactly one prospective fresh-process OFF/OFF pair with the qualified unchanged wire replay entry. No stack sampler/ETW/human/live acquisition/Run/optimization AB. Comparability feasibility only; no variance or equivalence claim.',
                checks=old['checks']+['Both cases share exact observer configuration and full input. All original protocol gates must pass independently.',
                                      'Compare actual video and inference identity sequences, SDK workload and draws; any mismatch prevents matched-workload overhead qualification. Never trim/filter/select matching frames.',
                                      'One pair cannot estimate between-pair variance. Do not proceed to ON or extend sample count to search for matching cases.',
                                      'Keep3% effect and1% precision gates for later calibration. Common-observer absolute cost remains unknown.'],
                prior_qualified_window_sha256=sha(HERE.parent/'gil_sdk_workload/result01.json'))
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in plan['sources']:z.write(HERE/n,n)
        z.write(HERE/'plan01.json','plan01.json')
    package=sha(HERE/'source01.zip')
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing AA plan'}};if(@(Get-Process python -ErrorAction SilentlyContinue).Count){{throw 'Existing Python target'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{REMOTE}/source01.zip')
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/source01.zip').Hash.ToLower() -ne '{package}'){{throw 'Package mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source01.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(package)
