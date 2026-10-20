"""Four retained windows, phase instruction/work bounds; no root/GHz/share claim."""
import base64
import collections
import hashlib
import json
from pathlib import Path
import statistics
import struct
from verify import check,identity
from classify import state
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def phase_bound(begin,end,spans,frequency):
    assert begin['tid']==end['tid'] and begin['creation']==end['creation'] and begin['qpc']<end['qpc']
    lo,hi=begin['qpc'],end['qpc'];hits=[s for s in spans if s['end']>lo and s['begin']<hi]
    assert hits and min(s['begin'] for s in hits)<=lo and max(s['end'] for s in hits)>=hi
    outside=sum(max(0,lo-s['begin'])+max(0,s['end']-hi) for s in hits)
    cpu=(end['kernel']+end['user']-begin['kernel']-begin['user'])*100
    return dict(retired_instruction_outer=sum(s['values'][0] for s in hits),core_counter_outer=sum(s['values'][1] for s in hits),reference_counter_outer=sum(s['values'][2] for s in hits),
        running_outer_ns=sum(s['end']-s['begin'] for s in hits)*1e9/frequency,
        marker_wall_ns=(hi-lo)*1e9/frequency,thread_cpu_ns=cpu,OS_cycles=end['cycles']-begin['cycles'],
        outside_marker_running_ns=outside*1e9/frequency,switch_intervals=len(hits))

def compare(slow,fast,limits):
    if not slow or not fast:return dict(available=False,reason='Frozen slow andfast states not both observed. No extra cases.')
    pairs=[]
    for a in slow:
        for b in fast:
            wall=a['wall_ns']/b['wall_ns'];instructions=a['instructions']/b['instructions']
            pairs.append(dict(slow=a['case'],fast=b['case'],wall_ratio=wall,instruction_outer_ratio=instructions,
                comparable_retired_work=abs(instructions-1)<=limits['comparable_instruction_fraction'],
                slow_effect_large=wall>=limits['minimum_wall_ratio']))
    return dict(available=True,all_cross_state_pairs=pairs,
        all_pairs_comparable_retired_work_and_slower=all(v['comparable_retired_work'] and v['slow_effect_large'] for v in pairs))

if __name__=='__main__':
    p=read(HERE/'plan01.json');root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest.items()) and all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert sha(HERE/'runs/evidence01.zip')==read(HERE/'transport01.json')['sha256']
    assert sha(root/'boundary.dll')==p['boundary_dll_sha256']
    status=read(root/'runs/status.json');capture=read(root/'capture01.json');assert status['complete'] and capture['cleanup_confirmed']
    meta=read(root/'decoded01/metadata.json');assert meta['clock_type']==1
    assert all(meta[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost'))
    by=collections.defaultdict(list);lifecycles=collections.defaultdict(list);orders=[]
    with (root/'decoded01/events.jsonl').open() as f:
        for line in f:
            e=json.loads(line);data=base64.b64decode(e['payload'])
            if e['provider']=='ce1dbfb4-137e-4da6-87b0-3f59aa102cbc' and e['opcode']==48:
                assert struct.unpack_from('<I',data)[0]==3;orders.append([v for v in data[4:].decode('utf-16le').split('\0') if v])
            if e['provider']=='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' and e['opcode'] in (1,2,3,4) and len(data)>=8:
                pid,tid=struct.unpack_from('<II',data);lifecycles[tid].append(dict(pid=pid,opcode=e['opcode'],qpc=e['qpc']))
            if e['pmc']:
                assert e['provider']=='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c' and e['opcode']==36 and e['version']==5
                assert len(e['pmc'])==1 and e['pmc'][0]['size']==24 and len(e['pmc'][0]['values'])==3
                new,old=struct.unpack_from('<II',data);by[e['cpu']].append((e['qpc'],new,old,e['pmc'][0]['values']))
    assert orders and all(v==p['counter_order'] for v in orders)
    spans=collections.defaultdict(list)
    for cpu,events in by.items():
        for a,b in zip(events,events[1:]):
            assert a[0]<=b[0] and a[1]==b[2] and all(y>=x for x,y in zip(a[3],b[3]))
            spans[a[1]].append(dict(cpu=cpu,begin=a[0],end=b[0],values=[y-x for x,y in zip(a[3],b[3])]))
    rows=[];reference=identity(read(HERE/'reference01.json'))
    for name in p['cases']:
        r=read(root/f'runs/{name}/result.json');exit=read(root/f'runs/{name}.status.json');context=read(root/f'runs/{name}.context.json')
        assert exit['confirmed_exit'] and exit['native_query_success'] and exit['observation_complete'] and exit['native_exit_code']==exit['managed_exit_code']==0
        assert check(p,r)['pass_all'] and identity(r)==reference and r['preparation']['frames']==42237 and r['opencv_threads']==8
        assert context['pid']==r['process_before']['pid']==exit['pid'] and context['session_id']==p['expected_session'][name]
        tid=r['consumer']['tid'];life=lifecycles[tid];assert any(v['pid']==context['pid'] and v['opcode']==1 for v in life) and any(v['pid']==context['pid'] and v['opcode']==2 for v in life)
        phases={}
        for phase in ('preparation','consumer'):
            a=r['native_phase_marks'][phase+'_begin'];b=r['native_phase_marks'][phase+'_end'];assert a['tid']==tid
            v=phase_bound(a,b,spans[tid],meta['qpc_frequency'])
            v['edge_quality_pass']=v['outside_marker_running_ns']<=p['phase_gates']['maximum_edge_running_ns']
            v['CPU_accounting_pass']=abs(v['running_outer_ns']-v['thread_cpu_ns'])<=p['phase_gates']['CPU_accounting_tolerance_ns']
            phases[phase]=v
        rows.append(dict(case=name,state=state(r,p['state_rules']),context=context,phases=phases))
    contexts_equal=len({v['context']['priority_class'] for v in rows})==1 and {v['context']['qpa'] for v in rows}=={'offscreen'}
    for kind in ('process','thread'):
        contexts_equal=contexts_equal and all(v['context'][kind]['success'] for v in rows) and len({(v['context'][kind]['control_mask'],v['context'][kind]['state_mask']) for v in rows})==1
    quality=contexts_equal and all(v['edge_quality_pass'] and v['CPU_accounting_pass'] for row in rows for v in row['phases'].values())
    comparisons={}
    for phase in ('preparation','consumer'):
        groups={label:[dict(case=v['case'],instructions=v['phases'][phase]['retired_instruction_outer'],wall_ns=v['phases'][phase]['marker_wall_ns']) for v in rows if v['state']['label']==label] for label in ('slow','fast')}
        comparisons[phase]=compare(groups['slow'],groups['fast'],p['comparison_rules']) if quality else dict(available=False,reason='Phase/context quality failed; no quantitative comparison.')
    out=dict(four_windows_complete=True,all_work_outputs_exact=True,phase_context_quality_pass=quality,cases=rows,comparisons=comparisons,
        both_joint_states_observed={v['state']['label'] for v in rows}>={'slow','fast'},
        root_mechanism_identified=False,actual_workload_disturbance_qualified=False,hardware_frequency_semantics_verified=False,
        limitations=['Sleep boundary andWPR change the fixture; no originalGUI/3pct/1pct certification.','Outer instructions include bounded edge work; no blank subtraction orcycle normalization.',
            'Retired counts do not identify a responsible function orunique power/cache mechanism.','Model/native pools exist; preparation andserial consumer precede formal inference.','All4windows retained; no extension towait forstates.'],
        bindings={v.name:sha(v) for v in (Path(__file__),HERE/'plan01.json',HERE/'runs/evidence01.zip')})
    with (HERE/'result01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
