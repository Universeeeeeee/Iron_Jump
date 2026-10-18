"""One new two-phase metadata protocol case; no retry of failed01/02 evidence."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_workload_finalization'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    old=read(ROOT/'experiments/gil_workload_observation/plan02.json')
    sources={p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.py','.ps1')}
    existing=dict(old['frozen_existing'])
    for folder,names in [('gil_workload_observation',list(old['sources'])),('gil_observation_termination',['snapshot.py','synthetic_plan01.json'])]:
        for n in names:existing['experiments/'+folder+'/'+n]=sha(ROOT/'experiments'/folder/n)
    plan=dict(scope='One independent qualification of the new two-phase recorder, with original fixed saved optical/video replay and real SDK control child. Extra observer lifetime only after original application return. No human, optical/camera acquisition, Run, stack sampling, ETW or optimization AB.',
              sources=sources,existing_sources=existing,input_root=old['input_root'],input_sha256=old['input_sha256'],offset_ns=old['offset_ns'],duration_ns=old['duration_ns'],lateness_ns_max=old['lateness_ns_max'],clock_uncertainty_ns_max=old['clock_uncertainty_ns_max'],
              python_dll_sha256=old['python_dll_sha256'],numpy_pyd_sha256=old['numpy_pyd_sha256'],external_native_sha256=old['external_native_sha256'],observer_tail_deadline_s=90,
              old_failed_metadata_plan_sha256=sha(ROOT/'experiments/gil_workload_observation/plan02.json'),synthetic_qualification_sha256=sha(ROOT/'experiments/gil_observation_termination/result01.json'),
              checks=['Write and retain original application-return snapshot before any observer join. Never upgrade or rewrite its unconfirmed end state.',
                      'Bounded90s observer-only tail releases recorder lock before joining existing threads; does not call stop again or change original timeouts, data policy, worker structure or painter.',
                      'Final model completion/identity/order and contiguous event prefix must pass; timeout/app error remains failure. Native creation/lifetimes checked with retained handles through process exit.',
                      'Full original report/state/input equality; every actual saved adapter/inference/submit and relay/SDK metadata link; separate SDK PID and unchanged QPC/ROI lateness gates.',
                      'This one case is protocol feasibility only, not3%/1% equivalence or actual observer-overhead acceptance. All old failures/locks stay unchanged.'],
              actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in sources:z.write(HERE/n,n)
        z.write(HERE/'plan01.json','plan01.json')
    package=sha(HERE/'source01.zip')
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing protocol case'}};if(@(Get-CimInstance Win32_Process|Where-Object {{$_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe'}}).Count){{throw 'Existing target; no start'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{REMOTE}/source01.zip')
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/source01.zip').Hash.ToLower() -ne '{package}'){{throw 'Source package mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source01.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan01.json'),sources=len(sources))))
