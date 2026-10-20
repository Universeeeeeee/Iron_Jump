"""Check same-thread residency is never counted simultaneously on two CPUs."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent

def union_length(intervals):
    merged=[]
    for a,b in sorted(intervals):
        assert a<=b
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else:merged.append((a,b))
    return sum(b-a for a,b in merged)
if __name__=='__main__':
    audit=json.loads((HERE/'audit01.json').read_text());frequency=audit['QPC_frequency'];rows=[]
    for c in audit['cases']:
        for phase,v in c['phases'].items():
            lo,hi=v['native_QPC_markers'];spans=v['intervals'];clipped=[(max(lo,s['begin']),min(hi,s['end'])) for s in spans]
            total=sum(b-a for a,b in clipped);unique=union_length(clipped);dup=(total-unique)/frequency*1000
            rows.append(dict(case=c['case'],phase=phase,CPUs=sorted({s['cpu'] for s in spans}),switch_intervals=len(spans),
                clipped_summed_running_ms=total/frequency*1000,clipped_unique_running_ms=unique/frequency*1000,
                simultaneous_CPU_overlap_ms=dup,unique_running_minus_GetThreadTimes_ms=unique/frequency*1000-v['GetThreadTimes_total_ms']))
    out=dict(cases=rows,any_double_counted_residency=any(v['simultaneous_CPU_overlap_ms']>0 for v in rows),
        original_gate_or_failure_changed=False,binding=dict(audit_sha256=hashlib.sha256((HERE/'audit01.json').read_bytes()).hexdigest()))
    with (HERE/'overlap01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
