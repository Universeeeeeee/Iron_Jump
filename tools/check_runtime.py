"""Read-only core runtime preflight; does not open hardware or contact APIs."""

import importlib
import platform
import sys


def main():
    print(f"Python {platform.python_version()} / {platform.system()}")
    failed = sys.version_info < (3, 11)
    if failed:
        print("FAIL: Python 3.11 or newer is required")
    for name in ("qtpy.QtWidgets", "dayu_widgets", "numpy", "cv2", "pyqtgraph", "openpyxl", "pydantic", "dotenv", "requests"):
        try:
            importlib.import_module(name)
            print(f"OK: {name}")
        except Exception as error:
            print(f"FAIL: {name} ({type(error).__name__})")
            failed = True
    if platform.system() != "Windows":
        print("USB acquisition requires Windows + CyUsbInterface.dll; use python -m ui.demo for simulation.")
    print("This check does not verify cloud keys, audio devices or USB hardware.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
