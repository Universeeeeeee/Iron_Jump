"""Run exactly one frozen first window per distinct Windows boot."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from gate import require_gate

HERE=Path(__file__).resolve().parent

def next_case(cases,records):
    completed={name for name,value in records.items() if value.get('complete')}
    failed=[name for name,value in records.items() if not value.get('complete')]
    if failed:raise RuntimeError('Failed cold-boot case retained; no continuation: '+failed[0])
    return next((case for case in cases if case['id'] not in completed),None)

def boot_context():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.GetTickCount64.restype=ctypes.c_ulonglong
    uptime_ms=int(kernel.GetTickCount64());now_100ns=int(time.time_ns()//100+116444736000000000);boot_100ns=now_100ns-uptime_ms*10000
    class Power(ctypes.Structure):_fields_=[('ac',ctypes.c_byte),('battery_flag',ctypes.c_byte),('battery_percent',ctypes.c_byte),('system_status',ctypes.c_byte),('lifetime',wintypes.DWORD),('full_lifetime',wintypes.DWORD)]
    power=Power();assert kernel.GetSystemPowerStatus(ctypes.byref(power))
    session=wintypes.DWORD();assert kernel.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
    kernel.GetPriorityClass.restype=wintypes.DWORD;kernel.GetCurrentProcess.restype=wintypes.HANDLE
    return dict(boot_100ns=boot_100ns,uptime_seconds=uptime_ms/1000,session_id=session.value,priority_class=kernel.GetPriorityClass(kernel.GetCurrentProcess()),ac_online=int(power.ac))

if __name__=='__main__':
    plan=require_gate(HERE);stage=HERE/'runs/cold01';stage.mkdir(parents=True,exist_ok=True)
    lock=stage/'active.lock'
    if not lock.exists():lock.mkdir()
    records={}
    for case in plan['cases']:
        path=stage/case['id']/'record.json'
        if path.exists():records[case['id']]=json.loads(path.read_text())
    case=next_case(plan['cases'],records)
    if case is None:
        status=dict(complete=True,cases=[c['id'] for c in plan['cases']],errors=[])
        target=stage/'status.json'
        if not target.exists():target.write_text(json.dumps(status,indent=2))
        print(json.dumps(status));raise SystemExit(0)
    context=boot_context();previous=[r['boot']['boot_100ns'] for r in records.values()]
    if previous and min(abs(context['boot_100ns']-value) for value in previous)<300000000:raise RuntimeError('A new Windows boot is required for '+case['id'])
    settle=plan['boot']['settle_seconds']-context['uptime_seconds']
    if settle>0:time.sleep(settle);context=boot_context()
    assert plan['boot']['settle_seconds']<=context['uptime_seconds']<=plan['boot']['maximum_uptime_seconds']
    assert context['session_id']!=0 and context['priority_class']==16384 and context['ac_online']==1
    folder=stage/case['id'];folder.mkdir();(folder/'active.lock').mkdir();target=None
    record=dict(case=case,boot=context,complete=False,errors=[],target_still_running=None)
    try:
        with (folder/'target.stdout').open('xb') as out,(folder/'target.stderr').open('xb') as err:
            target=subprocess.Popen([sys.executable,str(HERE/'entry.py'),'--case',case['id']],stdout=out,stderr=err)
            record['target_pid']=target.pid;record['target_returncode']=target.wait(timeout=300)
        assert record['target_returncode']==0 and b'Traceback' not in (folder/'target.stderr').read_bytes()
        capture=folder/'capture';assert json.loads((capture/'gui_result.json').read_text())['complete'] and (capture/'pipeline_review.json').exists()
        record['complete']=True
    except BaseException as exc:record['errors'].append(repr(exc))
    finally:
        record['target_still_running']=target is not None and target.poll() is None
        (folder/'record.json').write_text(json.dumps(record,indent=2))
    if record['errors'] or record['target_still_running']:raise SystemExit(1)
    remaining=next_case(plan['cases'],{**records,case['id']:record})
    if remaining is None:
        status=dict(complete=True,cases=[c['id'] for c in plan['cases']],errors=[])
        (stage/'status.json').write_text(json.dumps(status,indent=2));print(json.dumps(status));raise SystemExit(0)
    request=dict(completed_case=case['id'],next_case=remaining['id'],requested_at=time.time_ns(),delay_seconds=plan['boot']['reboot_delay_seconds'])
    (folder/'reboot_requested.json').write_text(json.dumps(request,indent=2))
    command=['shutdown','/r','/t',str(plan['boot']['reboot_delay_seconds']),'/d','p:4:1','/c','IronJump cold-boot evidence: next '+remaining['id']]
    outcome=subprocess.run(command,capture_output=True,text=True);request['returncode']=outcome.returncode;request['stdout']=outcome.stdout;request['stderr']=outcome.stderr
    (folder/'reboot_command.json').write_text(json.dumps(request,indent=2));assert outcome.returncode==0
    print(json.dumps(request));raise SystemExit(0)
