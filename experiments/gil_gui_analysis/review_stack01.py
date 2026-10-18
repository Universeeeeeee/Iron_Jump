"""Individual coherent GIL mechanism evidence; never time shares or failed-gate repair."""
import argparse
from bisect import bisect_left,bisect_right
import json
from pathlib import Path,PureWindowsPath
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
from align_clock import mapping
from review_aa01 import read,sha
from temporal_review01 import validate_queue
import numpy as np


def native_check(n,modules,addresses):
    names=[addresses.get(f['address'],{}).get('symbol') for f in n['frames']]
    raw=bool(n['frames']) and n['context_ip']==n['frames'][0]['address'] and 'frame cap' not in n['stopped_by']
    raw=raw and all(f['module_base'] in modules and f['module_offset']==f['address']-f['module_base'] and 0<=f['module_offset']<modules[f['module_base']]['image_size'] for f in n['frames'])
    roots=raw and len(names)>=2 and names[-2:]==['BaseThreadInitThunk','RtlUserThreadStart']
    roots=roots and all(addresses.get(f['address'],{}).get('pdb_matched') for f in n['frames'][-2:])
    roots=roots and [PureWindowsPath(modules[f['module_base']]['path']).name.lower() for f in n['frames'][-2:]]==['kernel32.dll','ntdll.dll']
    def matched(name):return any(a.get('symbol')==name and a['pdb_matched'] for f in n['frames'] for a in [addresses.get(f['address'],{})])
    return dict(raw_valid=bool(raw),roots_closed=bool(roots),matched_take_gil=matched('take_gil'),matched_entry=matched('PyEval_RestoreThread') or matched('PyGILState_Ensure'),matched_wait=matched('NtWaitForSingleObject'),functions=[n for n in names if n])


def same_lifetime(tid,pid,before,after):
    a=before.get((pid,tid));b=after.get((pid,tid))
    return bool(a and b and a['active'] and b['active'] and a['creation_100ns']==b['creation_100ns'] and all(b[k]>=a[k] for k in ('cycles','user_100ns','kernel_100ns')))


def main(a):
    manifest=read(a.raw/'manifest.json');assert all(sha(a.raw/n)==h for n,h in manifest.items())
    base=a.raw/'experiments/gil_gui_analysis';plan=read(base/'stack_plan01.json');stage=base/'runs/stack01';record=read(stage/'record01.json');m=read(stage/'capture/measurement.json')
    assert record['plan_sha256']==sha(base/'stack_plan01.json') and all(sha(a.raw/n)==h for n,h in plan['frozen_sources'].items())
    symbols=read(stage/'symbols01.json');assert symbols['samples_sha256']==sha(stage/'samples.jsonl') and symbols['resolver_sha256']==sha(base/'resolve_fixed01.py') and symbols['dbghelp_sha256']==plan['dbghelp_sha256']
    modules={x['base']:x for x in symbols['modules']};addresses={x['address']:x for v in modules.values() for x in v['resolved']}
    for mod in modules.values():
        if mod['pdb_matched']:
            assert not mod['pdb_unmatched'] and any(cv['guid']==mod['pdb_identity']['guid']==mod['loaded_guid'] and cv['age']==mod['pdb_identity']['age']==mod['loaded_age'] for cv in mod['codeview'])
        assert all((x['symbol'] is None or x['pdb_matched']) and x['module_offset']==x['address']-mod['base'] for x in mod['resolved'])
    clock=mapping(record['anchors']+[x[k] for group in ('before','after') for x in record[group] for k in ('start','end')]);f=clock['qpc_frequency'];lo=clock['host_ns_offset_lower'];hi=clock['host_ns_offset_upper']
    before={(x['pid'],x['tid']):x for x in record['before']};after={(x['pid'],x['tid']):x for x in record['after']}
    with np.load(stage/'capture/raw_frames.npz') as raw:received={int(n):int(t) for n,t in zip(raw['sample_indices'],raw['received_ns'])}
    validation=validate_queue(m,received)
    rows=[json.loads(s) for s in (stage/'samples.jsonl').read_text().splitlines()];samples=[s for s in rows if s['kind']=='sample'];assert len(rows)==len(samples)+2 and rows[0]['kind']=='init' and rows[-1]['kind']=='complete' and rows[-1]['samples_written']==len(samples)==plan['count']
    assert rows[0]['requested_tid']==record['armed']['tids']['consumer'] and rows[0]['requested_count']==plan['count'] and rows[0]['period_ms']==plan['period_ms'] and rows[0]['schema']==4 and rows[0]['error'] is None
    wanted=record['armed']['tids']['consumer'];q=m['queue_samples'];times=[r[0] for r in q];prior=rows[0]['qpc_end'];out=[];read_cost=[];gaps=[]
    for i,s in enumerate(samples):
        assert s['ordinal']==i and s['pid']==record['target_pid'] and prior<=s['qpc_begin']<=s['suspended_qpc']<=s['resume_returned_qpc']<=s['qpc_end']<=s['resolve_begin_qpc']<=s['resolve_end_qpc']
        assert not s['activity_flags_valid'] and s['oracle_reads']==[None]*4;prior=s['resolve_end_qpc']
        if i:gaps.append((s['qpc_begin']-samples[i-1]['qpc_begin'])*1000/f)
        read_cost.append((s['qpc_end']-s['qpc_begin'])*1e6/f)
        left=s['qpc_begin']*10**9//f+lo;right=(s['qpc_end']*10**9+f-1)//f+hi
        owners=[t for t in s['traces'] if t['owns_gil']];assert len(owners)<=1 and all(t['pid']==s['pid'] for t in s['traces'])
        native={n['tid']:n for n in s['native']};assert len(native)==len(s['native']) and wanted in native
        consumer=native_check(native[wanted],modules,addresses);owner=owners[0] if owners else None;owner_tid=None if owner is None else owner['os_thread_id']
        owner_native=None if owner_tid not in native else native_check(native[owner_tid],modules,addresses)
        stable_owner=owner_tid is not None and same_lifetime(owner_tid,s['pid'],before,after);stable_consumer=same_lifetime(wanted,s['pid'],before,after)
        project=[]
        for frame in [] if owner is None else owner['frames']:
            try:rel=PureWindowsPath(frame['filename']).relative_to(PureWindowsPath('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01')).as_posix()
            except ValueError:continue
            expected=plan['baseline_files'].get(rel,plan['frozen_sources'].get(rel))
            project.append(dict(file=rel,function=frame['name'],line=frame['line'],source_hash_matched=expected is not None and sha(ROOT/rel)==expected,production=rel in plan['baseline_files']))
        pre_i=bisect_right(times,left)-1;post_i=bisect_left(times,right);join=None
        if pre_i>=0 and post_i<len(q):
            pre,post=q[pre_i],q[post_i];lower=pre[5]-post[1]-20
            same_batch=pre[9]==post[9]=='batch' and pre[10:13]==post[10:13] and pre[12]==20
            join=dict(pre=pre,post=post,pending_lower_bound=lower,same_inflight20_batch=same_batch)
        closed_pair=bool(owner is not None and owner_tid!=wanted and owner_native and consumer['roots_closed'] and owner_native['roots_closed'] and stable_owner and stable_consumer and consumer['matched_take_gil'] and consumer['matched_entry'] and consumer['matched_wait'])
        backlog_join=bool(join and join['pending_lower_bound']>=100 and join['same_inflight20_batch'])
        out.append(dict(ordinal=i,host_bracket_ns=[left,right],formal_host_s=[(left-m['armed_ns'])/1e9,(right-m['armed_ns'])/1e9],owner_tid=owner_tid,owner_is_consumer=owner_tid==wanted,owner_lifetime_stable=stable_owner,consumer_lifetime_stable=stable_consumer,consumer=consumer,owner_native=owner_native,owner_project_stack=project,closed_gil_pair=closed_pair,backlog_join=join,qualified_inflight_backlog_gil_witness=closed_pair and backlog_join,inside_requested_window=record['armed']['host_ns']+plan['capture_offset_ns']<=left<=right<=record['armed']['host_ns']+plan['capture_offset_ns']+plan['duration_ns']))
    assert prior<=rows[-1]['qpc']
    result=dict(clock=clock,queue_validation=validation,rows=out,actual_gap_ms=gaps,read_bracket_us=read_cost,post_resume_symbol_us=[(s['resolve_end_qpc']-s['resolve_begin_qpc'])*1e6/f for s in samples],
        window_checks=dict(all20_inside_requested_window=all(r['inside_requested_window'] for r in out),counter_end_lateness_pass=record['counter_end_late_ns']<=plan['lateness_ns_max'],cadence_pass=all(plan['period_ms']-1<=g<=plan['period_ms']+50 for g in gaps)),
        counts=dict(samples=len(out),closed_gil_pairs=sum(r['closed_gil_pair'] for r in out),qualified_inflight_backlog_witnesses=sum(r['qualified_inflight_backlog_gil_witness'] for r in out)),max_observed_pending=max(r[3] for r in m['queue_common']),
        source_sha256=sha(Path(__file__)),manifest_sha256=sha(a.raw/'manifest.json'),actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,
        limits=['Individual closed owner/waiter mechanisms only; counts are not time shares. GUI painting or reply parsing at an instant does not measure whole native-call GIL hold time or identify the severe OFF cases cause.','This new window is not a replacement for any OFF/failed window. Late completion/cadence failures stay failures; all20 samples including out-of-window rows retained.','Unmatched native modules keep original module/SHA/RVA; no kernel stack or scheduling state attribution. No-owner/empty Python frames remain explicit.','Replay reader/video thread paths are experimental and cannot be relabeled as the formal USB/camera reader. SDK native threads belong to another PID/GIL; GUI-side reply decoding is a separate main-process path.'])
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(dict(window_checks=result['window_checks'],counts=result['counts'],max_pending=result['max_observed_pending'],closed_pair_ordinals=[r['ordinal'] for r in out if r['closed_gil_pair']]))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
