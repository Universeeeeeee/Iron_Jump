import pytest

pytest.importorskip("dayu_widgets")

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QApplication, QBoxLayout, QGridLayout

from config.test_config import TestConfig
from config.treadmill_config import TreadmillGaitConfig, TreadmillRunningConfig
from ui.footprint_channel import FootprintChannelWidget
from ui.views.execution_view import ExecutionView, MetricCard, _PG_AVAILABLE


def _app():
    return QApplication.instance() or QApplication([])


def test_metric_card_keeps_value_visible_when_unit_is_shown(qtbot):
    card = MetricCard("平均步速", "cm/s")
    qtbot.addWidget(card)
    card.resize(400, 130)
    card.show()
    QApplication.processEvents()

    assert card.minimumHeight() >= card.minimumSizeHint().height()
    assert card._value.height() >= card._value.sizeHint().height()
    assert card._unit.height() >= card._unit.sizeHint().height()


def test_execution_view_passes_treadmill_direction_to_footprint_channel():
    _app()
    view = ExecutionView()

    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Opposite side",
        )
    )

    assert view._footprint_channel._direction == "Opposite side"


@pytest.mark.parametrize(
    "config_type",
    [TreadmillGaitConfig, TreadmillRunningConfig],
)
def test_execution_view_shows_footprint_channel_for_treadmill(qtbot, config_type):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()

    view.configure(
        config_type(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )
    QApplication.processEvents()

    assert isinstance(view._footprint_channel, FootprintChannelWidget)
    assert view._footprint_channel.isVisible()
    assert len(
        view._footprint_channel._rail_marker_rects(
            rail_x=30.0, top=34.0, height=486.0
        )
    ) == 96
    assert view._cycle_panel.isVisible()
    assert not view._chart_container.isVisible()
    layout = view._lower_split.layout()
    assert isinstance(layout, QGridLayout)
    assert layout.getItemPosition(layout.indexOf(view._camera_column)) == (0, 0, 2, 1)
    assert view._camera_panel.parentWidget() is view._camera_column
    assert view._cycle_panel.parentWidget() is view._camera_column
    assert layout.getItemPosition(layout.indexOf(view._progress_container)) == (0, 1, 2, 1)
    assert layout.getItemPosition(layout.indexOf(view._footprint_channel)) == (0, 2, 1, 1)
    assert layout.getItemPosition(layout.indexOf(view._controls_container)) == (1, 2, 1, 1)
    assert layout.columnStretch(0) == 3
    assert layout.columnStretch(2) == 1


def test_gait_time_and_controls_use_vertical_lower_layout(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1600, 900)
    view.show()

    view.configure(
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    assert view._progress_bar.orientation() == Qt.Vertical
    assert view._progress_title.text() == "剩余"
    assert view._progress_value.text() == "01:00"
    assert view._progress_container.isVisible()
    assert view._progress_container.width() == 72
    assert view._progress_container.height() == view._lower_split.height()
    assert view._progress_bar.width() == view._progress_container.width()
    assert view._progress_bar.height() == view._progress_container.height()
    assert view._progress_overlay.geometry() == view._progress_bar.geometry()
    assert view._controls_layout.direction() == QBoxLayout.TopToBottom
    assert view.btn_stop.text() == "结束"
    assert view._controls_container.geometry().left() == view._footprint_channel.geometry().left()
    assert view._controls_container.geometry().right() == view._footprint_channel.geometry().right()


def test_gait_running_controls_stack_in_right_column(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="End of Time",
            test_length="01:00",
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    view.on_device_state("connected", "设备已连接")
    view._on_start()
    view.on_session_started()

    assert not view.btn_start.isVisible()
    assert view.btn_pause.isVisible()
    assert view.btn_stop.isVisible()
    assert view._controls_layout.direction() == QBoxLayout.TopToBottom

    remaining_before_pause = view._countdown_remaining
    view._on_pause()
    assert not view._paused  # UI waits for the engine acknowledgement.
    view.set_paused(True)
    assert "暂停分析（计时已暂停）" in view._mode_label.text()
    assert view.btn_pause.text() == "▶ 继续分析"
    assert view._countdown_timer is None
    view._on_countdown_tick()
    assert view._countdown_remaining == remaining_before_pause

    view._on_pause()
    assert view._paused
    view.set_paused(False)
    assert view.btn_pause.text() == "⏸ 暂停"
    assert view._countdown_timer is not None
    assert view._countdown_timer.isActive()


def test_execution_view_reuses_camera_layout_and_only_shows_jump_height_chart(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    config = TestConfig(test_type="Jump Test")

    view.configure(config)
    QApplication.processEvents()

    assert view._lower_split.isVisible()
    assert view._camera_panel.isVisible()
    assert view._chart_container.isVisible()
    assert not view._footprint_channel.isVisible()
    layout = view._lower_split.layout()
    assert layout.getItemPosition(layout.indexOf(view._camera_column)) == (0, 0, 2, 1)
    assert layout.getItemPosition(layout.indexOf(view._chart_container)) == (0, 2, 1, 1)
    assert layout.getItemPosition(layout.indexOf(view._progress_container)) == (0, 1, 2, 1)
    assert layout.getItemPosition(layout.indexOf(view._controls_container)) == (1, 2, 1, 1)
    assert layout.columnStretch(0) == 3
    assert layout.columnStretch(2) == 1
    assert view._progress_bar.orientation() == Qt.Vertical
    assert view._controls_layout.direction() == QBoxLayout.TopToBottom
    if _PG_AVAILABLE:
        assert view._plot_h.isVisible()
        assert not view._plot_cadence.isVisible()


def test_execution_view_shows_current_gait_cycle_without_completed_table(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )

    view.on_gait_snapshot({
        "touch_count": 3,
        "stride_count": 0,
        "velocity_count": 0,
        "gait_cycle_asymmetry_percent": {"gait_cycle_s": 4.5},
        "gait_cycle_state": {
            "support_state": "左脚单支撑",
            "completed_cycle_count": 1,
            "completed_cycle_start_index": 0,
            "current_cycles": {
                "left": {"phase": "支撑相", "elapsed_s": 0.4},
            },
            "completed_cycles": [{
                "index": 0,
                "side": "right",
                "gait_cycle_s": 1.0,
                "stance_phase_s": 0.6,
                "swing_phase_s": 0.4,
                "total_double_support_s": 0.2,
            }],
        },
    })

    assert view._current_cycle_state.text() == "左脚单支撑"
    assert view._left_cycle_value.text() == "左脚  支撑相 0.400 s"
    assert view._right_cycle_value.text() == "右脚  --"
    assert not hasattr(view, "_completed_cycle_label")
    assert not hasattr(view, "_completed_cycle_table")
    assert view._card_imbalance._value.text() == "4.5"

def test_current_cycle_summary_uses_dashes_for_missing_values(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )
    view._render_gait_cycle_state({
        "support_state": "右脚单支撑",
        "current_cycles": {"left": {"phase": "摆动相", "elapsed_s": None}},
        "completed_cycles": [],
    })

    assert view._current_cycle_state.text() == "右脚单支撑"
    assert view._left_cycle_value.text() == "左脚  摆动相 --"
    assert view._right_cycle_value.text() == "右脚  --"

    view.reset()

    assert view._current_cycle_state.text() == "等待触地事件"
    assert view._left_cycle_value.text() == "左脚  --"
    assert view._right_cycle_value.text() == "右脚  --"


def test_current_cycle_summary_only_uses_space_left_after_max_camera(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1690, 1050)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )
    QApplication.processEvents()

    preview = view._camera_panel._preview
    container = view._camera_panel._preview_container
    assert view._cycle_panel.isVisible()
    assert view._cycle_panel.height() == 72
    assert preview.width() == (container.width() // 16) * 16
    assert preview.width() * 9 == preview.height() * 16

    view.resize(1280, 720)
    QApplication.processEvents()

    assert not view._cycle_panel.isVisible()
    assert preview.width() * 9 == preview.height() * 16


def test_visible_cycle_summary_preserves_max_camera_at_height_threshold(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.resize(1280, 810)
    view.show()
    view.configure(
        TreadmillGaitConfig(
            stop_type="Software command",
            test_length=None,
            treadmill_speed=5.0,
            direction="Interface side",
        )
    )
    QApplication.processEvents()

    preview = view._camera_panel._preview
    container = view._camera_panel._preview_container
    assert not view._cycle_panel.isVisible()

    view.resize(1280, 812)
    QApplication.processEvents()

    assert view._cycle_panel.isVisible()
    assert preview.width() == (container.width() // 16) * 16
    assert preview.width() * 9 == preview.height() * 16


def test_execution_view_does_not_enable_cycle_panel_for_ground_gait(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.show()

    view.configure(TestConfig(test_type="Gait Test"))

    assert not view._cycle_panel.isVisible()


def test_execution_view_waits_for_device_and_session_started(qtbot):
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(TestConfig(test_type="Jump Test"))

    assert not view.btn_start.isEnabled()
    assert view.btn_start.text() == "开始采集"

    view.on_device_state("connected", "设备已连接")
    assert view.btn_start.isEnabled()

    view._on_start()
    assert not view.btn_start.isEnabled()
    assert view.btn_start.text() == "正在启动…"
    assert not view.btn_start.isHidden()
    assert view.btn_pause.isHidden()

    view.on_session_started()
    assert view.btn_start.isHidden()
    assert not view.btn_pause.isHidden()
    assert not view.btn_stop.isHidden()
