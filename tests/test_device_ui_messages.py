"""Keep driver diagnostics in logs and present readable device states."""
import logging

import pytest

from config.test_config import default_jump_config
from ui.session_controller import SessionController
from ui.views.execution_view import ExecutionView
from ui.views.setup_view import SetupView


DETAIL = "USB_Read failed: E:/device/driver.dll; ff ff 00 00"


def test_driver_messages_are_logged_without_becoming_business_notices(caplog):
    controller = SessionController()
    notices = []
    controller.device_message.connect(notices.append)
    with caplog.at_level(logging.DEBUG, logger="ui.session_controller"):
        controller._on_device_message(DETAIL)
    assert notices == []
    assert DETAIL in caplog.text
    controller.device_message.emit("设备段数识别中")
    assert notices == ["设备段数识别中"]


@pytest.mark.parametrize("state", ["error", "disconnected", "unknown"])
def test_device_state_widgets_do_not_display_driver_details(qtbot, state):
    execution = ExecutionView()
    setup = SetupView()
    qtbot.addWidget(execution)
    qtbot.addWidget(setup)
    execution.configure(default_jump_config())
    for view, label in ((execution, execution._device_label),
                        (setup, setup._device_state_label)):
        view.on_device_state(state, DETAIL)
        assert DETAIL not in label.text()
        assert DETAIL not in label.toolTip()
        assert "设备" in label.text()


def test_camera_driver_error_is_logged_instead_of_painted(qtbot, caplog):
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    detail = "OBSBOT TinySE source filter not found (hr=0x80004005)"
    with caplog.at_level(logging.ERROR, logger="ui.embedded_camera_panel"):
        panel._on_error(detail)
    assert detail in caplog.text
    assert detail not in panel._preview.text()
    assert detail not in panel._status_text
    assert "检查连接" in panel._preview.text()


@pytest.mark.parametrize("degraded", [False, True])
def test_report_keeps_quality_diagnostics_out_of_visible_text(qtbot, degraded):
    from config.treadmill_report import TreadmillGaitReport
    from ui.views.report_view import ReportView
    quality = {
        "degraded": degraded,
        "preflight": {"bad_indices": [576] if degraded else [],
                      "stability": {"transient_beam_pulses": 107966}},
        "events": [{"code": "runtime_suspicious"}] if degraded else [],
        "event_count": 68 if degraded else 0,
        "limitation": "internal diagnostic details",
    }
    report = TreadmillGaitReport(touch_count=0, lift_count=0, resolved_starting_foot="unknown",
                                 starting_foot_source="unknown", finish_reason="manual",
                                 report_config_snapshot={"beam_quality": quality})
    view = ReportView()
    qtbot.addWidget(view)
    view.load_report(report)
    text = view._reason_label.text()
    assert all(value not in text for value in ("107966", "冻结", "项记录", "internal diagnostic"))
    assert not view._reason_label.toolTip()
    assert ("1 束不可用，相关事件已排除" in text) == degraded
    assert ("部分采集区间需复核" in text) == degraded
    assert report.report_config_snapshot["beam_quality"] == quality


def test_execution_quality_notice_is_concise_and_keeps_start_gate(qtbot):
    from config.walking_config import WalkingConfig
    view = ExecutionView()
    qtbot.addWidget(view)
    view.configure(WalkingConfig())
    status = dict(ready=True, requires_acknowledgement=True, segment_count=8,
                  message='异常在阈值内', details='第7段：1/96，1.04%，10ms')
    view.on_walking_readiness(status)
    assert '异常' in view._ground_status.text()
    assert '1/96' not in view._ground_status.text()
    assert view._ground_status.toolTip() == status['details']
    assert view.btn_start.text() == '确认并开始'
    assert view.btn_start.isEnabled()
    status.update(ready=False, requires_acknowledgement=False)
    view.on_walking_readiness(status)
    assert not view.btn_start.isEnabled()
    track = view._ground_track
    assert track.detail_status.isHidden()
    assert track.legend.isHidden()
