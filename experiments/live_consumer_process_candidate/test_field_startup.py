"""Build the actual field GUI while preventing hardware and session startup."""
import importlib.util,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

@unittest.skipUnless(importlib.util.find_spec('qtpy') and importlib.util.find_spec('cv2'),'Qt runtime unavailable')
class FieldStartupTests(unittest.TestCase):
 def test_constructor_connects_callable_visual_slot_without_hardware(self):
  os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
  if os.name=='nt':os.environ.setdefault('QT_QPA_FONTDIR','C:/Windows/Fonts')
  from qtpy.QtWidgets import QApplication
  from field_walk import Run,EmbeddedCameraPanel,LiveSessionProcess
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as temporary:
   with patch.object(EmbeddedCameraPanel,'start_preview') as preview,patch.object(LiveSessionProcess,'prepare') as prepare:
    run=Run(Path(temporary)/'field',app,{})
    try:
     self.assertTrue(callable(run.on_visual_frame))
     run.client.footprint_visual_frame.emit({'feet':[{'contact_id':3,'status':'confirmed'}]})
     self.assertIn('3',run.visual_receipts)
     self.assertIsNone(run.client.process)
     preview.assert_called_once();prepare.assert_called_once()
    finally:run.finalize()

if __name__=='__main__':unittest.main()
