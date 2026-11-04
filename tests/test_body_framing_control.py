from dataclasses import replace
from types import SimpleNamespace

import pytest

from vision.foot_reference import Landmark
from vision.gimbal_tracking import body_framing, framing_velocity, tracking_velocity


def body(top=.1, bottom=.9):
    points = [Landmark(.5, .5, 0, .9, .9)] * 33
    points[0] = replace(points[0], y=top)
    for index in (27, 28, 29, 30, 31, 32):
        points[index] = replace(points[index], y=bottom)
    return SimpleNamespace(landmarks_33=tuple(points))


def test_margin_risk_can_require_pitch_when_center_is_inside_deadzone():
    framing = body_framing(body(.01, .91))
    assert tracking_velocity(framing.target) == (0, 0)
    assert framing_velocity(framing) == pytest.approx((-3.2, 0))
    assert not framing.points_with_margin
    assert not framing.fits_with_margin


def test_full_body_with_headroom_lowers_view_to_leave_floor_margin():
    framing = body_framing(body())
    assert framing_velocity(framing) == pytest.approx((1.6, 0))
    assert framing.points_with_margin and framing.fits_with_margin


def test_reliable_center_does_not_imply_head_or_foot_tips_visible():
    pose = body()
    points = list(pose.landmarks_33)
    for index in (0, 29, 30, 31, 32):
        points[index] = replace(points[index], visibility=.2)
    pose.landmarks_33 = tuple(points)
    framing = body_framing(pose)
    assert framing is not None
    assert not framing.head_landmark_visible
    assert not framing.foot_tips_visible and not framing.points_with_margin


def test_body_too_large_is_reported_without_lowering_quality_or_zooming():
    framing = body_framing(body(.01, .99))
    assert not framing.fits_with_margin
    assert framing_velocity(framing) == (0, 0)


def test_floor_margin_stops_lowering_when_feet_have_room():
    assert framing_velocity(body_framing(body(.08, .88))) == (0, 0)

def test_floor_margin_never_lowers_without_headroom_or_pose():
    assert framing_velocity(None) == (0, 0)
    assert framing_velocity(body_framing(body(.05, .90)))[0] <= 0
