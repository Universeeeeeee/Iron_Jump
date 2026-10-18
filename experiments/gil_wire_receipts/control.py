"""Same serve body and synthetic gates; add observer-local line/write ordinals."""
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('original_sdk_synthetic_control',HERE.parent/'gil_sdk_receipt_control/control.py')
legacy_control=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy_control)
from receipts import TextReceipts,WriteReceipts,compare_ascii_lines


def run_case(mode):
    holders={};original_input=legacy_control.Input;original_compile=legacy_control.compile_serve
    class ObservedInput(original_input):
        def __init__(self):
            super().__init__();holders['input']=self
            def accepted(data):
                line=data.decode('ascii');value=json.loads(line);return self._send_unwrapped(value,data)
            self.writes=WriteReceipts(accepted)
        def _send_unwrapped(self,value,data):
            seq=len(self.sent)+1;line=data.decode('ascii')
            self.sent.append(dict(sequence=seq,observed_ns=__import__('time').perf_counter_ns(),value=value));self.queue.put((seq,line));return len(data)
        def send(self,value):
            data=(json.dumps(value,separators=(',',':'))+'\n').encode('ascii');self.writes(data);return len(self.sent)
    def compile_observed(source,input_stream,*args):
        tap=TextReceipts(input_stream);holders['tap']=tap
        return original_compile(source,tap,*args)
    try:
        legacy_control.Input=ObservedInput;legacy_control.compile_serve=compile_observed
        result=legacy_control.run_case(mode)
    finally:legacy_control.Input=original_input;legacy_control.compile_serve=original_compile
    stream=holders['input'];tap=holders['tap'];result['sender_write_receipts']=stream.writes.rows;result['preparse_text_receipts']=tap.rows
    result['text_eof_observed']=tap.eof;result['text_read_errors']=tap.errors
    result['line_links']=compare_ascii_lines(stream.writes.rows,tap.rows)
    return result


if __name__=='__main__':
    folder=HERE/'runs/synthetic01';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir()
    status=dict(cases={},errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        for mode in ('before_runtime','constructor_gap','inactive_runtime','wrong_generation'):
            value=run_case(mode)
            with (folder/(mode+'.json')).open('x') as f:json.dump(value,f,indent=2)
            status['cases'][mode]=mode+'.json';assert value['line_links']['receipt_link_pass'] and not value['errors'] and value['returncode']==0
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        status['lock_retained']=(folder/'active.lock').is_dir()
        with (folder/'result01.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status,indent=2));raise SystemExit(bool(status['errors']))
