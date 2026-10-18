import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from entry import Observer
spec=importlib.util.spec_from_file_location('new_entry_control',Path(__file__).parent/'control.py');control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)
MODES=control.MODES;QCoreApplication=control.QCoreApplication;run_case=control.run_case
spec=importlib.util.spec_from_file_location('new_entry_verify',Path(__file__).parent/'verify.py');verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
inspect=verify.inspect


class EntryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QCoreApplication.instance() or QCoreApplication([]);cls.temp=tempfile.TemporaryDirectory();cls.cases={}
        for mode in MODES:
            folder=Path(cls.temp.name)/mode;r=run_case(mode,folder,cls.app);c=json.loads((folder/'child/receipts.json').read_text());cls.cases[mode]=(r,c)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_original_serve_real_pipe_all_controls(self):
        for mode,(r,c) in self.cases.items():self.assertTrue(inspect(r,c)['synthetic_entry_pass'],(mode,inspect(r,c)))
    def test_identical_early_line_received_without_runtime_entry(self):
        for mode in ('before_runtime','constructor_gap'):
            r,c=self.cases[mode];early,late=r['target_sequences'];self.assertEqual(c['rows'][early-1]['text_utf8_sha256'],c['rows'][late-1]['text_utf8_sha256']);self.assertNotIn(early,[x['line_sequence'] for x in c['events']]);self.assertIn(late,[x['line_sequence'] for x in c['events']])
    def test_runtime_receipt_does_not_imply_mailbox_call(self):
        for mode in ('inactive_runtime','wrong_generation'):
            r,c=self.cases[mode];self.assertEqual(len(c['events']),1);self.assertEqual(c['events'][0]['stage'],'runtime_packet')
    def test_old_barrier_reaches_runtime_without_new_submit(self):
        r,c=self.cases['old_barrier'];self.assertEqual(sum(x['stage']=='runtime_packet' for x in c['events']),2);self.assertEqual(sum(x['stage']=='mailbox_submit' for x in c['events']),2)
    def test_parse_and_runtime_errors_do_not_become_complete_EOF(self):
        for mode in ('bad_json','bad_packet'):
            r,c=self.cases[mode];self.assertFalse(c['eof']);self.assertFalse(c['observation_complete']);self.assertTrue(c['rows']);self.assertTrue(r['errors'])
    def test_deleted_receipt_rejected(self):
        r,c=copy.deepcopy(self.cases['active']);c['rows'].pop();self.assertFalse(inspect(r,c)['synthetic_entry_pass'])
    def test_wrong_occurrence_rejected_even_with_identical_payload(self):
        r,c=copy.deepcopy(self.cases['before_runtime']);c['events'][0]['line_sequence']=r['target_sequences'][0];self.assertFalse(inspect(r,c)['checks']['runtime_line_occurrences'])
    def test_wrong_TID_rejected(self):
        r,c=copy.deepcopy(self.cases['active']);c['events'][0]['tid']=-1;self.assertFalse(inspect(r,c)['checks']['event_identity_and_bounds'])
    def test_wrong_nested_time_rejected(self):
        r,c=copy.deepcopy(self.cases['active']);c['events'][1]['end_ns']=c['events'][0]['end_ns']+1;self.assertFalse(inspect(r,c)['checks']['nested_call_bounds'])
    def test_unconfirmed_reader_rejected(self):
        r,c=copy.deepcopy(self.cases['active']);c['reader_exited']=False;self.assertFalse(inspect(r,c)['checks']['child_terminated'])
    def test_log_payload_corruption_rejected(self):
        r,c=copy.deepcopy(self.cases['active']);next(x for x in r['logs'] if x.get('event')=='pose_input')['packet']['generation']=99;self.assertFalse(inspect(r,c)['checks']['original_pose_log_payloads'])
    def test_wrong_child_PID_rejected(self):
        r,c=copy.deepcopy(self.cases['active']);r['QProcess_child_pid']=-1;self.assertFalse(inspect(r,c)['checks']['separate_PIDs'])
    def test_crash_status_is_rejected_even_with_zero_exitcode(self):
        r,c=copy.deepcopy(self.cases['active']);r['child_exit_normal']=False;self.assertFalse(inspect(r,c)['checks']['child_terminated'])


class HookTests(unittest.TestCase):
    def test_identity_return_and_exception_preserved(self):
        observer=Observer();value=object();result=object();seen=[]
        def original(x,*,keyword):seen.append((x,keyword));return result
        self.assertIs(observer.call('test',original,value,keyword=value),result);self.assertIs(seen[0][0],value);self.assertIs(seen[0][1],value)
        error=OSError('injected')
        def fail():raise error
        with self.assertRaises(OSError) as caught:observer.call('fail',fail)
        self.assertIs(caught.exception,error);self.assertEqual(observer.events[-1]['error'],'OSError')


if __name__=='__main__':unittest.main()
