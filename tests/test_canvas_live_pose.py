import pytest
from qtpy.QtCore import Qt
from qtpy.QtGui import QPixmap
from ui.annotation_canvas import AnnotationCanvas
from tests.test_leg_identity import _sample


@pytest.mark.parametrize('dpr', [1, 2])
@pytest.mark.parametrize('mirrored', [False, True])
def test_live_pose_draws_on_centered_image_without_enabling_annotations(qtbot, dpr, mirrored):
    canvas = AnnotationCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(640, 480)
    canvas.setAlignment(Qt.AlignCenter)
    pixmap = QPixmap(640 * dpr, 360 * dpr)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.black)
    canvas.setPixmap(pixmap)
    canvas.show()
    clean = canvas.grab().toImage()
    background = canvas.pixmap().toImage()
    canvas.set_live_pose(_sample(1), (1920, 1080), mirrored=mirrored)
    image = canvas.grab().toImage()
    scale = image.devicePixelRatioF()
    def color(x, y):
        return image.pixelColor(round(x * scale), round(y * scale))
    rect = canvas.image_rect()
    # Bone midpoints, beyond the joint circles and text.
    for x, expected in ((.65 if mirrored else .35, (30, 120, 255)),
                        (.35 if mirrored else .65, (255, 165, 20))):
        actual = color(rect.x() + x * rect.width(), rect.y() + .425 * rect.height())
        channels = actual.getRgb()[:3]
        assert max(channels) > 100
        # A one-pixel antialiased bone may cover half of each adjacent pixel.
        assert max(abs(a * 255 / max(channels) - b) for a,b in zip(channels,expected)) < 3
    assert not canvas.annotations_visible
    assert canvas.pixmap().toImage() == background
    assert image.pixelColor(10, 10) == clean.pixelColor(10, 10)
    canvas.set_live_pose(None)
    assert canvas.grab().toImage() == clean


def test_unreliable_live_pose_does_not_draw_nodes_or_labels(qtbot):
    canvas = AnnotationCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(640, 360)
    pixmap = QPixmap(640, 360)
    pixmap.fill(Qt.black)
    canvas.setPixmap(pixmap)
    before = canvas.grab().toImage()
    canvas.set_live_pose(_sample(1, quality=.4), (1920, 1080))
    assert canvas.grab().toImage() == before


def test_live_pose_retains_side_labels_outside_joint_markers(qtbot):
    canvas = AnnotationCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(1920, 1080)
    pixmap = QPixmap(1920, 1080)
    pixmap.fill(Qt.black)
    canvas.setPixmap(pixmap)
    canvas.set_live_pose(_sample(1), (1920, 1080))
    image = canvas.grab().toImage()
    dpr = image.devicePixelRatioF()
    for ankle_x in (672, 1248):
        # Text lies above and to the right of the ankle's 8-pixel joint ring.
        colored = [image.pixelColor(round(x*dpr),round(y*dpr))
                   for x in range(ankle_x+11,ankle_x+28) for y in range(830,854)]
        assert any(c.red()+c.green()+c.blue()>100 for c in colored)
