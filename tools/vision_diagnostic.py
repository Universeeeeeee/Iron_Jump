"""Standalone Windows diagnostic UI for the visual foot-reference service."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path



CSV_FIELDS = (
    "event_id",
    "event_time_s",
    "decided_at_s",
    "label",
    "confidence",
    "reason",
    "candidate_label",
    "latency_ms",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Show continuous MediaPipe foot labels from Tiny SE/Logitech."
    )
    parser.add_argument("--camera", choices=("tinyse", "logi"), default="tinyse")
    parser.add_argument("--model", required=True, help="Path to Pose Landmarker Full .task")
    parser.add_argument("--output", default="vision-results.csv", help="CSV result path")
    parser.add_argument(
        "--interval-ms",
        type=_positive_int,
        default=250,
        help="Rolling visual-state update interval (default: 250 ms)",
    )
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("interval must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


def run(args: argparse.Namespace) -> int:
    import cv2
    from qtpy.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
    from qtpy.QtGui import QImage, QKeySequence, QPixmap, QShortcut
    from qtpy.QtWidgets import (
        QApplication,
        QLabel,
        QVBoxLayout,
        QWidget,
    )

    from camera.logi_camera import CAMERA_INDEX, CameraCapture
    from camera.tinyse_camera import TinySeCameraCapture
    from vision import FootVisionService, VisionConfig
    from vision.pose_overlay import draw_pose_overlay

    class _Bridge(QObject):
        decision = Signal(object)
        pose = Signal(object)
        status = Signal(str)

    class DiagnosticWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Iron_Jump 左右脚视觉实时状态")
            self.resize(1100, 760)
            self._event_id = 0
            self._closing = False
            self._capture = None
            self._camera_thread = None
            self._latest_pose = None

            output_path = Path(args.output).expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._csv_file = output_path.open("w", newline="", encoding="utf-8-sig")
            self._csv = csv.DictWriter(self._csv_file, fieldnames=CSV_FIELDS)
            self._csv.writeheader()
            self._csv_file.flush()

            self._preview = QLabel("正在连接相机……")
            self._preview.setAlignment(Qt.AlignCenter)
            self._preview.setMinimumSize(960, 540)
            self._preview.setStyleSheet("background:#111; color:#aaa;")

            self._result = QLabel("等待视觉窗口……")
            self._result.setStyleSheet("font-size:18px; font-weight:600;")
            self._status = QLabel("正在初始化视觉模型……")
            self._queue = QLabel("队列：frames=0 events=0")
            self._help = QLabel(
                "相机画面将自动连续判断左右脚状态    Q：退出\n"
                "注意：这是视觉参考状态，不代表光栅触地时刻。"
            )

            layout = QVBoxLayout(self)
            layout.addWidget(self._preview, 1)
            layout.addWidget(self._result)
            layout.addWidget(self._status)
            layout.addWidget(self._queue)
            layout.addWidget(self._help)

            quit_shortcut = QShortcut(QKeySequence("Q"), self)
            quit_shortcut.activated.connect(self.close)
            self._quit_shortcut = quit_shortcut

            self._bridge = _Bridge(self)
            self._bridge.decision.connect(self._on_decision)
            self._bridge.pose.connect(self._on_pose_sample)
            self._bridge.status.connect(self._on_service_status)

            self._service = FootVisionService(
                VisionConfig(
                    inference_interval_ms=80,
                    min_confidence=0.65,
                ),
                Path(args.model).expanduser(),
            )
            self._service.decision_ready.connect(self._bridge.decision.emit)
            self._service.pose_ready.connect(self._bridge.pose.emit)
            self._service.status_changed.connect(self._bridge.status.emit)
            self._service.start()

            self._queue_timer = QTimer(self)
            self._queue_timer.timeout.connect(self._refresh_queue)
            self._queue_timer.start(100)

            self._event_timer = QTimer(self)
            self._event_timer.timeout.connect(self._submit_event)

            try:
                self._start_camera()
                self._event_timer.start(args.interval_ms)
            except Exception as exc:
                self._status.setText(f"相机不可用：{exc}")

        def _start_camera(self) -> None:
            if args.camera == "tinyse":
                capture = TinySeCameraCapture()
            else:
                capture = CameraCapture()
                if not capture.open(CAMERA_INDEX):
                    raise RuntimeError("无法打开 Logitech 相机")

            thread = QThread(self)
            capture.moveToThread(thread)
            capture.analysis_frame_ready.connect(self._service.submit_frame)
            capture.analysis_frame_ready.connect(self._on_analysis_frame)
            capture.stats_updated.connect(self._on_camera_stats)
            capture.error.connect(self._on_camera_error)
            thread.started.connect(capture.start)
            thread.finished.connect(capture.deleteLater)

            self._capture = capture
            self._camera_thread = thread
            thread.start()

        @Slot()
        def _submit_event(self) -> None:
            self._event_id += 1
            event_time_s = time.perf_counter()
            self._service.submit_touch_event(self._event_id, event_time_s)

        @Slot(object)
        def _on_decision(self, decision) -> None:
            decided_at_s = decision.decided_at_s or time.perf_counter()
            latency_ms = (decided_at_s - decision.event_time_s) * 1000.0
            display_label = decision.label.value.upper()
            candidate_label = decision.candidate_label
            if decision.label.value == "unknown" and candidate_label is not None:
                display_label += f"（候选 {candidate_label.value.upper()}）"
            self._result.setText(
                f"事件 {decision.event_id}：{display_label}  "
                f"置信度 {decision.confidence:.3f}  延迟 {latency_ms:.1f} ms"
            )
            self._status.setText(f"原因：{decision.reason}")
            self._csv.writerow(
                {
                    "event_id": decision.event_id,
                    "event_time_s": f"{decision.event_time_s:.9f}",
                    "decided_at_s": f"{decided_at_s:.9f}",
                    "label": decision.label.value,
                    "confidence": f"{decision.confidence:.6f}",
                    "reason": decision.reason,
                    "candidate_label": (
                        candidate_label.value if candidate_label is not None else ""
                    ),
                    "latency_ms": f"{latency_ms:.3f}",
                }
            )
            self._csv_file.flush()

        @Slot(str)
        def _on_service_status(self, status: str) -> None:
            self._status.setText(f"视觉服务：{status}")

        @Slot(float, float)
        def _on_camera_stats(self, fps: float, _record_seconds: float) -> None:
            self.setWindowTitle(
                f"Iron_Jump 左右脚视觉实时状态 — {args.camera} — {fps:.1f} FPS"
            )

        @Slot(str)
        def _on_camera_error(self, message: str) -> None:
            self._status.setText(f"相机错误：{message}")

        @Slot(object)
        def _on_pose_sample(self, sample) -> None:
            self._latest_pose = sample

        @Slot(object, float)
        def _on_analysis_frame(self, frame, captured_at_s: float) -> None:
            pose = self._latest_pose
            if pose is not None and abs(captured_at_s - pose.timestamp_s) > 0.30:
                pose = None
            annotated = draw_pose_overlay(frame.copy(), pose)
            rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
            height, width = rgb.shape[:2]
            target = self._preview.size()
            scale = min(target.width() / width, target.height() / height)
            display_width = max(1, int(width * scale))
            display_height = max(1, int(height * scale))
            if (display_width, display_height) != (width, height):
                rgb = cv2.resize(
                    rgb,
                    (display_width, display_height),
                    interpolation=cv2.INTER_AREA,
                )
            image = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()
            self._preview.setPixmap(QPixmap.fromImage(image))

        @Slot()
        def _refresh_queue(self) -> None:
            depth = self._service.queue_depth
            self._queue.setText(
                f"队列：frames={depth['frames']} events={depth['events']}"
            )

        def closeEvent(self, event) -> None:
            if self._closing:
                event.accept()
                return
            self._closing = True
            self._queue_timer.stop()
            self._event_timer.stop()
            capture = self._capture
            thread = self._camera_thread
            if capture is not None:
                capture.stop()
            if thread is not None:
                thread.quit()
                thread.wait(2000)
            self._service.stop()
            self._csv_file.close()
            event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    window = DiagnosticWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
