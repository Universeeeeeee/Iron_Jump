"""Pair rare GC callback brackets without turning them into exclusive CPU attribution."""
import argparse
from pathlib import Path
from control03 import read,write


def pair_events(data):
    if data['overflow']:raise ValueError('GC buffer overflow; incomplete evidence')
    active=None;rows=[];previous=0
    for e in data['events']:
        if len(e)!=6 or e[0]<previous:raise ValueError('Malformed/nonmonotone GC event')
        previous=e[0]
        if e[2]==0:
            if active is not None:raise ValueError('Nested/unclosed start')
            active=e
        elif e[2]==1:
            if active is None or (active[3],active[5])!=(e[3],e[5]) or e[1]<active[1]:raise ValueError('Mismatched GC stop')
            rows.append(dict(start_ns=active[0],end_ns=e[0],wall_ns=e[0]-active[0],thread_cpu_counter_delta_ns=e[1]-active[1],generation=e[3],tid=e[5],start_phase=active[4],end_phase=e[4]));active=None
        else:raise ValueError('Unknown GC event kind')
    if active is not None:raise ValueError('Unclosed GC event')
    return rows


def inspect(folder):
    data=read(folder/'gc_events.json');roi=read(folder/'roi.json');pairs=pair_events(data)
    inside=[e for e in pairs if roi['wall_begin_ns']<=e['start_ns']<=e['end_ns']<=roi['wall_end_ns']]
    largest=sorted(inside,key=lambda e:e['wall_ns'],reverse=True)[:10]
    blocks=[]
    for b in roi['blocks']:
        overlaps=[e for e in pairs if e['start_ns']<b['wall_end_ns'] and b['wall_begin_ns']<e['end_ns']]
        blocks.append(dict(raw_first=b['raw_first'],raw_last=b['raw_last'],wall_ns=b['wall_ns'],thread_cpu_ns=b['thread_cpu_ns'],gc_event_count=len(overlaps),gc_brackets=overlaps))
    return dict(total_paired_gc=len(pairs),whole_roi_wall_ns=roi['wall_ns'],inside_roi_events=len(inside),largest_inside_roi=largest,blocks=blocks,prior_callbacks=data['prior_callbacks'],scope='New instrumented diagnostic only. Callback boundaries include callback cost and scheduling. No original-run retrospective blame or GC CPU/wall percentage; no GC disabling or threshold change.',field_attribution_ready=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out={x.name:inspect(x/'target') for x in sorted((a.raw/'gc_diagnostic01/run01').iterdir()) if x.is_dir()};write(a.output,out)
    print({k:dict(events=v['inside_roi_events'],largest_ms=[e['wall_ns']/1e6 for e in v['largest_inside_roi'][:3]]) for k,v in out.items()})
