import hashlib
from pathlib import Path
import sys
import unittest
from identity_hook import Identity,verify


class IdentityGate(unittest.TestCase):
    def data(self):
        row=dict(tid=7,entry_rva=10,receiver_cpp_pointer=1,pixmap=dict(width=1,height=1),
            pre_native_observation_bracket_ns=[1,2],caller=dict(relative='a.py',source_sha256='sha'))
        return dict(errors=[],auto_detached=True,final_profile_restored=True,rows=[dict(row) for _ in range(3)],budget=3,gui_tid=7)
    def test_wrong_entry_source_or_thread_rejected(self):
        for key,value in [('tid',8),('entry_rva',11)]:
            d=self.data();d['rows'][0][key]=value
            with self.assertRaises(AssertionError):verify(d,dict(entry_rva=10),{'a.py':'sha'})
        with self.assertRaises(AssertionError):verify(self.data(),dict(entry_rva=10),{'a.py':'different'})
    def test_incomplete_budget_or_unrestored_profile_rejected(self):
        for key in ('auto_detached','final_profile_restored'):
            d=self.data();d[key]=False
            with self.assertRaises(AssertionError):verify(d,dict(entry_rva=10),{'a.py':'sha'})
    @unittest.skipUnless(sys.platform=='win32','Win64 delivery')
    def test_actual_bound_protected_call_and_budget_detach(self):
        from PySide6 import QtGui,QtWidgets
        app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        class Label(QtWidgets.QLabel):
            def paintEvent(self,event):super().paintEvent(event)
        label=Label();label.resize(80,60);image=QtGui.QImage(8,8,QtGui.QImage.Format_RGB32);image.fill(0xff123456)
        label.setPixmap(QtGui.QPixmap.fromImage(image));out=QtGui.QImage(80,60,QtGui.QImage.Format_RGB32)
        entry=dict(entry_rva=0x1a8690,module_sha256='85cb6c2181b4b09887a7d8507dd950844d1b8f74a9c4002c7b71169f75bf6fda')
        hook=Identity(Path(__file__).parent,entry);hook.start()
        try:
            for _ in range(4):label.render(out)
        finally:data=hook.close();label.close()
        formal={Path(__file__).name:hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        verify(data,entry,formal)
        self.assertTrue(all(r['caller_self_is_receiver'] for r in data['rows']))
