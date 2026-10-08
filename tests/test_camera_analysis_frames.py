import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _class_node(path: Path, class_name: str) -> ast.ClassDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    text = path.read_text(encoding="utf-8")
    node = _class_node(path, class_name)
    method = next(
        item
        for item in node.body
        if isinstance(item, ast.FunctionDef) and item.name == method_name
    )
    return ast.get_source_segment(text, method) or ""


class CameraAnalysisFrameContractTests(unittest.TestCase):
    def test_both_capture_classes_keep_preview_signal_and_add_analysis_signal(self):
        cases = [
            (ROOT / "camera/logi_camera.py", "CameraCapture"),
            (ROOT / "camera/tinyse_camera.py", "TinySeCameraCapture"),
        ]

        for path, class_name in cases:
            with self.subTest(class_name=class_name):
                node = _class_node(path, class_name)
                assignments = {
                    target.id
                    for item in node.body
                    if isinstance(item, ast.Assign)
                    for target in item.targets
                    if isinstance(target, ast.Name)
                }
                self.assertIn("frame_ready", assignments)
                self.assertIn("analysis_frame_ready", assignments)
                if class_name == "TinySeCameraCapture":
                    self.assertIn("analysis_frame_timed_ready", assignments)

    def test_logitech_emits_unmirrored_analysis_frame_before_flip(self):
        source = _method_source(
            ROOT / "camera/logi_camera.py", "CameraCapture", "_loop"
        )

        analysis_position = source.index("analysis_frame_ready.emit")
        flip_position = source.index("cv2.flip")

        self.assertLess(analysis_position, flip_position)
        self.assertIn("captured_at_s = time.perf_counter()", source)

    def test_tinyse_emits_decoded_analysis_frame_before_optional_flip(self):
        source = _method_source(
            ROOT / "camera/tinyse_camera.py",
            "TinySeCameraCapture",
            "_decode_preview_frame",
        )

        decode_position = source.index("cv2.imdecode")
        analysis_position = source.index("analysis_frame_ready.emit")
        flip_position = source.index("cv2.flip")

        self.assertLess(decode_position, analysis_position)
        self.assertLess(analysis_position, flip_position)
        self.assertIn("decoded_at_s = time.perf_counter()", source)
        self.assertIn("analysis_frame_timed_ready.emit", source)


if __name__ == "__main__":
    unittest.main()
