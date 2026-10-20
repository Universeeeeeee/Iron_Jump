"""Shared strict media/pose identity helpers for the saved-input delivery gate."""
from dataclasses import asdict
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pose_payload(pose):
    return None if pose is None else pose if isinstance(pose,dict) else asdict(pose)


def canonical_pose(pose):
    value=pose_payload(pose)
    data=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


class Media:
    def __init__(self,folder,expected):
        self.folder=Path(folder)
        assert sha(self.folder/'camera.csv')==expected['camera.csv']
        assert sha(self.folder/'camera.mjpg')==expected['camera.mjpg']
        with (self.folder/'camera.csv').open(newline='') as f:
            rows=list(csv.DictReader(f))
        offsets=[int(v['offset']) for v in rows];lengths=[int(v['length']) for v in rows]
        assert offsets and offsets[0]==0
        assert all(b==a+n for a,n,b in zip(offsets,lengths,offsets[1:]))
        self.rows={int(v['capture_frame_index']):v for v in rows}
        self.source=None

    def __enter__(self):
        self.source=(self.folder/'camera.mjpg').open('rb');return self

    def __exit__(self,*args):
        self.source.close();self.source=None

    def decode(self,frame_id):
        import cv2
        row=self.rows[frame_id]
        self.source.seek(int(row['offset']));data=self.source.read(int(row['length']))
        assert len(data)==int(row['length'])
        frame=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
        if frame is None:raise RuntimeError('Archived JPEG decode failed')
        return frame,dict(frame_index=frame_id,sample_time_s=float(row['sample_time']),
            encoded_sha256=hashlib.sha256(data).hexdigest(),offset=int(row['offset']),length=int(row['length']))


def frame_identity(frame,meta):
    return dict(**meta,shape=list(frame.shape),dtype=str(frame.dtype),strides=list(frame.strides),
        pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest())


def preview_identity(frame,meta,ordinal):
    value=frame_identity(frame,meta);value['ordinal']=ordinal;return value
