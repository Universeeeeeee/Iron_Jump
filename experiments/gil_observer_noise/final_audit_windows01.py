"""Read-only preservation audit after every diagnostic target has exited."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


root=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
formal=Path('E:/OptoJump/IronJump-single-usb-human-etw-20261017')
replay=Path('E:/OptoJump/IronJump-walk-compute-offline-20261017-01')
field=Path('E:/OptoJump/IronJump-gil-timestamped-20261018-01/field01')
waiter=Path('E:/OptoJump/IronJump-gil-waiter-control-20261018-01')
dynamic=Path('E:/OptoJump/IronJump-gil-coherent-dynamic-20261018-01')
prior=Path('E:/OptoJump/IronJump-gil-replay-disturbance-20261018-01')
base=read(formal/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
def mismatches(folder,expected):return [n for n,h in expected.items() if not (folder/n).is_file() or sha(folder/n)!=h]
v=dict(formal_count=len(base),formal_mismatches=mismatches(formal,base),replay_mismatches=mismatches(replay,base),old_field_mismatches=mismatches(field,read(field/'experiments/gil_timestamped/field_plan01.json')['source_sha256']),old_waiter_mismatches=mismatches(waiter,read(waiter/'plan01.json')['sources']),old_dynamic_mismatches=mismatches(dynamic,read(dynamic/'plan01.json')['sources']),old_failure_mismatches=mismatches(prior,read(prior/'failure_manifest01.json')),plan_sources={},raw_manifests={},locks={})
for name in ('off_aa_plan01.json','on_aa_plan01.json','confirmation_plan01.json','gc_plan01.json','field_rate01/plan01.json','cpu_delivery01/plan01.json'):
    path=root/name;plan=read(path)
    v['plan_sources'][name]=dict(plan_sha256=sha(path),mismatches=mismatches(path.parent,plan['sources']))
for name in ('off_aa01_manifest.json','on_aa01_manifest.json','confirmation01_manifest.json','gc_diagnostic01_manifest.json','cpu_delivery01_diagnostic01_manifest.json'):
    v['raw_manifests'][name]=dict(sha256=sha(root/name),mismatches=mismatches(root,read(root/name)))
v['raw_manifests']['field_rate01/manifest01.json']=dict(sha256=sha(root/'field_rate01/manifest01.json'),mismatches=mismatches(root/'field_rate01',read(root/'field_rate01/manifest01.json')))
for name,path in dict(old_field=field/'active.lock',old_python_marker=field.parent/'changing01/active.lock',old_native_constant=Path('E:/OptoJump/IronJump-gil-coherent-native-20261018-01/fault01/active.lock'),old_dynamic=dynamic/'active.lock',old_waiter=waiter/'active.lock',old_replay_failure=prior/'active.lock',old_replay_cohort=prior/'cohort03/active.lock',off_aa=root/'off_aa01/active.lock',on_aa=root/'on_aa01/active.lock',confirmation=root/'confirmation01/active.lock',gc=root/'gc_diagnostic01/active.lock',field_rate=root/'field_rate01/active.lock',cpu=root/'cpu_delivery01/diagnostic01/active.lock').items():v['locks'][name]=dict(path=str(path),retained=path.is_dir())
sys.path.insert(0,str(field/'experiments/native_stack_capture'));from winapi import profile_interval
v['sampling_interval_100ns']=profile_interval()
v['observer_sha256']=sha(root/'observer.exe')
v['numpy_pyd_sha256']=sha(Path('D:/conda/Lib/site-packages/numpy/_core/_multiarray_umath.cp311-win_amd64.pyd'))
v['replay_helper_sha256']=sha(replay/'experiments/walk_compute_offline_diagnosis/replay.py')
ps="@((Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe' -or $_.Name -like 'ironjump-gil-*.exe') -and ($_.CommandLine -like '*IronJump-gil-*' -or $_.Name -eq 'observer.exe' -or $_.Name -like 'ironjump-gil-*.exe')})|Select-Object ProcessId,Name,CreationDate,CommandLine)|ConvertTo-Json -Compress"
process=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,check=True)
v['remaining_diagnostic_processes']=json.loads(process.stdout.decode('utf-8-sig')) if process.stdout.strip() else []
v['audit_source_sha256']=sha(Path(__file__))
v['preservation_pass']=not any(value for key,value in v.items() if key.endswith('mismatches')) and all(not p['mismatches'] for p in [*v['plan_sources'].values(),*v['raw_manifests'].values()]) and all(p['retained'] for p in v['locks'].values()) and v['sampling_interval_100ns']==10000 and v['observer_sha256']=='02e367c7ca0b1cda5f1067b03125a770a502f10fcabb99fa5925b4265050d615' and v['numpy_pyd_sha256']=='4fb4c5d62a6bd766eea716350eaf5396580e33cf7dc159e305488d1b7d72dad2' and v['replay_helper_sha256']=='fcde26dd2e707cc457623a971a97e68ebd9f49630126c51bd6ce83072a0d40a8' and not v['remaining_diagnostic_processes']
with (root/'final_audit_windows01.json').open('x') as f:json.dump(v,f,indent=2)
print(json.dumps(v));raise SystemExit(not v['preservation_pass'])
