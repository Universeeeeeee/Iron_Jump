"""Read-only audit of actual source/media bytes, writing only into this experiment."""
import hashlib
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = Path('E:/OptoJump/IronJump-mirror-validation-20261014-01')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def changed(root, manifest):
    return [name for name, sha in manifest.items()
            if not (root / name).is_file() or digest(root / name) != sha]


if __name__ == '__main__':
    manifest = json.loads((HERE / 'baseline_manifest.json').read_text(encoding='utf-8'))
    old_manifest = json.loads((OLD / 'exports/ground_boundary_latency_20261014/package_manifest.json').read_text())
    rollback = json.loads((OLD / 'exports/ground_boundary_latency_20261014/rollback_manifest.json').read_text())
    media = {}
    for name in ('camera.mjpg', 'camera.csv', 'raw_frames.npz'):
        rel = Path('exports/ground_boundary_latency_20261014/field_run_20261015_02') / name
        media[name] = {'original': digest(OLD / rel), 'experiment': digest(ROOT / rel)}
    result = {'experiment_source_files': len(manifest['base_files']),
              'experiment_source_changed': changed(ROOT, manifest['base_files']),
              'prior_isolated_source_changed': changed(OLD, old_manifest),
              'formal_source_changes_since_old_backup': changed(Path(rollback['original_root']), rollback['files']),
              'media': media}
    (HERE / 'windows_final_audit.json').write_text(json.dumps(result, indent=2) + '\n')
    assert not result['experiment_source_changed']
    assert not result['prior_isolated_source_changed']
    assert all(item['original'] == item['experiment'] for item in media.values())
    print(json.dumps(result, indent=2), flush=True)
