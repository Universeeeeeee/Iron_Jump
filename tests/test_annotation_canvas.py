import pytest
from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import QPixmap

from ui.annotation_canvas import AnnotationCanvas


@pytest.fixture
def canvas(qtbot):
    canvas = AnnotationCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(640, 480)
    pixmap = QPixmap(640, 360)
    pixmap.fill(Qt.black)
    canvas.setPixmap(pixmap)
    canvas.setAlignment(Qt.AlignCenter)
    canvas.set_frame(0, 1920, 1080)
    canvas.set_editable(True)
    canvas.show()
    return canvas


@pytest.mark.parametrize('dpr', [1, 2])
def test_mapping_uses_image_rect_and_device_independent_size(canvas, dpr):
    pixmap = QPixmap(640 * dpr, 360 * dpr)
    pixmap.setDevicePixelRatio(dpr)
    canvas.setPixmap(pixmap)
    assert canvas.image_rect().y() == 60
    for point in ([0, 0], [960, 540], [1919, 1079]):
        assert canvas.to_image(canvas.to_screen(point)) == pytest.approx(point)
    assert canvas.to_image(QPointF(10, 10)) is None
    assert canvas.to_image(QPointF(-100, -100), clamp=True) == [0, 0]
    assert canvas.to_image(QPointF(10000, 10000), clamp=True) == [1919, 1079]


def test_angle_clicks_ignore_black_bars_and_cancel_on_frame_change(canvas, qtbot):
    created = []
    messages = []
    canvas.angle_created.connect(created.append)
    canvas.message.connect(messages.append)
    canvas.set_tool('angle')
    qtbot.mouseClick(canvas, Qt.LeftButton, pos=QPointF(10, 10).toPoint())
    assert canvas.draft == []
    for point in ([300, 300], [600, 300], [600, 300], [600, 600]):
        qtbot.mouseClick(canvas, Qt.LeftButton, pos=canvas.to_screen(point).toPoint())
    assert len(created) == 1
    assert messages and '重合' in messages[0]
    qtbot.mouseClick(canvas, Qt.LeftButton, pos=canvas.to_screen([300, 300]).toPoint())
    canvas.set_frame(1, 1920, 1080)
    assert not canvas.draft


def test_drag_edits_only_on_release_and_clamps(canvas, qtbot):
    record = {'id': 'a', 'kind': 'angle', 'frame': 0, 'points': [[300, 300], [600, 300], [600, 600]]}
    canvas.records = [record]
    edits = []
    canvas.angle_edited.connect(lambda ident, points: edits.append((ident, points)))
    qtbot.mousePress(canvas, Qt.LeftButton, pos=canvas.to_screen(record['points'][0]).toPoint())
    qtbot.mouseMove(canvas, QPointF(-10, -10).toPoint())
    assert not edits
    assert record['points'][0] == [300, 300]
    qtbot.mouseRelease(canvas, Qt.LeftButton, pos=QPointF(-10, -10).toPoint())
    assert edits[0][1][0] == [0, 0]
    canvas.set_frame(1, 1920, 1080)
    assert canvas.visible_angles() == []


def test_interval_visibility_includes_both_endpoints(canvas):
    canvas.records = [{'id': 'a', 'kind': 'interval', 'start': 1, 'end': 3}, {'id': 'b', 'kind': 'interval', 'start': 2, 'end': 4}]
    for index, count in [(0, 0), (1, 1), (2, 2), (3, 2), (4, 1), (5, 0)]:
        canvas.set_frame(index, 1920, 1080)
        assert len(canvas.visible_intervals()) == count
