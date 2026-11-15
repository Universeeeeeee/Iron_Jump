"""Application-level shell with fixed module navigation."""

from __future__ import annotations

import os

from qtpy.QtCore import Signal, Qt
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from path_utils import get_base_dir

from ui.styles import SHELL_QSS, APP_DIALOG_QSS
from ui.theme import SPACE


MODULE_ATHLETES = "athletes"
MODULE_TEST = "test"
MODULE_RESULTS = "results"
MODULE_SETTINGS = "settings"

MODULE_LABELS = {
    MODULE_ATHLETES: "运动员",
    MODULE_TEST: "测试",
    MODULE_RESULTS: "结果",
    MODULE_SETTINGS: "设置",
}

MODULE_GLYPHS = {
    MODULE_ATHLETES: "○",
    MODULE_TEST: "▷",
    MODULE_RESULTS: "▥",
    MODULE_SETTINGS: "⚙",
}


class ApplicationSidebar(QFrame):
    """Fixed expanded navigation. Collapsing is intentionally deferred."""

    module_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ApplicationSidebar")
        self.setFixedWidth(184)
        self.buttons: dict[str, QPushButton] = {}
        self._active_module = MODULE_TEST
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE["control"], SPACE["card"], SPACE["control"], SPACE["lg"])
        layout.setSpacing(SPACE["control"])

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(SPACE["sm"], 0, SPACE["xs"], SPACE["dialog"])

        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("BrandLogo")
        self.brand_logo.setAccessibleName("映衡")
        self.brand_logo.setFixedSize(146, 52)
        self.brand_logo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        logo_path = os.path.join(
            get_base_dir(), "ui", "assets", "yingheng_brand.png"
        )
        logo = QPixmap(logo_path)
        self.brand_logo.setPixmap(
            logo.scaled(
                self.brand_logo.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
        brand_row.addWidget(self.brand_logo)
        brand_row.addStretch()
        layout.addLayout(brand_row)

        for module in (
            MODULE_ATHLETES,
            MODULE_TEST,
            MODULE_RESULTS,
            MODULE_SETTINGS,
        ):
            button = QPushButton()
            button.setObjectName("ModuleButton")
            button.setMinimumHeight(54)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName(MODULE_LABELS[module])

            button_layout = QHBoxLayout(button)
            button_layout.setContentsMargins(SPACE["lg"], 0, SPACE["control"], 0)
            button_layout.setSpacing(13)

            glyph = QLabel(MODULE_GLYPHS[module])
            glyph.setObjectName("NavGlyph")
            glyph.setAlignment(Qt.AlignCenter)
            glyph.setAttribute(Qt.WA_TransparentForMouseEvents)
            glyph_font = glyph.font()
            glyph_font.setPixelSize(20)
            glyph.setFont(glyph_font)
            button_layout.addWidget(glyph)

            label = QLabel(MODULE_LABELS[module])
            label.setObjectName("NavLabel")
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            label_font = label.font()
            label_font.setPixelSize(15)
            label.setFont(label_font)
            button_layout.addWidget(label)
            button_layout.addStretch(1)

            button.clicked.connect(
                lambda _checked=False, key=module: self._request_module(key)
            )
            self._button_group.addButton(button)
            self.buttons[module] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.set_active_module(MODULE_TEST)

    def set_active_module(self, module: str) -> None:
        button = self.buttons.get(module)
        if button is not None:
            self._active_module = module
            for key, candidate in self.buttons.items():
                active = key == module
                candidate.setChecked(active)
                for object_name in ("NavGlyph", "NavLabel"):
                    label = candidate.findChild(QLabel, object_name)
                    if label is None:
                        continue
                    label.setProperty("active", active)
                    label.style().unpolish(label)
                    label.style().polish(label)

    def _request_module(self, module: str) -> None:
        # A route can be rejected by MainWindow (for example while acquiring).
        # Keep the accepted route selected until the router confirms a change.
        self.set_active_module(self._active_module)
        self.module_requested.emit(module)


class ApplicationShell(QWidget):
    """Visual shell; the main window remains authoritative for routing."""

    module_requested = Signal(str)

    def __init__(self, content: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("ApplicationShell")
        self.setStyleSheet(SHELL_QSS)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = ApplicationSidebar()
        self.sidebar.module_requested.connect(self.module_requested)
        layout.addWidget(self.sidebar)

        content_frame = QFrame()
        content_frame.setObjectName("ShellContent")
        content_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content_layout = QVBoxLayout(content_frame)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(content)
        layout.addWidget(content_frame, 1)

    def set_active_module(self, module: str) -> None:
        self.sidebar.set_active_module(module)
