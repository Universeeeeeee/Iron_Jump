"""Continuous overground overview and selectable, physically indexed detail."""
from bisect import bisect_right

from qtpy.QtCore import QRectF, Qt, Signal
from qtpy.QtGui import QColor, QPainter
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.footprint_channel import FootprintChannelWidget


class GroundChannelWidget(FootprintChannelWidget):
    segment_selected = Signal(int)

    def __init__(self, parent=None, *, overview=True):
        super().__init__(parent)
        self.setProperty("integrated", True)
        self.setStyleSheet("FootprintChannelWidget { background: transparent; border: none; }")
        self.overview = overview
        self.selected_segment = 0
        self.setMinimumSize(220 if overview else 170, 260)
        self.setFocusPolicy(Qt.StrongFocus if overview else Qt.NoFocus)
        self.setAccessibleName("全程跑道；上下方向键选择设备段" if overview else "所选段光束详情")
        self.clear()

    def clear(self):
        super().clear()
        self._contact_bits = []
        self.valid_bits = []
        self.selected_segment = 0

    def render_state(self, frame):
        super().render_state(frame)
        if len(self.valid_bits) != len(self._contact_bits) or not all(self.valid_bits):
            self._feet = []
        self.selected_segment = min(self.selected_segment, max(0, len(self._contact_bits) // 96 - 1))

    def select_segment(self, index):
        count = len(self._contact_bits) // 96
        if count:
            self.selected_segment = min(max(0, index), count - 1)
            self.segment_selected.emit(self.selected_segment)
            self.update()

    def mousePressEvent(self, event):
        if self.overview and self._positions_m:
            rect = self.lane_rect()
            ratio = min(1, max(0, (event.pos().y() - rect.top()) / rect.height()))
            position = self._positions_m[0] + ratio * (self._positions_m[-1] - self._positions_m[0])
            self.select_segment(bisect_right(self._positions_m[::96], position) - 1)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self.overview and event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.select_segment(self.selected_segment + (1 if event.key() == Qt.Key_Down else -1))
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        if not self._positions_m or not self._contact_bits:
            painter = QPainter(self)
            painter.setPen(QColor("#9aa6b7"))
            painter.drawText(self.rect(), Qt.AlignCenter, "等待识别设备布局")
            return
        # Reuse the original rails, beam dots, contact lines and foot renderer.
        super().paintEvent(event)
        if not self.overview:
            return
        painter = QPainter(self)
        rect = self.lane_rect()
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        count = len(self._contact_bits) // 96
        stride = max(1, (count * 28 + int(rect.height()) - 1) // int(rect.height()))
        for segment in range(count):
            selected = segment == self.selected_segment
            if segment % stride and not selected:
                continue
            y = self._y_for_index(segment * 96, rect.top(), rect.height())
            painter.setPen(QColor("#ff9b3d" if selected else "#8f9bad"))
            position = f"{self._positions_m[segment * 96]:g}"
            position = painter.fontMetrics().elidedText(position, Qt.ElideRight, 21)
            painter.drawText(QRectF(2, y - 8, 21, 18), Qt.AlignRight | Qt.AlignVCenter, position)
            painter.drawText(QRectF(self.width() - 23, y - 8, 22, 18),
                             Qt.AlignLeft | Qt.AlignVCenter, f"{segment + 1}段")
        painter.setPen(QColor("#8f9bad"))
        painter.drawText(QRectF(0, rect.bottom() + 7, self.width(), 20), Qt.AlignCenter,
                         f"{self._positions_m[-1]:.3f} m · 末光束")
        painter.end()

    def _foot_size_for_lane(self, lane_width, lane_height, length_cm):
        width, height = super()._foot_size_for_lane(lane_width, lane_height, length_cm)
        # Keep the existing foot icons legible in the full-track overview.
        # The minimum is a display size, not a measured foot length.
        if self.overview:
            height = max(40, height)
            width = max(width, int(height / 1.62))
        return width, height


class GroundTrackPanel(QWidget):
    """The overview can live in the app's full-height rail; detail stays beside video."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame = {}
        self._summary = {}
        self._layout = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(7)
        self.title = QLabel("全程跑道")
        self.title.setStyleSheet("font-size: 13pt; color: #c6ced9; font-weight: bold;")
        self.device_label = QLabel("等待识别设备段数")
        self.direction_label = QLabel("上方为接口侧 · 等待进入")
        self.channel = GroundChannelWidget()
        self.legend = QLabel("淡色：历史脚印 · 居中：左右未知\n黄色光束：数据未知 · 图标大小非实测")
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("font-size: 10pt; color: #768394;")
        for item in (self.title, self.device_label, self.direction_label):
            layout.addWidget(item)
        layout.addWidget(self.channel, 1)
        layout.addWidget(self.legend)
        self.setMinimumWidth(240)
        self.setMaximumWidth(340)
        self.setStyleSheet("GroundTrackPanel { background: transparent; border: none; } QLabel { color: #aeb7c5; background: transparent; border: none; }")

        self.detail = QWidget(self)
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(4, 4, 4, 4)
        self.detail_title = QLabel("选择设备段查看光束")
        self.detail_title.setStyleSheet("font-size: 12pt; color: #c6ced9; font-weight: bold;")
        self.detail_range = QLabel("")
        self.detail_channel = GroundChannelWidget(overview=False)
        self.detail_status = QLabel("等待数据")
        self.detail_status.setWordWrap(True)
        self.detail_status.setMinimumHeight(48)
        for item in (self.detail_title, self.detail_range):
            detail_layout.addWidget(item)
        detail_layout.addWidget(self.detail_channel, 1)
        detail_layout.addWidget(self.detail_status)
        self.detail.setMinimumWidth(190)
        self.detail.setMaximumWidth(280)
        self.detail.setStyleSheet("QWidget { background: transparent; border: none; color: #aeb7c5; }")
        self.detail.hide()
        self.channel.segment_selected.connect(self._render_detail)

    def clear(self):
        self._frame, self._summary, self._layout = {}, {}, {}
        self.channel.clear()
        self.detail_channel.clear()
        self.device_label.setText("等待识别设备段数")
        self.direction_label.setText("上方为接口侧 · 等待进入")
        self.detail_title.setText("选择设备段查看光束")
        self.detail_range.clear()
        self.detail_status.setText("等待数据")

    def set_layout(self, device):
        self._layout = device or {}
        positions = self._layout.get("positions_m", ())
        if positions:
            self.render_state({"positions_m": positions, "contact_bits": [0] * len(positions),
                               "valid_bits": [0] * len(positions), "feet": []})

    def set_summary(self, summary):
        self._summary = summary
        direction = summary.get("direction", 0)
        self.direction_label.setText({1: "↓ 向末端前进", -1: "↑ 向接口侧前进"}.get(direction, "上方为接口侧 · 方向待识别"))
        self._render_history()

    def render_state(self, frame):
        if not frame.get("positions_m"):
            return
        self._frame = frame
        self.channel.render_state(frame)
        count = len(self.channel._contact_bits) // 96
        self.device_label.setText(f"{count} 段 / 标称 {count} 米")
        self._render_detail()
        self._render_history()

    def _render_history(self):
        now = self._frame.get("timestamp_s", 0)
        history = []
        for contact in self._summary.get("contacts", []):
            if "toe_m" in contact:
                if not all(contact.get(k, {}).get("valid") for k in ("toe_m", "lift_s", "contact_s")):
                    continue
                position, end = contact["toe_m"]["value"], contact["lift_s"]["value"]
            else:
                if not contact.get("confirmed") or contact.get("exclusion"):
                    continue
                position, end = contact.get("position_m"), contact.get("end")
            if position is not None and end is not None and end <= now:
                history.append({"centroid_cm": position * 100, "side": contact.get("side", "unknown"),
                                "status": "confirmed"})
        self.channel.history = history
        self.channel.update()

    def _render_detail(self, *_):
        if not self._frame:
            return
        index = self.channel.selected_segment
        start, end = index * 96, (index + 1) * 96
        positions = self._frame["positions_m"][start:end]
        bits = self._frame["contact_bits"][start:end]
        valid = self._frame.get("valid_bits", [1] * len(self._frame["contact_bits"]))[start:end]
        self.detail_title.setText(f"第 {index + 1} 段 · 光束详情")
        self.detail_range.setText(f"{positions[0]:.3f}–{positions[-1]:.3f} m")
        self.detail_channel.render_state({"positions_m": positions, "contact_bits": bits, "valid_bits": valid,
                                          "feet": [foot for foot in self._frame.get("feet", [])
                                                   if foot.get("centroid_cm") is not None
                                                   and positions[0] <= foot["centroid_cm"] / 100 <= positions[-1]]})
        invalid = [i + 1 for i, v in enumerate(valid) if not v]
        blocked = [i + 1 for i, b in enumerate(bits) if b and i < len(valid) and valid[i]]
        if invalid:
            status = "数据无效 / 未知：" + self._indices(invalid)
        elif blocked:
            status = "遮挡光束：" + self._indices(blocked)
        else:
            status = "96 路数据有效 · 无遮挡"
        self.detail_status.setText(status)
        self.detail_status.setToolTip(status)

    @staticmethod
    def _indices(indices):
        # Compact consecutive beams without losing the module-local numbering.
        groups = []
        for value in indices:
            if groups and value == groups[-1][-1] + 1:
                groups[-1].append(value)
            else:
                groups.append([value])
        return "、".join(str(g[0]) if len(g) == 1 else f"{g[0]}–{g[-1]}" for g in groups)
