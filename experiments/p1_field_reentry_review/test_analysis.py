import unittest
from analyze import field


class QueueMetric(unittest.TestCase):
    def test_sustained_shortage_keeps_actual_input_and_consumer_separate(self):
        rows=[]
        for i in range(31):
            host=i*100_000_000
            rows.append([host,i*50,host,i*50,host,i*100,host,i*50,0,'pending',None,None,0])
        result=field.window(rows,0,3_100_000_000)
        self.assertGreater(result['enqueued_fps'],990)
        self.assertLess(result['consumer_fps'],970)

    def test_empty_window_does_not_invent_rate(self):
        self.assertTrue(field.window([],0,1_000_000_000)['insufficient'])


if __name__=='__main__':
    unittest.main()
