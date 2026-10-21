"""Lower-body pose overlay helpers with lazy OpenCV drawing."""

from __future__ import annotations

from .foot_reference import FootPoseSample


_CONNECTIONS = (
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("left_ankle", "left_heel"),
    ("left_heel", "left_foot_index"),
    ("left_ankle", "left_foot_index"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("right_ankle", "right_heel"),
    ("right_heel", "right_foot_index"),
    ("right_ankle", "right_foot_index"),
)


def build_pose_overlay(
    sample: FootPoseSample,
    width: int,
    height: int,
    *,
    min_quality: float = 0.65,
    mirrored: bool = False,
) -> dict:
    landmarks = {
        "left_hip": sample.left_hip,
        "left_knee": sample.left_knee,
        "left_ankle": sample.left_ankle,
        "left_heel": sample.left_heel,
        "left_foot_index": sample.left_foot_index,
        "right_hip": sample.right_hip,
        "right_knee": sample.right_knee,
        "right_ankle": sample.right_ankle,
        "right_heel": sample.right_heel,
        "right_foot_index": sample.right_foot_index,
    }
    nodes = {}
    for name, landmark in landmarks.items():
        nodes[name] = {
            "point": (
                round((1 - landmark.x if mirrored else landmark.x) * width),
                round(landmark.y * height),
            ),
            "quality": landmark.quality,
            "valid": landmark.quality >= min_quality,
            "side": "left" if name.startswith("left_") else "right",
        }
    return {"nodes": nodes, "connections": _CONNECTIONS}


def draw_pose_overlay(
    frame,
    sample: FootPoseSample | None,
    *,
    min_quality: float = 0.65,
    mirrored: bool = False,
):
    if sample is None:
        return frame

    import cv2

    height, width = frame.shape[:2]
    overlay = build_pose_overlay(
        sample,
        width,
        height,
        min_quality=min_quality,
        mirrored=mirrored,
    )
    nodes = overlay["nodes"]
    colors = {
        "left": (255, 120, 30),
        "right": (20, 165, 255),
    }
    for start_name, end_name in overlay["connections"]:
        start = nodes[start_name]
        end = nodes[end_name]
        if not start["valid"] or not end["valid"]:
            continue
        color = colors[start["side"]]
        cv2.line(frame, start["point"], end["point"], color, 3, cv2.LINE_AA)

    for node in nodes.values():
        if not node["valid"]:
            continue
        color = colors[node["side"]]
        cv2.circle(frame, node["point"], 6, color, -1, cv2.LINE_AA)
        cv2.circle(frame, node["point"], 8, (255, 255, 255), 1, cv2.LINE_AA)

    for side, ankle_name in (("L", "left_ankle"), ("R", "right_ankle")):
        ankle = nodes[ankle_name]
        if not ankle["valid"]:
            continue
        x, y = ankle["point"]
        cv2.putText(
            frame,
            side,
            (x + 10, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            colors[ankle["side"]],
            2,
            cv2.LINE_AA,
        )
    return frame
