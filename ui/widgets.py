"""Small native Qt sections shared by parameter and camera forms."""

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget, QSizePolicy


class CollapsibleSection(QWidget):
    def __init__(self, title, widget, expand=False, parent=None):
        super().__init__(parent)
        self.toggle_button = QToolButton()
        self.toggle_button.setObjectName("SectionToggle")
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.toggle_button)
        layout.addWidget(widget)
        self.toggle_button.toggled.connect(widget.setVisible)
        self.toggle_button.toggled.connect(
            lambda checked: self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        )
        self.toggle_button.setChecked(expand)
        self.toggle_button.setArrowType(Qt.DownArrow if expand else Qt.RightArrow)
        widget.setVisible(expand)


class SectionHeading(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        label = QLabel(title)
        label.setObjectName("SectionHeading")
        layout.addWidget(label)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line, 1)
