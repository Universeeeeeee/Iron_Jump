"""Windows RC200U tap-to-identify probe.

Usage:
    python -m tools.rc200u_probe
    python -m tools.rc200u_probe --simulate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qtpy.QtCore import QTimer
from qtpy.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from data.subject_store import SubjectStore
from hardware.rc200u import STATUS_NO_CARD, Rc200uUnavailable, SimulatedRc200u, UidRead, open_reader
from path_utils import get_base_dir


class Rc200uProbeWindow(QMainWindow):
    def __init__(self, reader, subject_store: SubjectStore, parent=None):
        super().__init__(parent)
        self.reader = reader
        self.subject_store = subject_store
        self._last_uid: str | None = None
        self._last_status: int | None = None
        self.setWindowTitle("RC200U 读卡验证")
        self.resize(720, 520)
        self._build_ui()
        self._refresh_subjects()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.poll_once)
        self._timer.start()
        self._log(f"backend={reader.backend} device={reader.device_number() or '-'}")

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        self._backend_label = QLabel()
        self._uid_label = QLabel("等待贴卡")
        self._uid_label.setStyleSheet("font-size: 28px; font-weight: 600;")
        self._match_label = QLabel("未识别")
        self._match_label.setStyleSheet("font-size: 18px;")
        layout.addWidget(self._backend_label)
        layout.addWidget(self._uid_label)
        layout.addWidget(self._match_label)

        bind_row = QHBoxLayout()
        self._subject_combo = QComboBox()
        self._subject_combo.setMinimumWidth(280)
        self._bind_btn = QPushButton("绑定到所选运动员")
        self._unbind_btn = QPushButton("解绑")
        self._bind_btn.clicked.connect(self._bind_selected)
        self._unbind_btn.clicked.connect(self._unbind_selected)
        bind_row.addWidget(QLabel("运动员"))
        bind_row.addWidget(self._subject_combo, 1)
        bind_row.addWidget(self._bind_btn)
        bind_row.addWidget(self._unbind_btn)
        layout.addLayout(bind_row)

        sim_row = QHBoxLayout()
        self._sim_uid = QLineEdit()
        self._sim_uid.setPlaceholderText("模拟 UID，例如 AABBCCDD")
        self._sim_tap_btn = QPushButton("模拟贴卡")
        self._sim_leave_btn = QPushButton("模拟离开")
        self._sim_tap_btn.clicked.connect(self._simulate_tap)
        self._sim_leave_btn.clicked.connect(self._simulate_leave)
        sim_row.addWidget(self._sim_uid, 1)
        sim_row.addWidget(self._sim_tap_btn)
        sim_row.addWidget(self._sim_leave_btn)
        layout.addLayout(sim_row)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        layout.addWidget(self._log_view, 1)
        self._update_backend_label()

    def _update_backend_label(self) -> None:
        mode = "硬件" if self.reader.backend == "hardware" else "模拟"
        device = self.reader.device_number() or "未读到设备号"
        self._backend_label.setText(f"模式：{mode}    设备：{device}")

    def poll_once(self) -> UidRead:
        result = self.reader.request_uid()
        uid = result.uid
        changed = uid != self._last_uid
        status_changed = result.status != self._last_status
        self._last_status = result.status
        if changed:
            previous = self._last_uid
            self._last_uid = uid
            if uid and self.reader.backend == "hardware":
                self.reader.beep(30)
            if uid is None and previous:
                self._log("card left")
        if uid is None and result.status != STATUS_NO_CARD:
            self._uid_label.setText(f"读卡异常（{result.status}）")
            self._match_label.setText(result.message)
        else:
            self._render_uid(uid, log=changed)
        if status_changed:
            self._log(f"status={result.status} {result.message}")
        return result

    def _render_uid(self, uid: str | None, *, log: bool) -> None:
        if uid is None:
            self._uid_label.setText("等待贴卡")
            self._match_label.setText("未识别")
            return
        self._uid_label.setText(uid)
        subject = self.subject_store.get_subject_by_card_uid(uid)
        if subject is None:
            self._match_label.setText("未绑定运动员")
            if log:
                self._log(f"uid={uid} unbound")
            return
        self._match_label.setText(f"识别到：{subject.display_name}  #{subject.id}")
        self._select_subject(subject.id)
        if log:
            self._log(f"uid={uid} -> {subject.display_name} #{subject.id}")

    def _refresh_subjects(self) -> None:
        current_id = self._selected_subject_id()
        self._subject_combo.blockSignals(True)
        self._subject_combo.clear()
        for result in self.subject_store.search_subjects(""):
            subject = result.subject
            card = subject.card_uid or "未绑卡"
            self._subject_combo.addItem(
                f"{subject.display_name}  #{subject.id}  [{card}]",
                subject.id,
            )
        self._subject_combo.blockSignals(False)
        if current_id is not None:
            self._select_subject(current_id)

    def _selected_subject_id(self) -> int | None:
        data = self._subject_combo.currentData()
        return int(data) if data is not None else None

    def _select_subject(self, subject_id: int) -> None:
        for index in range(self._subject_combo.count()):
            if self._subject_combo.itemData(index) == subject_id:
                self._subject_combo.setCurrentIndex(index)
                return

    def _bind_selected(self) -> None:
        uid = self._last_uid
        subject_id = self._selected_subject_id()
        if not uid:
            QMessageBox.information(self, "RC200U", "请先贴卡。")
            return
        if subject_id is None:
            QMessageBox.information(self, "RC200U", "请选择运动员。")
            return
        try:
            self.subject_store.bind_card_uid(subject_id, uid)
        except ValueError as exc:
            QMessageBox.warning(self, "RC200U", str(exc))
            return
        self._refresh_subjects()
        self.poll_once()
        self._log(f"bound {uid} -> #{subject_id}")

    def _unbind_selected(self) -> None:
        subject_id = self._selected_subject_id()
        if subject_id is None:
            return
        self.subject_store.unbind_card_uid(subject_id)
        self._refresh_subjects()
        self.poll_once()
        self._log(f"unbound #{subject_id}")

    def _simulate_tap(self) -> None:
        if not isinstance(self.reader, SimulatedRc200u):
            QMessageBox.information(self, "RC200U", "当前是硬件模式，请直接贴卡。")
            return
        uid = self._sim_uid.text().strip()
        if not uid:
            QMessageBox.information(self, "RC200U", "请输入模拟 UID。")
            return
        self.reader.queue_uid(uid)
        self.poll_once()

    def _simulate_leave(self) -> None:
        if isinstance(self.reader, SimulatedRc200u):
            self.reader.clear()
            self.poll_once()

    def _log(self, message: str) -> None:
        self._log_view.appendPlainText(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RC200U tap-to-identify probe")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--dll", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        reader = open_reader(simulate=args.simulate, dll_path=args.dll)
    except Rc200uUnavailable as exc:
        print(exc, file=sys.stderr)
        return 2
    store = SubjectStore(args.db or Path(get_base_dir()) / "data" / "iron_jump.sqlite3")
    app = QApplication.instance() or QApplication(sys.argv)
    window = Rc200uProbeWindow(reader, store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
