"""Independent native marker/phase timing and retained task metadata cross-check."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');out=read(HERE/'result01.json');root=HERE/'runs/evidence01'
    manifest=read(root/'manifest01.json');assert all(sha(root/n)==v for n,v in manifest.items())
    assert sha(HERE/'runs/evidence01.zip')==read(HERE/'transport01.json')['sha256']
    assert read(HERE/'transport_execution01.json')['ssh_returncode']==0 and read(root/'runs/status.json')['complete']
    cap=read(root/'capture01.json');assert cap['stop_returncode']==0 and cap['cleanup_confirmed'] and cap['interval_before_100ns']==cap['interval_after_100ns']
    meta=read(root/'decoded01/metadata.json')
    with (root/'decoded01/events.jsonl').open() as f:assert sum(1 for _ in f)==meta['selected']
    users=[];ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    for name,row in zip(p['cases'],out['cases']):
        assert row['case']==name
        task=ET.fromstring((root/f'runs/{name}.task.xml').read_text(encoding='utf-8-sig'));get=lambda name:task.find('.//t:'+name,ns)
        users.append(get('UserId').text)
        assert get('LogonType').text==('S4U' if name.startswith('service') else 'InteractiveToken')
        assert get('RunLevel').text=='HighestAvailable' and (get('Priority').text if get('Priority') is not None else '7')=='7'
        r=read(root/f'runs/{name}/result.json');marks=r['native_phase_marks']
        assert marks['preparation_begin']['qpc']<marks['preparation_end']['qpc']<marks['consumer_begin']['qpc']<marks['consumer_end']['qpc']
        for phase in ('preparation','consumer'):
            a,b=marks[phase+'_begin'],marks[phase+'_end'];v=row['phases'][phase]
            assert v['retired_instruction_outer']>0 and v['OS_cycles']==b['cycles']-a['cycles']>=0
            wall=r[phase]['end_ns']-r[phase]['begin_ns']
            # Native marker brackets include only boundary/record bookkeeping beyond original phase.
            assert 0<=v['marker_wall_ns']-wall<=p['phase_gates']['maximum_edge_running_ns']
    assert len(set(users))==1 and len(out['cases'])==4
    post=read(HERE/'post01.json');assert not post['related_processes']
    verification=dict(all_manifests_and_original_windows_match=True,native_marker_order_and_timing_match=True,
        task_XML_same_user_level_priority_verified=True,owned_stop_and_interval_verified=True,all_four_cases_retained=True,
        root_mechanism_identified=False,actual_workload_disturbance_qualified=False,
        bindings={f.name:sha(f) for f in (Path(__file__),HERE/'result01.json',HERE/'plan01.json',HERE/'transport01.json')})
    with (HERE/'verification01.json').open('x') as f:json.dump(verification,f,indent=2)
    print(json.dumps(verification,indent=2))
