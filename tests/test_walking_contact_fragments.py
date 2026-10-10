"""Heel/forefoot splits must retain a previously observed optical contact."""
import pytest

from config.walking_config import WalkingConfig
from engine.modes.walking_processor import WalkingProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice
from engine.walking_session import WalkingSession


def replay(contacts_at, end=500, *, filtered=False, reverse=False, wire_order=None):
    layout = DeviceLayout.linear(3, wire_order=wire_order)
    p = WalkingProcessor(WalkingConfig(stop_type='Software command', starting_foot='Left'),
                         PreparedDevice(layout, 'fragments', -1, 0, 3000))
    optical = GroundStabilityFilter(layout)
    for n in range(end):
        bits = bytearray(layout.bit_count)
        for low, high in contacts_at(n):
            if reverse:
                low, high = layout.bit_count - 1 - high, layout.bit_count - 1 - low
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        f = SensorFrame('fragments', layout, n, n, n * 1_000_000,
                        bytes(bits), b'\x01' * layout.bit_count, b'')
        for measured in optical.feed(f) if filtered else [f]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    return p


@pytest.mark.parametrize('filtered', [False, True])
def test_existing_foot_can_split_into_heel_and_forefoot(filtered):
    def trajectory(n):
        if not 100 <= n < 400:
            return []
        return [(20, 23), (29, 40)] if 200 <= n < 280 else [(20, 40)]
    p = replay(trajectory, filtered=filtered)
    assert len(p.contacts) == 1
    assert not p.issues
    c = p.contacts[0]
    assert c.confirmed and not c.exclusion and c.side == 'left'
    assert c.start == pytest.approx(.1)
    assert c.end == pytest.approx(.4)
    assert p.summary()['mean_contact_s'] == pytest.approx(.3)
    snapshot = p.build_report('manual').report_config_snapshot
    assert snapshot['algorithm'] == 'overground_walking_v1.10'
    assert snapshot['fragment_association'] == 'unique_existing_envelope_with_match_margin'


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('wire_order', [None, (3, 1, 2)])
def test_small_forefoot_roll_across_seam_does_not_lose_its_heel(reverse, wire_order):
    def trajectory(n):
        if not 100 <= n < 400:
            return []
        return [(80, 81), (87, 106)] if 200 <= n < 280 else [(80, 105)]
    p = replay(trajectory, reverse=reverse, wire_order=wire_order)
    assert len(p.contacts) == 1 and not p.issues
    assert p.contacts[0].end == pytest.approx(.4)


def test_new_foot_outside_preceding_envelope_remains_separate():
    def trajectory(n):
        return ([(49, 60)] if 100 <= n < 350 else []) + ([(66, 79)] if 220 <= n < 450 else [])
    p = replay(trajectory)
    assert len(p.contacts) == 2 and not p.issues
    assert p.contacts[0].start == pytest.approx(.1)
    assert p.contacts[1].start == pytest.approx(.22)


def test_two_existing_feet_keep_separate_identity_when_both_split():
    def trajectory(n):
        a = [(20, 40)] if 100 <= n < 320 else []
        b = [(85, 105)] if 220 <= n < 450 else []
        if 280 <= n < 300:
            a, b = [(20, 23), (29, 40)], [(85, 88), (94, 105)]
        return a + b
    p = replay(trajectory)
    assert len(p.contacts) == 2 and not p.issues
    assert [c.side for c in p.contacts] == ['left', 'right']
    assert p.summary()['valid_steps'] == 1


def test_fragment_with_multiple_possible_owners_still_breaks_continuity():
    def trajectory(n):
        if 100 <= n < 200:
            return [(20, 40)]
        if 200 <= n < 300:
            return [(20, 40), (50, 70)]
        if 300 <= n < 400:
            return [(33, 57)]
        return []
    p = replay(trajectory)
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)
    steps = p.summary()['steps']
    assert len(steps) == 1  # the two touches preceded the later identity loss
    assert steps[0]['time_s'] == pytest.approx(.1)
    assert steps[0]['length_m'] is None


def test_new_simultaneous_fragments_without_a_prior_foot_remain_uncertain():
    p = replay(lambda n: [(20, 23), (29, 40)] if 100 <= n < 400 else [])
    assert p.summary()['valid_steps'] == 0
    assert p.summary()['valid_step_lengths'] == 0
    assert all(c.exclusion for c in p.contacts)


def test_third_distant_foot_is_not_joined_to_an_existing_foot():
    def trajectory(n):
        feet = [(20, 40)] if 100 <= n < 400 else []
        if 180 <= n < 400:
            feet += [(85, 105)]
        if 260 <= n < 400:
            feet += [(160, 180)]
        return feet
    p = replay(trajectory)
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)
    assert p.summary()['valid_steps'] == 1  # retain only the pre-ambiguity interval
    assert p.summary()['valid_step_lengths'] == 0


def test_two_shifted_islands_without_an_inner_anchor_remain_uncertain():
    def trajectory(n):
        if 100 <= n < 200:
            return [(20, 40)]
        if 200 <= n < 400:
            return [(19, 23), (29, 41)]
        return []
    p = replay(trajectory)
    assert any(i['code'] == 'ambiguous_contacts' for i in p.issues)
    assert p.summary()['valid_steps'] == 0


def test_formal_eight_metre_session_preserves_raw_islands_and_fixed_bad_bit(qtbot):
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, 'formal', -1, 0, 3000, bad_indices=(576,))
    session = WalkingSession(WalkingConfig(stop_type='Software command', starting_foot='Left'))
    session.start_prepared(device)
    original = []
    for n in range(1100):
        groups = []
        if 100 <= n < 300:
            groups = [(20, 40)]
        elif 450 <= n < 700:
            groups = [(80, 110)]
            if 550 <= n < 610:
                groups = [(80, 83), (90, 111)]
        elif 820 <= n < 970:
            groups = [(150, 172)]
        bits = bytearray(layout.bit_count)
        bits[576] = 1
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        raw = SensorFrame('formal', layout, n, n, n * 1_000_000,
                          bytes(bits), b'\x01' * layout.bit_count, b'')
        original.append(raw.contact_bits)
        session.on_frame(masked_frame(raw, device.bad_indices), raw_frame=raw)
    session.halt()
    report = session.build_report('manual')
    assert report.export_frames == tuple(original)
    assert not report.walking_summary['issues']
    assert report.walking_summary['valid_steps'] == 2
    assert report.walking_summary['valid_cycles'] == 1
    assert len(session.processor.contacts) == 3
    assert session.processor.contacts[1].start == pytest.approx(.45)
    assert session.processor.contacts[1].end == pytest.approx(.7)
