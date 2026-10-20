import unittest
from check_overlap import union_length


class AuditRules(unittest.TestCase):
    def test_cross_cpu_overlap_is_not_summed_twice(self):
        self.assertEqual(union_length([(0, 10), (4, 12)]), 12)

    def test_touching_residency_is_continuous(self):
        self.assertEqual(union_length([(0, 10), (10, 20)]), 20)

    def test_negative_interval_is_rejected(self):
        with self.assertRaises(AssertionError):
            union_length([(5, 4)])


if __name__ == '__main__':
    unittest.main()
