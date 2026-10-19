"""Recheck one original GUI's current call identities, never historical owners."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import numpy as np
from identity_hook import verify

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan02.json');data=read(HERE/'call_identity01.json');meta=read(HERE/'transport01.json')
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    formal=read(ROOT/p['formal_baseline_manifest'])['baseline_files']
    qualification=verify(data,p['native_entry'],formal)
    assert p['process_budget']==1 and len(p['cases'])==1 and not p['performance_AB']
    archive=HERE/'runs/evidence01.zip';assert sha(archive)==meta['sha256']
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('manifest01.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in manifest['files'].items())
        assert len(manifest['files'])==meta['manifest_files'] and all(n+'/' in z.namelist() for n in manifest['locks'])
        assert all(manifest['files'][n]==v for n,v in p['sources'].items())
        capture='runs/cohort01/identity01/capture/'
        assert json.loads(z.read(capture+'call_identity.json'))==data
        actor=json.loads(z.read(capture+'client/actor/result.json'));report=json.loads(z.read(capture+'client/actor/report.json'))
        assert actor['complete'] and actor['reader_stopped'] and actor['qt_thread_stopped'] and actor['controller_released']
        arm=actor['armed'][0];assert len(actor['armed'])==1
        with np.load(io.BytesIO(z.read(capture+'client/actor/raw_frames.npz'))) as raw:
            mask=raw['valid_bits'].astype(bool);bad=report['report_config_snapshot']['beam_quality']['preflight']['bad_indices'];mask[:,bad]=False
            active=(raw['sample_indices']>p['checked_sample']) & np.any(raw['bits'].astype(bool)&mask,axis=1)
            i=int(np.flatnonzero(active)[0]);first_activity=dict(sample=int(raw['sample_indices'][i]),received_ns=int(raw['received_ns'][i]),bad_indices_excluded=bad)
    gui=read(HERE/'gui_result01.json');pipeline=read(HERE/'pipeline_review01.json');record=read(HERE/'record01.json')
    assert gui['complete'] and gui['no_physical_camera_capture'] and pipeline['original_same_process_gui_delivery_pass']
    assert pipeline['final_model_cleanup_confirmed'] and pipeline['label_call_identity']['call_identity_pass']
    assert record['complete'] and record['target_returncode']==0 and not record['target_still_running']
    process=read(HERE/'task_status01.json');assert process['confirmed_exit'] and process['observation_complete'] and process['native_exit_code']==process['managed_exit_code']==0
    assert all(record['semantics'][k] for k in ('full_original_report','full_quality_runtime_state','raw_fields_exact'))
    rows=[]
    for row in data['rows']:
        assert row['tid']==pipeline['thread_ids']['gui'] and row['caller_self_is_receiver']
        assert row['receiver_type']=='ui.annotation_canvas.AnnotationCanvas'
        assert any(v['type']=='ui.embedded_camera_panel.EmbeddedCameraPanel' and v['preview_member_is_receiver'] for v in row['parents'])
        interval=[(n-arm)/1e9 for n in row['pre_native_observation_bracket_ns']]
        assert row['pre_native_observation_bracket_ns'][1] < first_activity['received_ns']
        rows.append(dict(receiver_type=row['receiver_type'],caller=row['caller'],entry_rva=row['entry_rva'],
            preview_owner_directly_matched=True,pixmap=row['pixmap'],widget=row['widget'],live_pose_present=row['live_pose_present'],
            observation_relative_arm_s=interval,before_first_nonbad_valid_beam_activity=True))
    result=dict(call_identity_pass=qualification['call_identity_pass'],gui_pid=record['target_pid'],sdk_fake_pid=pipeline['sdk_pid'],
        same_observed_preview_instance=len({r['receiver_cpp_pointer'] for r in data['rows']})==1,rows=rows,
        first_nonbad_valid_beam_activity=first_activity,full_original_semantics=record['semantics'],
        model_cleanup_at_original_return=pipeline['original_return_model_confirmed'],model_cleanup_after_tail=pipeline['final_model_cleanup_confirmed'],
        limits=['Three early image calls in this new saved-workload window are directly identified; not all calls/widgets over the whole window.',
            'DPR1 pixmap versus DPR1.25 widget is observed metadata, not a measured resampling job or CPU/GIL cost.',
            'The profiling callback perturbs the GUI before the native call. Its partial observation bracket is not native paint time or complete observer cost.',
            'No historical field receiver, GIL owner, same-backlog pending/batch witness or dominant root contribution is recovered.',
            'The experiment never installs the GIL-boundary bridge; no optimization/performance A/B or observer-equivalence qualification follows.'],
        performance_qualification=False,actual_load_disturbance_pass=False,field_historical_receiver_identified=False,root_cause_or_fix_complete=False,
        bindings={f.name:sha(f) for f in (Path(__file__),HERE/'plan02.json',HERE/'call_identity01.json',HERE/'record01.json',HERE/'gui_result01.json',
            HERE/'pipeline_review01.json',HERE/'task_status01.json',HERE/'transport01.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
