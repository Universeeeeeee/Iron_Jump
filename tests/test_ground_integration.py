"""Consumer compatibility for certified centres; no ownership changes."""
from copy import deepcopy
import json

import pytest
from qtpy.QtWidgets import QTextBrowser

from reporting.builders import ReportDataPackageBuilder, ReportManifestBuilder
from reporting.models import ReportContextInput, DataAccessScope, DataScopeAvailability
from reporting.observation import ObservationBuilder
from reporting.excel import build_report_workbook
from reporting.repository import ReportRepository
from data.subject_store import SubjectStore
from ui.views.report_view import ReportView
from ui.ground_track import GroundTrackPanel


@pytest.fixture(scope='module')
def certified_report():
    from pathlib import Path
    from config.test_report import GaitTestReport
    s = json.loads((Path(__file__).parents[1] / 'exports/ground_centre_E_20261011/after/walk/summary.json').read_text())
    return GaitTestReport(11, 10, tuple(s['step_lengths_m']), (), s['mean_step_m'], None,
                          s['walking_speed_m_s'], None, walking_summary=s)


def package(report):
    return ReportDataPackageBuilder().build(report, ReportContextInput(session_id=1, test_type='Sprint and Gait Test'))


def test_certified_centre_reaches_report_and_history(qtbot, certified_report):
    report = deepcopy(certified_report)
    c = report.walking_summary['contacts'][13]
    c['position_m'] = 7.442  # Old diagnostic value must not override the certificate.
    assert c['centre_m']['value'] == pytest.approx(7.429)
    assert not c['position_known'] and c['exclusion']
    view = ReportView(); qtbot.addWidget(view); view.load_report(report)
    assert any('7.429' in b.toPlainText() for b in view.findChildren(QTextBrowser))
    assert any('位置有独立证据' in b.toPlainText() for b in view.findChildren(QTextBrowser))
    panel = GroundTrackPanel(); qtbot.addWidget(panel)
    panel.render_state({'positions_m': [0., 8.], 'contact_bits': [0, 0], 'timestamp_s': 100})
    panel.set_summary(report.walking_summary)
    assert any(h['centroid_cm'] == pytest.approx(742.9) for h in panel.channel.history)


def test_centre_storage_excel_and_agent_agree(tmp_path, certified_report):
    from config.walking_config import WalkingConfig
    from openpyxl import load_workbook
    report = deepcopy(certified_report)
    report.walking_summary['contacts'][13]['position_m'] = 7.442
    store = SubjectStore(tmp_path / 'integration.sqlite3')
    sid = store.record_session(None, WalkingConfig(), report)
    restored = store.get_session(sid).report
    assert restored.walking_summary == report.walking_summary
    p = ReportRepository(store).get_package(sid)
    c = next(r for r in p.record_sets[0].records if r.source_index == 13)
    assert c.values['centre_m'].value == pytest.approx(7.429)
    assert c.status.validity == 'valid' and c.status.inclusion == 'included'
    assert p.payload.record_sources[c.record_id]['row']['exclusion']
    step = next(r for r in p.record_sets[1].records if
                p.payload.record_sources[r.record_id]['row']['to_id'] == 13)
    assert step.values['step_length_m'].value == pytest.approx(.7998)
    obs = ObservationBuilder().build(p, ReportManifestBuilder().build(p), DataScopeAvailability(), DataAccessScope(), ())
    text = obs.model_dump_json()
    assert '7.429' in text and '0.7998' in text
    book = build_report_workbook(restored); path = tmp_path / 'saved.xlsx'; book.save(path); book.close()
    book = load_workbook(path, read_only=True)
    rows = list(book['Walking contacts'].values); columns = rows[0]
    x = next(dict(zip(columns, row)) for row in rows[1:] if row[columns.index('id')] == 13)
    assert x['position_m'] == pytest.approx(7.429)
    assert x['diagnostic_position_m'] == pytest.approx(7.442)
    steps = list(book['Walking steps'].values)
    x = next(dict(zip(steps[0], row)) for row in steps[1:] if row[steps[0].index('to_id')] == 13)
    assert x['length_m'] == pytest.approx(.7998)
    book.close()


def test_explicit_invalid_centre_never_uses_legacy_number(qtbot, certified_report):
    report = deepcopy(certified_report)
    c = report.walking_summary['contacts'][13]
    c.update(position_known=True, exclusion=None, position_m=99.1234,
             centre_m={'value': None, 'valid': False, 'missing_reason': 'unresolved_position_source'})
    p = package(report)
    x = next(r for r in p.record_sets[0].records if r.source_index == 13)
    assert x.values['centre_m'].state == 'invalid' and x.values['centre_m'].value is None
    assert x.values['contact_time_s'].state == 'present'
    view = ReportView(); qtbot.addWidget(view); view.load_report(report)
    assert all('99.1234' not in b.toPlainText() for b in view.findChildren(QTextBrowser))
    panel = GroundTrackPanel(); qtbot.addWidget(panel)
    panel.render_state({'positions_m': [0., 8.], 'contact_bits': [0, 0], 'timestamp_s': 100})
    panel.set_summary(report.walking_summary)
    assert all(h['centroid_cm'] != 9912.34 for h in panel.channel.history)
    book = build_report_workbook(report); rows = list(book['Walking contacts'].values)
    x = next(dict(zip(rows[0], row)) for row in rows[1:] if row[rows[0].index('id')] == 13)
    assert x['position_m'] is None and x['diagnostic_position_m'] == 99.1234
    book.close()


def test_legacy_report_keeps_original_position_interpretation(qtbot, certified_report):
    report = deepcopy(certified_report)
    for c in report.walking_summary['contacts']:
        c.pop('centre_m', None)
    c = report.walking_summary['contacts'][13]
    c.update(position_known=True, exclusion=None, position_m=7.442)
    p = package(report)
    assert 'centre_m' not in p.record_sets[0].metric_codes
    view = ReportView(); qtbot.addWidget(view); view.load_report(report)
    assert any('7.442' in b.toPlainText() for b in view.findChildren(QTextBrowser))
    c['position_known'] = False
    view.load_report(report)
    assert all('7.442' not in b.toPlainText() for b in view.findChildren(QTextBrowser))


@pytest.mark.parametrize('mode,stop_sample', [('walk', None), ('run', None), ('walk', 50140), ('walk', 50145)])
def test_real_session_queued_delivery_and_stop_flush(tmp_path, mode, stop_sample):
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).parents[1]
    command = [sys.executable, str(root / 'exports/ground_minimal_fixes_F_20261011/session_acceptance.py'),
               '--mode', mode, '--output-dir', str(tmp_path / 'session')]
    if stop_sample is not None: command += ['--stop-sample', str(stop_sample)]
    result = subprocess.run(command, capture_output=True, timeout=60)
    (tmp_path / 'stdout.bin').write_bytes(result.stdout)
    (tmp_path / 'stderr.bin').write_bytes(result.stderr)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')
    assert b'Traceback' not in result.stderr
    data = json.loads((tmp_path / 'session/result.json').read_text())
    assert data['reports_identical'] and data['publication_idempotent']
    assert data['final_ui_summary_equal']
    if stop_sample is None:
        assert data['summary_semantics_equal_frozen_E']
        assert all(e['action'] in {'contact_competition', 'direction_established', 'direction_turn', 'source_uncertainty_resolved'}
                   for e in data['additional_audit'])
    if mode == 'walk':
        c, received = data['calculated']['13'], data['consumer_receipt']['13']
        assert c['evidence_available_sample'] == 50135
        assert c['evaluation_formal_sample'] >= c['evidence_available_sample']
        assert received['received_host_ns'] >= c['calculated_host_ns']
        assert received['value'] == pytest.approx(7.429)
        assert received['latest_stride_cm'] == pytest.approx(79.98)
        assert received['touch_count'] == 11


@pytest.mark.parametrize('reason', ['unresolved_fragment_join', 'pending_touch_order', 'masked_contact_boundary'])
def test_centre_independent_of_duration_and_audit_preserved(certified_report, reason):
    report = deepcopy(certified_report); c = report.walking_summary['contacts'][13]
    c['exclusion'] = reason
    c['contact_s'] = {'value': None, 'valid': False, 'missing_reason': 'unobserved_duration'}
    before = deepcopy(report.walking_summary)
    p = package(report); row = next(r for r in p.record_sets[0].records if r.source_index == 13)
    assert row.status.inclusion == 'included' and row.status.validity == 'valid'
    assert row.values['centre_m'].value == pytest.approx(7.429)
    assert row.values['contact_time_s'].state == 'invalid'
    flags = [f for f in p.quality_flags if f.source_ref == row.record_id and f.code == reason]
    assert len(flags) == 1
    assert report.walking_summary == before


def test_actual_agent_service_receives_certified_position_and_step(tmp_path, certified_report):
    from agent.report.service import ReportAnalysisService
    from tests.test_report_analysis_service import _SequentialServiceFakeAgent
    from reporting.models import DraftAnalysisPackage
    from config.walking_config import WalkingConfig
    seen = []
    class Agent(_SequentialServiceFakeAgent):
        def decide(self, observation, state, evidence, skill_context):
            text = observation.model_dump_json()
            assert '7.429' in text and '0.7998' in text
            seen.append('decide')
            return super().decide(observation, state, evidence, skill_context)
        def synthesize_sequential(self, observation, state, evidence, skill_context):
            assert '7.429' in observation.model_dump_json()
            seen.append('synthesize')
            return DraftAnalysisPackage(summary='按分项有效性读取当前报告。', claims=())
    store = SubjectStore(tmp_path / 'agent.sqlite3')
    sid = store.record_session(None, WalkingConfig(), certified_report)
    service = ReportAnalysisService(ReportRepository(store), agent=Agent(), rag_unavailable_error_code='rag_release_gate_invalid')
    result = service.analyze(sid, DataAccessScope())
    assert result.cycle_count == 1 and not result.claims
    assert seen == ['decide', 'decide', 'synthesize']
