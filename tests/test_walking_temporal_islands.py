"""Clear beams separate observations; proximity alone never establishes an owner."""
from dataclasses import replace

import pytest

from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout, SensorSegment
from hardware.walking_preflight import PreparedDevice
from tests.test_overground_walking import processor, frame


def replay(trajectory, *, filtered=False, reverse=False, end=650):
    p = processor(3, stop_type='Software command', starting_foot='Left')
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(end):
        bits = bytearray(len(p.positions))
        for low, high in trajectory(n):
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        if reverse:
            bits.reverse()
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        for measured in optical.feed(raw) if filtered else [raw]:
            p.process(measured)
        assert raw.contact_bits == bytes(bits)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    return p


@pytest.mark.parametrize('clear_beams', [1, 2, 3])
def test_clear_beams_remain_separate_raw_islands(clear_beams):
    p = processor()
    bits = bytearray(len(p.positions))
    bits[20:41] = b'\x01' * 21
    low = 41 + clear_beams
    bits[low:low + 21] = b'\x01' * 21
    assert p._clusters(bytes(bits)) == [(20, 40), (low, low + 20)]


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('narrow_start', [False, True])
def test_new_nearby_foot_keeps_its_own_touch_and_release(filtered, reverse, narrow_start):
    def trajectory(n):
        groups = [(20, 40)] if 100 <= n < 400 else []
        if 220 <= n < 500:
            groups += [(43, 45 if narrow_start and n < 240 else 63)]
        return groups
    p = replay(trajectory, filtered=filtered, reverse=reverse)
    assert not p.issues
    assert len(p.contacts) == 2
    assert [c.start for c in p.contacts] == pytest.approx([.100, .220])
    assert [c.end for c in p.contacts] == pytest.approx([.400, .500])
    assert all(c.confirmed and c.touch_known and not c.exclusion for c in p.contacts)
    assert p.summary()['valid_steps'] == 1


@pytest.mark.parametrize('filtered', [False, True])
def test_two_close_tracks_can_each_split_without_becoming_one_foot(filtered):
    def trajectory(n):
        a = [(20, 40)] if 100 <= n < 400 else []
        b = [(43, 63)] if 220 <= n < 500 else []
        if 300 <= n < 350:
            a, b = [(20, 23), (29, 40)], [(43, 46), (52, 63)]
        return a + b
    p = replay(trajectory, filtered=filtered)
    assert not p.issues and len(p.contacts) == 2
    assert [c.end for c in p.contacts] == pytest.approx([.400, .500])
    assert all(c.touch_known and not c.has_unknown for c in p.contacts)


@pytest.mark.parametrize('filtered', [False, True])
def test_actual_overlap_preserves_tracks_but_cannot_prove_individual_lift(filtered):
    def trajectory(n):
        if 300 <= n < 350:
            return [(20, 63)]
        return ([(20, 40)] if 100 <= n < 400 else []) + ([(43, 63)] if 220 <= n < 500 else [])
    p = replay(trajectory, filtered=filtered)
    assert len(p.contacts) == 2  # no reconstructed touchdown after separation
    assert [c.start for c in p.contacts] == pytest.approx([.100, .220])
    assert all(c.confirmed and c.touch_known and c.has_unknown for c in p.contacts)
    assert p.summary()['valid_contact_durations'] == 0
    assert all(row['lift_sample'] is None for row in p.summary()['contacts'])
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)


def test_simultaneous_disjoint_islands_do_not_become_one_known_foot():
    p = replay(lambda n: [(20, 30), (33, 43)] if 100 <= n < 400 else [])
    assert len(p.contacts) == 2
    assert all(not c.touch_known for c in p.contacts)
    assert p.summary()['valid_touches'] == 0


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('connect', [False, True])
def test_local_first_islands_cannot_restart_a_remote_reliable_track(filtered, connect):
    def trajectory(n):
        groups = [(20, 40)] if 100 <= n < 400 else []
        if 220 <= n < 500:
            groups += [(85, 105)] if connect and n >= 310 else [(85, 90), (93, 105)]
        return groups
    p = replay(trajectory, filtered=filtered)
    anchor = p.contacts[0]
    assert anchor.start == pytest.approx(.1) and anchor.end == pytest.approx(.4)
    assert anchor.confirmed and anchor.touch_known and not anchor.exclusion
    assert not any(i['code'] == 'ambiguous_contacts' and 'scope' not in i for i in p.issues)
    assert all(not c.touch_known for c in p.contacts[1:])


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_returning_island_keeps_occupancy_without_proving_same_foot(filtered, reverse):
    def trajectory(n):
        if not 100 <= n < 500:
            return []
        if 250 <= n < 350:
            return [(194, 202)]
        if 350 <= n < 356:
            return [(178, 178), (194, 202)]
        return [(175, 202)]
    p = replay(trajectory, filtered=filtered, reverse=reverse)
    assert len(p.contacts) == 1 and not p.issues
    c = p.contacts[0]
    assert c.touch_known and c.has_unknown and c.exclusion == 'unresolved_fragment_join'
    assert c.start == pytest.approx(.1) and c.end == pytest.approx(.5)


@pytest.mark.parametrize('filtered', [False, True])
def test_unknown_occupied_tail_keeps_later_independent_times_but_not_support(filtered):
    def trajectory(n):
        groups = [(60, 80)] if 100 <= n < 277 else [(60, 90)] if 277 <= n < 400 else []
        if 220 <= n < 277 or 400 <= n < 500:
            groups += [(90, 90)]
        groups += [(150, 170)] if 450 <= n < 650 else []
        groups += [(200, 220)] if 700 <= n < 900 else []
        groups += [(250, 270)] if 950 <= n < 1100 else []
        return groups
    p = replay(trajectory, filtered=filtered, end=1200)
    assert p.contacts[0].touch_known and p.contacts[0].has_unknown
    assert not p.contacts[0].position_known
    assert p.summary()['valid_support_cycles'] == 0
    # The unknown source's original onset still blocks the earlier sequence.
    # Its occupied tail cannot cancel three later independently confirmed touches.
    assert any(c['start_s'] == pytest.approx(.35) and c['duration_s'] == pytest.approx(.5)
               for c in p.summary()['cycles'])
    gap = next(g for g in p.contacts[0].merged_interruptions if g['reason'] == 'unresolved_fragment_join')
    assert gap['start_sample'] == 220 and gap['end_sample'] == 500


def test_large_calibrated_seam_is_not_a_contiguous_island_or_an_owner_margin():
    p = processor(3, stop_type='Software command')
    layout = DeviceLayout((SensorSegment('1', 0, 0), SensorSegment('2', 1, 1.08),
                           SensorSegment('3', 2, 2.08)))
    p.device = PreparedDevice(layout, 'test', -1, 0, 3000)
    p.positions = layout.positions_m
    for n in range(650):
        bits = bytearray(layout.bit_count)
        if 100 <= n < 400:
            bits[90:96] = b'\x01' * 6
            if n < 200:
                bits[85:90] = b'\x01' * 5
        if 220 <= n < 500:
            bits[96:106] = b'\x01' * 10
        raw = replace(frame(layout, n), contact_bits=bytes(bits))
        if n == 250:
            assert p._clusters(raw.contact_bits) == [(90, 95), (96, 105)]
        p.process(raw)
    assert not p.issues and len(p.contacts) == 2
    assert [c.start for c in p.contacts] == pytest.approx([.1, .22])
    assert [c.end for c in p.contacts] == pytest.approx([.4, .5])


@pytest.mark.parametrize('filtered', [False, True])
def test_vacated_historical_envelope_cannot_absorb_a_new_touch(filtered):
    def trajectory(n):
        groups = [(20, 40)] if 100 <= n < 200 else [(36, 56)] if 200 <= n < 400 else []
        return groups + ([(20, 28)] if 300 <= n < 500 else [])
    p = replay(trajectory, filtered=filtered)
    assert len(p.contacts) == 2 and not p.issues
    assert [c.start for c in p.contacts] == pytest.approx([.1, .3])
    assert [c.end for c in p.contacts] == pytest.approx([.4, .5])


@pytest.mark.parametrize('filtered', [False, True])
def test_connected_shape_shift_cannot_reconstruct_a_new_touch(filtered):
    def trajectory(n):
        groups = [(20, 40)] if 100 <= n < 200 else [(40, 60)] if 200 <= n < 400 else []
        return groups + ([(20, 30)] if 300 <= n < 500 else [])
    p = replay(trajectory, filtered=filtered)
    assert len(p.contacts) == 2
    assert [c.start for c in p.contacts] == pytest.approx([.1, .3])
    assert p.contacts[0].has_unknown and not p.contacts[0].position_known


@pytest.mark.parametrize('dark_length', [2, 4, 8])
@pytest.mark.parametrize('remote', [False, True])
def test_unknown_seam_cannot_prove_an_old_fragment_was_a_complete_foot(dark_length, remote):
    from tests.test_ground_local_observation import processor as local_processor, sample, replay as local_replay
    p = local_processor('walk')
    frames = [sample(n, ([(p.positions[87], p.positions[95])] if 100 <= n < 200 else
                        [(p.positions[98], p.positions[115])] if 200 <= n < 220 else [])
                     + ([(p.positions[220], p.positions[240])] if remote and 120 <= n < 250 else []),
                     [1] if 198 <= n < 198 + dark_length else []) for n in range(280)]
    local_replay(p, frames)
    old = p.contacts[0]
    assert old.start == pytest.approx(.1) and old.touch_known
    assert old.has_unknown and old.exclusion == 'unresolved_fragment_join'
    assert p.summary()['contacts'][0]['lift_sample'] is None
    assert p.summary()['valid_contact_durations'] == int(remote)
    assert all(not c.touch_known for c in p.contacts[1:] if c.start != .120)
    if remote:
        healthy = next(c for c in p.contacts if c.start == .120)
        assert healthy.end == .250 and healthy.touch_known and not healthy.exclusion
