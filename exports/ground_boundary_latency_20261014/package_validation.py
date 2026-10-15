"""Freeze this working tree into a separate Windows validation tree."""
import hashlib
import json
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
paths=set()
for name in ('config','engine','hardware','reporting','ui','camera','vision','voice','agent','data','tools','tests','knowledge'):
    paths.update(p for p in (ROOT/name).rglob('*.py') if '__pycache__' not in p.parts)
paths.add(ROOT/'path_utils.py')
paths.add(ROOT/'models/pose_landmarker_full.task')
paths.update(p for p in (ROOT/'camera/bin').glob('*') if p.is_file())
paths.update(p for p in (ROOT/'ui/assets').rglob('*') if p.is_file())
paths.update(p for p in OUT.glob('*.py'))
paths.update(p for p in (OUT/'before_latency').glob('*.py'))
base=ROOT/'exports/ground_mirror_fragments_20261014'
paths.add(base/'replay.py');paths.update((base/'before'/name) for name in ('walking_processor.py','beam_filter.py','overground_running_processor.py'))
for folder in ('exports/ground_field_20261009','exports/walking_field_v16_20261009','exports/ground_field_20261010_audit'):
    for mode in ('walk','run'):
        source=ROOT/folder/mode
        paths.add(source/'metadata.json')
        paths.add(source/('matched_usb.npz' if (source/'matched_usb.npz').exists() else 'raw_frames.npz'))
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
(OUT/'package_manifest.json').write_text(json.dumps(manifest,indent=2))
with zipfile.ZipFile(OUT/'validation.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(paths):archive.write(p,str(p.relative_to(ROOT)))
    archive.write(OUT/'package_manifest.json','exports/ground_boundary_latency_20261014/package_manifest.json')
print(len(paths),(OUT/'validation.zip').stat().st_size)
