"""Batch 1: local evidence and source lifetimes, not foot recovery rules."""
from copy import deepcopy
from dataclasses import fields
import json
from pathlib import Path

import numpy as np
import pytest

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.modes.walking_processor import WalkingProcessor
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.walking_preflight import PreparedDevice


@pytest.fixture(scope='module')
def field_replay(request):
    mode = request.param
    root = Path(__file__).resolve().parents[1]
    source = root / 'exports/ground_field_20261010_audit' / mode
    meta = json.loads((source / 'metadata.json').read_text())
    dev = meta['device']
    geometry = dev['layout']
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in geometry['segments']),
                          tuple(geometry['invalid_bit_indices']))
    device = PreparedDevice(layout, dev['stream_id'], dev['checked_sample_index'],
                            dev['checked_monotonic_ns'], dev['healthy_samples'], bad_indices=tuple(dev['bad_indices']))
    config, factory = (WalkingConfig, WalkingProcessor) if mode == 'walk' else (OvergroundRunningConfig, OvergroundRunningProcessor)
    p = factory(config(**{k: v for k, v in meta.items() if k in {f.name for f in fields(config) if f.init}}), device)
    optical = GroundStabilityFilter(layout, device.bad_indices)
    selected = {45694, 45696, 102726, 103055, 104271, 104572, 105474, 105796}
    snapshots = {}
    def consume(frame):
        p.process(frame, masked_contact=uncertain_contact(frame, device.bad_indices))
        if frame.sample_index in selected:
            snapshots[frame.sample_index] = deepcopy(p)
    with np.load(source / 'matched_usb.npz') as data:
        counters = data['frame_indices']
        samples = data['sample_indices'] if 'sample_indices' in data else counters
        for n, index, bits in zip(samples, counters, data['bits']):
            frame = SensorFrame(device.stream_id, layout, int(index), int(n), int(n) + 1,
                                bits.tobytes(), b'\x01' * layout.bit_count, b'')
            for measured in optical.feed(masked_frame(frame, device.bad_indices)):
                consume(measured)
    for measured in optical.flush():
        consume(measured)
    return mode, p, snapshots


@pytest.mark.parametrize('field_replay', ['walk'], indirect=True)
def test_field_45694_does_not_cancel_remote_candidate(field_replay):
    mode, _, snapshots = field_replay
    assert mode == 'walk'
    for sample, votes in [(45694, 58), (45696, 60)]:
        c = next(c for c in snapshots[sample].contacts if round(c.start * 1000) == 45637)
        assert c.touch_known and c.position_known
        assert c.observed_samples == votes
        assert c.confirmed == (sample == 45696)


@pytest.mark.parametrize('sample,first', [(102726, 102723), (104271, 104264), (105474, 105473)])
@pytest.mark.parametrize('field_replay', ['run'], indirect=True)
def test_field_running_group_keeps_sources_and_grows(field_replay, sample, first):
    mode, final, snapshots = field_replay
    assert mode == 'run'
    before = next(g for g in snapshots[sample]._ownership_groups
                  if any(s['first_sample'] == first for s in g['sources']))
    after = next(g for g in final._ownership_groups if g['id'] == before['id'])
    assert len(before['sources']) >= 2
    assert any(r.get('ownership_group_id') == before['id']
               for r in snapshots[sample]._local_regions)
    assert before['state'] == 'observing'
    assert after['observed_samples'] > before['observed_samples'] + 100
    assert after['state'] == 'closed_unknown'
    assert after['occupancy_end_sample'] is not None
    assert after['observed_samples'] == sum(b - a for a, b in after['valid_sample_intervals'])
    assert all(a < b for a, b in after['valid_sample_intervals'])
    assert all(a[1] < b[0] for a, b in zip(after['valid_sample_intervals'], after['valid_sample_intervals'][1:]))
    assert after['unresolved_since_sample'] == before['unresolved_since_sample']
    assert not any(c.first_seen_sample == first and c.touch_known and c.confirmed for c in snapshots[sample].contacts)  # no confirmation merely from connecting


def make(mode):
    layout = DeviceLayout.linear(8)
    dev = PreparedDevice(layout, 'groups', -1, 0, 1000)
    if mode == 'walk':
        return WalkingProcessor(WalkingConfig(stop_type='Software command', stop_threshold_s=.1), dev)
    return OvergroundRunningProcessor(OvergroundRunningConfig(stop_type='Software command',
                                      min_contact_time=60, stop_threshold_s=.1), dev)


def feed(p, n, groups, **kwargs):
    bits = bytearray(len(p.positions))
    for low, high in groups:
        bits[low:high + 1] = b'\x01' * (high - low + 1)
    frame = SensorFrame('groups', p.device.layout, n, n, n + 1, bytes(bits), b'\x01' * len(bits), b'')
    p.process(frame, **kwargs)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_group_budget_union_split_and_clear(mode):
    p = make(mode)
    for n in range(2400):
        groups = []
        if n == 100:
            groups = [(40, 43), (46, 49)]
        elif 101 <= n < 2300:
            groups = [(40, 49)]
            if 400 <= n < 450:
                groups = [(40, 43), (46, 49)]
            if 1800 <= n < 1810:
                groups += [(52, 54)]
            if n >= 1810:
                groups = [(40, 54)]
        feed(p, n, groups)
        if n == 1100:
            g = p._ownership_groups[0]
            assert g['state'] == 'observing'  # independent of stop_threshold_s
            assert g['observed_samples'] == 1001
        if n == 2200:
            g = p._ownership_groups[0]
            assert g['state'] == 'closed_unknown' and g['close_reason'] == 'observation_budget'
            assert g['occupancy_end_sample'] is None
            assert g['unresolved_since_sample'] <= 101
    g = p._ownership_groups[0]
    assert g['valid_sample_intervals'] == [[100, 2300]]
    assert g['observed_samples'] == 2200
    assert g['occupancy_end_sample'] == 2300
    assert len(g['sources']) >= 3
    assert not any(c.confirmed and c.touch_known for c in p.contacts)


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_group_gap_closes_without_inventing_release(mode):
    p = make(mode)
    for n in range(200):
        feed(p, n, [(40, 43), (46, 49)] if n == 100 else [(40, 49)] if n > 100 else [])
    feed(p, 205, [(40, 49)])
    g = p._ownership_groups[0]
    assert g['state'] == 'closed_unknown' and g['close_reason'] == 'frame_gap'
    assert g['valid_sample_intervals'] == [[100, 200]]
    assert g['occupancy_end_sample'] is None


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_merging_groups_keeps_oldest_budget_and_union(mode):
    p = make(mode)
    for n in range(2150):
        groups = [(40, 43), (46, 49)] if n == 100 else [(40, 49)] if n > 100 else []
        if n == 600:
            groups += [(60, 63), (66, 69)]
        elif 600 < n < 1000:
            groups += [(60, 69)]
        if n >= 1000:
            groups = [(40, 69)]
        feed(p, n, groups)
    g = p._ownership_groups[0]
    assert g['merged_group_ids'] == [1]
    assert g['unresolved_since_sample'] == 100
    assert g['closed_sample'] == 2100
    assert g['valid_sample_intervals'] == [[100, 2150]]
    assert g['observed_samples'] == 2050
    assert len(g['sources']) == 4
    assert p._ownership_groups[1]['merged_into'] == 0


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_mature_overlap_does_not_vote_shared_samples_into_feet(mode):
    p = make(mode)
    counts = None
    for n in range(450):
        groups = [(40, 60)] if 100 <= n else []
        if n >= 200:
            groups += [(65, 85)]
        if n >= 300:
            groups = [(40, 85)]
        feed(p, n, groups)
        if n == 299:
            counts = [c.observed_samples for c in p.contacts]
    assert [c.observed_samples for c in p.contacts] == counts
    assert all(c.confirmed and c.touch_known for c in p.contacts)
    g = p._ownership_groups[0]
    assert g['observed_samples'] == 350
    assert g['valid_sample_intervals'] == [[100, 450]]


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_manual_report_closes_group_once_and_summary_is_read_only(mode):
    p = make(mode)
    for n in range(200):
        feed(p, n, [(40, 43), (46, 49)] if n == 100 else [(40, 49)] if n > 100 else [])
    before = deepcopy(p._ownership_groups)
    p.summary()
    assert p._ownership_groups == before
    assert before[0]['state'] == 'observing'
    report = p.build_report('manual')
    again = p.build_report('manual')
    key = 'walking_summary' if mode == 'walk' else 'running_summary'
    assert getattr(report, key) == getattr(again, key)
    g = p._ownership_groups[0]
    assert g['state'] == 'closed_unknown' and g['close_reason'] == 'manual'
    assert g['occupancy_end_sample'] is None


@pytest.mark.parametrize('mode', ['walk', 'run'])
def test_source_join_after_timeout_does_not_reopen_or_predate_its_closure(mode):
    p = make(mode)
    for n in range(2350):
        groups = [(40, 43), (46, 49)] if n == 100 else [(40, 49)] if n > 100 else []
        if 2200 <= n < 2210:
            groups += [(52, 54)]
        if n >= 2210:
            groups = [(40, 54)]
        feed(p, n, groups)
    p.build_report('manual')
    g = p._ownership_groups[0]
    assert g['closed_sample'] == 2100 and g['close_reason'] == 'observation_budget'
    assert g['valid_sample_intervals'] == [[100, 2350]]
    late = next(s for s in g['sources'] if s['first_sample'] == 2200)
    assert late['closed_sample'] >= late['joined_sample']
    assert late['outcome'] == 'unresolved'
