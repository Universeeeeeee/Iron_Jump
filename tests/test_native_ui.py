"""Native widget migration and small-window behavior, without USB or cloud services."""

import os
from pathlib import Path
import subprocess
import sys

import pytest
from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QLabel, QPushButton, QScrollArea

from config.test_config import default_jump_config
from tests.test_main_window_navigation import _window
from ui.widgets import CollapsibleSection


def test_sections_expand_and_collapse_with_native_keyboard_control(qtbot):
    content = QLabel("参数内容")
    section = CollapsibleSection("滤波参数", content)
    qtbot.addWidget(section)
    section.show()
    assert not content.isVisible()
    section.toggle_button.setFocus()
    qtbot.keyClick(section.toggle_button, Qt.Key_Space)
    assert content.isVisible()
    qtbot.keyClick(section.toggle_button, Qt.Key_Space)
    assert not content.isVisible()


@pytest.mark.parametrize("size", [(1920, 1080), (1366, 768), (1280, 720), (1092, 614), (910, 512)])
def test_small_windows_keep_actions_in_the_visible_viewport(qtbot, tmp_path, monkeypatch, size):
    window, _ = _window(qtbot, tmp_path)
    monkeypatch.setattr(window._exec_view._camera_panel, "start_preview", lambda: None)
    window.resize(*size)
    window.show()
    window._setup_view._set_config_mode(1)
    QApplication.processEvents()
    assert (window.width(), window.height()) == size

    def visible_in_viewport(button):
        assert button.isVisible()
        rect = button.rect().translated(button.mapTo(window, button.rect().topLeft()))
        assert window.rect().contains(rect)
        center = button.mapTo(window, button.rect().center())
        assert window.childAt(center) is button

    visible_in_viewport(window._setup_view.btn_ready)
    window._exec_view.configure(default_jump_config())
    window._go_to_execution()
    QApplication.processEvents()
    visible_in_viewport(window._exec_view.btn_return_config)
    visible_in_viewport(window._exec_view.btn_start)
    assert window._exec_view._progress_container.parentWidget() is window._exec_view._lower_split
    assert window._exec_view._progress_bar.orientation() == Qt.Vertical
    # A hidden ground rail must not reserve an empty column in other modes.
    assert window._content_layout.columnStretch(1) == 0


def test_desktop_and_legacy_entries_work_with_dayu_imports_blocked():
    code = '''
import importlib.abc
import sys
class NoDayu(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == 'dayu_widgets':
            raise ModuleNotFoundError('Dayu intentionally unavailable', name=fullname)
sys.meta_path.insert(0, NoDayu())
from qtpy.QtCore import QTimer
from ui.application import application
from ui.demo import DemoWindow
from ui.data_show import RealTimeGaitWidget
from ui.led_con import SerialDataWidget
from camera.logi_camera import LogiCameraWidget
from camera.tinyse_camera import TinySeCameraWidget
import agent.agent_test_ui
with application() as app:
    windows = [RealTimeGaitWidget(), SerialDataWidget(), LogiCameraWidget(), TinySeCameraWidget()]
    for window in windows:
        window.show()
        window.close()
    assert not any(n.split('.')[0] == 'dayu_widgets' for n in sys.modules)
    QTimer.singleShot(0, app.quit)
'''
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_API": "pyside6"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_small_settings_window_scrolls_instead_of_compressing_fields(qtbot, tmp_path):
    window, _ = _window(qtbot, tmp_path)
    window.resize(910, 512)
    window.show()
    window._go_to_settings()
    QApplication.processEvents()
    view = window._settings_view
    for label in view._value_labels.values():
        assert label.height() >= label.heightForWidth(label.width())
    scroll = view.findChild(QScrollArea, "SettingsContentScroll")
    scrollbar = scroll.verticalScrollBar()
    assert scrollbar.maximum() > 0
    scrollbar.setValue(scrollbar.maximum())
    QApplication.processEvents()
    save = view._quality_card.findChild(QPushButton)
    assert window.childAt(save.mapTo(window, save.rect().center())) is save
