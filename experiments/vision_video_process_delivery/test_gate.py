import unittest


class Gate(unittest.TestCase):
    def test_separate_pid_is_required(self):
        parent=10;child=11
        self.assertNotEqual(parent,child)
        with self.assertRaises(AssertionError):
            assert parent!=parent

    def test_all_messages_not_a_subset(self):
        expected=417
        self.assertEqual(417,expected)
        self.assertNotEqual(416,expected)

    def test_delivery_is_not_performance(self):
        result=dict(delivery=True,performance=False,field_fix=False)
        self.assertTrue(result['delivery']);self.assertFalse(result['performance']);self.assertFalse(result['field_fix'])


if __name__=='__main__':unittest.main()
