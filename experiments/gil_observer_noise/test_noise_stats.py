import unittest
import noise_stats as n


def case(x):return dict(wall_ns=x,thread_cpu_ns=x,cycles=x,blocks=[dict(raw_first=1,wall_ns=x)])


class StatisticalChecks(unittest.TestCase):
    def test_equal_controls_have_zero_width(self):
        v=n.contrast([(case(100),case(100))]*8);self.assertEqual(v['independent_pairs'],8);self.assertTrue(n.acceptance(v)['statistical_equivalence_pass'])
    def test_two_percent_constant_effect_inside_three(self):self.assertTrue(n.acceptance(n.contrast([(case(100),case(102))]*8))['statistical_equivalence_pass'])
    def test_four_percent_constant_effect_rejected(self):self.assertFalse(n.acceptance(n.contrast([(case(100),case(104))]*8))['statistical_equivalence_pass'])
    def test_noisy_mean_not_enough(self):
        pairs=[(case(100),case(x)) for x in (90,110)*4];self.assertFalse(n.acceptance(n.contrast(pairs))['statistical_equivalence_pass'])
    def test_outlier_not_averaged_away(self):
        pairs=[(case(100),case(100))]*23+[(case(100),case(116))];v=n.acceptance(n.contrast(pairs));self.assertFalse(v['every_original_trial_inside_legacy_hard_limit']);self.assertFalse(v['statistical_equivalence_pass'])
    def test_blocks_do_not_increase_n(self):
        v=n.contrast([(case(100),case(101))]*8);self.assertEqual(v['df'],7);self.assertEqual(v['family_size'],4)
    def test_zero_values_rejected(self):
        with self.assertRaises(ValueError):n.contrast([(case(0),case(1))]*8)
    def test_single_pair_rejected(self):
        with self.assertRaises(ValueError):n.contrast([(case(100),case(101))])
    def test_missing_block_rejected(self):
        a,b=case(100),case(100);b['blocks']=[]
        with self.assertRaises(ValueError):n.contrast([(a,b)]*8)
    def test_precision_cap_not_success(self):
        v=n.contrast([(case(100),case(x)) for x in (50,200)*4]);p=n.precision_plan(v,v);self.assertEqual(p['chosen_pairs'],24);self.assertFalse(p['predicted_precision_sufficient'])
    def test_drift_flag_is_not_frequency_claim(self):self.assertTrue(n.drift([case(x) for x in range(100,116)])['flag'])


if __name__=='__main__':unittest.main()
