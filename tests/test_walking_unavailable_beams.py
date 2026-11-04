"""Fixed bad beams retain coordinates without censoring healthy adjacent sources."""
import json
from pathlib import Path

import numpy as np
import pytest

from config.walking_config import WalkingConfig
from engine.walking_session import WalkingSession
from hardware.beam_quality import masked_frame
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice


def replay(groups, *, reverse=False, raw_bad=True):
    layout = DeviceLayout.linear(8)
    bad = 767 - 576 if reverse else 576
    device = PreparedDevice(layout, 'missing-beam', -1, 0, 3000, bad_indices=(bad,))
    session = WalkingSession(WalkingConfig(stop_type='Software command', min_contact_time=60))
    session.start_prepared(device)
    raw_rows = []
    for n in range(650):
        bits = bytearray(768)
        bits[bad] = int(raw_bad)
        for lo, hi in groups(n):
            if reverse:
                lo, hi = 767-hi, 767-lo
            bits[lo:hi+1] = b'\x01' * (hi-lo+1)
        bits[bad] = int(raw_bad)
        raw = SensorFrame(device.stream_id, layout, n, n, n*1_000_000,
                          bytes(bits), b'\x01'*768, b'')
        raw_rows.append(raw.contact_bits)
        session.on_frame(masked_frame(raw, device.bad_indices), raw_frame=raw)
    session.halt()
    assert session.build_report('manual').export_frames == tuple(raw_rows)
    assert all(f['contact_bits'][bad] == 0 for f in session.processor.timeline)
    assert session.processor.positions == layout.positions_m
    return session.processor


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('raw_bad', [False, True])
def test_healthy_foot_next_to_bad_beam_is_published(qtbot, reverse, raw_bad):
    p = replay(lambda n: [(577, 595)] if 100 <= n < 400 else [], reverse=reverse, raw_bad=raw_bad)
    assert [e['touch_sample'] for e in p.touch_events if e['active']] == [100]
    assert p.contacts[0].end == pytest.approx(.4)
    assert not p.contacts[0].exclusion


@pytest.mark.parametrize('reverse', [False, True])
def test_bad_only_separator_does_not_publish_a_second_foot(qtbot, reverse):
    p = replay(lambda n: ([(577, 595)] if 100 <= n < 450 else [])
               + ([(563, 575)] if 140 <= n < 400 else []), reverse=reverse)
    assert [e['touch_sample'] for e in p.touch_events if e['active']] == [100]
    assert len(p.contacts) == 2  # No artificial connection across the bad beam.
    assert not p.contacts[1].touch_known


def test_healthy_clear_beam_still_separates_two_contacts(qtbot):
    p = replay(lambda n: ([(578, 595)] if 100 <= n < 450 else [])
               + ([(563, 575)] if 180 <= n < 400 else []))
    assert [e['touch_sample'] for e in p.touch_events if e['active']] == [100, 180]


def test_bad_bit_alone_never_creates_contact(qtbot):
    p = replay(lambda n: [])
    assert not p.contacts and not p.touch_events


def test_recorded_oct28_walk_publishes_one_healthy_onset_near_bad_beam(qtbot):
    root = Path(__file__).parent/'fixtures/walking_bad_beam_20261028'
    meta = json.loads((root/'source.json').read_text())
    with np.load(root/'frames.npz') as data:
        bits = np.unpackbits(data['packed'], axis=1, bitorder='little')
    layout = DeviceLayout.linear(8)
    device = PreparedDevice(layout, meta['stream_id'], meta['checked_sample'], 0, 3000,
                            bad_indices=tuple(meta['bad_indices']))
    session = WalkingSession(WalkingConfig(stop_type='Status change', starting_foot='Left', min_contact_time=60))
    session.start_prepared(device)
    for index, row in enumerate(bits):
        n = device.checked_sample_index + 1 + index
        raw = SensorFrame(device.stream_id, layout, n, n, n*1_000_000,
                          row.tobytes(), b'\x01'*768, np.packbits(1-row, bitorder='little').tobytes())
        session.on_frame(masked_frame(raw, device.bad_indices), raw_frame=raw)
    session.halt()
    p = session.processor
    target = [e for e in p.touch_events if e['active'] and 21700 <= e['touch_sample'] <= 21850]
    assert len(target) == 1
    assert target[0]['touch_sample'] == 21719
    # Independent raw-bit check: this onset is real and strictly off the bad beam.
    i = 21719 - device.checked_sample_index - 1
    assert bits[i, 588] and not bits[i-1, 588]
    assert bits[:, 576].all()
    assert tuple(session.frames) == tuple(row.tobytes() for row in bits)


def test_simultaneous_sides_without_measured_separator_do_not_prove_foot_count(qtbot):
    p = replay(lambda n: [(563, 575), (577, 595)] if 100 <= n < 400 else [])
    assert not p.touch_events
    assert len(p.contacts) == 2 and all(c.bad_separator_unknown for c in p.contacts)


def test_cleared_earlier_foot_does_not_poison_later_source(qtbot):
    p = replay(lambda n: ([(577, 595)] if 100 <= n < 300 else [])
               + ([(563, 575)] if 305 <= n < 500 else []))
    assert [e['touch_sample'] for e in p.touch_events if e['active']] == [100, 305]


def test_missing_separator_never_supplies_full_foot_lift_or_contact_duration(qtbot):
    p = replay(lambda n: ([(577, 595)] if 100 <= n < 450 else [])
               + ([(563, 575)] if 140 <= n < 500 else []))
    report = p.build_report('manual')
    row = report.walking_summary['contacts'][0]
    assert row['touch_s']['valid']
    assert not any(row[k]['valid'] for k in ['lift_s', 'contact_s', 'centre_m'])
    assert row['contact_s']['missing_reason'] == 'unavailable_separator'
    assert report.touch_count == 1 and report.lift_count == 0


@pytest.mark.parametrize('reverse', [False, True])
def test_unknown_side_rolling_away_keeps_its_uncertainty(qtbot, reverse):
    def groups(n):
        return ([(557, 575)] if 100 <= n < 250 else []) + (
            [(577, 578)] if 200 <= n < 260 else [(579, 598)] if 260 <= n < 500 else [])
    p = replay(groups, reverse=reverse)
    assert [e['touch_sample'] for e in p.touch_events if e['active']] == [100]
    assert len(p.contacts) == 2
    assert p.contacts[1].bad_separator_unknown and not p.contacts[1].touch_known
