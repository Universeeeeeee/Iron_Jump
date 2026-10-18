import copy
import json
import threading
import unittest
from unittest.mock import patch
from fixture import run_case
from snapshot import FrozenAudit,model_end_checks


class SnapshotTests(unittest.TestCase):
    def test_nested_payload_owned_at_commit_and_snapshot(self):
        audit=FrozenAudit();value=dict(args=[1,2],meta=dict(frame=7))
        audit.event('sdk_events',data=value);first=audit.finish()
        value['args'].append(3);value['meta']['frame']=99
        self.assertEqual(first['rows']['sdk_events'][0]['data'],dict(args=[1,2],meta=dict(frame=7)))
        self.assertEqual(audit.finish()['rows']['sdk_events'][0]['data'],dict(args=[1,2],meta=dict(frame=7)))
        first['rows']['sdk_events'][0]['data']['args'].append(4)
        self.assertEqual(audit.finish()['rows']['sdk_events'][0]['data']['args'],[1,2])

    def test_late_event_does_not_rewrite_returned_snapshot(self):
        a=FrozenAudit();a.event('service_status',service=0,status='ready');first=a.finish();saved=json.dumps(first,sort_keys=True)
        a.event('service_status',service=0,status='stopped')
        self.assertEqual(json.dumps(first,sort_keys=True),saved);self.assertEqual(first['event_sequence'],1);self.assertEqual(a.finish()['event_sequence'],2)

    def test_writer_cannot_commit_inside_snapshot(self):
        a=FrozenAudit();a.event('service_status',service=0,status='ready')
        copying=threading.Event();release=threading.Event();writer_ready=threading.Event();writer_done=threading.Event();snapshots=[];failures=[]
        original=copy.deepcopy
        def gated(value,*args,**kwargs):
            if value is a.rows:
                copying.set()
                if not release.wait(2):raise TimeoutError('Snapshot test release missing')
            if isinstance(value,dict) and value.get('writer_marker'):writer_ready.set()
            return original(value,*args,**kwargs)
        def snapshot():
            try:snapshots.append(a.finish())
            except BaseException as exc:failures.append(repr(exc))
        def writer():
            try:a.event('service_status',service=0,status='stopped',writer_marker=True)
            except BaseException as exc:failures.append(repr(exc))
            finally:writer_done.set()
        s=threading.Thread(target=snapshot);w=threading.Thread(target=writer)
        try:
            with patch('snapshot.copy.deepcopy',gated):
                s.start();self.assertTrue(copying.wait(1));w.start();self.assertTrue(writer_ready.wait(1));self.assertFalse(writer_done.is_set());release.set();s.join(2);w.join(2)
        finally:release.set();s.join(2)
        self.assertFalse(failures);self.assertFalse(s.is_alive());self.assertFalse(w.is_alive())
        self.assertEqual(snapshots[0]['event_sequence'],1);self.assertEqual(len(snapshots[0]['rows']['service_status']),1)
        last=a.finish();self.assertEqual(last['event_sequence'],2)
        self.assertGreaterEqual(last['rows']['service_status'][1]['commit_ns'],snapshots[0]['snapshot']['locked_end_ns'])

    def test_failed_copy_does_not_publish_or_consume_sequence(self):
        a=FrozenAudit()
        class Bad:
            def __deepcopy__(self,memo):raise ValueError('injected copy fault')
        with self.assertRaises(ValueError):a.event('sdk_events',data=Bad())
        self.assertEqual(a.finish()['event_sequence'],0)
        a.event('service_status',service=0,status='ready');self.assertEqual(a.finish()['event_sequence'],1)

    def test_close_entry_preserves_return_and_exception(self):
        a=FrozenAudit();token=object();receiver=object();seen=[]
        def call(adapter,arg):seen.append((adapter,arg));return token
        wrapped=a.close_entry(call);self.assertIs(wrapped(receiver,7),token);self.assertEqual(seen,[(receiver,7)]);self.assertEqual(wrapped.__name__,call.__name__)
        error=RuntimeError('injected')
        def fail(adapter):raise error
        with self.assertRaises(RuntimeError) as caught:a.close_entry(fail)(receiver)
        self.assertIs(caught.exception,error);self.assertEqual(len(a.finish()['rows']['model_close_enter']),2)


class ServiceEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.delay=run_case('frozen');cls.listener=run_case('frozen',True);cls.failed=run_case('frozen',False,True)

    def test_actual_service_stop_can_return_while_close_is_blocked(self):
        r=self.delay;self.assertTrue(r['target_was_real_FootVisionService']);self.assertTrue(r['blocked']['service_running']);self.assertTrue(r['blocked']['python_thread_alive']);self.assertTrue(r['blocked']['close_enter_oracle'])
        self.assertFalse(all(r['first_snapshot']['model_end_checks'].values()));self.assertFalse(r['first_snapshot_changed'])
        self.assertTrue(all(r['second_snapshot']['model_end_checks'].values()))

    def test_stopped_signal_is_not_thread_exit(self):
        s=self.listener['listener_snapshot'];self.assertTrue(s['model_end_checks']['service_markers']);self.assertTrue(s['model_end_checks']['close_return_confirmed']);self.assertFalse(s['model_end_checks']['service_exited'])

    def test_exception_does_not_become_success_at_thread_exit(self):
        s=self.failed['second_snapshot'];self.assertTrue(s['model_end_checks']['service_exited']);self.assertFalse(s['model_end_checks']['close_return_confirmed'])

    def reject(self,change,gate):
        s=copy.deepcopy(self.delay['second_snapshot']);change(s);self.assertFalse(model_end_checks(s)[gate])

    def test_missing_close_entry_rejected(self):self.reject(lambda s:s['rows']['model_close_enter'].clear(),'one_model')
    def test_wrong_model_identity_rejected(self):self.reject(lambda s:s['rows']['model_close'][0].__setitem__('adapter',0),'model_identity')
    def test_wrong_worker_identity_rejected(self):self.reject(lambda s:s['rows']['model_close'][0].__setitem__('tid',0),'model_identity')
    def test_unknown_or_collected_service_is_not_exited(self):self.reject(lambda s:s['service_liveness_reads'][0].__setitem__('alive',None),'service_exited')
    def test_missing_terminal_notification_rejected(self):
        self.reject(lambda s:s['rows'].__setitem__('service_status',[x for x in s['rows']['service_status'] if x['status']!='stopped']),'service_markers')
    def test_return_order_rejected(self):self.reject(lambda s:s['rows']['model_close'][0].__setitem__('end_ns',0),'close_return_confirmed')
    def test_duplicate_event_sequence_rejected(self):self.reject(lambda s:s['rows']['model_close'][0].__setitem__('event_sequence',1),'committed_prefix')
    def test_missing_record_rejected(self):self.reject(lambda s:s['rows']['model_close'].clear(),'committed_prefix')
    def test_callback_fault_rejected(self):self.reject(lambda s:s['rows']['callback_errors'].append(dict(event_sequence=999,error='fault')),'no_callback_faults')
    def test_multiple_or_ambiguous_service_unqualified(self):self.reject(lambda s:s.__setitem__('service_count',2),'single_service')


if __name__=='__main__':unittest.main()
