"""Mac-only live validator for MediaPipe lower-body L/R identity stability."""

from __future__ import annotations

import argparse
import importlib.metadata
import sys
import threading
import time
from collections import deque
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SUPPORTED_MAC_MEDIAPIPE_VERSION = "0.10.35"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate MediaPipe anatomical left/right leg identity on a Mac camera. "
            "No gait analysis, CSV, or video recording is performed."
        )
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Path to pose_landmarker_full.task",
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=_positive_int, default=1280)
    parser.add_argument("--height", type=_positive_int, default=720)
    parser.add_argument("--camera-fps", type=_positive_int, default=30)
    parser.add_argument(
        "--inference-interval-ms",
        type=_positive_int,
        default=50,
        help="Minimum interval between Pose inferences (default: 50 ms)",
    )
    return parser


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def stream_fps(timestamps: deque[float]) -> float:
    if len(timestamps) < 2:
        return 0.0
    elapsed = timestamps[-1] - timestamps[0]
    return (len(timestamps) - 1) / elapsed if elapsed > 0 else 0.0


def validate_macos_mediapipe_version(version_text: str) -> None:
    if version_text != SUPPORTED_MAC_MEDIAPIPE_VERSION:
        raise RuntimeError(
            "Mac验证工具要求mediapipe=="
            f"{SUPPORTED_MAC_MEDIAPIPE_VERSION}，当前为{version_text}。"
            "请执行：python -m pip install --force-reinstall "
            f"mediapipe=={SUPPORTED_MAC_MEDIAPIPE_VERSION}"
        )


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


def run(args: argparse.Namespace) -> int:
    import cv2
    from qtpy.QtCore import QObject, QTimer, Signal, Slot, Qt
    from qtpy.QtGui import QImage, QKeySequence, QPixmap, QShortcut
    from qtpy.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from vision.leg_identity import (
        LegIdentityAnalyzer,
        LegIdentityResult,
        LegIdentityState,
    )
    from vision.mediapipe_pose import MediaPipePoseAdapter
    from vision.pose_overlay import build_pose_overlay, draw_pose_overlay

    class _Bridge(QObject):
        frame_ready = Signal(object, object, object, float, float)
        status_changed = Signal(str)
        finished = Signal()

    class ValidatorWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Mac MediaPipe 左右脚身份验证")
            self.resize(1280, 860)
            self._closing = False
            self._stop = threading.Event()
            self._worker: threading.Thread | None = None

            self._preview = QLabel("正在打开Mac相机和MediaPipe模型……")
            self._preview.setAlignment(Qt.AlignCenter)
            self._preview.setMinimumSize(960, 540)
            self._preview.setStyleSheet("background:#101216; color:#aaa;")
            self._state = QLabel("状态：初始化")
            self._state.setStyleSheet("font-size:20px; font-weight:700;")
            self._details = QLabel(
                "只验证MediaPipe解剖学左右脚身份；不判断触地，不计算步态参数。"
            )
            self._help = QLabel(
                "建议画面包含骨盆至双脚。蓝色=L，橙色=R，灰色点=低质量。  Q：退出"
            )

            layout = QVBoxLayout(self)
            layout.addWidget(self._preview, 1)
            layout.addWidget(self._state)
            layout.addWidget(self._details)
            layout.addWidget(self._help)

            self._quit_shortcut = QShortcut(QKeySequence("Q"), self)
            self._quit_shortcut.activated.connect(self.close)

            self._bridge = _Bridge(self)
            self._bridge.frame_ready.connect(self._on_frame)
            self._bridge.status_changed.connect(self._on_status)
            self._bridge.finished.connect(self._on_finished)

            QTimer.singleShot(0, self._start_capture)

        @Slot()
        def _start_capture(self) -> None:
            if self._closing:
                return

            try:
                validate_macos_mediapipe_version(
                    importlib.metadata.version("mediapipe")
                )
                self._capture = _open_mac_camera(
                    cv2,
                    args.camera_index,
                    args.width,
                    args.height,
                    args.camera_fps,
                )
            except Exception as exc:
                self._capture = None
                self._on_status(f"error:{exc}")
                return

            self._worker = threading.Thread(
                target=self._capture_loop,
                name="MacMediaPipeValidator",
                daemon=True,
            )
            self._worker.start()

        def _capture_loop(self) -> None:
            adapter = MediaPipePoseAdapter(Path(args.model).expanduser())
            analyzer = LegIdentityAnalyzer()
            capture = self._capture
            try:
                adapter.open()
                self._bridge.status_changed.emit("ready")
                camera_times: deque[float] = deque(maxlen=90)
                pose_times: deque[float] = deque(maxlen=60)
                last_inference_s = float("-inf")
                last_timestamp_ms = -1
                latest_pose = None
                latest_identity = analyzer.update(None)
                interval_s = args.inference_interval_ms / 1000.0

                while not self._stop.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        raise RuntimeError("无法读取Mac相机画面")
                    now_s = time.perf_counter()
                    camera_times.append(now_s)
                    if now_s - last_inference_s >= interval_s:
                        timestamp_ms = max(last_timestamp_ms + 1, int(now_s * 1000.0))
                        latest_pose = adapter.infer_bgr(frame, timestamp_ms)
                        latest_identity = analyzer.update(latest_pose)
                        last_timestamp_ms = timestamp_ms
                        last_inference_s = now_s
                        pose_times.append(time.perf_counter())
                    self._bridge.frame_ready.emit(
                        frame,
                        latest_pose,
                        latest_identity,
                        stream_fps(camera_times),
                        stream_fps(pose_times),
                    )
            except Exception as exc:
                self._bridge.status_changed.emit(f"error:{exc}")
            finally:
                if capture is not None:
                    capture.release()
                    self._capture = None
                adapter.close()
                self._bridge.finished.emit()

        @Slot(object, object, object, float, float)
        def _on_frame(
            self,
            frame,
            pose,
            identity: LegIdentityResult,
            camera_fps: float,
            pose_fps: float,
        ) -> None:
            annotated = draw_pose_overlay(frame.copy(), pose, min_quality=0.60)
            if pose is not None:
                _draw_landmark_names(
                    cv2,
                    annotated,
                    build_pose_overlay(
                        pose,
                        annotated.shape[1],
                        annotated.shape[0],
                        min_quality=0.60,
                    ),
                )
            _draw_identity_status(cv2, annotated, identity, camera_fps, pose_fps)
            self._set_preview(annotated)
            state_text = identity.state.value.upper()
            self._state.setText(f"身份状态：{state_text}")
            self._state.setStyleSheet(
                "font-size:20px; font-weight:700; color:"
                + {
                    LegIdentityState.STABLE: "#27ae60",
                    LegIdentityState.AMBIGUOUS: "#e67e22",
                    LegIdentityState.UNAVAILABLE: "#95a5a6",
                }[identity.state]
                + ";"
            )
            cost_text = ""
            if identity.original_cost is not None:
                cost_text = (
                    f" | original={identity.original_cost:.3f} "
                    f"swapped={identity.swapped_cost:.3f} "
                    f"margin={identity.assignment_margin:.3f}"
                )
            self._details.setText(
                f"原因：{identity.reason} | L质量={identity.left_quality:.2f} "
                f"R质量={identity.right_quality:.2f}{cost_text} | "
                f"Camera={camera_fps:.1f} FPS Pose={pose_fps:.1f} FPS"
            )

        @Slot(str)
        def _on_status(self, status: str) -> None:
            if status == "ready":
                return
            if status.startswith("error:"):
                self._state.setText("状态：ERROR")
                self._details.setText(status.removeprefix("error:"))
            else:
                self._details.setText(status)

        @Slot()
        def _on_finished(self) -> None:
            if not self._closing:
                self._details.setText(self._details.text() + " | 处理线程已停止")

        def _set_preview(self, frame) -> None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width = rgb.shape[:2]
            target = self._preview.size()
            scale = min(target.width() / width, target.height() / height)
            size = max(1, round(width * scale)), max(1, round(height * scale))
            if size != (width, height):
                rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
            image = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()
            self._preview.setPixmap(QPixmap.fromImage(image))

        def closeEvent(self, event) -> None:
            if self._closing:
                event.accept()
                return
            self._closing = True
            self._stop.set()
            worker = self._worker
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=2.0)
            event.accept()

    app = QApplication.instance() or QApplication(sys.argv)
    window = ValidatorWindow()
    window.show()
    return app.exec()


def _open_mac_camera(cv2, index: int, width: int, height: int, fps: int):
    backend = getattr(cv2, "CAP_AVFOUNDATION", None)
    capture = cv2.VideoCapture(index, backend) if backend is not None else None
    if capture is None or not capture.isOpened():
        if capture is not None:
            capture.release()
        capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(
            f"无法打开相机索引 {index}；请在macOS“系统设置 → 隐私与安全性 → "
            "相机”中允许当前终端使用相机，或尝试其他索引"
        )
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_FPS, fps)
    return capture


def _draw_landmark_names(cv2, frame, overlay: dict) -> None:
    abbreviations = {
        "hip": "HIP",
        "knee": "KNEE",
        "ankle": "ANKLE",
        "heel": "HEEL",
        "foot_index": "TOE",
    }
    colors = {"left": (255, 120, 30), "right": (20, 165, 255)}
    for name, node in overlay["nodes"].items():
        side = node["side"]
        suffix = name.removeprefix(f"{side}_")
        label = f"{side[0].upper()} {abbreviations[suffix]} {node['quality']:.2f}"
        x, y = node["point"]
        cv2.putText(
            frame,
            label,
            (x + 8, y + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            colors[side] if node["valid"] else (120, 120, 120),
            1,
            cv2.LINE_AA,
        )


def _draw_identity_status(cv2, frame, identity, camera_fps: float, pose_fps: float) -> None:
    colors = {
        "stable": (45, 190, 85),
        "ambiguous": (20, 150, 245),
        "unavailable": (150, 150, 150),
    }
    color = colors[identity.state.value]
    cv2.rectangle(frame, (12, 12), (690, 80), (18, 20, 24), -1)
    cv2.putText(
        frame,
        f"IDENTITY: {identity.state.value.upper()}  {identity.reason}",
        (24, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        color,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"L quality {identity.left_quality:.2f} | R quality {identity.right_quality:.2f} "
        f"| Camera {camera_fps:.1f} | Pose {pose_fps:.1f} FPS",
        (24, 67),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )


if __name__ == "__main__":
    raise SystemExit(main())
