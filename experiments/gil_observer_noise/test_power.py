import unittest
from confirmation_review import sensitivity
from noise_stats import contrast


def case(x):return dict(wall_ns=x,thread_cpu_ns=x,cycles=x,blocks=[dict(raw_first=1,wall_ns=x)])


class PowerChecks(unittest.TestCase):
    def test_more_effect_has_more_power(self):
        v=contrast([(case(100),case(x)) for x in (95,105)*12]);p=sensitivity(v)['wall_ns']['power_for_positive_effect'];self.assertLess(p['0.02'],p['0.03']);self.assertLess(p['0.03'],p['0.1'])
    def test_noisy_data_loses_small_effect_power(self):
        v=contrast([(case(100),case(x)) for x in (50,200)*12]);self.assertLess(sensitivity(v)['wall_ns']['power_for_positive_effect']['0.03'],.8)
    def test_tail_symmetry_matches_independent_quadrature(self):
        import math
        from scipy.integrate import quad
        from scipy.stats import nct,t,norm,chi2
        df=23;critical=t.ppf(.99375,df);nc=8
        direct=quad(lambda v:(norm.sf(critical*math.sqrt(v/df)-nc)+norm.cdf(-critical*math.sqrt(v/df)-nc))*chi2.pdf(v,df),0,math.inf,epsabs=1e-11)[0]
        stable=nct.sf(critical,df,nc)+nct.sf(critical,df,-nc)
        self.assertAlmostEqual(direct,stable,places=9)
    def test_report_is_sensitivity_not_field_qualification(self):
        v=contrast([(case(100),case(x)) for x in (95,105)*12]);self.assertIn('not measured',sensitivity(v)['wall_ns']['limits'])


if __name__=='__main__':unittest.main()
