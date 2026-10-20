from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from proxy import digest,frame_identity,payload_pose,pose_payload


@dataclass(frozen=True)
class Point:
    x:float;y:float;z:float;visibility:float;presence:float


@dataclass(frozen=True)
class Pose:
    timestamp_s:float;left_hip:Point;left_knee:Point;left_ankle:Point;left_heel:Point;left_foot_index:Point
    right_hip:Point;right_knee:Point;right_ankle:Point;right_heel:Point;right_foot_index:Point;landmarks_33:tuple;identity_reject_reason:object=None


class ProxyTests(unittest.TestCase):
    def test_frame_identity_covers_ordinal_source_layout_and_pixels(self):
        frame=np.arange(18,dtype=np.uint8).reshape(2,3,3);row=dict(capture_frame_index='7',sample_time='1.5',encoded_sha256='x',offset='4',length='9')
        value=frame_identity(frame,row,11)
        self.assertEqual((value['ordinal'],value['frame_index'],value['shape']),(11,7,[2,3,3]))
        self.assertEqual(value['pixels_sha256'],hashlib.sha256(frame.tobytes()).hexdigest())

    def test_pose_crosses_as_plain_values_and_reconstructs_current_time(self):
        point=Point(1,2,3,.9,.8);pose=Pose(5,*(point,)*10,(point,))
        payload=pose_payload(pose);before=digest(payload);result=payload_pose(payload,9)
        self.assertEqual(result.timestamp_s,9);self.assertEqual(result.left_hip.x,1);self.assertEqual(digest(payload),before)

    def test_none_pose_round_trip(self):
        self.assertIsNone(pose_payload(None));self.assertIsNone(payload_pose(None,1))


if __name__=='__main__':unittest.main()
