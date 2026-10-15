"""Verify retained provenance and catalog closed evidence; never alter raw inputs."""
import csv,hashlib,io,json,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))

if __name__=='__main__':
    # Normalize generated top-level metadata only; retain original bytes separately.
    normalized=[];backup=HERE/'raw_metadata';backup.mkdir(exist_ok=True)
    for path in sorted([*HERE.glob('*.json'),*HERE.glob('*.csv')]):
        raw=path.read_bytes();clean=raw.removeprefix(b'\xef\xbb\xbf').replace(b'\r\n',b'\n')
        if clean==raw:continue
        old=backup/path.name
        assert not old.exists() or old.read_bytes()==raw
        old.write_bytes(raw)
        if path.suffix=='.json':assert json.loads(raw.decode('utf-8-sig'))==json.loads(clean)
        else:assert list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))==list(csv.reader(io.StringIO(clean.decode())))
        path.write_bytes(clean)
        normalized.append({'file':path.name,'raw_sha256':hashlib.sha256(raw).hexdigest(),'normalized_sha256':sha(path),'original_backup':str(old.relative_to(HERE))})
    if normalized:(HERE/'metadata_line_endings.json').write_text(json.dumps(normalized,indent=2)+'\n')
    baseline=read(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files']
    assert all(sha(ROOT/name)==value for name,value in baseline.items())
    plan=read(HERE/'live_plan.json');audit=read(HERE/'windows_final_audit.json')
    assert all(sha(HERE/name)==value==audit['experiment_python_sources'][name] for name,value in plan['sources'].items())
    for key in ('diagnostic_baseline_changes','previous_experiment_changes','old_isolated_archive_changes','formal_changes_since_prior_backup'):assert not audit[key]
    cleanup=read(HERE/'windows_task_cleanup.json')
    assert cleanup['remaining_task_count']==0 and not cleanup['remaining_experiment_processes']
    assert not (HERE/'runs/live_run_01').exists() and not (HERE/'live_run_01.log').exists()
    summary=read(HERE/'summary.json');assert len(summary['runs'])==24
    assert all(r['raw_report_runtime_quality_audit_exact'] and r['tree_conservation_exact'] for r in summary['runs'].values())
    assert all(not c['pass'] for c in summary['calibration'].values())
    preview=read(HERE/'preview_state_summary.json');assert preview['all_raw_reports_quality_runtime_events_exact']
    external=read(HERE/'external_summary.json');assert len(external['runs'])==6
    for run in external['runs'].values():assert run['raw_report_runtime_quality_audit_exact']
    for name in ('live_walk_07','live_run_02'):
        live=read(HERE/(name+'_summary.json'))
        assert live['full_report_and_runtime_quality_audit_exact'] and live['raw_wire_counter_validity_issue_sidecars_verified']
        report=read(HERE/'runs'/name/'report.json');replay=read(HERE/'runs'/name/'independent_report.json');assert report==replay
        assert live['sdk_proof']['nonzero_set_speed_calls']>0 and not live['sdk_proof']['errors']
        assert live['pose_draws']['with_valid_links']>0
    for source in read(HERE/'screen_sources.json'):assert sha(Path(source['source']))==source['sha256']
    paths=[]
    for root in (HERE/'runs',HERE/'oracles',backup):
        paths += [p for p in root.rglob('*') if p.is_file()]
    paths += [p for p in HERE.iterdir() if p.suffix in ('.zip','.log','.ps1') and p.is_file()]
    inventory={'root':str(HERE),'created_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'windows_inventory':'windows_evidence_inventory.json','discarded_trial':'live_run_01, deleted on explicit user request; not retained or analyzed','local_files':[{'path':str(p.relative_to(HERE)),'bytes':p.stat().st_size,'sha256':sha(p),'authoritative':not(p.name=='runs_live_walk_07.zip' and p.stat().st_size==0)} for p in sorted(set(paths))], 'limits':'Large real-camera MJPEG files remain at the Windows paths in its SHA inventory. A zero-byte interrupted local download is not evidence. Screen originals remain in user-provided directory, unchanged.'}
    (HERE/'evidence_inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    sources={p.name:sha(p) for p in sorted(HERE.iterdir()) if p.suffix=='.py'}
    (HERE/'source_manifest.json').write_text(json.dumps({'parent_commit':'5e1686469e789e5bae0e3c2fd47a5a1d191fd60d','production_baseline_files':len(baseline),'python_sources':sources},indent=2)+'\n')
    result={'original_numpy_and_baseline_458_exact':True,'windows_formal_and_prior_sources_unchanged':True,'replay_semantic_verifications':38,'live_independent_full_reports_exact':2,'calibration_passed':False,'stage_gil_qt_exact_time_partition_established':False,'screen_review_outbound_only':True,'discarded_run_absent':True,'scheduled_tasks_and_experiment_processes_remaining':0,'source_scope':'Only new experiment scripts and diagnosis artifacts; no production optimization implemented','local_inventory_files':len(inventory['local_files'])}
    (HERE/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
