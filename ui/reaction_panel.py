"""Native reaction stimulus presentation with explicitly uncalibrated timing."""

from pathlib import Path
from dataclasses import asdict, is_dataclass
import time

from qtpy.QtCore import Qt, Signal, QUrl
from qtpy.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout

from ui.theme import qss


STIMULUS_LABELS = {"visual": "视觉", "acoustic": "听觉"}
TRIAL_STATUS_LABELS = {
    "valid": "有效", "early": "抢先反应", "timeout": "超时",
    "gap": "数据中断", "cancelled": "已取消", "stimulus_failed": "刺激失败",
}
STATE_LABELS = {
    "idle": "准备开始", "preparing": "保持起始姿势", "waiting": "等待刺激",
    "stimulus_pending": "等待刺激", "responding": "请反应", "rest": "休息并恢复起始姿势",
    "manual_wait": "准备下一次", "finished": "测试结束",
}


class ReactionPanel(QFrame):
    stimulus_presented = Signal(object)
    next_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False
        self._sound = None
        self._audio_error = ""
        self.setObjectName("ReactionPanel")
        self.setStyleSheet(qss("""
            QFrame#ReactionPanel { background: ${surface}; border: 1px solid ${border_card}; border-radius: 12px; }
            QLabel { background: transparent; border: none; color: ${text}; }
        """))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        self.trial_label = QLabel("第 1 / 5 次")
        self.trial_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(self.trial_label)
        header.addStretch()
        quality = QLabel("软件估计 · 未校准")
        quality.setStyleSheet(qss("color: ${warning}; font-size: 13px;"))
        header.addWidget(quality)
        layout.addLayout(header)
        self.stimulus = QLabel("准备开始")
        self.stimulus.setAlignment(Qt.AlignCenter)
        self.stimulus.setMinimumHeight(170)
        self.stimulus.setWordWrap(True)
        layout.addWidget(self.stimulus, 1)
        self.instruction = QLabel()
        self.instruction.setAlignment(Qt.AlignCenter)
        self.instruction.setWordWrap(True)
        self.instruction.setStyleSheet("font-size: 17px;")
        layout.addWidget(self.instruction)
        self.result_label = QLabel("本次结果  —")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setStyleSheet(qss("font-size: 20px; color: ${text_heading}; font-weight: 700;"))
        layout.addWidget(self.result_label)
        self.next_button = QPushButton("下一次")
        self.next_button.setProperty("role", "primary")
        self.next_button.setMinimumHeight(44)
        self.next_button.clicked.connect(self.next_requested)
        self.next_button.hide()
        layout.addWidget(self.next_button, 0, Qt.AlignCenter)
        note = QLabel("计时基于刺激请求与设备数据接收，实际声光起始延迟未经校准。")
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet(qss("font-size: 12px; color: ${text_muted};"))
        layout.addWidget(note)
        self._set_stimulus("准备开始", False)

    def configure(self, config):
        self.clear()
        self._active = True
        self.trial_label.setText(f"第 1 / {config.number_of_repetitions} 次")
        position, action = ("站在测量区内", "跳起") if config.start_position == "Inside area" else ("站在测量区外", "进入测量区")
        cue = {"Visual stimulus": "屏幕变绿后", "Acoustic stimulus": "听到提示音后", "Visual/Acoustic stimulus": "屏幕变绿或听到提示音后"}[config.stimulus_type]
        self.instruction.setText(f"{position} · {cue}{action}")
        self.result_label.setText("本次结果  —")
        if config.stimulus_type != "Visual stimulus":
            self._preload_audio()

    def _preload_audio(self):
        if self._sound is not None:
            return
        try:
            from PySide6.QtMultimedia import QMediaDevices, QSoundEffect
            if not QMediaDevices.audioOutputs():
                self._audio_error = "未找到音频输出设备"
                return
            self._sound = QSoundEffect(self)
            self._sound.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "assets" / "reaction_tone.wav")))
            self._sound.setVolume(0.8)
            self._audio_error = ""
        except ImportError:
            self._audio_error = "音频组件不可用"

    def _set_stimulus(self, text, go):
        color = "#16834f" if go else "#8c293b"
        self.stimulus.setStyleSheet(f"background: {color}; color: white; border-radius: 14px; font-size: 38px; font-weight: 700; padding: 20px;")
        self.stimulus.setText(text)

    def present(self, request):
        if not self._active:
            return
        modality = request.get("stimulus_type", request.get("modality"))
        success = True
        error = ""
        if modality == "visual":
            requested_ns = time.perf_counter_ns()
            self._set_stimulus("现在反应", True)
        elif modality == "acoustic":
            if self._sound is None or not self._sound.isLoaded():
                success = False
                error = self._audio_error or "提示音尚未就绪"
                requested_ns = time.perf_counter_ns()
            else:
                requested_ns = time.perf_counter_ns()
                self._sound.play()
        else:
            success = False
            error = "未知刺激类型"
            requested_ns = time.perf_counter_ns()
        self.stimulus_presented.emit({
            "session_id": request.get("session_id"),
            "trial_index": request["trial_index"], "stimulus_type": modality,
            "requested_monotonic_ns": requested_ns,
            "timing_source": "software_request", "calibrated": False,
            "success": success, "error": error,
        })
        if not success:
            self._set_stimulus("刺激失败", False)
            self.result_label.setText(error)

    def update_snapshot(self, snapshot):
        state = snapshot.get("state", "idle")
        self.trial_label.setText(f"第 {snapshot.get('trial_index', 1)} / {snapshot.get('total_trials', 1)} 次")
        self.next_button.setVisible(state == "manual_wait")
        self.next_button.setEnabled(bool(snapshot.get("next_allowed")))
        # Acoustic trials keep the waiting colour so the screen adds no visual cue.
        if state not in {"stimulus_pending", "responding"}:
            self._set_stimulus(STATE_LABELS.get(state, state), False)
        latest = snapshot.get("latest_trial")
        if latest:
            if is_dataclass(latest):
                latest = asdict(latest)
            status = latest.get("status")
            value = latest.get("reaction_time_ms")
            result = f"{value:.0f} ms" if status == "valid" and value is not None else TRIAL_STATUS_LABELS.get(status, status or "—")
            self.result_label.setText(f"第 {latest.get('index', '')} 次  {result}")

    def cancel_stimulus(self):
        if self._sound is not None:
            self._sound.stop()
        self._set_stimulus("等待刺激", False)

    def clear(self):
        self._active = False
        self.cancel_stimulus()
        self.next_button.hide()
