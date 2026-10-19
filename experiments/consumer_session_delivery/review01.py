"""Offline independent comparison against retained realGUI baseline, not live timings."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(report):
    result=copy.deepcopy(report)
    for v in (result['report_config_snapshot']['device'],result['report_config_snapshot']['beam_quality']['preflight']):del v['checked_monotonic_ns']
    return result

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items())
    actor=raw/'runs/actor';reference=ROOT/'experiments/gui_qos_candidate/runs/evidence01/runs/gui02/pair01_default/capture'
    status=read(raw/'runs/status.json');state=read(actor/'result.json')
    assert status['complete'] and not status['actor_still_alive'] and status['actor_exitcode']==0
    assert state['complete'] and state['reader_stopped'] and state['qt_thread_stopped'] and state['controller_released'] and state['application_class']=='QCoreApplication'
    with np.load(actor/'raw_frames.npz') as a,np.load(reference/'raw_frames.npz') as b:
        for key in ('sample_indices','frame_indices','bits','wire','valid_bits','dropped_frames_before'):assert np.array_equal(a[key],b[key]),key
        count=len(a['sample_indices']);assert np.all(np.diff(a['received_ns'])>=0)
    assert canonical(read(actor/'report.json'))==canonical(read(reference/'report.json'))
    a=read(actor/'state.json');b=read(reference/'measurement.json')['state']
    for value in (a,b):del value['quality']['preflight']['checked_monotonic_ns']
    assert a==b
    encoding=read(HERE/'post_encoding01.json')['preferred_encoding']
    assert encoding=='cp936' and read(HERE/'post_encoding01.json')['utf8_mode']==0
    rows=[json.loads(s) for s in (raw/'runs/messages.jsonl').read_text(encoding=encoding).splitlines()]
    assert [r['sequence'] for r in rows]==list(range(1,len(rows)+1)) and all(r['pid']==status['actor_pid'] for r in rows)
    assert status['parent_pid']!=status['actor_pid'] and len(rows)==status['messages']
    reports=[r['payload']['report'] for r in rows if r['kind']=='report_value'];assert reports==[read(actor/'report.json')]
    kinds=[r['kind'] for r in rows]
    assert kinds.index('ready_to_start')<kinds.index('started')<kinds.index('drained_eof')<kinds.index('report_value')<kinds.index('terminal')
    result=dict(core_session_delivery_pass=True,complete_original_report_and_state_match=True,raw_frames_exact=count,ordered_actual_output_messages=len(rows),separate_pid=True,actual_qt_thread_and_reader_stop=True,
        supported_commands=['prepare','start'],stop_path='Existing sourceEOF -> childdrain -> originalcontroller.stop(manual). Parent-requested earlystop not implemented.',
        observed_output_kinds={k:kinds.count(k) for k in sorted(set(kinds))},log_encoding=encoding,performance_qualification=False,full_gui_proxy_qualification=False,field_fix_verified=False,
        missing=['Parent-commanded earlystop, pause/resume/discard and their fault paths.','RemainingGUI signals including device notices, quality notices, step events and layout changes.','RealGUI/vision/SDK load, bounded output buffering and1000Hz pending/contact-to-paint performance.'],
        bindings=dict(manifest_sha256=sha(raw/'manifest.json'),reference_report_sha256=sha(reference/'report.json'),reference_measurement_sha256=sha(reference/'measurement.json'),review_source_sha256=sha(Path(__file__))))
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
