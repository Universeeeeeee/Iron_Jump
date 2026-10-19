"""Reuse exact native probe at model-thread boundaries; explicitly perturbs startup."""
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time

ROOT=Path(__file__).resolve().parents[2]

def probe(folder,label):
    source=ROOT/'experiments/cpu_execution_probe/probe.py'
    spec=importlib.util.spec_from_file_location('phase_native_'+label,source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    destination=folder/label;destination.mkdir(exist_ok=False)
    module.HERE=destination
    (destination/'plan01.json').write_bytes((source.parent/'plan01.json').read_bytes())
    begin=time.perf_counter_ns();tid=threading.get_native_id();code=module.run();end=time.perf_counter_ns()
    if code:raise RuntimeError('Native stage failed: '+label)
    result=json.loads((destination/'result01.json').read_text())
    if not result['complete'] or result['errors'] or not result['memory_released']:raise RuntimeError('Native stage incomplete')
    return dict(label=label,tid=tid,begin_ns=begin,end_ns=end,result_sha256=hashlib.sha256((destination/'result01.json').read_bytes()).hexdigest())

class Boundaries:
    def __init__(self,folder,reader=probe,clock=time.perf_counter_ns):
        self.folder=folder;self.reader=reader;self.clock=clock;self.rows=[];self.open_count=0;self.close_count=0
    def opened(self,original):
        def call(adapter,*args,**kwargs):
            self.open_count+=1
            if self.open_count!=1:raise RuntimeError('Unexpected model reopen; preserve window')
            self.rows.append(self.reader(self.folder,'before_open'))
            begin=self.clock()
            try:result=original(adapter,*args,**kwargs)
            except BaseException:
                self.rows.append(dict(label='original_open',begin_ns=begin,end_ns=self.clock(),success=False,tid=threading.get_native_id()));raise
            self.rows.append(dict(label='original_open',begin_ns=begin,end_ns=self.clock(),success=True,tid=threading.get_native_id()))
            self.rows.append(self.reader(self.folder,'after_open'))
            return result
        return call
    def closed(self,original):
        def call(adapter,*args,**kwargs):
            self.close_count+=1
            if self.close_count!=1:raise RuntimeError('Unexpected model reclose; preserve window')
            begin=self.clock()
            try:result=original(adapter,*args,**kwargs)
            except BaseException:
                self.rows.append(dict(label='original_close',begin_ns=begin,end_ns=self.clock(),success=False,tid=threading.get_native_id()));raise
            self.rows.append(dict(label='original_close',begin_ns=begin,end_ns=self.clock(),success=True,tid=threading.get_native_id()))
            self.rows.append(self.reader(self.folder,'after_close'))
            return result
        return call
    def save(self):
        with (self.folder/'boundaries.json').open('x') as f:
            json.dump(dict(rows=self.rows,open_count=self.open_count,close_count=self.close_count,latency_qualification=False),f,indent=2)

    def install(self,adapter_class):
        # Patch the base before the existing audit installs its outer wrappers.
        # Patching only _PreviewAdapter would bypass those base-class audit wrappers.
        original_open,original_close=adapter_class.open,adapter_class.close
        adapter_class.open=self.opened(original_open);adapter_class.close=self.closed(original_close)
        return original_open,original_close
