import unittest
from analyze import role
class Roles(unittest.TestCase):
    def test_generic_gui_native_is_not_gui_paint(self):self.assertEqual(role(1,8,1,{'gui_main':3}),'unassigned_same_process')
    def test_model_video_and_sdk_stay_distinct(self):
        named={'gui_main':3,'model_caller':8,'saved_video_submitter':9}
        self.assertEqual(role(1,8,1,named),'model_caller');self.assertEqual(role(1,9,1,named),'saved_video_submitter');self.assertEqual(role(2,8,1,named),'sdk_child')
    def test_conflicting_thread_mapping_rejected(self):
        with self.assertRaises(ValueError):role(1,8,1,{'model_caller':8,'saved_video_submitter':8})
