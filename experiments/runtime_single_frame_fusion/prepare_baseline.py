"""Reconstruct the previously exercised source, without editing the source checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(source):
    marker = HERE / 'baseline_manifest.json'
    if marker.exists():
        raise FileExistsError('Baseline already reconstructed; verify it instead of overwriting')
    archive = source / 'exports/ground_boundary_latency_20261014/validation.zip'
    with zipfile.ZipFile(archive) as z:
        z.extractall(ROOT)
    old = source / 'exports/canvas_latency_20261015'
    package = json.loads((ROOT / 'exports/ground_boundary_latency_20261014/package_manifest.json').read_text())
    assert all(digest(ROOT / name) == sha for name, sha in package.items())
    overlays = {
        'hardware/walking_preflight.py': 'runtime_baseline/hardware/walking_preflight.py',
        'hardware/beam_filter.py': 'filter_candidate/hardware/beam_filter.py',
        'engine/modes/overground_running_processor.py': 'pipeline_candidate/engine/modes/overground_running_processor.py',
        'ui/annotation_canvas.py': 'candidate/ui/annotation_canvas.py',
        'ui/embedded_camera_panel.py': 'candidate/ui/embedded_camera_panel.py',
    }
    for target, origin in overlays.items():
        shutil.copy2(old / origin, ROOT / target)
    # All code is materialized at its ordinary module path; no hidden patch loader.
    baseline = {name: digest(ROOT / name) for name in package}
    for name in overlays:
        baseline[name] = digest(ROOT / name)
    extras = [source / 'config/Iron_parameters.json']
    extras += list((source / 'led_con_package_8m_0918/hardware').glob('*.py'))
    for origin in extras:
        relative = origin.relative_to(source)
        (ROOT / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, ROOT / relative)
        baseline[str(relative)] = digest(ROOT / relative)
    for name in ('fixed_replay.py', 'fixed_geometry_cache.py', 'full_report_oracle.json', 'local_oracle.json'):
        shutil.copy2(old / name, HERE / name)
    for name in ('field_run_20261015_02', 'field_walk_full_02'):
        destination = ROOT / 'exports/ground_boundary_latency_20261014' / name
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ('raw_frames.npz', 'report.json', 'timing.json', 'camera_record_start.json'):
            shutil.copy2(source / 'exports/ground_boundary_latency_20261014' / name / filename,
                         destination / filename)
    result = {'archive_sha256': digest(archive), 'source_root': str(source),
              'base_files': baseline, 'overlays': overlays,
              'experiment_support': {name: digest(HERE / name) for name in
                                     ('fixed_replay.py', 'fixed_geometry_cache.py', 'full_report_oracle.json', 'local_oracle.json')},
              'status': 'materialized_sources; A/A execution verification pending'}
    marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Materialized baseline:', len(baseline), 'files')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    main(parser.parse_args().source_root)
