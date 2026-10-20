import unittest
from install import verify


class Gate(unittest.TestCase):
    def data(self):
        return dict(calls=4,pose_calls=2,errors=[],depth_at_restore=0,method_restored=True,installed_method_unchanged=True,
            gui_tid=7,AST_audit=dict(remaining_body_AST_equal=True),samples=[dict(tid=7,widget_dpr=1.25,pose_present=True)])
    def test_missing_updates_or_restore_fails(self):
        for key,value in [('pose_calls',0),('depth_at_restore',1),('method_restored',False),('errors',['fault'])]:
            d=self.data();d[key]=value
            with self.assertRaises(AssertionError):verify(d,dict(thread_ids=dict(gui=7)))
    def test_wrong_thread_or_DPR_fails(self):
        for key,value in [('tid',8),('widget_dpr',1)]:
            d=self.data();d['samples'][0][key]=value
            with self.assertRaises(AssertionError):verify(d,dict(thread_ids=dict(gui=7)))
    def test_pass_is_not_native_SDK_or_performance_pass(self):
        q=verify(self.data(),dict(thread_ids=dict(gui=7)))
        self.assertFalse(q['performance_AB_pass']);self.assertFalse(q['real_native_SDK_qualified'])
