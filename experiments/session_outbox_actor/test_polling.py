import multiprocessing
import unittest
from polling import poll_packet

class Fake:
    def __init__(self,poll_error=None,recv_error=None,ready=True):self.poll_error=poll_error;self.recv_error=recv_error;self.ready=ready;self.recv_called=False
    def poll(self,timeout):
        if self.poll_error:raise self.poll_error
        return self.ready
    def recv(self):
        self.recv_called=True
        if self.recv_error:raise self.recv_error
        return dict(value=7)

class EndpointClosure(unittest.TestCase):
    def test_poll_broken_pipe_is_closed(self):
        c=Fake(poll_error=BrokenPipeError(32,'pipe ended'));kind,value=poll_packet(c)
        self.assertEqual(kind,'closed');self.assertEqual(value['error_type'],'BrokenPipeError');self.assertFalse(c.recv_called)
    def test_recv_eof_is_closed(self):self.assertEqual(poll_packet(Fake(recv_error=EOFError()))[0],'closed')
    def test_idle_is_not_closed(self):self.assertEqual(poll_packet(Fake(ready=False)),('idle',None))
    def test_decode_failure_not_hidden(self):
        with self.assertRaises(ValueError):poll_packet(Fake(recv_error=ValueError('bad packet')))
    def test_actual_native_closed_pipe(self):
        reader,writer=multiprocessing.Pipe(duplex=False);writer.close()
        try:self.assertEqual(poll_packet(reader,1)[0],'closed')
        finally:reader.close()
