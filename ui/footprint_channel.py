"""Shared footprint-channel visualization widgets."""

from __future__ import annotations

import os
from bisect import bisect_left

from qtpy.QtCore import QLineF, QRectF, Qt, QTimer
from qtpy.QtGui import QColor, QPainter, QPixmap
from qtpy.QtWidgets import QFrame, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from dayu_widgets.push_button import MPushButton

from path_utils import get_base_dir


_LED_COUNT = 96
_LED_SPACING_CM = 1.04
_DEFAULT_FOOT_LENGTH_CM = 28.0
_MAX_REASONABLE_FOOT_LENGTH_CM = 40.0

_SOURCE_IN = getattr(QPainter, "CompositionMode_SourceIn", None)
if _SOURCE_IN is None:
    _SOURCE_IN = QPainter.CompositionMode.CompositionMode_SourceIn

REPLAY_QSS = """
QWidget#FootprintReplayPanel {
    background: transparent;
    color: #dce5f0;
}
QPushButton#ReplayButton {
    min-width: 78px;
    min-height: 30px;
    border: 1px solid #354151;
    border-radius: 6px;
    background-color: #1a2230;
    color: #dce5f0;
    padding: 0 14px;
}
QPushButton#ReplayButton:hover {
    background-color: #243043;
    border-color: #46566a;
}
QPushButton#ReplayButton:pressed {
    background-color: #111923;
}
QSlider#ReplaySlider::groove:horizontal {
    height: 6px;
    border-radius: 3px;
    background-color: #273445;
}
QSlider#ReplaySlider::sub-page:horizontal {
    border-radius: 3px;
    background-color: #ff7a00;
}
QSlider#ReplaySlider::add-page:horizontal {
    border-radius: 3px;
    background-color: #273445;
}
QSlider#ReplaySlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border: 2px solid #ff9b3d;
    border-radius: 8px;
    background-color: #f5f7fb;
}
QLabel#ReplayTimeLabel {
    min-width: 64px;
    color: #9ca8b8;
    background: transparent;
}
"""


class FootprintChannelWidget(QFrame):
    """Render canonical footprint frames between two LED rails."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._contact_bits = [0] * _LED_COUNT
        self._positions_m = None
        self._feet: list[dict] = []
        self.history: list[dict] = []
        self.valid_bits = [1] * _LED_COUNT
        self._direction = "Interface side"
        self._left_foot = self._load_pixmap("left_foot.png")
        self._right_foot = self._load_pixmap("right_foot.png")
        self.setMinimumSize(260, 420)
        self.setStyleSheet(
            "FootprintChannelWidget {"
            "  background-color: rgba(20, 20, 24, 0.9);"
            "  border: 1px solid rgba(90, 90, 95, 0.7);"
            "  border-radius: 8px;"
            "}"
        )

    def _load_pixmap(self, name: str) -> QPixmap:
        path = os.path.join(get_base_dir(), "ui", "assets", name)
        return QPixmap(path)

    def clear(self):
        self._contact_bits = [0] * _LED_COUNT
        self._feet = []
        self.history = []
        self.valid_bits = [1] * _LED_COUNT
        self._positions_m = None
        self.update()

    def set_direction(self, direction: str | None):
        self._direction = "Opposite side" if direction == "Opposite side" else "Interface side"
        self.update()

    def render_state(self, frame):
        if hasattr(frame, "to_dict"):
            frame = frame.to_dict()

        bits = [1 if int(bit) else 0 for bit in frame.get("contact_bits", [])]
        if len(bits) < _LED_COUNT:
            bits.extend([0] * (_LED_COUNT - len(bits)))

        self._contact_bits = bits
        self.valid_bits = list(frame.get("valid_bits", [1] * len(bits)))
        self._positions_m = frame.get("positions_m")
        self._feet = []
        for foot in frame.get("feet", []):
            foot_state = dict(foot)
            if foot_state.get("status") != "confirmed":
                continue
            self._feet.append(
                {
                    key: value
                    for key, value in foot_state.items()
                    if key != "opacity"
                }
            )
        self.update()

    def _y_for_index(self, index: float, top: float, height: float) -> float:
        clamped = min(max(float(index), 0.0), float(len(self._contact_bits) - 1))
        ratio = clamped / float(len(self._contact_bits) - 1)
        if self._positions_m and len(self._positions_m) == len(self._contact_bits):
            i = int(clamped)
            j = min(i + 1, len(self._positions_m) - 1)
            position = self._positions_m[i] + (clamped - i) * (self._positions_m[j] - self._positions_m[i])
            ratio = (position - self._positions_m[0]) / (self._positions_m[-1] - self._positions_m[0])
        if self._direction == "Opposite side":
            ratio = 1.0 - ratio
        return top + ratio * height

    def _rail_marker_rects(
        self, rail_x: float, top: float, height: float
    ) -> list[QRectF]:
        spacing = height / float(len(self._contact_bits) - 1)
        marker_height = min(6.0, max(2.0, spacing * 0.78))
        return [
            QRectF(
                rail_x - 3.0,
                self._y_for_index(index, top, height) - marker_height / 2.0,
                6.0,
                marker_height,
            )
            for index in range(len(self._contact_bits))
        ]

    def lane_rect(self):
        rect = self.rect().adjusted(14, 14, -14, -14)
        return QRectF(rect.left() + 34, rect.top() + 20, rect.width() - 69, rect.height() - 40)

    def _foot_size_for_lane(
        self, lane_width: int, lane_height: int, length_cm: float | None
    ) -> tuple[int, int]:
        length = self._resolved_foot_length_cm(length_cm)
        channel_cm = float(len(self._contact_bits) - 1) * _LED_SPACING_CM
        if self._positions_m:
            channel_cm = (self._positions_m[-1] - self._positions_m[0]) * 100
        foot_h = max(8 if len(self._contact_bits) > 96 else 48, int((length / channel_cm) * float(lane_height)))
        foot_w = max(6 if len(self._contact_bits) > 96 else 30, int(foot_h / 1.62))
        if lane_width > 0:
            foot_w = min(foot_w, max(30, int(lane_width * 0.32)))
        return foot_w, foot_h

    def _resolved_foot_length_cm(self, length_cm: float | None) -> float:
        try:
            length = float(length_cm)
        except (TypeError, ValueError):
            return _DEFAULT_FOOT_LENGTH_CM
        if length <= 0 or length > _MAX_REASONABLE_FOOT_LENGTH_CM:
            return _DEFAULT_FOOT_LENGTH_CM
        return length

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(14, 14, -14, -14)
        rail_left_x = rect.left() + 12
        rail_right_x = rect.right() - 12
        lane = self.lane_rect()
        lane_left, lane_right = int(lane.left()), int(lane.right())
        top, height = int(lane.top()), int(lane.height())

        integrated = bool(self.property("integrated"))
        painter.setPen(Qt.NoPen if integrated else QColor(70, 70, 76))
        painter.setBrush(QColor(255, 255, 255, 5) if integrated else QColor(28, 28, 32))
        painter.drawRoundedRect(lane_left, top, lane_right - lane_left, height, 8, 8)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(42, 42, 48))
        painter.drawRoundedRect(
            QRectF(rail_left_x - 3.0, top - 2.0, 6.0, height + 4.0),
            3.0,
            3.0,
        )
        painter.drawRoundedRect(
            QRectF(rail_right_x - 3.0, top - 2.0, 6.0, height + 4.0),
            3.0,
            3.0,
        )

        left_markers = self._rail_marker_rects(rail_left_x, top, height)
        right_markers = self._rail_marker_rects(rail_right_x, top, height)
        for idx, active in enumerate(self._contact_bits):
            y = self._y_for_index(idx, top, height)
            valid = idx < len(self.valid_bits) and self.valid_bits[idx]
            color = QColor("#ddaa57") if not valid else QColor(70, 220, 125) if active else QColor(70, 70, 76)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(left_markers[idx], 2.0, 2.0)
            painter.drawRoundedRect(right_markers[idx], 2.0, 2.0)
            if active and valid:
                painter.setPen(QColor(70, 220, 125, 60))
                painter.drawLine(
                    QLineF(float(lane_left), y, float(lane_right), y)
                )

        painter.save()
        if self._positions_m:
            painter.setClipRect(lane)
        painter.setOpacity(.32)
        for foot in self.history:
            self._paint_foot(painter, foot, lane_left, lane_right, top, height)
        painter.setOpacity(1)
        if len(self.valid_bits) == len(self._contact_bits) and any(self.valid_bits):
            for foot in self._feet:
                centre = foot.get("centroid_cm")
                length = foot.get("length_cm")
                if centre is None or length is None:
                    continue
                positions = self._positions_m or [i * .0104 for i in range(len(self._contact_bits))]
                overlaps_unknown = any(not valid and abs(position * 100 - centre) <= length / 2 + 1.04
                                       for position, valid in zip(positions, self.valid_bits))
                if not overlaps_unknown:
                    self._paint_foot(painter, foot, lane_left, lane_right, top, height)
        painter.restore()
        painter.end()

    def _paint_foot(
        self,
        painter: QPainter,
        foot: dict,
        lane_left: int,
        lane_right: int,
        top: int,
        height: int,
    ):
        centroid_cm = foot.get("centroid_cm")
        if centroid_cm is None:
            return

        index = float(centroid_cm) / _LED_SPACING_CM
        if self._positions_m:
            pos = float(centroid_cm) / 100
            j = min(max(bisect_left(self._positions_m, pos), 1), len(self._positions_m) - 1)
            index = j - 1 + (pos - self._positions_m[j - 1]) / (self._positions_m[j] - self._positions_m[j - 1])
        y = self._y_for_index(index, top, height)
        side = foot.get("side", "unknown")
        status = foot.get("status", "confirmed")
        alpha = 255 if status == "confirmed" else 130
        color = (
            QColor(82, 170, 255, alpha)
            if side == "right"
            else QColor(82, 220, 130, alpha)
        )
        pixmap = self._right_foot if side == "right" else self._left_foot
        foot_w, foot_h = self._foot_size_for_lane(
            lane_width=lane_right - lane_left,
            lane_height=height,
            length_cm=foot.get("length_cm"),
        )
        x_center = lane_left + (lane_right - lane_left) * (
            0.64 if side == "right" else (0.36 if side == "left" else 0.5)
        )
        target_x = int(x_center - foot_w / 2)
        target_y = int(y - foot_h / 2)

        if pixmap.isNull() or side == "unknown":
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(target_x, target_y, foot_w, foot_h)
            return

        tinted = QPixmap(pixmap.size())
        tinted.fill(Qt.transparent)
        tint_painter = QPainter(tinted)
        tint_painter.drawPixmap(0, 0, pixmap)
        tint_painter.setCompositionMode(_SOURCE_IN)
        tint_painter.fillRect(tinted.rect(), color)
        tint_painter.end()
        painter.drawPixmap(target_x, target_y, foot_w, foot_h, tinted)


class FootprintReplayPanel(QWidget):
    """Replay a canonical footprint timeline through the shared channel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FootprintReplayPanel")
        self.setStyleSheet(REPLAY_QSS)
        self._timeline: list = []
        self._index = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._channel = FootprintChannelWidget()
        layout.addWidget(self._channel, 1)
        from ui.ground_track import GroundTrackPanel
        self.ground_track = GroundTrackPanel()
        self.ground_track.hide()
        layout.addWidget(self.ground_track, 1)
        self.is_ground = False

        controls = QHBoxLayout()
        self._btn_play = MPushButton("Play")
        self._btn_play.setObjectName("ReplayButton")
        self._btn_play.setStyleSheet(REPLAY_QSS)
        self._btn_play.clicked.connect(self._toggle_playback)
        controls.addWidget(self._btn_play)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setObjectName("ReplaySlider")
        self._slider.valueChanged.connect(self._on_slider_changed)
        controls.addWidget(self._slider, 1)

        self._time_label = QLabel("0.000 s")
        self._time_label.setObjectName("ReplayTimeLabel")
        controls.addWidget(self._time_label)
        layout.addLayout(controls)

    def set_direction(self, direction: str | None):
        self._channel.set_direction(direction)

    def set_ground_context(self, device=None, summary=None):
        self.is_ground = summary is not None
        self._channel.setVisible(not self.is_ground)
        self.ground_track.setVisible(self.is_ground)
        self.ground_track.detail.setVisible(self.is_ground)
        self.ground_track.clear()
        if self.is_ground:
            self.ground_track.set_layout(device)
            self.ground_track.set_summary(summary)

    def set_timeline(self, timeline):
        self._timer.stop()
        self._btn_play.setText("Play")
        self._timeline = [
            frame.to_dict() if hasattr(frame, "to_dict") else frame
            for frame in timeline
        ]
        self._index = 0
        self._slider.setMaximum(max(len(self._timeline) - 1, 0))
        self._slider.setValue(0)

        if self._timeline:
            self._render_index(0)
        else:
            self._channel.clear()
            self._time_label.setText("No replay data")

    def _toggle_playback(self):
        if not self._timeline:
            return
        if self._timer.isActive():
            self._timer.stop()
            self._btn_play.setText("Play")
        else:
            self._timer.start(self._next_interval())
            self._btn_play.setText("Pause")

    def _next_interval(self):
        if self.is_ground and self._index + 1 < len(self._timeline):
            current = self._timeline[self._index].get("timestamp_s", 0)
            following = self._timeline[self._index + 1].get("timestamp_s", current)
            return max(1, round((following - current) * 1000))
        return 40

    def _advance(self):
        if not self._timeline:
            self._timer.stop()
            return

        next_index = self._index + 1
        if next_index >= len(self._timeline):
            self._timer.stop()
            self._btn_play.setText("Play")
            return
        self._slider.setValue(next_index)

    def _on_slider_changed(self, value: int):
        if self._timeline:
            self._render_index(value)
            if self.is_ground and self._timer.isActive():
                self._timer.start(self._next_interval())

    def _render_index(self, index: int):
        self._index = max(0, min(index, len(self._timeline) - 1))
        frame = self._timeline[self._index]
        self._channel.render_state(frame)
        if self.is_ground:
            self.ground_track.render_state(frame)
        self._time_label.setText(f"{frame.get('timestamp_s', 0.0):.3f} s")
