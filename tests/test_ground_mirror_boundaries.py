"""Boundary outcomes of the isolated-mirror guard and its stability consumer."""
from dataclasses import replace

import pytest

from hardware.payload_mirror import PeriodicPayloadMirrorGuard
from hardware.sensor_frame import DeviceLayout
from tests.test_ground_payload_mirror import sample, replay


@pytest.mark.parametrize('last', [11, 41, 71, 101])
def test_learning_and_unverified_tail_preserve_raw_order_and_clock(last):
    frames = [sample(n, [(40, 60)], n in {11, 41, 71, 101}) for n in range(last + 1)]
    filt, out = replay(frames)
    assert [(f.sample_index, f.frame_index, f.received_monotonic_ns, f.wire_payload)
            for f in out] == [(f.sample_index, f.frame_index, f.received_monotonic_ns, f.wire_payload)
                             for f in frames]
    assert [e['sample_index'] for e in filt.mirror_guard.events] == ([71] if last == 101 else [])
    assert not filt.mirror_guard.tail_events if last < 101 else filt.mirror_guard.tail_events
    # One unlearned mirror cannot create a stable copied beam or release a real one.
    assert not any(f.contact_bits[64] and f.valid_bits[64] for f in out)
    assert all(f.contact_bits[50] for f in out[10:last])


@pytest.mark.parametrize('width', range(2, 11))
def test_short_consecutive_aliases_do_not_promote_copied_bits(width):
    frames = [sample(n, [(40, 60)], n in {11, 41, 71} or 101 <= n < 101 + width)
              for n in range(150)]
    filt, out = replay(frames)
    assert [e['sample_index'] for e in filt.mirror_guard.events] == [71]
    assert not any(f.contact_bits[64] and f.valid_bits[64] for f in out)
    assert all(f.contact_bits[50] for f in out[10:])


@pytest.mark.parametrize('width', [11, 20, 80])
def test_normal_symmetric_contacts_survive_even_after_phase_learning(width):
    frames = [sample(n, [(40, 60)] if n < 90 else [], n in {11, 41, 71}) for n in range(220)]
    # True, sustained equal projections at both ends; raw wire equality is valid here.
    for n in range(101, 101 + width):
        frames[n] = sample(n, [(40, 60), (64, 64), (552, 572)])
    filt, out = replay(frames)
    assert [e['sample_index'] for e in filt.mirror_guard.events] == [71]
    assert all(out[n].contact_bits[50] and out[n].contact_bits[560]
               for n in range(101, 101 + width))


@pytest.mark.parametrize('damage', ['counter_gap', 'invalid', 'quality', 'layout', 'stream'])
def test_pending_candidate_cannot_use_a_damaged_right_neighbour(damage):
    guard = PeriodicPayloadMirrorGuard(DeviceLayout.linear(8))
    for n in range(102):guard.feed(sample(n, [(40, 60)], n in {11, 41, 71, 101}))
    right = sample(102, [(40, 60)])
    if damage == 'counter_gap':right = replace(right, frame_index=104)
    if damage == 'invalid':right = replace(right, valid_bits=bytes(768))
    if damage == 'quality':right = replace(right, quality_flags=('damaged',))
    if damage == 'layout':right = replace(right, layout=DeviceLayout.linear(7))
    if damage == 'stream':right = replace(right, stream_id='new')
    ready = guard.feed(right)
    assert ready[0][0].sample_index == 101 and not ready[0][1]
    assert [e['sample_index'] for e in guard.events] == [71]
    assert guard._phase is None


def test_wire_distance_preserves_bit_counts_and_short_buffer_semantics():
    from hardware.payload_mirror import bit_distance
    assert bit_distance(b'\x80\x00',b'\x01\xff')==10
    assert bit_distance(b'\x80\x00',b'\x01')==2
    assert bit_distance(b'',b'\xff')==0
    import random
    rng=random.Random(14)
    for n in (1,32,96):
        for _ in range(20):
            left=bytes(rng.randrange(256) for _ in range(n))
            right=bytes(rng.randrange(256) for _ in range(n))
            expected=sum(bin(a^b).count('1') for a,b in zip(left,right))
            assert bit_distance(left,right)==expected
