"""Conservative progress brackets and symmetric external perturbation acceptance."""
import copy
import unittest
from external_report import pair_result,work_bounds


def snapshot(q):return dict(start=dict(qpc_before=q),end=dict(qpc_after=q+1))


class ExternalReportTests(unittest.TestCase):
    def history(self):return [dict(host_before_ns=q*100,host_after_ns=q*100,work=dict(cpu_a=q)) for q in [0,10,20,30,40]]

    def test_work_retains_both_boundary_uncertainties(self):
        result=work_bounds(self.history(),'cpu_a',snapshot(15),snapshot(35),dict(qpc_frequency=10000000,host_ns_offset_lower=0,host_ns_offset_upper=0))
        self.assertEqual(result,dict(lower=10,upper=30))

    def test_missing_progress_bracket_rejected(self):
        with self.assertRaises(ValueError):
            work_bounds(self.history(),'cpu_a',snapshot(15),snapshot(45),dict(qpc_frequency=10000000,host_ns_offset_lower=0,host_ns_offset_upper=0))

    def test_regressing_progress_rejected(self):
        rows=self.history();rows[-1]['work']['cpu_a']=0
        with self.assertRaises(ValueError):
            work_bounds(rows,'cpu_a',snapshot(15),snapshot(35),dict(qpc_frequency=10000000,host_ns_offset_lower=0,host_ns_offset_upper=0))

    def test_midpoint_pass_does_not_hide_wide_failed_bound(self):
        p=dict(measurement_acceptance_pass=True,threads={n:dict(cpu_s=2,cycles=100,work=dict(lower=100,upper=100)) for n in ['cpu_a','cpu_b']})
        off=dict(processes=dict(gui=p,sdk=copy.deepcopy(p)));on=copy.deepcopy(off)
        on['processes']['sdk']['threads']['cpu_a']['work']=dict(lower=60,upper=140)
        result=pair_result(off,on,dict(work=.15,cpu_s=.15,cycles=.15))
        self.assertFalse(result['passed'])
        self.assertTrue(result['processes']['gui']['perturbation_pass'])
        self.assertFalse(result['processes']['sdk']['perturbation_pass'])

    def test_failed_trace_blocks_pair(self):
        p=dict(measurement_acceptance_pass=True,threads={n:dict(cpu_s=2,cycles=100,work=dict(lower=100,upper=100)) for n in ['cpu_a','cpu_b']})
        off=dict(processes=dict(gui=p,sdk=copy.deepcopy(p)));on=copy.deepcopy(off)
        on['processes']['gui']['measurement_acceptance_pass']=False
        self.assertFalse(pair_result(off,on,dict(work=.15,cpu_s=.15,cycles=.15))['passed'])

    def test_missing_work_is_failed_evidence_not_a_success(self):
        p=dict(measurement_acceptance_pass=True,threads={n:dict(cpu_s=2,cycles=100,work=dict(lower=100,upper=100)) for n in ['cpu_a','cpu_b']})
        off=dict(processes=dict(gui=p,sdk=copy.deepcopy(p)));on=copy.deepcopy(off)
        off['processes']['sdk']['threads']['cpu_a']['work']=dict(lower=None,upper=None,failure='Missing end bracket')
        result=pair_result(off,on,dict(work=.15,cpu_s=.15,cycles=.15))
        self.assertFalse(result['passed'])
        self.assertEqual(result['processes']['sdk']['work_unavailable'],['Missing end bracket'])


if __name__=='__main__':unittest.main()
