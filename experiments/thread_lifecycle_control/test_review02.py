import unittest
from review02 import unexpected_shapes

class EventClasses(unittest.TestCase):
    def test_cpu_sample_rejected(self):self.assertTrue(unexpected_shapes({'ce1dbfb4-x/46/v2/len16':1}))
    def test_stack_rejected(self):self.assertTrue(unexpected_shapes({'def2fe46-x/32/v2/len32':1}))
    def test_switch_rejected(self):self.assertTrue(unexpected_shapes({'3d6fa8d1-x/36/v5/len28':1}))
    def test_unknown_perfinfo_rejected(self):self.assertTrue(unexpected_shapes({'ce1dbfb4-x/99/v0/len8':1}))
    def test_known_mark_shape_allowed(self):self.assertFalse(unexpected_shapes({'ce1dbfb4-x/34/v0/len24':1}))
