import copy
import unittest
from verify_phases import verify_record

class Phases(unittest.TestCase):
    def fixture(self):
        labels=['before_open','original_open','after_open','original_close','after_close'];rows=[];probes={}
        for i,label in enumerate(labels):
            start=i*1000;rows.append(dict(label=label,tid=1,begin_ns=start,end_ns=start+900,success=True))
            if label.startswith('original_'):continue
            runs=[];now=start
            for n in [8000000,32000000,32000000,8000000,8000000,32000000]:
                duration=n//1000000;runs.append(dict(iterations=n,dependent_adds=n*16,result=n*16,begin_ns=now,end_ns=now+duration));now+=duration
            probes[label]=dict(complete=True,errors=[],memory_released=True,rows=runs)
        return dict(rows=rows,open_count=1,close_count=1),probes
    def test_valid(self):self.assertEqual(verify_record(*self.fixture())['same_model_tid'],1)
    def test_changed_tid(self):
        b,p=self.fixture();b['rows'][2]['tid']=2
        with self.assertRaises(ValueError):verify_record(b,p)
    def test_wrong_output(self):
        b,p=self.fixture();p['after_open']['rows'][0]['result']=0
        with self.assertRaises(ValueError):verify_record(b,p)
    def test_failed_original(self):
        b,p=self.fixture();b['rows'][1]['success']=False
        with self.assertRaises(ValueError):verify_record(b,p)
    def test_scaling_failure(self):
        b,p=self.fixture();p['after_open']['rows'][0]['end_ns']+=20
        with self.assertRaises(ValueError):verify_record(b,p)
    def test_time_outside_stage(self):
        b,p=self.fixture();p['before_open']['rows'][0]['begin_ns']=-1
        with self.assertRaises(ValueError):verify_record(b,p)
