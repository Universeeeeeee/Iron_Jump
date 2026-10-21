"""Windows desktop launcher for recording, annotation, and offline replay."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path


APP_NAME = "IronJumpVisionTools"
ORGANIZATION_NAME = "Yingheng"
MODEL_NAME = "pose_landmarker_full.task"
PROJECT_ROOT = Path(__file__).resolve().parent


def default_user_root() -> Path:
    return Path.home() / "Documents" / "IronJump"


def default_output_root() -> Path:
    return default_user_root() / "vision_sessions"


def default_log_root() -> Path:
    return default_user_root() / "app_logs"


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))


def find_model(remembered_path: str = "") -> Path | None:
    candidates = []
    if remembered_path:
        candidates.append(Path(remembered_path).expanduser())
    candidates.extend(
        (
            resource_root() / "models" / MODEL_NAME,
            PROJECT_ROOT / "models" / MODEL_NAME,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def read_session_status(session_root: str | Path) -> str:
    path = Path(session_root) / "session.json"
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "invalid"
    status = str(metadata.get("status") or "partial").lower()
    return status if status in {"recording", "complete", "partial"} else "partial"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Iron_Jump vision dataset tools")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--record", action="store_true", help=argparse.SUPPRESS)
    modes.add_argument("--annotate", metavar="SESSION", help=argparse.SUPPRESS)
    modes.add_argument("--replay", metavar="SESSION", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--output-root", help=argparse.SUPPRESS)
    parser.add_argument("--mode", default="treadmill-gait", help=argparse.SUPPRESS)
    parser.add_argument("--speed", type=float, default=1.0, help=argparse.SUPPRESS)
    parser.add_argument("--direction", default="Interface side", help=argparse.SUPPRESS)
    parser.add_argument("--starting-foot", choices=("left", "right"), help=argparse.SUPPRESS)
    parser.add_argument("--scenario", default="normal", help=argparse.SUPPRESS)
    parser.add_argument("--legacy-output", help=argparse.SUPPRESS)
    parser.add_argument("--log-dir", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_root = Path(args.log_dir).expanduser() if args.log_dir else default_log_root()
    _configure_logging(log_root, "launcher" if not any((args.record, args.annotate, args.replay)) else "tool")
    if args.record:
        return _run_record(args, log_root)
    if args.annotate:
        return _run_annotation(args.annotate)
    if args.replay:
        return _run_replay(args.replay)
    return run_launcher()


def _run_record(args: argparse.Namespace, log_root: Path) -> int:
    if not args.model or not args.output_root:
        raise SystemExit("--record requires --model and --output-root")
    from tools.vision_event_validator import main as validator_main

    validator_args = [
        "--camera",
        "tinyse",
        "--model",
        args.model,
        "--output-root",
        args.output_root,
        "--mode",
        args.mode,
        "--speed",
        str(args.speed),
        "--direction",
        args.direction,
        "--scenario",
        args.scenario,
        "--output",
        args.legacy_output or str(log_root / "vision-event-validation.csv"),
    ]
    if args.starting_foot:
        validator_args.extend(("--starting-foot", args.starting_foot))
    return validator_main(validator_args)


def _run_annotation(session: str) -> int:
    _reject_recording_session(session)
    from tools.annotate_foot_contacts import main as annotation_main

    return annotation_main([session])


def _run_replay(session: str) -> int:
    _reject_recording_session(session)
    from tools.replay_foot_classifier import main as replay_main

    return replay_main([session])


def _reject_recording_session(session: str) -> None:
    status = read_session_status(session)
    if status == "recording":
        raise SystemExit("session is still recording")
    if status == "invalid":
        raise SystemExit("invalid vision session")


def _configure_logging(root: Path, component: str) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{component}-{datetime.now():%Y%m%d}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            handlers=(logging.FileHandler(path, encoding="utf-8"),),
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)


def run_launcher() -> int:
    from qtpy.QtCore import QProcess, QSettings, QUrl, Qt
    from qtpy.QtGui import QCloseEvent, QDesktopServices, QIcon
    from qtpy.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    class RecordDialog(QDialog):
        def __init__(self, settings: QSettings, parent=None) -> None:
            super().__init__(parent)
            self.setWindowTitle("录制新 Vision Session")
            self.resize(650, 360)
            self._settings = settings

            self.mode = QComboBox()
            self.mode.addItem("跑步机步态", "treadmill-gait")
            self.mode.addItem("跑步机跑步", "treadmill-running")
            self.mode.addItem("纵跳（仅保存，不进入 benchmark）", "jump")
            _select_data(self.mode, settings.value("record/mode", "treadmill-gait"))

            self.speed = QDoubleSpinBox()
            self.speed.setRange(0.1, 30.0)
            self.speed.setDecimals(2)
            self.speed.setValue(float(settings.value("record/speed", 1.0)))

            self.direction = QComboBox()
            self.direction.addItem("Interface side", "Interface side")
            self.direction.addItem("Opposite side", "Opposite side")
            _select_data(self.direction, settings.value("record/direction", "Interface side"))

            self.starting_foot = QComboBox()
            self.starting_foot.addItem("自动", "")
            self.starting_foot.addItem("Left", "left")
            self.starting_foot.addItem("Right", "right")
            _select_data(self.starting_foot, settings.value("record/starting_foot", ""))

            self.scenario = QLineEdit(str(settings.value("record/scenario", "normal")))
            remembered_model = str(settings.value("paths/model", ""))
            model = find_model(remembered_model)
            self.model_path = QLineEdit(str(model or remembered_model))
            self.output_root = QLineEdit(
                str(settings.value("paths/output_root", str(default_output_root())))
            )

            form = QFormLayout()
            form.addRow("模式", self.mode)
            form.addRow("速度", self.speed)
            form.addRow("方向", self.direction)
            form.addRow("起始脚", self.starting_foot)
            form.addRow("Scenario", self.scenario)
            form.addRow("MediaPipe 模型", _path_row(self.model_path, self._browse_model))
            form.addRow("Session 根目录", _path_row(self.output_root, self._browse_output))
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText("开始录制")
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            layout = QVBoxLayout(self)
            layout.addLayout(form)
            layout.addWidget(buttons)

        def values(self) -> dict[str, object]:
            return {
                "mode": self.mode.currentData(),
                "speed": self.speed.value(),
                "direction": self.direction.currentData(),
                "starting_foot": self.starting_foot.currentData(),
                "scenario": self.scenario.text().strip() or "normal",
                "model": self.model_path.text().strip(),
                "output_root": self.output_root.text().strip(),
            }

        def save(self) -> None:
            values = self.values()
            for key in ("mode", "speed", "direction", "starting_foot", "scenario"):
                self._settings.setValue(f"record/{key}", values[key])
            self._settings.setValue("paths/model", values["model"])
            self._settings.setValue("paths/output_root", values["output_root"])

        def _browse_model(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 Pose Landmarker Full 模型",
                self.model_path.text() or str(PROJECT_ROOT),
                "MediaPipe Task (*.task)",
            )
            if path:
                self.model_path.setText(path)

        def _browse_output(self) -> None:
            path = QFileDialog.getExistingDirectory(
                self,
                "选择 Vision Session 根目录",
                self.output_root.text() or str(default_output_root()),
            )
            if path:
                self.output_root.setText(path)

    class LauncherWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("IronJump Vision Tools")
            self.resize(760, 520)
            icon_path = resource_root() / "ui" / "assets" / "yingheng_app_icon.png"
            if icon_path.is_file():
                self.setWindowIcon(QIcon(str(icon_path)))
            self.settings = QSettings(ORGANIZATION_NAME, APP_NAME)
            self.log_root = Path(
                str(self.settings.value("paths/log_root", str(default_log_root())))
            ).expanduser()
            self.log_root.mkdir(parents=True, exist_ok=True)
            self._processes: dict[str, QProcess] = {}
            self._replay_session: Path | None = None

            title = QLabel("Iron_Jump 左右脚视觉数据工具")
            title.setStyleSheet("font-size:24px; font-weight:700;")
            subtitle = QLabel("录制真实数据、人工标注，并离线 Replay 当前分类器")
            subtitle.setStyleSheet("color:#666;")

            self.record_button = QPushButton("录制新 Session")
            self.annotate_button = QPushButton("标注已有 Session")
            self.replay_button = QPushButton("Replay 已有 Session")
            for button in (self.record_button, self.annotate_button, self.replay_button):
                button.setMinimumHeight(54)
            self.record_button.clicked.connect(self._record)
            self.annotate_button.clicked.connect(self._annotate)
            self.replay_button.clicked.connect(self._replay)

            self.record_status = QLabel("录制：空闲")
            self.annotate_status = QLabel("标注：空闲")
            self.replay_status = QLabel("Replay：空闲")
            status_box = QGroupBox("任务状态")
            status_layout = QVBoxLayout(status_box)
            status_layout.addWidget(self.record_status)
            status_layout.addWidget(self.annotate_status)
            status_layout.addWidget(self.replay_status)

            self.replay_result = QLabel("尚未运行 Replay")
            self.replay_result.setWordWrap(True)
            replay_box = QGroupBox("最近 Replay 结果")
            replay_layout = QVBoxLayout(replay_box)
            replay_layout.addWidget(self.replay_result)
            self.open_output_button = QPushButton("打开输出目录")
            self.open_output_button.setEnabled(False)
            self.open_output_button.clicked.connect(self._open_replay_output)
            replay_layout.addWidget(self.open_output_button)

            self.open_logs_button = QPushButton("打开日志目录")
            self.open_logs_button.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_root)))
            )

            central = QWidget()
            layout = QVBoxLayout(central)
            layout.setContentsMargins(28, 24, 28, 24)
            layout.addWidget(title)
            layout.addWidget(subtitle)
            layout.addSpacing(14)
            layout.addWidget(self.record_button)
            layout.addWidget(self.annotate_button)
            layout.addWidget(self.replay_button)
            layout.addWidget(status_box)
            layout.addWidget(replay_box)
            layout.addWidget(self.open_logs_button, alignment=Qt.AlignRight)
            self.setCentralWidget(central)

        def _record(self) -> None:
            if self._is_running("record"):
                QMessageBox.information(self, "录制运行中", "已有录制任务正在运行。")
                return
            dialog = RecordDialog(self.settings, self)
            if dialog.exec() != QDialog.Accepted:
                return
            values = dialog.values()
            model = Path(str(values["model"])).expanduser()
            if not model.is_file():
                QMessageBox.warning(self, "模型不存在", "请选择有效的 pose_landmarker_full.task。")
                return
            output_root = Path(str(values["output_root"])).expanduser()
            try:
                output_root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(self, "目录不可用", str(exc))
                return
            dialog.save()
            arguments = [
                "--record",
                "--model",
                str(model.resolve()),
                "--output-root",
                str(output_root.resolve()),
                "--mode",
                str(values["mode"]),
                "--speed",
                str(values["speed"]),
                "--direction",
                str(values["direction"]),
                "--scenario",
                str(values["scenario"]),
                "--log-dir",
                str(self.log_root),
            ]
            if values["starting_foot"]:
                arguments.extend(("--starting-foot", str(values["starting_foot"])))
            self._start_process("record", arguments)

        def _annotate(self) -> None:
            if self._is_running("annotate"):
                QMessageBox.information(self, "标注运行中", "已有标注工具正在运行。")
                return
            session = self._choose_session("选择需要标注的 Vision Session")
            if session is None:
                return
            self._start_process(
                "annotate",
                ("--annotate", str(session), "--log-dir", str(self.log_root)),
            )

        def _replay(self) -> None:
            if self._is_running("replay"):
                QMessageBox.information(self, "Replay 运行中", "已有 Replay 正在运行。")
                return
            session = self._choose_session("选择需要 Replay 的 Vision Session")
            if session is None:
                return
            self._replay_session = session
            self._start_process(
                "replay",
                ("--replay", str(session), "--log-dir", str(self.log_root)),
            )

        def _choose_session(self, title: str) -> Path | None:
            initial = str(
                self.settings.value(
                    "paths/recent_session",
                    self.settings.value("paths/output_root", str(default_output_root())),
                )
            )
            selected = QFileDialog.getExistingDirectory(self, title, initial)
            if not selected:
                return None
            session = Path(selected).resolve()
            status = read_session_status(session)
            if status == "invalid":
                QMessageBox.warning(self, "Session 无效", "所选目录没有有效的 session.json。")
                return None
            if status == "recording":
                QMessageBox.warning(self, "Session 正在录制", "录制完成前不能标注或 Replay。")
                return None
            if status == "partial":
                answer = QMessageBox.question(
                    self,
                    "Session 不完整",
                    "该 Session 状态为 partial。是否仍要继续？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    return None
            self.settings.setValue("paths/recent_session", str(session))
            return session

        def _start_process(self, kind: str, arguments) -> None:
            process = QProcess(self)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            process.setStandardOutputFile(
                str(self.log_root / f"{kind}-{stamp}.out.log")
            )
            process.setStandardErrorFile(
                str(self.log_root / f"{kind}-{stamp}.error.log")
            )
            program, child_arguments = _child_command(arguments)
            process.finished.connect(
                lambda exit_code, _exit_status, selected_kind=kind: self._process_finished(
                    selected_kind, exit_code
                )
            )
            process.errorOccurred.connect(
                lambda _error, selected_kind=kind: self._process_error(selected_kind)
            )
            self._processes[kind] = process
            self._set_status(kind, "运行中")
            if kind == "record":
                self.record_button.setEnabled(False)
            process.start(program, list(child_arguments))

        def _process_finished(self, kind: str, exit_code: int) -> None:
            self._set_status(kind, "完成" if exit_code == 0 else f"失败（退出码 {exit_code}）")
            if kind == "record":
                self.record_button.setEnabled(True)
            if kind == "replay" and exit_code == 0:
                self._show_replay_summary()
            elif exit_code != 0:
                QMessageBox.warning(
                    self,
                    "工具运行失败",
                    f"{kind} 退出码为 {exit_code}。请查看日志目录。",
                )

        def _process_error(self, kind: str) -> None:
            self._set_status(kind, "启动失败")
            if kind == "record":
                self.record_button.setEnabled(True)
            QMessageBox.critical(self, "无法启动", f"{kind} 子进程无法启动，请查看日志。")

        def _show_replay_summary(self) -> None:
            session = self._replay_session
            if session is None:
                return
            try:
                summary = json.loads(
                    (session / "replay_summary.json").read_text(encoding="utf-8")
                )
                wrong_ids = summary.get("wrong_event_ids") or []
                self.replay_result.setText(
                    f"Accuracy: {_percent(summary, 'accuracy')}\n"
                    f"Accepted Accuracy: {_percent(summary, 'accepted_accuracy')}\n"
                    f"Coverage: {_percent(summary, 'coverage')}\n"
                    f"Unknown Rate: {_percent(summary, 'unknown_rate')}\n"
                    f"错误 event_id: {', '.join(map(str, wrong_ids)) if wrong_ids else '无'}"
                )
                self.open_output_button.setEnabled(True)
            except Exception as exc:
                QMessageBox.warning(self, "结果读取失败", str(exc))

        def _open_replay_output(self) -> None:
            if self._replay_session is not None:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._replay_session)))

        def _is_running(self, kind: str) -> bool:
            process = self._processes.get(kind)
            return bool(process is not None and process.state() != QProcess.NotRunning)

        def _set_status(self, kind: str, value: str) -> None:
            getattr(self, f"{kind}_status").setText(
                {"record": "录制", "annotate": "标注", "replay": "Replay"}[kind]
                + f"：{value}"
            )

        def closeEvent(self, event: QCloseEvent) -> None:
            if any(self._is_running(kind) for kind in self._processes):
                QMessageBox.warning(
                    self,
                    "任务仍在运行",
                    "仍有录制、标注或 Replay 任务运行。请先关闭这些工具，再退出启动器。",
                )
                event.ignore()
                return
            event.accept()

    def _path_row(line_edit: QLineEdit, callback):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("浏览…")
        button.clicked.connect(callback)
        layout.addWidget(line_edit, 1)
        layout.addWidget(button)
        return container

    app = QApplication.instance() or QApplication(sys.argv)
    window = LauncherWindow()
    window.show()
    return app.exec()


def _child_command(arguments) -> tuple[str, list[str]]:
    values = list(arguments)
    if getattr(sys, "frozen", False):
        return sys.executable, values
    return sys.executable, [str(Path(__file__).resolve()), *values]


def _select_data(combo, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _percent(summary: dict, key: str) -> str:
    return f"{float(summary.get(key, 0.0)) * 100.0:.2f}%"


if __name__ == "__main__":
    raise SystemExit(main())
