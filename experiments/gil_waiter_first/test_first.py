import copy
import unittest
from verify import native_checks,stream_checks,pause_order


def fixture(wait=True):
    def module(base,path,syms):
        return dict(base=base,path=path,image_size=1000,pdb_matched=True,pdb_unmatched=False,codeview=[dict(guid='ABC',age=1)],pdb_identity=dict(guid='ABC',age=1),loaded_guid='ABC',loaded_age=1,
                    resolved=[dict(address=base+r,module_base=base,module_offset=r,pdb_matched=True,symbol=s) for r,s in syms.items()])
    catalog=dict(modules=[module(1000,'python311.dll',{1:'take_gil',2:'PyGILState_Ensure'}),module(2000,'ntdll.dll',{1:'NtDelayExecution',2:'NtWaitForSingleObject',9:'RtlUserThreadStart'}),module(3000,'kernel32.dll',{1:'SleepEx',9:'BaseThreadInitThunk'})])
    addresses=[2002,1001,1002,3009,2009] if wait else [2001,3001,3009,2009]
    n=dict(tid=22,context_ip=addresses[0],context_sp=9000,context_bp=9001,stopped_by='StackWalk64 returned false',frames=[dict(address=a,module_base=a//1000*1000) for a in addresses])
    s=dict(kind='sample',ordinal=0,qpc_begin=20,requested_suspend_call_qpc=21,requested_locked_qpc=22,pre_context_begin_qpc=23,pre_context_end_qpc=24,global_suspend_call_qpc=25,suspended_qpc=26,global_resume_returned_qpc=27,resume_returned_qpc=28,qpc_end=29,collection_end_qpc=30,resolve_begin_qpc=31,resolve_end_qpc=32,natural_owner_association_qualified=False,activity_flags_valid=False,pre_native=n,native=[copy.deepcopy(n)])
    s['oracle_reads']=[dict(qpc_begin=20,qpc_end=21,values=[2,1,21,10]),dict(qpc_begin=26,qpc_end=26,values=[2,1,21,11]),dict(qpc_begin=26,qpc_end=26,values=[2,1,21,11]),dict(qpc_begin=29,qpc_end=29,values=[2,1,21,12])]
    return [dict(kind='init',schema=5,error=None,test_gate_enabled=False,qpc_end=10,natural_owner_association_qualified=False,activity_flags_valid=False),s,dict(kind='complete',samples_written=1,qpc=40)],catalog


class FirstTests(unittest.TestCase):
    def test_positive_and_negative_locations(self):
        for wait in (False,True):
            rows,c=fixture(wait);self.assertTrue(all(stream_checks(rows,1,False).values()));self.assertTrue(native_checks(rows[1],22,c,wait)['passed'])
    def test_pre_context_after_global_pause_rejected(self):
        r,c=fixture();r[1]['pre_context_end_qpc']=27;self.assertFalse(all(stream_checks(r,1,False).values()))
    def test_symbolication_inside_collection_rejected(self):
        r,c=fixture();r[1]['resolve_begin_qpc']=28;self.assertFalse(all(stream_checks(r,1,False).values()))
    def test_incomplete_rows_rejected(self):
        r,c=fixture();r[-1]['kind']='error';self.assertFalse(all(stream_checks(r,1,False).values()))
    def test_same_tstate_does_not_promote_owner(self):
        r,c=fixture();r[1]['current_tstate_reads']=[{'values':[123]}]*3;r[1]['natural_owner_association_qualified']=True;self.assertFalse(stream_checks(r,1,False)['no_owner_promotion'])
    def test_synthetic_barrier_never_normal_mode(self):
        r,c=fixture();r[0]['test_gate_enabled']=True;self.assertFalse(stream_checks(r,1,False)['schema'])
    def test_resumed_requested_context_rejected(self):
        r,c=fixture();r[1]['native'][0]['context_sp']+=8;self.assertFalse(native_checks(r[1],22,c,True)['checks']['unchanged_requested_context'])
    def test_missing_gil_symbol_rejected(self):
        r,c=fixture();c['modules'][0]['resolved'][0]['symbol']=None;self.assertFalse(native_checks(r[1],22,c,True)['checks']['acquisition_location'])
    def test_unmatched_pdb_rejected(self):
        r,c=fixture();c['modules'][0]['resolved'][0]['pdb_matched']=False;self.assertFalse(native_checks(r[1],22,c,True)['passed'])
    def test_wrong_guid_rejected(self):
        r,c=fixture();c['modules'][0]['loaded_guid']='WRONG';self.assertFalse(native_checks(r[1],22,c,True)['checks']['symbol_identities'])
    def test_truncated_pre_stack_rejected(self):
        r,c=fixture();r[1]['pre_native']['frames'].pop();self.assertFalse(native_checks(r[1],22,c,True)['checks']['roots'])
    def test_preexisting_wait_fails_negative(self):
        r,c=fixture();self.assertFalse(native_checks(r[1],22,c,False)['checks']['acquisition_location'])
    def test_wrong_tid_rejected(self):
        r,c=fixture();self.assertFalse(native_checks(r[1],23,c,True)['checks']['requested_identity'])
    def test_activity_flags_rejected(self):
        r,c=fixture();r[1]['activity_flags_valid']=True;self.assertFalse(stream_checks(r,1,False)['activity_not_used'])
    def test_native_heartbeat_pause(self):
        r,c=fixture();self.assertTrue(pause_order(r[1]))
    def test_native_heartbeat_not_paused(self):
        r,c=fixture();r[1]['oracle_reads'][2]['values'][3]+=1;self.assertFalse(pause_order(r[1]))
    def test_native_probe_outside_scope(self):
        r,c=fixture();r[1]['oracle_reads'][1]['qpc_begin']=25;self.assertFalse(pause_order(r[1]))


if __name__=='__main__':unittest.main()
