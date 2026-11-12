"""The note editor saves user input and ignores responses for previous reports."""

import time

from qtpy.QtWidgets import QDialogButtonBox

from reporting.annotations import AnnotationReadRequest, AnnotationSaveRequest
from tests.test_report_annotations import setup_annotations
from tests.reporting_fixtures import make_treadmill_report
from ui.report_annotations import AnnotationPanel


class Client:
    def __init__(self, service):
        self.service = service

    def get_report_annotations(self, session_id, scope, analysis_run_id=None):
        return {'annotations': self.service.get_annotations(AnnotationReadRequest(
            session_id=session_id, data_access_scope=scope, analysis_run_id=analysis_run_id,
        ))}

    def save_report_annotation(self, session_id, scope, **values):
        try:
            self.service.save_annotation(AnnotationSaveRequest(session_id=session_id, data_access_scope=scope, **values))
        except ValueError as error:
            return {'error_code': error.code, 'message':str(error)}
        return self.get_report_annotations(session_id, scope)


def wait(qtbot, panel):
    qtbot.waitUntil(lambda: not panel.workers, timeout=5000)


def panel_for(qtbot, service, read):
    panel = AnnotationPanel(Client(service))
    qtbot.addWidget(panel)
    panel.set_context(read.session_id, {'analysis_run_id':read.analysis_run_id}, True)
    panel.show()
    wait(qtbot, panel)
    return panel


def test_note_target_editor_roundtrip_and_retest_progress(qtbot, tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    panel = panel_for(qtbot, service, read)
    panel.edit_button.click()
    wait(qtbot, panel)
    panel.note.setPlainText('下次保持相同速度，关注节奏。')
    panel.metric.setCurrentIndex(1)
    assert '0.35' in panel.baseline.text()
    panel.target.setValue(.3)
    panel.buttons.button(QDialogButtonBox.Save).click()
    wait(qtbot, panel)
    assert not panel.dialog.isVisible()
    assert '下次保持相同速度' in panel.summary.text()
    assert '0.3 s' in panel.summary.text()
    panel.edit_button.click()
    wait(qtbot, panel)
    assert panel.target.value() == .3
    assert panel.revision == 1
    panel.target.setValue(.4)
    panel.status.setCurrentIndex(panel.status.findData('completed'))
    assert panel.target.value() == .3
    assert not panel.target.isEnabled()
    panel.dialog.reject()
    retest = store.record_session(subject, config, make_treadmill_report([.2]*12,[.2]*12))
    panel.set_context(retest, None, True)
    wait(qtbot, panel)
    assert '本次达到目标值' in panel.summary.text()
    assert '-0.15 s' in panel.summary.text()


def test_concurrent_edit_conflict_keeps_user_text(qtbot, tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    first = panel_for(qtbot, service, read)
    second = panel_for(qtbot, service, read)
    for panel in (first, second):
        panel.open_editor()
        wait(qtbot, panel)
    first.note.setPlainText('先保存的备注')
    first.buttons.button(QDialogButtonBox.Save).click()
    wait(qtbot, first)
    second.note.setPlainText('尚未保存的备注')
    second.buttons.button(QDialogButtonBox.Save).click()
    wait(qtbot, second)
    assert second.dialog.isVisible()
    assert '已被更新' in second.error.text()
    assert second.note.toPlainText() == '尚未保存的备注'
    assert service.get_annotations(read)['annotations'][0]['note'] == '先保存的备注'


def test_late_annotation_response_cannot_repopulate_cleared_report(qtbot, tmp_path):
    store, service, read, save, config, subject = setup_annotations(tmp_path)
    service.save_annotation(save)
    client = Client(service)
    get = client.get_report_annotations

    def delayed(*args):
        time.sleep(.1)
        return get(*args)

    client.get_report_annotations = delayed
    panel = AnnotationPanel(client)
    qtbot.addWidget(panel)
    panel.set_context(read.session_id, {'analysis_run_id':read.analysis_run_id}, True)
    panel.set_context(None, None, False)
    wait(qtbot, panel)
    assert panel.data is None
    assert panel.summary.text() == ''
