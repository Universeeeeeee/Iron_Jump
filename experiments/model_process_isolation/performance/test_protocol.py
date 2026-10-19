import unittest
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from model_process import receive

class Fake:
    def __init__(self,message,ready=True):self.message=message;self.ready=ready
    def poll(self,timeout):return self.ready
    def recv(self):return self.message

class Protocol(unittest.TestCase):
    def test_pose_identity(self):self.assertEqual(receive(Fake(dict(kind='pose',ordinal=2,pose=None)),'pose',2)['pose'],None)
    def test_wrong_ordinal(self):
        with self.assertRaises(ValueError):receive(Fake(dict(kind='pose',ordinal=1)),'pose',2)
    def test_error_not_success(self):
        with self.assertRaises(ValueError):receive(Fake(dict(kind='error',error='model failed')),'ready')
    def test_observation_timeout_not_success(self):
        with self.assertRaises(TimeoutError):receive(Fake({},False),'ready')
