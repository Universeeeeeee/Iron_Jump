"""Typed walking reports and raw exports, verified before GUI delivery."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import numpy as np
from data.subject_store import _report_detail, _report_from_detail

MAX_ARTIFACT_BYTES = 128 * 1024 * 1024


def reference(path):
    size = path.stat().st_size
    if not 0 < size <= MAX_ARTIFACT_BYTES:
        raise ValueError('Measurement artifact exceeds its size bound')
    return dict(file=path.name, bytes=size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def verified_bytes(folder, value, name):
    if value.get('file') != name or type(value.get('bytes')) is not int:
        raise ValueError('Invalid measurement artifact reference')
    size = value['bytes']
    if not 0 < size <= MAX_ARTIFACT_BYTES:
        raise ValueError('Measurement artifact exceeds its size bound')
    path = folder / name
    if path.stat().st_size != size:
        raise ValueError('Measurement artifact size changed')
    with path.open('rb') as stream:
        data = stream.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != value.get('sha256'):
        raise ValueError('Measurement artifact integrity failure')
    return data


def save_report(folder, report):
    detail = _report_detail(report)
    (folder / 'report.json').write_text(json.dumps(detail, ensure_ascii=False), encoding='utf-8')
    frames = np.array([np.frombuffer(bytes(frame), np.uint8) for frame in report.export_frames], dtype=np.uint8)
    np.savez_compressed(folder / 'exports.npz', frames=frames,
                        timestamps=np.asarray(report.export_timestamps, dtype=np.float64))
    return dict(report=reference(folder / 'report.json'), exports=reference(folder / 'exports.npz'))


def load_report(folder, value):
    import io
    report = _report_from_detail(json.loads(verified_bytes(folder, value['report'], 'report.json')))
    with np.load(io.BytesIO(verified_bytes(folder, value['exports'], 'exports.npz')), allow_pickle=False) as exports:
        frames = exports['frames']
        timestamps = exports['timestamps']
        if frames.dtype != np.uint8 or timestamps.ndim != 1 or len(frames) != len(timestamps):
            raise ValueError('Invalid measurement raw exports')
        if frames.size and (frames.ndim != 2 or not np.all((frames == 0) | (frames == 1))):
            raise ValueError('Invalid measurement frame bits')
        return replace(report, export_frames=tuple(frame.tobytes() for frame in frames),
                       export_timestamps=tuple(float(stamp) for stamp in timestamps))
