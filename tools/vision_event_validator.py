"""Windows sidecar UI for validating visual labels on real grid touch events."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from dataclasses import replace
from pathlib import Path



CSV_FIELDS = (
    "event_id",
    "event_time_s",
    "decided_at_s",
    "project_mode",
    "event_role",
    "source_contact_id",
    "source_grid_label",
    "raw_device_label",
    "effective_device_label",
    "final_label",
    "vision_label",
    "left_evidence",
    "right_evidence",
    "candidate_label",
    "confidence",
    "reason",
    "latency_ms",
    "window_frame_count",
    "inference_attempts",
    "pose_total",
    "pose_before",
    "pose_after",
    "max_pose_gap_ms",
    "analysis_fps",
    "pose_fps",
    "sync_status",
    "sync_reason",
    "sync_warmup_ms",
    "sync_offset_ms",
    "sync_uncertainty_ms",
    "sync_sample_period_ms",
    "camera_frame_index",
    "camera_sample_time_s",
    "camera_callback_time_s",
    "camera_legacy_time_s",
    "camera_aligned_time_s",
    "alignment_delta_ms",
    "camera_event_delta_ms",
    "device_anomaly",
    "anomaly_reasons",
    "phase_offset",
    "phase_epoch",
    "phase_action",
    "phase_flip_start_event_id",
    "phase_flip_confirm_event_id",
    "manual_label",
    "is_match",
)


VALIDATOR_VISION_CONFIG = {
    "pre_event_ms": 250,
    "post_event_ms": 200,
    "inference_interval_ms": 60,
    "decision_timeout_ms": 500,
    "min_confidence": 0.65,
    "frame_buffer_ms": 1500,
    "max_frames": 180,
    "max_events": 16,
}


class JumpEventRoleTracker:
    """Distinguish the initial stand-in touch from landings after a lift."""

    def __init__(self) -> None:
        self._seen_touch = False
        self._lift_since_touch = False

    def observe(self, kind: str) -> str | None:
        normalized = kind.lower()
        if normalized == "lift":
            self._lift_since_touch = True
            return None
        if normalized != "touch":
            return None
        if self._lift_since_touch:
            role = "landing"
        elif not self._seen_touch:
            role = "baseline"
        else:
            role = "unpaired_touch"
        self._seen_touch = True
        self._lift_since_touch = False
        return role


def validation_metrics(rows) -> dict[str, float | int]:
    eligible = [
        row
        for row in rows
        if row.get("event_role", "grid_touch") in ("grid_touch", "landing")
    ]
    reviewed = [
        row
        for row in eligible
        if row.get("manual_label") in ("left", "right", "both")
    ]
    covered = sum(row.get("vision_label") != "unknown" for row in eligible)
    return {
        "eligible": len(eligible),
        "reviewed": len(reviewed),
        "correct": sum(row.get("is_match") == "1" for row in reviewed),
        "wrong": sum(row.get("is_match") == "0" for row in reviewed),
        "coverage_percent": covered / len(eligible) * 100.0 if eligible else 0.0,
    }


def event_sync_rejection_reason(status: str) -> str | None:
    if status in ("ready", "unsupported"):
        return None
    if status == "degraded":
        return "clock_sync_degraded"
    return "clock_sync_unavailable"


def _stream_fps(timestamps, *, now_s: float | None = None) -> float:
    if len(timestamps) < 2:
        return 0.0
    if now_s is not None and now_s - timestamps[-1] > 1.0:
        return 0.0
    elapsed = timestamps[-1] - timestamps[0]
    return (len(timestamps) - 1) / elapsed if elapsed > 0 else 0.0


def _csv_float(value, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{float(value):.{digits}f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate MediaPipe landing-foot labels on real grid touch events."
    )
    parser.add_argument("--camera", choices=("tinyse",), default="tinyse")
    parser.add_argument("--model", required=True, help="Path to Pose Landmarker Full .task")
    parser.add_argument(
        "--output",
        default="vision-event-validation.csv",
        help="Legacy live-validation CSV path",
    )
    parser.add_argument(
        "--output-root",
        default="data/vision_sessions",
        help="Root directory for collision-free vision session packages",
    )
    parser.add_argument(
        "--scenario",
        default="normal",
        help="Default scenario stored on this session and its events",
    )
    parser.add_argument(
        "--mode",
        choices=("treadmill-gait", "treadmill-running", "jump"),
        default="treadmill-gait",
    )
    parser.add_argument("--speed", type=_positive_float, default=1.0)
    parser.add_argument(
        "--direction",
        choices=("Interface side", "Opposite side"),
        default="Interface side",
    )
    parser.add_argument("--starting-foot", choices=("left", "right"))
    parser.add_argument(
        "--treadmill-rear",
        type=_normalized_point,
        help="Optional normalized x,y point at the rear of the visible belt",
    )
    parser.add_argument(
        "--treadmill-front",
        type=_normalized_point,
        help="Optional normalized x,y point at the front of the visible belt",
    )
    return parser


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("speed must be positive")
    return parsed


def _normalized_point(value: str) -> tuple[float, float]:
    try:
        x_text, y_text = value.split(",", 1)
        point = float(x_text), float(y_text)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("point must be normalized x,y") from exc
    if not all(0.0 <= item <= 1.0 for item in point):
        raise argparse.ArgumentTypeError("point coordinates must be between 0 and 1")
    return point


def absolute_event_time(session_start_s: float, relative_event_s: float) -> float:
    return session_start_s + relative_event_s


def build_session_config(args: argparse.Namespace):
    if args.mode == "jump":
        from config.test_config import TestConfig

        return TestConfig(
            test_type="Jump Test",
            stop_type="Software command",
            number_of_jumps=None,
        )

    from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig

    common = {
        "stop_type": "Software command",
        "test_length": None,
        "treadmill_speed": args.speed,
        "direction": args.direction,
        "starting_foot_override": args.starting_foot,
    }
    if args.mode == "treadmill-running":
        return TreadmillRunningConfig(**common)
    return TreadmillGaitConfig(**common)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


def run(args: argparse.Namespace) -> int:
    if (args.treadmill_rear is None) != (args.treadmill_front is None):
        raise ValueError("--treadmill-rear and --treadmill-front must be provided together")
    import cv2
    from qtpy.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
    from qtpy.QtGui import QImage, QKeySequence, QPixmap, QShortcut
    from qtpy.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    from camera.logi_camera import CAMERA_INDEX, CameraCapture
    from camera.tinyse_camera import TinySeCameraCapture
    from ui.session_controller import SessionController
    from vision import (
        CameraClockSynchronizer,
        ClockSyncStatus,
        FootLabel,
        FootVisionService,
        VisionConfig,
    )
    from vision.foot_reference import (
        LANDING_CLASSIFIER_ENTRYPOINT,
        LANDING_CLASSIFIER_VERSION,
        classify_landing_event,
        unknown_decision,
    )
    from vision.landing_v2 import (
        LANDING_V2_ENTRYPOINT,
        LANDING_V2_VERSION,
        LandingV2Classifier,
    )
    from vision.phase_resync import (
        DeviceAnomalyDetector,
        DeviceLabelMapper,
        DevicePhaseInput,
        FootPhaseManager,
    )
    from vision.pose_overlay import draw_pose_overlay
    from vision.framing import check_framing
    from vision.session import (
        NullVisionSessionRecorder,
        VisionSessionRecorder,
        canonical_reject_reason,
        normalize_label,
        pose_sample_to_record,
    )

    class _Bridge(QObject):
        decision = Signal(object)
        pose = Signal(object)
        inference = Signal(object)
        status = Signal(str)

    class _CalibrationLabel(QLabel):
        normalized_clicked = Signal(float, float)

        def mousePressEvent(self, event) -> None:
            pixmap = self.pixmap()
            if pixmap is None or pixmap.width() <= 0 or pixmap.height() <= 0:
                return super().mousePressEvent(event)
            offset_x = (self.width() - pixmap.width()) / 2.0
            offset_y = (self.height() - pixmap.height()) / 2.0
            x = (event.pos().x() - offset_x) / pixmap.width()
            y = (event.pos().y() - offset_y) / pixmap.height()
            if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                self.normalized_clicked.emit(x, y)
            super().mousePressEvent(event)

    class ValidationWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Iron_Jump 光栅触地 × 视觉落地脚验证")
            self.resize(1500, 860)
            self._closing = False
            self._event_id = 0
            self._current_event_id = None
            self._capture = None
            self._camera_thread = None
            self._last_frame = None
            self._last_frame_timing = None
            self._analysis_times = deque(maxlen=180)
            self._pose_samples = deque(maxlen=64)
            self._framing_pose = None
            self._pose_ready_times = deque(maxlen=64)
            self._frame_timings = deque(maxlen=2048)
            self._event_frames = {}
            self._event_meta = {}
            self._phase_payloads = {}
            self._session_contact_records = {}
            self._next_session_contact_id = 1
            self._rows = {}
            self._row_order = []
            self._shortcuts = []
            self._jump_roles = JumpEventRoleTracker()
            self._seen_gait_touch = False
            self._grid_session_started = False
            self._video_record_started = False
            self._video_record_failed = False
            self._label_mapper = DeviceLabelMapper(args.starting_foot)
            self._anomaly_detector = DeviceAnomalyDetector()
            self._phase_manager = FootPhaseManager()
            self._calibration_clicks = None
            self._landing_v2 = LandingV2Classifier(
                args.treadmill_rear,
                args.treadmill_front,
            )
            self._analysis_resolution = (1920, 1080)
            self._clock_sync = (
                CameraClockSynchronizer() if args.camera == "tinyse" else None
            )
            self._sync_snapshot = (
                self._clock_sync.snapshot if self._clock_sync is not None else None
            )
            self._output_path = Path(args.output).expanduser().resolve()
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                active_version = (
                    LANDING_V2_VERSION
                    if args.mode in ("treadmill-gait", "treadmill-running")
                    else LANDING_CLASSIFIER_VERSION
                )
                active_entrypoint = (
                    LANDING_V2_ENTRYPOINT
                    if args.mode in ("treadmill-gait", "treadmill-running")
                    else LANDING_CLASSIFIER_ENTRYPOINT
                )
                self._recorder = VisionSessionRecorder(
                    args.output_root,
                    metadata={
                        "camera_name": "OBSBOT Tiny SE",
                        "camera_resolution": {"width": 1920, "height": 1080},
                        "camera_fps": 100,
                        "mediapipe_model": str(Path(args.model).expanduser()),
                        "pose_inference_interval_ms": VALIDATOR_VISION_CONFIG["inference_interval_ms"],
                        "classifier_version": active_version,
                        "classifier_entrypoint": active_entrypoint,
                        "vision_config": dict(VALIDATOR_VISION_CONFIG),
                        "project_mode": args.mode,
                        "scenario": args.scenario,
                        "treadmill_axis_calibration": {
                            "rear_normalized": list(args.treadmill_rear) if args.treadmill_rear else None,
                            "front_normalized": list(args.treadmill_front) if args.treadmill_front else None,
                            "analysis_mirrored": False,
                        },
                    },
                )
            except Exception as exc:
                self._recorder = NullVisionSessionRecorder(args.output_root)
                self._recorder.add_error("session", str(exc))

            self._live_preview = _CalibrationLabel("正在连接相机……")
            self._live_preview.setAlignment(Qt.AlignCenter)
            self._live_preview.setMinimumSize(900, 540)
            self._live_preview.setStyleSheet("background:#111; color:#aaa;")
            self._event_preview = QLabel("等待真实光栅触地事件")
            self._event_preview.setAlignment(Qt.AlignCenter)
            self._event_preview.setMinimumSize(480, 300)
            self._event_preview.setStyleSheet("background:#181818; color:#aaa;")

            previews = QHBoxLayout()
            previews.addWidget(self._live_preview, 2)
            previews.addWidget(self._event_preview, 1)

            self._result = QLabel("等待光栅 touch……")
            self._result.setStyleSheet("font-size:20px; font-weight:700;")
            self._reason = QLabel("视觉模型正在初始化……")
            self._framing = QLabel(check_framing(None, now_s=time.perf_counter()).message)
            self._framing.setWordWrap(True)
            self._device = QLabel("光栅会话正在初始化……")
            self._queue = QLabel("队列：frames=0 events=0")
            self._metrics = QLabel("已标注 0 | 正确 0 | 错误 0 | 视觉覆盖率 0.0%")
            self._calibrate_button = QPushButton("标定跑带方向")
            self._calibrate_button.clicked.connect(self._begin_axis_calibration)
            self._manual_phase_button = QPushButton("校正左右脚相位")
            self._manual_phase_button.clicked.connect(self._manual_phase_flip)
            self._live_preview.normalized_clicked.connect(self._on_calibration_click)
            self._help = QLabel(
                "真实 touch 到来后自动判断落地脚；右侧保留事件画面。\n"
                "启动时先保持光栅无接触；L 左脚 / R 右脚 / B 双脚 / "
                "U 无法判断    Q 退出；Jump 首次站入标记为 baseline\n"
                f"vision session: {self._recorder.session_root}"
            )

            layout = QVBoxLayout(self)
            layout.addLayout(previews, 1)
            layout.addWidget(self._result)
            layout.addWidget(self._reason)
            layout.addWidget(self._framing)
            layout.addWidget(self._device)
            layout.addWidget(self._queue)
            layout.addWidget(self._metrics)
            controls = QHBoxLayout()
            controls.addWidget(self._calibrate_button)
            controls.addWidget(self._manual_phase_button)
            controls.addStretch(1)
            layout.addLayout(controls)
            layout.addWidget(self._help)

            self._install_shortcut("Q", self.close)
            self._install_shortcut("L", lambda: self._annotate("left"))
            self._install_shortcut("R", lambda: self._annotate("right"))
            self._install_shortcut("B", lambda: self._annotate("both"))
            self._install_shortcut("U", lambda: self._annotate("unknown"))

            self._bridge = _Bridge(self)
            self._bridge.decision.connect(self._on_decision)
            self._bridge.pose.connect(self._on_pose_sample)
            self._bridge.inference.connect(self._on_pose_inference)
            self._bridge.status.connect(self._on_vision_status)

            classifier = (
                self._landing_v2
                if args.mode in ("treadmill-gait", "treadmill-running")
                else classify_landing_event
            )
            self._service = FootVisionService(
                VisionConfig(**VALIDATOR_VISION_CONFIG),
                Path(args.model).expanduser(),
                classifier=classifier,
            )
            self._service.decision_ready.connect(self._bridge.decision.emit)
            self._service.pose_ready.connect(self._bridge.pose.emit)
            self._service.pose_inference_ready.connect(self._bridge.inference.emit)
            self._service.status_changed.connect(self._bridge.status.emit)
            self._service.start()

            self._controller = SessionController(self)
            self._controller.gait_step_event.connect(self._on_gait_step_event)
            self._controller.hop_event.connect(self._on_hop_event)
            self._controller.device_message.connect(self._on_device_message)
            self._controller.session_finished.connect(self._on_session_finished)

            self._queue_timer = QTimer(self)
            self._queue_timer.timeout.connect(self._refresh_queue)
            self._queue_timer.start(100)

            self._write_csv()
            try:
                self._start_camera()
                if args.camera != "tinyse":
                    self._start_grid_session()
            except Exception as exc:
                self._device.setText(f"启动失败：{exc}")

        def _start_grid_session(self) -> None:
            if self._grid_session_started:
                return
            self._controller.prepare(build_session_config(args))
            self._controller.start()
            self._grid_session_started = True
            self._device.setText("光栅会话已启动；请先保持检测区空闲 1–2 秒")

        def _install_shortcut(self, key: str, callback) -> None:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

        def _begin_axis_calibration(self) -> None:
            self._calibration_clicks = []
            self._reason.setText(
                "跑带方向标定：请在左侧画面依次点击跑带后端、前端。"
            )

        @Slot(float, float)
        def _on_calibration_click(self, x: float, y: float) -> None:
            if self._calibration_clicks is None:
                return
            self._calibration_clicks.append((x, y))
            if len(self._calibration_clicks) == 1:
                self._reason.setText("已记录跑带后端；请点击跑带前端。")
                return
            rear, front = self._calibration_clicks[:2]
            self._landing_v2.set_axis_points(rear, front)
            self._recorder.update_metadata(
                treadmill_axis_calibration={
                    "rear_normalized": list(rear),
                    "front_normalized": list(front),
                    "analysis_mirrored": False,
                    "frame_width": self._analysis_resolution[0],
                    "frame_height": self._analysis_resolution[1],
                }
            )
            self._calibration_clicks = None
            self._reason.setText("跑带图像方向标定完成；下一次触地开始使用landing_v2。")

        def _manual_phase_flip(self) -> None:
            for result in self._phase_manager.manual_flip():
                self._finalize_phase_result(result)
            self._device.setText(
                "已手动校正左右脚相位；"
                f"phase epoch={self._phase_manager.phase_epoch}"
            )

        def _start_camera(self) -> None:
            if args.camera == "tinyse":
                capture = TinySeCameraCapture()
            else:
                capture = CameraCapture()
                if not capture.open(CAMERA_INDEX):
                    raise RuntimeError("无法打开 Logitech 相机")

            thread = QThread(self)
            capture.moveToThread(thread)
            if args.camera == "tinyse":
                capture.analysis_frame_timed_ready.connect(
                    self._on_timed_analysis_frame
                )
                capture.started.connect(self._ensure_video_recording)
            else:
                capture.analysis_frame_ready.connect(self._on_analysis_frame)
            capture.stats_updated.connect(self._on_camera_stats)
            capture.error.connect(self._on_camera_error)
            thread.started.connect(capture.start)
            thread.finished.connect(capture.deleteLater)
            self._capture = capture
            self._camera_thread = thread
            thread.start()

        @Slot(object, object)
        def _on_timed_analysis_frame(self, frame, timing) -> None:
            self._ensure_video_recording()
            synchronizer = self._clock_sync
            if synchronizer is None:
                return
            snapshot = synchronizer.observe(
                timing.sample_time_s,
                timing.callback_time_s,
                frame_index=timing.frame_index,
            )
            self._sync_snapshot = snapshot
            aligned_time_s = snapshot.aligned_time_s
            frame_timing = {
                "frame_index": timing.frame_index,
                "sample_time_s": timing.sample_time_s,
                "callback_time_s": timing.callback_time_s,
                "legacy_time_s": timing.decoded_at_s,
                "aligned_time_s": aligned_time_s,
                "alignment_delta_ms": (
                    (timing.decoded_at_s - aligned_time_s) * 1000.0
                    if aligned_time_s is not None
                    else None
                ),
            }
            self._last_frame_timing = frame_timing
            self._frame_timings.append(frame_timing)
            self._recorder.update_metadata(
                sync={
                    "state": snapshot.status.value,
                    "reason": snapshot.reason,
                    "offset_ms": snapshot.offset_ms,
                    "uncertainty_ms": snapshot.uncertainty_ms,
                    "warmup_ms": snapshot.warmup_ms,
                }
            )
            if snapshot.status is ClockSyncStatus.READY and aligned_time_s is not None:
                self._analysis_times.append(aligned_time_s)
                self._service.submit_frame(frame, aligned_time_s)
                self._render_analysis_frame(frame, aligned_time_s)
                if not self._grid_session_started:
                    try:
                        self._start_grid_session()
                    except Exception as exc:
                        self._device.setText(f"光栅启动失败：{exc}")
                return

            self._last_frame = frame
            annotated = draw_pose_overlay(frame.copy(), None)
            self._set_preview(self._live_preview, annotated)
            if snapshot.status is ClockSyncStatus.WARMING_UP:
                self._device.setText(
                    "TinySE 时间同步中："
                    f"{synchronizer.sample_count}/30；请保持光栅检测区空闲"
                )
            else:
                self._device.setText(
                    f"TinySE 时间同步失效：{snapshot.reason}；视觉事件将拒识"
                )

        @Slot(object, float)
        def _on_analysis_frame(self, frame, captured_at_s: float) -> None:
            self._last_frame_timing = {
                "frame_index": None,
                "sample_time_s": None,
                "callback_time_s": None,
                "legacy_time_s": captured_at_s,
                "aligned_time_s": captured_at_s,
                "alignment_delta_ms": 0.0,
            }
            self._analysis_times.append(captured_at_s)
            self._service.submit_frame(frame, captured_at_s)
            self._render_analysis_frame(frame, captured_at_s)

        def _render_analysis_frame(self, frame, captured_at_s: float) -> None:
            height, width = frame.shape[:2]
            resolution = (width, height)
            if resolution != self._analysis_resolution:
                self._analysis_resolution = resolution
                if self._landing_v2.set_frame_geometry(width, height):
                    self._calibration_clicks = None
                    self._recorder.update_metadata(
                        camera_resolution={"width": width, "height": height},
                        treadmill_axis_calibration={
                            "rear_normalized": None,
                            "front_normalized": None,
                            "analysis_mirrored": False,
                            "invalid_reason": "analysis_resolution_changed",
                        },
                    )
                    self._reason.setText("分析分辨率已变化；请重新标定跑带方向。")
            self._last_frame = frame
            pose = self._nearest_pose(captured_at_s, max_delta_s=0.30)
            annotated = draw_pose_overlay(frame.copy(), pose)
            self._set_preview(self._live_preview, annotated)

        @Slot(object)
        def _on_pose_sample(self, sample) -> None:
            self._pose_samples.append(sample)
            self._pose_ready_times.append(time.perf_counter())

        @Slot(object)
        def _on_pose_inference(self, inference) -> None:
            self._framing_pose = inference.pose
            timing = self._nearest_frame_timing(inference.frame_timestamp_s)
            self._recorder.record_pose(
                pose_sample_to_record(
                    inference.pose,
                    frame_index=timing.get("frame_index") if timing else None,
                    camera_sample_timestamp=(
                        timing.get("sample_time_s") if timing else None
                    ),
                    perf_counter_timestamp=inference.frame_timestamp_s,
                    inference_start_timestamp=inference.inference_start_timestamp_s,
                    inference_end_timestamp=inference.inference_end_timestamp_s,
                    error=inference.error,
                )
            )

        def _nearest_frame_timing(self, timestamp_s: float):
            if not self._frame_timings:
                return None
            return min(
                self._frame_timings,
                key=lambda item: abs((item.get("aligned_time_s") or -1.0) - timestamp_s),
            )

        def _ensure_video_recording(self) -> None:
            if self._video_record_started or self._video_record_failed:
                return
            capture = self._capture
            if capture is None:
                return
            try:
                native_capture = getattr(capture, "_capture", None)
                if native_capture is not None:
                    capture_stats = native_capture.stats()
                    self._recorder.update_metadata(
                        camera_resolution={
                            "width": int(capture_stats.connected_width),
                            "height": int(capture_stats.connected_height),
                        },
                        camera_fps=float(capture_stats.connected_fps),
                    )
            except Exception as exc:
                self._recorder.add_error("camera_metadata", str(exc))
            try:
                path = capture.start_record(
                    self._recorder.paths.video.with_suffix(""),
                    preserve_raw=True,
                )
            except Exception as exc:
                path = None
                self._recorder.add_error("video", str(exc))
            if path is None:
                self._video_record_failed = True
                self._recorder.add_error("video", "TinySE native recording did not start")
                self._recorder.update_metadata(recording={"status": "failed"})
                return
            self._video_record_started = True
            self._recorder.update_metadata(
                recording={
                    "status": "recording",
                    "video": self._recorder.paths.video.name,
                    "index": self._recorder.paths.video_index.name,
                }
            )

        @Slot(object)
        def _on_gait_step_event(self, ev) -> None:
            if ev.kind != "touch":
                lift_time = getattr(ev.contact, "lift_time", None)
                if lift_time is not None:
                    self._record_nonbenchmark_event(
                        lift_time,
                        event_role="lift",
                        source_contact_id=getattr(ev.contact, "contact_id", ""),
                        source_grid_label=getattr(ev.contact, "foot_label", "") or "",
                    )
                return
            relative_time = ev.contact.touch_time
            if relative_time is None:
                return
            event_role = "grid_touch" if self._seen_gait_touch else "initial_touch"
            self._seen_gait_touch = True
            self._submit_project_touch(
                relative_time,
                source_contact_id=ev.contact.contact_id,
                source_grid_label=ev.contact.foot_label or "",
                source_label_confidence=getattr(ev.contact, "label_confidence", None),
                event_role=event_role,
            )

        @Slot(object)
        def _on_hop_event(self, ev) -> None:
            if str(ev.kind).lower() == "lift":
                self._jump_roles.observe(ev.kind)
                self._record_nonbenchmark_event(ev.time, event_role="lift")
                return
            event_role = self._jump_roles.observe(ev.kind)
            if event_role is None:
                return
            self._submit_project_touch(
                ev.time,
                source_contact_id="",
                source_grid_label="",
                source_label_confidence=None,
                event_role=event_role,
            )

        def _record_nonbenchmark_event(
            self,
            relative_time_s: float,
            *,
            event_role: str,
            source_contact_id: str = "",
            source_grid_label: str = "",
        ) -> None:
            start_time = self._controller.start_time
            if start_time is None:
                return
            self._event_id += 1
            event_id = self._event_id
            event_time_s = absolute_event_time(start_time, relative_time_s)
            snapshot = self._sync_snapshot
            sync_status = snapshot.status.value if snapshot is not None else "warming_up"
            offset_ms = snapshot.offset_ms if snapshot is not None else None
            timing = self._last_frame_timing or {}
            self._queue_session_contact(
                event_id,
                {
                    "event_id": event_id,
                    "contact_timestamp": f"{event_time_s:.9f}",
                    "camera_sample_timestamp": _csv_float(
                        event_time_s - offset_ms / 1000.0
                        if offset_ms is not None
                        else timing.get("sample_time_s"),
                        9,
                    ),
                    "camera_aligned_timestamp": _csv_float(
                        timing.get("aligned_time_s"), 9
                    ),
                    "camera_event_delta_ms": _csv_float(
                        (timing.get("aligned_time_s") - event_time_s) * 1000.0
                        if timing.get("aligned_time_s") is not None
                        else None
                    ),
                    "original_grating_label": source_grid_label,
                    "visual_label": "Unknown",
                    "visual_raw_label": "",
                    "visual_raw_score": "",
                    "reject_reason": "none",
                    "raw_reason": "not_classified",
                    "sync_state": sync_status,
                    "sync_uncertainty_ms": _csv_float(
                        snapshot.uncertainty_ms if snapshot is not None else None
                    ),
                    "sync_offset_ms": _csv_float(offset_ms),
                    "pre_pose_count": "",
                    "post_pose_count": "",
                    "classifier_version": LANDING_CLASSIFIER_VERSION,
                    "classifier_entrypoint": LANDING_CLASSIFIER_ENTRYPOINT,
                    "project_mode": args.mode,
                    "event_role": event_role,
                    "source_contact_id": source_contact_id,
                    "valid_for_benchmark": "0",
                    "scenario": args.scenario,
                }
            )

        def _submit_project_touch(
            self,
            relative_time_s: float,
            *,
            source_contact_id,
            source_grid_label: str,
            source_label_confidence: float | None,
            event_role: str,
        ) -> None:
            start_time = self._controller.start_time
            if start_time is None:
                return
            self._event_id += 1
            event_id = self._event_id
            event_time_s = absolute_event_time(start_time, relative_time_s)
            snapshot = self._sync_snapshot
            sync_status = (
                snapshot.status.value if snapshot is not None else "unsupported"
            )
            timing = self._last_frame_timing or {}
            self._event_meta[event_id] = {
                "event_time_s": event_time_s,
                "event_role": event_role,
                "source_contact_id": source_contact_id,
                "source_grid_label": source_grid_label,
                "source_label_confidence": source_label_confidence,
                "sync_status": sync_status,
                "sync_reason": (
                    snapshot.reason if snapshot is not None else "unsupported"
                ),
                "sync_warmup_ms": (
                    snapshot.warmup_ms if snapshot is not None else None
                ),
                "sync_offset_ms": (
                    snapshot.offset_ms if snapshot is not None else None
                ),
                "sync_uncertainty_ms": (
                    snapshot.uncertainty_ms if snapshot is not None else None
                ),
                "sync_sample_period_ms": (
                    snapshot.sample_period_ms if snapshot is not None else None
                ),
                "camera_frame_index": timing.get("frame_index"),
                "camera_sample_time_s": timing.get("sample_time_s"),
                "camera_callback_time_s": timing.get("callback_time_s"),
                "camera_legacy_time_s": timing.get("legacy_time_s"),
                "camera_aligned_time_s": timing.get("aligned_time_s"),
                "alignment_delta_ms": timing.get("alignment_delta_ms"),
                "camera_event_delta_ms": (
                    (timing["aligned_time_s"] - event_time_s) * 1000.0
                    if timing.get("aligned_time_s") is not None
                    else None
                ),
            }
            if self._last_frame is not None:
                frame_time_s = timing.get("aligned_time_s")
                if frame_time_s is None:
                    frame_time_s = event_time_s
                self._event_frames[event_id] = (
                    self._small_snapshot(self._last_frame),
                    frame_time_s,
                )
                while len(self._event_frames) > 16:
                    self._event_frames.pop(next(iter(self._event_frames)))
            self._result.setText(
                f"光栅触地事件 {event_id}：等待事件后视觉窗口……"
            )
            rejection_reason = (
                event_sync_rejection_reason(sync_status)
                if args.camera == "tinyse"
                else None
            )

            if rejection_reason is not None:
                self._on_decision(
                    unknown_decision(
                        event_id,
                        event_time_s,
                        rejection_reason,
                        decided_at_s=time.perf_counter(),
                    )
                )
            else:
                self._service.submit_touch_event(event_id, event_time_s)

        @Slot(object)
        def _on_decision(self, decision) -> None:
            raw_decision = decision
            meta = dict(self._event_meta.get(decision.event_id, {}))
            current_sync = self._sync_snapshot
            if (
                args.camera == "tinyse"
                and current_sync is not None
                and current_sync.status is ClockSyncStatus.DEGRADED
            ):
                decision = replace(
                    decision,
                    label=FootLabel.UNKNOWN,
                    confidence=0.0,
                    reason="clock_sync_degraded",
                    candidate_label=None,
                )
                meta["sync_status"] = "degraded"
                meta["sync_reason"] = current_sync.reason
                meta["sync_uncertainty_ms"] = current_sync.uncertainty_ms
            self._event_meta[decision.event_id] = meta

            decided_at_s = decision.decided_at_s or time.perf_counter()
            latency_ms = (decided_at_s - decision.event_time_s) * 1000.0
            candidate = decision.candidate_label
            previous = self._rows.get(decision.event_id, {})
            diagnostics = decision.diagnostics
            analysis_fps = _stream_fps(
                self._analysis_times,
                now_s=decided_at_s,
            )
            pose_fps = _stream_fps(self._pose_ready_times, now_s=decided_at_s)
            row = {
                "event_id": decision.event_id,
                "event_time_s": f"{decision.event_time_s:.9f}",
                "decided_at_s": f"{decided_at_s:.9f}",
                "project_mode": args.mode,
                "event_role": meta.get("event_role", "grid_touch"),
                "source_contact_id": meta.get("source_contact_id", ""),
                "source_grid_label": meta.get("source_grid_label", ""),
                "raw_device_label": "",
                "effective_device_label": "",
                "final_label": "",
                "vision_label": decision.label.value,
                "left_evidence": _csv_float(decision.left_evidence, 6),
                "right_evidence": _csv_float(decision.right_evidence, 6),
                "candidate_label": candidate.value if candidate is not None else "",
                "confidence": f"{decision.confidence:.6f}",
                "reason": decision.reason,
                "latency_ms": f"{latency_ms:.3f}",
                "window_frame_count": (
                    diagnostics.frame_count if diagnostics is not None else ""
                ),
                "inference_attempts": (
                    diagnostics.inference_attempts if diagnostics is not None else ""
                ),
                "pose_total": (
                    diagnostics.pose_total if diagnostics is not None else ""
                ),
                "pose_before": (
                    diagnostics.pose_before if diagnostics is not None else ""
                ),
                "pose_after": (
                    diagnostics.pose_after if diagnostics is not None else ""
                ),
                "max_pose_gap_ms": _csv_float(
                    diagnostics.max_pose_gap_ms if diagnostics is not None else None
                ),
                "analysis_fps": _csv_float(analysis_fps),
                "pose_fps": _csv_float(pose_fps),
                "sync_status": meta.get("sync_status", ""),
                "sync_reason": meta.get("sync_reason", ""),
                "sync_warmup_ms": _csv_float(meta.get("sync_warmup_ms")),
                "sync_offset_ms": _csv_float(meta.get("sync_offset_ms")),
                "sync_uncertainty_ms": _csv_float(
                    meta.get("sync_uncertainty_ms")
                ),
                "sync_sample_period_ms": _csv_float(
                    meta.get("sync_sample_period_ms")
                ),
                "camera_frame_index": (
                    meta.get("camera_frame_index")
                    if meta.get("camera_frame_index") is not None
                    else ""
                ),
                "camera_sample_time_s": _csv_float(
                    meta.get("camera_sample_time_s"),
                    9,
                ),
                "camera_callback_time_s": _csv_float(
                    meta.get("camera_callback_time_s"),
                    9,
                ),
                "camera_legacy_time_s": _csv_float(
                    meta.get("camera_legacy_time_s"),
                    9,
                ),
                "camera_aligned_time_s": _csv_float(
                    meta.get("camera_aligned_time_s"),
                    9,
                ),
                "alignment_delta_ms": _csv_float(
                    meta.get("alignment_delta_ms")
                ),
                "camera_event_delta_ms": _csv_float(
                    meta.get("camera_event_delta_ms")
                ),
                "device_anomaly": "",
                "anomaly_reasons": "",
                "phase_offset": "",
                "phase_epoch": "",
                "phase_action": "pending",
                "phase_flip_start_event_id": "",
                "phase_flip_confirm_event_id": "",
                "manual_label": previous.get("manual_label", ""),
                "is_match": previous.get("is_match", ""),
            }
            self._rows[decision.event_id] = row
            if decision.event_id not in self._row_order:
                self._row_order.append(decision.event_id)
            self._current_event_id = decision.event_id
            self._write_csv()

            raw_device = self._label_mapper.map(meta.get("source_grid_label"))
            device_anomaly, anomaly_reasons = self._anomaly_detector.observe(
                raw_device,
                decision.event_time_s,
                label_confidence=meta.get("source_label_confidence"),
            )
            self._phase_payloads[decision.event_id] = {
                "decision": decision,
                "raw_decision": raw_decision,
                "meta": meta,
                "diagnostics": diagnostics,
            }
            phase_results = self._phase_manager.process(
                DevicePhaseInput(
                    event_id=decision.event_id,
                    raw_device_symbol=str(meta.get("source_grid_label", "")),
                    raw_device_label=raw_device,
                    visual_label=decision.label,
                    left_evidence=decision.left_evidence,
                    right_evidence=decision.right_evidence,
                    device_anomaly=device_anomaly,
                    anomaly_reasons=anomaly_reasons,
                )
            )
            for result in phase_results:
                self._finalize_phase_result(result)

            display_label = decision.label.value.upper()
            if decision.label.value == "unknown" and candidate is not None:
                display_label += f"（候选 {candidate.value.upper()}）"
            if phase_results:
                latest_phase = phase_results[-1]
                phase_text = (
                    f"设备 {latest_phase.raw_device_label.value.upper()}→"
                    f"{latest_phase.effective_device_label.value.upper()} | "
                    f"phase={latest_phase.phase_action} epoch={latest_phase.phase_epoch}"
                )
            else:
                phase_text = (
                    f"设备 {raw_device.value.upper()} | phase=SUSPECT，等待交叉反证"
                )
            self._result.setText(
                f"触地事件 {decision.event_id}：{display_label}  "
                f"分数 {decision.confidence:.3f}  延迟 {latency_ms:.1f} ms\n"
                f"{phase_text}"
            )
            if diagnostics is None:
                diagnostic_text = ""
            else:
                max_gap = _csv_float(diagnostics.max_pose_gap_ms) or "N/A"
                diagnostic_text = (
                    f" | frames={diagnostics.frame_count} "
                    f"attempts={diagnostics.inference_attempts} "
                    f"pose={diagnostics.pose_total} "
                    f"before/after={diagnostics.pose_before}/{diagnostics.pose_after} "
                    f"max_gap={max_gap}ms"
                )
            sync_diagnostics = (
                f"sync={meta.get('sync_status', '')} "
                f"detail={meta.get('sync_reason', '')} "
                f"offset={_csv_float(meta.get('sync_offset_ms')) or 'N/A'}ms "
                "uncertainty="
                f"{_csv_float(meta.get('sync_uncertainty_ms')) or 'N/A'}ms "
                f"period={_csv_float(meta.get('sync_sample_period_ms')) or 'N/A'}ms "
                "legacy-aligned="
                f"{_csv_float(meta.get('alignment_delta_ms')) or 'N/A'}ms"
            )
            self._reason.setText(
                f"原因：{decision.reason}{diagnostic_text}\n{sync_diagnostics}"
            )
            self._show_event_snapshot(decision)
            self._refresh_metrics()

        def _finalize_phase_result(self, result) -> None:
            payload = self._phase_payloads.pop(result.event_id, None)
            if payload is None:
                return
            decision = payload["decision"]
            raw_decision = payload["raw_decision"]
            meta = payload["meta"]
            diagnostics = payload["diagnostics"]
            classifier_diagnostics = decision.classifier_diagnostics or {}
            row = self._rows.get(result.event_id)
            if row is not None:
                row.update(
                    raw_device_label=result.raw_device_label.value,
                    effective_device_label=result.effective_device_label.value,
                    final_label=result.final_label.value,
                    device_anomaly="1" if result.device_anomaly else "0",
                    anomaly_reasons="|".join(result.anomaly_reasons),
                    phase_offset="1" if result.phase_offset else "0",
                    phase_epoch=result.phase_epoch,
                    phase_action=result.phase_action,
                    phase_flip_start_event_id=result.phase_flip_start_event_id or "",
                    phase_flip_confirm_event_id=result.phase_flip_confirm_event_id or "",
                )
                self._write_csv()

            raw_label = raw_decision.label.value
            persisted_label = normalize_label(decision.label.value) or "Unknown"
            if raw_label == "both":
                persisted_label = "Unknown"
            event_role = str(meta.get("event_role", "grid_touch"))
            valid_for_benchmark = (
                args.mode in ("treadmill-gait", "treadmill-running")
                and event_role == "grid_touch"
            )
            active_version = (
                LANDING_V2_VERSION
                if args.mode in ("treadmill-gait", "treadmill-running")
                else LANDING_CLASSIFIER_VERSION
            )
            active_entrypoint = (
                LANDING_V2_ENTRYPOINT
                if args.mode in ("treadmill-gait", "treadmill-running")
                else LANDING_CLASSIFIER_ENTRYPOINT
            )
            record = {
                "event_id": decision.event_id,
                "contact_timestamp": f"{decision.event_time_s:.9f}",
                "camera_sample_timestamp": _csv_float(
                    decision.event_time_s - float(meta["sync_offset_ms"]) / 1000.0
                    if meta.get("sync_offset_ms") is not None
                    else meta.get("camera_sample_time_s"),
                    9,
                ),
                "camera_aligned_timestamp": _csv_float(meta.get("camera_aligned_time_s"), 9),
                "camera_event_delta_ms": _csv_float(meta.get("camera_event_delta_ms")),
                "original_grating_label": meta.get("source_grid_label", ""),
                "raw_device_symbol": result.raw_device_symbol,
                "raw_device_label": result.raw_device_label.value,
                "effective_device_label": result.effective_device_label.value,
                "final_label": result.final_label.value,
                "visual_label": persisted_label,
                "left_evidence": _csv_float(result.left_evidence, 6),
                "right_evidence": _csv_float(result.right_evidence, 6),
                "visual_raw_label": raw_label,
                "visual_raw_score": f"{raw_decision.confidence:.6f}",
                "reject_reason": canonical_reject_reason(decision.reason, raw_label),
                "raw_reason": decision.reason,
                "device_anomaly": "1" if result.device_anomaly else "0",
                "anomaly_reasons": "|".join(result.anomaly_reasons),
                "phase_suspect_trigger": "1" if result.phase_suspect_trigger else "0",
                "phase_offset": "1" if result.phase_offset else "0",
                "phase_epoch": result.phase_epoch,
                "phase_action": result.phase_action,
                "suspect_start_event_id": result.suspect_start_event_id or "",
                "first_mismatch_device_label": (
                    result.first_mismatch_device_label.value
                    if result.first_mismatch_device_label is not None else ""
                ),
                "first_mismatch_visual_label": (
                    result.first_mismatch_visual_label.value
                    if result.first_mismatch_visual_label is not None else ""
                ),
                "pending_contact_count": result.pending_contact_count,
                "suspect_unknown_count": result.suspect_unknown_count,
                "phase_flip_reason": result.phase_flip_reason,
                "phase_flip_start_event_id": result.phase_flip_start_event_id or "",
                "phase_flip_confirm_event_id": result.phase_flip_confirm_event_id or "",
                "sync_state": meta.get("sync_status", ""),
                "sync_uncertainty_ms": _csv_float(meta.get("sync_uncertainty_ms")),
                "sync_offset_ms": _csv_float(meta.get("sync_offset_ms")),
                "pre_pose_count": diagnostics.pose_before if diagnostics is not None else "",
                "post_pose_count": diagnostics.pose_after if diagnostics is not None else "",
                "max_pose_gap_ms": (
                    diagnostics.max_pose_gap_ms if diagnostics is not None else ""
                ),
                "classifier_version": active_version,
                "classifier_entrypoint": active_entrypoint,
                "project_mode": args.mode,
                "event_role": event_role,
                "source_contact_id": meta.get("source_contact_id", ""),
                "valid_for_benchmark": "1" if valid_for_benchmark else "0",
                "scenario": args.scenario,
            }
            for key in (
                "left_observation_quality", "right_observation_quality",
                "left_contact_evidence", "right_contact_evidence",
                "left_peak_phase", "right_peak_phase",
                "left_velocity_turn", "right_velocity_turn",
                "left_post_backward", "right_post_backward",
                "left_pre_velocity", "right_pre_velocity",
                "left_post_velocity", "right_post_velocity",
                "left_longitudinal_peak_time_delta", "right_longitudinal_peak_time_delta",
                "left_hip_foot_distance_peak_time_delta", "right_hip_foot_distance_peak_time_delta",
                "calibration_status", "basis_determinant", "forward_axis_angle_degrees",
            ):
                record[key] = classifier_diagnostics.get(key, "")
            self._queue_session_contact(result.event_id, record)

        def _queue_session_contact(self, event_id: int, record: dict) -> None:
            self._session_contact_records[event_id] = record
            self._drain_session_contacts()

        def _drain_session_contacts(self, *, force: bool = False) -> None:
            while self._next_session_contact_id in self._session_contact_records:
                record = self._session_contact_records.pop(self._next_session_contact_id)
                self._recorder.record_contact(record)
                self._next_session_contact_id += 1
            if force and self._session_contact_records:
                for event_id in sorted(self._session_contact_records):
                    self._recorder.record_contact(self._session_contact_records[event_id])
                self._session_contact_records.clear()

        def _show_event_snapshot(self, decision) -> None:
            snapshot = self._event_frames.pop(decision.event_id, None)
            if snapshot is None:
                return
            frame, frame_time_s = snapshot
            pose = self._nearest_pose(frame_time_s, max_delta_s=0.20)
            annotated = draw_pose_overlay(frame.copy(), pose)
            cv2.putText(
                annotated,
                f"EVENT {decision.event_id}: {decision.label.value.upper()} "
                f"{decision.confidence:.2f}",
                (16, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            self._set_preview(self._event_preview, annotated)

        def _annotate(self, label: str) -> None:
            event_id = self._current_event_id
            if event_id is None or event_id not in self._rows:
                return
            row = self._rows[event_id]
            row["manual_label"] = label
            if label == "unknown":
                row["is_match"] = ""
            else:
                row["is_match"] = "1" if row["vision_label"] == label else "0"
            self._write_csv()
            self._refresh_metrics()

        def _nearest_pose(self, timestamp_s: float, *, max_delta_s: float):
            if not self._pose_samples:
                return None
            sample = min(
                self._pose_samples,
                key=lambda item: abs(item.timestamp_s - timestamp_s),
            )
            if abs(sample.timestamp_s - timestamp_s) > max_delta_s:
                return None
            return sample

        @staticmethod
        def _small_snapshot(frame):
            height, width = frame.shape[:2]
            scale = min(1.0, 640.0 / width)
            if scale == 1.0:
                return frame.copy()
            return cv2.resize(
                frame,
                (round(width * scale), round(height * scale)),
                interpolation=cv2.INTER_AREA,
            )

        @staticmethod
        def _set_preview(label, frame) -> None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = rgb.shape[:2]
            target = label.size()
            scale = min(target.width() / width, target.height() / height)
            display_size = (
                max(1, round(width * scale)),
                max(1, round(height * scale)),
            )
            if display_size != (width, height):
                rgb = cv2.resize(rgb, display_size, interpolation=cv2.INTER_AREA)
            image = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()
            label.setPixmap(QPixmap.fromImage(image))

        def _write_csv(self) -> None:
            with self._output_path.open("w", newline="", encoding="utf-8-sig") as file:
                writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
                writer.writeheader()
                for event_id in self._row_order:
                    writer.writerow(self._rows[event_id])

        def _refresh_metrics(self) -> None:
            metrics = validation_metrics(self._rows.values())
            self._metrics.setText(
                f"有效事件 {metrics['eligible']} | 已标注 {metrics['reviewed']} | "
                f"正确 {metrics['correct']} | 错误 {metrics['wrong']} | "
                f"视觉覆盖率 {metrics['coverage_percent']:.1f}%"
            )

        @Slot()
        def _refresh_queue(self) -> None:
            depth = self._service.queue_depth
            now_s = time.perf_counter()
            self._framing.setText(check_framing(
                self._framing_pose, now_s=now_s,
                min_quality=self._service.config.min_landmark_quality,
            ).message)
            analysis_fps = _stream_fps(self._analysis_times, now_s=now_s)
            pose_fps = _stream_fps(self._pose_ready_times, now_s=now_s)
            snapshot = self._sync_snapshot
            sync_status = (
                snapshot.status.value if snapshot is not None else "unsupported"
            )
            uncertainty = (
                _csv_float(snapshot.uncertainty_ms)
                if snapshot is not None
                else ""
            )
            sync_text = sync_status
            if uncertainty:
                sync_text += f" uncertainty={uncertainty}ms"
            self._queue.setText(
                f"队列：frames={depth['frames']} events={depth['events']} | "
                f"分析={analysis_fps:.1f} FPS Pose={pose_fps:.1f} FPS | "
                f"sync={sync_text}"
            )

        @Slot(str)
        def _on_vision_status(self, status: str) -> None:
            self._reason.setText(f"视觉服务：{status}")

        @Slot(str)
        def _on_device_message(self, message: str) -> None:
            self._device.setText(f"光栅：{message}")

        @Slot(object)
        def _on_session_finished(self, _report) -> None:
            self._device.setText("光栅会话已结束")

        @Slot(float, float)
        def _on_camera_stats(self, fps: float, _record_seconds: float) -> None:
            now_s = time.perf_counter()
            analysis_fps = _stream_fps(self._analysis_times, now_s=now_s)
            pose_fps = _stream_fps(self._pose_ready_times, now_s=now_s)
            self.setWindowTitle(
                "Iron_Jump 光栅触地 × 视觉落地脚验证 — "
                f"{args.mode} — {args.camera} — capture {fps:.1f} / "
                f"analysis {analysis_fps:.1f} / pose {pose_fps:.1f} FPS"
            )

        @Slot(str)
        def _on_camera_error(self, message: str) -> None:
            self._device.setText(f"相机错误：{message}")
            self._recorder.add_error("video", message)

        def _recording_summary(self) -> dict:
            stats = getattr(self._capture, "last_record_stats", None)
            if stats is None:
                return {
                    "status": "failed" if self._video_record_failed else "partial",
                    "written": 0,
                    "dropped": 0,
                    "queue_peak": 0,
                    "errors": [],
                    "video": self._recorder.paths.video.name,
                    "index": self._recorder.paths.video_index.name,
                }
            written = int(getattr(stats, "frames_written", 0))
            dropped = int(getattr(stats, "frames_dropped", 0))
            last_hresult = int(getattr(stats, "last_hresult", 0))
            complete = (
                written > 0
                and dropped == 0
                and last_hresult == 0
                and self._recorder.paths.video.exists()
                and self._recorder.paths.video_index.exists()
            )
            return {
                "status": "complete" if complete else "partial",
                "written": written,
                "dropped": dropped,
                "queue_peak": int(
                    getattr(stats, "queue_high_watermark_frames", 0)
                ),
                "queue_peak_bytes": int(
                    getattr(stats, "queue_high_watermark_bytes", 0)
                ),
                "bytes_written": int(getattr(stats, "bytes_written", 0)),
                "last_hresult": last_hresult,
                "errors": [],
                "video": self._recorder.paths.video.name,
                "index": self._recorder.paths.video_index.name,
            }

        def closeEvent(self, event) -> None:
            if self._closing:
                event.accept()
                return
            self._closing = True
            self._queue_timer.stop()
            if self._controller.is_running:
                self._controller.stop()
            capture = self._capture
            thread = self._camera_thread
            if capture is not None:
                if self._video_record_started:
                    try:
                        capture.stop_record(wait=True)
                    except Exception as exc:
                        self._recorder.add_error("video", str(exc))
                capture.stop()
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._service.stop()
            for result in self._phase_manager.flush():
                self._finalize_phase_result(result)
            self._drain_session_contacts(force=True)
            self._recorder.close(recording=self._recording_summary())
            event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    window = ValidationWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
