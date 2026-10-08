from dataclasses import replace

import pytest

from tests.test_leg_identity import _sample
from vision.framing import check_framing


LANDMARKS = tuple(f"{side}_{part}" for side in ("left", "right")
                  for part in ("hip", "knee", "ankle", "heel", "foot_index"))


def test_complete_fresh_lower_body_passes():
    result = check_framing(_sample(1.0), now_s=1.1)
    assert result.ready
    assert result.problem_points == ()
    assert "完整可见" in result.message


@pytest.mark.parametrize("name", LANDMARKS)
@pytest.mark.parametrize("change", [{"x": -0.01}, {"y": 1.01},
                                    {"visibility": .64}, {"presence": .64}])
def test_each_required_point_is_checked(name, change):
    pose = _sample(1.0)
    pose = replace(pose, **{name: replace(getattr(pose, name), **change)})
    result = check_framing(pose, now_s=1.1)
    assert not result.ready
    assert result.problem_points == (name,)
    assert "调整机位或避免遮挡" in result.message


@pytest.mark.parametrize("field", ["x", "y", "visibility", "presence"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_landmarks_never_pass(field, value):
    pose = _sample(1.0)
    pose = replace(pose, left_heel=replace(pose.left_heel, **{field: value}))
    assert not check_framing(pose, now_s=1.1).ready


@pytest.mark.parametrize("timestamp", [0.0, 2.0, float("nan")])
def test_stale_future_and_invalid_pose_timestamps_never_pass(timestamp):
    result = check_framing(_sample(timestamp), now_s=1.1)
    assert not result.ready
    assert result.reason == "stale_pose"


def test_missing_pose_and_threshold_boundary():
    assert check_framing(None, now_s=1.1).reason == "no_pose"
    pose = _sample(1.0, quality=.65)
    assert check_framing(pose, now_s=1.1).ready
    assert not check_framing(pose, now_s=1.1, min_quality=.7).ready


def test_live_preview_reports_foot_visibility_and_clears_old_success():
    from tests.test_live_walking_vision import Service
    from vision.live_walking import LiveWalkingVision
    from vision.service import PoseInferenceRecord

    now = [1.1]
    live = LiveWalkingVision(service_factory=Service, clock=lambda: now[0])
    def emit(pose):
        live._service.pose_inference_ready.emit(PoseInferenceRecord(now[0], now[0], now[0], pose))
    emit(_sample(1.1))
    assert "完整可见" in live.display_state()[1]
    pose = _sample(1.1)
    emit(replace(pose, right_foot_index=replace(pose.right_foot_index, visibility=.2)))
    assert "右脚尖" in live.display_state()[1]
    assert "当前下肢完整可见" not in live.display_state()[1]
    emit(_sample(1.1))
    now[0] = 2.0
    assert "当前下肢完整可见" not in live.display_state()[1]
    emit(None)
    assert "进入画面" in live.display_state()[1]


def test_prepared_camera_panel_displays_framing_without_starting_acquisition(qtbot):
    from tests.test_live_walking_vision import Service
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    from vision.live_walking import LiveWalkingVision
    from vision.service import PoseInferenceRecord

    panel = EmbeddedCameraPanel()
    qtbot.addWidget(panel)
    panel.set_vision_enabled(True)
    panel._vision = LiveWalkingVision(service_factory=Service, clock=lambda: 1.1)
    pose = _sample(1.1)
    pose = replace(pose, left_heel=replace(pose.left_heel, x=-.1))
    panel._vision._service.pose_inference_ready.emit(PoseInferenceRecord(1.1, 1.1, 1.1, pose))
    panel._show_latest_frame()
    assert "左脚跟" in panel._vision_label.text()
    assert "调整机位" in panel._vision_label.text()
    assert not panel._vision_label.isHidden()
    assert panel._capture is None
    panel.shutdown()
