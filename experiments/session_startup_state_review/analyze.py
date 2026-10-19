"""Offline first-call/prefix and independent fixed-work CPU-accounting review."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def prefix(a,b):
    n=0
    for x,y in zip(a,b):
        if x!=y:break
        n+=1
    return n

def startup(folder):
    work=read(folder/'workload_final.json');actor=read(folder/'client/actor/result.json')
    boundary=load('retained_model_boundaries',ROOT/'experiments/session_gui_comparison/boundary_review.py');joined=boundary.join(work)
    inference=work['rows']['inferences'];opening=work['rows']['model_open'];assert len(opening)==1 and opening[0]['is_open'] and opening[0]['error'] is None
    begin=inference[0]['record']['inference_start_s']*1e9;assert opening[0]['end_ns']<=begin
    first=inference[0]['record'];metadata=first['metadata'];arm=actor['armed'][0];assert len(actor['armed'])==1
    phases=[]
    for second in range(0,35,5):
        lo=arm+second*10**9;hi=lo+5*10**9
        select=[j for j,r in zip(joined,inference) if lo<=r['record']['inference_start_s']*1e9 and r['record']['inference_end_s']*1e9<=hi]
        phases.append(dict(after_arm_seconds=[second,second+5],fully_contained_calls=len(select),medians_ms={k:statistics.median(v[k] for v in select) if select else None for k in ('whole_ms','base_adapter_ms','outer_shell_ms')}))
    return dict(open_wall_ms=(opening[0]['end_ns']-opening[0]['begin_ns'])/1e6,open_end_to_first_inference_ms=(begin-opening[0]['end_ns'])/1e6,first_inference_minus_arm_ms=(begin-arm)/1e6,
        first_input_identity=dict(frame_index=metadata['frame_index'],media_sample_time_s=metadata['sample_time_s'],camera_epoch=metadata['camera_clock_epoch'],sync_status=metadata['clock_sync_status'],shape=[360,640,3],dtype='uint8'),
        first_call=joined[0],fully_contained_model_time_bins=phases,all_calls=len(joined),excluded_from_five_second_bins=len(joined)-sum(v['fully_contained_calls'] for v in phases)),joined,inference

if __name__=='__main__':
    plan=read(HERE/'plan01.json');assert all(sha(ROOT/n)==v for n,v in plan['bindings'].items())
    current=ROOT/'experiments/session_gui_comparison/runs/evidence01';old=ROOT/'experiments/fixed_overlap_comparison/runs/evidence01'
    for archive,name in ((current,'manifest01.json'),(old,'manifest.json')):
        manifest=read(archive/name);assert all(sha(archive/n)==v for n,v in manifest.items())
    startup_cases={};records={};inferences={}
    for name in ('aa01','aa02','aa03','aa04'):
        summary,records[name],inferences[name]=startup(current/'runs/cohort01'/name/'capture');startup_cases[name]=summary
    identities=[v['first_input_identity'] for v in startup_cases.values()];assert all(v==identities[0] for v in identities)
    common={}
    for name in ('aa02','aa03','aa04'):
        count=prefix([v['frame_index'] for v in records['aa01']],[v['frame_index'] for v in records[name]])
        pairs=[]
        for a,b,ra,rb in zip(records['aa01'][:count],records[name][:count],inferences['aa01'][:count],inferences[name][:count]):
            ma,mb=ra['record']['metadata'],rb['record']['metadata'];assert ma['sample_time_s']==mb['sample_time_s'] and ma['camera_clock_epoch']==mb['camera_clock_epoch']
            pairs.append(dict(frame_index=a['frame_index'],first_window=a,comparison_window=b,relative_video_timestamp_difference_ms=(a['timestamp_ms']-records['aa01'][0]['timestamp_ms'])-(b['timestamp_ms']-records[name][0]['timestamp_ms'])))
        common[name]=dict(identical_frame_id_prefix=count,pairs=pairs,exact_timestamp_history_equal=all(v['relative_video_timestamp_difference_ms']==0 for v in pairs),scope='Same frame identifiers/recorded media times, not proof of identical native internal execution or observed pixel hashes.')
    original_plan=read(old/'plan01.json');reference=read(old/'reference01.json')
    verifier=load('original_fixed_overlap_verify',ROOT/'experiments/fixed_overlap_comparison/verify.py');counter=load('original_fixed_cpu_counter',ROOT/'experiments/fixed_work_accounting/counters.py')
    fixed={}
    for name in original_plan['cases']:
        r=read(old/'runs'/name/'result.json');assert verifier.check(original_plan,r)['pass_all']
        assert r['frame_evidence']==reference['frame_evidence'] and r['model_result_sha256']==reference['model_result_sha256'] and r['report_sha256']==reference['report_sha256']
        account=counter.validate(r);assert account==r['process_accounting'] and account['accounting_pass']
        c,m=r['consumer'],r['model']
        fixed[name]=dict(variant=r['variant'],full_fixed_input_and_returns_exact=True,model_calls=len(m['calls']),consumer_frames=c['frames'],consumer_wall_ms=(c['end_ns']-c['begin_ns'])/1e6,consumer_thread_cpu_ms=c['thread_cpu_ns']/1e6,
            model_wall_ms=(m['end_ns']-m['begin_ns'])/1e6,model_caller_thread_cpu_ms=m['thread_cpu_ns']/1e6,process_cpu_ms=account['process_cpu_ns']/1e6,process_cycles=account['process_cycles'],actual_concurrent=verifier.check(original_plan,r)['actual_overlap'])
    output=dict(scope='Posthoc existing-record review only. CurrentGUI four A/A windows and independent historical eight fixed-work windows are not pooled as one trial.',startup=startup_cases,common_prefixes=common,historical_fixed_work=fixed,
        findings=['First external model-call input identifiers match before subsequent frame histories diverge; aa01 is already slower at that first call.','Model open is also slower and is complete more than3seconds before first inference in all four windows. Ready is not an execution-performance guarantee.','Historical serial windows execute the same220 model inputs, logical timestamps and complete returned-value hashes after consumer work ends; their model caller-thread CPU and whole-process CPU also differ between early and later windows.','Model caller-thread CPU is not all model CPU: native worker pools are included in whole-process accounting, not in the one caller thread. Wall minus caller CPU is not GIL waiting.'],
        limits=['These wall/CPU/cycle counters do not give instruction counts, actualGHz, thermal causes or exclusive CPU/GIL/Qt contribution shares.','GUI model histories are not timestamp-identical and native tracking/detection work is not proven identical.','Five-second bins omit straddling calls only from bin summaries; all records and cases remain, with excluded counts explicit.','Historical accounting is a separate workload/cohort; no cross-cohort effect percentage is estimated.','Old observer3%/1%, native-stack and active probe failures remain unchanged. No added test window orformal change.'],new_capture=False,primary_root_identified=False,field_fix_verified=False,bindings=plan['bindings'])
    with (HERE/'result01.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(dict(first_calls={n:dict(open_ms=v['open_wall_ms'],arm_to_first_ms=v['first_inference_minus_arm_ms'],first=v['first_call']) for n,v in startup_cases.items()},prefix_lengths={n:v['identical_frame_id_prefix'] for n,v in common.items()},serial_cpu={n:v for n,v in fixed.items() if v['variant']=='serial'}),indent=2))
