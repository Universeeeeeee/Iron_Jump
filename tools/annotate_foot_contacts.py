"""QtPy ground-truth tool for a saved Iron_Jump vision session."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path



ANNOTATION_PRE_MS = 500
ANNOTATION_POST_MS = 300


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Annotate anatomical contact foot")
    parser.add_argument("session", help="Path to a vision_session directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(Path(args.session))


def run(session_root: Path) -> int:
    import cv2
    from qtpy.QtCore import QTimer, Qt
    from qtpy.QtGui import QImage, QKeySequence, QPixmap, QShortcut
    from qtpy.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QVBoxLayout,
        QWidget,
    )

    from vision.annotations import (
        first_unannotated_index,
        is_benchmark_event,
        load_annotations,
        save_annotations,
        set_annotation,
    )
    from vision.session import load_csv, load_session, normalize_label
    from vision.video_index import MjpgIndexedVideo

    metadata, paths = load_session(session_root)
    events = [
        event for event in load_csv(paths.contact_events) if is_benchmark_event(event)
    ]
    if not events:
        raise RuntimeError("session contains no benchmark contact events")
    annotations = load_annotations(paths.annotations)

    class AnnotationWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle(f"Iron_Jump 足接触标注 — {metadata['session_id']}")
            self.resize(1280, 840)
            self._events = events
            self._annotations = annotations
            self._current = first_unannotated_index(events, annotations)
            self._frame_positions: list[int] = []
            self._frame_cursor = 0
            self._playing = True
            self._show_prediction = False
            self._shortcuts = []
            self._video = None
            self._video_error = ""
            try:
                self._video = MjpgIndexedVideo(paths.video, paths.video_index)
            except Exception as exc:
                self._video_error = str(exc)

            self._preview = QLabel("正在读取事件视频……")
            self._preview.setAlignment(Qt.AlignCenter)
            self._preview.setMinimumSize(960, 540)
            self._preview.setStyleSheet("background:#111; color:#aaa;")
            self._event_text = QLabel()
            self._event_text.setStyleSheet("font-size:18px; font-weight:600;")
            self._status = QLabel()
            self._scenario = QLineEdit(str(metadata.get("scenario") or "normal"))
            self._note = QLineEdit()

            fields = QHBoxLayout()
            fields.addWidget(QLabel("scenario"))
            fields.addWidget(self._scenario)
            fields.addWidget(QLabel("note"))
            fields.addWidget(self._note, 2)

            help_text = QLabel(
                "L Left / R Right / S Skip    ←/A 上一个    →/D 下一个    "
                "Space 播放/暂停    V 标注后显示/隐藏算法结果"
            )
            layout = QVBoxLayout(self)
            layout.addWidget(self._preview, 1)
            layout.addWidget(self._event_text)
            layout.addWidget(self._status)
            layout.addLayout(fields)
            layout.addWidget(help_text)

            for key, callback in (
                ("L", lambda: self._annotate("Left")),
                ("R", lambda: self._annotate("Right")),
                ("S", lambda: self._annotate("Skip")),
                ("Left", self._previous),
                ("A", self._previous),
                ("Right", self._next),
                ("D", self._next),
                ("Space", self._toggle_play),
                ("V", self._toggle_prediction),
            ):
                shortcut = QShortcut(QKeySequence(key), self)
                shortcut.activated.connect(callback)
                self._shortcuts.append(shortcut)

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._advance_frame)
            self._timer.start(15)
            self._load_event()

        def _event(self):
            return self._events[self._current]

        def _load_event(self) -> None:
            event = self._event()
            event_id = str(event["event_id"])
            saved = self._annotations.get(event_id, {})
            self._scenario.setText(
                saved.get("scenario") or event.get("scenario") or metadata.get("scenario") or "normal"
            )
            self._note.setText(saved.get("note", ""))
            sample_time = _float_or_none(event.get("camera_sample_timestamp"))
            self._frame_positions = []
            if self._video is not None and sample_time is not None:
                start = sample_time - ANNOTATION_PRE_MS / 1000.0
                end = sample_time + ANNOTATION_POST_MS / 1000.0
                self._frame_positions = [
                    index for index, _frame in self._video.iter_time_window(start, end)
                ]
            self._frame_cursor = 0
            self._playing = True
            self._show_prediction = False
            truth = normalize_label(saved.get("ground_truth", ""), allow_skip=True)
            truth_text = truth or "未标注"
            self._event_text.setText(
                f"Event {event_id}  ({self._current + 1}/{len(self._events)})  "
                f"Ground Truth: {truth_text}"
            )
            recording = metadata.get("recording", {})
            warning = ""
            if recording.get("status") in {"partial", "failed"}:
                warning = f"录像状态：{recording.get('status')}；缺失画面可按 S 跳过。 "
            if not self._frame_positions:
                detail = self._video_error or "事件窗口没有可用视频帧"
                self._preview.setText(detail)
            self._status.setText(warning + "播放中" if self._playing else warning + "已暂停")
            self._render_current()

        def _render_current(self) -> None:
            if self._video is None or not self._frame_positions:
                return
            index = self._frame_positions[min(self._frame_cursor, len(self._frame_positions) - 1)]
            frame = self._video.read(index)
            if frame is None:
                self._preview.setText("JPEG 帧解码失败；可按 S 跳过")
                return
            frame_meta = self._video.frames[index]
            event = self._event()
            contact_sample_s = _float_or_none(event.get("camera_sample_timestamp"))
            delta_ms = (
                (frame_meta.sample_time_s - contact_sample_s) * 1000.0
                if contact_sample_s is not None
                else 0.0
            )
            cv2.putText(
                frame,
                f"EVENT {event['event_id']}  t={frame_meta.sample_time_s:.3f}s  contact {delta_ms:+.0f}ms",
                (20, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
                cv2.LINE_AA,
            )
            if abs(delta_ms) <= 8.0:
                cv2.putText(
                    frame,
                    "CONTACT",
                    (20, 78),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
            if self._show_prediction:
                cv2.putText(
                    frame,
                    "prediction="
                    f"{event.get('visual_label', '')} raw={event.get('visual_raw_label', '')} "
                    f"score={event.get('visual_raw_score', '')}",
                    (20, frame.shape[0] - 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (0, 220, 255),
                    2,
                    cv2.LINE_AA,
                )
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = QImage(
                rgb.data,
                rgb.shape[1],
                rgb.shape[0],
                rgb.strides[0],
                QImage.Format_RGB888,
            ).copy()
            pixmap = QPixmap.fromImage(image).scaled(
                self._preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self._preview.setPixmap(pixmap)

        def _advance_frame(self) -> None:
            if not self._playing or not self._frame_positions:
                return
            self._frame_cursor = (self._frame_cursor + 1) % len(self._frame_positions)
            self._render_current()

        def _annotate(self, label: str) -> None:
            event_id = str(self._event()["event_id"])
            set_annotation(
                self._annotations,
                event_id,
                label,
                scenario=self._scenario.text().strip() or "normal",
                note=self._note.text().strip(),
            )
            save_annotations(paths.annotations, self._annotations)
            if self._current < len(self._events) - 1:
                self._current += 1
            self._load_event()

        def _previous(self) -> None:
            self._current = max(0, self._current - 1)
            self._load_event()

        def _next(self) -> None:
            self._current = min(len(self._events) - 1, self._current + 1)
            self._load_event()

        def _toggle_play(self) -> None:
            self._playing = not self._playing
            self._status.setText("播放中" if self._playing else "已暂停")

        def _toggle_prediction(self) -> None:
            event_id = str(self._event()["event_id"])
            truth = normalize_label(
                self._annotations.get(event_id, {}).get("ground_truth", ""),
                allow_skip=True,
            )
            if truth not in {"Left", "Right", "Skip"}:
                self._status.setText("请先完成当前事件的人工标注，再查看算法结果。")
                return
            self._show_prediction = not self._show_prediction
            self._render_current()

    app = QApplication.instance() or QApplication(sys.argv)
    window = AnnotationWindow()
    window.show()
    return app.exec()


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
