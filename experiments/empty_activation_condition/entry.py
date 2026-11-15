"""Common launch context audit; empty activation exits before loading original work."""
import json
import os
from pathlib import Path
import runpy
import sys
import time
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
if __name__=='__main__':
    name,kind=sys.argv[1:];plan=json.loads((HERE/'plan01.json').read_text());assert any(v['id']==name and v['kind']==kind for v in plan['steps'])
    begin=time.perf_counter_ns();cpu=time.process_time_ns();output=HERE/'runs'/(name+'.context.json');original=list(sys.argv)
    try:
        sys.argv=['read_context.py',str(output)]
        runpy.run_path(str(ROOT/'experiments/qos_context_review/read_context.py'),run_name='__main__')
    finally:sys.argv=original
    context=json.loads(output.read_text());assert context['session_id']==plan['expected_session'][name]
    if kind=='empty':
        prohibited=[n for n in sys.modules if n.split('.')[0] in ('numpy','cv2','mediapipe','PySide6','qtpy','vision','engine','hardware')]
        result=dict(pid=os.getpid(),complete=not prohibited,prohibited_modules=prohibited,begin_ns=begin,end_ns=time.perf_counter_ns(),
            entry_process_cpu_ns=time.process_time_ns()-cpu,total_process_cpu_ns=time.process_time_ns(),
            scope='Common Python/context startup only; no original compute, model, GUI ordevice. PowerShell/task startup overhead exists in both logon types.')
        with (HERE/'runs'/(name+'.empty.json')).open('x') as f:json.dump(result,f,indent=2)
        assert result['complete'] and result['total_process_cpu_ns']<=plan['empty_process_CPU_max_ns']
        raise SystemExit(0)
    assert kind=='work'
    sys.path.insert(0,str(HERE));import workload
    code=workload.child(name)
    if code==0:
        from verify import check,identity
        result=json.loads((HERE/'runs'/name/'result.json').read_text());reference=json.loads((HERE/'reference01.json').read_text())
        assert check(plan,result)['pass_all'] and identity(result)==identity(reference)
    raise SystemExit(code)
