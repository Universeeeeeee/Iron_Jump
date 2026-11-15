"""Bounded read-only check of this experiment's recorded Windows process IDs."""
import base64
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent


def main():
    code='''from pathlib import Path
import hashlib,json,subprocess
root=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01');lab=root/'exports/sparse_processing_20261021'
plan=json.loads((root/'experiments/live_consumer_process_candidate16/plan16.json').read_text(encoding='utf-8'))
checks={n:hashlib.sha256((root/n).read_bytes()).hexdigest()==v for n,v in plan['formal_sha256'].items()}
pids=set()
for f in lab.glob('*.pid'):
 try:pids.add(int(f.read_text()))
 except ValueError:pass
for name in ('sparse_offline_process_gui_20261021','sparse_offline_process_gui_v3_20261021'):
 gui=root/'experiments'/name
 f=gui/'driver.pid'
 if f.exists():pids.add(int(f.read_text()))
 for f in (gui/'runs').glob('*/offline_result.json'):
  d=json.loads(f.read_text(encoding='utf-8'))
  if d.get('actor_pid'):pids.add(d['actor_pid'])
script='Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine,CreationDate | ConvertTo-Json -Compress'
r=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,check=True)
processes=json.loads(r.stdout)
active=[{'pid':d['ProcessId'],'command':d['CommandLine'],'created':str(d['CreationDate'])} for d in processes if d['ProcessId'] in pids]
result={'formal_plan16_hashes':checks,'formal_sources_unchanged':all(checks.values()),'recorded_owned_pids':sorted(pids),'recorded_owned_pids_still_running':active,'native_active_marker_exists':(lab/'native_v2.active').exists(),'scope':'Read-only verification; no device/camera/SDK/field capture started.'}
assert all(checks.values()) and not active and not result['native_active_marker_exists'],result
print(json.dumps(result))
'''
    encoded=base64.b64encode(code.encode()).decode()
    command='D:\\conda\\python.exe -X utf8 -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=25','-o','ConnectionAttempts=1','-o','ControlMaster=no',
        '-o','ControlPath=none','-o','ControlPersist=no','86150@100.116.17.121',command],
        capture_output=True,text=True)
    (HERE/'cleanup_retry.stdout').write_text(result.stdout)
    (HERE/'cleanup_retry.stderr').write_text(result.stderr)
    if result.returncode:raise SystemExit(result.returncode)
    parsed=json.loads(result.stdout)
    (HERE/'cleanup.json').write_text(json.dumps(parsed,indent=2))
    print(json.dumps({k:v for k,v in parsed.items() if k!='formal_plan16_hashes'}),flush=True)


if __name__=='__main__':main()
