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
