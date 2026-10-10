"""Unmeasured activity near a bad beam cannot silently shorten the passage."""
import pytest

from config.walking_config import WalkingConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.walking_session import WalkingSession
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice


def capture(end, *, near_bad=True, later_healthy=False):
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, 'mask-duration', -1, 0, 3000, bad_indices=(576,))
    session = WalkingSession(WalkingConfig(stop_type='Software command'))
    session.start_prepared(device)
    original = []
    for n in range(end):
        bits = bytearray(layout.bit_count)
        bits[576] = 1
        if 100 <= n < 300:
            bits[20:41] = b'\x01' * 21
        if near_bad and 500 <= n < 900:
            low = 584 if n < 510 else 577
            bits[low:596] = b'\x01' * (596 - low)
        if later_healthy and 1000 <= n < 1200:
            bits[680:703] = b'\x01' * 23
        raw = SensorFrame(device.stream_id, layout, n, n, n * 1_000_000,
                          bytes(bits), b'\x01' * layout.bit_count, b'')
        original.append(raw.contact_bits)
        session.on_frame(masked_frame(raw, device.bad_indices), raw_frame=raw)
    session.halt()
    report = session.build_report('manual')
    assert report.export_frames == tuple(original)
    return session.processor, report, original


@pytest.mark.parametrize('end', [750, 1000])
def test_masked_activity_at_end_does_not_report_an_earlier_duration(qtbot, end):
    p, report, raw = capture(end)
    occupied = [n for n, bits in enumerate(raw) if any(b for i, b in enumerate(bits) if i != 576)]
    assert occupied[0] == 100 and occupied[-1] == min(end, 900) - 1
    assert any(issue['code'] == 'masked_contact_boundary' for issue in p.issues)
    assert report.walking_summary['duration_s'] is None
    # Missing passage duration must not erase an earlier complete contact.
    first = report.walking_summary['contacts'][0]
    assert first['exclusion'] is None
    assert first['end'] - first['start'] == pytest.approx(.2)


def test_later_complete_healthy_contact_restores_passage_duration(qtbot):
    p, report, raw = capture(1400, later_healthy=True)
    assert any(issue['code'] == 'masked_contact_boundary' for issue in p.issues)
    assert report.walking_summary['duration_s'] == pytest.approx(1.1)
    assert raw[1199][680] and not raw[1200][680]
    assert p.contacts[-1].end == pytest.approx(1.2)
    assert not p.contacts[-1].exclusion


def test_masked_bad_bit_without_neighbor_activity_keeps_valid_duration(qtbot):
    p, report, _ = capture(1000, near_bad=False)
    assert not p.issues
    assert report.walking_summary['duration_s'] == pytest.approx(.2)


def test_masked_first_activity_cannot_become_a_later_partial_duration():
    layout = DeviceLayout.linear(8)
    p = WalkingProcessor(WalkingConfig(stop_type='Software command'),
                         PreparedDevice(layout, 'head', -1, 0, 3000, bad_indices=(576,)))
    for n in range(1000):
        bits = bytearray(layout.bit_count)
        if 100 <= n < 300:
            bits[577:596] = b'\x01' * 19
        if 500 <= n < 800:
            bits[680:703] = b'\x01' * 23
        frame = SensorFrame('head', layout, n, n, n * 1_000_000,
                            bytes(bits), b'\x01' * layout.bit_count, b'')
        p.process(frame, masked_contact=uncertain_contact(frame, p.device.bad_indices))
    s = p.summary()
    assert s['duration_s'] is None
    assert s['contacts'][-1]['end'] - s['contacts'][-1]['start'] == pytest.approx(.3)


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('earlier_healthy', [False, True])
def test_gap_at_first_unknown_touch_does_not_publish_a_later_partial_duration(filtered, earlier_healthy):
    from hardware.beam_filter import GroundStabilityFilter
    layout = DeviceLayout.linear(3)
    p = WalkingProcessor(WalkingConfig(stop_type='Software command'),
                         PreparedDevice(layout, 'gap-head', -1, 0, 1000))
    optical = GroundStabilityFilter(layout)
    for n in range(700):
        if n == 129:
            continue
        bits = bytearray(layout.bit_count)
        if earlier_healthy and 20 <= n < 100:
            bits[5:26] = b'\x01' * 21
        if 130 <= n < 350:
            bits[40:61] = b'\x01' * 21
        if 400 <= n < 550:
            bits[150:171] = b'\x01' * 21
        frame = SensorFrame('gap-head', layout, n, n, n + 1, bytes(bits),
                            b'\x01' * layout.bit_count, b'')
        for measured in optical.feed(frame) if filtered else [frame]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    assert [i['code'] for i in p.issues] == ['frame_gap']
    assert not next(c for c in p.contacts if c.start == .130).touch_known
    assert p.summary()['duration_s'] == (pytest.approx(.530) if earlier_healthy else None)


@pytest.mark.parametrize('healthy_start', [90, 99])
def test_unknown_initial_touch_interval_cannot_be_recovered_using_its_midpoint(healthy_start):
    from tests.test_ground_local_observation import processor, replay, sample
    p = processor('walk')
    frames = []
    for n in range(700):
        contacts = [(1.20, 1.38)] if healthy_start <= n < 350 else []
        if 100 <= n < 300:
            contacts.append((0, .18))
        if 400 <= n < 550:
            contacts.append((2.20, 2.38))
        frames.append(sample(n, contacts, [0] if 96 <= n < 105 else []))
    replay(p, frames)
    boundary = next(c for c in p.contacts if c.exclusion == 'boundary_contact')
    assert boundary.edge_estimates['touch'] == [95, 105]
    assert boundary.start == .100 and not boundary.touch_known
    assert p.origin == healthy_start / 1000 and not p.issues
    assert p.summary()['duration_s'] == (pytest.approx(.460) if healthy_start == 90 else None)


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('earlier_healthy', [False, True])
def test_first_unowned_ambiguity_cannot_be_replaced_by_a_later_duration(filtered, earlier_healthy):
    from hardware.beam_filter import GroundStabilityFilter
    from tests.test_overground_walking import processor
    p = processor(stop_type='Software command')
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(700):
        bits = bytearray(p.device.layout.bit_count)
        if earlier_healthy and 20 <= n < 100:
            bits[5:26] = b'\x01' * 21
        if 100 <= n < 250:
            for low in (40, 95, 150):
                bits[low:low + 21] = b'\x01' * 21
        if 400 <= n < 550:
            bits[220:241] = b'\x01' * 21
        frame = SensorFrame('test', p.device.layout, n, n, n + 1, bytes(bits),
                            b'\x01' * p.device.layout.bit_count, b'')
        for measured in optical.feed(frame) if filtered else [frame]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    assert [i['code'] for i in p.issues] == ['ambiguous_contacts']
    assert p.summary()['duration_s'] == (pytest.approx(.530) if earlier_healthy else None)


@pytest.mark.parametrize('filtered', [False, True])
@pytest.mark.parametrize('kind', ['isolated_pulse', 'unresolved_wide', 'unresolved_narrow'])
def test_initial_candidate_must_be_explicitly_excluded_before_using_a_later_start(filtered, kind):
    from hardware.beam_filter import GroundStabilityFilter
    from tests.test_overground_walking import processor
    p = processor(stop_type='Software command')
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(700):
        bits = bytearray(p.device.layout.bit_count)
        if kind == 'isolated_pulse' and n == 100:
            bits[20] = 1
        elif kind != 'isolated_pulse' and 100 <= n < 130:
            high = 40 if kind == 'unresolved_wide' else 21
            bits[20:high + 1] = b'\x01' * (high - 19)
        if 400 <= n < 550:
            bits[150:171] = b'\x01' * 21
        frame = SensorFrame('test', p.device.layout, n, n, n + 1, bytes(bits),
                            b'\x01' * p.device.layout.bit_count, b'')
        for measured in optical.feed(frame) if filtered else [frame]:
            p.process(measured)
    if filtered:
        for measured in optical.flush():
            p.process(measured)
    assert not p.issues
    assert p.summary()['duration_s'] == (pytest.approx(.150) if kind == 'isolated_pulse' else None)
    if kind != 'isolated_pulse':
        assert p.contacts[0].candidate_outcome == 'unresolved'
    elif not filtered:
        assert p.contacts[0].candidate_outcome == 'excluded_nonstep'
