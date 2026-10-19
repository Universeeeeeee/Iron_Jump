"""Independently recheck derived startup intervals against retained source records."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    summary=read(HERE/'readiness_result04.json');aligned=read(HERE/'readiness_alignment04.json');plan=read(HERE/'plan02.json')
    assert all(hashlib.sha256((HERE/n).read_bytes()).hexdigest()==v for n,v in summary['bindings'].items())
    assert summary['common_frames']==aligned['common_frames'] and summary['median_first_to_later_ratio']==aligned['median_per_frame_early_to_late_ratio']
    previous=None
    for case in plan['cases']:
        name=case['id'];folder=HERE/'runs/evidence01/runs/gui02'/name
        m=read(folder/'capture/measurement.json');w=read(folder/'capture/workload_final.json');ctx=read(folder/'startup_context.json');s=summary['cases'][name]
        ready=[v for v in w['rows']['service_status'] if v['status']=='ready'];assert len(ready)==1
        assert s['ready_before_arm_ms']==(m['armed_ns']-ready[0]['observed_ns'])/1e6
        assert s['startup_to_arm_ms']==(m['armed_ns']-ctx['perf_counter_ns'])/1e6
        assert s['previous_model_close_to_startup_ms']==(None if previous is None else (ctx['perf_counter_ns']-previous)/1e6)
        previous=max(v['end_ns'] for v in w['rows']['model_close'])
    print('All eight startup intervals and common-frame alignment verified')
