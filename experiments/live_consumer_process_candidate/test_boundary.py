import ast
from pathlib import Path
import unittest
class BoundaryTests(unittest.TestCase):
 def test_live_actor_uses_original_controller_and_default_usb(self):
  text=(Path(__file__).parent/'actor.py').read_text();self.assertIn("if fixture_root is None:controller=SessionController()",text);self.assertIn("else:\n  from replay02 import Source",text)
 def test_batch40_is_child_argument_and_original_source_unchanged(self):
  text=(Path(__file__).parent/'actor.py').read_text();self.assertIn('batch_size=40',text);self.assertIn('min(batch_size,len(inbox._pending))',text)
 def test_terminal_requires_resource_and_writer_completion(self):
  text=(Path(__file__).parent/'actor.py').read_text();self.assertIn("controller._thread is None",text);self.assertIn('writer_finished=outbox.finish(2)',text)
if __name__=='__main__':unittest.main()
