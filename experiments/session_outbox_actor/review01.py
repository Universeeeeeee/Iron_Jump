"""Derive actor facts from retained archives; original failed parent gate stays failed."""
import copy
import hashlib
import json
from pathlib import Path
import pickle
import sys
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT))
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(report):
    report=copy.deepcopy(report)
    for item in (report['report_config_snapshot']['device'],report['report_config_snapshot']['beam_quality']['preflight']):del item['checked_monotonic_ns']
    return report

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');original=read(raw/'runs/status.json')
    assert not original['complete'] and original['cases']==plan['cases']
    reference=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture';cases={}
    for name in plan['cases']:
        folder=raw/'runs'/name;parent=read(folder/'status.json');actor=read(folder/'actor/result.json');out=actor['outbox']
        assert not parent['actor_still_alive'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['controller_released']
        assert parent['actor_pid']==actor['pid'] and parent['actor_pid']!=parent['parent_pid']
        messages=[json.loads(v) for v in (folder/'messages.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [v['sequence'] for v in messages]==list(range(1,len(messages)+1)) and all(v['pid']==actor['pid'] for v in messages)
        report=read(folder/'actor/report.json');state=read(folder/'actor/state.json')
        with np.load(folder/'actor/raw_frames.npz') as a,np.load(reference/'raw_frames.npz') as b:
            count=len(a['sample_indices'])
            for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(a[key],b[key][:count])
            assert np.all(np.diff(a['received_ns'])>=0)
            mask=(a['sample_indices']>plan['checked_sample'])&(a['sample_indices']<=actor['accepted_last_sample'])
            accepted=int(np.count_nonzero(mask));assert accepted==actor['accepted_last_sample']-plan['checked_sample']
            assert accepted==report['report_config_snapshot']['raw_buffer']['total_received_frames']
            assert hashlib.sha256(a['bits'][mask].tobytes()).hexdigest()==state['raw_archive_sha256']
        snapshot=read(folder/'actor/output_snapshot/state.json');saved=[]
        for file,digest in snapshot['unconfirmed_files'].items():
            path=folder/'actor/output_snapshot'/file;assert sha(path)==digest
            value=pickle.loads(path.read_bytes());assert value['pid']==actor['pid'];saved.append(value['sequence'])
        assert sorted(saved)==snapshot['state']['pending_sequences']
        if name=='normal':
            assert parent['contract_pass'] and actor['complete'] and parent['actor_exitcode']==0 and actor['writer_stop_confirmed']
            assert not actor['errors'] and actor['transport_fault'] is None and out['failure'] is None
            assert out['accepted']==out['write_calls_returned']==len(messages) and out['pending_sequences']==[]
            assert messages[-1]['kind']=='payload_end' and messages[-1]['payload']['transport_unconfirmed']
            values=[v['payload']['report'] for v in messages if v['kind']=='report_value'];assert values==[report]
            assert canonical(report)==canonical(read(reference/'report.json'))
            baseline=read(reference/'measurement.json')['state'];given=copy.deepcopy(state)
            for value in (given,baseline):del value['quality']['preflight']['checked_monotonic_ns']
            assert given==baseline
        else:
            assert not actor['complete'] and parent['actor_exitcode']!=0 and actor['transport_fault'] is not None and actor['errors']
            assert out['failure'] is not None and report['finish_reason']=='ipc_transport_failure'
            assert not out['parent_application_receipt_confirmed']
            if name=='parent_stall':
                assert not parent['contract_pass'] and parent['errors']
                assert out['failure']['reason']=='message_limit' and out['high_accepted_messages']==out['max_messages']==128
                assert out['high_accepted_bytes']<=out['max_bytes'] and len(saved)==128
                assert not actor['writer_stop_confirmed'] and snapshot['state']['writer_alive']
        cases[name]=dict(original_parent_contract_pass=parent['contract_pass'],actor_complete=actor['complete'],
            ingress_prefix_frames=count,accepted_formal_frames=accepted,raw_prefix_and_archive_verified=True,
            local_report_and_quality_state_saved=True,measurement_resources_stopped=True,actor_exitcode=parent['actor_exitcode'],
            writer_stop_confirmed_at_record=actor['writer_stop_confirmed'],received_message_count=len(messages),
            unconfirmed_packet_count=len(saved),outbox_failure=out['failure'],high_accepted_messages=out['high_accepted_messages'],
            high_accepted_bytes=out['high_accepted_bytes'],full_report_algorithm_oracle=name=='normal')
    result=dict(original_validation_cohort_pass=False,independent_actor_observations_verified=True,cases=cases,
        actual_parent_process_death_tested=False,partial_report_algorithm_oracle=False,gui_proxy_or_performance_qualification=False,field_fix_verified=False,
        limits=['First parent validator failed onpollBrokenPipe; its failedstatus andruntime files remain unchanged.','Closed parent endpoint andpaused reading are tested, not forcedGUIparent process death.','Failed writer confirmation is retained despite subsequent OSprocess exit; no transport success inferred.','No replacement windows or extension of15sec pause.'],
        bindings=dict(manifest_sha256=sha(raw/'manifest.json'),plan_sha256=sha(HERE/'plan01.json'),reference_report_sha256=sha(reference/'report.json'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
