"""Device-clock debounce used by both ground measurement modes."""
from dataclasses import replace
import pytest
from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout, SensorFrame
from tools.validate_ground_observation import make_processor


def frame(n, blocked=(), **kwargs):
    layout = DeviceLayout.linear(2)
    bits = bytearray(192)
    for low, high in blocked:
        bits[low:high + 1] = b'\x01' * (high - low + 1)
    return SensorFrame('stable', layout, n, n, n + 1, bytes(bits), b'\x01' * 192,
                       bytes([n % 256]) * 24, **kwargs)


def filtered(frames):
    filt = GroundStabilityFilter(frames[0].layout)
    result = []
    for f in frames:
        result.extend(filt.feed(f))
        assert len(filt._queue) <= 10
    result.extend(filt.flush())
    return result


@pytest.mark.parametrize('length', range(1, 11))
def test_short_block_and_clear_pulses_are_removed(length):
    frames = [frame(n, [(10, 25)] if 20 <= n < 180 and not 80 <= n < 80 + length else
                    [(110, 191)] if 5 <= n < 5 + length else []) for n in range(210)]
    result = filtered(frames)
    assert [f.contact_bits for f in result] == [frame(n, [(10, 25)] if 20 <= n < 180 else []).contact_bits for n in range(210)]
    assert [f.wire_payload for f in result] == [f.wire_payload for f in frames]
    assert [f.sample_index for f in result] == list(range(210))


def test_confirmation_backdates_to_first_sample_and_waits_ten_ms():
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    for n in range(10):
        assert not filt.feed(frame(n, [(10, 10)]))
    out = filt.feed(frame(10, [(10, 10)]))
    assert len(out) == 1 and out[0].sample_index == 0 and out[0].contact_bits[10] == 1
    assert len(filt._queue) == 10


def test_per_beam_changes_are_independent_and_raw_frames_immutable():
    frames = [frame(n, ([(10, 25)] if 20 <= n < 160 else []) +
                      ([(110, 130)] if 80 <= n < 180 else []) +
                      ([(170, 191)] if n % 20 < 5 else [])) for n in range(210)]
    original = [(f.contact_bits, f.wire_payload) for f in frames]
    result = filtered(frames)
    assert [(f.contact_bits, f.wire_payload) for f in frames] == original
    for n, f in enumerate(result):
        assert f.contact_bits == frame(n, ([(10, 25)] if 20 <= n < 160 else []) +
                                      ([(110, 130)] if 80 <= n < 180 else [])).contact_bits


def test_no_right_confirmation_does_not_invent_lift():
    result = filtered([frame(n, [(10, 25)] if n < 95 else []) for n in range(100)])
    assert all(f.contact_bits[10] for f in result)


def test_counter_gap_does_not_count_as_confirmation():
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    out = []
    for n in [0, 1, 2, 3, 20, 21, 22]:
        out.extend(filt.feed(frame(n, [(10, 25)])))
    out.extend(filt.flush())
    assert not any(any(f.contact_bits) for f in out)
    assert [f.sample_index for f in out] == [0, 1, 2, 3, 20, 21, 22]


def test_faults_and_device_change_are_not_filtered_away():
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    filt.feed(frame(0))
    invalid = replace(frame(1), valid_bits=bytes(192), quality_flags=('crc_error',))
    assert filt.feed(invalid)[-1] is invalid
    changed = replace(frame(2), stream_id='different')
    assert filt.feed(changed)[-1] is changed


def test_raw_all_blocked_flag_is_not_a_transport_failure():
    frames = [frame(n, [(0, 191)] if 10 <= n < 15 else [],
                    quality_flags=('all_beams_blocked',) if 10 <= n < 15 else ()) for n in range(40)]
    assert all(not any(f.contact_bits) and not f.quality_flags for f in filtered(frames))
    persistent = filtered([frame(n, [(0, 191)], quality_flags=('all_beams_blocked',)) for n in range(30)])
    assert all(all(f.contact_bits) for f in persistent)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_clean_edges_and_duration_match_normal_processor(mode):
    frames = [frame(n, [(10, 28)] if 100 <= n < 300 else [(55, 73)] if 400 <= n < 600 else
                    [(110, 128)] if 700 <= n < 900 else []) for n in range(930)]
    normal = make_processor(mode, frames[0].layout, 'stable')
    stable = make_processor(mode, frames[0].layout, 'stable')
    for f in frames:normal.process(f)
    for f in filtered(frames):stable.process(f)
    assert normal.summary() == stable.summary()
    scale = 1000 if mode == 'walk' else 1
    assert stable.contacts[0].start * scale == pytest.approx(100)
    assert stable.contacts[0].end * scale == pytest.approx(300)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_session_uses_only_filter_and_preserves_raw_archive(qtbot, mode):
    from engine.overground_session import OvergroundSession
    p = make_processor(mode, DeviceLayout.linear(2), 'stable')
    session = OvergroundSession(p.config, type(p));session.start_prepared(p.device)
    frames = [frame(n, ([(10, 28)] if 100 <= n < 300 else []) +
                      ([(96, 191)] if n % 30 < 5 else [])) for n in range(340)]
    for f in frames:session.on_frame(f)
    session.halt()
    assert len(session.processor.contacts) == 1
    assert session.processor.contacts[0].confirmed
    assert session.processor.contacts[0].end is not None
    assert tuple(session.frames) == tuple(f.contact_bits for f in frames)
    assert not session.processor.issues


def test_minimum_confirmed_pulse_does_not_reuse_previous_direction_votes():
    result = filtered([frame(n, [(10, 25)] if 10 <= n < 21 else []) for n in range(50)])
    assert [f.sample_index for f in result if f.contact_bits[10]] == list(range(10, 21))


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_repeated_whole_zero_pulses_cannot_keep_a_departed_foot_blocked(mode):
    frames = [frame(n, [(0, 95)] if n % 6 == 0 else [(10, 28)] if 100 <= n < 300 else []) for n in range(360)]
    p = make_processor(mode, frames[0].layout, 'stable')
    for f in filtered(frames):p.process(f)
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    scale = 1000 if mode == 'walk' else 1
    assert p.contacts[0].end is not None
    assert 300 <= p.contacts[0].end * scale <= 301.001


def test_persistent_whole_zero_is_not_hidden_indefinitely():
    result = filtered([frame(n, [(0, 95)] if n >= 20 else []) for n in range(70)])
    assert all(all(f.contact_bits[:96]) for f in result if f.sample_index >= 20)


@pytest.mark.parametrize('length', range(1, 11))
@pytest.mark.parametrize('edge', [100, 300])
def test_whole_zero_moved_across_edges_has_bounded_delay(length, edge):
    for offset in range(-length, 2):
        start = edge + offset
        frames = [frame(n, [(0, 95)] if start <= n < start + length else
                        [(10, 28)] if 100 <= n < 300 else []) for n in range(340)]
        active = [f.sample_index for f in filtered(frames) if f.contact_bits[10]]
        assert 100 <= active[0] <= 100 + length
        assert 300 <= active[-1] + 1 <= 300 + length


def test_known_bad_beam_does_not_defeat_whole_zero_detection():
    filt = GroundStabilityFilter(DeviceLayout.linear(2), (0,))
    out = []
    for n in range(360):
        f = frame(n, [(1, 95)] if n % 6 == 0 else [(10, 28)] if 100 <= n < 300 else [])
        out.extend(filt.feed(f))
    out.extend(filt.flush())
    assert [f.sample_index for f in out if f.contact_bits[10]] == list(range(100, 301))
    assert not any(f.contact_bits[0] for f in out)
