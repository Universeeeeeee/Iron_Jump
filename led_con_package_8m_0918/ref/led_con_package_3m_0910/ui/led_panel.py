"""
led_panel.py — 8×12 LED 面板控件

使用单个 QWidget 批量绘制全部 LED，避免为每个 LED 创建 QLabel。
"""
from qtpy import QtWidgets
from qtpy.QtCore import QRectF, QSize, Qt
from qtpy.QtGui import QColor, QPainter, QPen


class LEDPanel(QtWidgets.QWidget):
    """轻量 LED 面板：绿色=亮，灰色=灭。"""

    _ON = QColor("#2ecc71")
    _ON_BORDER = QColor("#1b874a")
    _OFF = QColor("#4b4b4b")
    _OFF_BORDER = QColor("#2e2e2e")
    _MARGIN = 6.0
    _SPACING = 6.0
    _LED_SIZE = 18.0

    def __init__(self, rows=8, cols=12, parent=None):
        super().__init__(parent)
        self.rows = int(rows)
        self.cols = int(cols)
        self._states = (False,) * (self.rows * self.cols)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    def sizeHint(self):
        width = self.cols * self._LED_SIZE + (self.cols - 1) * self._SPACING + 2 * self._MARGIN
        height = self.rows * self._LED_SIZE + (self.rows - 1) * self._SPACING + 2 * self._MARGIN
        return QSize(round(width), round(height))

    def minimumSizeHint(self):
        return QSize(self.cols * 8, self.rows * 8)

    def led_states(self):
        """Return the currently displayed states in row-major order."""
        return tuple(int(value) for value in self._states)

    def clear(self):
        self.set_leds(())

    def set_leds(self, bits):
        """Store the latest LED state and schedule one coalesced repaint."""
        count = len(self._states)
        incoming = tuple(bool(bits[index]) if index < len(bits) else False for index in range(count))
        if incoming == self._states:
            return
        self._states = incoming
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        usable_width = max(0.0, self.width() - 2 * self._MARGIN)
        usable_height = max(0.0, self.height() - 2 * self._MARGIN)
        cell_width = usable_width / self.cols if self.cols else 0.0
        cell_height = usable_height / self.rows if self.rows else 0.0
        diameter = max(1.0, min(self._LED_SIZE, cell_width - self._SPACING, cell_height - self._SPACING))

        for index, is_on in enumerate(self._states):
            row, col = divmod(index, self.cols)
            center_x = self._MARGIN + (col + 0.5) * cell_width
            center_y = self._MARGIN + (row + 0.5) * cell_height
            rect = QRectF(center_x - diameter / 2, center_y - diameter / 2, diameter, diameter)
            painter.setPen(QPen(self._ON_BORDER if is_on else self._OFF_BORDER, 1.0))
            painter.setBrush(self._ON if is_on else self._OFF)
            painter.drawRoundedRect(rect, 3.0, 3.0)
