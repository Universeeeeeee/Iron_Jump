"""Frozen alternating WPR OFF/ON calibration; instance-local tracing only."""
import json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;INSTANCE='IronJumpSingleUsbSchedule'
PLAN=json.loads((HERE/'plan.json').read_text(encoding='utf-8'))

def command(args,path):
    r=subprocess.run(args,capture_output=True,timeout=90);path.write_bytes(r.stdout+r.stderr)
    return r.returncode,(r.stdout+r.stderr).decode('utf-8',errors='replace')

def run(item):
    name,mode,on=item['name'],item['mode'],item['trace'];out=HERE/'runs'/name;assert not out.exists();trace_owned=False
    status_code,status=command(['wpr.exe','-status'],HERE/(name+'_before.txt'))
    assert 'WPR is not recording' in status,'Existing WPR session; do not disturb it'
    if on:
        code,_=command(['wpr.exe','-start',str(HERE/'schedule.wprp')+'!IronJumpSchedule','-filemode','-instancename',INSTANCE],HERE/(name+'_start.txt'));assert code==0,'trace start';trace_owned=True
    success=False;terminated=False
    try:
        with (HERE/(name+'.log')).open('xb') as log:
            p=subprocess.Popen([sys.executable,str(HERE/'entry.py'),'--output',str(out),'--mode',mode],stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    marker=out/'complete.json'
                    if marker.exists():
                        m=json.loads(marker.read_text());assert m['system_exit_code']==0 and m['serialized'],m
                        shutdown=json.loads((out/'shutdown.json').read_text());assert not shutdown['errors'] and shutdown['SDK']['stops']>0 and not shutdown['readers']
                        success=True
                        try:p.wait(timeout=3)
                        except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10);terminated=True
                        break
                    if p.poll() is not None:raise RuntimeError((name,p.returncode))
                    time.sleep(.15)
                assert success,'trial watchdog'
            finally:
                if p.poll() is None:p.terminate();p.wait(timeout=10)
        (out/'exit_cleanup.json').write_text(json.dumps({'success':success,'terminated_after_confirmed_success':terminated,'returncode':p.returncode}))
    finally:
        if trace_owned:
            command(['wpr.exe','-status','collectors','-details','-instancename',INSTANCE],HERE/(name+'_trace_status.txt'))
            code,_=command(['wpr.exe','-stop',str(HERE/(name+'.etl')),'-instancename',INSTANCE],HERE/(name+'_stop.txt'));assert code==0,'trace stop failed'
    print('DONE',name,flush=True)

if __name__=='__main__':
    for item in PLAN['trials']:run(item);time.sleep(8)
    (HERE/'batch_complete.json').write_text(json.dumps({'completed':len(PLAN['trials'])}))
