import unittest
from qt_label_wait_review import guarded_overlap, required_matched


class QtWait(unittest.TestCase):
    def test_ready_to_running_tail_is_excluded(self):
        a = dict(out_qpc=0, ready_qpc=10, in_qpc=100)
        b = dict(out_qpc=20, ready_qpc=30, in_qpc=110)
        self.assertIsNone(guarded_overlap(a, b, guard=1))

    def test_both_sides_of_wait_intersection_are_guarded(self):
        a = dict(out_qpc=0, ready_qpc=10, in_qpc=100)
        b = dict(out_qpc=5, ready_qpc=20, in_qpc=110)
        self.assertEqual(guarded_overlap(a, b, guard=1), [6, 9])
        self.assertIsNone(guarded_overlap(a, b, guard=3))

    def test_unmatched_symbol_or_missing_latch_is_not_a_witness(self):
        frames = [dict(symbol='QLatch::waitInternal', pdb_matched=True),
                  dict(symbol='QLabel::paintEvent', pdb_matched=False)]
        self.assertFalse(required_matched(frames, ['QLatch::waitInternal', 'QLabel::paintEvent']))
        self.assertFalse(required_matched(frames[1:], ['QLatch::waitInternal']))
        frames[1]['pdb_matched'] = True
        self.assertTrue(required_matched(frames, ['QLatch::waitInternal', 'QLabel::paintEvent']))
