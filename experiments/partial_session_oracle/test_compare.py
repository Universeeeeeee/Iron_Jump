import unittest
from compare import differences

class ExactValues(unittest.TestCase):
    def test_same(self):self.assertEqual(differences(dict(a=[1,None]),dict(a=[1,None])),[])
    def test_metric_changes_not_normalized(self):self.assertEqual(differences(dict(step_length=1),dict(step_length=2))[0]['path'],'/step_length')
    def test_history_order_preserved(self):self.assertTrue(differences([1,2],[2,1]))
    def test_missing_fields_rejected(self):self.assertTrue(differences(dict(a=1),dict(a=1,b=2)))
