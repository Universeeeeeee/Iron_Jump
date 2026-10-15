import pytest

pytest.importorskip("qtpy")

from qtpy.QtWidgets import QApplication
from qtpy.QtCore import Qt
from qtpy.QtGui import QPainter, QPixmap

from ui.footprint_channel import FootprintChannelWidget, FootprintReplayPanel
from ui.ground_track import GroundChannelWidget


def _app():
    return QApplication.instance() or QApplication([])


def test_channel_widget_maps_interface_side_zero_to_top():
    _app()
    widget = FootprintChannelWidget()

    widget.set_direction("Interface side")

    assert widget._y_for_index(0, 10, 90) == 10
    assert widget._y_for_index(95, 10, 90) == 100


def test_channel_widget_maps_opposite_side_zero_to_bottom():
    _app()
    widget = FootprintChannelWidget()

    widget.set_direction("Opposite side")

    assert widget._y_for_index(0, 10, 90) == 100
    assert widget._y_for_index(95, 10, 90) == 10


def test_channel_widget_uses_uniform_subpixel_led_spacing_for_any_height():
    _app()
    widget = FootprintChannelWidget()

    markers = widget._rail_marker_rects(rail_x=30.0, top=34.0, height=486.0)
    centers = [marker.center().y() for marker in markers]
    gaps = [abs(right - left) for left, right in zip(centers, centers[1:])]

    assert len(markers) == 96
    assert gaps == pytest.approx([486.0 / 95.0] * 95)
    assert any(center != int(center) for center in centers)


def test_replay_panel_applies_direction_to_channel():
    _app()
    panel = FootprintReplayPanel()

    panel.set_direction("Opposite side")

    assert panel._channel._y_for_index(0, 10, 90) == 100


def test_channel_widget_scales_footprint_size_from_real_foot_length():
    _app()
    widget = FootprintChannelWidget()

    foot_w, foot_h = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=24.0,
    )

    assert 110 <= foot_h <= 130
    assert 65 <= foot_w <= 80


def test_channel_widget_defaults_to_28cm_foot_length_when_missing():
    _app()
    widget = FootprintChannelWidget()

    foot_w, foot_h = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=None,
    )

    assert 135 <= foot_h <= 150
    assert 82 <= foot_w <= 92


def test_channel_widget_ignores_unreasonable_cluster_length_for_size():
    _app()
    widget = FootprintChannelWidget()

    default_size = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=None,
    )
    oversized_cluster_size = widget._foot_size_for_lane(
        lane_width=900,
        lane_height=500,
        length_cm=99.84,
    )

    assert oversized_cluster_size == default_size


def test_channel_widget_skips_candidate_foot_glyphs():
    _app()
    widget = FootprintChannelWidget()

    widget.render_state({
        "timestamp_s": 0.0,
        "contact_bits": [0] * 96,
        "feet": [
            {
                "contact_id": 1,
                "side": "unknown",
                "centroid_cm": 28.0,
                "length_cm": 99.84,
                "status": "candidate",
            },
            {
                "contact_id": 2,
                "side": "right",
                "centroid_cm": 42.0,
                "length_cm": 28.0,
                "status": "confirmed",
            },
        ],
    })

    assert len(widget._feet) == 1
    assert widget._feet[0]["contact_id"] == 2
    assert widget._feet[0]["side"] == "right"


@pytest.mark.parametrize("channel_type", ["treadmill", "overview", "detail"])
@pytest.mark.parametrize("side, rgb", [
    ("left", (82, 220, 130)),
    ("right", (82, 170, 255)),
    ("unknown", (174, 183, 197)),
])
def test_contact_renders_footprint_with_separate_toes(qtbot, channel_type, side, rgb):
    widget = (FootprintChannelWidget() if channel_type == "treadmill"
              else GroundChannelWidget(overview=channel_type == "overview"))
    qtbot.addWidget(widget)
    count = 768 if channel_type == "overview" else 96
    widget.render_state({
        "contact_bits": [0] * count,
        "positions_m": [i * .0104 for i in range(count)],
        "feet": [],
    })
    foot = {"centroid_cm": (count - 1) * 1.04 / 2,
            "length_cm": 28, "status": "confirmed", "side": side}
    canvas = QPixmap(300, 600)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    widget._paint_foot(painter, foot, 0, 300, 0, 600)
    painter.end()
    image = canvas.toImage()
    pixels = [(x, y) for y in range(image.height()) for x in range(image.width())
              if image.pixelColor(x, y).alpha() > 128]

    assert pixels
    # An ellipse has one filled span per row; toes leave several separate spans.
    assert any(sum(image.pixelColor(x, y).alpha() > 128
                   and image.pixelColor(x - 1, y).alpha() <= 128
                   for x in range(1, image.width())) > 1
               for y in range(image.height()))
    assert all(image.pixelColor(x, y).getRgb()[:3] == rgb for x, y in pixels)
    expected_center = 300 * {"left": .36, "right": .64, "unknown": .5}[side]
    assert (min(x for x, _ in pixels) + max(x for x, _ in pixels)) / 2 == pytest.approx(
        expected_center, abs=3,
    )
    assert foot["side"] == side


def test_channel_widget_accepts_short_frame_without_resizing(qtbot):
    widget = FootprintChannelWidget()
    qtbot.addWidget(widget)

    widget.render_state({"timestamp_s": 0.0, "contact_bits": [1, 0, 1], "feet": []})

    assert widget._contact_bits[:3] == [1, 0, 1]
    assert len(widget._contact_bits) == 96


def test_channel_widget_does_not_store_opacity_state(qtbot):
    widget = FootprintChannelWidget()
    qtbot.addWidget(widget)
    frame = {
        "timestamp_s": 0.0,
        "contact_bits": [0] * 96,
        "feet": [{"contact_id": 1, "side": "left", "status": "confirmed"}],
    }

    widget.render_state(frame)

    assert "opacity" not in widget._feet[0]


def test_replay_panel_renders_first_timeline_frame(qtbot):
    panel = FootprintReplayPanel()
    qtbot.addWidget(panel)
    timeline = (
        {"timestamp_s": 0.0, "contact_bits": [0] * 96, "feet": []},
        {"timestamp_s": 0.1, "contact_bits": [1] * 96, "feet": []},
    )

    panel.set_timeline(timeline)

    assert panel._timeline == list(timeline)
    assert panel._channel._contact_bits == [0] * 96
