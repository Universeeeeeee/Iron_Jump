"""One operator-started field acquisition; preserve failures, no automatic repetition."""
import json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
mode,name=sys.argv[1:];assert mode in ('walk','run') and name.replace('_','').isalnum()
out=HERE/'runs'/name;assert not out.exists()
with (HERE/(name+'.log')).open('xb') as log:
    process=subprocess.Popen([sys.executable,str(HERE/'entry.py'),'--output',str(out),'--mode',mode],stdout=log,stderr=subprocess.STDOUT)
    success=False;terminated=False
    try:
        deadline=time.monotonic()+1020
        while time.monotonic()<deadline:
            marker=out/'complete.json'
            if marker.exists():
                m=json.loads(marker.read_text());assert m['system_exit_code']==0 and m['serialized'],m;success=True
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10);terminated=True
                break
            if process.poll() is not None:raise RuntimeError((name,process.returncode))
            time.sleep(.15)
        assert success,'outer watchdog'
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=10)
(out/'exit_cleanup.json').write_text(json.dumps({'successful_serialization_and_SDK_teardown':success,'native_exit_telemetry_terminated_after_success':terminated,'return_code':process.returncode}))
print('DONE',name,flush=True)
