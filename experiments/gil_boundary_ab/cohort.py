"""Fixed paired GUI replay, no adaptive repeats and no actual SDK hardware."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'ab_plan01.json');stage=HERE/'runs/ab01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir();status=dict(cases=[],errors=[],complete=False,actual_load_disturbance_pass=False)
    try:
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
        sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'));import semantics02
        for case in plan['cases']:
            folder=stage/case['id'];folder.mkdir();(folder/'active.lock').mkdir();capture=folder/'capture';target=None;record=dict(case=case,errors=[])
            try:
                with (folder/'target.stdout').open('xb') as out,(folder/'target.stderr').open('xb') as err:
                    target=subprocess.Popen([sys.executable,str(HERE/'gui_entry.py'),'--equality-variant',case['variant'],'--input',plan['input_root'],'--output',str(capture),'--mode','walk','--variant','A','--probe','P','--load','fixed'],stdout=out,stderr=err)
                    record['target_pid']=target.pid;record['target_returncode']=target.wait(timeout=240)
                assert record['target_returncode']==0
                measurement,*_=semantics02.verify(capture);assert measurement['sdk']['stop_success'] and not measurement['sdk_errors']
                final=read(capture/'finalization.json');assert final['metadata_finalization_pass']
                backend=read(capture/'sdk_backend.json');assert backend['backend']=='simulated_native_SDK' and backend['serve_returncode']==0 and backend['calls']['close']==1 and backend['no_native_device_opened']
                active=read(capture/'activation.json');assert active['variant']==case['variant'] and active['candidate_installed']==(case['variant']=='candidate') and active['original_source_file_unchanged'] and active['candidate_sha256']==plan['candidate_sha256']
                assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
                record.update(complete=True,full_original_semantics_exact=True,backend=backend,activation=active)
            except BaseException as exc:record['errors'].append(repr(exc))
            finally:
                record['target_still_running']=target is not None and target.poll() is None
                with (folder/'record.json').open('x') as f:json.dump(record,f,indent=2)
            status['cases'].append(case['id']);print(json.dumps(dict(case=case,complete=record.get('complete',False),errors=record['errors'])),flush=True)
            if record['errors'] or record['target_still_running']:raise RuntimeError('Failed case retained; no replacement: '+case['id'])
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(bool(status['errors']))
