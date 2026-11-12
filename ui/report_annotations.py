"""Nonblocking user-note editor and retest progress panel."""

from qtpy.QtCore import Qt, QThread, Signal
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QDialog, QFormLayout,
    QComboBox, QPlainTextEdit, QDoubleSpinBox, QDialogButtonBox,
)

from reporting.annotations import annotations_html
from ui.theme import PALETTE


class _AnnotationWorker(QThread):
    completed = Signal(object)

    def __init__(self, client, session_id, scope, run_id, edit, parent):
        super().__init__(parent)
        self.client, self.session_id, self.scope = client, session_id, scope
        self.run_id, self.edit = run_id, edit

    def run(self):
        try:
            if self.edit is None:
                result = self.client.get_report_annotations(self.session_id, self.scope, self.run_id)
            else:
                result = self.client.save_report_annotation(self.session_id, self.scope, **self.edit)
        except Exception:
            result = {'error_code': 'annotation_unavailable', 'message': '备注服务暂时不可用，请重试。'}
        self.completed.emit(result)


class AnnotationPanel(QWidget):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.data = None
        self.generation = 0
        self.request_serial = 0
        self.context = None
        self.workers = set()
        self.finished_workers = []
        self.dialog = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        layout.addWidget(self.summary)
        self.edit_button = QPushButton('备注与复测目标')
        self.edit_button.clicked.connect(self.open_editor)
        layout.addWidget(self.edit_button)
        self.hide()

    def set_context(self, session_id, analysis, allow_history):
        run_id = analysis.get('analysis_run_id') if analysis else None
        context = (session_id, run_id, allow_history)
        if context == self.context:
            return
        self.context = context
        self.generation += 1
        self.data = None
        self.summary.clear()
        if self.dialog:
            self.dialog.close()
        available = session_id is not None and callable(getattr(self.client, 'get_report_annotations', None))
        self.setVisible(available)
        self.edit_button.setVisible(bool(run_id))
        self.edit_button.setEnabled(False)
        if available:
            self._request()

    def _request(self, edit=None):
        session_id, run_id, allow_history = self.context
        scope = {'current_session': True, 'longitudinal': allow_history, 'cohort': False}
        generation = self.generation
        self.request_serial += 1
        serial = self.request_serial
        worker = _AnnotationWorker(self.client, session_id, scope, run_id, edit, self)
        self.workers.add(worker)
        worker.completed.connect(lambda result: self._receive(result, generation, serial, edit is not None))
        worker.finished.connect(lambda: self._finish(worker))
        worker.start()

    def _finish(self, worker):
        self.workers.discard(worker)
        self.finished_workers.append(worker)

    def _receive(self, response, generation, serial, saved):
        if generation != self.generation or serial != self.request_serial:
            return
        self.edit_button.setEnabled(bool(self.context[1]))
        if response.get('error_code'):
            message = response.get('message') or '备注读取失败，请点击备注按钮重试。'
            if self.dialog and self.dialog.isVisible():
                self.error.setText(message)
                self.buttons.button(QDialogButtonBox.Save).setEnabled(bool(self.data))
            else:
                self.summary.setTextFormat(Qt.PlainText)
                self.summary.setText(message)
            return
        self.data = response['annotations']
        self.edit_button.setVisible(bool(self.data['claims']))
        self.edit_button.setEnabled(bool(self.data['claims']))
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setText(annotations_html(self.data))
        if self.dialog and self.dialog.isVisible():
            if saved:
                self.dialog.accept()
            else:
                self._populate()

    def open_editor(self):
        if not self.context or not (self.context[1] or self.data and self.data['claims']):
            return
        if self.dialog:
            self.dialog.close()
        self.dialog = QDialog(self)
        self.dialog.setStyleSheet(
            f"QDialog {{ background: {PALETTE['surface']}; }} QLabel {{ color: {PALETTE['text']}; }}"
        )
        self.dialog.setWindowTitle('发现备注与复测目标')
        self.dialog.setMinimumWidth(540)
        form = QFormLayout(self.dialog)
        self.form = form
        self.claim = QComboBox()
        self.claim.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.claim.setMinimumContentsLength(32)
        self.claim.currentIndexChanged.connect(self._select_claim)
        form.addRow('关联发现', self.claim)
        self.note = QPlainTextEdit()
        self.note.setPlaceholderText('记录观察、测试背景或下次关注点')
        self.note.setMaximumHeight(150)
        form.addRow('用户备注', self.note)
        self.metric = QComboBox()
        self.metric.currentIndexChanged.connect(self._select_metric)
        form.addRow('复测指标（完整测试均值）', self.metric)
        self.baseline = QLabel()
        form.addRow('基线', self.baseline)
        self.direction = QComboBox()
        self.direction.addItem('不高于', 'at_most')
        self.direction.addItem('不低于', 'at_least')
        form.addRow('目标方向', self.direction)
        self.target = QDoubleSpinBox()
        self.target.setRange(-1e9, 1e9)
        self.target.setDecimals(6)
        form.addRow('目标值', self.target)
        self.status = QComboBox()
        for label, value in (('跟进中','active'), ('标记完成','completed'), ('归档','archived')):
            self.status.addItem(label, value)
        self.status.currentIndexChanged.connect(self._select_status)
        form.addRow('状态', self.status)
        self.error = QLabel('正在读取备注…')
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        form.addRow(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText('保存')
        self.buttons.button(QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.dialog.reject)
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        form.addRow(self.buttons)
        self.dialog.show()
        self._request()

    def _populate(self):
        for field in (self.metric, self.baseline, self.direction, self.target):
            self.form.setRowVisible(field, self.data['can_set_target'])
        self.claim.blockSignals(True)
        self.claim.clear()
        for claim in self.data['claims']:
            self.claim.addItem(claim['text'][:70], (claim['analysis_run_id'], claim['claim_id']))
            self.claim.setItemData(self.claim.count()-1, claim['text'], Qt.ToolTipRole)
        self.claim.blockSignals(False)
        self.error.clear()
        self._select_claim()
        self.buttons.button(QDialogButtonBox.Save).setEnabled(bool(self.claim.count()))

    def _select_claim(self):
        if not self.data:
            return
        identity = self.claim.currentData()
        claim = next((item for item in self.data['claims']
                      if (item['analysis_run_id'], item['claim_id']) == tuple(identity or ())), None)
        if claim is None:
            return
        existing = next((item for item in self.data['annotations']
                         if item['analysis_run_id'] == claim['analysis_run_id'] and item['claim_id'] == claim['claim_id']), {})
        self.selected_claim = claim
        self.existing_annotation = existing
        self.revision = existing.get('revision', 0)
        self.note.setPlainText(existing.get('note', ''))
        self.note.setReadOnly(claim['stale'])
        self.metric.clear()
        self.metric.addItem('不设置复测目标', None)
        if self.data['can_set_target']:
            for fact in claim['facts']:
                self.metric.addItem(f"{fact['label']} ({fact['unit']})", fact)
                self.metric.setItemData(self.metric.count()-1, fact['source_ref'], Qt.ToolTipRole)
        target = existing.get('target')
        if target:
            for index in range(1, self.metric.count()):
                if self.metric.itemData(index)['fact_id'] == target['fact_id']:
                    self.metric.setCurrentIndex(index)
            self.target.setValue(target['target_value'])
            self.direction.setCurrentIndex(self.direction.findData(target['direction']))
        self.status.setCurrentIndex(self.status.findData(existing.get('status', 'active')))
        self._select_metric()
        if claim['stale']:
            self.error.setText('原分析已更新，可将已有备注标记完成或归档。')

    def _select_metric(self):
        fact = self.metric.currentData()
        active = self.status.currentData() == 'active'
        self.metric.setEnabled(active)
        self.direction.setEnabled(bool(fact) and active)
        self.target.setEnabled(bool(fact) and active)
        self.target.setSuffix(' ' + fact['unit'] if fact else '')
        self.baseline.setText(f"{fact['value']:.6g} {fact['unit']}" if fact else '—')

    def _select_status(self):
        if self.status.currentData() != 'active' and getattr(self, 'existing_annotation', None):
            target = self.existing_annotation.get('target')
            self.metric.setCurrentIndex(0)
            if target:
                for index in range(1, self.metric.count()):
                    if self.metric.itemData(index)['fact_id'] == target['fact_id']:
                        self.metric.setCurrentIndex(index)
                self.target.setValue(target['target_value'])
                self.direction.setCurrentIndex(self.direction.findData(target['direction']))
        self._select_metric()

    def _save(self):
        note = self.note.toPlainText().strip()
        fact = self.metric.currentData()
        closing = self.revision > 0 and self.status.currentData() in {'archived', 'completed'}
        if self.selected_claim['stale'] and not closing:
            self.error.setText('原分析已更新，请选择标记完成或归档。')
            return
        if len(note) > 2000 or (not note and not fact and not closing):
            self.error.setText('请填写备注或复测目标，备注最多 2000 字。')
            return
        self.buttons.button(QDialogButtonBox.Save).setEnabled(False)
        self.error.setText('正在保存…')
        self._request({
            'analysis_run_id': self.selected_claim['analysis_run_id'], 'claim_id': self.selected_claim['claim_id'],
            'expected_revision': self.revision, 'note': note,
            'fact_id': fact['fact_id'] if fact else None,
            'target_value': self.target.value() if fact else None,
            'target_direction': self.direction.currentData(), 'status': self.status.currentData(),
        })

    def hideEvent(self, event):
        if self.dialog:
            self.dialog.close()
        super().hideEvent(event)
