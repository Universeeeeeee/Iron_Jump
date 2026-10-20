import unittest
from derive import derive,transform


class Source:
    def paintEvent(self,event):
        super().paintEvent(event)
        self.after.append(event)


class Derivation(unittest.TestCase):
    def test_only_base_call_changes_and_closure_is_not_forged(self):
        calls=[]
        fn,text,audit=derive(Source.paintEvent,lambda obj,event:calls.append((obj,event)),'diagnostic_generated.py')
        obj=type('Receiver',(),{})();obj.after=[]
        fn(obj,'event')
        self.assertEqual(calls,[(obj,'event')]);self.assertEqual(obj.after,['event'])
        self.assertTrue(audit['remaining_body_AST_equal']);self.assertEqual(fn.__code__.co_filename,'diagnostic_generated.py')
        self.assertEqual(fn.__code__.co_freevars,())

    def test_changed_base_call_or_additional_super_is_rejected(self):
        for text in ['def paintEvent(self,event):\n self.other(event)\n',
                     'def paintEvent(self,event):\n super().paintEvent(event)\n super().other()\n']:
            with self.assertRaises(AssertionError):transform(text)

    def test_source_after_base_call_is_preserved(self):
        _,audit=transform('def paintEvent(self,event):\n super().paintEvent(event)\n if self.flag:\n  return self.draw(event)\n')
        self.assertTrue(audit['only_first_statement_changed']);self.assertTrue(audit['remaining_body_AST_equal'])
