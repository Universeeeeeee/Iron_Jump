import unittest
from decision import decide
class Decision(unittest.TestCase):
    def setUp(self):self.good=dict(b1_baseline='slow',b1_after_sham='slow',b1_after_interactive='fast',b2_baseline='slow',b2_after_interactive='fast',b2_after_sham='fast')
    def test_pattern_and_quality_both_required(self):
        self.assertTrue(decide(self.good,True)['activation_condition_supported']);self.assertFalse(decide(self.good,False)['activation_condition_supported'])
    def test_fast_initial_state_is_not_a_reset(self):
        self.assertFalse(decide(dict(self.good,b2_baseline='fast'),True)['activation_condition_supported'])
    def test_service_sham_also_recovers_is_not_specific(self):
        self.assertFalse(decide(dict(self.good,b1_after_sham='fast'),True)['activation_condition_supported'])
    def test_intermediate_and_missing_stay_unqualified(self):
        self.assertFalse(decide(dict(self.good,b1_after_interactive='intermediate'),True)['activation_condition_supported'])
        self.assertFalse(decide({},True)['activation_condition_supported'])
if __name__=='__main__':unittest.main()
