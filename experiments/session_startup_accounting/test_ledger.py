import unittest
from ledger import Ledger,validate_read,verify
import copy
import itertools

def sample():return dict(pid=1,tid=2,identity_crosscheck=True,begin_ns=1,end_ns=2,process=dict(creation_100ns=1,kernel_100ns=0,user_100ns=2,cycles=3),thread=dict(creation_100ns=1,kernel_100ns=0,user_100ns=2,cycles=3),python_thread_before_ns=100,python_thread_after_ns=300,python_process_before_ns=100,python_process_after_ns=300)
class LedgerTests(unittest.TestCase):
    def test_native_crosscheck_and_wide_read_rejection(self):
        self.assertTrue(validate_read(sample()));v=sample();v['end_ns']=1000002
        with self.assertRaises(ValueError):validate_read(v)
        v=sample();v['python_thread_after_ns']=199
        with self.assertRaises(ValueError):validate_read(v)
    def test_open_preserves_return_and_boundaries(self):
        l=Ledger(sample);sentinel=object();out=l.wrap_open(lambda a:sentinel)(object());self.assertIs(out,sentinel);self.assertEqual([r['label'] for r in l.rows],['before_open','after_open'])
    def test_original_exception_not_masked_by_failed_observer(self):
        def failed():raise OSError('read injected')
        error=RuntimeError('model injected');l=Ledger(failed)
        def original(a):raise error
        with self.assertRaises(RuntimeError) as got:l.wrap_open(original)(object())
        self.assertIs(got.exception,error);self.assertEqual(len(l.rows),2);self.assertFalse(any(r['valid'] for r in l.rows))
    def test_only_fixed_inference_boundaries_are_read(self):
        l=Ledger(sample);obj=object();calls=[];f=l.wrap_infer(lambda a,x:calls.append(x) or x)
        for i in range(205):self.assertEqual(f(obj,i),i)
        self.assertEqual(len(calls),205);self.assertEqual([r['label'] for r in l.rows],['before_infer1','after_infer1','after_infer100','after_infer200'])
    def test_read_failure_does_not_change_inference_return(self):
        l=Ledger(lambda:(_ for _ in ()).throw(OSError('read injected')))
        self.assertEqual(l.wrap_infer(lambda a:17)(object()),17);self.assertFalse(l.rows[0]['valid'])

    def full(self):
        clock=itertools.count(100,100).__next__;count=[0];tid=[7]
        def reader():
            count[0]+=1;v=sample();v['tid']=tid[0];v['thread']['creation_100ns']=tid[0]
            v['process']['user_100ns']=count[0]*3;v['process']['cycles']=count[0]*30
            v['thread']['user_100ns']=count[0];v['thread']['cycles']=count[0]*10
            v['python_process_before_ns']=(count[0]*3-1)*100;v['python_process_after_ns']=(count[0]*3+1)*100
            v['python_thread_before_ns']=(count[0]-1)*100;v['python_thread_after_ns']=(count[0]+1)*100
            return v
        l=Ledger(reader,clock);obj=object();l.wrap_open(lambda a:None)(obj);f=l.wrap_infer(lambda a:None)
        for _ in range(200):f(obj)
        phases=[]
        for role,number in [('gui',8),('model',7),('consumer',9)]:
            tid[0]=number
            for ordinal in (59904,65904):l.capture(f'{role}/{ordinal}');phases.append(dict(role=role,ordinal=ordinal,pid=1,tid=number,cpu_hook_total_ns=100))
        return l.payload(),phases
    def test_stage_identity_and_monotone_cpu_work(self):
        value,phases=self.full();self.assertTrue(verify(value,phases)['startup_cpu_ledger_pass'])
        broken=copy.deepcopy(value);broken['calls'][0]['begin_ns']=0
        with self.assertRaises(AssertionError):verify(broken,phases)
        broken=copy.deepcopy(value)
        for r in broken['rows']:
            for role in ('process','thread'):r['value'][role]['cycles']=0
        with self.assertRaises(AssertionError):verify(broken,phases)

    def test_snapshot_is_immutable_when_later_records_change(self):
        l=Ledger(sample);l.capture('first');frozen=l.payload();l.rows[0]['value']['cycles']=999;l.rows[0]['value']['thread']['cycles']=999;l.capture('second')
        self.assertEqual(len(frozen['rows']),1);self.assertNotIn('cycles',frozen['rows'][0]['value']);self.assertEqual(frozen['rows'][0]['value']['thread']['cycles'],3)
