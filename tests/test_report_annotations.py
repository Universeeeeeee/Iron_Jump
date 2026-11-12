"""User-authored targets retain provenance, revisions and comparable baselines."""

import json
from dataclasses import replace

import pytest

from agent.report.service import ReportAnalysisService
from config.treadmill_config import TreadmillGaitConfig
from data.subject_store import SubjectStore
from reporting.annotations import AnnotationError, AnnotationReadRequest, AnnotationSaveRequest, annotations_html
from reporting.models import DataAccessScope
from reporting.repository import ReportRepository
from tests.reporting_fixtures import make_treadmill_report
from tests.test_report_analysis_service import _ServiceFakeAgent


def setup_annotations(tmp_path, guest=False):
    store = SubjectStore(tmp_path / 'notes.sqlite3')
    subject = None if guest else store.create_subject('Runner', 1990)
    config = TreadmillGaitConfig(stop_type='End of Time', test_length='01:00')
    session = store.record_session(subject, config, make_treadmill_report([.2]*6+[.4]*6, [.3]*6+[.5]*6))
    repository = ReportRepository(store)
    service = ReportAnalysisService(repository, agent=_ServiceFakeAgent())
    answer = service.analyze(session, DataAccessScope())
    read = AnnotationReadRequest(session_id=session, data_access_scope=DataAccessScope(longitudinal=not guest), analysis_run_id=answer.analysis_run_id)
    fact = service.get_annotations(read)['claims'][0]['facts'][0]
    save = AnnotationSaveRequest(**read.model_dump(), claim_id=answer.claims[0].claim_id,
                                 expected_revision=0, note='复测时关注节奏。', fact_id=fact['fact_id'],
                                 target_value=.3, target_direction='at_most')
    return store, service, read, save, config, subject


def test_notes_and_targets_are_versioned_user_records_with_conflict_detection(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    first = service.save_annotation(save)
    assert first['author_type'] == 'user'
    assert first['target']['baseline_value'] == pytest.approx(.35)
    assert first['revision'] == 1
    assert service.get_annotations(read)['annotations'][0]['note'] == save.note
    second = service.save_annotation(save.model_copy(update={'expected_revision':1, 'note':'关注左脚落地。'}))
    assert second['revision'] == 2
    with pytest.raises(AnnotationError) as error:
        service.save_annotation(save)
    assert error.value.code == 'annotation_conflict'
    with store._connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM report_annotations').fetchone()[0] == 2


def test_target_retest_matches_original_baseline_and_respects_closure(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    service.save_annotation(save)
    retest = store.record_session(subject, config, make_treadmill_report([.2]*12, [.2]*12))
    read_retest = AnnotationReadRequest(session_id=retest, data_access_scope=read.data_access_scope)
    progress = service.get_annotations(read_retest)['progress'][0]
    assert progress['status'] == 'reached'
    assert progress['value'] == pytest.approx(.2)
    assert progress['difference'] == pytest.approx(-.15)
    assert progress['annotation']['session_id'] == read.session_id
    assert service.get_annotations(read_retest.model_copy(update={'data_access_scope':DataAccessScope()}))['progress'] == []
    service.save_annotation(save.model_copy(update={'expected_revision':1, 'status':'completed'}))
    assert service.get_annotations(read_retest)['progress'] == []


def test_target_protocol_and_snapshot_changes_do_not_report_achievement(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    service.save_annotation(save)
    retest = store.record_session(subject, replace(config,treadmill_speed=7), make_treadmill_report([.2]*12,[.2]*12))
    request = AnnotationReadRequest(session_id=retest, data_access_scope=read.data_access_scope)
    assert service.get_annotations(request)['progress'][0]['status'] == 'protocol_mismatch'
    with store._connect() as conn:
        payload = json.loads(conn.execute('SELECT report_detail_json FROM test_sessions WHERE id=?',(read.session_id,)).fetchone()[0])
        payload['report_config_snapshot'] = {'changed': True}
        conn.execute('UPDATE test_sessions SET report_detail_json=? WHERE id=?',(json.dumps(payload),read.session_id))
    assert service.get_annotations(request)['progress'][0]['status'] == 'stale_baseline'
    with pytest.raises(AnnotationError):
        service.save_annotation(save.model_copy(update={'expected_revision':1}))


def test_guest_can_note_but_cannot_create_cross_session_target(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path, guest=True)
    with pytest.raises(AnnotationError) as error:
        service.save_annotation(save)
    assert error.value.code == 'guest_target_unavailable'
    service.save_annotation(save.model_copy(update={'fact_id':None,'target_value':None}))
    data = service.get_annotations(read)
    assert data['can_set_target'] is False
    assert data['progress'] == []


def test_annotation_rejects_foreign_claim_and_unrelated_metric_and_escapes_text(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    for changes in ({'claim_id':'missing'}, {'fact_id':'another-report-fact'}, {'session_id':9999}):
        with pytest.raises((AnnotationError, KeyError)):
            service.save_annotation(save.model_copy(update=changes))
    service.save_annotation(save.model_copy(update={'note':'<script>bad()</script>'}))
    rendered = annotations_html(service.get_annotations(read))
    assert '<script>' not in rendered
    assert '&lt;script&gt;' in rendered


def test_stale_target_can_be_archived_without_rewriting_its_original_baseline(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    original = service.save_annotation(save)
    with store._connect() as conn:
        payload = json.loads(conn.execute('SELECT report_detail_json FROM test_sessions WHERE id=?',(read.session_id,)).fetchone()[0])
        payload['per_step_results'][0]['contact_time_s'] = .9
        conn.execute('UPDATE test_sessions SET report_detail_json=? WHERE id=?',(json.dumps(payload),read.session_id))
    stale = service.get_annotations(read.model_copy(update={'analysis_run_id':None}))
    assert stale['claims'][0]['stale'] is True
    closed = service.save_annotation(save.model_copy(update={'expected_revision':1,'status':'archived'}))
    assert closed['target'] == original['target']
    assert closed['revision'] == 2
    assert annotations_html(service.get_annotations(read.model_copy(update={'analysis_run_id':None}))) == ''


def test_other_subject_goals_and_guest_progress_are_excluded(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    service.save_annotation(save)
    other = store.create_subject('Other', 1990)
    for owner in (other, None):
        session = store.record_session(owner, config, make_treadmill_report([.2]*12,[.2]*12))
        result = service.get_annotations(AnnotationReadRequest(session_id=session, data_access_scope=read.data_access_scope))
        assert result['progress'] == []


def test_annotation_pdf_contains_user_text_and_numeric_goal(tmp_path):
    from reporting.pdf import report_html
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    service.save_annotation(save)
    report = make_treadmill_report([.2]*6+[.4]*6,[.3]*6+[.5]*6)
    for detailed in (False, True):
        content = report_html(report, title='测试报告', stats=[], reason='完成', detailed=detailed,
                              annotations=service.get_annotations(read))
        assert '用户备注' in content
        assert save.note in content
        assert '完整测试触地时间均值目标不高于 0.3 s' in content


def test_goal_boundary_tolerates_only_floating_point_roundoff_and_keeps_target_precision(tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    service.save_annotation(save)
    retest = store.record_session(subject, config, make_treadmill_report([.3]*12,[.3]*12))
    result = service.get_annotations(AnnotationReadRequest(session_id=retest, data_access_scope=read.data_access_scope))
    assert result['progress'][0]['status'] == 'reached'
    service.save_annotation(save.model_copy(update={'expected_revision':1,'target_value':.299999}))
    result = service.get_annotations(AnnotationReadRequest(session_id=retest, data_access_scope=read.data_access_scope))
    assert result['progress'][0]['status'] == 'pending'
    assert '0.299999 s' in annotations_html(result)
