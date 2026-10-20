"""Cross-check delivered task XML, native exits and exact workload outputs."""
import hashlib
import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET
from verify import check,identity

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    root=HERE/'runs/evidence01';p=read(HERE/'plan01.json');result=read(HERE/'result01.json');meta=read(HERE/'transport01.json')
    binding=read(HERE/'analysis_binding01.json');manifest=read(root/'manifest01.json')
    assert sha(HERE/'runs/evidence01.zip')==meta['sha256']
    assert binding['analyzer_sha256']==sha(HERE/'analyze.py') and binding['plan_sha256']==sha(HERE/'plan01.json')
    assert all(sha(root/n)==h for n,h in manifest['files'].items())
    assert read(HERE/'transport_execution01.json')['ssh_returncode']==0
    assert read(root/'runs/status.json')['complete'] and result['all_four_complete']
    assert not read(HERE/'post01.json')['related_processes'] and not read(HERE/'post01.json')['remaining_tasks']
    users=[];rows=[]
    ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    for name,outcome in zip(p['cases'],result['cases']):
        task=ET.fromstring((root/f'runs/{name}.task.xml').read_text(encoding='utf-8-sig'))
        value=lambda q:task.find(q,ns).text
        users.append(value('.//t:UserId'))
        logon='InteractiveToken' if name.startswith('interactive') else 'S4U'
        assert value('.//t:LogonType')==logon and value('.//t:RunLevel')=='HighestAvailable'
        # Task Scheduler schema default is7; exports omit this default.
        priority=task.find('.//t:Priority',ns)
        assert (priority.text if priority is not None else '7')=='7'
        assert value('.//t:Command')=='powershell.exe'
        assert value('.//t:Arguments').endswith('-Case '+name)
        data=read(root/f'runs/{name}/result.json');exit_record=read(root/f'runs/{name}.status.json');context=read(root/f'runs/{name}.context.json')
        assert exit_record['native_query_success'] and exit_record['confirmed_exit'] and exit_record['observation_complete']
        assert exit_record['managed_exit_code']==exit_record['native_exit_code']==0
        assert context['pid']==data['process_before']['pid']==exit_record['pid']
        assert check(p,data)['pass_all'] and identity(data)==identity(read(HERE/'reference01.json'))
        assert data['preparation']['frames']==42237 and data['consumer']['frames']==6824 and len(data['model']['calls'])==220
        assert data['opencv_threads']==8 and data['variant']=='serial'
        prep=(data['preparation']['end_ns']-data['preparation']['begin_ns'])/1e6
        median=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in data['model']['calls'])
        label='slow' if prep>=4300 and median>=30 else 'fast' if prep<=3500 and median<=26 else 'intermediate'
        assert outcome['id']==name and outcome['state']['label']==label
        rows.append(dict(case=name,session_id=context['session_id'],priority_class=context['priority_class'],label=label,
            preparation_ms=prep,consumer_ms=(data['consumer']['end_ns']-data['consumer']['begin_ns'])/1e6,model_median_ms=median))
    assert len(set(users))==1
    supports=result['actual_startup_contexts_matched_except_logon_session'] and all(v['label']==('fast' if v['case'].startswith('interactive') else 'slow') for v in rows)
    assert supports==result['service_slow_interactive_fast_condition_supported']
    output=dict(task_xml_and_native_exits_verified=True,full_work_identity_verified=True,all_four_windows=rows,
        service_slow_interactive_fast_condition_supported=supports,root_mechanism_identified=False,
        bindings={f.name:sha(f) for f in (Path(__file__),HERE/'result01.json',HERE/'plan01.json',HERE/'transport01.json')})
    with (HERE/'verification01.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output,indent=2))
