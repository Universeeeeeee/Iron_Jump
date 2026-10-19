"""Three known threads created and joined between endpoint enumerations."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/native_stack_capture'))
sys.path.insert(0,str(ROOT/'experiments/thread_accounting_controls'))
from winapi import anchor,current_thread
from inventory02 import Inventory,enumerate_timed

def main(a):
    a.output.mkdir(parents=True,exist_ok=False);plan=json.loads((HERE/'plan01.json').read_text());result=dict(pid=os.getpid(),synthetic_only=True,threads=[],errors=[]);inv=None;workers=[]
    try:
        result['start']=anchor();inv=Inventory();result['enumeration_before']=enumerate_timed(inv)
        for ordinal in range(plan['thread_count']):
            row=dict(ordinal=ordinal);result['threads'].append(row)
            def work():
                try:
                    row['before']=current_thread();deadline=time.perf_counter()+plan['thread_seconds'];blocks=0
                    while time.perf_counter()<deadline:
                        assert sum(range(10000))==49995000;blocks+=1
                    row['blocks']=blocks;row['after']=current_thread()
                except BaseException as exc:row['error']=repr(exc)
            t=threading.Thread(target=work);workers.append(t);t.start();t.join(5)
            row['joined']=not t.is_alive();assert row['joined'] and 'error' not in row
        result['enumeration_after']=enumerate_timed(inv);result['end']=anchor()
        assert all(x['before']['tid'] not in result['enumeration_before']['tids'] and x['before']['tid'] not in result['enumeration_after']['tids'] for x in result['threads'])
        result['complete']=True
    except BaseException as exc:result['errors'].append(repr(exc))
    finally:
        for t in workers:t.join(5)
        result['workers_alive']=any(t.is_alive() for t in workers)
        if inv:
            try:inv.close();result['handles_closed']=not inv.handles
            except BaseException as exc:result['errors'].append(repr(exc))
        with (a.output/'fixture.json').open('x') as f:json.dump(result,f,indent=2)
    return int(bool(result['errors']) or result['workers_alive'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--seconds',type=float);raise SystemExit(main(p.parse_args()))
