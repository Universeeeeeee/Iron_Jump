"""Preview preparation must retain the old color and resampling output."""
import numpy as np
import pytest

import cv2
from qtpy.QtGui import QImage
from ui.embedded_camera_panel import EmbeddedCameraPanel


@pytest.mark.parametrize('target', [(90, 50), (384, 216), (192, 108)])
def test_preview_resize_before_color_preserves_pixels_and_ownership(qtbot, target):
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel._preview.setGeometry(0, 0, *target)
    frame = np.random.default_rng(42).integers(0, 256, (108, 192, 3), dtype=np.uint8)
    original = frame.copy()
    panel._render_frame(frame)
    image = panel._preview.pixmap().toImage().convertToFormat(QImage.Format_RGB888)
    expected = cv2.cvtColor(original, cv2.COLOR_BGR2RGB)
    if (image.width(), image.height()) != (192, 108):
        expected = cv2.resize(expected, (image.width(), image.height()), interpolation=cv2.INTER_AREA)
    np.testing.assert_array_equal(frame, original)
    frame[:] = 0
    pixels = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    actual = pixels[:, :image.width() * 3].reshape(image.height(), image.width(), 3)
    np.testing.assert_array_equal(actual, expected)
