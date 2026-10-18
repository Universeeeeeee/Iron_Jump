import copy
from pathlib import Path
import unittest
import verify

ROOT=Path(__file__).resolve().parents[2]


class WaiterChecks(unittest.TestCase):
    def fixture(self):
        anchor=dict(frequency=10**9,qpc_before=0,qpc_after=0,perf_before_ns=0,perf_after_ns=0)
        def counters(tid):return [dict(pid=10,tid=t,creation_100ns=t,active=True,cycles=5,user_100ns=0,kernel_100ns=0,start=anchor,end=anchor) for t in (tid,23,25)]
        record=dict(ready=dict(pid=10,tids={'1':22,'2':24,'waiter':23,'native_beat':25}),phases={},oracle=[[0,1,2,1,22,10,2,1,0,25],[120,121,2,1,22,20,2,1,0,25],[150,151,4,2,24,30,4,2,1,25],[220,221,4,2,24,40,4,2,1,25],[300,301,6,0,0,100,6,2,2,25]],free_running_controls=[[[0,1,0,0,0,1,0],[10,11,0,0,0,2,0]]],complete=dict(completed=True,pid=10,acquired=2,heartbeat=101),capture_complete=True,target_returncode=0,errors=[],target_still_running=False,observer_still_running=False,lock_retained=True)
        modules=[]
        for base,path,sha,syms in [(100,'ntdll.dll','system',{1:'NtDelayExecution',2:'NtWaitForSingleObject',9:'RtlUserThreadStart'}),(200,'kernel32.dll','system',{1:'SleepEx',9:'BaseThreadInitThunk'}),(300,'python311.dll','python',{1:'take_gil',2:'PyGILState_Ensure'}),(400,'WaiterOracle.dll','oracle',{1:None})]:
            matched=base!=400
            modules.append(dict(base=base,path=path,image_sha256=sha,image_size=100,pdb_matched=matched,pdb_unmatched=False,codeview=[dict(guid='g',age=1)],pdb_identity=dict(guid='g',age=1),loaded_guid='g',loaded_age=1,resolved=[dict(address=base+r,module_base=base,module_offset=r,symbol=n,pdb_matched=matched) for r,n in syms.items()]))
        def native(tid,ips):return dict(tid=tid,context_ip=ips[0],frames=[dict(address=a,module_base=a//100*100,module_offset=a%100) for a in ips],stopped_by='StackWalk64 returned false')
        streams={}
        for phase,tid,beat in [(1,22,15),(2,24,35)]:
            t=phase*100;values=[phase*2,phase,tid,beat]
            probes=[dict(qpc_begin=t+a,qpc_end=t+b,values=list(values)) for a,b in [(0,0),(1,2),(7,8),(10,11)]]
            probes[0]['values'][3]-=1;probes[-1]['values'][3]+=1
            sample=dict(kind='sample',ordinal=0,pid=10,qpc_begin=t,suspended_qpc=t+1,resume_returned_qpc=t+9,qpc_end=t+10,resolve_begin_qpc=t+11,resolve_end_qpc=t+12,oracle_reads=probes,activity_flags_valid=False,traces=[dict(pid=10,os_thread_id=tid,owns_gil=True,frames=[dict(name='hold_a' if phase==1 else 'hold_b')]),dict(pid=10,os_thread_id=23,owns_gil=False,frames=[])],native=[native(tid,[101,201,401,209,109]),native(23,[102,301,302,209,109])])
            streams[str(phase)]=[dict(kind='init',schema=4,error=None,pid=10,qpc_frequency=10**9,qpc_end=t-20,activity_flags_valid=False,synthetic_probe_enabled=True),sample,dict(kind='complete',pid=10,samples_written=1,qpc=t+25)]
            cs=counters(tid);record['phases'][str(phase)]=dict(anchors=[anchor],before=cs,after=copy.deepcopy(cs),external_begin_ns=t-10,external_end_ns=t+30,done=dict(phase=phase,acquired=phase,host_ns=t+40),observer_returncode=0)
        return record,streams,dict(count_per_phase=1,free_running_count=1,clock_uncertainty_ns_max=1000,oracle_dll_sha256='oracle'),dict(modules=modules)

    def check(self,*args):return verify.inspect(*args,ROOT)
    def test_pass_is_control_only(self):
        v=self.check(*self.fixture());self.assertTrue(v['deterministic_waiter_control_pass']);self.assertFalse(v['field_attribution_ready']);self.assertFalse(v['actual_load_disturbance_pass'])
    def test_acquired_marker_inside_window_rejected(self):
        r,s,p,m=self.fixture();r['oracle'][1][8]=1;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_unrequested_native_wait_rejected(self):
        r,s,p,m=self.fixture();r['oracle'][0][7]=0;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_take_gil_missing_rejected(self):
        r,s,p,m=self.fixture();m['modules'][2]['resolved'][0]['symbol']='pysleep';self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_native_waiter_is_not_python_heartbeat(self):
        r,s,p,m=self.fixture();s['1'][1]['traces'][1]['frames']=[dict(name='heartbeat')];self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_owner_function_mismatch_rejected(self):
        r,s,p,m=self.fixture();s['2'][1]['traces'][0]['frames'][0]['name']='hold_a';self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_native_heartbeat_motion_rejected(self):
        r,s,p,m=self.fixture();s['1'][1]['oracle_reads'][2]['values'][3]+=1;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_stuck_negative_control_rejected(self):
        r,s,p,m=self.fixture();r['free_running_controls'][0][1][5]=1;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_root_truncation_rejected(self):
        r,s,p,m=self.fixture();s['1'][1]['native'][1]['frames'].pop();self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_unmatched_pdb_rejected(self):
        r,s,p,m=self.fixture();m['modules'][2]['loaded_age']=2;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_reused_tid_rejected(self):
        r,s,p,m=self.fixture();r['phases']['1']['after'][0]['creation_100ns']+=1;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_foreign_counter_tid_rejected(self):
        r,s,p,m=self.fixture();r['phases']['1']['before'][0]['tid']=99;r['phases']['1']['after'][0]['tid']=99;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_missing_recovery_rejected(self):
        r,s,p,m=self.fixture();r['complete']['acquired']=1;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])
    def test_lost_lock_rejected(self):
        r,s,p,m=self.fixture();r['lock_retained']=False;self.assertFalse(self.check(r,s,p,m)['deterministic_waiter_control_pass'])


if __name__=='__main__':unittest.main()
