"""Regression checks for report navigation, exporting and preparation defaults."""
from dataclasses import replace
import unicodedata
from qtpy.QtWidgets import QFileDialog, QMessageBox
from data.subject_store import SubjectStore
from config.test_config import default_jump_config
from tests.reporting_fixtures import make_jump_report
from ui.views.history_view import HistoryView
from ui.views.report_view import ReportView
from ui.views.execution_view import ExecutionView
from reporting.contact_quality import contact_reason


def test_history_list_defers_large_report_until_open(qtbot, tmp_path, monkeypatch):
    store = SubjectStore(tmp_path / 'results.sqlite3')
    report = replace(make_jump_report([.2]), report_config_snapshot={'evidence': 'x' * 2_000_000})
    sid = store.record_session(None, default_jump_config(), report)
    view = HistoryView(store)
    qtbot.addWidget(view)
    view.load_all()
    selected = view._selected_session()
    assert selected.id == sid and selected.has_report
    assert selected.report_detail_json is None
    fetched = []
    original = store.get_session
    monkeypatch.setattr(store, 'get_session', lambda key: fetched.append(key) or original(key))
    opened = []
    view.open_report_requested.connect(opened.append)
    view._on_open_report_clicked()
    assert fetched == [sid]
    assert opened[0].report.report_config_snapshot['evidence'] == 'x' * 2_000_000
    assert view._session_table.item(0, 3).text() == '纵跳测试'


def test_preparation_enables_sdk_without_starting_before_preview(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(default_jump_config())
    view._camera_start_timer.stop()
    panel = view._camera_panel
    assert panel._chk_sdk_tracking.isChecked()
    assert panel._sdk_tracking and not panel._auto_tracking
    assert panel._control is None
    assert not panel._cmb_ai.isEnabled()
    panel._chk_sdk_tracking.setChecked(False)
    view.configure(default_jump_config())
    view._camera_start_timer.stop()
    assert panel._sdk_tracking


def test_contact_reason_distinguishes_duration_from_width():
    snapshot = {'min_contact_time': 60, 'confirmation_ms': 8}
    row = dict(exclusion='short_contact', start=0., end=.1, peak_width_m=.02, observed_samples=100)
    assert '足迹宽度不足' in contact_reason(row, snapshot)
    assert '接触过短' in contact_reason({**row, 'end': .005}, snapshot)
    assert '有效观测样本不足' in contact_reason({**row, 'peak_width_m': .1, 'observed_samples': 2}, snapshot)


def test_pdf_menu_exports_summary_without_raw_frames(qtbot, tmp_path, monkeypatch):
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(replace(make_jump_report([.2]), jump_heights=(.2,)))
    view.set_export_context({'display_name': '测试运动员'}, '2026-10-25 10:00')
    path = tmp_path / 'report.pdf'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(path), ''))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: None)
    def fail_export(*args):
        raise AssertionError(args[-1])
    monkeypatch.setattr(QMessageBox, 'warning', fail_export)
    view.btn_export.menu().actions()[0].trigger()
    from pypdf import PdfReader
    text = unicodedata.normalize('NFKC', ''.join(p.extract_text() for p in PdfReader(path).pages))
    assert '精简版' in text and '测试运动员' in text and '平均跳高' in text
    assert '逐次跳跃' not in text
    view.btn_export.menu().actions()[1].trigger()
    text = unicodedata.normalize('NFKC', ''.join(p.extract_text() for p in PdfReader(path).pages))
    assert '详细版' in text and '逐次跳跃' in text
