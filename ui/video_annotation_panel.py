"""Annotation tools, list navigation and persistence for the replay surface."""

import uuid

from qtpy.QtCore import QEvent, Qt, Signal
from qtpy.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QToolButton, QVBoxLayout, QWidget

from camera.video_annotations import VideoAnnotations, angle_degrees


class VideoAnnotationPanel(QWidget):
    layout_changed = Signal()

    def __init__(self, playback, canvas, parent=None):
        super().__init__(parent)
        self.playback = playback
        self.canvas = canvas
        self.document = None
        self._path = None
        self._loaded = False
        self._valid_frame = False
        self.time_start = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.select_button = QToolButton()
        self.angle_button = QToolButton()
        self.start_button = QToolButton()
        self.end_button = QToolButton()
        self.delete_button = QToolButton()
        self.select_button.setCheckable(True)
        self.angle_button.setCheckable(True)
        self.select_button.clicked.connect(lambda: self.set_tool("select"))
        self.angle_button.clicked.connect(lambda: self.set_tool("angle"))
        self.start_button.clicked.connect(self.set_start)
        self.end_button.clicked.connect(self.set_end)
        self.delete_button.clicked.connect(self.delete_selected)
        for button, text in zip(
            (self.select_button, self.angle_button, self.start_button, self.end_button, self.delete_button),
            ("选择", "角度", "计时起点", "计时终点", "删除"),
        ):
            button.setText(text)
            button.setStyleSheet("QToolButton:checked { border: 1px solid #69dfca; }")
            row.addWidget(button)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.list_toggle = QPushButton("标注列表 ▸")
        self.list_toggle.setCheckable(True)
        self.list_toggle.toggled.connect(self._toggle_list)
        layout.addWidget(self.list_toggle)
        self.list_panel = QWidget()
        list_layout = QVBoxLayout(self.list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(100)
        self.list.itemClicked.connect(self._list_jump)
        self.list.itemActivated.connect(self._list_jump)
        self.list.currentItemChanged.connect(self._list_select)
        list_layout.addWidget(self.list)
        row = QHBoxLayout()
        self.jump_start = QPushButton("跳转起点 / 所属帧")
        self.jump_end = QPushButton("跳转终点")
        self.jump_start.clicked.connect(lambda: self.jump_selected(False))
        self.jump_end.clicked.connect(lambda: self.jump_selected(True))
        row.addWidget(self.jump_start)
        row.addWidget(self.jump_end)
        list_layout.addLayout(row)
        layout.addWidget(self.list_panel)
        self.list_panel.hide()
        canvas.angle_created.connect(self._create_angle)
        canvas.angle_edited.connect(self._edit_angle)
        canvas.selection_changed.connect(self._sync_selection)
        canvas.message.connect(self.status.setText)
        playback.pending_changed.connect(self._pending_changed)
        playback.playing_changed.connect(self._playing_changed)
        self.reset()

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self.layout_changed.emit()
        return super().event(event)

    def reset(self, path=None):
        self.document = None
        self._path = path
        self._loaded = False
        self._valid_frame = False
        self.time_start = None
        self.canvas.reset_annotations()
        self.list.clear()
        self.status.clear()
        self._refresh()

    def on_frame(self, frame, index):
        height, width = frame.shape[:2]
        self._valid_frame = True
        if not self._loaded:
            self._loaded = True
            try:
                self.document = VideoAnnotations(self._path, self.playback.info.frame_count, width, height)
                self.canvas.records = self.document.records
                self._rebuild_list()
            except (OSError, ValueError) as exc:
                self.status.setText(f"标注修改已禁用：{exc}")
        self.canvas.times = self.playback.info.times
        self.canvas.estimated = self.playback.info.time_source != "采样时间"
        self.canvas.set_frame(index, width, height)
        self._refresh()

    def on_error(self):
        self._valid_frame = False
        self.canvas.annotations_visible = False
        self.canvas.cancel_draft()
        self._refresh()

    def _pending_changed(self, pending):
        if pending:
            self.canvas.cancel_draft()
        self._refresh()

    def _playing_changed(self, playing):
        if playing:
            self.canvas.set_tool("select")
        self._refresh()

    def _refresh(self):
        ready = self.document is not None and self._valid_frame
        stable = ready and not self.playback.is_frame_pending and not self.playback.playing
        freeze = ready and (not self.playback.is_frame_pending or self.playback.playing)
        self.canvas.set_editable(stable)
        self.select_button.setEnabled(freeze)
        self.angle_button.setEnabled(freeze)
        self.start_button.setEnabled(freeze)
        self.end_button.setEnabled(freeze and self.time_start is not None)
        record = self._selected()
        self.delete_button.setEnabled(stable and record is not None)
        self.jump_start.setEnabled(record is not None)
        self.jump_end.setEnabled(record is not None and record["kind"] == "interval")
        self.select_button.setChecked(self.canvas.tool == "select")
        self.angle_button.setChecked(self.canvas.tool == "angle")

    def _freeze(self):
        return (self.document is not None and self._valid_frame
                and (not self.playback.is_frame_pending or self.playback.playing)
                and self.playback.freeze_current_frame())

    def set_tool(self, tool):
        if not self._freeze():
            return
        self.canvas.set_tool(tool)
        self.canvas.setFocus()
        self.status.setText("依次点击端点、顶点、端点；Esc 取消" if tool == "angle" else "选择标注后可拖动控制点，Delete 删除")
        self._refresh()

    def cancel(self):
        self.time_start = None
        self.canvas.set_tool("select")
        if self.document is not None:
            self.status.setText("已取消未完成标注")
        self._refresh()

    def set_start(self):
        if self._freeze():
            self.canvas.set_tool("select")
            self.time_start = self.playback.index
            self.status.setText(f"起点：第 {self.time_start + 1} 帧，请定位终点")
            self._refresh()

    def set_end(self):
        if self.time_start is None or not self._freeze():
            return
        if self.playback.index <= self.time_start:
            self.status.setText("计时终点必须晚于起点，请重新定位")
            return
        record = {"id": uuid.uuid4().hex, "kind": "interval", "start": self.time_start, "end": self.playback.index}
        if self._commit(self.document.records + [record], record["id"]):
            self.time_start = None
            self._refresh()

    def _create_angle(self, points):
        if not self.canvas.editable:
            return
        record = {"id": uuid.uuid4().hex, "kind": "angle", "frame": self.canvas.index, "points": points}
        self._commit(self.document.records + [record], record["id"])

    def _edit_angle(self, record_id, points):
        if self.canvas.editable:
            records = [dict(r, points=points) if r["id"] == record_id else r for r in self.document.records]
            self._commit(records, record_id)

    def _commit(self, records, selected_id):
        try:
            self.document.commit(records)
        except (OSError, ValueError) as exc:
            self.status.setText(f"保存失败，修改未生效：{exc}")
            self.canvas.update()
            return False
        self.canvas.records = self.document.records
        self._rebuild_list()
        self.canvas.select(selected_id)
        self.status.setText("标注已保存")
        return True

    def _selected(self):
        if self.document is not None:
            return next((r for r in self.document.records if r["id"] == self.canvas.selected_id), None)
        return None

    def delete_selected(self):
        if self.canvas.editable and self._selected() is not None:
            self._commit([r for r in self.document.records if r["id"] != self.canvas.selected_id], "")

    def _rebuild_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        info = self.playback.info
        for record in self.document.records:
            if record["kind"] == "angle":
                text = f"角度 · 第 {record['frame'] + 1} 帧 · {angle_degrees(record['points']):.1f}°"
            else:
                delta = info.times[record["end"]] - info.times[record["start"]]
                text = f"时间 · 第 {record['start'] + 1}–{record['end'] + 1} 帧 · {delta:.3f} s"
                if info.time_source != "采样时间":
                    text += "（估算）"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, record["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)

    def _sync_selection(self, record_id):
        self.list.blockSignals(True)
        self.list.setCurrentRow(next((i for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole) == record_id), -1))
        self.list.blockSignals(False)
        self._refresh()

    def _list_select(self, item, previous):
        self.canvas.select(item.data(Qt.UserRole) if item else "")

    def _list_jump(self, item):
        self.canvas.select(item.data(Qt.UserRole))
        self.jump_selected(False)

    def jump_selected(self, end=False):
        record = self._selected()
        if record is not None:
            self.canvas.set_tool("select")
            self.playback.seek(record["frame"] if record["kind"] == "angle" else record["end" if end else "start"])

    def _toggle_list(self, expanded):
        self.list_panel.setVisible(expanded)
        self.list_toggle.setText("标注列表 ▾" if expanded else "标注列表 ▸")
        self.layout_changed.emit()
