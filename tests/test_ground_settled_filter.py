"""Settled frames must retain tail uncertainty and reliable-vote timing."""
from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout
from tests.test_ground_stability_filter import frame


def test_fully_bad_module_still_marks_an_unconfirmed_tail():
    filt = GroundStabilityFilter(DeviceLayout.linear(2), range(96))
    for n in range(5):
        assert filt.feed(frame(n)) == []
    out = filt.flush()
    assert len(out) == 5
    assert all(f.valid_bits == bytes(96) + b'\x01' * 96 for f in out)
    assert all('unconfirmed_filter_tail' in f.quality_flags for f in out)


def test_settled_plateau_does_not_turn_a_quarantined_sample_into_a_vote():
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    out = []
    for n in range(30):
        out.extend(filt._feed(frame(n)))
    for n in range(30, 41):
        out.extend(filt._feed(frame(n, [(10, 25)]), tuple(range(96)) if n == 35 else ()))
    assert not any(f.contact_bits[10] for f in out)
    assert filt._queue[0][0].sample_index == 30
    confirmed = filt._feed(frame(41, [(10, 25)]))
    assert confirmed[0].sample_index == 30
    assert confirmed[0].contact_bits[10] == 1
    assert confirmed[0].wire_payload == frame(30).wire_payload


def test_reset_requires_new_confirmation_after_a_settled_touch():
    filt = GroundStabilityFilter(DeviceLayout.linear(2))
    for n in range(30):
        filt.feed(frame(n, [(10, 25)]))
    filt.reset()
    for n in range(30, 40):
        assert filt.feed(frame(n, [(10, 25)])) == []
    out = filt.feed(frame(40, [(10, 25)]))
    assert out[0].sample_index == 30
    assert out[0].contact_bits[10] == 1
