"""One original GUI identity window; no candidate or optional extension."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from gate import require_gate
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=require_gate(HERE);stage=HERE/'runs/cohort01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir()
    status=dict(complete=False,cases=[],errors=[],controller_pid=os.getpid());session=None
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    try:
        for case in plan['cases']:
            require_gate(HERE)
            assert all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
            assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
            folder=stage/case['id'];folder.mkdir();(folder/'active.lock').mkdir();target=None;record=dict(case=case,errors=[])
            try:
                with (folder/'target.stdout').open('xb') as out,(folder/'target.stderr').open('xb') as err:
                    target=subprocess.Popen([sys.executable,str(HERE/'entry.py'),'--case',case['id']],stdout=out,stderr=err)
                    record['target_pid']=target.pid;record['target_returncode']=target.wait(timeout=240)
                assert record['target_returncode']==0
                capture=folder/'capture';assert (capture/'pipeline_review.json').exists() and read(capture/'gui_result.json')['complete']
                sys.path.insert(0,str(ROOT/'experiments/consumer_session_delivery'));from verify import verify_values
                record['semantics']=verify_values(capture/'client/actor',ROOT)
                context=read(capture/'gui_context.json');assert context['session_id']!=0 and context['priority_class']==16384 and context['qpa']=='windows'
                if session is None:session=context['session_id']
                assert session==context['session_id']
                assert b'Traceback' not in (folder/'target.stderr').read_bytes()
                require_gate(HERE);record['complete']=True
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
