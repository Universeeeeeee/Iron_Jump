import unittest
from state import State

class Confirmations(unittest.TestCase):
    def apply(self,state,kind,payload):return state.apply(dict(sequence=state.sequence+1,pid=2,kind=kind,payload=payload),2)
    def test_enqueue_does_not_imply_running(self):
        s=State();self.apply(s,'actor_ready',{});self.apply(s,'prepared',{});self.apply(s,'source_enabled',{});self.apply(s,'ready_to_start',dict(quality_key='key'));self.assertFalse(s.is_running)
        self.apply(s,'started',{});self.assertTrue(s.is_running)
    def test_wrong_actor_rejected(self):
        with self.assertRaises(ValueError):State().apply(dict(sequence=1,pid=3,kind='actor_ready',payload={}),2)
    def test_unconfirmed_stop_rejected(self):
        with self.assertRaises(ValueError):self.apply(State(),'command_completed',dict(kind='stop',reader_stopped=False,qt_thread_stopped=True))
    def test_report_requires_stop(self):
        with self.assertRaises(ValueError):self.apply(State(),'report_value',dict(report={}))
    def test_data_end_does_not_finalize(self):
        s=State();self.apply(s,'actor_ready',{});self.apply(s,'prepared',{})
        self.apply(s,'command_completed',dict(kind='discard',reader_stopped=True,qt_thread_stopped=True))
        self.apply(s,'payload_end',dict(local_measurement_complete=True,transport_unconfirmed=True));self.assertNotEqual(s.phase,'complete')
        with self.assertRaises(ValueError):s.finalize(dict(complete=False),1)
    def test_unknown_notification_rejected(self):
        with self.assertRaises(ValueError):self.apply(State(),'notification',dict(signal='unknown',args=[]))
