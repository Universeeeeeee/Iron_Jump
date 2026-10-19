"""Normal and two fixed parent-channel faults for the real saved-input actor."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
from actor import run_actor
from json_values import json_value

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def scenario(name,plan,stage):
    folder=stage/name;folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    context=multiprocessing.get_context('spawn');connection,child=context.Pipe()
    process=context.Process(target=run_actor,args=(child,plan['input_root'],str(folder/'actor')))
    process.start();child.close();command_sequence=0;rows=[];report=None;injected=False;normal_end=False;connection_closed=False
    result=dict(case=name,parent_pid=os.getpid(),actor_pid=process.pid,contract_pass=False,errors=[],commands=[])
    with (folder/'controller.json').open('x') as f:json.dump(result,f,indent=2)
    def send(kind,**kwargs):
        nonlocal command_sequence
        command_sequence+=1;value=dict(sequence=command_sequence,kind=kind,**kwargs)
        result['commands'].append(value);connection.send(value)
    try:
        deadline=time.monotonic()+160
        with (folder/'messages.jsonl').open('x',encoding='utf-8') as log:
            while time.monotonic()<deadline:
                if not connection.poll(.2):
                    if not process.is_alive():break
                    continue
                try:value=connection.recv()
                except (EOFError,OSError):break
                assert value['sequence']==len(rows)+1 and value['pid']==process.pid
                rows.append(value);log.write(json.dumps(value,ensure_ascii=False,default=json_value)+'\n');log.flush()
                kind=value['kind']
                if kind=='actor_ready':send('prepare')
                elif kind=='ready_to_start':
                    assert value['payload']['completed_sample']==plan['checked_sample']
                    send('start',quality_key=value['payload']['quality_key'])
                elif kind=='started' and name=='peer_disconnect':
                    connection.close();connection_closed=True;injected=True;break
                elif kind=='started' and name=='parent_stall':
                    injected=True;result['stall_started_ns']=time.perf_counter_ns()
                    time.sleep(plan['stall_seconds'])
                    result['stall_ended_ns']=time.perf_counter_ns()
                    # Do not wait longer to manufacture a fault. If the original
                    # budget did not trigger it, request graceful stop for cleanup.
                    if not (folder/'actor/result.json').exists():
                        try:send('stop')
                        except (EOFError,OSError) as exc:result['cleanup_send_error']=repr(exc)
                elif kind=='drained_eof' and name=='normal':send('stop')
                elif kind=='report_value':report=value['payload']['report']
                elif kind=='payload_end':
                    normal_end=True;break
        process.join(20)
        assert not process.is_alive(),'Actor still live; preserve PID/locks, do not terminate/restart'
        actor=read(folder/'actor/result.json')
        assert actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['controller_released']
        assert actor['report_saved'] and (folder/'actor/report.json').exists() and (folder/'actor/state.json').exists()
        result.update(actor_exitcode=process.exitcode,received_sequences=len(rows),measurement_resources_stopped=True,actor_status=actor['complete'])
        if name=='normal':
            assert normal_end and process.exitcode==0 and actor['complete'] and not actor['errors'] and actor['transport_fault'] is None
            assert actor['writer_stop_confirmed'] and actor['outbox']['failure'] is None and actor['outbox']['accepted']==actor['outbox']['write_calls_returned']==len(rows)
            assert report==read(folder/'actor/report.json') and rows[-1]['kind']=='payload_end' and rows[-1]['payload']['transport_unconfirmed']
            from verify import verify_values
            result['semantics']=verify_values(folder/'actor',ROOT)
            result['independent_application_receipt_confirmed']=True
        else:
            assert injected and process.exitcode!=0 and not actor['complete'] and actor['errors'] and actor['transport_fault'] is not None
            assert actor['outbox']['failure'] is not None and not actor['outbox']['parent_application_receipt_confirmed']
            assert read(folder/'actor/report.json')['finish_reason']=='ipc_transport_failure'
            from verify_fault import verify_fault_values
            result['semantics']=verify_fault_values(folder/'actor',ROOT,plan['checked_sample'])
            result.update(expected_actor_failure=True,independent_application_receipt_confirmed=False,
                          fault_reason=actor['outbox']['failure']['reason'],writer_stop_confirmed=actor['writer_stop_confirmed'])
            if name=='parent_stall':
                assert actor['outbox']['failure']['reason'] in ('message_limit','byte_limit')
                assert actor['outbox']['high_accepted_messages']<=plan['output_max_messages'] and actor['outbox']['high_accepted_bytes']<=plan['output_max_bytes']
        result['contract_pass']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        result.update(actor_still_alive=process.is_alive(),actor_exitcode=process.exitcode)
        if not connection_closed:connection.close()
        with (folder/'status.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,default=json_value)
    return result

if __name__=='__main__':
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json') and gate['tests_sha256']==sha(HERE/'windows_tests01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['existing_sources'].items())
    stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(complete=False,cases=[],errors=[])
    with (stage/'controller.json').open('x') as f:json.dump(dict(pid=os.getpid()),f)
    try:
        for name in plan['cases']:
            result=scenario(name,plan,stage);status['cases'].append(name);print(json.dumps(result,default=json_value),flush=True)
            if not result['contract_pass']:raise RuntimeError('Failed window retained: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(not status['complete'])
