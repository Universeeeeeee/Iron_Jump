"""Independent review of derived P1 rows and Windows full-integrity outputs."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    result=read(HERE/'result01.json');inventory=read(HERE/'inventory01.json')
    assert len(result['cases'])==len(inventory['cases'])==4
    integrity=[]
    for row in result['cases']:
        name=row['case'];proof=read(HERE/'integrity'/(name+'.json'))
        assert proof['integrity_passed'] and proof['name'].startswith(name)
        assert proof['active_publications']==row['active_publications']==row['active_publications_painted']==11
        assert proof['report_touch_count']==row['algorithm_touch_count']==11
        assert proof['raw_frames_with_preparation']==row['raw_frames_with_preparation']
        assert proof['formal_archived_frames']==row['formal_archive_frames']
        assert proof['one_reader_final_drained_sdk_stopped']
        assert row['field_integrity_pass'] and 990<=row['actual_receipt_rate_fps']<=1010
        integrity.append(dict(case=name,proof_sha256=sha(HERE/'integrity'/(name+'.json'))))
    severe={v['case'] for v in result['cases'] if v['severe_real_backlog']}
    assert severe=={'20261017_213018','20261017_214905'}
    assert all(v['receipt_to_paint_max_ms']>250 or v['observed_pending_max']>250 for v in result['cases'])
    out=dict(four_full_integrity_reviews_pass=True,actual_1000Hz_input_verified=True,
        severe_real_backlog_cases=sorted(severe),all_four_exceed_old_candidate_FIFO_or_display_target=True,
        candidate_AB_started=False,formal_program_changed=False,human_or_device_test_started=False,
        goal_complete=False,integrity=integrity,
        bindings={p.name:sha(p) for p in (Path(__file__),HERE/'result01.json',HERE/'inventory01.json',HERE/'onsite_observations01.json')})
    with (HERE/'verification01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
