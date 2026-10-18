import unittest
from temporal_review02 import queue_cursor_brackets,event_bounds


def row(ms,completed,enqueued,pending):
    return [ms*10**6,completed,0,pending,None,enqueued,0,enqueued-completed,enqueued-completed-pending,'pending',None,None,0]


class QueueCursorChecks(unittest.TestCase):
    def fixture(self):
        return dict(queue_common=[row(100,0,0,0),row(180,10,15,5),row(200,10,20,10),row(300,20,25,5),row(400,30,30,0)],queue_samples=[row(240,10,20,0)],paints={'1':250*10**6})
    def test_fifo_prefix_proves_distinct_enqueue_and_pop(self):
        v=queue_cursor_brackets(self.fixture(),12);self.assertEqual(v['enqueued'],[100*10**6,180*10**6]);self.assertEqual(v['popped'],[200*10**6,240*10**6])
    def test_residence_bounds_do_not_use_source_time_as_exact_enqueue(self):
        m=self.fixture();e=dict(event_id='x',contact_id=1,touch_sample=5,published_sample=10,active=True,revision=1);r=dict(walking_summary=dict(event_publications=[e]));received={n:(100+5*n)*10**6 for n in range(31)};triggers={'x':dict(phase='feed',raw_trigger_sample=12,event=dict(e))}
        v=event_bounds(m,r,received,triggers)[0];self.assertEqual(v['enqueue_host_bounds_ns'],[160*10**6,180*10**6]);self.assertEqual(v['queue_residence_bounds_ms'],[20,80]);self.assertEqual(v['dequeue_to_publication_bounds_ms'],[0,100])
    def test_regressing_dequeue_prefix_rejected(self):
        m=self.fixture();m['queue_samples'].append(row(250,10,20,20))
        with self.assertRaises(AssertionError):queue_cursor_brackets(m,12)
    def test_missing_two_sided_queue_witness_rejected(self):
        with self.assertRaises(ValueError):queue_cursor_brackets(self.fixture(),31)


if __name__=='__main__':unittest.main()
