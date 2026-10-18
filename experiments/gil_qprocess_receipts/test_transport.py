import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from verify import inspect

spec=importlib.util.spec_from_file_location('qt_receipt_synthetic',Path(__file__).parent/'control.py');control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=control.QCoreApplication.instance() or control.QCoreApplication([]);cls.temp=tempfile.TemporaryDirectory();cls.cases={}
        for name in ('lines','split','bad_json','close_buffered'):
            folder=Path(cls.temp.name)/name;r=control.run_case(name,folder,cls.app);child=json.loads((folder/'child_receipts.json').read_text());cls.cases[name]=(r,child)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_actual_QProcess_all_cases(self):
        for r,c in self.cases.values():self.assertTrue(inspect(r,c)['synthetic_QProcess_receipt_pass'],inspect(r,c))
    def test_split_chunks_need_stream_comparison(self):
        r,c=self.cases['split'];self.assertGreater(len(r['write_rows']),len(c['rows']));self.assertTrue(inspect(r,c)['checks']['complete_line_stream'])
    def test_bad_json_record_exists_before_parse_error(self):
        r,c=self.cases['bad_json'];bad=next(x for x in c['parsed'] if not x['parsed']);receipt=c['rows'][bad['sequence']-1];self.assertTrue(receipt['text_utf8_sha256'])
    def test_buffered_close_flushes_in_this_echo_control(self):
        r,c=self.cases['close_buffered'];self.assertTrue(inspect(r,c)['synthetic_QProcess_receipt_pass']);self.assertGreater(r['bytes_pending_before_close'],0)
    def test_missing_child_line_rejected(self):
        r,c=copy.deepcopy(self.cases['lines']);c['rows'].pop();self.assertFalse(inspect(r,c)['synthetic_QProcess_receipt_pass'])
    def test_digest_mismatch_rejected(self):
        r,c=copy.deepcopy(self.cases['lines']);c['rows'][0]['text_utf8_sha256']='wrong';self.assertFalse(inspect(r,c)['checks']['complete_line_stream'])
    def test_reported_partial_write_rejected(self):
        r,c=copy.deepcopy(self.cases['lines']);r['write_rows'][0]['reported_accepted_bytes']-=1;self.assertFalse(inspect(r,c)['checks']['all_writes_accepted'])
    def test_unconfirmed_stop_rejected(self):
        r,c=copy.deepcopy(self.cases['lines']);r['stop_confirmed']=False;self.assertFalse(inspect(r,c)['checks']['stopped_and_closed'])
    def test_reordered_lines_rejected(self):
        r,c=copy.deepcopy(self.cases['lines']);c['rows'][0],c['rows'][-1]=c['rows'][-1],c['rows'][0];self.assertFalse(inspect(r,c)['checks']['complete_line_stream'])


if __name__=='__main__':unittest.main()
