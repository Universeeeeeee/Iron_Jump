"""Describe coarse placement metadata; never infer physical frequency or past causes."""
import argparse
from pathlib import Path
from archive_review01 import verify_manifest
from control03 import read,sha,write
from verify import case_result


def placement(data,roi):
    points=data['points'];expected=['before_roi']+['after_'+str(b['raw_last']) for b in roi['blocks']]
    assert [p['boundary'] for p in points]==expected
    assert all(p['host_before_ns']<=p['host_after_ns'] for p in points)
    assert all(a['host_after_ns']<=b['host_before_ns'] for a,b in zip(points,points[1:]))
    assert points[0]['host_after_ns']<=roi['wall_begin_ns']
    assert all(b['wall_end_ns']<=p['host_before_ns']<=p['host_after_ns']<=roi['wall_end_ns'] for p,b in zip(points[1:],roi['blocks']))
    records=data['topology']['records'];topology={}
    for row in records:
        if 'logical' in row:
            key=(row['group'],row['logical'])
            assert key not in topology;topology[key]=row
    out=[]
    for p in points:
        row=topology.get((p['group'],p['logical'])) if data['topology']['error']==0 else None
        out.append(dict(**p,core=row['core'] if row else None,efficiency_class=row['efficiency_class'] if row else None))
    return out


def main(a):
    verify_manifest(a.raw);base=a.raw/'cpu_delivery01';plan=read(base/'plan01.json');summary=read(base/'diagnostic01/run01/result.json')
    assert summary['capture_protocol_complete'] and not summary['errors'] and summary['plan_sha256']==sha(base/'plan01.json')
    assert all(sha(base/n)==h for n,h in plan['sources'].items()) and sha(base/'CpuProbe.dll')==plan['cpu_probe_sha256']
    result=dict(cases={},plan_sha256=sha(base/'plan01.json'),manifest_sha256=sha(a.raw/'manifest.json'),reviewer_sha256=sha(Path(__file__)),actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    for spec in plan['cases']:
        folder=base/'diagnostic01/run01'/spec['id'];record=read(folder/'record.json');roi=read(folder/'target/roi.json');complete=read(folder/'target/complete.json');analysis=case_result(record,roi,complete,[],plan,Path(__file__).resolve().parents[2])
        assert spec['mode']=='off' and analysis==read(folder/'analysis.json') and analysis['case_pass']
        assert not (folder/'target.log').read_bytes() and not (folder/'observer.log').read_bytes()
        data=read(folder/'target/cpu_delivery.json')
        result['cases'][spec['id']]=dict(case_pass=True,wall_ms=roi['wall_ns']/1e6,thread_cpu_ms=roi['thread_cpu_ns']/1e6,os_cpu_span_ms=analysis['os_cpu_span_ns']/1e6,cycles=analysis['cycles'],points=placement(data,roi),topology=data['topology'],power_before=data['power_before'],power_after=data['power_after'])
    result['limits']=['Only these new instrumented OFF runs. No observer disturbance calibration, historical slow-run explanation, full migration trace, physical delivery/frequency or exclusive GC attribution.','No affinity, scheduling, power, timer, GC or production setters. OS policy getter metadata does not prove physical delivery.','All4 fixed cases and exact original processing outputs retained.']
    write(a.output,result)
    print({k:dict(wall_ms=v['wall_ms'],cpu_ms=v['thread_cpu_ms'],positions=[(p['logical'],p['efficiency_class']) for p in v['points']],power=v['power_before']) for k,v in result['cases'].items()})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
