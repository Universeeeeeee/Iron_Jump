import unittest
from decision import decide
from run_next import next_case
class ProtocolTests(unittest.TestCase):
 def test_failed_case_stops_sequence(self):
  with self.assertRaises(RuntimeError):next_case([dict(id='a')],{'a':dict(complete=False)})
 def test_next_case_requires_order(self):
  cases=[dict(id='a'),dict(id='b')];self.assertEqual(next_case(cases,{'a':dict(complete=True)})['id'],'b')
 def test_replicated_original_and_bounded_process_support(self):
  plan=dict(original_cases=['o1','o2'],process_cases=['p1','p2'],decision=dict(input_lateness_max_ms=100,severe_queue_lower=1000,severe_latency_ms=1000,process_queue_upper=250,process_latency_ms=250))
  def r(q,l):return dict(complete=True,boot_qualified=True,input_lateness_ms=10,observed_queue_lower=q,queue_upper=q,scheduled_max_ms=l)
  rows=dict(o1=r(1200,1300),o2=r(1100,1400),p1=r(100,180),p2=r(120,190));self.assertTrue(decide(rows,plan)['advance_to_field'])
if __name__=='__main__':unittest.main()
