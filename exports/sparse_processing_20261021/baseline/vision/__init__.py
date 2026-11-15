"""Independent visual foot-reference package."""

from .foot_reference import (
    FootLabel,
    VisionConfig,
    VisionDecision,
    VisionWindowDiagnostics,
)
from .time_sync import CameraClockSynchronizer, ClockSyncSnapshot, ClockSyncStatus


def __getattr__(name):
    if name in {"FootVisionService", "PoseInferenceRecord"}:
        from .service import FootVisionService, PoseInferenceRecord

        return {"FootVisionService": FootVisionService, "PoseInferenceRecord": PoseInferenceRecord}[name]
    if name in {"VisionInferenceError", "VisionUnavailableError"}:
        from .mediapipe_pose import VisionInferenceError, VisionUnavailableError

        return {"VisionInferenceError": VisionInferenceError, "VisionUnavailableError": VisionUnavailableError}[name]
    if name in {"VisionSessionRecorder", "NullVisionSessionRecorder"}:
        from .session import NullVisionSessionRecorder, VisionSessionRecorder

        return {
            "VisionSessionRecorder": VisionSessionRecorder,
            "NullVisionSessionRecorder": NullVisionSessionRecorder,
        }[name]
    raise AttributeError(name)

__all__ = [
    "FootLabel",
    "FootVisionService",
    "CameraClockSynchronizer",
    "ClockSyncSnapshot",
    "ClockSyncStatus",
    "VisionConfig",
    "VisionDecision",
    "VisionWindowDiagnostics",
    "VisionInferenceError",
    "VisionUnavailableError",
]
