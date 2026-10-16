"""Fresh process per pair; no periodic shell polling inside a GUI session."""
import json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def pair(name,mode,smoke=False):
    out=HERE/'runs'/name;assert not out.exists()
    command=[sys.executable,str(HERE/'entry.py'),'--output',str(out),'--mode',mode]+(['--smoke'] if smoke else [])
    with (HERE/(name+'.log')).open('xb') as log:
        p=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT);success=False;terminated=False
        try:
            end=time.monotonic()+240
            while time.monotonic()<end:
                marker=out/'complete.json'
                if marker.exists():
                    m=json.loads(marker.read_text());assert m['system_exit_code']==0 and m['pair_serialized'],m;success=True
                    try:p.wait(timeout=3)
                    except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10);terminated=True
                    break
                if p.poll() is not None:raise RuntimeError((name,p.returncode))
                time.sleep(.15)
            assert success,'pair watchdog'
        finally:
            if p.poll() is None:p.terminate();p.wait(timeout=10)
    (out/'exit_cleanup.json').write_text(json.dumps({'successful_serialization_and_SDK_teardown':success,'native_exit_telemetry_terminated_after_success':terminated,'return_code':p.returncode}))
    print('DONE',name,flush=True)
if __name__=='__main__':
    stage=sys.argv[1]
    if stage=='smoke':pair('smoke_01_walk','walk',True)
    else:
        assert stage=='formal'
        for n,mode in enumerate(('walk','run','walk','run','walk','run'),1):
            pair(f'pair_{n:02d}_{mode}',mode);time.sleep(10)
