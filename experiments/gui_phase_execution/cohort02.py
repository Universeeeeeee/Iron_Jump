"""Exactly two original-GUI windows; no silent repair or replacement."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from run_gate import require_gate
from context_gate import check_context
from verify_runtime import verify_runtime

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=require_gate(HERE);stage=HERE/'runs/phase02';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir()
    status=dict(complete=False,cases=[],errors=[],controller_pid=os.getpid());session=None
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    try:
        sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'));import semantics02
        for case in plan['cases']:
            require_gate(HERE)
            assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
            assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
            folder=stage/case['id'];folder.mkdir();(folder/'active.lock').mkdir();capture=folder/'capture';target=None;record=dict(case=case,errors=[])
            try:
                with (folder/'target.stdout').open('xb') as out,(folder/'target.stderr').open('xb') as err:
                    target=subprocess.Popen([sys.executable,str(HERE/'gui_entry02.py'),'--qos-variant',case['variant'],'--input',plan['input_root'],'--output',str(capture),'--mode','walk','--variant','A','--probe','P','--load','fixed'],stdout=out,stderr=err)
                    record['target_pid']=target.pid;record['target_returncode']=target.wait(timeout=240)
                assert record['target_returncode']==0
                measurement,*_=semantics02.verify(capture);assert measurement['sdk']['stop_success'] and not measurement['sdk_errors']
                final=read(capture/'finalization.json');assert final['metadata_finalization_pass']
                backend=read(capture/'sdk_backend.json');assert backend['backend']=='simulated_native_SDK' and backend['serve_returncode']==0 and backend['calls']['close']==1 and backend['no_native_device_opened']
                active=read(folder/'qos_activation.json');check_context(active['context'],session)
                if session is None:session=active['context']['session_id']
                record['runtime_context']=verify_runtime(active,case['variant'],session)
                from verify_phases import verify_phases
                record['native_phases']=verify_phases(folder/'native_phases')
                assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items());require_gate(HERE)
                record.update(complete=True,full_original_semantics_exact=True,original_return_confirmed=final['application_return_model_confirmed'])
            except BaseException as exc:record['errors'].append(repr(exc))
            finally:
                record['target_still_running']=target is not None and target.poll() is None
                with (folder/'record.json').open('x') as f:json.dump(record,f,indent=2)
            status['cases'].append(case['id']);print(json.dumps(record),flush=True)
            if record['errors'] or record['target_still_running']:raise RuntimeError('Failed window retained: '+case['id'])
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(bool(status['errors']))
