"""Resolve and archive a finished single window; retain every failure and lock."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


here=Path(__file__).resolve().parent;root=here.parents[1];stage=here/'runs/stack01'
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=read(here/'stack_plan01.json');record=read(stage/'record01.json')
ps="@((Get-CimInstance Win32_Process|Where-Object {$_.ProcessId -ne "+str(os.getpid())+" -and ($_.Name -eq 'python.exe' -or $_.Name -eq 'observer.exe') -and ($_.CommandLine -like '*IronJump-gil-*' -or $_.CommandLine -match '-m\\s+camera\\.control_service')})|Select-Object ProcessId,Name,CommandLine)|ConvertTo-Json -Compress"
q=subprocess.run(['powershell','-NoProfile','-Command',ps],capture_output=True,check=True);remaining=json.loads(q.stdout.decode('utf-8-sig')) if q.stdout.strip() else []
assert not remaining and not record['target_still_running'] and not record['observer_still_running'],'Quiescence unconfirmed; preserve state'
assert all(sha(root/n)==h for n,h in plan['frozen_sources'].items()) and sha(Path(plan['observer_path']))==plan['observer_sha256']
sys.path.insert(0,str(root/'experiments/gil_gui_calibration'));from winapi import profile_interval
assert profile_interval()==10000
with (stage/'resolve01.log').open('xb') as log:
    done=subprocess.run([sys.executable,str(here/'resolve_fixed01.py'),'--samples',str(stage/'samples.jsonl'),'--output',str(stage/'symbols01.json'),'--preflight','E:/OptoJump/IronJump-native-symbol-preflight-20261017-01'],stdout=log,stderr=subprocess.STDOUT)
with (stage/'resolve_status01.json').open('x') as f:json.dump(dict(returncode=done.returncode,quiescent=True,sampling_interval_100ns=10000),f,indent=2)
names=set(plan['frozen_sources'])
names.update('experiments/gil_gui_analysis/'+n for n in ('stack_plan01.json','stack_orchestration01.json','launch_stack01.ps1','start_stack01.ps1','stack_task01.log','collect_stack01.py'))
names.update(p.relative_to(root).as_posix() for p in stage.rglob('*') if p.is_file())
manifest={n:sha(root/n) for n in sorted(names)}
with (here/'stack_manifest01.json').open('x') as f:json.dump(manifest,f,indent=2)
with zipfile.ZipFile(here/'stack_evidence01.zip','x',zipfile.ZIP_DEFLATED) as z:
    for n in manifest:z.write(root/n,n)
    z.write(here/'stack_manifest01.json','manifest.json');z.write(stage/'active.lock',stage.relative_to(root).as_posix()+'/active.lock/')
print(json.dumps(dict(archive_sha256=sha(here/'stack_evidence01.zip'),manifest_files=len(manifest),resolver_returncode=done.returncode)))
