"""Time only the real consumer-side call chain, with decoded inputs ready."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback

from experiment import (HERE, ROOT, Decoder, digest, dump, feed_quality, pipeline,
                        recorded, synthetic, enabled)


def one(case,variant):
    if case.startswith('field_'):
        layout,raw,meta=recorded(case)
        mode='run' if case=='field_run_20261015_02' else 'walk'
    else:
        layout,raw=synthetic(case);meta=None;mode='run'
    decode_variant=('decode_full' if enabled(variant,'decode_full') else
                    'decode_segments' if enabled(variant,'decode_segments') else 'baseline')
    decoder=Decoder(layout,decode_variant)
    # This preparation represents the reader. Its CPU is explicitly excluded.
    frames=[replace(f,contact_bits=decoder.decode(f.wire_payload)) for f in raw]
    quality,session=pipeline(mode,layout,frames,variant,meta)
    wq,ws=pipeline(mode,layout,frames,'baseline',meta)
    for f in frames[:100]:feed_quality(wq,f)
    ws.halt()
    cpu=time.thread_time_ns();wall=time.perf_counter_ns()
    for f in frames:feed_quality(quality,f)
    session.halt()
    wall=time.perf_counter_ns()-wall;cpu=time.thread_time_ns()-cpu
    assert session.total_frames==len(frames)
    assert session.processor.last_sample==frames[-1].sample_index
    assert session.processor.finished_reason is None
    return {'case':case,'variant':variant,'cpu_ns':cpu,'wall_ns':wall,'frames':len(frames),
            'cpu_us_per_frame':cpu/len(frames)/1000,'wall_us_per_frame':wall/len(frames)/1000,
            'report_sha256':digest(asdict(session.build_report('manual'))),
            'accepted_frames':session.total_frames,'last_formal_sample':session.processor.last_sample,
            'scope':'Consumer-side quality/filter/processor/publication/stop-flush only. Decoding, input allocation and saving excluded. No Qt inbox/IPC/GUI/hardware.',
            'idle_hits':getattr(session.processor,'_exp_idle_hits',0)}


def paired(case,variant,label):
    folder=HERE/'consumer_benchmarks';folder.mkdir(exist_ok=True)
    pairs=[]
    for pair,order in enumerate((('baseline',variant),(variant,'baseline'),
                                 ('baseline',variant),(variant,'baseline'))):
        data={}
        for index,name in enumerate(order):
            out=folder/f'{label}_{case}_{pair}_{index}_{name}.json'
            cmd=[sys.executable,str(Path(__file__).resolve()),'one',case,name,str(out)]
            with out.with_suffix('.stdout').open('w') as stdout,out.with_suffix('.stderr').open('w') as stderr:
                subprocess.run(cmd,stdout=stdout,stderr=stderr,check=True)
            data[name]=json.loads(out.read_text())
        a,b=data['baseline'],data[variant]
        assert a['report_sha256']==b['report_sha256'],(case,variant,pair,'report')
        assert a['accepted_frames']==b['accepted_frames']
        pairs.append({'pair':pair,'order':order,'baseline':a,'candidate':b,
                      'cpu_reduction':1-b['cpu_ns']/a['cpu_ns']})
    values=[p['cpu_reduction'] for p in pairs]
    return {'case':case,'variant':variant,'pairs':pairs,'median_cpu_reduction':statistics.median(values),
            'positive_pairs':sum(x>0 for x in values)}


def main():
    if sys.argv[1]=='one':
        _,case,variant,path=sys.argv[1:]
        result=one(case,variant);dump(Path(path),result);print(json.dumps(result),flush=True)
        return
    label,variant=sys.argv[1:3]
    rows=[]
    for case in ('empty','sparse','cross','plateau','stress',
                 'field_run_20261015_02','field_walk_full_02'):
        row=paired(case,variant,label);rows.append(row)
        dump(HERE/f'{label}_consumer.json',{'complete':False,'results':rows})
        print(case,round(row['median_cpu_reduction']*100,2),row['positive_pairs'],flush=True)
    gate=any(r['median_cpu_reduction']>=.05 and r['positive_pairs']>=3 for r in rows)
    gate &= all(r['median_cpu_reduction']>=-.05 for r in rows)
    dump(HERE/f'{label}_consumer.json',{'complete':True,'results':rows,
         'consumer_cpu_gate':gate,'scope_correction':'CONSUMER_SCOPE_CORRECTION.md'})


if __name__=='__main__':
    try:main()
    except BaseException:
        traceback.print_exc();sys.exit(1)
