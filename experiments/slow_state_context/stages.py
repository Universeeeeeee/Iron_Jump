"""Exploratory all-stage review; never relabel the frozen joint state outcome."""
import hashlib
import json
from pathlib import Path
import statistics
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    root=HERE/'runs/evidence01';plan=read(HERE/'plan01.json');rows=[]
    manifest=read(root/'manifest01.json');assert all(sha(root/n)==v for n,v in manifest['files'].items())
    for name in plan['cases']:
        r=read(root/f'runs/{name}/result.json');c=r['consumer'];m=r['model'];last=dict(frames=0,host_ns=c['begin_ns'],thread_cpu_ns=0);segments=[]
        for point in r['consumer_progress']:
            count=point['frames']-last['frames'];wall=point['host_ns']-last['host_ns'];cpu=point['thread_cpu_ns']-last['thread_cpu_ns']
            segments.append(dict(after_frame=point['frames'],frames=count,wall_ms=wall/1e6,cpu_ms=cpu/1e6,wall_us_per_frame=wall/count/1e3,cpu_us_per_frame=cpu/count/1e3))
            last=point
        calls=m['calls'];blocks=[]
        for start in range(0,len(calls),20):
            part=calls[start:start+20]
            blocks.append(dict(first=start,last=start+len(part)-1,median_ms=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in part)))
        rows.append(dict(case=name,consumer_segments=segments,model_blocks=blocks,model_open_ms=(m['open_end_ns']-m['open_begin_ns'])/1e6))
    out=dict(exploratory=True,all_cases_and_blocks_retained=True,cases=rows,root_mechanism_identified=False,
        interpretation='Intermediate joint label is retained. Stage variation alone is not a proven same-process hardware-state transition, and single calls/segments are not independent trials.',
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),archive_sha256=sha(HERE/'runs/evidence01.zip'),analysis_sha256=sha(Path(__file__))))
    with (HERE/'stages01.json').open('x') as f:json.dump(out,f,indent=2)
    for row in rows:print(row['case'],'consumer_us/frame',[round(v['wall_us_per_frame'],1) for v in row['consumer_segments']],'model20_medians',[round(v['median_ms'],2) for v in row['model_blocks']])
