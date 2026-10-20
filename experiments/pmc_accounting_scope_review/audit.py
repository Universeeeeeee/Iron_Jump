"""P0 audit of the unchanged four-window ETL; all phases retained, no new capture."""
import base64
import collections
import hashlib
import json
from pathlib import Path
import struct
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
THREAD='3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c';PERF='ce1dbfb4-137e-4da6-87b0-3f59aa102cbc'
def overlap(spans,lo,hi):
    assert lo<hi
    selected=[v for v in spans if v['end']>lo and v['begin']<hi]
    return dict(outer_qpc=sum(v['end']-v['begin'] for v in selected),
        clipped_qpc=sum(min(v['end'],hi)-max(v['begin'],lo) for v in selected),intervals=selected)
if __name__=='__main__':
    folder=ROOT/'experiments/slow_state_pmc_work';raw=folder/'runs/evidence01';plan=read(folder/'plan01.json');manifest=read(raw/'manifest01.json');meta=read(raw/'decoded01/metadata.json')
    assert all(sha(raw/n)==v for n,v in manifest.items())
    assert sha(folder/'runs/evidence01.zip')==read(folder/'transport01.json')['sha256']
    assert all(meta[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost')) and meta['clock_type']==1
    cases={n:read(raw/f'runs/{n}/result.json') for n in plan['cases']};tids={r['consumer']['tid'] for r in cases.values()}
    spans=collections.defaultdict(list);life=collections.defaultdict(list);last={};perf=collections.Counter();event_count=0;chain_count=0
    for line in (raw/'decoded01/events.jsonl').open():
        e=json.loads(line);event_count+=1;data=base64.b64decode(e['payload'])
        if e['provider']==PERF:perf[str(e['opcode'])]+=1
        if e['provider']==THREAD and e['opcode'] in (1,2,3,4) and len(data)>=8:
            pid,tid=struct.unpack_from('<II',data)
            if tid in tids:life[tid].append(dict(pid=pid,tid=tid,opcode=e['opcode'],qpc=e['qpc'],version=e['version'],length=len(data),flags=e['flags']))
        if e['provider']!=THREAD or e['opcode']!=36:continue
        assert e['version']==5 and len(data)==28 and e['flags']&0x40
        new,old=struct.unpack_from('<II',data);a=last.get(e['cpu']);current=dict(qpc=e['qpc'],new=new,old=old)
        if a:
            assert a['qpc']<=e['qpc'] and a['new']==old
            chain_count+=1
            if a['new'] in tids:spans[a['new']].append(dict(cpu=e['cpu'],begin=a['qpc'],end=e['qpc']))
        last[e['cpu']]=current
    assert event_count==meta['selected'];freq=meta['qpc_frequency'];rows=[]
    for name,r in cases.items():
        marks=r['native_phase_marks'];tid=r['consumer']['tid'];pid=r['process_before']['pid'];created={v['creation'] for v in marks.values()}
        assert len(created)==1 and all(v['tid']==tid for v in marks.values())
        first=marks['preparation_begin']['qpc'];last=marks['consumer_end']['qpc']
        starts=[v for v in life[tid] if v['pid']==pid and v['opcode']==1 and v['qpc']<=first]
        ends=[v for v in life[tid] if v['pid']==pid and v['opcode']==2 and v['qpc']>=last]
        assert len(starts)==len(ends)==1 and starts[0]['qpc']<first<last<ends[0]['qpc']
        assert not any(first<v['qpc']<last and v['opcode'] in (1,2) for v in life[tid])
        phases={}
        for phase in ('preparation','consumer'):
            a,b=marks[phase+'_begin'],marks[phase+'_end'];v=overlap(spans[tid],a['qpc'],b['qpc'])
            assert v['intervals'] and min(x['begin'] for x in v['intervals'])<=a['qpc'] and max(x['end'] for x in v['intervals'])>=b['qpc']
            cpu=(b['kernel']+b['user']-a['kernel']-a['user'])*100
            outer=v['outer_qpc']/freq*1000;clipped=v['clipped_qpc']/freq*1000
            start_skew=r[phase]['begin_ns']-a['qpc']*1e9/freq;end_skew=b['qpc']*1e9/freq-r[phase]['end_ns']
            assert start_skew>=0 and end_skew>=0 and start_skew+end_skew<=plan['phase_gates']['maximum_edge_running_ns']
            phases[phase]=dict(native_QPC_markers=[a['qpc'],b['qpc']],thread_creation_FILETIME_100ns=a['creation'],
                GetThreadTimes_kernel_delta_ms=(b['kernel']-a['kernel'])/10000,GetThreadTimes_user_delta_ms=(b['user']-a['user'])/10000,
                GetThreadTimes_total_ms=cpu/1e6,Python_thread_time_ms=r[phase]['thread_cpu_ns']/1e6,
                native_and_Python_accounting_equal=cpu==r[phase]['thread_cpu_ns'],
                CSwitch_outer_running_ms=outer,CSwitch_exactly_clipped_running_ms=clipped,
                marker_wall_ms=(b['qpc']-a['qpc'])/freq*1000,outer_edge_ms=outer-clipped,
                original_begin_inside_native_ns=start_skew,original_end_inside_native_ns=end_skew,
                raw_gap_ms=outer-cpu/1e6,clipped_gap_ms=clipped-cpu/1e6,
                raw_gate_pass=abs(outer-cpu/1e6)<=31.25,clipped_gate_pass_for_diagnostic_only=abs(clipped-cpu/1e6)<=31.25,
                intervals=v['intervals'])
        rows.append(dict(case=name,pid=pid,tid=tid,thread_start=starts[0],thread_end=ends[0],same_native_thread_creation_across_phases=True,
            no_TID_reuse_inside_markers=True,phases=phases))
    result=dict(original_ETL_and_manifest_verified=True,all_four_cases_all_eight_phases_retained=True,zero_reported_loss=True,
        all_adjacent_per_CPU_thread_chains_match=True,adjacent_intervals_checked=chain_count,event_rows_verified=event_count,
        QPC_frequency=freq,raw_QPC_clock_type=meta['clock_type'],PerfInfo_opcodes=dict(perf),DPC_ISR_recorded_in_old_ETL=False,
        cases=rows,
        established=['Actual target PID/TID lifetimes enclose phase markers, withstable thread creation identity.','Exact clipping preserves the large preparation mismatch; CSwitch edge overhang is not its explanation.',
            'Native GetThreadTimes andPython thread CPU use the same OS accounting family; agreement is not an independent precision certification.',
            'Native API read order brackets QPC markers onthe outside; exact CPU-read timestamps were not recorded.'],
        hypotheses=['OS statistical/quantized accounting scope, interrupt/DPC overlap, andinstrumentation accounting may contribute. None is assigned the full residual.'],
        unresolved=['No DPC/ISR events inoldETL; cannot reconstruct old interrupt overlap from later control.','No before/after timestamp brackets around each GetThreadTimes invocation; exact skew cannot be retrospectively measured.',
            '83.612ms cannot be split into unique causes withcurrent evidence.'],
        original_31_25ms_gate_unchanged=True,original_failure_unchanged=True,cross_state_comparisons_released=False,
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),folder/'plan01.json',folder/'result01.json',folder/'transport01.json',ROOT/'experiments/interrupt_scope_control/scope_audit01.json')})
    with (HERE/'audit01.json').open('x') as f:json.dump(result,f,indent=2)
    bad=next(v for v in rows if v['case']=='service01')['phases']['preparation'];print(json.dumps({k:v for k,v in bad.items() if k!='intervals'},indent=2))
