import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from common import frame_identity
from process_delivery import receive


class FakeConnection:
    def __init__(self,message,polls=True):self.message=message;self.polls=polls
    def poll(self,timeout):return self.polls
    def recv(self):return self.message


class Protocol(unittest.TestCase):
    def test_frame_identity_covers_pixels_layout_and_source(self):
        frame=np.arange(18,dtype=np.uint8).reshape(2,3,3);meta=dict(frame_index=7,sample_time_s=1.5,encoded_sha256='x',offset=4,length=9)
        value=frame_identity(frame,meta)
        self.assertEqual(value['shape'],[2,3,3]);self.assertEqual(value['strides'],list(frame.strides))
        self.assertEqual(value['pixels_sha256'],hashlib.sha256(frame.tobytes()).hexdigest())

    def test_wrong_kind_rejected(self):
        with self.assertRaises(ValueError):receive(FakeConnection(dict(kind='other')),'ready')

    def test_timeout_retained(self):
        with self.assertRaises(TimeoutError):receive(FakeConnection({},False),'ready',0)

    def test_pose_message_requires_parent_rehash(self):
        message=dict(kind='pose',ordinal=0,pose_sha256='bad')
        self.assertEqual(receive(FakeConnection(message),'pose')['pose_sha256'],'bad')


if __name__=='__main__':unittest.main()
