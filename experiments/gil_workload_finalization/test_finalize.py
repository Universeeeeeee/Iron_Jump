import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import weakref

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from finalize import RetainedAudit,finalize,prefix_equal
from vision.service import FootVisionService
from vision.foot_reference import VisionConfig


def service_fixture():
    audit=RetainedAudit();ready=threading.Event();entered=threading.Event();release=threading.Event()
    class Adapter:
        def __init__(self,path):self.is_open=False
        def open(self):
            before=time.perf_counter_ns();self.is_open=True
            audit.event('model_open',adapter=id(self),begin_ns=before,end_ns=time.perf_counter_ns(),is_open=True,error=None)
        def infer_bgr(self,*args):raise AssertionError('No frames in finalization tests')
        def close_body(self):
            before=time.perf_counter_ns();entered.set();assert release.wait(3);self.is_open=False
            audit.event('model_close',adapter=id(self),begin_ns=before,end_ns=time.perf_counter_ns(),is_open=False,error=None)
    Adapter.close=audit.close_entry(Adapter.close_body)
    svc=FootVisionService(VisionConfig(),'no-model',adapter_factory=Adapter);audit.retained_services[0]=svc;audit.services.append(weakref.ref(svc));audit.tags[svc]=0
    def status(value):
        audit.event('service_status',service=0,status=value)
        if value=='ready':ready.set()
    svc.status_changed.connect(status);svc.start();assert ready.wait(1);worker=svc._thread;svc.stop(.001);assert entered.wait(1)
    return audit,svc,worker,release


class FinalizeTests(unittest.TestCase):
    def test_two_phases_preserve_unconfirmed_return(self):
        audit,svc,worker,release=service_fixture();saved={}
        def write(name,value):
            saved[name]=copy.deepcopy(value)
            if name=='application_return.json':release.set()
        try:
            result=finalize(audit,write,2,dict(success=True))
            self.assertTrue(result['metadata_finalization_pass']);self.assertFalse(result['application_return_model_confirmed'])
            self.assertEqual(saved['application_return.json']['snapshot']['running_services'],[0]);self.assertEqual(saved['observer_tail.json']['running_services'],[])
            self.assertTrue(prefix_equal(saved['application_return.json']['snapshot'],saved['observer_tail.json']))
            self.assertFalse(worker.is_alive())
        finally:release.set();worker.join(2)

    def test_timeout_never_becomes_cleanup_success(self):
        audit,svc,worker,release=service_fixture();saved={}
        try:
            result=finalize(audit,lambda name,value:saved.setdefault(name,copy.deepcopy(value)),0,dict(success=True))
            self.assertFalse(result['metadata_finalization_pass']);self.assertFalse(result['checks']['no_join_timeout']);self.assertTrue(worker.is_alive())
            before=json.dumps(saved,sort_keys=True);release.set();worker.join(2);self.assertEqual(json.dumps(saved,sort_keys=True),before)
        finally:release.set();worker.join(2)

    def test_application_failure_retained_even_if_tail_closes(self):
        audit,svc,worker,release=service_fixture();saved={}
        def write(name,value):
            saved[name]=copy.deepcopy(value)
            if name=='application_return.json':release.set()
        try:
            result=finalize(audit,write,2,dict(success=False,error='injected application failure'))
            self.assertFalse(result['metadata_finalization_pass']);self.assertTrue(result['checks']['final_model_checks']);self.assertEqual(saved['application_return.json']['application_outcome']['error'],'injected application failure')
        finally:release.set();worker.join(2)

    def test_changed_prefix_rejected(self):
        audit,svc,worker,release=service_fixture()
        try:
            first=audit.finish();release.set();worker.join(2);last=audit.finish();self.assertTrue(prefix_equal(first,last))
            last['rows']['model_open'][0]['adapter']+=1;self.assertFalse(prefix_equal(first,last))
        finally:release.set();worker.join(2)

    def test_write_failure_is_not_masked(self):
        audit,svc,worker,release=service_fixture()
        def fail(*args):raise OSError('injected write failure')
        try:
            with self.assertRaises(OSError):finalize(audit,fail,0,dict(success=True))
            self.assertTrue(worker.is_alive())
        finally:release.set();worker.join(2)


class EntryTests(unittest.TestCase):
    def test_new_entry_bootstrap_and_original_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);root=base/'repo';here=root/'experiments/diag';old=root/'experiments/gil_gui_calibration';outside=base/'outside'
            for p in (here,old,root/'vision',outside):p.mkdir(parents=True)
            shutil.copyfile(Path(__file__).parent/'entry01.py',here/'entry01.py');(root/'vision/__init__.py').write_text("marker='correct-root'\n")
            (old/'atomic_io03.py').write_text("import json\ndef write(p,v):\n    with p.open('x') as f:json.dump(v,f)\n")
            (old/'winapi.py').write_text("def anchor():return {'test':True}\n")
            (here/'finalize.py').write_text("class RetainedAudit:\n    def install(self):\n        import vision\n        assert vision.marker=='correct-root'\ndef finalize(a,write,timeout,outcome):\n    write('application_return.json',outcome);write('observer_tail.json',{'marker':'finalized'});return {'metadata_finalization_pass':True}\n")
            (old/'entry02.py').write_text("import sys\nfrom pathlib import Path\np=Path(sys.argv[sys.argv.index('--output')+1]);p.mkdir();(p/'measurement.json').write_text('{}');raise SystemExit(0)\n")
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            p=subprocess.run([sys.executable,str(here/'entry01.py'),'--output',str(base/'capture')],cwd=outside,env=env,capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertTrue(json.loads((base/'capture/application_return.json').read_text())['success']);self.assertEqual(json.loads((base/'capture/workload_final.json').read_text())['marker'],'finalized')


if __name__=='__main__':unittest.main()
