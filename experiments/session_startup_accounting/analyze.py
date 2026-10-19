"""Read completed passive-ledger windows; retain all failures and old quality gates."""
import hashlib,json,statistics,sys
from pathlib import Path
from delta import interval
from ledger import verify
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/session_gui_comparison'));from metrics import measure
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');archive=HERE/'runs/evidence01';manifest=read(archive/'manifest01.json');assert all(sha(archive/n)==v for n,v in manifest.items())
    assert all(sha(archive/n)==v for n,v in p['sources'].items())
    original=ROOT/'experiments/session_isolation_throughput/runs/recorded_source01.npz';assert sha(original)==p['input_sha256']['raw_frames.npz']
    stage=archive/'runs/cohort01';status=read(stage/'status.json');cases={}
    for case in p['cases']:
        folder=stage/case['id'];record=folder/'record.json'
        if not record.exists():cases[case['id']]=dict(not_attempted=True);continue
        r=read(record)
        if not r.get('complete') or r['errors'] or r['target_still_running']:cases[case['id']]=dict(failed=True,record=r);continue
        capture=folder/'capture';data=read(capture/'cpu_ledger.json');phases=read(capture/'phase_context.json');quality=verify(data,phases)
        m=measure(capture,original);actor=read(capture/'client/actor/result.json');work=read(capture/'workload_final.json');due=actor['source_clock_history'][1]['anchor_ns']+p['first_touch_offset_ns']
        before=[(v['end_ns']-v['begin_ns'])/1e6 for v in work['rows']['adapter_calls'] if v['end_ns']<=due]
        assert len(before)>=20
        median=statistics.median(before);state='slow' if median>=p['state_labels']['slow_base_adapter_ms_at_least'] else 'fast' if median<=p['state_labels']['fast_base_adapter_ms_at_most'] else 'intermediate'
        by={r['label']:r for r in data['rows']};accounts={name:interval(by[a],by[b]) for name,a,b in [('model_open','before_open','after_open'),('first_base_call','before_infer1','after_infer1'),('caller_before_first_through_100','before_infer1','after_infer100'),('caller_before_first_through_200','before_infer1','after_infer200'),('consumer_dense_to_mixed','consumer/59904','consumer/65904'),('model_dense_to_mixed','model/59904','model/65904'),('gui_dense_to_mixed','gui/59904','gui/65904')]}
        m.update(cpu_quality=quality,accounts=accounts,selected_original_calls=data['calls'],reader_initialization_ns=data['reader_initialization_ns'],precontact_base_adapter_ms_median=median,precontact_model_calls=len(before),exploratory_state=state,full_original_report_state_and_raw_exact=True)
        cases[case['id']]=m
    states={v['exploratory_state'] for v in cases.values() if 'exploratory_state' in v};complete=status['complete'] and not status['errors'] and all('accounts' in v for v in cases.values())
    result=dict(all_fixed_windows_complete=complete,cases=cases,both_states_observed=complete and {'slow','fast'}<=states,
        scope='Descriptive passive-accounting study of four new original sharedGUI saved-source windows; no intervention orzero-observer effect estimate.',
        actual_load_disturbance_pass=False,primary_root_identified=False,field_fix_verified=False,
        limits=['CPU account intervals include observer and all process concurrency; do not assign entire processCPU to the model.','Caller-threadCPU excludes native worker CPU; wall minus callerCPU is not GIL waiting.','Cycles are not actualGHz and threadCPU granularity is not per-call precision.','Operational state labels are exploratory proxies, not old stack/perturbation gates orroot causes.','Every attempted/failed/unattempted case retained, no replacement oroptional extension.'],bindings=dict(plan_sha256=sha(HERE/'plan01.json'),archive_sha256=sha(HERE/'evidence01.zip'),analyzer_sha256=sha(Path(__file__))))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(complete=complete,both_states=result['both_states_observed'],cases={n:{k:v.get(k) for k in ('exploratory_state','precontact_base_adapter_ms_median','scheduled_max_ms','failed','not_attempted')} for n,v in cases.items()}),indent=2))
