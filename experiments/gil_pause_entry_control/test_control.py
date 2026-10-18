import copy
import unittest
from verify import inspect


def fixture(case='early_owner_pause01'):
    early=case!='baseline01'
    anchor=lambda t:dict(qpc_before=t,qpc_after=t+1)
    state=[2,1,21,10,0,0,23,22,0,5,0,0,0,0,0,0]
    def probe(label,t,request=False,beat=10):
        v=state.copy();v[3]=beat
        if request:v[4]=1;v[8]=1
        return dict(label=label,begin=anchor(t),end=anchor(t+1),values=v,confirm=2)
    observations=[probe('before_intervention',20)]
    if early:
        observations += [probe('owner_pause_delivery',40+i*3,beat=10+i) for i in range(5)]
        observations += [probe('before_request',60,beat=15)]
    observations += [probe('before_snapshot',80,early,20),probe('after_snapshot',100,early,30)]
    def module(base,path,syms):
        return dict(base=base,path=path,image_size=1000,pdb_matched=True,pdb_unmatched=False,
                    codeview=[dict(guid='ABC',age=1)],pdb_identity=dict(guid='ABC',age=1),loaded_guid='ABC',loaded_age=1,
                    resolved=[dict(address=base+r,module_base=base,module_offset=r,pdb_matched=True,symbol=s) for r,s in syms.items()])
    catalog=dict(modules=[module(1000,'python311.dll',{1:'take_gil',2:'PyGILState_Ensure'}),
                          module(2000,'ntdll.dll',{1:'NtDelayExecution',2:'NtWaitForSingleObject',9:'RtlUserThreadStart'}),
                          module(3000,'kernel32.dll',{1:'SleepEx',9:'BaseThreadInitThunk'})])
    def native(tid,addresses):
        return dict(tid=tid,context_ip=addresses[0],stopped_by='StackWalk64 returned false',
                    frames=[dict(address=a,module_base=a//1000*1000) for a in addresses])
    values=[2,1,21,22]
    s=dict(kind='sample',pid=10,ordinal=0,qpc_begin=90,suspended_qpc=91,resume_returned_qpc=94,qpc_end=95,
           resolve_begin_qpc=96,resolve_end_qpc=97,
           oracle_reads=[None,dict(values=values),dict(values=values),None],
           traces=[dict(pid=10,os_thread_id=21,owns_gil=True,frames=[dict(name='hold_native')])],
           native=[native(21,[2001,3001,3009,2009]),native(22,[2002,1001,1002,3009,2009] if early else [2001,3001,3009,2009])])
    rows=[dict(kind='init',pid=10,schema=4,error=None,qpc_end=10),s,dict(kind='complete',pid=10,samples_written=1,qpc=98)]
    counters=[dict(pid=10,tid=t,creation_100ns=100+t,cycles=50,user_100ns=0,kernel_100ns=0,active=True) for t in (21,22,23)]
    final=state.copy();final[4:6]=[1,1] if early else [0,0];final[11]=1 if early else 2
    record=dict(ready=dict(pid=10,tids=dict(owner=21,waiter=22,native_beat=23)),oracle=observations,
                before=counters,after=copy.deepcopy(counters),errors=[],observer_returncode=0,target_returncode=0,
                observer_still_running=False,target_still_running=False,owner_pause_outstanding=False,lock_retained=True,
                complete=dict(state=final))
    if early:record.update(suspend=dict(previous=0,begin=anchor(30),end=anchor(31)),resume=dict(previous=1,begin=anchor(110),end=anchor(111)),request_gate_written=anchor(64))
    return record,rows,catalog


class ControlTests(unittest.TestCase):
    def check(self,change,gate):
        r,s,c=fixture();change(r,s,c);result=inspect(r,s,c,'early_owner_pause01')
        self.assertFalse(result['checks'][gate]);self.assertFalse(result['passed'])
    def test_baseline_and_adversarial(self):
        for name in ('baseline01','early_owner_pause01'):
            r,s,c=fixture(name);result=inspect(r,s,c,name);self.assertTrue(result['passed'],result)
    def test_preexisting_request_cannot_certify_manufactured_wait(self):
        self.check(lambda r,s,c:r['oracle'][0]['values'].__setitem__(4,1),'no_request_before_intervention')
    def test_suspend_not_delivered(self):
        self.check(lambda r,s,c:r['oracle'][2]['values'].__setitem__(9,6),'delivered_owner_pause')
    def test_whole_process_stalled_is_not_owner_only_pause(self):
        def change(r,s,c):
            for p in r['oracle'][1:6]:p['values'][3]=10
        self.check(change,'delivered_owner_pause')
    def test_wrong_suspend_count(self):
        self.check(lambda r,s,c:r['suspend'].__setitem__('previous',1),'suspension_order')
    def test_resume_unconfirmed(self):
        self.check(lambda r,s,c:r['resume'].__setitem__('previous',2),'suspension_order')
    def test_request_already_acquired(self):
        self.check(lambda r,s,c:r['oracle'][-1]['values'].__setitem__(5,1),'request_after_pause')
    def test_missing_take_gil(self):
        self.check(lambda r,s,c:c['modules'][0]['resolved'][0].__setitem__('symbol',None),'closed_induced_GIL_chain')
    def test_unmatched_python_symbols(self):
        self.check(lambda r,s,c:c['modules'][0]['resolved'][0].__setitem__('pdb_matched',False),'closed_induced_GIL_chain')
    def test_mismatched_pdb_guid(self):
        self.check(lambda r,s,c:c['modules'][0].__setitem__('loaded_guid','OTHER'),'symbol_identities')
    def test_unclosed_native_stack(self):
        self.check(lambda r,s,c:s[1]['native'][1]['frames'].pop(),'both_roots_closed')
    def test_owner_switch(self):
        self.check(lambda r,s,c:r['oracle'][-1]['values'].__setitem__(2,30),'stable_owner')
    def test_tid_reuse(self):
        self.check(lambda r,s,c:r['after'][0].__setitem__('creation_100ns',12345),'identities')
    def test_live_observer_never_clean(self):
        self.check(lambda r,s,c:r.__setitem__('observer_still_running',True),'clean')
    def test_snapshot_outside_oracle_bracket(self):
        self.check(lambda r,s,c:s[1].__setitem__('qpc_begin',70),'order')
    def test_incomplete_capture(self):
        r,s,c=fixture();s.pop(1);self.assertFalse(inspect(r,s,c,'early_owner_pause01')['passed'])


if __name__=='__main__':unittest.main()
