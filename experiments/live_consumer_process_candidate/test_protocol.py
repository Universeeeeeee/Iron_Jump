import unittest
from protocol import validate_command,validate_output
class ProtocolTests(unittest.TestCase):
 def test_command_order_and_kind(self):
  self.assertEqual(validate_command(dict(sequence=1,kind='prepare'),0),1)
  with self.assertRaises(ValueError):validate_command(dict(sequence=3,kind='prepare'),0)
  with self.assertRaises(ValueError):validate_command(dict(sequence=1,kind='pause'),0)
 def test_output_pid_order_and_kind(self):
  self.assertEqual(validate_output(dict(sequence=1,pid=4,kind='actor_ready'),0,4),1)
  with self.assertRaises(ValueError):validate_output(dict(sequence=1,pid=5,kind='actor_ready'),0,4)
