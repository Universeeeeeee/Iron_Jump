"""Lossless field replay of eight landings that Windows v1.9 reported as four."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from config.overground_running_config import OvergroundRunningConfig
from engine.modes.overground_running_processor import OvergroundRunningProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.walking_preflight import PreparedDevice


def test_eight_field_landings_keep_original_time_without_counting_toe_fragments():
    folder = Path(__file__).parent / 'fixtures/ground'
    meta = json.loads((folder / 'run_20261028_012812.json').read_text())
    device = meta['device']
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in device['layout']['segments']))
    bad = tuple(device['bad_indices'])
    prepared = PreparedDevice(layout, device['stream_id'], meta['sample_range'][0] - 1,
                              0, 3000, bad_indices=bad)
    p = OvergroundRunningProcessor(OvergroundRunningConfig(**meta['config']), prepared)
    optical = GroundStabilityFilter(layout, bad)
    with np.load(folder / 'run_20261028_012812.npz') as data:
        packed = data['packed_contacts']
        bits = np.unpackbits(packed, axis=1, bitorder='little')
        original = bits.copy()
        for sample, contact, payload in zip(data['samples'], bits, packed):
            n = int(sample)
            frame = SensorFrame(device['stream_id'], layout, n, n, n * 1000000,
                                contact.tobytes(), b'\x01' * layout.bit_count,
                                (255 - payload).tobytes())
            for measured in optical.feed(masked_frame(frame, bad)):
                p.process(measured, masked_contact=uncertain_contact(measured, bad))
        assert np.array_equal(bits, original)
    for measured in optical.flush():
        p.process(measured, masked_contact=uncertain_contact(measured, bad))
    events = [e for e in p.touch_events if e['active']]
    assert [e['touch_sample'] for e in events] == meta['reference_touch_samples']
    assert len({e['event_id'] for e in events}) == 8
    assert p.config.min_contact_time == 60
    assert max(e['published_sample'] - e['touch_sample'] for e in events) < 80
    s = p.summary()
    assert s['valid_touches'] == 8 and s['valid_steps'] == 7
    assert all(step['time_s']['valid'] for step in s['steps'])
    audit = deepcopy(p.event_audit)
    assert p.summary() == s and p.event_audit == audit
    # Later attribution retains the original publication's source proof.
    expanded = [g for g in p._ownership_groups
                if any(d['reason'] == 'continuous_early_local_projection'
                       for d in g.get('source_decisions', []))]
    assert expanded
    for g in expanded:
        publication = next(e for e in p.event_audit
                           if e['action'] == 'ownership_recovered' and e['group_id'] == g['id'])
        assert g['recovery']['source_ids'] == publication['source_ids']
