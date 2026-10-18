import unittest
from temporal_review01 import completed_at,completion_bracket,event_bounds,validate_queue


MS=10**6


class TemporalBoundsChecks(unittest.TestCase):
    def rows(self):return [[t*MS,n] for t,n in [(100,0),(200,10),(300,20),(400,30)]]
    def event(self):
        event=dict(event_id='x',contact_id=1,touch_sample=5,published_sample=10,active=True,revision=1)
        m=dict(queue_common=self.rows(),paints={'1':250*MS})
        trigger={'x':dict(phase='feed',raw_trigger_sample=12,event=event)}
        return m,dict(walking_summary=dict(event_publications=[event])),{n:(100+n*5)*MS for n in range(31)},trigger
    def test_no_timestamp_interpolation(self):
        self.assertEqual(completed_at(self.rows(),250*MS,30),[10,20]);self.assertEqual(completion_bracket(self.rows(),12),[200*MS,300*MS])
    def test_duplicate_clock_ticks_keep_range(self):
        rows=[[1,0],[2,10],[2,20],[3,30]];self.assertEqual(completed_at(rows,2,30),[10,20])
    def test_unobserved_tail_unknown(self):self.assertIsNone(completed_at(self.rows(),500*MS,40))
    def test_known_finite_tail_closed(self):self.assertEqual(completed_at(self.rows(),500*MS,30),[30,30])
    def test_missing_publication_bracket_rejected(self):
        with self.assertRaises(ValueError):completion_bracket(self.rows(),31)
    def test_processing_trigger_not_touch_sample(self):
        v=event_bounds(*self.event())[0];self.assertEqual(v['raw_release_trigger'],12);self.assertEqual(v['publication_host_bounds_ns'],[200*MS,300*MS]);self.assertEqual(v['source_trigger_to_publication_ms'],[40,140])
    def test_paint_can_precede_later_batch_witness(self):
        v=event_bounds(*self.event())[0];self.assertEqual(v['publication_to_paint_raw_bounds_ms'],[-50,50]);self.assertEqual(v['publication_to_paint_nonnegative_bounds_ms'],[0,50])
    def test_paint_before_proven_lower_bound_rejected(self):
        m,r,t,g=self.event();m['paints']['1']=190*MS
        with self.assertRaises(AssertionError):event_bounds(m,r,t,g)
    def test_published_sample_mismatch_rejected(self):
        m,r,t,g=self.event();g['x']['event']=dict(g['x']['event'],published_sample=11)
        with self.assertRaises(AssertionError):event_bounds(m,r,t,g)


class QueueWitnessChecks(unittest.TestCase):
    def fixture(self):
        # Source indices1..3; C=1,E=3,P=2 proves oldest enqueued sample2.
        row=[100,1,10,2,20,3,30,2,0,'pending',None,None,0]
        return dict(queue_common=[row],queue_samples=[],armed_ns=0),{1:10,2:20,3:30}
    def test_oldest_receipt_independently_matches(self):self.assertEqual(validate_queue(*self.fixture())['oldest_pending_receipts_independently_matched'],1)
    def test_oldest_receipt_corruption_rejected(self):
        m,r=self.fixture();m['queue_common'][0][4]=15
        with self.assertRaises(AssertionError):validate_queue(m,r)
    def test_unfinished_not_pending_rejected(self):
        m,r=self.fixture();m['queue_common'][0][7]=1
        with self.assertRaises(AssertionError):validate_queue(m,r)
    def test_empty_queue_with_inflight_is_not_idle(self):
        m,r=self.fixture();m['queue_samples']=[[90,1,10,0,None,3,30,2,2,'batch',2,3,2]];m['queue_common'][0]=[100,3,30,0,None,3,30,0,0,'empty',None,None,0]
        self.assertEqual(validate_queue(m,r)['max_post_arm_inflight'],2)


if __name__=='__main__':unittest.main()
