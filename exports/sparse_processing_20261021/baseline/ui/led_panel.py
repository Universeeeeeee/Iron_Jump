"""
led_panel.py — 8×12 LED 面板控件

从 start_test.py / led_con.py 提取为独立公共模块。
"""
from qtpy import QtWidgets
from qtpy.QtCore import Qt


class LEDPanel(QtWidgets.QWidget):
    """简单的 8x12 LED 面板：绿色=亮，灰色=灭。"""
    def __init__(self, rows=8, cols=12, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self._cells = []  # list[list[QLabel]]
        lay = QtWidgets.QGridLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setHorizontalSpacing(6)
        lay.setVerticalSpacing(6)
        size = 18
        for r in range(rows):
            row_cells = []
            for c in range(cols):
                lab = QtWidgets.QLabel()
                lab.setFixedSize(size, size)
                lab.setStyleSheet(self._style_off())
                lab.setAlignment(Qt.AlignCenter)
                lay.addWidget(lab, r, c)
                row_cells.append(lab)
            self._cells.append(row_cells)

    def _style_on(self):
        return (
            "background-color: #2ecc71; border: 1px solid #1b874a; border-radius: 3px;"
        )

    def _style_off(self):
        return (
            "background-color: #4b4b4b; border: 1px solid #2e2e2e; border-radius: 3px;"
        )

    def clear(self):
        for r in range(self.rows):
            for c in range(self.cols):
                self._cells[r][c].setStyleSheet(self._style_off())

    def set_leds(self, bits):
        """bits: 长度<=96，按 LSB→MSB，索引 i 映射到 (row=i//12, col=i%12) 水平排列。

        1 表示 LED 亮（绿色），0 表示熄灭/遮挡。
        """
        # 保护：只取前 96 位
        n = min(96, len(bits))
        # 先全部置灭
        self.clear()
        for i in range(n):
            if bits[i]:
                row = i // 12  # 0..7（行优先，水平连续）
                col = i % 12   # 0..11
                if 0 <= row < self.rows and 0 <= col < self.cols:
                    self._cells[row][col].setStyleSheet(self._style_on())
