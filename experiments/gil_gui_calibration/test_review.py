import copy
import unittest
from review_aa01 import counters,summarize


class CounterChecks(unittest.TestCase):
    def fixture(self):
        anchor=dict(frequency=10**9,qpc_before=0,qpc_after=0,perf_before_ns=0,perf_after_ns=0)
        before=[dict(pid=10 if role!='sdk' else 20,tid=i,role=role,creation_100ns=i,active=True,cycles=5,user_100ns=1,kernel_100ns=0,start=anchor,end=anchor) for i,role in enumerate(('gui','consumer','reader','sdk'),1)]
        after=copy.deepcopy(before)
        for r in after:r['cycles']=10;r['user_100ns']=2
        return dict(case_pass=True,errors=[],target_still_running=False,target_pid=10,before=before,after=after,anchors=[anchor])
    def test_separate_roles_preserved(self):
        v=counters(self.fixture());self.assertEqual(v['totals']['sdk'],dict(cpu_ns=100,cycles=5,threads=1));self.assertEqual(v['totals']['gui']['threads'],1)
    def test_sdk_same_pid_rejected(self):
        r=self.fixture();r['before'][-1]['pid']=10;r['after'][-1]['pid']=10
        with self.assertRaises(AssertionError):counters(r)
    def test_reused_tid_rejected(self):
        r=self.fixture();r['after'][0]['creation_100ns']+=1
        with self.assertRaises(AssertionError):counters(r)
    def test_backward_counter_rejected(self):
        r=self.fixture();r['after'][0]['user_100ns']=0
        with self.assertRaises(AssertionError):counters(r)
    def test_missing_sdk_rejected(self):
        r=self.fixture();r['before'].pop();r['after'].pop()
        with self.assertRaises(AssertionError):counters(r)
    def test_duplicate_identity_rejected(self):
        r=self.fixture();r['before'][1]=copy.deepcopy(r['before'][0]);r['after'][1]=copy.deepcopy(r['after'][0])
        with self.assertRaises(AssertionError):counters(r)
    def test_large_clock_uncertainty_rejected(self):
        r=self.fixture()
        for g in ('before','after'):
            for row in r[g]:
                for k in ('start','end'):row[k]['qpc_after']=2000000;row[k]['perf_after_ns']=2000000
        with self.assertRaises(ValueError):counters(r)


class FeasibilityStatisticsChecks(unittest.TestCase):
    def value(self,v):return {r:dict(cpu_ns=v,cycles=v,threads=1) for r in ('consumer','gui','reader','sdk')}
    def test_pairs_not_threads_are_independent(self):
        v=summarize([(self.value(100),self.value(101))]*4);self.assertEqual(v['sdk_cpu_ns']['independent_pairs'],4)
    def test_outlier_kept(self):
        v=summarize([(self.value(100),self.value(x)) for x in (100,100,100,200)]);self.assertEqual(len(v['gui_cpu_ns']['raw_relative_changes']),4);self.assertEqual(v['gui_cpu_ns']['raw_relative_changes'][-1],1)
    def test_zero_delta_unavailable(self):
        v=summarize([(self.value(0),self.value(1))]*4);self.assertFalse(v['consumer_cpu_ns']['available'])


if __name__=='__main__':unittest.main()
