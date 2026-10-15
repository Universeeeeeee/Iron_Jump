"""Read-only source/media audit; writes solely inside this experiment."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = Path('E:/OptoJump/IronJump-runtime-fusion-20261015')
ARCHIVE = Path('E:/OptoJump/IronJump-mirror-validation-20261014-01')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def changes(root, manifest):
    return [name for name, digest in manifest.items() if not (root / name).is_file() or sha(root / name) != digest]


if __name__ == '__main__':
    baseline = json.loads((ROOT / 'experiments/runtime_single_frame_fusion/baseline_manifest.json').read_text())['base_files']
    old_manifest = json.loads((ARCHIVE / 'exports/ground_boundary_latency_20261014/package_manifest.json').read_text())
    rollback = json.loads((ARCHIVE / 'exports/ground_boundary_latency_20261014/rollback_manifest.json').read_text())
    media = {}
    for filename in ('camera.mjpg', 'camera.csv', 'raw_frames.npz'):
        rel = Path('exports/ground_boundary_latency_20261014/field_run_20261015_02') / filename
        media[str(rel)] = {'original': sha(PRIOR / rel), 'diagnosis': sha(ROOT / rel)}
    walk_source = ARCHIVE / 'camera/recordings/tinyse_20261014_231141.avi'
    walk_dest = ROOT / 'exports/ground_boundary_latency_20261014/field_walk_full_02/camera_original.avi'
    media['walking_archived_avi'] = {'original': sha(walk_source), 'diagnosis': sha(walk_dest)}
    result = {'baseline_files': len(baseline), 'diagnostic_baseline_changes': changes(ROOT, baseline),
              'previous_experiment_changes': changes(PRIOR, baseline),
              'old_isolated_archive_changes': changes(ARCHIVE, old_manifest),
              'formal_changes_since_prior_backup': changes(Path(rollback['original_root']), rollback['files']),
              'media': media, 'profiler_executable_sha256': sha(HERE / 'tools/py-spy.exe'),
              'experiment_python_sources': {p.name: sha(p) for p in sorted(HERE.glob('*.py'))}}
    (HERE / 'windows_final_audit.json').write_text(json.dumps(result, indent=2) + '\n')
    assert not result['diagnostic_baseline_changes']
    assert not result['previous_experiment_changes']
    assert not result['old_isolated_archive_changes']
    assert all(v['original'] == v['diagnosis'] for v in media.values())
    print(json.dumps(result, indent=2), flush=True)
