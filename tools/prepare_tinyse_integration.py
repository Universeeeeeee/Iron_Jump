"""Freeze vae's current Python sources plus isolated control changes for review."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


OVERRIDES = (
    'camera/control_service.py', 'camera/gimbal_control.py', 'camera/pose_tracking.py',
    'camera/pose_transport.py', 'camera/tracking_runtime.py', 'vision/gimbal_tracking.py',
    'ui/embedded_camera_panel.py', 'tools/tinyse_gimbal_validator.py',
    'tests/test_pose_tracking.py', 'tests/test_tracking_runtime.py',
    'tests/test_gimbal_tracking.py', 'tests/test_camera_control_service.py',
    'tests/test_sdk_tracking_integration.py',
    'tests/test_body_framing_control.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve()
    control = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if output.exists():
        parser.error('output must be a new directory')
    output.mkdir(parents=True)
    manifest = {}
    for source in baseline.iterdir():
        if source.name.startswith('.'):
            continue
        target = output / source.name
        if source.name in {'camera', 'vision', 'ui', 'tests', 'tools'}:
            # Freeze Python code; non-code SDK/assets/evidence remain read-only
            # references to their actual source directory in this local view.
            for child in source.rglob('*'):
                if child.suffix != '.py' or '__pycache__' in child.parts:
                    continue
                name = child.relative_to(baseline).as_posix()
                destination = output / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(child, destination)
                manifest[name] = {'source': str(child), 'sha256': hashlib.sha256(child.read_bytes()).hexdigest()}
            for child in source.iterdir():
                destination = target / child.name
                if not destination.exists() and child.name != '__pycache__':
                    destination.symlink_to(child, target_is_directory=child.is_dir())
        else:
            target.symlink_to(source, target_is_directory=source.is_dir())
    for name in OVERRIDES:
        source, target = control / name, output / name
        if target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        manifest[name] = {'source': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    binary_folder = output / 'camera/bin'
    if binary_folder.is_symlink():
        binary_folder.unlink()
    binary_folder.mkdir(exist_ok=True)
    for source in (baseline / 'camera/bin').iterdir():
        target = binary_folder / source.name
        if not target.exists():
            target.symlink_to(source, target_is_directory=source.is_dir())
    name = 'camera/bin/obsbot_c_api.dll'
    target = output / name
    if target.is_symlink():
        target.unlink()
    shutil.copyfile(control / name, target)
    manifest[name] = {'source': str(control / name), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    (output / 'control-manifest.json').write_text(json.dumps(manifest, indent=2))
    print(output)


if __name__ == '__main__':
    main()
