"""Own native stdout/stderr in Python; preserve target identity on timeout."""
import json
from pathlib import Path
import subprocess
import sys


def capture(command,folder,timeout):
    folder.mkdir(parents=True,exist_ok=False);record=dict(command=command,complete=False);target=None
    try:
        with (folder/'stdout.log').open('xb') as out,(folder/'stderr.log').open('xb') as err:
            target=subprocess.Popen(command,stdout=out,stderr=err)
            with (folder/'started.json').open('x') as f:json.dump(dict(pid=target.pid,command=command),f,indent=2)
            record['pid']=target.pid
            try:record['returncode']=target.wait(timeout=timeout)
            except subprocess.TimeoutExpired:record['observation_timeout']=True
            record['target_still_running']=target.poll() is None
            record['complete']=not record['target_still_running'] and record.get('returncode')==0
    except BaseException as exc:
        record['error']=repr(exc);record['target_still_running']=target is not None and target.poll() is None
    finally:
        with (folder/'result.json').open('x') as f:json.dump(record,f,indent=2)
    return record,target

if __name__=='__main__':
    # Future attempts require a new frozen plan, case ID and unused launch folder.
    folder=Path(sys.argv[1]);script=Path(sys.argv[2]);result,_=capture([sys.executable,str(script)],folder,240)
    print(json.dumps(result));raise SystemExit(0 if result['complete'] else 1)
