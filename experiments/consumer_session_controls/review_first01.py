"""Recover facts from untouched first-window artifacts, without repairing its status."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(value):
    value=copy.deepcopy(value)
    for item in (value['report_config_snapshot']['device'],value['report_config_snapshot']['beam_quality']['preflight']):del item['checked_monotonic_ns']
    return value

if __name__=='__main__':
    raw=HERE/'runs/evidence01';m=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in m.items())
    case=raw/'runs/full_with_unsupported_pause';actor=case/'actor';reference=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture'
    assert not read(raw/'runs/status.json')['complete']
    try:read(case/'status.json')
    except json.JSONDecodeError:truncated=True
    else:raise AssertionError('Expected original incomplete status bytes')
    result=read(actor/'result.json');assert result['complete'] and not result['errors'] and result['reader_stopped'] and result['qt_thread_stopped'] and result['controller_released']
    assert canonical(read(actor/'report.json'))==canonical(read(reference/'report.json'))
    a=read(actor/'state.json');b=read(reference/'measurement.json')['state']
    for value in (a,b):del value['quality']['preflight']['checked_monotonic_ns']
    assert a==b
    with np.load(actor/'raw_frames.npz') as a,np.load(reference/'raw_frames.npz') as b:
        for k in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(a[k],b[k])
        frames=len(a['sample_indices'])
    messages=[json.loads(v) for v in (case/'messages.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [v['sequence'] for v in messages]==list(range(1,len(messages)+1)) and all(v['pid']==result['pid'] for v in messages)
    rejections=[v['payload'] for v in messages if v['kind']=='command_rejected']
    assert [v['kind'] for v in rejections]==['pause','resume'] and all(v['status']=='unsupported' and not v['applied'] for v in rejections)
    completed=[v['payload'] for v in messages if v['kind']=='command_completed'];assert len(completed)==1 and completed[0]['kind']=='stop' and completed[0]['command_sequence']==5
    assert completed[0]['reader_stopped'] and completed[0]['qt_thread_stopped']
    reports=[v['payload']['report'] for v in messages if v['kind']=='report_value'];assert reports==[read(actor/'report.json')]
    notes=[v['payload']['signal'] for v in messages if v['kind']=='notification']
    derived=dict(cohort_gate_remains_failed=True,original_truncated_status_preserved=True,independent_first_core_semantics_pass=True,raw_frames_exact=frames,
        walk_pause_resume_explicitly_unsupported=True,parent_stop_after_actual_resource_stop=True,received_notification_signals=sorted(set(notes)),
        output_messages=len(messages),second_and_third_not_attempted=True,performance_qualification=False,
        bindings=dict(manifest_sha256=sha(raw/'manifest.json'),truncated_status_sha256=sha(case/'status.json'),reference_report_sha256=sha(reference/'report.json'),review_source_sha256=sha(Path(__file__))))
    with (HERE/'first_review01.json').open('x') as f:json.dump(derived,f,indent=2)
    print(json.dumps(derived,indent=2))
