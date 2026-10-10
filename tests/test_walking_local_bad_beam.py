"""A known bad beam must not erase a remote foot's measured boundaries."""
import pytest

from config.walking_config import WalkingConfig
from engine.walking_session import WalkingSession
from hardware.beam_quality import masked_frame
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice


def capture(reverse=False, head=False):
    layout = DeviceLayout.linear(8)
    bad = 767-576 if reverse else 576
    device = PreparedDevice(layout, 'local-bad', -1, 0, 3000, bad_indices=(bad,))
    session = WalkingSession(WalkingConfig(stop_type='Software command', starting_foot='Left'))
    session.start_prepared(device)
    original = []
    for n in range(1100):
        groups = []
        if 100 <= n < 600:
            groups.append((577,595) if head else (550,570) if n < 250 else
                          (557,578) if n < 550 else (579,584))
        if 400 <= n < 750:
            groups.append((620,641))
        if 700 <= n < 1000:
            groups.append((680,701))
        bits = bytearray(768)
        bits[bad] = 1
        for lo,hi in groups:
            if reverse: lo,hi = 767-hi,767-lo
            bits[lo:hi+1] = b'\x01'*(hi-lo+1)
        raw = SensorFrame(device.stream_id,layout,n,n,n*1_000_000,
                          bytes(bits),b'\x01'*768,b'')
        original.append(raw.contact_bits)
        session.on_frame(masked_frame(raw,device.bad_indices),raw_frame=raw)
    session.halt()
    report = session.build_report('manual')
    assert report.export_frames == tuple(original)
    return session.processor, report.walking_summary


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('head', [False, True])
def test_remote_touch_and_release_are_observed_during_local_bad_boundary(qtbot, reverse, head):
    p,s = capture(reverse,head)
    healthy = [c for c in p.contacts if c.start == pytest.approx(.4)]
    assert len(healthy) == 1
    assert healthy[0].end == pytest.approx(.75)
    assert healthy[0].confirmed and not healthy[0].exclusion
    assert healthy[0].side == 'unknown'
    assert len(p.contacts) == 3  # the censored foot rolling away is not a new touch
    assert p.contacts[0].exclusion == 'masked_contact_boundary'
    assert p.contacts[0].end is None  # no invented release through the unavailable beam
    assert s['valid_steps'] == (1 if head else 2)
    assert s['valid_cycles'] == (0 if head else 1)
    assert s['valid_step_lengths'] == 1
    assert s['valid_support_cycles'] == 0  # never fill support across the censored foot
    assert not any(c.exclusion == 'unknown_touch_after_gap' for c in p.contacts)


def test_local_bad_contact_keeps_duration_censored_when_it_is_first_activity(qtbot):
    _,s = capture(head=True)
    assert s['duration_s'] is None


def test_already_confirmed_remote_foot_can_lift_during_local_mask(qtbot):
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout,'remote-lift',-1,0,3000,bad_indices=(576,))
    session = WalkingSession(WalkingConfig(stop_type='Software command'))
    session.start_prepared(device)
    for n in range(800):
        bits = bytearray(768)
        bits[576] = 1
        if 100 <= n < 400:bits[500:521] = b'\x01'*21
        if 250 <= n < 700:bits[577:596] = b'\x01'*19
        raw = SensorFrame(device.stream_id,layout,n,n,n*1_000_000,bytes(bits),b'\x01'*768,b'')
        session.on_frame(masked_frame(raw,device.bad_indices),raw_frame=raw)
    session.halt()
    first = session.processor.contacts[0]
    assert first.confirmed and not first.exclusion
    assert first.start == pytest.approx(.1) and first.end == pytest.approx(.4)
    assert session.processor.summary()['duration_s'] is None
