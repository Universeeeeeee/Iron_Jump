import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
spec=importlib.util.spec_from_file_location('new_wire_parent',HERE/'parent.py');parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
spec=importlib.util.spec_from_file_location('new_wire_link',HERE/'link.py');link=importlib.util.module_from_spec(spec);spec.loader.exec_module(link)
from camera.control_service import CameraControlService
from qtpy.QtCore import QCoreApplication,QProcess
from workload import Audit

def wait(app,predicate):
    deadline=time.monotonic()+5
    while not predicate():
        if time.monotonic()>deadline:raise TimeoutError('Synthetic fixture event')
        app.processEvents();time.sleep(.001)
    app.processEvents()


class Links(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.app=QCoreApplication.instance() or QCoreApplication([]);cls.sources={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ('camera/control_service.py','camera/tracking_runtime.py','camera/pose_tracking.py')}
        cls.original=CameraControlService.__init__;audit=parent.Parent(Path(cls.temp.name),HERE/'fixture_child.py');audit.install()
        control=CameraControlService();acks=[];closed=[];work=Audit();control.completed.connect(lambda m,c:acks.append([m,c]));control.closed.connect(lambda:closed.append(True));control.tracking_event.connect(lambda v:work.sdk(0,v))
        try:
            control.request('tracking_start',1);wait(cls.app,lambda:['tracking_start',0] in acks)
            ready=dict(status='ready',inference=None,identity=None,framing=None);packet=dict(generation=1,barrier_sequence=2,barrier=ready,update=ready)
            for index in range(2):
                data=(json.dumps(dict(pose_packet=packet))+'\n').encode('ascii')
                for chunk in ([data[:7],data[7:]] if index==0 else [data]):control._process.write(chunk)
                work.event('relay_packets',packet=link.packet(packet))
            wait(cls.app,lambda:sum(x['data']['event']=='pose_input' for x in work.rows['sdk_events'])==2)
            control.request('tracking_stop');wait(cls.app,lambda:['tracking_stop',0] in acks);control.close();wait(cls.app,lambda:bool(closed) and control._process.state()==QProcess.NotRunning)
            cls.parent=audit.finish();cls.child=json.loads((Path(cls.temp.name)/'wire/child_0/receipts.json').read_text());cls.workload=dict(pid=work.pid,rows=work.rows)
        finally:
            CameraControlService.__init__=cls.original
            if control._process.state()!=QProcess.NotRunning:
                control.close();wait(cls.app,lambda:control._process.state()==QProcess.NotRunning)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def check(self,p=None,c=None,w=None):return link.inspect(p or self.parent,c or self.child,w or self.workload,self.sources)
    def test_real_parent_with_original_child_functions(self):self.assertTrue(self.check()['wire_delivery_pass'],self.check())
    def test_duplicate_packets_have_two_closed_occurrences(self):
        result=self.check();self.assertEqual(result['counts']['pose_lines'],2);self.assertEqual(result['counts']['runtime_packet_calls'],2);self.assertEqual(result['counts']['mailbox_submit_calls'],3)
    def test_real_chunk_split_preserves_independent_stream(self):self.assertGreater(self.check()['counts']['write_calls'],self.check()['counts']['text_lines']);self.assertTrue(self.check()['checks']['independent_read_receipts'])
    def test_deleted_receipt_fails_without_classifying_absence(self):
        c=copy.deepcopy(self.child);c['rows'].pop();r=self.check(c=c);self.assertFalse(r['wire_delivery_pass']);self.assertEqual(r['read_pose_sequences_without_runtime'],[])
    def test_partial_write_rejected(self):
        p=copy.deepcopy(self.parent);p['controls'][0]['writes'][0]['reported_accepted_bytes']-=1;self.assertFalse(self.check(p=p)['checks']['write_acceptance'])
    def test_wrong_PID_rejected(self):
        p=copy.deepcopy(self.parent);p['controls'][0]['started'][0]['sdk_pid']=-1;self.assertFalse(self.check(p=p)['checks']['PID_and_exit'])
    def test_missing_pose_log_rejected(self):
        w=copy.deepcopy(self.workload);w['rows']['sdk_events']=[x for x in w['rows']['sdk_events'] if x['data']['event']!='pose_input'];self.assertFalse(self.check(w=w)['checks']['runtime_to_original_pose_logs'])
    def test_unknown_runtime_occurrence_rejected(self):
        c=copy.deepcopy(self.child);c['events'][0]['line_sequence']=999;self.assertFalse(self.check(c=c)['wire_delivery_pass'])
    def test_wrong_reader_TID_rejected(self):
        c=copy.deepcopy(self.child);c['events'][0]['tid']=-1;self.assertFalse(self.check(c=c)['checks']['reader_event_identity'])
    def test_changed_source_rejected(self):
        c=copy.deepcopy(self.child);c['source_sha256']['camera/control_service.py']='wrong';self.assertFalse(self.check(c=c)['wire_delivery_pass'])
    def test_unconfirmed_EOF_rejected(self):
        c=copy.deepcopy(self.child);c['eof']=False;self.assertFalse(self.check(c=c)['checks']['EOF_and_reader_exit'])
    def test_relay_metadata_mismatch_rejected(self):
        w=copy.deepcopy(self.workload);w['rows']['relay_packets'][0]['packet']['generation']=-1;self.assertFalse(self.check(w=w)['checks']['relay_to_write_occurrences'])
    def test_unknown_event_stage_rejected(self):
        c=copy.deepcopy(self.child);c['events'][0]['stage']='invented';self.assertFalse(self.check(c=c)['checks']['known_stage_names'])
    def test_cross_process_clock_contradiction_rejected(self):
        p=copy.deepcopy(self.parent)
        for x in p['controls'][0]['writes']:x['write_begin_ns']+=10**12;x['write_end_ns']+=10**12
        self.assertFalse(self.check(p=p)['checks']['independent_causal_clock'])


if __name__=='__main__':unittest.main()
