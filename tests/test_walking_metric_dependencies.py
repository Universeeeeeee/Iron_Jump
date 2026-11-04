"""Each walking metric uses only its own observed boundaries and relationships."""
from dataclasses import replace

import pytest

from hardware.walking_preflight import PreparedDevice
from tests.test_overground_walking import frame, processor, walk


@pytest.mark.parametrize('segments', [3, 8])
def test_last_touch_keeps_step_and_cycle_without_its_future_lift(segments):
    p = processor(segments, stop_type='Software command', starting_foot='Left')
    walk(p, [(100, 300, .35), (220, 500, .95), (420, 800, 1.55)], 600)
    s = p.summary()
    assert p.contacts[-1].confirmed and p.contacts[-1].end is None
    assert s['valid_steps'] == 2
    assert s['steps'][-1]['time_s'] == pytest.approx(.2)
    assert s['valid_cycles'] == 1
    assert s['cycles'][0]['duration_s'] == pytest.approx(.32)
    assert s['cycles'][0]['single_support_s'] == pytest.approx(.24)
    assert s['cycles'][0]['double_support_s'] == pytest.approx(.08)
    assert s['mean_contact_s'] == pytest.approx(.24)
    assert p.build_report('manual').lift_count == 2


def later_masked_walk():
    p = processor(8, stop_type='Software command', starting_foot='Left')
    p.device = PreparedDevice(p.device.layout, 'test', -1, 0, 3000, bad_indices=(576,))
    for n in range(900):
        bits = bytearray(768)
        if 100 <= n < 600:
            lo, hi = (550, 570) if n < 250 else (557, 578)
            bits[lo:hi+1] = b'\x01'*(hi-lo+1)
            bits[576] = 0
        if 400 <= n < 750:
            bits[620:642] = b'\x01'*22
        if 700 <= n < 850:
            bits[680:702] = b'\x01'*22
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)),
                  masked_contact=250 <= n < 600)
    return p


def test_later_mask_keeps_known_touch_times_but_not_unknown_position_or_support():
    p = later_masked_walk()
    s = p.summary()
    assert len(p.contacts) == 4
    assert [e['touch_sample'] for e in p.touch_events if e['active']] == [100, 400, 700]
    assert p.contacts[1].bad_separator_unknown
    assert not s['contacts'][0]['lift_s']['valid']
    assert not s['contacts'][0]['centre_m']['valid']
    assert s['valid_steps'] == s['valid_step_lengths'] == 1
    assert s['steps'][0]['time_s'] == pytest.approx(.3)
    assert s['valid_cycles'] == s['valid_support_cycles'] == 0
    assert s['valid_contact_durations'] == 2
    assert s['walking_speed_m_s'] == pytest.approx(s['steps'][0]['length_m'] / .3)


def test_healthy_initial_touch_next_to_bad_beam_stays_known():
    p = processor(8, stop_type='Software command')
    p.device = PreparedDevice(p.device.layout, 'test', -1, 0, 3000, bad_indices=(576,))
    for n in range(900):
        bits = bytearray(768)
        if 100 <= n < 600:
            bits[577:596] = b'\x01'*19
        if 400 <= n < 750:
            bits[620:642] = b'\x01'*22
        if 700 <= n < 850:
            bits[680:702] = b'\x01'*22
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)),
                  masked_contact=100 <= n < 600)
    s = p.summary()
    assert [(x['from_id'], x['to_id']) for x in s['steps']] == [(0, 1), (1, 2)]
    assert s['valid_cycles'] == 1


def test_reliable_clear_debounce_does_not_become_known_support():
    p = processor(stop_type='Software command')
    walk(p, [(100, 250, .35), (258, 350, .35),
             (220, 500, .95), (420, 650, 1.55)], 750)
    s = p.summary()
    assert len(p.contacts) == 3
    assert s['valid_steps'] == 2 and s['valid_cycles'] == 1
    assert p.contacts[0].merged_interruptions
    assert s['cycles'][0]['single_support_s'] is None
    assert s['cycles'][0]['double_support_s'] is None
    assert s['valid_support_cycles'] == 0


def test_unlocalized_mask_after_local_mask_still_breaks_remote_continuity():
    p = processor(8, stop_type='Software command')
    p.device = PreparedDevice(p.device.layout, 'test', -1, 0, 3000, bad_indices=(576,))
    for n in range(300):
        ranges = [(5.2, 5.4)] if n >= 100 else []
        if n >= 250:
            ranges += [(6.001, 6.2)]
        p.process(frame(p.device.layout, n, ranges), masked_contact=n >= 250)
    before = p.epoch
    # The source now reports an unknown location; only a remote foot is visible.
    p.process(frame(p.device.layout, 300, [(5.2, 5.4)]), masked_contact=True)
    assert p.epoch == before + 1
    assert not p.active


def test_gap_still_blocks_touch_intervals_even_when_both_touches_are_known():
    p = processor(stop_type='Software command')
    walk(p, [(100, 300, .35), (400, 600, .95), (700, 900, 1.55)],
         1000, skip={350})
    s = p.summary()
    assert [(x['from_id'], x['to_id']) for x in s['steps']] == [(1, 2)]
    assert s['valid_cycles'] == 0


def test_partial_metrics_survive_saved_report_package_and_excel(qtbot):
    from io import BytesIO
    from openpyxl import load_workbook
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.builders import ReportDataPackageBuilder
    from reporting.excel import build_report_workbook
    from reporting.models import ReportContextInput

    report = later_masked_walk().build_report('manual')
    restored = _report_from_detail(_report_detail(report))
    assert restored.walking_summary == report.walking_summary
    package = ReportDataPackageBuilder().build(restored, ReportContextInput(
        session_id=1, test_type='Sprint and Gait Test'))
    first_step = package.record_sets[1].records[0]
    assert first_step.status.validity == 'valid'
    assert first_step.values['step_time_s'].value == pytest.approx(.3)
    assert first_step.values['step_length_m'].value is not None
    assert first_step.values['speed_m_s'].value is not None
    for code, count in [('step_length_m', 1), ('speed_m_s', 1),
                        ('cadence_steps_per_min', 1), ('single_support_s', 0)]:
        fact = next(f for f in package.scalar_facts if f.metric_code == code)
        assert fact.sample_count == count
    book = build_report_workbook(restored)
    stream = BytesIO()
    book.save(stream)
    book.close()
    stream.seek(0)
    saved = load_workbook(stream)
    steps = list(saved['Walking steps'].values)
    headers = steps[0]
    assert steps[1][headers.index('time_s')] == pytest.approx(.3)
    assert steps[1][headers.index('length_m')] is not None
    assert steps[1][headers.index('speed_m_s')] is not None
    saved.close()


def test_partial_metrics_report_uses_separate_time_and_position_counts(qtbot):
    from qtpy.QtWidgets import QTextBrowser
    from ui.views.report_view import ReportView

    report = later_masked_walk().build_report('manual')
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(report)
    detail = next(x for x in view.findChildren(QTextBrowser)
                  if '接触记录' in x.toPlainText())
    assert '坏束两侧归属未确定' in detail.toPlainText()
    assert '数据不足' in detail.toPlainText()


@pytest.mark.parametrize('filtered', [False, True])
def test_disjoint_healthy_projection_does_not_inherit_bad_neighbor_censorship(filtered):
    from hardware.beam_filter import GroundStabilityFilter
    from hardware.beam_quality import uncertain_contact

    p = processor(8, stop_type='Software command')
    p.device = PreparedDevice(p.device.layout, 'test', -1, 0, 3000, bad_indices=(576,))
    optical = GroundStabilityFilter(p.device.layout, p.device.bad_indices)
    for n in range(900):
        bits = bytearray(768)
        if 100 <= n < 700:
            bits[500:521] = b'\x01'*21
        if 300 <= n < 312:
            bits[577:579] = b'\x01'*2
        elif 312 <= n < 800:
            bits[580:601] = b'\x01'*21
        raw = replace(frame(p.device.layout, n), contact_bits=bytes(bits))
        for measured in optical.feed(raw) if filtered else [raw]:
            p.process(measured, masked_contact=uncertain_contact(measured, p.device.bad_indices))
    if filtered:
        for measured in optical.flush():
            p.process(measured, masked_contact=uncertain_contact(measured, p.device.bad_indices))
    assert len(p.contacts) == 2
    healthy = p.contacts[1]
    assert healthy.exclusion is None and healthy.touch_known and healthy.position_known
    assert healthy.start == pytest.approx(.312) and healthy.end == pytest.approx(.8)
    assert not any(e['touch_sample'] == 300 for e in p.touch_events)
    assert p.summary()['valid_steps'] == 0


def test_remote_unresolved_candidate_does_not_invalidate_own_contact_duration():
    from hardware.beam_filter import GroundStabilityFilter

    p = processor(stop_type='Software command')
    optical = GroundStabilityFilter(p.device.layout)
    for n in range(1000):
        ranges = []
        if 100 <= n < 500:
            ranges.append((.2, .4))
        if 200 <= n < 212:
            ranges.append((.9, .91))
        if 600 <= n < 900:
            ranges.append((1.4, 1.6))
        for measured in optical.feed(frame(p.device.layout, n, ranges)):
            p.process(measured)
    for measured in optical.flush():
        p.process(measured)
    s = p.summary()
    assert p._narrow_barriers  # adjacency is still conservative in this phase
    assert s['valid_steps'] == 0
    assert s['mean_contact_s'] == pytest.approx(.35)
    assert s['valid_contact_durations'] == 2
