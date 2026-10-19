"""Associate lifecycle and live new-thread queries; never infer CPU/GIL shares."""
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path,PureWindowsPath
import struct
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def module(name,path):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

if __name__=='__main__':
    sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'));from analyze import clock_residual_ms,PLAN
    life_module=module('fixed_lifecycle_events',ROOT/'experiments/thread_lifecycle_review/review.py')
    entry_module=module('fixed_lifecycle_entry',ROOT/'experiments/thread_entry_control/review.py')
    counters=module('fixed_lifecycle_counters',ROOT/'experiments/fixed_work_accounting/counters.py')
    inventory=module('fixed_lifecycle_inventory',ROOT/'experiments/thread_accounting_controls/inventory02.py')
    plan=read(HERE/'plan01.json');a=read(HERE/'accounting01.json');r=read(HERE/'workload01.json');m=read(HERE/'metadata01.json');record=read(HERE/'record01.json');status=read(HERE/'status01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and all(sha(ROOT/n)==v for n,v in plan['dependency_sources'].items())
    prior_root=ROOT/'experiments/fixed_work_variance/runs/evidence01';manifest=read(prior_root/'manifest.json');assert all(sha(prior_root/n)==v for n,v in manifest.items());prior=read(prior_root/'runs/pair01_a/result.json')
    assert all(r[k]==prior[k] for k in ('frame_evidence','model_result_sha256','report_sha256'))
    assert r['complete'] and not r['errors'] and not r['worker_alive'] and r['model']['closed']
    assert a['workload_returncode']==0 and not a['errors'] and a['source_unchanged'] and a['handles_closed']
    assert status['complete'] and not status['errors'] and status['interval_before']==status['interval_after'] and record['cleanup_complete'] and record['stop_ok']
    p=counters.validate(r);assert p['accounting_pass'] and p==r['process_accounting']
    before,after=a['reads'];assert before['process']==r['process_before'] and after['process']==r['process_after']
    retained=inventory.summarize(before['threads'],after['threads'],plan['per_read_ns'],plan['group_ns']);assert retained==a['retained_accounting']
    assert before['threads']['after_ns']<=min(r['consumer']['begin_ns'],r['model']['begin_ns']) and max(r['consumer']['end_ns'],r['model']['work_done_ns'])<=after['threads']['before_ns']
    assert a['enumeration_before']['after_ns']<=before['process']['begin_ns'] and after['process']['end_ns']<=a['enumeration_after']['before_ns']
    assert m['target_pid']==a['pid']==r['process_before']['pid'] and m['clock_type']==1 and m['qpc_frequency']==record['start']['frequency']
    assert all(m[k]==0 for k in ('header_events_lost','consumer_events_lost','buffers_lost'))
    assert not any(k.startswith('def2fe46') or (k.startswith('ce1dbfb4') and k.split('/')[1]!='34') or (k.startswith('3d6fa8d1') and k.split('/')[1] in ('36','50')) for k in m['shapes'])
    anchors=[record['start'],record['end']];freq=m['qpc_frequency'];residual=clock_residual_ms(anchors,m['clock_samples'],freq);assert residual<=PLAN['gates']['clock_residual_ms_max']
    lo=max(x['perf_before_ns']-x['qpc_after']*10**9//freq for x in anchors);hi=min(x['perf_after_ns']-x['qpc_before']*10**9//freq for x in anchors);assert lo<=hi
    events=defaultdict(list);images=[]
    for line in (HERE/'events01.jsonl').open():
        e=json.loads(line);d=base64.b64decode(e['payload'])
        if e['provider'].startswith('3d6fa8d1') and e['opcode'] in (1,2,3,4):
            assert e['version']==3 and len(d)>=8;pid,tid=struct.unpack_from('<II',d);assert pid==a['pid'];events[tid].append(e)
        if e['provider'].startswith('2cb15d1d') and e['opcode']==10 and e['version'] in (2,3) and e['flags']&0x40 and len(d)>=58:
            base,size,pid,checksum=struct.unpack_from('<QQII',d)
            if pid==a['pid']:images.append(dict(base=base,size=size,path=d[56:].decode('utf-16le').split('\0')[0],qpc=e['qpc']))
    life={tid:life_module.lifetimes([(e['qpc'],e['opcode']) for e in rows]) for tid,rows in events.items()}
    new=sorted(set(a['enumeration_after']['tids'])-set(a['enumeration_before']['tids']));assert new==[q['tid'] for q in a['new_thread_queries']]
    links=[]
    for q in a['new_thread_queries']:
        item=dict(query=q,qualified=False);links.append(item)
        if q.get('error') or q.get('module_hash_error') or not q['handle_closed'] or q.get('exit_100ns')!=0:continue
        spans=[x for x in life.get(q['tid'],[]) if x['actual_creation'] and x['actual_exit'] and x['begin']*10**9//freq+hi<=q['before_ns'] and q['after_ns']<=x['end']*10**9//freq+lo]
        if len(spans)!=1:continue
        span=spans[0];start=[e for e in events[q['tid']] if e['opcode']==1 and e['qpc']==span['begin']];assert len(start)==1
        try:entry_module.verify_entry(start[0],q['entry'])
        except ValueError as exc:item['layout_or_address_error']=str(exc);continue
        matches=[x for x in images if x['qpc']<=span['begin'] and x['base']==q['module_base'] and x['base']<=q['entry']<x['base']+x['size'] and PureWindowsPath(x['path']).name.lower()==PureWindowsPath(q['module_path']).name.lower()]
        if len(matches)!=1:continue
        item.update(qualified=True,lifetime=span,module_load=matches[0],created_inside_process_counter_window=span['begin']*10**9//freq+lo>=r['process_before']['end_ns'] and span['begin']*10**9//freq+hi<=r['process_after']['begin_ns'],
            lifetime_cpu_ms_at_late_query=(q['lifetime_kernel_100ns']+q['lifetime_user_100ns'])/10000,query_delay_after_work_counter_ms=(q['before_ns']-r['process_after']['end_ns'])/1e6)
    result=dict(full_work_identity_exact=True,retained_accounting=retained,process_cpu_ms=p['process_cpu_ns']/1e6,retained_cpu_ms=retained['sum_cpu_ms'],unassigned_cpu_ms=p['process_cpu_ns']/1e6-retained['sum_cpu_ms'],
        new_tids=new,new_thread_links=links,all_new_entries_correlated=all(x['qualified'] for x in links),all_target_lifetimes=life,clock_residual_ms=residual,
        loss={k:m[k] for k in ('header_events_lost','consumer_events_lost','buffers_lost')},trace_elapsed_s=(record['end']['qpc_after']-record['start']['qpc_before'])/freq,
        actual_load_disturbance_pass=False,primary_root_identified=False,
        limits=['Post-work queries include lifetime CPU through their later timestamps, not exact ROI CPU; do not subtract them to claim precise attribution.',
                'Thread entry module is not current execution stack, creator or responsibility function. Unknown layouts/queries stay unknown.',
                'Single lifecycle-observed fixed workload is not an OFF/ON comparison and does not replace earlier failures or quantify field/GIL contributions.'],
        sources={n:sha(HERE/n) for n in ['review.py','accounting01.json','workload01.json','record01.json','metadata01.json','events01.jsonl','plan01.json']})
    with (HERE/'review01.json').open('x') as out:json.dump(result,out,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('all_target_lifetimes','retained_accounting','sources')},indent=2))
