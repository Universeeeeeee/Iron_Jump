import hashlib
import json

def verify_record(boundaries,probes):
    rows=boundaries['rows']
    labels=['before_open','original_open','after_open','original_close','after_close']
    if boundaries['open_count']!=1 or boundaries['close_count']!=1 or [r['label'] for r in rows]!=labels:raise ValueError('Incomplete stage sequence')
    if len({r['tid'] for r in rows})!=1:raise ValueError('Not the same model thread')
    if not all(r['end_ns']>=r['begin_ns'] for r in rows) or not all(a['end_ns']<=b['begin_ns'] for a,b in zip(rows,rows[1:])):raise ValueError('Invalid stage ordering')
    if not all(r['success'] for r in rows if r['label'].startswith('original_')):raise ValueError('Original operation failed')
    out={}
    for row in (rows[0],rows[2],rows[4]):
        p=probes[row['label']];runs=p['rows']
        if not p['complete'] or p['errors'] or not p['memory_released']:raise ValueError('Probe failed')
        if [v['iterations'] for v in runs]!=[8000000,32000000,32000000,8000000,8000000,32000000]:raise ValueError('Changed native work')
        if not all(v['result']==v['dependent_adds']==16*v['iterations'] and row['begin_ns']<=v['begin_ns']<v['end_ns']<=row['end_ns'] for v in runs):raise ValueError('Invalid native result')
        for a,b in zip(runs[::2],runs[1::2]):
            lo,hi=sorted([a,b],key=lambda v:v['iterations'])
            ratio=(hi['end_ns']-hi['begin_ns'])/(lo['end_ns']-lo['begin_ns'])
            if not 3.2<=ratio<=4.8:raise ValueError('Native scaling failed')
        out[row['label']]=dict(billion_adds_per_second=sum(v['dependent_adds'] for v in runs)/sum(v['end_ns']-v['begin_ns'] for v in runs),probe_wall_ms=(row['end_ns']-row['begin_ns'])/1e6)
    return dict(stages=out,original_open_ms=(rows[1]['end_ns']-rows[1]['begin_ns'])/1e6,original_close_ms=(rows[3]['end_ns']-rows[3]['begin_ns'])/1e6,same_model_tid=rows[0]['tid'],latency_qualification=False)

def verify_phases(folder):
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    b=read(folder/'boundaries.json');probes={}
    for row in b['rows']:
        if 'result_sha256' not in row:continue
        path=folder/row['label']/'result01.json'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['result_sha256']:raise ValueError('Changed native evidence')
        probes[row['label']]=read(path)
    return verify_record(b,probes)
