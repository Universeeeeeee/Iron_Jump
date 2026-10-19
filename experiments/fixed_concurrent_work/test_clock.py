import threading
import unittest
from logical_clock import for_thread

class Clock(unittest.TestCase):
    def test_other_thread_never_sees_sensor_logical_time(self):
        clock=for_thread(threading.get_ident(),lambda:123,lambda:987);seen=[];worker=threading.Thread(target=lambda:seen.append(clock()));worker.start();worker.join();self.assertEqual(clock(),123);self.assertEqual(seen,[987])

if __name__=='__main__':unittest.main()
