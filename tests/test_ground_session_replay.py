from dataclasses import replace

import pytest

from hardware.sensor_frame import DeviceLayout, SensorFrame
from tools.replay_ground_session import replay_session


@pytest.fixture(scope='module')
def walking_capture():
    layout = DeviceLayout.linear(8)
    valid = b'\x01' * layout.bit_count
    clear = bytes(layout.bit_count)
    contacts = [bytes(int(x <= p <= x + .18) for p in layout.positions_m) for x in (.3, .6, .9)]
    frames = []
    for i in range(7000):
        bits = clear
        for step, start in enumerate((3400, 3850, 4300)):
            if start <= i < start + 300:
                bits = contacts[step]
        frames.append(SensorFrame('offline', layout, i, i, 99_000_000_000 + i * 1_000_000,
                                  bits, valid, b''))
    return frames


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_stall_changes_delivery_without_changing_measured_report(qapp, walking_capture, mode):
    normal = replay_session(walking_capture, mode=mode)
    delayed = replay_session(walking_capture, 'processing_stall', mode=mode)
    legacy = replay_session(walking_capture, 'legacy_processing_stall', mode=mode)
    assert normal['finish_reason'] == delayed['finish_reason'] == 'manual'
    assert normal['summary']['valid_steps'] == 2
    assert normal['summary']['valid_cycles'] == 1
    assert normal['exported_frames'] == 4000
    assert delayed['max_pending_frames'] >= 1200
    assert delayed['pending_at_stop'] == 0
    for key in ('summary', 'exported_contact_sha256', 'export_timestamps_sha256'):
        assert normal[key] == delayed[key]
    assert legacy['finish_reason'] == 'data_timeout'
    assert legacy['pending_at_stop'] >= 1200
    assert legacy['exported_frames'] < normal['exported_frames']
    assert walking_capture[0].received_monotonic_ns == 99_000_000_000


@pytest.mark.parametrize(('scenario', 'reason'), [('source_silence', 'data_timeout'),
                                                ('disconnect', 'disconnected')])
def test_true_acquisition_failure_still_ends_session(qapp, walking_capture, scenario, reason):
    result = replay_session(walking_capture, scenario)
    assert result['armed']
    assert result['finish_reason'] == reason
    assert result['quality_events'][-1]['code'] == reason
    # Armed at sample 2999; injection precedes sample 3499.
    assert result['exported_frames'] == 499


def test_degraded_start_requires_explicit_offline_acknowledgement(qapp, walking_capture):
    frames = [replace(f, contact_bits=f.contact_bits[:576] + b'\x01' + f.contact_bits[577:])
              for f in walking_capture[:3200]]
    blocked = replay_session(frames)
    accepted = replay_session(frames, accept_degraded=True)
    assert blocked['finish_reason'] == 'not_armed'
    assert blocked['readiness']['bad_indices'] == (576,)
    assert accepted['masked_indices'] == [576]
    assert accepted['exported_frames'] == 200


def test_invalid_clock_or_empty_capture_is_rejected(qapp, walking_capture):
    with pytest.raises(ValueError, match='no complete frames'):
        replay_session([])
    with pytest.raises(ValueError, match='monotonic'):
        replay_session(walking_capture[:2][::-1])
