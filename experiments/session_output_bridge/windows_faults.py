"""One fixed native-Pipe cohort; synthetic values only, never loads IronJump."""
import hashlib
import json
import multiprocessing
from pathlib import Path
import threading
from outbox import Outbox,OutboxError

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

class Watched:
    def __init__(self,connection):self.connection=connection;self.entered=threading.Event();self.returned=threading.Event()
    def send_bytes(self,packet):
        self.entered.set();self.connection.send_bytes(packet);self.returned.set()

def run_case(name,folder,plan):
    folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    reader,writer=multiprocessing.Pipe(duplex=False);watched=Watched(writer)
    limits=plan['limits'][name];box=Outbox(watched,max_messages=limits['messages'],max_bytes=limits['bytes'])
    result=dict(case=name,contract_pass=False,errors=[])
    try:
        if name=='normal':
            for n in range(1,9):box.enqueue(dict(sequence=n,value=n*2))
            received=[]
            for n in range(1,9):
                assert reader.poll(2);value=reader.recv();assert value==dict(sequence=n,value=n*2);received.append(value['sequence'])
            result['transport_complete']=box.finish(2);assert result['transport_complete']
            result['independent_parent_received_sequences']=received
        elif name=='disconnected_peer':
            reader.close();box.enqueue(dict(sequence=1,value='synthetic'))
            result['transport_complete']=box.finish(2);assert not result['transport_complete']
            assert box.snapshot()['failure']['reason'].startswith('send_failed:')
            box.preserve(folder/'unconfirmed')
            result['expected_transport_failure']=True
        elif name=='native_backpressure':
            value=b'x'*plan['backpressure_payload_bytes']
            box.enqueue(dict(sequence=1,payload=value));assert watched.entered.wait(2)
            assert reader.poll(2),'No native pipe data observed'
            assert not watched.returned.wait(.05),'No blocked native write observed; do not add samples'
            box.enqueue(dict(sequence=2,payload=value))
            try:box.enqueue(dict(sequence=3,payload=value))
            except OutboxError:pass
            else:raise AssertionError('In-flight output omitted from count limit')
            before=box.snapshot();assert before['failure']['reason']=='message_limit' and before['accepted_resident_messages']==2
            assert before['accepted_resident_bytes']<=limits['bytes'] and before['writer_alive']
            assert not box.finish(.02);box.preserve(folder/'unconfirmed_before_read')
            result['native_pipe_data_observed_before_parent_read']=True
            result['native_write_call_unreturned_before_parent_read']=True
            result['producer_reached_bound_without_parent_read']=True
            result['state_before_parent_read']=box.snapshot()
            assert reader.poll(2);received=reader.recv();assert received==dict(sequence=1,payload=value)
            result['transport_complete']=box.finish(2);assert not result['transport_complete']
            assert not box.snapshot()['writer_alive'] and box.snapshot()['pending_sequences']==[2]
            result['independent_parent_received_sequences']=[1]
            result['expected_transport_failure']=True
        else:raise ValueError('Unknown frozen case')
        result['contract_pass']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        # Only owned synthetic pipe handles close; never terminate any target process.
        reader.close();writer.close();box.finish(2)
        result['final_outbox']=box.snapshot()
        if result['final_outbox']['writer_alive']:
            result['contract_pass']=False;result['errors'].append('Writer termination unconfirmed')
        with (folder/'result.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    return result

if __name__=='__main__':
    plan=read(HERE/'plan01.json');gate=read(HERE/'preflight_passed01.json')
    assert gate['passed'] and gate['plan_sha256']==sha(HERE/'plan01.json') and gate['tests_sha256']==sha(HERE/'windows_tests01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    stage=HERE/'runs';stage.mkdir(exist_ok=False);(stage/'active.lock').mkdir();status=dict(complete=False,cases=[],errors=[])
    try:
        for name in plan['cases']:
            result=run_case(name,stage/name,plan);status['cases'].append(name);print(json.dumps(result),flush=True)
            if not result['contract_pass']:raise RuntimeError('Failed synthetic window retained: '+name)
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        with (stage/'status.json').open('x') as f:json.dump(status,f,indent=2)
    raise SystemExit(not status['complete'])
