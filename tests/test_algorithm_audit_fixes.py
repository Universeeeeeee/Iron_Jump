"""Independent regression expectations for the seven algorithm audit findings."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from reporting.recognized_gait import recognized_gait
from tests.test_recognized_gait import sample
from tests.test_overground_walking import processor,walk,frame


def valid_sample():
    s=sample()
    for row in s['contacts']:
        row['contact_s']={'value':.3,'valid':True,'missing_reason':None}
        row['exclusion']=None
        row['landing_reference']={'valid':True,'value':s['landing_positions_m'][str(row['id'])],
                                  'sample':100+500*row['id'],'basis':'first_observed_contact_center_v1'}
    return s


def test_stop_is_retained_but_never_reintroduced_into_contact_mean():
    p=processor(3,stop_type='Software command')
    walk(p,[(100,2800,.35),(2600,3300,.95),(3100,3800,1.55),(3600,4300,2.15)],4500)
    s=p.build_report('manual').walking_summary;r=recognized_gait(s)
    assert r['recognized_steps']==4
    assert r['mean_contact_s']==pytest.approx(.7)
    assert r['contact_count']==3
    assert not r['rows'][0]['contact_included']


def test_uncertain_occupancy_span_is_not_a_single_foot_contact_estimate():
    s=valid_sample();s['contacts'][0].update(end=.4,contact_s={'value':None,'valid':False,'missing_reason':'competing_source'})
    r=recognized_gait(s)
    assert r['rows'][0]['contact_s'] is None
    assert r['rows'][0]['observed_span_s']==pytest.approx(.4)
    assert r['mean_contact_s']==pytest.approx(.3) and r['contact_count']==2


def test_unconfirmed_intervening_foot_keeps_span_but_not_a_single_step():
    s=valid_sample()
    s['contacts'].append(dict(id=99,epoch=0,start=.25,end=.29,confirmed=False,exclusion='short_contact',candidate_outcome='unresolved'))
    r=recognized_gait(s)
    assert r['recognized_steps']==3
    assert r['rows'][1]['interval_distance_m']==pytest.approx(.5)
    assert r['rows'][1]['step_length_m'] is None
    assert r['interval_count']==1


def test_resolved_nonstep_candidate_does_not_block_recognized_steps():
    s=valid_sample();s['contacts'].append(dict(id=99,epoch=0,start=.25,end=.251,confirmed=False,candidate_outcome='excluded_nonstep'))
    assert recognized_gait(s)['interval_count']==2


def test_legacy_running_valid_contacts_are_supported_without_invented_publications():
    s=valid_sample();s.pop('event_publications');s.pop('landing_positions_m')
    for c in s['contacts']:
        c.update(touch_sample=100+500*c['id'],candidate_outcome='confirmed_contact')
    before=deepcopy(s);r=recognized_gait(s)
    assert r['supported'] and r['recognized_steps']==3 and r['interval_count']==2
    assert s==before


def test_empty_authoritative_publications_do_not_resurrect_retracted_feet():
    s=valid_sample();s['event_publications']=[]
    assert recognized_gait(s)['recognized_steps']==0


@pytest.mark.parametrize('mode',['walk','run'])
def test_first_observation_reference_is_independent_of_confirmation_threshold(mode):
    from tests.test_overground_running import processor as running
    values=[]
    for threshold in (20,60,100):
        p=(processor if mode=='walk' else running)(3,stop_type='Software command',min_contact_time=threshold)
        for n in range(1100):
            groups=[(.20,.30+min(n-100,100)*.0016)] if 100<=n<400 else [(.80,1.06)] if 600<=n<900 else []
            p.process(frame(p.device.layout,n,groups,stream=p.device.stream_id))
        report=p.build_report('manual');s=getattr(report,'walking_summary',None) or report.running_summary
        r=recognized_gait(s);values.append(r['mean_step_m'])
        assert r['rows'][0]['position_sample']==100
    assert values==pytest.approx([values[0]]*3)


def test_history_converts_saved_centimetres_to_metres():
    from data.subject_store import SessionRecord
    from ui.views.history_view import _session_summary
    session=SessionRecord(1,None,'synthetic',None,'Sprint and Gait Test','{}',
        report_summary_json=json.dumps({'report_type':'gait','avg_stride':59.88,'avg_velocity':119.76}))
    assert _session_summary(session)=='平均步长 0.599m / 平均步速 1.198m/s'


def test_analysis_exposes_same_recognized_sample_set_and_values_as_ui():
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from ui.views.report_view import ReportView
    p=processor(3,stop_type='Software command')
    walk(p,[(100,2800,.35),(2600,3300,.95),(3100,3800,1.55),(3600,4300,2.15)],4500)
    report=p.build_report('manual');r=recognized_gait(report.walking_summary)
    package=ReportDataPackageBuilder().build(report,ReportContextInput(session_id=1,test_type='Sprint and Gait Test'))
    fact=next(f for f in package.scalar_facts if f.metric_code=='recognized_contact_time_s')
    assert fact.value==pytest.approx(r['mean_contact_s']) and fact.sample_count==r['contact_count']
    assert package.payload.recognized_measurements==r
    stats=[('平均接触时间','','')];ReportView._apply_recognized_stats(stats,report.walking_summary)
    assert stats[0][1]==f'{fact.value:.3f} s'


def test_legacy_estimated_touch_uses_same_clock_origin_as_observed_touches():
    s=valid_sample();s.pop('event_publications')
    s['contacts'][0]['touch_sample']=100
    s['contacts'][1]['touch_sample']=None
    s['contacts'][2]['touch_sample']=1100
    r=recognized_gait(s)
    assert [row['timestamp_s'] for row in r['rows']]==pytest.approx([.1,.6,1.1])
    assert r['rows'][1]['step_time_s']==pytest.approx(.5)


def test_legacy_walking_preserves_valid_position_without_new_optional_fields():
    s=dict(contacts=[dict(id=i,epoch=0,start=.5*i,end=.5*i+.3,confirmed=True,exclusion=None,
                         position_m=.2+.5*i) for i in range(3)],stops=[],issues=[])
    r=recognized_gait(s)
    assert r['recognized_steps']==3 and r['interval_count']==2
    assert r['mean_step_m']==pytest.approx(.5)
    assert r['mean_contact_s']==pytest.approx(.3)
