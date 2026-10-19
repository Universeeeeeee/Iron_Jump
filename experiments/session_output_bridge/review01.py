"""Independently inspect synthetic native-Pipe outcomes and preserved packet values."""
import hashlib
import json
from pathlib import Path
import pickle

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    status=read(raw/'runs/status.json');plan=read(HERE/'plan01.json');assert status['complete'] and status['cases']==plan['cases'] and not status['errors']
    cases={name:read(raw/'runs'/name/'result.json') for name in plan['cases']}
    assert all(v['contract_pass'] and not v['errors'] and not v['final_outbox']['writer_alive'] for v in cases.values())
    normal=cases['normal'];assert normal['transport_complete'] and normal['independent_parent_received_sequences']==list(range(1,9))
    assert normal['final_outbox']['write_calls_returned']==8 and normal['final_outbox']['pending_sequences']==[]
    peer=cases['disconnected_peer'];assert not peer['transport_complete'] and peer['final_outbox']['write_calls_returned']==0 and peer['final_outbox']['pending_sequences']==[1]
    assert peer['final_outbox']['failure']['reason'].startswith('send_failed:')
    slow=cases['native_backpressure'];assert slow['native_pipe_data_observed_before_parent_read'] and slow['native_write_call_unreturned_before_parent_read'] and slow['producer_reached_bound_without_parent_read']
    before=slow['state_before_parent_read'];assert before['writer_alive'] and before['accepted_resident_messages']==before['max_messages']==2
    assert before['accepted_resident_bytes']<=before['max_bytes'] and before['write_calls_returned']==0 and before['pending_sequences']==[1,2]
    assert not slow['transport_complete'] and slow['final_outbox']['failure']['reason']=='message_limit'
    assert slow['independent_parent_received_sequences']==[1] and slow['final_outbox']['pending_sequences']==[2]
    saved=[]
    for path in (raw/'runs').rglob('state.json'):
        record=read(path)
        for name,digest in record['unconfirmed_files'].items():
            file=path.parent/name;assert sha(file)==digest
            # Only the hash-bound synthetic packets created by this cohort.
            packet=pickle.loads(file.read_bytes());saved.append(packet['sequence'])
            if path.parent.name=='unconfirmed_before_read':assert packet==dict(sequence=packet['sequence'],payload=b'x'*plan['backpressure_payload_bytes'])
            else:assert packet==dict(sequence=1,value='synthetic')
    assert sorted(saved)==[1,1,2]
    result=dict(synthetic_component_gate_pass=True,normal_native_received_8_exact=True,closed_native_peer_retains_failure=True,
        native_unreturned_write_counted_in_limits=True,resume_read_does_not_clear_failure=True,all_preserved_packet_hashes_and_values_pass=True,
        actor_integrated=False,actual_actor_parent_process_death_checked=False,raw_preservation_after_actor_transport_failure_checked=False,
        gui_or_throughput_qualification=False,field_fix_verified=False,
        cases=cases,limits=['Native endpoint closure and stopped reader are channel controls, not a measurement-actor crash test.','Bounds apply to acceptedserialized bytes includinginflight, not caller objects, serialization temporaries orOS buffers.','A successful local write is never used as proof of parent application receipt.'],
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),manifest_sha256=sha(raw/'manifest.json'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
