"""Execute the one frozen GUI semantic window and its independent verifier."""
import json
import subprocess
import sys
from pathlib import Path
from gate import require

HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    require(HERE);lock=HERE/'active.lock';lock.mkdir();status=dict(complete=False,steps=[],errors=[])
    try:
        for name,command,timeout in [('gui',[sys.executable,str(HERE/'entry.py')],300),('verify',[sys.executable,str(HERE/'verify.py')],30)]:
            record=dict(name=name,command=command,complete=False,errors=[]);target=None
            try:
                with (HERE/(name+'.stdout')).open('xb') as out,(HERE/(name+'.stderr')).open('xb') as err:
                    target=subprocess.Popen(command,stdout=out,stderr=err);record['pid']=target.pid;record['returncode']=target.wait(timeout=timeout)
                assert record['returncode']==0 and b'Traceback' not in (HERE/(name+'.stderr')).read_bytes();record['complete']=True
            except BaseException as exc:record['errors'].append(repr(exc))
            finally:
                record['target_still_running']=target is not None and target.poll() is None
                with (HERE/(name+'.record.json')).open('x') as output:json.dump(record,output,indent=2)
                status['steps'].append(record)
            if record['errors'] or record['target_still_running']:raise RuntimeError('Stop at failed step: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (HERE/'status01.json').open('x') as output:json.dump(status,output,indent=2)
    print(json.dumps(status));raise SystemExit(bool(status['errors']))
