"""Hardware-free failure-path checks; never launch GUI, USB, SDK or WPR."""
import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import controller as c
from protocol import write,read,acknowledged

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_ack_requires_same_case(self):
        case={'run_id':'one','trace':'on'}
        self.assertFalse(acknowledged(self.root,case))
        write(self.root/'trace_ready.json',{'run_id':'other','trace':'on'})
        with self.assertRaises(RuntimeError):acknowledged(self.root,case)
        write(self.root/'trace_ready.json',case);self.assertTrue(acknowledged(self.root,case))
        self.assertFalse(list(self.root.glob('*.tmp')))
    def test_preexisting_trace_not_touched(self):
        w=c.Wpr(self.root,True)
        with patch.object(c,'command',return_value=(0,'WPR recording is in progress')) as call:
            with self.assertRaises(RuntimeError):w.start()
            w.stop();self.assertEqual(call.call_count,1);self.assertFalse(w.owned)
    def test_timeout_start_still_checks_own_instance(self):
        w=c.Wpr(self.root,True)
        replies=[(0,'WPR is not recording'),subprocess.TimeoutExpired('wpr',45),(0,'WPR is not recording')]
        with patch.object(c,'command',side_effect=replies) as call:
            with self.assertRaises(subprocess.TimeoutExpired):w.start()
            self.assertTrue(w.owned);w.stop();self.assertFalse(w.owned)
            self.assertIn(c.INSTANCE,call.call_args.args[0]);self.assertNotIn('-cancel',str(call.call_args_list))
    def test_stop_failure_retains_ownership(self):
        w=c.Wpr(self.root,True);w.owned=w.started=True
        with patch.object(c,'command',side_effect=[(0,'WPR_initiated_'+c.INSTANCE+'_collector'),(1,'failed')]):
            with self.assertRaises(RuntimeError):w.stop()
        self.assertTrue(w.owned)
    def test_stop_retries_preserve_both_logs(self):
        w=c.Wpr(self.root,True);w.owned=w.started=True
        (self.root/'schedule.etl').write_bytes(b'offline-fixture')
        status=(0,'WPR_initiated_'+c.INSTANCE+'_collector')
        with patch.object(c,'command',side_effect=[status,(1,'failed'),status,(0,'stopped')]) as command:
            with self.assertRaises(RuntimeError):w.stop()
            w.stop()
        paths=[call.args[1].name for call in command.call_args_list]
        self.assertEqual(len(paths),len(set(paths)));self.assertFalse(w.owned)
    def test_trace_vanishing_is_failure(self):
        w=c.Wpr(self.root,True);w.owned=w.started=True
        with patch.object(c,'command',return_value=(0,'WPR is not recording')):
            with self.assertRaises(RuntimeError):w.stop()
        self.assertFalse(w.owned)
    def test_off_does_not_start_etw(self):
        w=c.Wpr(self.root,False)
        with patch.object(c,'command',return_value=(0,'WPR is not recording')) as call:w.start();w.stop()
        self.assertEqual(call.call_count,1)
    def test_existing_lock_prevents_child(self):
        (self.root/'active.lock').mkdir()
        with patch.object(c,'HERE',self.root),patch.object(c.subprocess,'Popen') as popen:
            with self.assertRaises(FileExistsError):c.capture('walk','on')
        popen.assert_not_called()
    def case_files(self,out,success=True):
        out.mkdir();root=out.parent;case=read(root/'case.json')
        write(root/'trace_request.json',{'run_id':case['run_id'],'trace':case['trace']})
        write(root/'trace_end_request.json',{})
        write(out/'complete.json',{'system_exit_code':0 if success else 1,'serialized':success})
        write(out/'shutdown.json',{'serialized':success,'errors':[],'SDK_errors':[],'readers':[],'SDK':{'stops':1}})
    def test_success_and_child_failure_cleanup(self):
        for success in (True,False):
            root=self.root/str(success);root.mkdir();write(root/'frozen_sources.json',{'files':{}});write(root/'dependencies.json',{'files':{}})
            class Child:
                returncode=0
                def poll(self):return None
                def wait(self,timeout):return 0
            def popen(args,**kwargs):self.case_files(Path(args[args.index('--output')+1]),success);return Child()
            with patch.object(c,'HERE',root),patch.object(c.subprocess,'Popen',side_effect=popen),patch.object(c.Wpr,'start'),patch.object(c.Wpr,'stop') as stop:
                code=c.capture('walk','on')
            self.assertEqual(code,0 if success else 1);self.assertFalse((root/'active.lock').exists());self.assertTrue(stop.called)
            folder=next((root/'runs').iterdir());self.assertEqual(read(folder/'controller_result.json')['valid_capture'],success)
    def test_uncertain_trace_cleanup_keeps_lock_and_invalidates(self):
        write(self.root/'frozen_sources.json',{'files':{}});write(self.root/'dependencies.json',{'files':{}})
        class Child:
            returncode=0
            def poll(self):return None
            def wait(self,timeout):return 0
        def popen(args,**kwargs):self.case_files(Path(args[args.index('--output')+1]));return Child()
        def start(wpr):wpr.owned=True
        with patch.object(c,'HERE',self.root),patch.object(c.subprocess,'Popen',side_effect=popen),patch.object(c.Wpr,'start',start),patch.object(c.Wpr,'stop',side_effect=RuntimeError('stop failure')):
            self.assertEqual(c.capture('walk','on'),1)
        self.assertTrue((self.root/'active.lock/owner.json').exists())
        root=next((self.root/'runs').iterdir());self.assertFalse(read(root/'controller_result.json')['valid_capture'])
    def test_start_failure_never_acknowledged(self):
        write(self.root/'frozen_sources.json',{'files':{}});write(self.root/'dependencies.json',{'files':{}})
        class Child:
            returncode=1
            def poll(self):return None
            def wait(self,timeout):return 1
        def popen(args,**kwargs):
            out=Path(args[args.index('--output')+1]);out.mkdir();case=read(out.parent/'case.json')
            write(out.parent/'trace_request.json',{'run_id':case['run_id'],'trace':case['trace']});return Child()
        with patch.object(c,'HERE',self.root),patch.object(c.subprocess,'Popen',side_effect=popen),patch.object(c.Wpr,'start',side_effect=RuntimeError('start failed')),patch.object(c.Wpr,'stop'):
            self.assertEqual(c.capture('walk','on'),1)
        root=next((self.root/'runs').iterdir());self.assertFalse((root/'trace_ready.json').exists());self.assertTrue((root/'abort_request.json').exists())

if __name__=='__main__':unittest.main()
