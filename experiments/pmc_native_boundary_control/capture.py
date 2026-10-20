"""One owned PMC delivery trial. Does not modify sample interval or launch real work."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from winapi import profile_interval

HERE=Path(__file__).resolve().parent

def capture(here=HERE,run=subprocess.run,interval=profile_interval):
    with (here/'active.lock').open('x') as f:f.write('One delivery attempt; retain all evidence.')
    plan=json.loads((here/'capture_plan02.json').read_text())
    assert all(hashlib.sha256((here/n).read_bytes()).hexdigest()==v for n,v in plan['sources'].items())
    result=dict(commands=[],target_started=False,cleanup_confirmed=False,pmc_delivery_verified=False)
    started=False
    def call(args):
        try:r=run(args,capture_output=True)
        except BaseException as error:
            result['commands'].append(dict(args=args,error=repr(error)))
            return subprocess.CompletedProcess(args,1,b'',repr(error).encode())
        result['commands'].append(dict(args=args,returncode=r.returncode,stdout=r.stdout.decode(errors='replace'),stderr=r.stderr.decode(errors='replace'),
            stdout_base64=base64.b64encode(r.stdout).decode(),stderr_base64=base64.b64encode(r.stderr).decode()))
        return r
    try:
        before=call(['logman','query','-ets'])
        if before.returncode or any(x in before.stdout.decode(errors='replace').lower() for x in ('wpr_system','nt kernel logger','ijnative_','ironjumppmc')):
            raise RuntimeError('Existing/unknown kernel session; leave untouched')
        result['interval_before_100ns']=interval()
        instance=plan['instance']
        start=call(['wpr','-start',str(here/'counters.wprp')+'!PmcDelivery','-filemode','-instancename',instance])
        started=start.returncode==0
        if not started:raise RuntimeError('PMC start rejected; do not launch control orretry')
        result['target_started']=True
        target=call([sys.executable,str(here/'target.py')])
        if target.returncode:raise RuntimeError('Native control failed; no replacement')
    except BaseException as error:result['failure']=repr(error)
    finally:
        if started:
            stop=call(['wpr','-stop',str(here/'trace01.etl'),'-instancename',plan['instance']])
            result['stop_returncode']=stop.returncode
        sessions=call(['logman','query','-ets']);status=call(['wpr','-status','-instancename',plan['instance']])
        result['sessions_after']=sessions.stdout.decode(errors='replace')
        result['owned_status_after']=status.stdout.decode(errors='replace')
        try:result['interval_after_100ns']=interval()
        except BaseException as error:result['interval_read_error']=repr(error)
        # Stop confirmation is required after a successful start; absence is checked independently.
        result['cleanup_confirmed']=(started and result.get('stop_returncode')==0 and sessions.returncode==0 and status.returncode==0 and 'not recording' in result['owned_status_after'].lower()
            and 'ironjumppmc' not in result['sessions_after'].lower() and result.get('interval_after_100ns')==result.get('interval_before_100ns'))
        with (here/'capture01.json').open('x') as f:json.dump(result,f,indent=2)
    return int('failure' in result or not result['cleanup_confirmed'])

if __name__=='__main__':raise SystemExit(capture())
