from types import SimpleNamespace
import unittest
from draw02 import observe,paint_then_observe
class Draw(unittest.TestCase):
    def stats(self):return dict(all=0,valid=0,disabled_calls=0)
    def test_actual_canvas_tuple(self):
        w=SimpleNamespace(_live_pose=({'nodes':{'a':{'valid':True},'b':{'valid':True}},'connections':[('a','b')]},(640,480)),isEnabled=lambda:True)
        s=self.stats();observe(w,s);self.assertEqual(s,dict(all=1,valid=1,disabled_calls=0))
    def test_empty_pose(self):
        s=self.stats();observe(SimpleNamespace(_live_pose=None),s);self.assertEqual(s['valid'],0)
    def test_observer_failure_does_not_skip_original_paint(self):
        calls=[];errors=[]
        result=paint_then_observe(lambda *args:calls.append('original') or 17,SimpleNamespace(_live_pose=()),None,None,self.stats(),errors)
        self.assertEqual(result,17);self.assertEqual(calls,['original']);self.assertEqual(len(errors),1)
