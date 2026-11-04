"""Seven recorded landings with local toe islands during normal forward walking."""
from dataclasses import fields
import json
from pathlib import Path

import numpy as np
import pytest

from config.walking_config import WalkingConfig
from engine.modes.walking_processor import WalkingProcessor
from hardware.beam_filter import GroundStabilityFilter
from hardware.sensor_frame import DeviceLayout, SensorFrame, SensorSegment
from hardware.walking_preflight import PreparedDevice


@pytest.fixture(scope='module', params=[False, True], ids=['forward', 'reverse'])
def five_meter_walk(request):
    source = Path(__file__).parent / 'fixtures/walking_5m_20261104'
    meta = json.loads((source / 'metadata.json').read_text())
    d = meta['device']
    layout = DeviceLayout(tuple(SensorSegment(**s) for s in d['layout']['segments']))
    device = PreparedDevice(layout, d['stream_id'], d['checked_sample_index'],
                            d['checked_monotonic_ns'], d['healthy_samples'])
    keys = {f.name for f in fields(WalkingConfig) if f.init}
    processor = WalkingProcessor(WalkingConfig(**{k: v for k, v in meta.items() if k in keys}), device)
    optical = GroundStabilityFilter(layout)
    with np.load(source / 'frames.npz') as data:
        for timestamp, bits in zip(data['timestamps'], data['bits']):
            sample = round(timestamp * 1000) + meta['origin_sample']
            bits = bits[::-1] if request.param else bits
            payload = (255 - np.packbits(bits, bitorder='little')).tobytes()
            frame = SensorFrame(device.stream_id, layout, sample, sample, sample * 1_000_000,
                                bits.tobytes(), b'\x01' * 480, payload)
            for measured in optical.feed(frame):
                processor.process(measured)
    for measured in optical.flush():
        processor.process(measured)
    return processor, processor.build_report('manual')


def test_seven_landings_retain_their_original_device_times(five_meter_walk):
    processor, report = five_meter_walk
    assert [e['touch_sample'] for e in processor.touch_events if e['active']] == [
        26879, 27566, 28207, 28861, 29483, 30141, 30793]
    assert report.touch_count == 7


def test_local_rolling_fragments_restore_contact_and_cycle_evidence(five_meter_walk):
    _, report = five_meter_walk
    s = report.walking_summary
    assert report.lift_count == s['valid_contact_durations'] == 7
    assert s['valid_steps'] == 6
    assert s['valid_cycles'] == s['valid_support_cycles'] == 5
    assert [c['duration_s'] for c in s['cycles']] == pytest.approx([1.328, 1.295, 1.276, 1.280, 1.310])
    assert [c['contact_s']['value'] for c in s['contacts'] if c['confirmed']] == pytest.approx(
        [.867, .833, .823, .817, .847, .819, .831])
    for cycle in s['cycles']:
        assert cycle['single_support_s'] + cycle['double_support_s'] == pytest.approx(cycle['duration_s'])


def test_report_consumers_use_resolved_source_certificates(five_meter_walk):
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.contact_quality import contact_quality_html
    from reporting.recognized_gait import recognized_gait
    from reporting.excel import build_report_workbook
    processor, report = five_meter_walk
    assert recognized_gait(processor.summary())['interval_count'] == 6
    s = report.walking_summary
    assert all(c['landing_reference']['valid'] for c in s['contacts'] if c['confirmed'])
    assert not s['metric_completion']['methods']
    assert '单脚边界未知' not in contact_quality_html(report)
    restored = _report_from_detail(_report_detail(report))
    assert restored.walking_summary == s
    book = build_report_workbook(restored)
    assert book['Walking cycles'].max_row == 6


def test_overlapping_attribution_intervals_are_counted_once():
    from reporting.contact_quality import merged_interval_duration_ms
    intervals = [{'start_sample': a, 'end_sample': b} for a,b in
                 [(26879, 26995), (26879, 27000), (26990, 27746)]]
    assert merged_interval_duration_ms(intervals) == 867
    assert merged_interval_duration_ms([]) == 0


def test_completed_contact_card_exposes_its_basis():
    from engine.ground_metric_completion import complete_ground_metrics
    from tests.test_ground_metric_completion import incomplete
    from ui.views.report_view import ReportView
    summary = complete_ground_metrics(incomplete(), 'walk')
    summary['valid_cycles'] = 0
    cards = [('平均接触时间', '', ''), ('有效步间 / 周期', '', '')]
    ReportView._apply_recognized_stats(cards, summary)
    assert cards[0][0] == '平均接触时间（补全）'
    assert '补全' in cards[0][2]
    assert cards[1][0] == '识别步间 / 有效周期'
