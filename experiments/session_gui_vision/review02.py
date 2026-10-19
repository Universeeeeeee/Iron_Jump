"""Offline independent raw/state/report and full-pipeline review; failures remain failures."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from verify_pipeline02 import verify_pipeline
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(value):
    value=copy.deepcopy(value)
    for item in (value['report_config_snapshot']['device'],value['report_config_snapshot']['beam_quality']['preflight']):del item['checked_monotonic_ns']
    return value

def values(stage):
    folder=stage/'client/actor';reference=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture'
    report=read(folder/'report.json');assert canonical(report)==canonical(read(reference/'report.json'))
    a=read(folder/'state.json');b=read(reference/'measurement.json')['state']
    for v in (a,b):del v['quality']['preflight']['checked_monotonic_ns']
    assert a==b
    with np.load(folder/'raw_frames.npz') as a,np.load(reference/'raw_frames.npz') as b:
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(a[key],b[key])
        count=len(a['sample_indices'])
    return dict(raw_frames_exact=count,full_original_report_and_state_exact=True)

if __name__=='__main__':
    roots={}
    for n in (1,2):
        root=HERE/f'runs/evidence{n:02d}';manifest=read(root/f'manifest{n:02d}.json')
        assert all(sha(root/name)==digest for name,digest in manifest.items())
        stage=root/('runs' if n==1 else 'runs02');roots[n]=(root,stage)
    old=roots[1][1];assert not read(old/'gui_result.json')['complete'] and not read(old/'finalization.json')['metadata_finalization_pass']
    assert (old/'pipeline_failure.json').exists() and not (old/'pipeline_review.json').exists()
    root,stage=roots[2];context=read(stage/'gui_context.json');gui=read(stage/'gui_result.json');work=read(stage/'workload_final.json')
    assert context['pid']==gui['pid'] and context['session_id']!=0 and context['priority_class']==16384 and context['qpa']=='windows'
    assert b'Traceback' not in (root/'task02.stderr').read_bytes()
    result=verify_pipeline(stage,work['anchors']);assert result==read(stage/'pipeline_review.json')
    result.update(original_failed_window_retained=True,failed_window_partial_values=values(old),successful_window_values=values(stage),
        actual_interactive_session=context['session_id'],parent_priority_class=context['priority_class'],
        active_publication_ids_painted=gui['painted_active_publications'],original_ground_paint_calls=gui['original_paint_calls'],actual_overlay_draws=gui['draws'],actual_sdk_work=gui['sdk'],
        confirmed_actor_packets=read(stage/'client/status.json')['confirmed_sequence'],
        original_application_return_still_unconfirmed=not read(stage/'finalization.json')['application_return_model_confirmed'],
        bindings=dict(plan02_sha256=sha(HERE/'plan02.json'),archive01_sha256=sha(HERE/'evidence01.zip'),archive02_sha256=sha(HERE/'evidence02.zip'),review_source_sha256=sha(Path(__file__))))
    with (HERE/'review02.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
