"""A repeated wire-block alias must not contribute measurement votes."""
from dataclasses import replace

import numpy as np
import pytest

from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout, SensorFrame


def sample(n, groups=(), mirror=False, layout=None):
    layout = layout or DeviceLayout.linear(8)
    wire_bits = np.zeros(768, dtype=np.uint8)
    wire_bits[576] = 1
    for low, high in groups:
        wire_bits[low:high + 1] = 1
    packed = np.packbits(1 - wire_bits, bitorder='little')
    if mirror:
        packed[:32] = packed[64:]
    wire = packed.tobytes()
    return SensorFrame('mirror', layout, n, n, n + 1, layout.contact_bits(wire),
                       b'\x01' * 768, wire)


def replay(frames):
    filt = GroundStabilityFilter(frames[0].layout)
    out = []
    for f in frames:
        out.extend(filt.feed(f))
    out.extend(filt.flush())
    return filt, out


def test_periodic_alias_does_not_complete_a_release_candidate():
    frames = [sample(n, [(40,60)] if n < 91 else [], n in {11,41,71,101})
              for n in range(140)]
    filt=GroundStabilityFilter(frames[0].layout);out=[];release_available=None
    for raw in frames:
        ready=filt.feed(raw)
        if release_available is None and any(not f.contact_bits[50] for f in ready):
            release_available=raw.sample_index
        out.extend(ready)
    out.extend(filt.flush())
    assert [f.sample_index for f in out] == list(range(140))
    assert [f.wire_payload for f in out] == [f.wire_payload for f in frames]
    assert release_available == 102  # Ten clear observations + one alias is not eleven.
    assert out[91].contact_bits[50] == 0  # Preserve the first observed clear boundary.
    assert {e['sample_index'] for e in filt.mirror_guard.events} == {71,101}
    assert all(e['wire_byte_range'] == [0,32] for e in filt.mirror_guard.events)


@pytest.mark.parametrize('kind', ['single', 'wrong_phase', 'persistent', 'other_size', 'bit_only'])
def test_block_equality_or_counter_phase_alone_cannot_quarantine(kind):
    frames = []
    for n in range(150):
        mirrors = {11} if kind == 'single' else {11,42,74,107} if kind == 'wrong_phase' else (
            set(range(11,150)) if kind == 'persistent' else {11,41,71,101})
        f = sample(n, [(40,60)], n in mirrors)
        if kind == 'other_size':
            layout = DeviceLayout.linear(7)
            f = replace(f, layout=layout, wire_payload=f.wire_payload[:84],
                        contact_bits=f.contact_bits[:672], valid_bits=f.valid_bits[:672])
        if kind == 'bit_only' and n in mirrors:
            bits = bytearray(sample(n, [(40,60)]).contact_bits); bits[64] = 1
            wire = np.packbits(1-np.frombuffer(bytes(bits),dtype=np.uint8),bitorder='little').tobytes()
            f = replace(f, contact_bits=bytes(bits), wire_payload=wire)
        frames.append(f)
    filt, _ = replay(frames)
    assert not filt.mirror_guard.events


def test_alias_is_mapped_from_wire_bytes_to_reordered_reversed_physical_beams():
    from hardware.sensor_frame import SensorSegment
    layout = DeviceLayout(tuple(SensorSegment(str(i), 7-i, float(i), reversed=True) for i in range(8)))
    frames = [sample(n, [(40,60),(620,640)], n in {11,41,71,101}, layout) for n in range(150)]
    filt, out = replay(frames)
    assert filt.mirror_guard.events
    assert set(filt.mirror_guard.affected_indices) == set(range(512,768))
    assert all(all(f.contact_bits[127:148]) for f in out)


def test_guard_forgets_phase_across_a_gap_or_stream_change():
    from hardware.payload_mirror import PeriodicPayloadMirrorGuard
    guard = PeriodicPayloadMirrorGuard(DeviceLayout.linear(8))
    for n in range(90):guard.feed(sample(n, [(40,60)], n in {11,41,71}))
    assert guard.events
    for n in range(120,140):guard.feed(sample(n, [(40,60)], n==131))
    assert len(guard.events)==1
    for n in range(150,180):guard.feed(replace(sample(n, [(40,60)], n==161),stream_id='new'))
    assert len(guard.events)==1


def test_pending_last_frame_is_not_quarantined_without_a_right_neighbour():
    filt, out = replay([sample(n, [(40,60)], n in {11,41,71,101}) for n in range(102)])
    assert [f.sample_index for f in out] == list(range(102))
    assert [e['sample_index'] for e in filt.mirror_guard.events] == [71]
    assert not any(out[-1].valid_bits[:256])
    assert all(out[-1].valid_bits[256:])


def test_unverified_mirror_tail_cannot_supply_the_eleventh_release_vote():
    frames=[sample(n,[(40,60)] if n<91 else [],n in {11,41,71,101}) for n in range(102)]
    filt,out=replay(frames)
    assert all(not f.valid_bits[50] for f in out[91:])
    assert all(f.contact_bits[50] for f in out[91:101])
    assert [f.wire_payload for f in out]==[f.wire_payload for f in frames]
