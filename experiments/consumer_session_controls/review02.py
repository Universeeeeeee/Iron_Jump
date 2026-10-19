"""Check remaining original scenarios without rewriting the first failed cohort."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    raw=HERE/'runs/evidence02';manifest=read(raw/'manifest02.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan02.json');old=read(HERE/'plan01.json')
    assert old['sources']['actor.py']==plan['sources']['actor.py']==sha(HERE/'actor.py')
    assert not read(raw/'runs/status.json')['complete']
    assert sha(raw/'runs/full_with_unsupported_pause/status.json')==read(HERE/'first_review01.json')['bindings']['truncated_status_sha256']
    root_status=read(raw/'runs02/status.json');assert root_status['complete'] and root_status['cases']==plan['cases']
    reference=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture';cases={}
    for name in plan['cases']:
        folder=raw/'runs02'/name;status=read(folder/'status.json');actor=read(folder/'actor/result.json')
        assert status['complete'] and not status['errors'] and not status['actor_still_alive'] and status['actor_exitcode']==0
        assert actor['complete'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['controller_released']
        messages=[json.loads(v) for v in (folder/'messages.jsonl').read_text(encoding='utf-8').splitlines()]
        assert [v['sequence'] for v in messages]==list(range(1,len(messages)+1)) and all(v['pid']==status['actor_pid'] for v in messages)
        assert status['parent_pid']!=status['actor_pid'] and status['output_sequence']==len(messages)
        commands=status['commands'];assert [v['sequence'] for v in commands]==list(range(1,len(commands)+1))
        completed=[v for v in messages if v['kind']=='command_completed'];assert len(completed)==1
        ack=completed[0]['payload'];assert ack['command_sequence']==commands[-1]['sequence'] and ack['kind']==commands[-1]['kind']
        assert ack['reader_stopped'] and ack['qt_thread_stopped']
        with np.load(folder/'actor/raw_frames.npz') as a,np.load(reference/'raw_frames.npz') as b:
            size=len(a['sample_indices'])
            for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(a[key],b[key][:size])
            if name=='early_stop':
                accepted=actor['accepted_last_sample'];mask=(a['sample_indices']>plan['checked_sample'])&(a['sample_indices']<=accepted)
                state=read(folder/'actor/state.json');report=read(folder/'actor/report.json')
                assert hashlib.sha256(a['bits'][mask].tobytes()).hexdigest()==state['raw_archive_sha256']
                assert int(np.count_nonzero(mask))==report['report_config_snapshot']['raw_buffer']['total_received_frames']==accepted-plan['checked_sample']
                reports=[v for v in messages if v['kind']=='report_value'];assert len(reports)==1 and reports[0]['payload']['report']==report
                assert completed[0]['sequence']<reports[0]['sequence']<messages[-1]['sequence']
                assert report['report_config_snapshot']['device']['bad_indices']==read(reference/'report.json')['report_config_snapshot']['device']['bad_indices']
            else:
                assert not actor['armed'] and not (folder/'actor/report.json').exists() and not any(v['kind'] in ('started','report_value') for v in messages)
        cases[name]=dict(complete=True,actual_resource_stop=True,ordered_messages=len(messages),actual_ingress_prefix_frames=size,
            command_completion_correlated=True,source_arm_error=actor['source_arm_error'],semantics=status['semantics'],
            notification_counts=dict(Counter(v['payload']['signal'] for v in messages if v['kind']=='notification')))
    result=dict(remaining_scenarios_pass=True,old_failed_cohort_unchanged=True,actor_source_unchanged=True,cases=cases,
        partial_report_algorithm_oracle=False,full_gui_proxy_qualification=False,output_backpressure_qualified=False,performance_qualification=False,field_fix_verified=False,
        limits=['Full scenario retained in first failed-cohort archive and independently verified; its malformed status is not repaired.','Only remaining earlystop/discard scenarios executed with JSON logging correction.','Discard sourcefixture retains armwait timeout; productionUSB stop timing not qualified.','Notifications with zero actual occurrences only have binding tests; not actual hardware-path evidence.'],
        bindings=dict(manifest_sha256=sha(raw/'manifest02.json'),first_review_sha256=sha(HERE/'first_review01.json'),review_source_sha256=sha(Path(__file__))))
    with (HERE/'review02.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
