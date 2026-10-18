import unittest
from review01 import cadence


class CadenceChecks(unittest.TestCase):
    def rows(self):
        return [dict(kind='init',period_ms=250,requested_count=3,requested_tid=9,qpc_frequency=1000)]+[dict(kind='sample',qpc_begin=i*250) for i in range(3)]
    def check_rows(self,rows):return cadence(rows,dict(period_ms=250,count_per_phase=3),9)
    def test_delivered(self):
        v=self.check_rows(self.rows());self.assertTrue(v['requested'] and v['within_pacing_budget'])
    def test_fast_actual_rate_rejected(self):
        rows=self.rows();rows[2]['qpc_begin']=50;self.assertFalse(self.check_rows(rows)['within_pacing_budget'])
    def test_missing_sample_rejected(self):
        rows=self.rows();rows.pop();self.assertFalse(self.check_rows(rows)['within_pacing_budget'])
    def test_wrong_tid_rejected(self):
        rows=self.rows();rows[0]['requested_tid']=10;self.assertFalse(self.check_rows(rows)['requested'])


if __name__=='__main__':unittest.main()
