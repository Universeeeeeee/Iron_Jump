"""Count/edge inventory with explicit duplicate-label ambiguity; no profiler timing."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def grouped(rows):
    groups=defaultdict(list)
    for row in rows:groups[json.dumps(row['function'],sort_keys=True)].append(row)
    return {k:dict(function=v[0]['function'],records=len(v),calls=sum(x['calls'] for x in v),ambiguous=len(v)>1) for k,v in groups.items()}

if __name__=='__main__':
    raw=HERE/'runs/evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());plan=read(HERE/'plan01.json');assert all(sha(raw/n)==v for n,v in plan['sources'].items());cases={};records={}
    for name in plan['cases']:
        r=read(raw/'runs'/name/'result.json');assert r['complete'] and not r['errors'] and r['full_original_semantics_exact'] and r['ROI_frames']==plan['raw_after_last']-plan['raw_first']
        records[name]=r;cases[name]=grouped(r['profile_rows'])
    a,b=plan['cases'];project=lambda f:f.get('file','').startswith(('engine/','hardware/'))
    project_keys={k for k,v in cases[a].items() if project(v['function'])}|{k for k,v in cases[b].items() if project(v['function'])}
    differences=[dict(label=json.loads(k),left=cases[a].get(k),right=cases[b].get(k)) for k in cases[a].keys()|cases[b].keys() if cases[a].get(k)!=cases[b].get(k)]
    edges=[];targets={'array_equal','all','any','review_group_sources','assigned_sources','ownership_record'}
    for r in records[a]['profile_rows']:
        for callee in r['callees']:
            if callee['function']['name'] in targets:edges.append(dict(caller=r['function'],callee=callee['function'],calls=callee['calls']))
    result=dict(ROI_frames=records[a]['ROI_frames'],reports_equal=records[a]['report_sha256']==records[b]['report_sha256'],
                project_named_counts_equal=all(cases[a].get(k)==cases[b].get(k) and not cases[a].get(k,{}).get('ambiguous',True) for k in project_keys),
                all_grouped_count_differences=differences,ambiguous_labels={n:[v for v in rows.values() if v['ambiguous']] for n,rows in cases.items()},
                project_inventory=sorted([v for v in cases[a].values() if project(v['function'])],key=lambda x:x['calls'],reverse=True),selected_edges=edges,
                limits=['CProfile changes execution and allocation. Timings deliberately not exported; counts do not rank CPU/GIL cost.','Generated functions may share file/line/name; aggregate counts preserve all records but cannot assign each constructor to a type.','Python/C interface call edges are not complete native stacks or natural owner evidence.','Only these new fixed synchronous runs; no old GUI or slow/fast run is reclassified.'],actual_load_disturbance_pass=False,primary_root_identified=False)
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:result[k] for k in ('reports_equal','project_named_counts_equal','all_grouped_count_differences','ambiguous_labels')},indent=2))
