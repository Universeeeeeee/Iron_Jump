"""Four retained context launches; no inference from startup getters alone."""
import hashlib
import json
from pathlib import Path
from classify import state
from verify import check,identity

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
    p=read(HERE/'plan01.json');root=HERE/'runs/evidence01';manifest=read(root/'manifest01.json')
    assert all(sha(root/n)==v for n,v in manifest['files'].items())
    assert all(sha(HERE/n)==v for n,v in p['sources'].items())
    status=read(root/'runs/status.json');rows=[];reference=identity(read(HERE/'reference01.json'))
    for name in p['cases']:
        folder=root/'runs'/name
        if not (folder/'result.json').exists():rows.append(dict(id=name,missing=True));continue
        data=read(folder/'result.json');context=read(root/'runs'/(name+'.context.json'))
        exit_record=read(root/'runs'/(name+'.status.json'))
        assert exit_record['confirmed_exit'] and exit_record['observation_complete'] and exit_record['native_exit_code']==exit_record['managed_exit_code']==0
        assert check(p,data)['pass_all'] and identity(data)==reference
        assert context['pid']==data['process_before']['pid']
        rows.append(dict(id=name,state=state(data,p['state_rules']),context=context,
            expected_session_matches=context['session_id']==p['expected_session'][name],complete=True))
    complete=status['complete'] and len(rows)==4 and all(v.get('complete',False) for v in rows)
    contexts_match=complete and all(v['expected_session_matches'] for v in rows)
    if complete:
        contexts_match=contexts_match and len({v['context']['priority_class'] for v in rows})==1
        contexts_match=contexts_match and {v['context']['qpa'] for v in rows}=={'offscreen'}
        for kind in ('process','thread'):
            contexts_match=contexts_match and all(v['context'][kind]['success'] for v in rows)
            contexts_match=contexts_match and len({(v['context'][kind]['control_mask'],v['context'][kind]['state_mask']) for v in rows})==1
    supports=contexts_match and all(v['state']['label']==('slow' if v['id'].startswith('service') else 'fast') for v in rows)
    result=dict(all_four_complete=complete,actual_startup_contexts_matched_except_logon_session=contexts_match,cases=rows,
        service_slow_interactive_fast_condition_supported=supports,
        conclusion='The repeated launch-context contrast supports this condition in the fixed-work fixture.' if supports else 'No qualified repeated service-slow/interactive-fast contrast; the proposed condition remains unconfirmed.',
        limitations=['Logon mode changes more than a session number; no unique hardware mechanism follows.','Startup policy metadata does not certify continuous CPU delivery.',
            'Original fixed work has no GUI/SDK, and no real-time repair orCPU/GIL share is certified.','No retries, posthoc state thresholds oradditional cases.'],
        root_mechanism_identified=False,
        bindings=dict(plan_sha256=sha(HERE/'plan01.json'),analyzer_sha256=sha(Path(__file__)),archive_sha256=sha(HERE/'runs/evidence01.zip')))
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
