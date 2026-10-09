"""Unconfirmed narrow islands cannot erase a reliably observed standing foot."""
import pytest

from config.walking_config import WalkingConfig
from engine.modes.walking_processor import WalkingProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice


def processor():
    layout = DeviceLayout.linear(3)
    return WalkingProcessor(WalkingConfig(stop_type='Software command', starting_foot='Left'),
                            PreparedDevice(layout, 'narrow', -1, 0, 3000))


def frame(p, n, groups, reverse=False):
    bits = bytearray(p.device.layout.bit_count)
    for low, high in groups:
        if reverse:
            low, high = len(bits)-1-high, len(bits)-1-low
        bits[low:high+1] = b'\x01'*(high-low+1)
    return SensorFrame('narrow', p.device.layout, n, n, n*1_000_000,
                       bytes(bits), b'\x01'*len(bits), b'')


def replay(trajectory, *, filtered=False, reverse=False, end=600):
    p = processor()
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(end):
        f = frame(p, n, trajectory(n), reverse)
        for measured in optical.feed(f) if filtered else [f]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    return p


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_cross_seam_first_flattening_and_returning_heel_keep_one_contact(filtered, reverse):
    def trajectory(n):
        if not 100 <= n < 500:
            return []
        if n < 170:
            return [(175, 187)]
        if n < 178:
            return [(175, 187), (192, 194)]
        if 250 <= n < 350:
            return [(194, 202)]
        if 350 <= n < 356:
            return [(178, 178), (194, 202)]
        return [(175, 202)]
    p = replay(trajectory, filtered=filtered, reverse=reverse)
    assert not p.issues
    assert len(p.contacts) == 1
    c = p.contacts[0]
    assert c.confirmed and not c.exclusion and c.side == 'left'
    assert c.start == pytest.approx(.1) and c.end == pytest.approx(.5)


def test_tiny_third_island_does_not_erase_two_uniquely_observed_feet():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(85, 105)] if 220 <= n < 450 else []) + (
            [(160, 160)] if 300 <= n < 304 else [])
    p = replay(trajectory)
    assert not p.issues
    assert len(p.contacts) == 2
    assert p.summary()['valid_steps'] == 1


@pytest.mark.parametrize('filtered', [False, True])
def test_real_new_foot_growing_from_narrow_keeps_original_touch_and_votes(filtered):
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 350 else []) + (
            [(85, 85)] if 220 <= n < 230 else [(85, 105)] if 230 <= n < 450 else [])
    p = replay(trajectory, filtered=filtered)
    assert not p.issues and len(p.contacts) == 2
    c = p.contacts[1]
    assert c.start == pytest.approx(.22)
    assert c.confirmed_at == pytest.approx(.279)
    assert c.end == pytest.approx(.45) and c.side == 'right'


def test_sustained_narrow_third_island_is_not_hidden_beyond_minimum_contact_time():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(85, 105)] if 180 <= n < 400 else []) + (
            [(160, 160)] if 220 <= n < 400 else [])
    p = replay(trajectory)
    issue = next(i for i in p.issues if i['code'] == 'ambiguous_contacts')
    assert issue['frame_index'] == 279


def test_wide_third_foot_still_breaks_continuity_immediately():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(85, 105)] if 180 <= n < 400 else []) + (
            [(160, 180)] if 220 <= n < 400 else [])
    p = replay(trajectory)
    assert p.issues[0]['frame_index'] == 220


def test_two_confirmed_feet_merging_remain_ambiguous():
    def trajectory(n):
        if 100 <= n < 200:
            return [(20, 40)]
        if 200 <= n < 300:
            return [(20, 40), (50, 70)]
        return [(33, 57)] if 300 <= n < 400 else []
    p = replay(trajectory)
    assert p.issues[0]['frame_index'] == 300


def test_first_unknown_narrow_islands_without_confirmed_anchor_stay_uncertain():
    p = replay(lambda n: [(20, 23), (29, 40)] if 100 <= n < 400 else [])
    assert p.summary()['valid_steps'] == 0
    assert all(c.exclusion for c in p.contacts)


@pytest.mark.parametrize('masked', [False, True])
def test_pending_narrow_evidence_cannot_cross_a_gap_or_masked_boundary(masked):
    p = processor()
    for n in range(226):
        groups = [(20, 40)] if n >= 100 else []
        if n >= 220:
            groups += [(85, 85)]
        p.process(frame(p, n, groups))
    p.process(frame(p, 226 if masked else 230, [(20, 40)]), masked_contact=masked)
    assert not p._narrow_candidates


def test_pending_narrow_island_that_fully_releases_is_not_a_contact():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(85, 85)] if 220 <= n < 226 else [])
    p = replay(trajectory)
    assert len(p.contacts) == 1 and not p.issues


def test_independently_released_narrow_island_is_a_step_sequence_barrier():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 300 else []) + (
            [(85, 105)] if 220 <= n < 500 else []) + (
            [(150, 170)] if 420 <= n < 650 else []) + (
            [(220, 220)] if 280 <= n < 285 else [])
    p = replay(trajectory, end=750)
    s = p.summary()
    assert not p.issues and s['valid_steps'] == 1 and s['valid_cycles'] == 0
    assert s['single_support_s'] is None and s['double_support_s'] is None


def test_promoted_real_foot_restores_support_from_its_original_touch():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 300 else []) + (
            [(85, 85)] if 220 <= n < 230 else [(85, 105)] if 230 <= n < 500 else []) + (
            [(150, 170)] if 420 <= n < 650 else [])
    p = replay(trajectory, end=750)
    s = p.summary()
    assert not p.issues and s['valid_cycles'] == 1
    assert s['single_support_s'] == pytest.approx(.24)
    assert s['double_support_s'] == pytest.approx(.08)


def test_two_pending_islands_merging_into_an_unknown_new_foot_remain_ambiguous():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(85, 85), (95, 95)] if 220 <= n < 225 else [(85, 105)] if 225 <= n < 400 else [])
    p = replay(trajectory)
    assert p.issues[0]['frame_index'] == 225


def test_later_independent_wide_foot_cannot_overtake_an_earlier_pending_touch():
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(150, 150)] if 220 <= n < 230 else [(150, 170)] if 230 <= n < 450 else []) + (
            [(85, 105)] if 225 <= n < 500 else [])
    p = replay(trajectory)
    assert p.issues[0]['frame_index'] == 225
    assert p.summary()['valid_steps'] == 0


@pytest.mark.parametrize('later_touch', [226, 230])
def test_released_earlier_pending_touch_cannot_publish_later_foot_side(later_touch):
    def trajectory(n):
        return ([(20, 40)] if 100 <= n < 400 else []) + (
            [(150, 150)] if 220 <= n < 226 else []) + (
            [(85, 105)] if later_touch <= n < 500 else [])
    p = replay(trajectory)
    assert not p.issues and len(p.contacts) == 2
    assert p.contacts[1].side == 'unknown'
    assert p.summary()['valid_steps'] == 0


def test_island_joining_known_foot_keeps_cycle_timing_but_support_unknown():
    def trajectory(n):
        a = [(20, 40)] if 100 <= n < 285 else [(20, 46)] if 285 <= n < 300 else []
        return a + ([(85, 105)] if 220 <= n < 500 else []) + (
            [(150, 170)] if 420 <= n < 650 else []) + (
            [(46, 46)] if 280 <= n < 285 else [])
    p = replay(trajectory, end=750)
    s = p.summary()
    assert not p.issues and s['valid_steps'] == 2 and s['valid_cycles'] == 1
    assert s['cycles'][0]['duration_s'] == pytest.approx(.32)
    assert s['single_support_s'] is None and s['double_support_s'] is None
