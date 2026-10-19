import unittest
from readiness_review03 import unique_frames

class IdentityTests(unittest.TestCase):
    def test_duplicate_identity_rejected(self):
        r=dict(frame=1,sample_time_s=2.,wall_ms=3.)
        with self.assertRaises(ValueError):unique_frames([r,r])
    def test_timestamp_is_part_of_identity(self):
        self.assertEqual(len(unique_frames([dict(frame=1,sample_time_s=t,wall_ms=3.) for t in (2.,4.)])),2)
