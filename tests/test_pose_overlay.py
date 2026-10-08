import unittest

from vision.foot_reference import FootPoseSample, Landmark
from vision.pose_overlay import build_pose_overlay


def _point(x: float, y: float, quality: float = 0.99) -> Landmark:
    return Landmark(x, y, 0.0, quality, quality)


class PoseOverlayTests(unittest.TestCase):
    def test_builds_named_left_and_right_lower_body_nodes(self):
        sample = FootPoseSample(
            1.0,
            _point(0.30, 0.20),
            _point(0.30, 0.40),
            _point(0.30, 0.60),
            _point(0.28, 0.65),
            _point(0.34, 0.66),
            _point(0.70, 0.20),
            _point(0.70, 0.40),
            _point(0.70, 0.60),
            _point(0.68, 0.65),
            _point(0.74, 0.66),
        )

        overlay = build_pose_overlay(sample, width=1000, height=500)

        self.assertEqual(overlay["nodes"]["left_ankle"]["point"], (300, 300))
        self.assertEqual(overlay["nodes"]["right_foot_index"]["point"], (740, 330))
        self.assertIn(("left_hip", "left_knee"), overlay["connections"])
        self.assertIn(("right_heel", "right_foot_index"), overlay["connections"])

    def test_low_quality_nodes_remain_visible_as_invalid(self):
        low = _point(0.5, 0.5, quality=0.2)
        sample = FootPoseSample(1.0, low, low, low, low, low, low, low, low, low, low)

        overlay = build_pose_overlay(sample, width=100, height=100)

        self.assertFalse(overlay["nodes"]["left_ankle"]["valid"])


if __name__ == "__main__":
    unittest.main()


def test_unreliable_pose_does_not_leave_dots_or_side_labels():
    import numpy as np
    from tests.test_leg_identity import _sample
    from vision.pose_overlay import draw_pose_overlay
    frame = np.zeros((500, 600, 3), dtype=np.uint8)
    draw_pose_overlay(frame, _sample(1, quality=.4))
    assert not frame.any()


def test_reliable_pose_draws_connected_leg_bones():
    import numpy as np
    from tests.test_leg_identity import _sample
    from vision.pose_overlay import draw_pose_overlay
    frame = np.zeros((500, 600, 3), dtype=np.uint8)
    draw_pose_overlay(frame, _sample(1))
    # Midpoints between hip/knee and knee/ankle must contain colored lines.
    for x in (210, 390):
        assert frame[212, x].any()
        assert frame[337, x].any()
