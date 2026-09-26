from __future__ import annotations

import importlib
import sys
from collections import deque

import pytest


def test_import_is_lazy_and_does_not_load_qt_opencv_or_mediapipe():
    sys.modules.pop("tools.mac_mediapipe_validator", None)
    before = set(sys.modules)

    importlib.import_module("tools.mac_mediapipe_validator")

    loaded = set(sys.modules) - before
    assert not any(name == "qtpy" or name.startswith("qtpy.") for name in loaded)
    assert "cv2" not in loaded
    assert "mediapipe" not in loaded


def test_parser_has_no_recording_or_csv_output_options():
    module = importlib.import_module("tools.mac_mediapipe_validator")
    args = module.build_parser().parse_args(["--model", "pose.task"])

    assert args.camera_index == 0
    assert args.inference_interval_ms == 50
    assert not hasattr(args, "output")
    assert not hasattr(args, "record")


def test_stream_fps_uses_real_timestamps():
    module = importlib.import_module("tools.mac_mediapipe_validator")

    assert module.stream_fps(deque()) == 0.0
    assert module.stream_fps(deque([1.0, 1.1, 1.2])) == pytest.approx(10.0)


def test_macos_validator_rejects_unverified_mediapipe_before_native_startup():
    module = importlib.import_module("tools.mac_mediapipe_validator")

    module.validate_macos_mediapipe_version("0.10.35")
    with pytest.raises(RuntimeError, match="mediapipe==0.10.35"):
        module.validate_macos_mediapipe_version("1.0.1")
