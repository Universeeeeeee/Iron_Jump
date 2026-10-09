"""Waiting for entry and a first landing cannot complete an optical passage."""
import pytest

from hardware.sensor_frame import SensorFrame
from tests.test_ground_local_observation import processor


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('segments', [1, 8, 12])
def test_clear_wait_and_first_foot_do_not_trigger_passage_complete(mode, segments):
    from hardware.sensor_frame import DeviceLayout
    from hardware.walking_preflight import PreparedDevice
    p = processor(mode)
    layout = DeviceLayout.linear(segments)
    p = type(p)(p.config, PreparedDevice(layout, 'startup', -1, 0, 3000))
    clear = bytes(layout.bit_count)
    contact = bytes(int(.2 <= x <= .38) for x in layout.positions_m)
    valid = b'\x01' * layout.bit_count
    # Override the helper's manual setting so this exercises automatic exit.
    p.config.stop_type = 'Status change'
    for n in range(3500):
        bits = contact if 2000 <= n < 2200 else clear
        p.process(SensorFrame('startup', layout, n, n, n * 1_000_000 + 1,
                              bits, valid, b''))
        if n < 2000:
            assert p.origin is None
        assert p.finished_reason is None
    assert len(p.contacts) == 1 and p.contacts[0].confirmed
    assert p.direction == 0
    assert p.summary()['valid_steps'] == 0
