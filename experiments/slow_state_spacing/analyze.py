"""All six windows, including intermediate/missing states; no fitted gap threshold."""
import hashlib
import json
from pathlib import Path
from classify import state,spacing_quality
from verify import check,identity

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
if __name__=='__main__':
    p=read(HERE/'plan01.json');root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest['files'].items())
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    status=read(root/'runs/status.json');rows=[];reference=identity(read(HERE/'reference01.json'))
    for c in p['schedule']:
        recordpath=root/'runs'/(c['id']+'.record.json')
        if not recordpath.exists():rows.append(dict(id=c['id'],not_attempted=True));continue
        record=read(recordpath)
        if not record['complete'] or record['errors'] or record['child_still_running']:
            rows.append(dict(id=c['id'],failed=True,record=record));continue
        r=read(root/'runs'/c['id']/'result.json');assert check(p,r)['pass_all'] and identity(r)==reference
        label=state(r,p['state_rules']);quality=spacing_quality(record['spacing'],p['spacing_rules']) if c['gap_seconds'] is not None else None
        rows.append(dict(id=c['id'],state=label,spacing_quality=quality,
            model_open_ms=(r['model']['open_end_ns']-r['model']['open_begin_ns'])/1e6,errors=record['errors'],complete=True))
    by={r['id']:r for r in rows};transitions=[]
    for previous,current in [('short01','long01'),('short03','long02')]:
        a,b=by[previous],by[current];observed=a.get('complete',False) and b.get('complete',False)
        q=b.get('spacing_quality') or {}
        transitions.append(dict(previous=previous,current=current,
            observed_fast_to_slow=observed and a['state']['label']=='fast' and b['state']['label']=='slow',
            qualified_spacing=q.get('spacing_pass',False) and q.get('long_gap_quiet_and_AC',False)))
    complete=status['complete'] and not status['errors'] and all(r.get('complete',False) for r in rows)
    supports=complete and all(v['observed_fast_to_slow'] and v['qualified_spacing'] for v in transitions)
    supports=supports and by['short02'].get('state',{}).get('label')=='fast' and by['short03'].get('state',{}).get('label')=='fast'
    result=dict(all_fixed_windows_complete=complete,cases=rows,transitions=transitions,
        controlled_five_minute_condition_supported=supports,
        conclusion='Repeated fast-to-slow transitions after the controlled five-minute interval support this condition in this fixed-work fixture.' if supports else 'This fixed budget does not establish the proposed five-minute recurrence condition. Other idle durations or mechanisms remain unknown.',
        limits=['No native hardware frequency, instruction, cache ormemory mechanism identified.','System aggregate quiet does not prove no per-core competitor or thermal change.',
            'No GUI orSDK input; positive spacing result cannot be called a formal real-time fix.','No additional windows, threshold fitting, warmup removal orfailure substitution.'],
        old_calibration_upgraded=False,root_mechanism_confirmed=False,
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),analysis_sha256=sha(Path(__file__)),archive_sha256=sha(HERE/'runs/evidence01.zip')))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
