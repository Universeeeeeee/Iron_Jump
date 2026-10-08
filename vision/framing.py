"""Advisory lower-body framing check; independent of event classification."""

from dataclasses import dataclass
import math

from .foot_reference import FootPoseSample, VisionConfig


_POINT_NAMES = {
    f"{side}_{part}": side_label + part_label
    for side, side_label in (("left", "左"), ("right", "右"))
    for part, part_label in (("hip", "髋"), ("knee", "膝"), ("ankle", "踝"),
                             ("heel", "脚跟"), ("foot_index", "脚尖"))
}


@dataclass(frozen=True)
class FramingCheck:
    ready: bool
    reason: str
    problem_points: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if self.ready:
            return "入镜检查：当前下肢完整可见"
        if self.reason == "no_pose":
            return "入镜检查：请让髋部、双膝、双踝、脚跟和脚尖完整进入画面"
        if self.reason == "stale_pose":
            return "入镜检查：等待最新姿态，请保持下肢完整可见"
        points = "、".join(_POINT_NAMES[name] for name in self.problem_points)
        return f"入镜检查：{points}未清晰入镜，请调整机位或避免遮挡"


def check_framing(
    pose: FootPoseSample | None, *, now_s: float,
    min_quality: float = VisionConfig().min_landmark_quality,
) -> FramingCheck:
    """Require all ten points in the image with fresh, finite pose evidence.

    Reuses the live overlay's 250 ms freshness bound and existing model quality
    threshold. Passing describes this frame, not identity or measurement accuracy.
    """
    if pose is None:
        return FramingCheck(False, "no_pose")
    if not 0 <= now_s - pose.timestamp_s <= .25:
        return FramingCheck(False, "stale_pose")
    problems = []
    for name in _POINT_NAMES:
        point = getattr(pose, name)
        if (not all(math.isfinite(value) for value in
                    (point.x, point.y, point.visibility, point.presence))
                or not 0 <= point.x <= 1 or not 0 <= point.y <= 1
                or not min_quality <= point.visibility <= 1
                or not min_quality <= point.presence <= 1):
            problems.append(name)
    return FramingCheck(not problems, "ready" if not problems else "landmarks_not_visible",
                        tuple(problems))
