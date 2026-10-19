import unittest
from types import SimpleNamespace
from commands import apply_control,resources_stopped,bind_notifications,NOTIFICATIONS

class Controller:
    def __init__(self):self.is_running=True;self.is_paused=False;self._pause_pending=False;self.engine=SimpleNamespace(overground=object());self._thread=object();self.calls=[]
    def pause(self):self.calls.append('pause')
    def resume(self):self.calls.append('resume')
    def stop(self,reason):self.calls.append(('stop',reason));self.is_running=False;self._thread=None
    def discard(self):self.calls.append('discard');self._thread=None

class Commands(unittest.TestCase):
    def test_walk_not_fake_paused(self):
        c=Controller()
        for kind in ['pause','resume']:
            self.assertEqual(apply_control(c,kind)['status'],'unsupported');self.assertFalse(c.is_paused)
    def test_pause_drift_fails(self):
        c=Controller();c.pause=lambda:setattr(c,'is_paused',True)
        with self.assertRaises(ValueError):apply_control(c,'pause')
    def test_stop_does_not_ack_completion(self):self.assertEqual(apply_control(Controller(),'stop')['status'],'pending_resource_confirmation')
    def test_running_discard_rejected(self):
        with self.assertRaises(ValueError):apply_control(Controller(),'discard')
    def test_unconfirmed_reader_prevents_completion(self):
        c=Controller();c._thread=None;source=SimpleNamespace(reader=SimpleNamespace(is_alive=lambda:True));thread=SimpleNamespace(isRunning=lambda:False)
        self.assertFalse(resources_stopped(c,source,thread));source.reader.is_alive=lambda:False;self.assertTrue(resources_stopped(c,source,thread))
    def test_no_missing_notification_bindings(self):
        c=SimpleNamespace();callbacks={};out=[]
        for name in NOTIFICATIONS:setattr(c,name,SimpleNamespace(connect=lambda f,n=name:callbacks.update({n:f})))
        refs=bind_notifications(c,lambda *args:out.append(args));self.assertEqual(len(refs),len(NOTIFICATIONS))
        for name in NOTIFICATIONS:callbacks[name]('value')
        self.assertEqual([v[1]['signal'] for v in out],list(NOTIFICATIONS))
