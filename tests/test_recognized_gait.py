"""Accepted footprints keep usable spatial/time measurements despite later merges."""
from copy import deepcopy
import pytest
from reporting.recognized_gait import recognized_gait


def sample():
    return dict(event_publications=[dict(event_id=str(i), epoch=0, contact_id=i, touch_sample=100+500*i, active=True)
                                    for i in range(3)],
                landing_positions_m={'0': .2, '1': .7, '2': 1.2},
                contacts=[dict(id=i, epoch=0, touch_s={'value': .5*i, 'valid': True}, start=.5*i,
                               end=.5*i+.3, exclusion='unresolved_fragment_join',
                               landing_reference={'valid':True,'value':.2+.5*i,'sample':100+500*i,'basis':'first_observed_contact_center_v1'},
                               contact_s={'valid': False,'value': None,'missing_reason':'competing_source'}) for i in range(3)],
                steps=[], cycles=[], issues=[], stops=[])


def test_recognized_footprints_keep_intervals_when_strict_stance_failed():
    s=sample();before=deepcopy(s);r=recognized_gait(s)
    assert s==before
    assert r['recognized_steps']==3 and r['interval_count']==2
    assert r['mean_step_m']==pytest.approx(.5) and r['speed_m_s']==pytest.approx(1.)
    assert r['cadence_per_min']==pytest.approx(120.)
    assert all(row['contact_s'] is None and row['observed_span_s']==pytest.approx(.3) for row in r['rows'])
    assert r['mean_contact_s'] is None


def test_unobserved_release_is_never_filled_with_zero_or_next_touch():
    s=sample();s['contacts'][1]['end']=None
    r=recognized_gait(s)
    assert r['rows'][1]['contact_s'] is None
    assert r['interval_count']==2


def test_retracted_candidate_is_not_recognized():
    s=sample();s['event_publications'].append({**s['event_publications'][1],'revision':2,'active':False})
    s['contacts'][1]['candidate_outcome']='associated_fragment'
    r=recognized_gait(s)
    assert r['recognized_steps']==2 and r['interval_count']==1


@pytest.mark.parametrize('boundary',['epoch','gap','stop','simultaneous'])
def test_recognized_intervals_never_bridge_known_boundary(boundary):
    s=sample()
    if boundary=='epoch':s['event_publications'][1]['epoch']=1
    elif boundary=='gap':s['issues']=[{'time_s':.3,'code':'frame_gap'}]
    elif boundary=='stop':s['stops']=[{'start_s':.1,'end_s':.4}]
    else:s['event_publications'][1]['touch_sample']=100
    r=recognized_gait(s)
    assert r['rows'][1]['step_time_s'] is None
    assert r['rows'][1]['step_length_m'] is None


def test_running_observed_span_is_explicit_estimate():
    s=sample();c=s['contacts'][0];c.pop('start');c.pop('end')
    c.update(observed_start_s=0.,observed_end_s=.15)
    row=recognized_gait(s)['rows'][0]
    assert row['contact_s'] is None and row['observed_span_s']==.15
    assert row['contact_basis']=='遮挡跨度，非单脚接触'


def test_export_keeps_recognized_rows_and_estimation_labels():
    from tests.test_overground_walking import processor, walk, CONTACTS
    from reporting.excel import build_report_workbook
    p=processor(8,stop_type='Software command');walk(p,CONTACTS,2400)
    r=p.build_report('manual')
    book=build_report_workbook(r, include_recognized=True)
    sheet=book['已识别脚印测量']
    data=recognized_gait(r.walking_summary)
    assert sheet.max_row==data['recognized_steps']+1
    assert sheet.cell(2,8).value=='完整边界'
    assert sheet.cell(2,9).value=='首次落脚'
