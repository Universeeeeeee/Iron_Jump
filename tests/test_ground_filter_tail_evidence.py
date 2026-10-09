"""Unconfirmed filter tails retain raw evidence without asserting measured states."""
import pytest

from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout
from engine.overground_session import OvergroundSession
from tests.test_ground_stability_filter import frame
from tools.validate_ground_observation import make_processor


@pytest.mark.parametrize('kind', ['touch', 'release', 'dark'])
@pytest.mark.parametrize('length', [1, 5, 10])
def test_flush_marks_only_unconfirmed_tail_and_preserves_raw(kind, length):
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    source, result = [], []
    for n in range(100):
        before = n < 100 - length
        blocked = ([(10, 25)] if not before else []) if kind == 'touch' else (
            [(10, 25)] if before else ([(0, 95)] if kind == 'dark' else []))
        raw = frame(n, blocked)
        source.append(raw)
        result.extend(filt.feed(raw))
    result.extend(filt.flush())
    assert [f.sample_index for f in result] == list(range(100))
    assert [f.wire_payload for f in result] == [f.wire_payload for f in source]
    for n, f in enumerate(result):
        if n < 100 - length:
            assert all(f.valid_bits)
            assert 'unconfirmed_filter_tail' not in f.quality_flags
        else:
            assert f.valid_bits[10] == 0
            assert f.valid_bits[120] == 1  # Other module's mask is unchanged.
            assert 'unconfirmed_filter_tail' in f.quality_flags
    assert filt.flush() == []
    assert all(all(f.valid_bits) for f in source)


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('raw_end', [2095, 2100])
@pytest.mark.parametrize('termination', ['halt', 'reset'])
def test_session_tail_cannot_create_stop_or_lift(qtbot, mode, raw_end, termination):
    p = make_processor(mode, DeviceLayout.linear(2), 'stable')
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    source = [frame(n, [(10,25)] if 100 <= n < raw_end else [])
              for n in range(raw_end + 5)]
    for f in source:
        session.on_frame(f)
    if termination == 'reset':
        from hardware.sensor_frame import AcquisitionIssue
        session.on_issue(AcquisitionIssue('checksum_or_tail_error', raw_end + 5))
    session.halt()
    report = session.build_report('manual')
    summary = report.walking_summary if mode == 'walk' else report.running_summary
    assert summary['stops'] == ([] if raw_end == 2095 else [{'start_s': 0.0, 'end_s': pytest.approx(2.0)}])
    assert session.processor.contacts[0].end is None  # Do not invent release.
    assert tuple(session.frames) == tuple(f.contact_bits for f in source)
    assert len(report.export_frames) == len(source)
    assert session.processor.contacts[0].last_reliable_sample == raw_end - 1


def test_pending_touch_is_not_reliable_flight():
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    result = []
    for n in range(100):
        result.extend(filt.feed(frame(n, [(10,25)] if n >= 95 else [])))
    result.extend(filt.flush())
    assert all(not any(f.contact_bits) for f in result[-5:])
    assert all(not all(f.valid_bits) for f in result[-5:])


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_earlier_confirmed_contacts_survive_tail_flush(qtbot, mode):
    p = make_processor(mode, DeviceLayout.linear(2), 'stable')
    session = OvergroundSession(p.config, type(p))
    session.start_prepared(p.device)
    for n in range(705):
        bounds = [(10,25)] if 100 <= n < 300 else ([(55,73)] if 400 <= n < 600 else
                  ([(110,128)] if n >= 700 else []))
        session.on_frame(frame(n, bounds))
    session.halt()
    assert len(session.processor.contacts) == 2
    summary = session.processor.summary()
    assert summary['valid_steps'] == 1
    scale = 1000 if mode == 'walk' else 1
    assert session.processor.contacts[0].end * scale == pytest.approx(300)
    assert session.processor.contacts[1].end * scale == pytest.approx(600)
