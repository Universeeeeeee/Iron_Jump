"""Observer perturbation on a saved synchronous contact chain; not field readiness."""
import json
from pathlib import Path
import sys


def protocol(rows,pid,tid,count):
    samples=[s for s in rows if s.get('kind')=='sample']
    if not rows or len(rows)!=count+2 or len(samples)!=count:return False
    first,last=rows[0],rows[-1]
    valid=first.get('kind')=='init' and first.get('schema')==4 and first.get('error') is None and first.get('synthetic_probe_enabled') is False and first.get('pid')==pid and last.get('kind')=='complete' and last.get('pid')==pid and last.get('samples_written')==count
    previous=first['qpc_end']
    for i,s in enumerate(samples):
        ts=s['traces'];native=s['native'];owners=[t for t in ts if t['owns_gil']]
        valid &= s['ordinal']==i and s['pid']==pid and previous<=s['qpc_begin']<=s['suspended_qpc']<=s['resume_returned_qpc']<=s['qpc_end']<=s['resolve_begin_qpc']<=s['resolve_end_qpc'] and s['oracle_reads']==[None]*4 and s['activity_flags_valid'] is False and all(t['pid']==pid for t in ts) and len(owners)<=1 and tid in {n['tid'] for n in native} and len({n['tid'] for n in native})==len(native) and all(n['frames'] and n['context_ip']==n['frames'][0]['address'] and n['context_ip']>0 and 'frame cap' not in n['stopped_by'] for n in native)
        previous=s['resolve_end_qpc']
    return bool(valid and first['activity_flags_valid'] is False and previous<=last['qpc'])


def case_result(record,roi,complete,rows,plan,root):
    sys.path.insert(0,str(root/'experiments/native_stack_capture'));from align_clock import mapping
    a,b=record['before'][0],record['after'][0]
    clock=mapping(record['anchors']+[x[k] for x in (a,b) for k in ('start','end')]);f=clock['qpc_frequency'];lo,hi=clock['host_ns_offset_lower'],clock['host_ns_offset_upper']
    before_late=(a['end']['qpc_after']*10**9+f-1)//f+hi;after_early=b['start']['qpc_before']*10**9//f+lo
    cpu=(b['user_100ns']+b['kernel_100ns']-a['user_100ns']-a['kernel_100ns'])*100
    stream=True if record['mode']=='off' else protocol(rows,record['ready']['pid'],record['ready']['tid'],plan['count'])
    selected=[s for s in rows if s.get('kind')=='sample'];brackets=[[s['qpc_begin']*10**9//f+lo,(s['qpc_end']*10**9+f-1)//f+hi] for s in selected]
    overlaps=sum(roi['wall_begin_ns']<=x<=y<=roi['wall_end_ns'] for x,y in brackets)
    checks=dict(clean=record['target_returncode']==0 and not record['errors'] and not record['target_still_running'] and not record['observer_still_running'] and (record['mode']=='off' or record['observer_returncode']==0),semantic_exact=all(complete[k] for k in ('full_report_exact','quality_runtime_exact','event_audit_exact','timeline_exact','mirror_exact','raw_archive_exact','inputs_unchanged','all_458_sources_unchanged')) and complete['report_canonical_sha256']==plan['report_canonical_sha256'],identity=a['active'] and b['active'] and (a['pid'],a['tid'],a['creation_100ns'])==(b['pid'],b['tid'],b['creation_100ns']) and a['pid']==record['ready']['pid'] and a['tid']==record['ready']['tid'],clock=clock['uncertainty_ns']<=plan['clock_uncertainty_ns_max'],counter_brackets=before_late<=roi['wall_begin_ns']<roi['wall_end_ns']<=after_early,cpu_cycles=cpu>=0 and b['cycles']>a['cycles'] and 0<=cpu-roi['thread_cpu_ns']<=plan['cpu_crosscheck_tolerance_ns'],fixed_input=roi['raw_first']==plan['raw_first'] and roi['raw_after_last']==plan['raw_after_last'] and roi['frames']==plan['raw_after_last']-plan['raw_first'],stream=stream,load_overlap=record['mode']=='off' or overlaps>=plan['minimum_samples_in_roi'])
    return dict(mode=record['mode'],checks=checks,case_pass=all(checks.values()),wall_ns=roi['wall_ns'],thread_cpu_ns=roi['thread_cpu_ns'],os_cpu_span_ns=cpu,cycles=b['cycles']-a['cycles'],clock=clock,samples_fully_inside_roi=overlaps,read_brackets_host_ns=brackets,blocks=roi['blocks'],report_canonical_sha256=complete['report_canonical_sha256'],actual_load_disturbance_pass=False)


def pair_result(off,on,plan):
    changes={k:on[k]/off[k]-1 for k in ('wall_ns','thread_cpu_ns','cycles')}
    block_changes=[dict(raw_first=a['raw_first'],wall_change=b['wall_ns']/a['wall_ns']-1) for a,b in zip(off['blocks'],on['blocks'])]
    passed=off['case_pass'] and on['case_pass'] and all(abs(v)<=plan['relative_limit'] for v in changes.values()) and len(block_changes)==len(off['blocks'])==len(on['blocks']) and all(abs(b['wall_change'])<=plan['relative_limit'] for b in block_changes)
    return dict(relative_changes=changes,block_changes=block_changes,offline_contact_chain_pair_pass=bool(passed),actual_load_disturbance_pass=False)
