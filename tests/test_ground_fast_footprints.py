"""Live candidates and sustained landing evidence must not wait for shape growth."""
from dataclasses import replace

import pytest

from engine.overground_session import OvergroundSession
from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import SensorFrame
from tests.test_ground_candidate_groups import make, feed


def frame(p, n, groups):
    bits = bytearray(len(p.positions))
    for low, high in groups:
        bits[low:high + 1] = b'\x01' * (high - low + 1)
    return SensorFrame(p.device.stream_id, p.device.layout, n, n,
                       10**12 + n * 1000000, bytes(bits), b'\x01' * len(bits), b'')


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('onset', [100, 105, 115])
def test_first_candidate_reaches_widget_before_confirmation(qtbot, mode, onset):
    from ui.ground_track import GroundTrackPanel
    p = make(mode)
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    session.visual.connect(panel.render_state)
    first = None
    for n in range(onset + 30):
        session.on_frame(frame(p, n, [(40, 60)] if n >= onset else []))
        if panel.channel._feet and first is None:
            first = n
            assert panel.channel._feet[0]['status'] == 'candidate'
            assert session.processor.reliable_touch_count == 0
    assert first is not None and first - onset <= 28
    assert session.processor.origin is None  # Preview does not start measurement.
    panel.resize(280, 700)
    candidate_pixels = panel.channel.grab().toImage()
    panel.render_state({**panel._frame, 'feet': []})
    assert candidate_pixels != panel.channel.grab().toImage()
    session.halt()


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_deferred_narrow_candidate_is_visible_without_adding_a_step(qtbot, mode):
    p = make(mode)
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    visuals = []
    session.visual.connect(visuals.append)
    for n in range(330):
        groups = [(40, 60)] if n >= 100 else []
        if n >= 300:
            groups += [(200, 200)]
        session.on_frame(frame(p, n, groups))
    assert any(f['status'] == 'candidate' and f['centroid_cm'] == p.positions[200] * 100
               for v in visuals for f in v['feet'])
    assert session.processor.reliable_touch_count == 1
    session.halt()


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_preview_drops_short_noise_and_clears_after_release(qtbot, mode):
    p = make(mode)
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    visuals, snapshots = [], []
    session.visual.connect(visuals.append)
    session.snapshot.connect(snapshots.append)
    for n in range(400):
        groups = [(40, 60)] if n == 100 or 200 <= n < 350 else []
        before = session.processor.reliable_touch_count
        session.on_frame(frame(p, n, groups))
        if n < 200:
            assert not any(v['feet'] for v in visuals)
        if before == 0 and session.processor.reliable_touch_count == 1:
            assert snapshots[-1]['touch_count'] == 1
        if n == 390:
            assert not visuals[-1]['feet']
    assert session.processor.reliable_touch_count == 1
    session.halt()


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('filtered', [False, True])
def test_eight_sustained_landings_need_no_extra_width_growth(mode, reverse, filtered):
    p = make(mode)
    if mode == 'run':
        p.config.min_contact_time = 20
    optical = GroundStabilityFilter(p.device.layout) if filtered else None
    for n in range(2600):
        groups = []
        for i in range(8):
            start, low = 100 + i * 300, 40 + i * 90
            if start <= n < start + 15:
                groups = [(low, low + 3), (low + 6, low + 9)]
            elif start + 15 <= n < start + 150:
                groups = [(low, low + 9)]
        if reverse:
            groups = [(len(p.positions) - 1 - b, len(p.positions) - 1 - a) for a, b in reversed(groups)]
        sample = frame(p, n, groups)
        for measured in optical.feed(sample) if optical else [sample]:
            p.process(measured)
    if optical:
        for measured in optical.flush():
            p.process(measured)
    events = [e for e in p.touch_events if e['active']]
    assert [e['touch_sample'] for e in events] == list(range(100, 2201, 300))
    assert len({e['event_id'] for e in events}) == 8
    if mode == 'run':
        assert p.summary()['valid_steps'] == 7


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('restriction', ['two_feet', 'gap', 'bad_beam', 'narrow'])
def test_stable_projection_does_not_override_contradictory_evidence(mode, restriction):
    p = make(mode)
    if restriction == 'bad_beam':
        p = type(p)(p.config, replace(p.device, bad_indices=(44,)))
    for n in range(350):
        if restriction == 'gap' and n == 120:
            continue
        groups = [(40, 43), (46, 49)] if n == 100 else [(40, 49)] if 101 <= n < 300 else []
        if restriction == 'two_feet':
            groups = [(40, 49), (52, 61)] if n == 100 else [(40, 61)] if 101 <= n < 300 else []
        elif restriction == 'narrow':
            groups = [(40, 40), (42, 42)] if n == 100 else [(40, 42)] if 101 <= n < 300 else []
        feed(p, n, groups)
    assert p.reliable_touch_count == 0
