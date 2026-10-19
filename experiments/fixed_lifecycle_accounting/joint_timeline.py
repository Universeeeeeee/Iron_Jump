"""Post-hoc decision evidence on one already-frozen real-work window; no new runs."""
import base64
import hashlib
import json
from pathlib import Path,PureWindowsPath
import statistics
import struct

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    r=read(HERE/'workload01.json');a=read(HERE/'accounting01.json');record=read(HERE/'record01.json');m=read(HERE/'metadata01.json');verified=read(HERE/'review01.json')
    assert verified['full_work_identity_exact'] and all(verified['loss'][k]==0 for k in verified['loss'])
    c=r['consumer'];model=r['model'];zero=c['begin_ns'];freq=m['qpc_frequency'];anchors=[record['start'],record['end']]
    lo=max(x['perf_before_ns']-x['qpc_after']*10**9//freq for x in anchors);hi=min(x['perf_after_ns']-x['qpc_before']*10**9//freq for x in anchors);assert lo<=hi
    images=[];starts=[]
    for line in (HERE/'events01.jsonl').open():
        e=json.loads(line);d=base64.b64decode(e['payload'])
        if e['provider'].startswith('2cb15d1d') and e['opcode']==10 and e['version'] in (2,3) and e['flags']&0x40 and len(d)>=58:
            base,size,pid=struct.unpack_from('<QQI',d)
            if pid==a['pid']:images.append(dict(base=base,size=size,path=d[56:].decode('utf-16le').split('\0')[0],qpc=e['qpc']))
        if e['provider'].startswith('3d6fa8d1') and e['opcode']==1:
            pid,tid=struct.unpack_from('<II',d);assert pid==a['pid']
            bounds=[e['qpc']*10**9//freq+lo,e['qpc']*10**9//freq+hi]
            if r['process_before']['end_ns']<=bounds[0] and bounds[1]<=r['process_after']['begin_ns']:
                row=dict(tid=tid,host_ns_bounds=bounds,since_consumer_start_ms=[(x-zero)/1e6 for x in bounds],layout_supported=e['version']==3 and bool(e['flags']&0x40) and len(d)==74)
                if row['layout_supported']:
                    entry=struct.unpack_from('<Q',d,48)[0];mods=[x for x in images if x['qpc']<=e['qpc'] and x['base']<=entry<x['base']+x['size']]
                    if len(mods)==1:row.update(entry=entry,module=mods[0]['path'],rva=entry-mods[0]['base'])
                row['contained_model_calls']=[x['ordinal'] for x in model['calls'] if x['begin_ns']<=bounds[0] and bounds[1]<=x['end_ns']]
                starts.append(row)
    before=[x for x in model['calls'] if x['end_ns']<=c['end_ns']];after=[x for x in model['calls'] if x['begin_ns']>=c['end_ns']];cross=[x for x in model['calls'] if x not in before and x not in after]
    blocks=[]
    for i in range(0,len(model['calls']),20):
        rows=model['calls'][i:i+20];blocks.append(dict(first_ordinal=i,count=len(rows),begin_ms=(rows[0]['begin_ns']-zero)/1e6,end_ms=(rows[-1]['end_ns']-zero)/1e6,median_wall_ms=statistics.median((x['end_ns']-x['begin_ns'])/1e6 for x in rows),max_wall_ms=max((x['end_ns']-x['begin_ns'])/1e6 for x in rows)))
    result=dict(exploratory_after_capture=True,slow_GUI_state_reproduced=False,reason='No prospectively frozen slow-state classifier or GUI/pending endpoint in this fixed-work lifecycle protocol.',
        timeline_ms=dict(model_ready=(model['ready_ns']-zero)/1e6,consumer_begin=0,consumer_end=(c['end_ns']-zero)/1e6,model_begin=(model['begin_ns']-zero)/1e6,model_end=(model['end_ns']-zero)/1e6),
        consumer_cpu_ms=c['thread_cpu_ns']/1e6,model_entry_cpu_ms=model['thread_cpu_ns']/1e6,
        process_cpu_ms=verified['process_cpu_ms'],retained_cpu_ms=verified['retained_cpu_ms'],unknown_cpu_ms=verified['unassigned_cpu_ms'],
        thread_starts_inside_work=starts,model_blocks=blocks,model_call_groups=dict(during_consumer=dict(count=len(before),median_wall_ms=statistics.median((x['end_ns']-x['begin_ns'])/1e6 for x in before)),after_consumer=dict(count=len(after),median_wall_ms=statistics.median((x['end_ns']-x['begin_ns'])/1e6 for x in after)),crossing_call_ordinals=[x['ordinal'] for x in cross]),
        exact_consumer_subwindow_progress_available=False,live_query_crosscheck_pass=False,
        next_single_intervention='Same complete consumer/model work: concurrent release versus model release only after consumer completes. Change only overlap in isolated harness; preserve original functions, inputs, model history and outputs.',
        limits=['ETW entry-to-module evidence uses the previously validated layout; live query failed with0xC0000022, so this window lacks its independent runtime cross-check.',
                'During/after model medians are temporal associations with different frame/history; not a causal estimate.',
                'Consumer CPU and wall are coextensive raw measurements, not a calibrated GIL/wait percentage. Process CPU can exceed wall; never subtract process CPU from wall.',
                'Only whole consumer-span timing was saved. No batch-by-batch consumer slowdown localization is available.','cv2.resize is a source-path candidate, not a stack-proven responsible function.'],
        sources={n:sha(HERE/n) for n in ['joint_timeline.py','review01.json','workload01.json','events01.jsonl']})
    with (HERE/'joint_result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k not in ('sources','model_blocks','limits')},indent=2))
