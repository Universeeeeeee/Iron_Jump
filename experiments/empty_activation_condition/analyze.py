"""Two finite ordered blocks; original work andempty activation remain distinct."""
import hashlib
import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
from classify import state
from verify import check,identity
from decision import decide
from spacing import busy
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest['files'].items()) and all(sha(HERE/n)==v for n,v in p['sources'].items())
    assert sha(HERE/'runs/evidence01.zip')==read(HERE/'transport01.json')['sha256']
    status=read(root/'runs/status.json');reference=identity(read(HERE/'reference01.json'));rows=[];contexts=[];labels={};task_users=[]
    ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'};all_good=status['complete']
    for step in p['steps']:
        name=step['id'];record=dict(step=step,complete=False)
        file=root/f'runs/{name}.status.json'
        if not file.exists():rows.append(dict(record,unattempted_or_status_missing=True));all_good=False;continue
        exit=read(file);record['exit']=exit
        if not (exit['native_query_success'] and exit['confirmed_exit'] and exit['observation_complete'] and exit['native_exit_code']==exit['managed_exit_code']==0):
            rows.append(record);all_good=False;continue
        c=read(root/f'runs/{name}.context.json');record['context']=c;contexts.append(c)
        assert c['pid']==exit['pid'] and c['session_id']==p['expected_session'][name]
        tree=ET.fromstring((root/f'runs/{name}.task.xml').read_text(encoding='utf-8-sig'));find=lambda k:tree.find('.//t:'+k,ns)
        task_users.append(find('UserId').text)
        assert find('LogonType').text==('InteractiveToken' if step['logon']=='Interactive' else 'S4U')
        assert find('RunLevel').text=='HighestAvailable' and (find('Priority').text if find('Priority') is not None else '7')=='7'
        if step['kind']=='work':
            r=read(root/f'runs/{name}/result.json');assert check(p,r)['pass_all'] and identity(r)==reference
            assert r['preparation']['frames']==42237 and r['consumer']['frames']==6824 and len(r['model']['calls'])==220 and r['opencv_threads']==8 and r['variant']=='serial'
            assert r['process_before']['pid']==c['pid'];record['state']=state(r,p['state_rules']);labels[name]=record['state']['label']
        else:
            empty=read(root/f'runs/{name}.empty.json');assert empty['complete'] and not empty['prohibited_modules'] and empty['pid']==c['pid']
            assert empty['total_process_cpu_ns']<=p['empty_process_CPU_max_ns'];record['empty']=empty
            assert not (root/f'runs/{name}/result.json').exists()
        record['complete']=True;rows.append(record)
    contexts_match=bool(contexts) and len({c['priority_class'] for c in contexts})==1 and {c['qpa'] for c in contexts}=={'offscreen'} and len(set(task_users))==1
    for kind in ('process','thread'):
        contexts_match=contexts_match and all(c[kind]['success'] for c in contexts) and len({(c[kind]['control_mask'],c[kind]['state_mask']) for c in contexts})==1
    gap_quality=False;actual_gap=None
    if (root/'runs/inter_block_gap01.json').exists():
        g=read(root/'runs/inter_block_gap01.json');r=g['record'];samples=r['system_samples'];loads=[busy(a,b) for a,b in zip(samples,samples[1:])]
        ready=(r['wait_finished_ns']-r['deadline_ns'])/1e9
        bounded=all(0<=v['end_ns']-v['begin_ns']<=50000000 for v in samples) and all(0<b['begin_ns']-a['begin_ns']<=6000000000 for a,b in zip(samples,samples[1:]))
        gap_quality=0<=ready<=2 and bounded and len(loads)>=50 and statistics.median(loads)<=15 and max(loads)<=50 and {v['ac'] for v in samples}=={1}
        c=next((row.get('context') for row in rows if row['step']['id']=='b2_baseline'),None)
        if c:
            actual_gap=(c['perf_counter_ns']-r['previous_exit_observed_ns'])/1e9
            gap_quality=gap_quality and p['inter_block_gap_seconds']<=actual_gap<=p['inter_block_gap_seconds']+p['actual_launch_lateness_max_seconds']
        else:gap_quality=False
    quality=all_good and contexts_match and gap_quality and len(rows)==10 and all(v['complete'] for v in rows)
    result=dict(all_ten_steps_complete=all_good,context_and_identity_quality_pass=contexts_match,inter_block_gap_pass=gap_quality,actual_gap_to_next_context_seconds=actual_gap,
        cases=rows,work_labels=labels,decision=decide(labels,quality),root_mechanism_identified=False,actual_workload_disturbance_qualified=False,
        no_formal_changes=True,no_new_human_device_GUI_SDK_or_Run=True,
        bindings={f.name:sha(f) for f in (Path(__file__),HERE/'plan01.json',HERE/'runs/evidence01.zip')})
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
