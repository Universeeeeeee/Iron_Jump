import hashlib
import io
import unittest
from receipts import TextReceipts,WriteReceipts,compare_ascii_lines
from control import run_case


class ReceiptTests(unittest.TestCase):
    def test_iterator_preserves_exact_text_and_distinguishes_occurrences(self):
        line='{"pose_packet":{}}\n';tap=TextReceipts(iter([line,line]))
        self.assertIs(iter(tap),tap);self.assertEqual(list(tap),[line,line]);self.assertEqual([x['sequence'] for x in tap.rows],[1,2]);self.assertEqual(tap.rows[0]['text_utf8_sha256'],tap.rows[1]['text_utf8_sha256']);self.assertTrue(tap.eof)
    def test_whitespace_and_bad_json_are_not_normalized(self):
        lines=[' { "key" : 1 } \n','{bad json\n'];tap=TextReceipts(iter(lines));self.assertEqual(list(tap),lines)
        self.assertEqual(tap.rows[0]['text_utf8_sha256'],hashlib.sha256(lines[0].encode()).hexdigest())
    def test_unicode_is_text_not_raw_pipe_bytes(self):
        text='中文\n';tap=TextReceipts(iter([text]));self.assertEqual(next(tap),text);self.assertEqual(tap.rows[0]['characters'],3)
    def test_source_exception_preserved(self):
        error=OSError('injected')
        class Source:
            def __iter__(self):return self
            def __next__(self):raise error
        tap=TextReceipts(Source())
        with self.assertRaises(OSError) as caught:next(tap)
        self.assertIs(caught.exception,error);self.assertEqual(tap.errors[0]['type'],'OSError');self.assertFalse(tap.eof)
    def test_write_preserves_bytes_identity_and_return(self):
        seen=[];data=b'{ "x" : 1 }\n'
        def write(value):seen.append(value);return len(value)
        receipt=WriteReceipts(write);self.assertEqual(receipt(data),len(data));self.assertIs(seen[0],data)
        tap=TextReceipts(iter([data.decode('ascii')]));list(tap);self.assertTrue(compare_ascii_lines(receipt.rows,tap.rows)['receipt_link_pass'])
    def test_partial_and_failed_writes_remain_failures(self):
        data=b'{}\n'
        for accepted in (0,1,-1):
            receipt=WriteReceipts(lambda value:accepted);receipt(data);tap=TextReceipts(iter([data.decode()]));list(tap);self.assertFalse(compare_ascii_lines(receipt.rows,tap.rows)['receipt_link_pass'])
    def test_write_exception_preserved(self):
        error=OSError('injected')
        def fail(value):raise error
        receipt=WriteReceipts(fail)
        with self.assertRaises(OSError) as caught:receipt(b'{}\n')
        self.assertIs(caught.exception,error);self.assertEqual(receipt.rows[0]['error'],'OSError');self.assertIsNone(receipt.rows[0]['reported_accepted_bytes'])
    def test_read_eof_does_not_invent_line(self):
        tap=TextReceipts(iter([]));self.assertEqual(list(tap),[]);self.assertTrue(tap.eof);self.assertFalse(tap.rows)
    def test_line_ending_translation_is_not_claimed_byte_equal(self):
        receipt=WriteReceipts(lambda value:len(value));receipt(b'{}\r\n');tap=TextReceipts(io.StringIO('{}\n'));list(tap);self.assertFalse(compare_ascii_lines(receipt.rows,tap.rows)['receipt_link_pass'])
    def test_new_receipt_exists_before_original_json_failure(self):
        import json
        tap=TextReceipts(iter(['{bad\n']))
        with self.assertRaises(json.JSONDecodeError):json.loads(next(tap))
        self.assertEqual(len(tap.rows),1)


class InterleavingTests(unittest.TestCase):
    def test_all_wire_reads_match_even_when_runtime_count_does_not(self):
        for mode in ('before_runtime','constructor_gap','inactive_runtime','wrong_generation'):
            r=run_case(mode);self.assertTrue(r['line_links']['receipt_link_pass']);self.assertTrue(r['text_eof_observed']);self.assertFalse(r['text_read_errors'])
            self.assertEqual(len(r['sender_write_receipts']),len(r['preparse_text_receipts']))
            if mode in ('before_runtime','constructor_gap'):
                pose_logs=[x for x in r['original_replies'] if x['value'].get('tracking_log',{}).get('event')=='pose_input'];self.assertEqual(len(pose_logs),1)


if __name__=='__main__':unittest.main()
