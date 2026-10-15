"""Healthy terminal release does not certify an entire masked stance."""
from dataclasses import replace
import pytest
from tests.test_ground_candidate_groups import field_replay
from config.walking_config import WalkingConfig
from engine.modes.walking_processor import WalkingProcessor
from hardware.sensor_frame import DeviceLayout, SensorFrame
from hardware.walking_preflight import PreparedDevice
from hardware.beam_quality import masked_frame, uncertain_contact


def terminal_capture(damage=None, reverse=False):
    layout = DeviceLayout.linear(8)
    bad = 191 if reverse else 576
    device = PreparedDevice(layout, 'terminal', -1, 0, 1000, bad_indices=(bad,))
    p = WalkingProcessor(WalkingConfig(stop_type='Software command'), device)
    for n in range(310 if damage == 'manual' else 340):
        if damage == 'gap' and n == 245:
            continue
        groups = [(550,570)] if 100 <= n < 200 else [(560,578)] if 200 <= n < 260 else [(578,580)] if 260 <= n < 300 else [(580,580)] if 300 <= n < 310 else []
        if damage == 'near_bad' and 260 <= n < 310:
            groups = [(577,580)]
        if damage == 'short_suffix' and 260 <= n < 308:
            groups = [(577,580)]
        if damage == 'replacement' and 200 <= n < 260:
            groups = [(560,575)]
        if damage == 'blind_gap' and 240 <= n < 245:
            groups = []
        if damage == 'unclear_release' and n == 315:
            groups = [(583,583)]
        if damage == 'competing_owner':
            if 180 <= n < 260:
                groups += [(583,602)]
            elif 260 <= n < 280:
                groups = [(560,602)]
        bits = bytearray(768);bits[bad] = 1
        for lo,hi in groups:
            if reverse:lo,hi = 767-hi,767-lo
            bits[lo:hi+1] = b'\x01'*(hi-lo+1)
        frame = SensorFrame(device.stream_id,layout,n,n,n*1_000_000,bytes(bits),b'\x01'*768,b'')
        if damage == 'invalid' and n == 245:
            frame = replace(frame,valid_bits=b'\x00'*768)
        frame = masked_frame(frame,device.bad_indices)
        p.process(frame,masked_contact=uncertain_contact(frame,device.bad_indices))
    return p


@pytest.mark.parametrize('reverse', [False,True])
def test_healthy_terminal_release_keeps_masked_duration_and_position_unknown(reverse):
    p = terminal_capture(reverse=reverse)
    c = p.contacts[0];s = p.summary();row = s['contacts'][0]
    assert c.end == pytest.approx(.310)
    assert c.lift_confirmed_at == pytest.approx(.320)
    assert c.exclusion == 'masked_contact_boundary' and not c.position_known
    assert row['lift_s']['valid'] and row['lift_sample'] == 310
    assert not row['contact_s']['valid'] and row['contact_s']['value'] is None
    assert row['contact_s']['missing_reason'] == 'contact_continuity_unknown'
    assert s['valid_contact_durations'] == s['valid_support_cycles'] == 0
    evidence = row['metric_evidence']['lift']
    assert evidence['basis'] == 'healthy_terminal_release'
    assert evidence['healthy_suffix_interval'] == [260,310]
    assert evidence['clear_interval'] == [310,321]
    assert evidence['association_valid'] and not evidence['occupancy_valid']
    events = p.touch_events
    first = p.build_report('manual');second = p.build_report('manual')
    assert first.lift_count == second.lift_count == 1
    assert first.touch_count == second.touch_count == 1 and p.touch_events == events
    assert first.avg_single_support is None and first.avg_double_support is None


@pytest.mark.parametrize('damage', ['near_bad','short_suffix','replacement','blind_gap','gap','invalid','unclear_release','manual','competing_owner'])
def test_terminal_release_requires_healthy_association_suffix_and_clear(damage):
    p = terminal_capture(damage)
    c = next(c for c in p.contacts if c.start == pytest.approx(.1))
    row = next(r for r in p.summary()['contacts'] if r['id'] == c.id)
    if damage != 'competing_owner':
        assert c.end is None
    assert not row['lift_s']['valid'] and not row['contact_s']['valid']


def test_terminal_release_survives_session_save_and_export_without_valid_duration(qtbot):
    from engine.overground_session import OvergroundSession
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from reporting.excel import build_report_workbook
    p = terminal_capture()
    session = OvergroundSession(p.config, WalkingProcessor)
    session.start_prepared(p.device);session.processor = p
    snapshots = [];session.snapshot.connect(snapshots.append)
    session.halt()
    report = session.build_report('manual')
    restored = _report_from_detail(_report_detail(report))
    assert restored.touch_count == restored.lift_count == 1
    assert snapshots[-1]['walking']['contacts'][0]['lift_sample'] == 310
    row = restored.walking_summary['contacts'][0]
    assert row['metric_evidence']['lift']['basis'] == 'healthy_terminal_release'
    assert not row['contact_s']['valid']
    package = ReportDataPackageBuilder().build(restored, ReportContextInput(session_id=1,test_type='Sprint and Gait Test'))
    value = package.record_sets[0].records[0].values['contact_time_s']
    assert value.state == 'invalid' and value.reason == 'contact_continuity_unknown'
    book = build_report_workbook(restored)
    exported = str(list(book['Walking contacts'].values))
    assert 'healthy_terminal_release' in exported and 'contact_continuity_unknown' in exported
    book.close()


@pytest.mark.parametrize('field_replay', ['walk'], indirect=True)
def test_field_47722_recovers_only_terminal_boundary(field_replay):
    _,p,_ = field_replay
    s = p.summary();row = next(c for c in s['contacts'] if c['touch_sample'] == 47722)
    assert row['lift_sample'] == 48621
    assert row['metric_evidence']['lift']['confirmed_sample'] == 48631
    assert row['metric_evidence']['lift']['healthy_suffix_interval'] == [48581,48621]
    assert row['metric_evidence']['lift']['checked_beams'] == [577,583]
    assert not row['contact_s']['valid'] and not row['position_known']
    assert row['contact_s']['missing_reason'] == 'contact_continuity_unknown'
    origin = min(c['touch_sample'] for c in s['contacts'] if c['touch_sample'] is not None)
    affected = [r for r in s['cycles'] if round(origin+r['start_s']*1000) == 47722]
    assert len(affected) == 1 and affected[0]['single_support_s'] is None
    assert affected[0]['double_support_s'] is None
    assert s['valid_touches'] == 11
