import unittest
from analyze import prefix
class Prefix(unittest.TestCase):
    def test_later_overlap_is_not_common_history(self):self.assertEqual(prefix([1,2,3,4],[1,9,3,4]),1)
    def test_empty_and_exact_prefix(self):
        self.assertEqual(prefix([],[]),0);self.assertEqual(prefix([1,2],[1,2,3]),2)
