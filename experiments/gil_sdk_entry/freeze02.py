"""Freeze corrected Qt enum observation; keep failed01 and its sources intact."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_sdk_entry_v2'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    previous=read(ROOT/'experiments/gil_qprocess_receipts/plan01.json');existing=dict(previous['existing_sources'])
    for folder in ('gil_qprocess_receipts','gil_sdk_receipt_control'):
        for n in read(ROOT/'experiments'/folder/'plan01.json')['sources']:existing['experiments/'+folder+'/'+n]=sha(ROOT/'experiments'/folder/n)
    for n in ('camera/tracking_runtime.py','camera/pose_tracking.py','camera/pose_transport.py'):existing[n]=sha(ROOT/n)
    sources={p.name:sha(p) for p in HERE.glob('*.py')}
    plan=dict(scope='Eight fixed synthetic real-QProcess controls of diagnostic entry calling original imported serve/runtime/mailbox with fake hardware. No actual SDK/model/replay/acquisition/human/Run/optimization AB.',
              previous_plan_sha256=sha(HERE/'plan01.json'),previous_failure_archive_sha256=read(HERE/'transport01.json')['archive_sha256'],sources=sources,existing_sources=existing,cases=['before_runtime','constructor_gap','active','inactive_runtime','wrong_generation','old_barrier','bad_json','bad_packet'],
              checks=['Accepted unchanged ASCII LF chunks reconstruct every child text receipt in order; no on-wire ID or new protocol messages.',
                      'Child-local line ordinal connects runtime_packet/runtime_submit/mailbox_submit entry/return/error with nested same-reader time brackets; separate PID verified against actual QProcess child ID.',
                      'Independent original pose_input logs retain full expected packet payloads and ordering, including runtime gating and duplicate early/late identical packets.',
                      'A mailbox function call/normal return does not establish accepted state mutation, inference consumption or SDK actuation. No additional state lock or acceptance counter is invented.',
                      'Bad JSON and missing generation preserve original reader termination/error; EOF and observation_complete remain false, even when the synthetic negative control passes.',
                      'Original serve return code and error identity preserved. Reader joined only after serve returns, outside its original interval; unconfirmed reader is failed and hooks are not restored while alive.',
                      'Normal child exit is compared against QProcess.NormalExit enum directly, not version-dependent str(enum). Old01 remains failed.',
                      'No cross-process clock equivalence or perturbation calibration is claimed. Old global540/539 failure and all candidates remain unchanged.'],
              actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with (HERE/'plan02.json').open('x') as f:json.dump(plan,f,indent=2)
    with zipfile.ZipFile(HERE/'source02.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in sources:z.write(HERE/n,n)
        z.write(HERE/'plan02.json','plan02.json')
    package=sha(HERE/'source02.zip')
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing frozen controls'}};if(@(Get-CimInstance Win32_Process|Where-Object {{$_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -eq 'ironjump-gil-waiter-first.exe'}}).Count){{throw 'Existing target; no start'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(HERE/'source02.zip',f'{w.HOST}:{REMOTE}/source02.zip')
    print(w.ssh(f"if((Get-FileHash '{REMOTE}/source02.zip').Hash.ToLower() -ne '{package}'){{throw 'Package mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source02.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}}"))
    print(json.dumps(dict(plan_sha256=sha(HERE/'plan02.json'),package_sha256=package)))
