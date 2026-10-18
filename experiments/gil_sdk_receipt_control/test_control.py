import ast
import copy
import json
from pathlib import Path
import unittest
from control import Input,ready_packet,run_case


class ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.cases={mode:run_case(mode) for mode in ('before_runtime','constructor_gap','inactive_runtime','wrong_generation')}
    def test_read_before_runtime_is_not_logged_as_pose_input(self):
        r=self.cases['before_runtime'];sent=[x for x in r['input_sent'] if 'pose_packet' in x['value']];reads=[x for x in r['raw_line_reads'] if 'pose_packet' in json.loads(x['line'])];logs=[x for x in r['original_replies'] if x['value'].get('tracking_log',{}).get('event')=='pose_input']
        self.assertEqual(len(sent),2);self.assertEqual(len(reads),2);self.assertEqual(len(logs),1);self.assertEqual(sent[0]['value'],sent[1]['value']);self.assertTrue(r['early_line_read_without_runtime'])
        self.assertIn(r['early_pose_sequence'],r['original_reader_processed_sequences']);self.assertEqual(logs[0]['value']['tracking_log']['packet'],sent[1]['value']['pose_packet'])
    def test_start_command_read_does_not_imply_runtime_exists(self):
        r=self.cases['constructor_gap'];self.assertTrue(r['early_line_read_without_runtime']);self.assertEqual(len(r['runtime_submit_calls']),1)
    def test_inactive_runtime_still_logs_receipt(self):
        r=self.cases['inactive_runtime'];self.assertEqual(len(r['runtime_submit_calls']),1);call=r['runtime_submit_calls'][0];self.assertFalse(call['before']['active']);self.assertEqual(call['before']['barrier_sequence'],call['after']['barrier_sequence'])
    def test_wrong_generation_still_logs_receipt(self):
        r=self.cases['wrong_generation'];call=r['runtime_submit_calls'][0];self.assertNotEqual(call['packet']['generation'],call['before']['generation']);self.assertEqual(call['before']['barrier_sequence'],call['after']['barrier_sequence'])
    def test_fake_hardware_closed_and_reader_finished(self):
        for r in self.cases.values():
            self.assertEqual(r['returncode'],0);self.assertFalse(r['serve_thread_alive']);self.assertFalse(r['errors']);self.assertEqual(len(r['raw_line_reads']),len(r['input_sent']));self.assertEqual(r['fake_sdk_calls'][-1]['kind'],'control_closed')
    def test_sdk_calls_stay_on_serve_owner(self):
        for r in self.cases.values():
            owners={x['tid'] for x in r['fake_sdk_calls']};readers={x['tid'] for x in r['raw_line_reads']};self.assertEqual(len(owners),1);self.assertEqual(len(readers),1);self.assertTrue(owners.isdisjoint(readers))


class InputTests(unittest.TestCase):
    def test_read_sequence_does_not_modify_wire_payload(self):
        stream=Input();value=ready_packet();before=copy.deepcopy(value);seq=stream.send(value);self.assertEqual(json.loads(next(stream)),before);self.assertEqual(value,before);self.assertEqual(stream.consumed[0]['sequence'],seq);self.assertNotIn('sequence',json.loads(stream.consumed[0]['line']))
    def test_eof_marks_previous_body_complete(self):
        stream=Input();seq=stream.send(ready_packet());next(stream);self.assertNotIn(seq,stream.processed);stream.close()
        with self.assertRaises(StopIteration):next(stream)
        self.assertIn(seq,stream.processed)


if __name__=='__main__':unittest.main()
