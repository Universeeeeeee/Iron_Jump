"""Independent raw latency/delivery checks, then retain the frozen decision."""
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');result=read(HERE/'result01.json');meta=read(HERE/'transport01.json')
    archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json')
    assert sha(HERE/'runs/evidence01.zip')==meta['sha256']
    assert all(sha(archive/n)==v for n,v in manifest['files'].items())
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    rows=[];severe=[];late_failed=[]
    original=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz'
    with np.load(original) as z:original_ids=z['sample_indices'].copy();original_receipts=z['received_ns'].copy()
    for case in p['cases']:
        path=archive/'runs/cohort01'/case['id']/'capture';a=read(path/'client/actor/result.json');g=read(path/'gui_result.json')
        report=read(path/'client/actor/report.json');measured=result['cases'][case['id']];boundary=read(path/'boundary.json')
        assert boundary['mode']==case['boundary'] and boundary['original_method_is_installed']==(case['boundary']=='original')
        assert boundary['restored'] and boundary['installed_intact'] and not boundary['per_paint_safety_wrapper']
        checked=report['report_config_snapshot']['device']['checked_sample_index']
        with np.load(path/'client/actor/raw_frames.npz') as z:ids=z['sample_indices'].copy();receipts=z['received_ns'].copy()
        selection=np.searchsorted(original_ids,ids);assert np.array_equal(original_ids[selection],ids)
        source=original_receipts[selection];epochs=a['source_clock_history'];assert len(epochs)==2
        due=np.array([int(epochs[1 if int(n)>checked else 0]['anchor_ns'])+int(t)-int(source[0]) for n,t in zip(ids,source)],dtype=np.int64)
        lateness=float(np.max(receipts[ids>checked]-due[ids>checked])/1e6)
        assert abs(lateness-measured['input_lateness_ms'])<1e-9
        contacts=[]
        for event in report['walking_summary']['event_publications']:
            if not event['active']:continue
            i=int(np.searchsorted(ids,event['touch_sample']));assert int(ids[i])==event['touch_sample']
            contacts.append((g['paint_first_ns'][str(event['contact_id'])]-int(due[i]))/1e6)
        latency=max(contacts);assert abs(latency-measured['scheduled_max_ms'])<1e-9
        observed=max(int(v[3]) for v in a['queue_common']);assert observed==measured['observed_queue_lower']
        is_severe=case['boundary']=='original' and observed>=1000 and latency>=1000
        if is_severe:severe.append(case['id'])
        if lateness>100:late_failed.append(case['id'])
        rows.append(dict(id=case['id'],mode=case['boundary'],observed_deque_lower=observed,queue_upper=measured['queue_upper'],
            independently_recomputed_scheduled_latency_ms=latency,independently_recomputed_input_lateness_ms=lateness))
    assert len(rows)==8 and result['cohort_complete'] and not result['cohort_errors']
    assert not result['decision']['advance'] and not result['decision']['severe_baseline_reproduced']
    assert len(severe)==1 and len(late_failed)==2 and not result['decision']['protocol_quality_pass']
    output=dict(all_eight_complete=True,raw_endpoints_independently_match=True,cases=rows,severe_original_windows=severe,
        input_lateness_failed_windows=late_failed,decision_failures=['input_lateness_exceeded_100ms','severe_baseline_only_1_of_4','first_bridge_remained_severely_backlogged'],
        conclusion='Cannot validate stable severe-backlog benefit. Candidate remains severely delayed in the first pair; later fast windows are not substitute evidence.',
        repeat_or_replacement_permitted=False,formal_fix_verified=False,
        bindings=dict(result_sha256=sha(HERE/'result01.json'),plan_sha256=sha(HERE/'plan01.json'),verifier_sha256=sha(Path(__file__))))
    with (HERE/'verification01.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output,indent=2))
