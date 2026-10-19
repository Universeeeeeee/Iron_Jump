"""Independent file-level value recheck of four fixed offline original-code replays."""
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    plan=read(HERE/'plan01.json');status=read(raw/'runs/status.json');assert status['complete'] and not status['errors']
    locations={
        'normal_positive':ROOT/'experiments/session_outbox_actor/runs/evidence01/runs/normal/actor',
        'early_manual':ROOT/'experiments/consumer_session_controls/runs/evidence02/runs02/early_stop/actor',
        'peer_fault':ROOT/'experiments/session_outbox_actor/runs/evidence01/runs/peer_disconnect/actor',
        'stall_fault':ROOT/'experiments/session_outbox_actor/runs/evidence01/runs/parent_stall/actor'}
    assert [v['name'] for v in status['cases']]==[v['name'] for v in plan['cases']]
    cases={}
    for case in plan['cases']:
        name=case['name'];expected=locations[name];folder=raw/'runs'/name;record=read(folder/'result.json')
        for file in ('report.json','state.json','raw_frames.npz','result.json'):
            assert sha(expected/file)==plan['evidence_files'][case['actor_folder']+'/'+file]
        report=read(folder/'recomputed_report.json');state=read(folder/'recomputed_state.json')
        assert report==read(expected/'report.json') and state==read(expected/'state.json')
        assert record['report_exact'] and record['state_exact'] and not record['report_mismatches'] and not record['state_mismatches']
        assert sha(folder/'recomputed_report.json')==record['recomputed_report_sha256'] and sha(folder/'recomputed_state.json')==record['recomputed_state_sha256']
        cutoff=read(expected/'result.json')['accepted_last_sample'];bounds=record['bounds']
        assert bounds['accepted_last_sample']==cutoff and bounds['formal_frames']==cutoff-plan['checked_sample'] and bounds['reason']==case['reason']
        assert report['finish_reason']==case['reason']
        with np.load(expected/'raw_frames.npz') as z:
            assert int(np.count_nonzero(z['sample_indices']>cutoff))==bounds['ingress_tail_not_reprocessed']
        cases[name]=dict(report_value_exact=True,full_quality_runtime_state_exact=True,bounds=bounds)
    result=dict(all_four_original_code_recomputations_exact=True,normal_positive_control_pass=True,cases=cases,
        normalization_or_field_removal=False,new_capture=False,new_actor_window=False,
        previous_failed_cohort_reclassified=False,writer_confirmation_failure_reclassified=False,
        qt_scheduling_or_latency_qualification=False,all_future_partial_reports_qualified=False,field_fix_verified=False,
        limits=['Applies to these fixed recorded prefixes and declared accepted boundaries/reasons, not everystop ordatafault.','Recorded receipt time is a logical clock for deterministicvalues; Qt dispatch, CPU orGIL timing is not reconstructed.','Same originalWindows Python/NumPy/filter/processor implementation, alternative offline orchestration; not an independent newalgorithm.'],
        bindings=dict(manifest_sha256=sha(raw/'manifest.json'),plan_sha256=sha(HERE/'plan01.json'),review_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
