import copy
from pathlib import Path
import unittest
import verify

ROOT=Path(__file__).resolve().parents[2]


class DynamicChecks(unittest.TestCase):
    def fixture(self):
        anchor=dict(frequency=10**9,qpc_before=0,qpc_after=0,perf_before_ns=0,perf_after_ns=0)
        counters=[dict(pid=10,tid=t,creation_100ns=t,active=True,cycles=5,user_100ns=0,kernel_100ns=0,start=anchor,end=anchor) for t in (22,23,24,25)]
        record=dict(anchors=[anchor],before=counters,after=copy.deepcopy(counters),ready=dict(pid=10,tids={'1':22,'2':24,'heartbeat':23,'native_beat':25}),oracle=[[0,1,2,1,22,10,2],[120,121,2,1,22,20,2],[150,151,4,2,24,30,4],[220,221,4,2,24,40,4],[300,301,6,0,0,100,6]],external_begin_ns=90,external_end_ns=230,complete=dict(completed=True,heartbeat=101,host_ns=300),errors=[],capture_complete=True,target_returncode=0,observer_returncode=0,target_still_running=False,observer_still_running=False,free_running_controls=[[[0,1,0,0,0,1,0],[10,11,0,0,0,2,0]]])
        modules=[]
        for base,path,sha,syms in [(100,'ntdll.dll','system',{1:'NtDelayExecution',2:'NtWaitForSingleObject',9:'RtlUserThreadStart'}),(200,'kernel32.dll','system',{1:'SleepEx',9:'BaseThreadInitThunk'}),(300,'python311.dll','python',{1:'take_gil',2:'PyEval_RestoreThread'}),(400,'DynamicOracle.dll','oracle',{1:None})]:
            matched=base!=400
            modules.append(dict(base=base,path=path,image_sha256=sha,image_size=100,pdb_matched=matched,pdb_unmatched=False,codeview=[dict(guid='g',age=1)],pdb_identity=dict(guid='g',age=1),loaded_guid='g',loaded_age=1,resolved=[dict(address=base+r,module_base=base,module_offset=r,symbol=n,pdb_matched=matched) for r,n in syms.items()]))
        def native(tid,ips):return dict(tid=tid,context_ip=ips[0],frames=[dict(address=a,module_base=a//100*100,module_offset=a%100) for a in ips],stopped_by='StackWalk64 returned false')
        samples=[]
        for i,(phase,tid,beat) in enumerate([(1,22,15),(2,24,35)]):
            t=100+i*100;values=[phase*2,phase,tid,beat]
            probes=[dict(qpc_begin=t+a,qpc_end=t+b,values=list(values)) for a,b in [(0,0),(1,2),(7,8),(10,11)]]
            probes[0]['values'][3]-=1;probes[-1]['values'][3]+=1
            samples.append(dict(kind='sample',ordinal=i,pid=10,qpc_begin=t,suspended_qpc=t+1,resume_returned_qpc=t+9,qpc_end=t+10,resolve_begin_qpc=t+11,resolve_end_qpc=t+12,oracle_reads=probes,activity_flags_valid=False,traces=[dict(pid=10,os_thread_id=tid,owns_gil=True,frames=[dict(name='hold_a' if phase==1 else 'hold_b')]),dict(pid=10,os_thread_id=23,owns_gil=False,frames=[dict(name='heartbeat')])],native=[native(tid,[101,201,401,209,109]),native(23,[102,301,302,209,109])]))
        rows=[dict(kind='init',schema=3,error=None,pid=10,qpc_frequency=10**9,qpc_end=80,activity_flags_valid=False),*samples,dict(kind='complete',pid=10,samples_written=2,qpc=225)]
        return record,rows,dict(count=2,eligible_floor=2,per_holder_floor=1,free_running_count=1,clock_uncertainty_ns_max=1000,oracle_dll_sha256='oracle'),dict(modules=modules)

    def check(self,r,s,p,m):return verify.inspect(r,s,p,m,ROOT)

    def test_pass_is_synthetic_only(self):
        v=self.check(*self.fixture());self.assertTrue(v['dynamic_synthetic_control_pass']);self.assertFalse(v['field_attribution_ready']);self.assertFalse(v['actual_load_disturbance_pass'])

    def test_native_heartbeat_progress_inside_pause_fails(self):
        r,s,p,m=self.fixture();s[1]['oracle_reads'][2]['values'][3]+=1;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_stuck_heartbeat_negative_control_fails(self):
        r,s,p,m=self.fixture();r['free_running_controls'][0][1][5]=1;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_probe_outside_pause_fails(self):
        r,s,p,m=self.fixture();s[1]['oracle_reads'][2]['qpc_end']=110;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_wrong_python_function_fails(self):
        r,s,p,m=self.fixture();s[2]['traces'][0]['frames'][0]['name']='hold_a';self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_external_identity_mismatch_fails(self):
        r,s,p,m=self.fixture();s[1]['oracle_reads'][1]['values'][2]=99;s[1]['oracle_reads'][2]['values'][2]=99;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_transition_unknown_cannot_fill_coverage(self):
        r,s,p,m=self.fixture();r['oracle'][1][2]=4;v=self.check(r,s,p,m);self.assertFalse(v['dynamic_synthetic_control_pass']);self.assertEqual(len(v['unknown']),1)

    def test_root_truncation_fails(self):
        r,s,p,m=self.fixture();s[1]['native'][0]['frames'].pop();self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_loaded_pdb_identity_mismatch_fails(self):
        r,s,p,m=self.fixture();m['modules'][0]['loaded_age']=2;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_counters_do_not_allow_reused_tid(self):
        r,s,p,m=self.fixture();r['after'][0]['creation_100ns']+=1;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_false_activity_validity_fails(self):
        r,s,p,m=self.fixture();s[1]['activity_flags_valid']=True;self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])

    def test_missing_terminal_recovery_fails(self):
        r,s,p,m=self.fixture();r['complete']['heartbeat']=r['oracle'][-2][5];self.assertFalse(self.check(r,s,p,m)['dynamic_synthetic_control_pass'])


if __name__=='__main__':unittest.main()
