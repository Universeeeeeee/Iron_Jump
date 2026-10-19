import unittest
from outbox import Outbox,OutboxError

class Memory:
    def send_bytes(self,packet):pass

class ExplicitPeerLoss(unittest.TestCase):
    def test_command_channel_loss_is_fault_even_without_send_error(self):
        box=Outbox(Memory());box.abort('command_channel_eof')
        with self.assertRaises(OutboxError):box.enqueue(dict(sequence=1,value='not delivered'))
        self.assertFalse(box.finish(2));self.assertFalse(box.snapshot()['writer_alive'])
        self.assertEqual(box.snapshot()['failure']['reason'],'command_channel_eof')
