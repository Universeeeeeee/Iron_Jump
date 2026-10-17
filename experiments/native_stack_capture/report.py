"""Reproduce calibration acceptance from preserved raw local/Windows evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from analyze import HERE, PLAN, quality, read


def independent_scan(case, summary=None):
    summary=case/'tracerpt_summary.txt' if summary is None else summary
    text=summary.read_text(encoding='utf-8-sig')
    lost=re.search(r'Total Events\s+Lost\s+(\d+)',text)
    if not lost: raise ValueError('Unrecognized tracerpt summary')
    rows={}
    for line in text.splitlines():
        m=re.match(r'^\|\s*(\d+)\s+(\w+)\s+0\s+(\w+)\s+(\d+)\s+\{([\w-]+)\}',line)
        if m:
            count,name,opcode,version,guid=m.groups()
            rows[guid,opcode,int(version)]=int(count)
    meta=read(case/'decoded/metadata.json')
    checks={}
    for guid,op,version,decode_op in [('def2fe46-7bd6-4b80-bd94-f57fe20d0ce3','Stack',2,32),
                                     ('ce1dbfb4-137e-4da6-87b0-3f59aa102cbc','SampleProf',2,46),
                                     ('3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c','36',5,36),
                                     ('3d6fa8d1-fe05-11d0-9dda-00c04fd7ba7c','ReadyThread',2,50)]:
        native=sum(n for shape,n in meta['shapes'].items() if shape.startswith(f'{guid}/{decode_op}/v{version}/'))
        external=rows.get((guid,op,version),0)
        checks[op]=dict(reader=native,tracerpt=external,equal=native==external)
    return dict(events_lost=int(lost.group(1)),counts=checks,
                passed=int(lost.group(1))==0 and all(v['equal'] for v in checks.values()),
                summary_sha256=hashlib.sha256(summary.read_bytes()).hexdigest())


def main(output):
    cases={}
    names=['cpu_probe02','wait_probe01']+[f'{m}_pair{i}_{s}' for m in ('cpu','wait') for i in range(1,4) for s in ('off',m)]
    for name in names:
        folder=HERE/'runs'/name
        r=quality(folder)
        if r['mode']!='off':
            r['independent_scan']=independent_scan(folder)
            r['quality_pass']=r['quality_pass'] and r['independent_scan']['passed']
        cases[name]=r
    pairs={}
    for mode in ('cpu','wait'):
        pairs[mode]=[]
        for i in range(1,4):
            off,on=[cases[f'{mode}_pair{i}_{s}'] for s in ('off',mode)]
            def total(result,key):return sum(t[key] for role,t in result['threads'].items() if role.startswith('cpu'))
            changes={key:total(on,key)/total(off,key)-1 for key in ('work','cpu_s','cycles')}
            # Symmetric gates; no acceptance of an apparent speed-up as "negative overhead".
            limits=dict(work=PLAN['gates']['synthetic_pair_work_relative_change_max'],
                        cpu_s=PLAN['gates']['synthetic_pair_cpu_relative_change_max'],
                        cycles=PLAN['gates']['synthetic_pair_cycles_relative_change_max'])
            pairs[mode].append(dict(pair=i,relative_changes=changes,
                                    perturbation_pass=all(abs(changes[k])<=limits[k] for k in changes),
                                    trace_quality_pass=on['quality_pass']))
    accepted={m:all(p['perturbation_pass'] and p['trace_quality_pass'] for p in pairs[m]) for m in pairs}
    result=dict(base_commit=PLAN['base_commit'],scope=PLAN['scope'],plan_sha256=hashlib.sha256((HERE/'plan.json').read_bytes()).hexdigest(),
                cases=cases,pairs=pairs,synthetic_tool_qualification_pass=accepted,
                quantitative_field_attribution_ready=False,
                rejected_attempts=['cpu_probe01: incorrect TOKEN_PRIVILEGES alignment, privilege setup failed before fixture; owned WPR stopped, interval not changed',
                                   'symbols initial image opcode omitted 10, then device paths unresolved; both rejected, QueryDosDevice mapping used in symbols03',
                                   'CPU clock mean of wide ctypes brackets rejected; bounds verified against independent ProcessTrace UTC conversion',
                                   'OldThreadID CSwitch stack join rejected; delivered payload identifies NewThreadID; preceding wait paired explicitly'])
    with output.open('x') as stream:json.dump(result,stream,indent=2)
    for m in pairs:
        print(m,'qualified',accepted[m])
        for p in pairs[m]:print(p)
    for name,r in cases.items():
        if r['mode']=='off':continue
        print(name,r['quality_checks'],r['independent_scan']['passed'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();main(a.output)
