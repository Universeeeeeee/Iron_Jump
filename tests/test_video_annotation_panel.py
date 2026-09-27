import json
from pathlib import Path

import pytest
from qtpy.QtCore import Qt

from ui.embedded_camera_panel import EmbeddedCameraPanel
from tests.test_avi_video import make_avi


@pytest.fixture
def panel(qtbot):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.resize(900, 850)
    panel.show()
    yield panel
    panel.shutdown()


def open_panel(qtbot, panel, path):
    panel.open_recording(path)
    qtbot.waitUntil(lambda: panel._annotation_tools._valid_frame and not panel._playback.is_frame_pending)


def draw(qtbot, panel, points):
    panel._annotation_tools.set_tool('angle')
    for point in points:
        qtbot.mouseClick(panel._preview, Qt.LeftButton, pos=panel._preview.to_screen(point).toPoint())


def seek(qtbot, panel, index):
    panel._playback.seek(index)
    qtbot.waitUntil(lambda: panel._playback.index == index and not panel._playback.is_frame_pending)


def test_full_annotation_edit_measure_reopen_flow(panel, tmp_path, qtbot):
    path = make_avi(tmp_path, count=4, times=[0, 0.1, 0.25, 0.5])
    open_panel(qtbot, panel, path)
    tools, canvas = panel._annotation_tools, panel._preview
    draw(qtbot, panel, [[10, 10], [30, 10], [30, 30]])
    draw(qtbot, panel, [[15, 15], [40, 15], [40, 35]])
    assert len(tools.document.records) == 2
    tools.set_tool('select')
    original = tools.document.records[1]['points'][0][:]
    qtbot.mousePress(canvas, Qt.LeftButton, pos=canvas.to_screen(original).toPoint())
    target = canvas.to_screen([20, 25]).toPoint()
    qtbot.mouseMove(canvas, target)
    qtbot.mouseRelease(canvas, Qt.LeftButton, pos=target)
    assert tools.document.records[1]['points'][0] != original
    tools.set_start()
    panel._playback.set_rate(0.25)
    seek(qtbot, panel, 3)
    assert not canvas.visible_angles()
    tools.set_end()
    assert len(tools.document.records) == 3
    assert '0.500 s' in tools.list.item(2).text()
    assert len(canvas.visible_intervals()) == 1
    tools._list_jump(tools.list.item(0))
    qtbot.waitUntil(lambda: panel._playback.index == 0 and not panel._playback.is_frame_pending)
    assert len(canvas.visible_angles()) == 2
    assert canvas.selected_id == tools.document.records[0]['id']
    tools.list_toggle.setChecked(True)
    assert tools.list_panel.isVisible()
    tools.list_toggle.setChecked(False)
    expected = json.loads(path.with_suffix('.annotations.json').read_text())['annotations']
    panel._leave_playback()
    open_panel(qtbot, panel, path)
    assert tools.document.records == expected
    tools.canvas.select(expected[0]['id'])
    qtbot.keyClick(canvas, Qt.Key_Delete)
    assert len(tools.document.records) == 2
    panel._leave_playback()
    open_panel(qtbot, panel, path)
    assert len(tools.document.records) == 2


def test_invalid_end_keeps_start_and_escape_cancels(panel, tmp_path, qtbot):
    open_panel(qtbot, panel, make_avi(tmp_path, count=3))
    tools = panel._annotation_tools
    seek(qtbot, panel, 1)
    tools.set_start()
    for index in [1, 0]:
        seek(qtbot, panel, index)
        tools.set_end()
        assert tools.time_start == 1
        assert '晚于' in tools.status.text()
    seek(qtbot, panel, 2)
    tools.set_end()
    assert '估算' in tools.list.item(0).text()
    assert tools.time_start is None
    tools.set_start()
    qtbot.keyClick(panel._preview, Qt.Key_Escape)
    assert tools.time_start is None


def test_save_failure_restores_angle_and_preserves_file(panel, tmp_path, qtbot, monkeypatch):
    path = make_avi(tmp_path)
    open_panel(qtbot, panel, path)
    tools = panel._annotation_tools
    draw(qtbot, panel, [[10, 10], [30, 10], [30, 30]])
    before = tools.document.path.read_bytes()
    points = tools.document.records[0]['points']

    def fail(*args):
        raise PermissionError('read only')

    monkeypatch.setattr(Path, 'replace', fail)
    tools._edit_angle(tools.document.records[0]['id'], [[5, 5], [30, 10], [30, 30]])
    assert tools.document.records[0]['points'] == points
    assert tools.document.path.read_bytes() == before
    assert '修改未生效' in tools.status.text()
    tools.delete_selected()
    assert len(tools.document.records) == 1


def test_broken_annotation_file_disables_edits_not_playback(panel, tmp_path, qtbot):
    path = make_avi(tmp_path)
    sidecar = path.with_suffix('.annotations.json')
    sidecar.write_text('{broken')
    open_panel(qtbot, panel, path)
    tools = panel._annotation_tools
    assert tools.document is None
    assert not tools.angle_button.isEnabled()
    assert panel._play_button.isEnabled()
    seek(qtbot, panel, 3)
    assert panel._playback.index == 3
    assert sidecar.read_text() == '{broken'


def test_play_exits_drawing_and_seek_discards_draft(panel, tmp_path, qtbot):
    open_panel(qtbot, panel, make_avi(tmp_path))
    tools, canvas = panel._annotation_tools, panel._preview
    tools.set_tool('angle')
    qtbot.mouseClick(canvas, Qt.LeftButton, pos=canvas.to_screen([10, 10]).toPoint())
    assert canvas.draft
    seek(qtbot, panel, 2)
    assert not canvas.draft
    tools.set_start()
    tools.set_tool('angle')
    panel._playback.play()
    assert canvas.tool == 'select' and not canvas.editable
    assert tools.time_start == 2
    panel._on_playback_error('bad frame')
    assert not canvas.annotations_visible and not canvas.editable
    assert not tools.start_button.isEnabled()


def test_read_pending_blocks_creation_and_small_layout_fits(panel, tmp_path, qtbot, monkeypatch):
    import threading
    from camera.avi_video import AviVideo

    open_panel(qtbot, panel, make_avi(tmp_path))
    tools, canvas = panel._annotation_tools, panel._preview
    entered, release = threading.Event(), threading.Event()
    read = AviVideo.read

    def slow(video, index):
        entered.set()
        release.wait(2)
        return read(video, index)

    monkeypatch.setattr(AviVideo, 'read', slow)
    try:
        panel._playback.seek(2)
        qtbot.waitUntil(entered.is_set)
        assert not tools.angle_button.isEnabled()
        assert not canvas.editable
        tools._create_angle([[10, 10], [30, 10], [30, 30]])
        assert tools.document.records == []
        release.set()
        qtbot.waitUntil(lambda: not panel._playback.is_frame_pending)
        assert tools.angle_button.isEnabled()
        panel.resize(360, 680)
        tools.list_toggle.setChecked(True)
        qtbot.wait(20)
        assert panel.width() <= 360
        for widget in (tools.select_button, tools.delete_button, tools.list_panel):
            assert tools.rect().contains(widget.geometry())
    finally:
        release.set()


def test_escape_from_control_focus_cancels_time_start(panel, tmp_path, qtbot):
    open_panel(qtbot, panel, make_avi(tmp_path))
    tools = panel._annotation_tools
    qtbot.mouseClick(tools.start_button, Qt.LeftButton)
    assert tools.time_start == 0
    panel._next_button.setFocus()
    qtbot.keyClick(panel._next_button, Qt.Key_Escape)
    assert tools.time_start is None
