"""The walking detail view must distinguish occupancy release from foot lift."""
from qtpy.QtWidgets import QTextBrowser

from tests.test_walking_temporal_islands import replay
from ui.views.report_view import ReportView


def test_unresolved_foot_join_does_not_display_an_individual_lift(qtbot):
    p = replay(lambda n: ([(60, 80)] if 100 <= n < 277 else
                          [(60, 90)] if 277 <= n < 400 else [])
               + ([(90, 90)] if 220 <= n < 277 or 400 <= n < 500 else []))
    c = p.contacts[0]
    assert c.end is not None and c.exclusion == 'unresolved_fragment_join'
    assert p.summary()['contacts'][0]['lift_sample'] is None
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(p.build_report('manual'))
    details = next(b.toPlainText() for b in view.findChildren(QTextBrowser)
                   if '接触记录' in b.toPlainText())
    contact_table = details.split('候选判定证据')[0]
    assert '遮挡来源归属未决，单脚边界未知' in contact_table
    assert str(c.end - p.origin) not in contact_table


def test_running_unresolved_source_has_a_chinese_report_reason():
    from dataclasses import replace
    from tests.test_overground_running import processor, frame
    from reporting.overground_running import detail_html
    p = processor(min_contact_time=60, stop_type='Software command')
    for n in range(650):
        groups = ([(60, 80)] if 100 <= n < 277 else [(60, 90)] if 277 <= n < 400 else [])
        groups += [(90, 90)] if 220 <= n < 277 or 400 <= n < 500 else []
        bits = bytearray(len(p.positions))
        for low, high in groups:
            bits[low:high + 1] = b'\x01' * (high - low + 1)
        p.process(replace(frame(p.device.layout, n), contact_bits=bytes(bits)))
    report = p.build_report('manual')
    assert not report.running_summary['contacts'][0]['lift_s']['valid']
    assert '遮挡来源归属未决，单脚边界未知' in detail_html(report)
