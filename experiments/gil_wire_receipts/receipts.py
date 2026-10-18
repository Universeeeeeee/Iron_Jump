"""Diagnostic receipts only: preserve text yielded and bytes passed to write()."""
import hashlib
import os
import threading
import time


class TextReceipts:
    def __init__(self,source):
        self._source=iter(source);self.rows=[];self.eof=False;self.errors=[]
    def __iter__(self):return self
    def __next__(self):
        begin=time.perf_counter_ns()
        try:line=next(self._source)
        except StopIteration:self.eof=True;raise
        except BaseException as exc:
            self.errors.append(dict(begin_ns=begin,end_ns=time.perf_counter_ns(),type=type(exc).__name__));raise
        end=time.perf_counter_ns()
        self.rows.append(dict(sequence=len(self.rows)+1,pid=os.getpid(),tid=threading.get_native_id(),read_begin_ns=begin,read_end_ns=end,
                              characters=len(line),text_utf8_sha256=hashlib.sha256(line.encode('utf-8')).hexdigest()))
        return line


class WriteReceipts:
    def __init__(self,write):self._write=write;self.rows=[]
    def __call__(self,data):
        begin=time.perf_counter_ns();result=None;error=None
        try:
            result=self._write(data);return result
        except BaseException as exc:error=type(exc).__name__;raise
        finally:
            end=time.perf_counter_ns()
            self.rows.append(dict(sequence=len(self.rows)+1,pid=os.getpid(),tid=threading.get_native_id(),write_begin_ns=begin,write_end_ns=end,
                                  requested_bytes=len(data),requested_sha256=hashlib.sha256(data).hexdigest(),reported_accepted_bytes=result,error=error))


def compare_ascii_lines(write_rows,read_rows):
    """One complete ASCII LF line per successful write, no stream normalization."""
    checks=dict(all_writes_accepted=all(x['error'] is None and x['reported_accepted_bytes']==x['requested_bytes'] for x in write_rows),
                counts=len(write_rows)==len(read_rows),write_sequences=[x['sequence'] for x in write_rows]==list(range(1,len(write_rows)+1)),
                read_sequences=[x['sequence'] for x in read_rows]==list(range(1,len(read_rows)+1)))
    checks['ordered_digests_match']=checks['counts'] and all(s['requested_sha256']==r['text_utf8_sha256'] and s['requested_bytes']==r['characters'] for s,r in zip(write_rows,read_rows))
    return dict(checks=checks,receipt_link_pass=all(checks.values()),
                scope='Only the tested one-ASCII-LF-line/write contract. Text receipt is after TextIO decoding, before JSON parsing; it is not raw kernel pipe bytes or business acceptance. Partial writes/normalization stay failed.')
