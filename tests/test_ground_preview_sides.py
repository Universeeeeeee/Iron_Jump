"""Configured first-foot hints change icons without changing measurement identity."""
from copy import deepcopy

import pytest

from engine.overground_session import OvergroundSession
from tests.test_ground_candidate_groups import make
from tests.test_ground_fast_footprints import frame
from ui.ground_track import GroundTrackPanel


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('starting,expected', [('Left', ['left','right','left']),
                                             ('Right', ['right','left','right']),
                                             ('Not defined', ['unknown']*3)])
def test_live_candidates_use_configured_first_foot_then_alternate(qtbot, mode, starting, expected):
    p = make(mode)
    p.config.starting_foot = starting
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    delivered = []
    session.visual.connect(delivered.append)
    session.visual.connect(panel.render_state)
    for n in range(900):
        groups = []
        for onset, low in [(100,40),(400,150),(700,250)]:
            if onset <= n < onset + 150:
                groups.append((low,low+20))
        session.on_frame(frame(p, n, groups))
        if n in (112,412,712):
            index = (n-112)//300
            assert panel.channel._feet[-1]['status'] == 'candidate'
            assert panel.channel._feet[-1]['side'] == expected[index]
            assert delivered[-1]['feet'][-1]['side'] == 'unknown'
            assert session.processor.active[-1].side == 'unknown'
    assert session.processor.reliable_touch_count == 3
    session.halt()


@pytest.mark.parametrize('starting,expected', [('Left','left'),('Right','right'),('Not defined','unknown')])
def test_uncertain_shape_keeps_manual_side_in_live_detail_and_history(qtbot, starting, expected):
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    state = {'positions_m':make('walk').positions, 'contact_bits':[0]*768, 'valid_bits':[1]*768,
             'timestamp_s':1, 'sample_index':1000, 'starting_foot':starting, 'next_foot_label':'B',
             'feet':[{'contact_id':0,'label':'A','side':'unknown','status':'confirmed',
                      'centroid_cm':52,'length_cm':None,'shape_valid':False}]}
    original = deepcopy(state)
    panel.render_state(state)
    assert panel.channel._feet[0]['side'] == expected
    assert panel.detail_channel._feet[0]['side'] == expected
    assert state == original
    summary = {'event_publications':[{'contact_id':0,'active':True}], 'landing_positions_m':{'0':.52},
               'contacts':[{'id':0,'label':'A','side':'unknown','start':0,'end':None,
                            'confirmed':True,'position_known':False,'exclusion':'unresolved_fragment_join'}]}
    saved = deepcopy(summary)
    panel.set_summary(summary)
    panel.render_state({**state,'feet':[]})
    assert panel.channel.history[0]['side'] == expected
    assert summary == saved
