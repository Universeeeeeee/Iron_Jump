"""Lazy MediaPipe Tasks Pose Landmarker adapter for VIDEO mode."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable

import numpy as np

from .foot_reference import FootPoseSample, Landmark


class VisionUnavailableError(RuntimeError):
    """Raised when the optional model runtime cannot be opened."""


class VisionInferenceError(RuntimeError):
    """Raised when an opened model cannot process a frame."""


class MediaPipePoseAdapter:
    def __init__(
        self,
        model_path: str | Path,
        *,
        module_loader: Callable[[], object] | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self._module_loader = module_loader or self._load_mediapipe
        self._mp = None
        self._landmarker = None
        self._last_timestamp_ms: int | None = None

    @property
    def is_open(self) -> bool:
        return self._landmarker is not None

    @property
    def last_timestamp_ms(self) -> int | None:
        return self._last_timestamp_ms

    def open(self) -> None:
        if self._landmarker is not None:
            return
        if not self.model_path.is_file():
            raise VisionUnavailableError(
                f"MediaPipe model file not found: {self.model_path}"
            )
        try:
            mp = self._module_loader()
        except Exception as exc:
            raise VisionUnavailableError(
                "MediaPipe is not installed or could not be imported"
            ) from exc

        try:
            base_options_values = {
                "model_asset_path": str(self.model_path),
            }
            delegate_type = getattr(mp.tasks.BaseOptions, "Delegate", None)
            cpu_delegate = getattr(delegate_type, "CPU", None)
            if cpu_delegate is not None:
                base_options_values["delegate"] = cpu_delegate
            options = mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(**base_options_values),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_poses=1,
                output_segmentation_masks=False,
            )
            landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        except Exception as exc:
            raise VisionUnavailableError(
                f"Could not create MediaPipe Pose Landmarker: {exc}"
            ) from exc

        self._mp = mp
        self._landmarker = landmarker
        self._last_timestamp_ms = None

    def infer_bgr(
        self, frame: np.ndarray, timestamp_ms: int
    ) -> FootPoseSample | None:
        if self._landmarker is None or self._mp is None:
            raise VisionUnavailableError("MediaPipe Pose Landmarker is not open")
        if (
            self._last_timestamp_ms is not None
            and timestamp_ms <= self._last_timestamp_ms
        ):
            raise ValueError("VIDEO timestamps must be strictly increasing")
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a BGR uint8 image with three channels")

        rgb = np.ascontiguousarray(frame[..., ::-1])
        try:
            image = self._mp.Image(
                image_format=self._mp.ImageFormat.SRGB,
                data=rgb,
            )
            self._last_timestamp_ms = timestamp_ms
            result = self._landmarker.detect_for_video(image, timestamp_ms)
        except Exception as exc:
            raise VisionInferenceError(f"MediaPipe inference failed: {exc}") from exc

        if not result.pose_landmarks:
            return None
        points = result.pose_landmarks[0]
        if len(points) < 33:
            return None
        all_landmarks = tuple(_landmark(point) for point in points[:33])
        return FootPoseSample(
            timestamp_s=timestamp_ms / 1000.0,
            left_hip=_landmark(points[23]),
            left_knee=_landmark(points[25]),
            left_ankle=_landmark(points[27]),
            left_heel=_landmark(points[29]),
            left_foot_index=_landmark(points[31]),
            right_hip=_landmark(points[24]),
            right_knee=_landmark(points[26]),
            right_ankle=_landmark(points[28]),
            right_heel=_landmark(points[30]),
            right_foot_index=_landmark(points[32]),
            landmarks_33=all_landmarks,
        )

    def close(self) -> None:
        landmarker = self._landmarker
        self._landmarker = None
        self._mp = None
        self._last_timestamp_ms = None
        if landmarker is not None:
            landmarker.close()

    @staticmethod
    def _load_mediapipe():
        return importlib.import_module("mediapipe")


def _landmark(point) -> Landmark:
    visibility = getattr(point, "visibility", 0.0)
    presence = getattr(point, "presence", visibility)
    return Landmark(
        x=float(point.x),
        y=float(point.y),
        z=float(point.z),
        visibility=float(visibility if visibility is not None else 0.0),
        presence=float(presence if presence is not None else 0.0),
    )
