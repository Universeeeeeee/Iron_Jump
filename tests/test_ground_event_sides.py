"""Confirmed footfall order, rather than shape certainty, defines side."""
import pytest
from copy import deepcopy

from tests.test_walking_immature_coalescence import replay


def test_recovered_walking_footprints_keep_configured_alternating_sides():
    p = replay(kind='single')
    s = p.summary()
    assert [r['side'] for r in s['footfalls']] == ['left', 'right', 'left']
    assert not s['contacts'][0]['position_known']
    assert s['contacts'][0]['touch_sample'] == 220
    assert s['contacts'][0]['lift_sample'] == 500


def event(cid, sample, active=True, revision=1):
    return dict(contact_id=cid, epoch=0, touch_sample=sample, active=active, revision=revision)


def test_revision_and_late_publication_recompute_event_order_not_contact_ids():
    from engine.footfall_sides import event_sides
    events = [event(9, 500), event(3, 100), event(7, 300)]
    assert event_sides(events, 'Left', []) == {3: 'left', 7: 'right', 9: 'left'}
    events.append(event(7, 300, False, 2))
    assert event_sides(events, 'Left', []) == {3: 'left', 9: 'right'}
    assert event_sides(events, 'Right', []) == {3: 'right', 9: 'left'}


@pytest.mark.parametrize('code', ['frame_gap', 'invalid_sample', 'data_timeout', 'disconnected', 'counter_reset'])
def test_capture_break_preserves_previous_labels_but_does_not_guess_missing_steps(code):
    from engine.footfall_sides import event_sides
    events = [event(0, 100), event(1, 400), event(2, 700)]
    assert event_sides(events, 'Left', [{'code': code, 'sample': 400}]) == {
        0: 'left', 1: 'right', 2: 'unknown'}


def test_local_shape_issues_do_not_disable_confirmed_event_alternation():
    from engine.footfall_sides import event_sides
    events = [event(0, 100), event(5, 400), event(9, 700)]
    issues = [{'code': 'ambiguous_contacts', 'sample': 110},
              {'code': 'unresolved_fragment_join', 'sample': 450}]
    assert list(event_sides(events, 'Left', issues).values()) == ['left', 'right', 'left']
    assert set(event_sides(events, 'Not defined', issues).values()) == {'unknown'}


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_live_and_report_sides_use_same_events_even_if_shape_identity_is_unknown(mode):
    from tests.test_ground_bilateral import measured
    from data.subject_store import _report_detail, _report_from_detail
    p = measured(mode)
    # Shape validity can change without retracting the known landing event.
    for c in p.contacts:
        c.side = 'unknown'
    p._identity_known = False
    s = p.summary()
    assert [r['side'] for r in s['contacts']] == ['left', 'right'] * 4
    assert [r['side'] for r in s['steps']] == ['right', 'left', 'right', 'left', 'right', 'left', 'right']
    report = _report_from_detail(_report_detail(p.build_report('manual')))
    result = report.walking_summary if mode == 'walk' else report.running_summary
    assert result['bilateral']['statistics']['contact_time_s']['left']['count'] == 4
    p.active = [p.contacts[-1]]
    assert p.visual_feet()[0]['side'] == 'right'


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_side_outputs_do_not_mutate_detection_or_event_state(mode):
    from tests.test_ground_bilateral import measured
    p = measured(mode)
    before = deepcopy([vars(c) for c in p.contacts])
    events, audit = deepcopy(p.touch_events), deepcopy(p.event_audit)
    p.summary()
    p.visual_feet()
    p.summary()
    assert [vars(c) for c in p.contacts] == before
    assert p.touch_events == events
    assert p.event_audit == audit


def test_live_display_respects_unknown_after_capture_break(qtbot):
    from ui.ground_track import GroundTrackPanel
    from tests.test_ground_candidate_groups import make
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    panel.render_state({'positions_m': make('walk').positions, 'contact_bits': [0]*768,
        'valid_bits': [1]*768, 'timestamp_s': 1, 'starting_foot': 'Left',
        'feet': [{'contact_id': 1, 'label': 'A', 'side': 'unknown', 'side_authoritative': True,
                  'status': 'confirmed', 'centroid_cm': 52, 'length_cm': None, 'shape_valid': False}]})
    assert panel.channel._feet[0]['side'] == 'unknown'
