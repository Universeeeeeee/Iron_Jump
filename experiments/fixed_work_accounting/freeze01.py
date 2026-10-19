"""Freeze one boundary-qualification pair before any variance/observer run."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
    old=ROOT/'experiments/fixed_concurrent_work';plan=json.loads((old/'plan01.json').read_text())
    plan.update(sources={p.name:sha(p) for p in HERE.glob('*.py')},cases=['a','b'],prior_fixed_bundle_plan_sha256=sha(old/'plan01.json'),
                scope='Exactly one new fixed-bundle boundary qualification pair. Whole process CPU/cycles include native model pools; original fixed consumer/model work unchanged. No live camera/USB, GUI/SDK, human, Run, optimization AB, ETW or sampler.',
                checks=plan['checks']+['Model work_done handshake blocks adapter.close until after process_after; counter brackets cover both complete task spans.',
                                      'Same process identity, monotonic process times/cycles and <=1ms counter read brackets. Named-thread sum cross-check retains prior50ms tolerance, not an equivalence margin.',
                                      'Both complete task identities and model result content must agree. Keep any fixed-consumer ROI model-overlap differences.',
                                      'One pair validates boundaries only; no between-pair variance/3% equivalence/1% precision or root attribution. No retries replacing a failed case.'])
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in plan['sources']:z.write(HERE/n,n)
        z.write(HERE/'plan01.json','plan01.json')
    remote='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/fixed_work_accounting'
    w.ssh(f"if(Test-Path '{remote}'){{throw 'Existing boundary case'}};if(@(Get-Process python -ErrorAction SilentlyContinue).Count){{throw 'Existing Python targets'}};New-Item -ItemType Directory '{remote}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{remote}/source01.zip')
    print(w.ssh(f"if((Get-FileHash '{remote}/source01.zip').Hash.ToLower() -ne '{sha(HERE/'source01.zip')}'){{throw 'Package mismatch'}};& D:/conda/python.exe -m zipfile -e '{remote}/source01.zip' '{remote}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan01.json'),source_archive_sha256=sha(HERE/'source01.zip'))))
