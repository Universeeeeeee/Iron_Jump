"""An interior landing survives later toe clipping at the exit boundary."""
import json
from pathlib import Path

import numpy as np
import pytest

from config.walking_config import WalkingConfig
from engine.modes.walking_processor import WalkingProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.beam_quality import masked_frame, uncertain_contact
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.walking_preflight import PreparedDevice
from tests.test_ground_candidate_groups import make, feed


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('restriction', [None, 'entry_clipped', 'frame_gap', 'wrong_exit'])
def test_exit_clipping_preserves_only_an_observed_interior_onset(reverse, restriction):
    p = make('walk')
    for n in range(1500):
        if restriction == 'frame_gap' and n == 1030:
            continue
        groups = [(200, 220)] if 100 <= n < 300 else [(400, 420)] if 500 <= n < 700 else []
        base = 0 if restriction == 'entry_clipped' else 741
        if 1000 <= n < 1003:
            groups += [(base, base + 3)]
            if n == 1002:
                groups += [(base + 9, base + 10)]
        if 1003 <= n < 1300:
            groups += [(base, 26 if restriction == 'entry_clipped' else 767)]
        if restriction == 'wrong_exit' and n >= 1000:
            groups = [(767 - b, 767 - a) for a, b in reversed(groups)]
        if reverse:
            groups = [(767 - b, 767 - a) for a, b in reversed(groups)]
        feed(p, n, groups)
    terminal = [e for e in p.touch_events if e['active'] and e['touch_sample'] == 1000]
    assert bool(terminal) == (restriction is None)
    if terminal:
        assert len(terminal) == 1
        assert not any(e['action'] == 'retract' and e['contact_id'] == terminal[0]['contact_id'] for e in p.event_audit)


def test_field_terminal_footprint_reaches_history_and_completed_detail_rows(qtbot):
    from ui.ground_track import GroundTrackPanel
    from data.subject_store import _report_detail, _report_from_detail
    folder = Path(__file__).parent / 'fixtures/ground'
    meta = json.loads((folder / 'walk_20261028_134902.json').read_text())
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in meta['device']['layout']['segments']))
    device = PreparedDevice(layout, meta['device']['stream_id'], 29999, 0, 3000,
                            bad_indices=tuple(meta['device']['bad_indices']))
    p = WalkingProcessor(WalkingConfig(**meta['config']), device)
    optical = GroundStabilityFilter(layout, device.bad_indices)
    with np.load(folder / 'walk_20261028_134902.npz') as data:
        for n, packed in zip(data['samples'], data['packed_contacts']):
            n = int(n)
            f = SensorFrame(device.stream_id, layout, n, n, n * 1000000,
                            np.unpackbits(packed, bitorder='little').tobytes(), b'\x01' * 768,
                            (255 - packed).tobytes())
            for measured in optical.feed(masked_frame(f, device.bad_indices)):
                p.process(measured, masked_contact=uncertain_contact(measured, device.bad_indices))
    for measured in optical.flush():
        p.process(measured, masked_contact=uncertain_contact(measured, device.bad_indices))
    assert p.reliable_touch_count == 13
    terminal = [e for e in p.touch_events if e['touch_sample'] == 38069]
    assert len(terminal) == 1 and terminal[0]['active']
    assert terminal[0]['published_sample'] == 38128
    report = p.build_report('manual')
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    panel.render_state({'positions_m': p.positions, 'segment_ids': tuple(str(i + 1) for i in range(8)),
                        'contact_bits': [0] * 768, 'valid_bits': [1] * 768, 'feet': [],
                        'timestamp_s': 39 - p.origin, 'sample_index': 39000})
    panel.set_summary(report.walking_summary)
    assert any(f.get('contact_id') == terminal[0]['contact_id'] for f in panel.channel.history)
    s = report.walking_summary
    assert len(s['footfalls']) == 13
    for i, row in enumerate(s['footfalls']):
        assert all(row[key]['valid'] for key in ('contact_s', 'lift_s', 'centre_m'))
        if i:
            assert row['step_time_s']['valid'] and row['step_length_m']['valid']
    assert s['metric_completion']['source_records']['footfalls']
    assert _report_from_detail(_report_detail(report)).walking_summary == s
