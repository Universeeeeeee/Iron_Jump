"""Three frozen saved-input command scenarios; never substitutes an old window."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
from actor import run_actor
from commands import NOTIFICATIONS

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def scenario(name,plan,stage):
    folder=stage/name;folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    context=multiprocessing.get_context('spawn');connection,child=context.Pipe()
    process=context.Process(target=run_actor,args=(child,plan['input_root'],str(folder/'actor')))
    process.start();child.close()
    result=dict(case=name,parent_pid=os.getpid(),actor_pid=process.pid,complete=False,errors=[],commands=[],output_sequence=0)
    with (folder/'controller.json').open('x') as f:json.dump(result,f,indent=2)
    events=[];received_report=None;rejections=[];completion=[];terminal=None;sent_stop=False;command_sequence=0
    def send(kind,**kwargs):
        nonlocal command_sequence
        command_sequence+=1;command=dict(sequence=command_sequence,kind=kind,**kwargs);result['commands'].append(command);connection.send(command)
    try:
        deadline=time.monotonic()+150
        with (folder/'messages.jsonl').open('x',encoding='utf-8') as log:
            while time.monotonic()<deadline:
                if not connection.poll(.2):
                    if not process.is_alive():raise RuntimeError('Actor ended without terminal message')
                    continue
                message=connection.recv()
                assert message['sequence']==result['output_sequence']+1 and message['pid']==process.pid
                result['output_sequence']=message['sequence'];kind=message['kind'];events.append(kind)
                log.write(json.dumps(message,ensure_ascii=False,default=lambda v:v.__dict__)+'\n');log.flush()
                if kind=='actor_ready':send('prepare')
                elif kind=='ready_to_start':
                    assert message['payload']['completed_sample']==plan['checked_sample']
                    if name=='discard_ready':send('discard')
                    else:send('start',quality_key=message['payload']['quality_key'])
                elif kind=='started' and name=='full_with_unsupported_pause':send('pause');send('resume')
                elif kind=='command_rejected':rejections.append(message['payload'])
                elif kind=='command_completed':completion.append(message['payload'])
                elif kind=='notification':assert message['payload']['signal'] in NOTIFICATIONS
                elif kind=='snapshot' and name=='early_stop' and not sent_stop:
                    timing=message['payload'].get('device_timing')
                    if timing and timing['frame_index']>=plan['checked_sample']+plan['early_stop_after_samples']:
                        sent_stop=True;send('stop')
                elif kind=='drained_eof' and name=='full_with_unsupported_pause' and not sent_stop:sent_stop=True;send('stop')
                elif kind=='report_value':received_report=message['payload']['report']
                elif kind=='terminal':terminal=message['payload'];break
            assert terminal and terminal['complete'] and not terminal['errors']
        process.join(15);assert not process.is_alive() and process.exitcode==0
        actor=read(folder/'actor/result.json');assert actor['complete'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['controller_released']
        assert len(completion)==1 and completion[0]['reader_stopped'] and completion[0]['qt_thread_stopped']
        if name=='discard_ready':
            assert completion[0]['kind']=='discard' and not actor['armed'] and received_report is None and not (folder/'actor/report.json').exists()
            result['semantics']=dict(no_started_or_report=True,discard_completed_after_resource_stop=True,source_fixture_arm_error=actor['source_arm_error'])
        else:
            assert received_report==read(folder/'actor/report.json') and completion[0]['kind']=='stop'
            assert events.index('command_completed')<events.index('report_value')<events.index('terminal')
            if name=='full_with_unsupported_pause':
                assert [v['kind'] for v in rejections]==['pause','resume'] and all(not v['applied'] and v['status']=='unsupported' for v in rejections)
                assert events.count('drained_eof')==1
                from verify import verify_values
                result['semantics']=verify_values(folder/'actor',ROOT)
            else:
                from verify_partial import verify_partial_stop
                result['semantics']=verify_partial_stop(folder/'actor',ROOT,plan['checked_sample'])
        result.update(complete=True,rejections=rejections,completions=completion)
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result.update(actor_still_alive=process.is_alive(),actor_exitcode=process.exitcode)
        with (folder/'status.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    return result

if __name__=='__main__':
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json') and gate['tests_sha256']==sha(HERE/'windows_tests01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(complete=False,cases=[],errors=[])
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    try:
        for name in plan['cases']:
            result=scenario(name,plan,stage);status['cases'].append(name);print(json.dumps(result),flush=True)
            if not result['complete']:raise RuntimeError('Failed scenario retained: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(not status['complete'])
