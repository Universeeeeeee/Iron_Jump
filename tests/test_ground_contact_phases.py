from copy import deepcopy

import pytest

from engine.ground_contact_phases import analyse_contact_phases, ContactShapeRecorder
from engine.ground_metric_evidence import metric


POSITIONS = tuple(i * .01 for i in range(96))
PARAMS = dict(flat_confirm_ms=5, heel_confirm_ms=3, edge_stability_m=.005,
              heel_retreat_m=.02, platform_extent_tolerance_m=.02, count_tolerance=1)
CONTACT = dict(id=0, touch_sample=100, lift_sample=700, contact_s=metric(.6))


def trace(front_first=False):
    return [[100, 120, [[35, 40]] if front_first else [[20, 25]], None],
            [120, 140, [[25, 40]] if front_first else [[20, 35]], None],
            [140, 500, [[20, 40]], None], [500, 650, [[22, 40]], None],
            [650, 700, [[35, 40]], None]]


@pytest.mark.parametrize('front_first', [False, True])
def test_any_initial_contact_starts_timing_and_confirmation_is_not_boundary(front_first):
    result = analyse_contact_phases(CONTACT, trace(front_first), POSITIONS, 1, PARAMS)
    assert result['boundaries'] == {'platform_start': {'sample': 140, 'confirmed_sample': 144},
                                   'rear_exit_start': {'sample': 500, 'confirmed_sample': 502}}
    for code, expected in [('contact_phase_s', .04), ('foot_flat_s', .36), ('propulsive_phase_s', .2)]:
        assert result['metrics'][code]['value'] == pytest.approx(expected)
    assert sum(result['metrics'][x]['value'] for x in result['metrics'] if x.endswith('_percent')) == pytest.approx(100)


def test_repeated_rear_exits_keep_one_contact_and_use_final_exit():
    runs = trace()[:2] + [[140, 250, [[20, 40]], None], [250, 270, [[23, 40]], None],
        [270, 350, [[20, 40]], None], [350, 370, [[24, 40]], None],
        [370, 500, [[20, 40]], None]] + trace()[3:]
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert result['boundaries']['platform_start']['sample'] == 140
    assert result['boundaries']['rear_exit_start']['sample'] == 500
    assert result['contact_id'] == 0


def test_single_sample_expansion_does_not_replace_the_stable_platform():
    runs = trace(); runs[1:2] = [[120, 121, [[20, 55]], None], [121, 140, [[20, 35]], None]]
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert result['boundaries']['platform_start']['sample'] == 140


def test_late_one_beam_expansion_does_not_delay_an_already_full_platform():
    runs = trace()[:2] + [[140, 400, [[20, 40]], None], [400, 500, [[19, 40]], None]] + trace()[3:]
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert result['boundaries']['platform_start']['sample'] == 140
    assert result['boundaries']['rear_exit_start']['sample'] == 500


def test_single_initial_hole_uses_plateau_duration_weight_not_first_sample_count():
    runs = trace()[:2] + [[140, 141, [[20, 25], [27, 40]], None], [141, 400, [[20, 40]], None],
                         [400, 500, [[19, 40]], None]] + trace()[3:]
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert result['boundaries']['platform_start']['sample'] == 140


def test_whole_foot_translation_can_settle_before_final_rear_exit():
    runs = trace()[:2] + [[140, 300, [[20, 40]], None], [300, 500, [[30, 50]], None],
                         [500, 700, [[32, 50]], None]]
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert result['boundaries']['platform_start']['sample'] == 140
    assert result['boundaries']['rear_exit_start']['sample'] == 500


def test_unknown_transition_keeps_known_initial_phase_but_not_false_rear_exit():
    runs = trace()[:3] + [[500, 510, [[22, 40]], 'unobserved_shape'], [510, 700, [[24, 40]], None]]
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert result['metrics']['contact_phase_s']['valid']
    assert not result['metrics']['foot_flat_s']['valid']
    assert not result['metrics']['propulsive_phase_s']['valid']


def test_unknown_platform_boundary_does_not_erase_observed_final_exit():
    runs = trace(); runs[1][3] = 'shared_projection'
    result = analyse_contact_phases(CONTACT, runs, POSITIONS, 1, PARAMS)
    assert not result['metrics']['contact_phase_s']['valid']
    assert not result['metrics']['foot_flat_s']['valid']
    assert result['metrics']['propulsive_phase_s']['value'] == pytest.approx(.2)


def test_reverse_direction_and_run_length_encoding_preserve_times():
    forward = analyse_contact_phases(CONTACT, trace(), POSITIONS, 1, PARAMS)
    reverse = [[a, b, [[95-hi, 95-lo] for lo, hi in reversed(islands)], reason]
               for a, b, islands, reason in trace()]
    assert analyse_contact_phases(CONTACT, reverse, POSITIONS, -1, PARAMS)['metrics'] == forward['metrics']
    expanded = [[n, n+1, islands, reason] for a, b, islands, reason in trace() for n in range(a, b)]
    assert analyse_contact_phases(CONTACT, expanded, POSITIONS, 1, PARAMS)['metrics'] == forward['metrics']


def test_confirmation_window_changes_confirmation_not_event_time():
    a = analyse_contact_phases(CONTACT, trace(), POSITIONS, 1, PARAMS)
    b = analyse_contact_phases(CONTACT, trace(), POSITIONS, 1, {**PARAMS, 'flat_confirm_ms': 10, 'heel_confirm_ms': 8})
    assert a['metrics'] == b['metrics']
    assert b['boundaries']['rear_exit_start']['confirmed_sample'] == 507


def test_recorder_uses_local_foot_and_preserves_actual_islands():
    from types import SimpleNamespace
    foot = SimpleNamespace(low=20, high=40)
    other = SimpleNamespace(low=50, high=90)
    p = SimpleNamespace(active=[foot, other], _narrow_candidates=[], _ownership_groups=[],
                        device=SimpleNamespace(bad_indices=()))
    bits = bytearray(96)
    for lo, hi in [(20, 25), (35, 40), (50, 90)]:
        bits[lo:hi+1] = b'\x01' * (hi-lo+1)
    frame = SimpleNamespace(sample_index=100, contact_bits=bits, valid_bits=b'\x01'*96)
    recorder = ContactShapeRecorder(); recorder.observe(p, frame)
    assert recorder.streams[id(foot)][1] == [[100, 101, [[20, 25], [35, 40]], None]]
    assert (foot.low, foot.high) == (20, 40)


def test_merged_groups_union_owned_islands_without_overwriting_each_other():
    from types import SimpleNamespace
    contact = SimpleNamespace(id=0)
    groups = [dict(id=0, state='closed', recovery=dict(owner_id=0, source_ids=[0, 1]),
                   sources=[dict(source_id=0, joined_sample=100), dict(source_id=1, joined_sample=100)],
                   merged_group_ids=[1]),
              dict(id=1, state='merged', recovery=dict(owner_id=0, source_ids=[1]),
                   sources=[dict(source_id=1, joined_sample=100)], merged_group_ids=[])]
    before = deepcopy(groups)
    recorder = ContactShapeRecorder()
    recorder.groups = {0: [[100, 105, [[10, 14]], None]], 1: [[100, 105, [[20, 24]], None]]}
    runs = recorder.contact_runs(SimpleNamespace(_ownership_groups=groups), contact, 100, 105)
    assert runs == [[100, 105, [[10, 14], [20, 24]], None]]
    assert groups == before


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_processing_records_initial_candidate_and_preserves_event_boundaries(mode):
    from tests.test_ground_candidate_groups import make
    from tests.test_ground_fast_footprints import frame
    p = make(mode); p.config.starting_foot = 'Left'
    p.config.stop_type = 'Software command'
    for n in range(900):
        groups = ([(30, 30)] if 100 <= n < 102 else [(30, 35)] if 102 <= n < 120
                  else [(30, 50)] if 120 <= n < 500 else [(32, 50)] if 500 <= n < 650
                  else [(45, 50)] if 650 <= n < 700 else [])
        p.process(frame(p, n, groups))
    events, audit = deepcopy(p.touch_events), deepcopy(p.event_audit)
    contacts = deepcopy([vars(c) for c in p.contacts])
    summary = p.summary()
    assert p.touch_events == events and p.event_audit == audit
    assert [vars(c) for c in p.contacts] == contacts
    rows = summary['contact_phases']['contacts']
    assert rows and rows[0]['shape_runs'][0][0] == 100


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_real_processor_three_phase_history_uses_landing_direction_without_feedback(mode):
    from tests.test_ground_candidate_groups import make
    from tests.test_ground_fast_footprints import frame
    p = make(mode); p.config.starting_foot = 'Left'; p.config.stop_type = 'Software command'
    for n in range(2400):
        groups = []
        for i in range(3):
            t = n - i*800
            for a, b, islands, _ in trace():
                if a <= t < b:
                    groups.extend((lo+96*i, hi+96*i) for lo, hi in islands)
        p.process(frame(p, n, groups))
    events = deepcopy(p.touch_events)
    p.direction = 0
    s = p.summary()
    assert p.direction == 0 and p.touch_events == events
    assert s['contact_phases']['direction'] == 1
    first = s['contact_phases']['contacts'][0]
    assert first['boundaries']['platform_start']['sample'] == 140
    assert first['boundaries']['rear_exit_start']['sample'] == 500
    assert first['metrics']['foot_flat_s']['value'] == pytest.approx(.36)
    assert s['bilateral']['statistics']['propulsive_phase_s']['all']['count'] == 3
