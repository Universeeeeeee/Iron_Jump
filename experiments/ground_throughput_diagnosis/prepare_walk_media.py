"""Losslessly demux the existing archived MJPEG AVI; never re-encode images."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = Path('E:/OptoJump/IronJump-mirror-validation-20261014-01/camera/recordings/tinyse_20261014_231141.avi')
DEST = ROOT / 'exports/ground_boundary_latency_20261014/field_walk_full_02'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


if __name__ == '__main__':
    target = DEST / 'camera.mjpg'
    assert not target.exists(), 'Refuse to overwrite retained media'
    shutil.copy2(SOURCE, DEST / 'camera_original.avi')
    time_source = SOURCE.with_suffix('.timestamps.npy')
    shutil.copy2(time_source, DEST / 'camera_original.timestamps.npy')
    times = np.load(time_source, allow_pickle=False)
    cap = cv2.VideoCapture(str(SOURCE), cv2.CAP_FFMPEG)
    assert cap.isOpened() and cap.set(cv2.CAP_PROP_FORMAT, -1)
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    assert len(times) == count
    rows = []
    with target.open('xb') as stream:
        for index, timestamp in enumerate(times):
            ok, raw = cap.read()
            assert ok
            encoded = raw.tobytes()
            assert encoded[:2] == b'\xff\xd8' and encoded[-2:] == b'\xff\xd9'
            image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            assert image is not None
            rows.append({'record_elapsed_seconds': float(timestamp), 'offset': stream.tell(),
                         'length': len(encoded), 'capture_frame_index': index,
                         'sample_time': float(timestamp)})
            stream.write(encoded)
    cap.release()
    with (DEST / 'camera.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {'source': str(SOURCE), 'source_sha256': sha(SOURCE),
              'source_times_sha256': sha(time_source), 'copied_avi_sha256': sha(DEST / 'camera_original.avi'),
              'mjpg_sha256': sha(target), 'csv_sha256': sha(DEST / 'camera.csv'),
              'frames': len(rows), 'duration_seconds': float(times[-1]),
              'format': 'Lossless demux of stored MJPEG packets, no additional JPEG encoding',
              'limitation': 'Original raw JPEG recording was removed by historical AVI conversion. Timestamps are relative to first archived video frame; exact record-start to first-frame offset is unavailable. All paired runs use this identical archive.'}
    assert result['source_sha256'] == result['copied_avi_sha256']
    (HERE / 'walk_media.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
