import copy
from pathlib import Path
import unittest
import verify

ROOT=Path(__file__).resolve().parents[2]


class CoherentNativeChecks(unittest.TestCase):
    def fixture(self):
        anchor=dict(frequency=10**9,qpc_before=0,qpc_after=0,perf_before_ns=0,perf_after_ns=0)
        counter=dict(pid=10,tid=22,creation_100ns=3,active=True,cycles=5,user_100ns=0,kernel_100ns=0,start=anchor,end=anchor)
        record=dict(anchors=[anchor],before=[counter],after=[copy.deepcopy(counter)],ready=dict(pid=10,tids=dict(native=22,heartbeat=23)),oracle=[[0,1,2,1,22,7,2],[120,121,2,1,22,7,2],[302,303,4,0,0,8,4]],external_begin_ns=90,external_end_ns=130,complete=dict(completed=True,heartbeat=8,host_ns=300),errors=[],target_returncode=0,observer_returncode=0,target_still_running=False,observer_still_running=False)
        modules=[]
        for base,path,sha,syms in [(100,'ntdll.dll','system',{1:'NtDelayExecution',2:'NtWaitForSingleObject',9:'RtlUserThreadStart'}),(200,'kernel32.dll','system',{1:'SleepEx',9:'BaseThreadInitThunk'}),(300,'python311.dll','python',{1:'take_gil',2:'PyEval_RestoreThread'}),(400,'NativeOwner.dll','oracle',{1:None})]:
            matched=base!=400
            modules.append(dict(base=base,path=path,image_sha256=sha,image_size=100,pdb_matched=matched,resolved=[dict(address=base+r,module_base=base,module_offset=r,symbol=n,pdb_matched=matched) for r,n in syms.items()]))
        def native(tid,ips):return dict(tid=tid,context_ip=ips[0],frames=[dict(address=a,module_base=(a//100)*100,module_offset=a%100) for a in ips],stopped_by='StackWalk64 returned false')
        sample=dict(kind='sample',ordinal=0,pid=10,qpc_begin=100,suspended_qpc=101,resume_returned_qpc=108,qpc_end=110,resolve_begin_qpc=111,resolve_end_qpc=120,activity_flags_valid=False,traces=[dict(pid=10,os_thread_id=22,owns_gil=True,frames=[]),dict(pid=10,os_thread_id=23,owns_gil=False,frames=[dict(name='heartbeat')])],native=[native(22,[101,201,401,209,109]),native(23,[102,301,302,209,109])])
        rows=[dict(kind='init',schema=2,error=None,pid=10,qpc_frequency=10**9,qpc_end=80,activity_flags_valid=False),sample,dict(kind='complete',pid=10,samples_written=1,qpc=125)]
        return record,rows,dict(count=1,eligible_floor=1,clock_uncertainty_ns_max=1000,oracle_dll_sha256='oracle'),dict(modules=modules)

    def check(self,r,s,p,m):return verify.inspect(r,s,p,m,ROOT)['coherent_native_control_pass']

    def test_complete_pair_is_control_only(self):
        r,s,p,m=self.fixture();v=verify.inspect(r,s,p,m,ROOT);self.assertTrue(v['coherent_native_control_pass']);self.assertFalse(v['field_attribution_ready']);self.assertFalse(v['actual_load_disturbance_pass'])

    def test_owner_id_mismatch_rejected(self):
        r,s,p,m=self.fixture();s[1]['traces'][0]['os_thread_id']=24;self.assertFalse(self.check(r,s,p,m))

    def test_ip_not_preserved_rejected(self):
        r,s,p,m=self.fixture();s[1]['native'][0]['context_ip']=103;self.assertFalse(self.check(r,s,p,m))

    def test_missing_native_root_rejected(self):
        r,s,p,m=self.fixture();s[1]['native'][0]['frames'].pop();self.assertFalse(self.check(r,s,p,m))

    def test_unmatched_pdb_name_not_proof(self):
        r,s,p,m=self.fixture();m['modules'][2]['pdb_matched']=False
        for f in m['modules'][2]['resolved']:f['pdb_matched']=False
        self.assertFalse(self.check(r,s,p,m))

    def test_heartbeat_progress_contradicts_oracle(self):
        r,s,p,m=self.fixture();r['oracle'][1][5]=8;self.assertFalse(self.check(r,s,p,m))

    def test_symbol_resolution_inside_read_rejected(self):
        r,s,p,m=self.fixture();s[1]['resolve_begin_qpc']=105;self.assertFalse(self.check(r,s,p,m))

    def test_activity_flag_not_validated_as_running(self):
        r,s,p,m=self.fixture();s[1]['activity_flags_valid']=True;self.assertFalse(self.check(r,s,p,m))

    def test_native_lifetime_changed_rejected(self):
        r,s,p,m=self.fixture();r['after'][0]['creation_100ns']=4;self.assertFalse(self.check(r,s,p,m))

    def test_fake_thread_root_module_rejected(self):
        r,s,p,m=self.fixture();m['modules'][0]['path']='unrelated.dll';self.assertFalse(self.check(r,s,p,m))


class FaultRetentionChecks(unittest.TestCase):
    def fixture(self):
        import verify_fault
        record=dict(oracle=[[0,1,2,1,22,7,2]],before=[dict(active=True,creation_100ns=3)],after=[dict(active=True,creation_100ns=3)],errors=['expected failure'],observer_returncode=1,target_returncode=0,target_still_running=False,observer_still_running=False,complete=dict(completed=True,heartbeat=8))
        rows=[dict(kind='init',error=None),dict(kind='error',error='Requested/owner OS thread missing',ordinal=0)]
        post=dict(fault_lock_retained=True,old_field_fault_lock_retained=True,old_failed_marker_lock_retained=True,constant_plan_sources_unchanged=True,fault_plan_sources_unchanged=True,formal_458_unchanged=True,old_field_sources_unchanged=True,sample_interval_100ns=10000)
        return record,rows,post,'Error: Requested/owner OS thread missing'

    def check(self,*a):
        import verify_fault
        return verify_fault.inspect(*a)['fault_recovery_control_pass']

    def test_failed_capture_recovered_and_retained(self):
        import verify_fault
        r,s,p,l=self.fixture();v=verify_fault.inspect(r,s,p,l);self.assertTrue(v['fault_recovery_control_pass']);self.assertFalse(v['capture_success']);self.assertFalse(v['field_attribution_ready'])

    def test_false_success_flag_rejected(self):
        r,s,p,l=self.fixture();r['capture_complete']=True;self.assertFalse(self.check(r,s,p,l))

    def test_target_not_recovered_rejected(self):
        r,s,p,l=self.fixture();r['target_still_running']=True;self.assertFalse(self.check(r,s,p,l))

    def test_fault_lock_lost_rejected(self):
        r,s,p,l=self.fixture();p['fault_lock_retained']=False;self.assertFalse(self.check(r,s,p,l))

    def test_recovery_heartbeat_absent_rejected(self):
        r,s,p,l=self.fixture();r['complete']['heartbeat']=7;self.assertFalse(self.check(r,s,p,l))

    def test_fault_log_discarded_rejected(self):
        r,s,p,l=self.fixture();self.assertFalse(self.check(r,s,p,''))


if __name__=='__main__':unittest.main()
