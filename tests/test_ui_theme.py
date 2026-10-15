"""Keep the migrated UI on shared tokens and check delivered button states."""
import re
from pathlib import Path
import subprocess
import sys

import pytest

from ui.theme import PALETTE


ROOT = Path(__file__).resolve().parents[1]
MIGRATED = (
    "ui/app_shell.py", "ui/views/setup_view.py", "ui/views/athletes_view.py",
    "ui/views/history_view.py", "ui/views/settings_view.py", "ui/styles.py",
)


@pytest.mark.parametrize("filename", MIGRATED)
def test_migrated_styles_do_not_duplicate_palette_values(filename):
    source = (ROOT / filename).read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{6}\b|rgba?\(", source)


def test_theme_and_styles_import_without_qt_or_dayu():
    code = """
import sys
import ui.theme, ui.styles
assert not any(name.split('.')[0] in {'qtpy', 'PySide6', 'PyQt5', 'dayu_widgets'}
               for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_primary_action_renders_distinct_enabled_and_disabled_surfaces(qtbot):
    from qtpy.QtWidgets import QApplication, QPushButton, QWidget
    from ui.styles import SETUP_QSS

    root = QWidget()
    root.setObjectName("SetupViewRoot")
    root.setStyleSheet(SETUP_QSS)
    qtbot.addWidget(root)
    button = QPushButton("进入测试准备", root)
    button.setObjectName("PrimaryStartButton")
    button.resize(240, 50)
    root.resize(300, 80)
    root.show()
    for enabled, color in ((True, "accent"), (False, "control_disabled")):
        button.setEnabled(enabled)
        QApplication.processEvents()
        image = button.grab().toImage()
        # Inside the surface, clear of the border, rounded corner and text.
        assert image.pixelColor(20, 10).name() == PALETTE[color]
