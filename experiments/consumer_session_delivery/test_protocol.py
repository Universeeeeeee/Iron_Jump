import unittest
from protocol import validate_message

class Protocol(unittest.TestCase):
    def test_expected(self):self.assertEqual(validate_message(dict(sequence=1,pid=2,kind='prepared'),0,2),1)
    def test_gap(self):
        with self.assertRaises(ValueError):validate_message(dict(sequence=2,pid=2,kind='prepared'),0,2)
    def test_pid(self):
        with self.assertRaises(ValueError):validate_message(dict(sequence=1,pid=3,kind='prepared'),0,2)
    def test_unknown(self):
        with self.assertRaises(ValueError):validate_message(dict(sequence=1,pid=2,kind='guessed_complete'),0,2)
