"""One frozen original-session delivery, no GUI/model/performance comparison."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
from actor import run_actor
from protocol import validate_message

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json') and gate['tests_sha256']==sha(HERE/'windows_tests01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    assert all(sha(Path(plan['input_root'])/n)==v for n,v in plan['input_sha256'].items())
    stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir()
    context=multiprocessing.get_context('spawn');connection,child=context.Pipe()
    process=context.Process(target=run_actor,args=(child,plan['input_root'],str(stage/'actor')))
    process.start();child.close();status=dict(parent_pid=os.getpid(),actor_pid=process.pid,complete=False,errors=[],messages=0,report_received=False,terminal_received=False)
    with (stage/'controller.json').open('x') as f:json.dump(status,f,indent=2)
    output_sequence=0;command_sequence=0;events=[];reported=None;deadline=time.monotonic()+150
    def send(kind,**kwargs):
        global command_sequence
        command_sequence+=1;connection.send(dict(sequence=command_sequence,kind=kind,**kwargs))
    try:
        with (stage/'messages.jsonl').open('x') as log:
            while time.monotonic()<deadline:
                if not connection.poll(.2):
                    if not process.is_alive():raise RuntimeError('Actor ended without terminal message')
                    continue
                message=connection.recv();output_sequence=validate_message(message,output_sequence,process.pid)
                # Persist detached actual values, including reports; no normalization of content.
                log.write(json.dumps(message,ensure_ascii=False,default=lambda v:v.__dict__)+'\n');log.flush()
                kind=message['kind'];events.append(kind);status['messages']+=1
                if kind=='actor_ready':send('prepare')
                elif kind=='ready_to_start':
                    assert message['payload']['completed_sample']==plan['checked_sample']
                    send('start',quality_key=message['payload']['quality_key'])
                elif kind=='report_value':reported=message['payload']['report'];status['report_received']=True
                elif kind=='terminal':
                    status['terminal_received']=True;assert message['payload']['complete'] and not message['payload']['errors'];break
            if not status['terminal_received']:raise TimeoutError('Actor completion unconfirmed; retain PID/locks')
        process.join(15);assert not process.is_alive() and process.exitcode==0
        assert status['report_received'] and events.count('started')==1 and events.count('ready_to_start')==1 and events.count('drained_eof')==1
        assert events.index('prepared')<events.index('ready_to_start')<events.index('started')<events.index('drained_eof')<events.index('report_value')<events.index('terminal')
        assert reported==read(stage/'actor/report.json')
        result=read(stage/'actor/result.json');assert result['complete'] and result['reader_stopped'] and result['controller_released']
        from verify import verify_values
        status['semantics']=verify_values(stage/'actor',ROOT)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        status.update(actor_still_alive=process.is_alive(),actor_exitcode=process.exitcode,commands_sent=command_sequence)
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status,indent=2));raise SystemExit(not status['complete'])
