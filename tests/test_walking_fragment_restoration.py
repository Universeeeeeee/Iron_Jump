"""Local attribution and visual publication have separate evidence lifetimes."""
from copy import deepcopy

import pytest

from tests.test_ground_candidate_groups import make, feed
from tests.test_ground_source_review import sequence


def test_both_rolling_split_ends_can_extend_while_each_overlaps_prior_blocked_bits():
    p = make('walk')
    for n in range(240):
        groups = [(40,60)] if 100 <= n < 200 else [(39,45),(55,61)] if n >= 200 else []
        feed(p,n,groups)
    assert len(p.contacts)==1 and p.reliable_touch_count==1
    assert not p.contacts[0].exclusion
    assert not any(i.get('scope')=='local_split' for i in p.issues)


def test_clear_hole_in_previous_envelope_cannot_anchor_a_new_fragment():
    p = make('walk')
    for n in range(200):feed(p,n,[(40,60)] if n>=100 else [])
    # The previous projection really has a hole. An envelope alone is not evidence.
    old=bytearray(p._previous_frame.contact_bits);old[46:55]=bytes(9)
    from dataclasses import replace
    p._previous_frame=replace(p._previous_frame,contact_bits=bytes(old))
    p.contacts[0].low,p.contacts[0].high=40,60
    groups=p._associate_inner_fragments([(39,44),(48,50),(56,61)])
    assert p.contacts[0].exclusion or len(groups)>1


def test_fully_attributed_late_fragment_restores_only_its_established_owner():
    p,_,events = sequence('walk')
    c=p.contacts[events[0]['contact_id']]
    assert c.exclusion is None and not c.has_unknown and c.position_known
    assert p.touch_events==events
    assert any(e['action']=='source_uncertainty_resolved' for e in p.event_audit)


@pytest.mark.parametrize('damage',['gap','far','wide'])
def test_unresolved_source_cannot_restore_owner(damage):
    p,_,_=sequence('walk',damage=damage)
    assert p.contacts[0].exclusion=='unresolved_fragment_join'
    assert not any(e['action']=='source_uncertainty_resolved' for e in p.event_audit)


def test_later_competing_source_reopens_uncertainty_without_retracting_touch():
    p,_,events=sequence('walk',long_source=True)
    assert p.contacts[0].exclusion=='unresolved_fragment_join'
    assert p.touch_events==events
    assert any(a==400 for a,b,e in p._ownership_barriers())


def test_initial_multi_source_recovery_cannot_be_relabelled_as_known_shape():
    p,_,_=sequence('walk',recovered=True)
    assert p.contacts[0].exclusion=='unresolved_fragment_join'
    assert not p.contacts[0].position_known


def test_touch_glyph_survives_uncertain_shape_but_not_an_explicit_retraction():
    p=make('walk')
    for n in range(500):
        groups=[(40,60)] if 100<=n<400 else []
        if 220<=n<250:groups += [(65,65)]
        if 250<=n<400:groups=[(40,65)]
        feed(p,n,groups)
    frames=[f for f in p.timeline if .15<=f['timestamp_s']<.28]
    assert frames
    glyphs=[foot for f in frames for foot in f['feet'] if foot['contact_id']==0]
    assert glyphs and all(foot['status']=='confirmed' for foot in glyphs)
    assert all(not foot['shape_valid'] for foot in glyphs)
    assert all(foot['side']=='unknown' and foot['length_cm'] is None for foot in glyphs)
    before=deepcopy(p.touch_events)
    p.contacts[0].candidate_outcome='associated_fragment';p._sync_touch_publications()
    assert before[0]['active'] and not p.touch_events[0]['active']
    from hardware.sensor_frame import SensorFrame
    f=SensorFrame('groups',p.device.layout,550,550,551,bytes(768),b'\x01'*768,b'')
    p.active=[p.contacts[0]];p._record_visual(f)
    assert p.timeline[-1]['feet'][0]['status']=='candidate'


def test_restoration_does_not_erase_an_independent_bad_beam_reason():
    p,_,_=sequence('walk')
    owner=p.contacts[0];owner.exclusion='masked_contact_boundary';owner.has_unknown=True
    p._restore_attributed_owner(p._ownership_groups[0])
    assert owner.exclusion=='masked_contact_boundary' and owner.has_unknown


def test_uncertain_published_touch_is_actually_painted(qtbot, tmp_path):
    from ui.ground_track import GroundChannelWidget
    from qtpy.QtWidgets import QApplication
    widget=GroundChannelWidget();qtbot.addWidget(widget)
    widget.resize(260,700);widget.show()
    state={'positions_m':make('walk').positions, 'contact_bits':[0]*768, 'valid_bits':[1]*768,
           'feet':[{'contact_id':0,'status':'confirmed','side':'unknown','centroid_cm':52,
                    'length_cm':None,'shape_valid':False}]}
    widget.render_state(state);QApplication.processEvents()
    image=widget.grab().toImage()
    assert image.save(str(tmp_path/'published_unknown_shape.png'))
    lane=widget.lane_rect()
    gray=sum(1 for x in range(int(lane.left()),int(lane.right())) for y in range(int(lane.top()),int(lane.bottom()))
             if 140<image.pixelColor(x,y).red()<230 and 160<image.pixelColor(x,y).blue()<230)
    assert gray>100  # Rasterized foot pixels, not just a widget-state getter.
    state['feet'][0]['status']='candidate';widget.render_state(state);QApplication.processEvents()
    hidden=widget.grab().toImage()
    gray_hidden=sum(1 for x in range(int(lane.left()),int(lane.right())) for y in range(int(lane.top()),int(lane.bottom()))
             if 140<hidden.pixelColor(x,y).red()<230 and 160<hidden.pixelColor(x,y).blue()<230)
    assert gray_hidden<gray-100


def test_published_landing_history_survives_unknown_lift_and_honours_retraction(qtbot):
    from ui.ground_track import GroundTrackPanel
    panel=GroundTrackPanel();qtbot.addWidget(panel)
    state={'positions_m':make('walk').positions,'contact_bits':[0]*768,'valid_bits':[1]*768,
           'timestamp_s':1,'feet':[]}
    summary={'event_publications':[{'contact_id':0,'active':True}], 'landing_positions_m':{'0':.52},
             'contacts':[{'id':0,'start':0,'confirmed':True,'position_known':False,
                          'exclusion':'unresolved_fragment_join','end':None}]}
    panel.render_state(state);panel.set_summary(summary)
    assert len(panel.channel.history)==1 and panel.channel.history[0]['centroid_cm']==52
    summary['event_publications'][0]['active']=False;summary['landing_positions_m']={}
    panel.set_summary(summary)
    assert not panel.channel.history
    summary['event_publications'][0]['active']=True;summary['landing_positions_m']={'0':.52}
    summary['event_publications'][0]['published_sample']=200
    state['sample_index']=150;panel.render_state(state);panel.set_summary(summary)
    assert not panel.channel.history
    state['sample_index']=250;panel.render_state(state);panel.set_summary(summary)
    assert panel.channel.history
    state['timestamp_s']=-.1;panel.render_state(state);panel.set_summary(summary)
    assert not panel.channel.history


def test_remote_healthy_anchor_cannot_change_a_growing_foot_position_votes():
    values=[]
    for anchor in (False,True):
        p=make('walk')
        for n in range(400):
            groups=[(40,60)] if anchor and 20<=n<350 else []
            if 100<=n<300:
                groups += [(200,200 if n<120 else 203 if n<140 else 209)]
            feed(p,n,groups)
        foot=next(c for c in p.contacts if round(c.start*1000)==100)
        values.append((foot.position,list(foot.positions)))
    assert values[0]==values[1]


def test_running_published_touch_also_survives_uncertain_shape_without_metric_repair(qtbot):
    from ui.ground_track import GroundTrackPanel
    p,_,events=sequence('run',long_source=True)
    assert p.contacts[0].problem=='unresolved_fragment_join'
    assert p.touch_events==events and len(events)==1
    uncertain=[f for f in p.timeline if .45<f['timestamp_s']<.5]
    assert uncertain
    assert all(any(foot['status']=='confirmed' and not foot['shape_valid'] and foot['length_cm'] is None
                   for foot in f['feet'] if foot['contact_id']==0) for f in uncertain)
    summary=p.summary();assert summary['valid_contact_durations']==0
    panel=GroundTrackPanel();qtbot.addWidget(panel)
    panel.render_state(p.timeline[-1]);panel.set_summary(summary)
    assert len(panel.channel.history)==1
    assert panel.channel.history[0]['side']=='unknown'
    assert panel.channel.history[0]['centroid_cm']==pytest.approx(52)
