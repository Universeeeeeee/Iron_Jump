import unittest
from review_stack01 import native_check,same_lifetime


class StackClosureChecks(unittest.TestCase):
    def fixture(self):
        modules={100:dict(path='ntdll.dll',image_size=100),200:dict(path='kernel32.dll',image_size=100),300:dict(path='python311.dll',image_size=100)}
        addresses={101:dict(symbol='NtWaitForSingleObject',pdb_matched=True),301:dict(symbol='take_gil',pdb_matched=True),302:dict(symbol='PyEval_RestoreThread',pdb_matched=True),209:dict(symbol='BaseThreadInitThunk',pdb_matched=True),109:dict(symbol='RtlUserThreadStart',pdb_matched=True)}
        n=dict(context_ip=101,stopped_by='StackWalk64 returned false',frames=[dict(address=x,module_base=x//100*100,module_offset=x%100) for x in addresses])
        return n,modules,addresses
    def test_complete_wait_path(self):
        v=native_check(*self.fixture());self.assertTrue(v['raw_valid'] and v['roots_closed'] and v['matched_take_gil'] and v['matched_entry'] and v['matched_wait'])
    def test_context_ip_corruption_rejected(self):
        n,m,a=self.fixture();n['context_ip']=102;self.assertFalse(native_check(n,m,a)['raw_valid'])
    def test_truncation_rejected(self):
        n,m,a=self.fixture();n['frames'].pop();self.assertFalse(native_check(n,m,a)['roots_closed'])
    def test_unmatched_root_rejected(self):
        n,m,a=self.fixture();a[109]['pdb_matched']=False;self.assertFalse(native_check(n,m,a)['roots_closed'])
    def test_unmatched_wait_symbol_not_proof(self):
        n,m,a=self.fixture();a[101]['pdb_matched']=False;self.assertFalse(native_check(n,m,a)['matched_wait'])
    def test_cap_stays_incomplete(self):
        n,m,a=self.fixture();n['stopped_by']='frame cap; incomplete';self.assertFalse(native_check(n,m,a)['roots_closed'])
    def test_bad_rva_rejected(self):
        n,m,a=self.fixture();n['frames'][0]['module_offset']=5;self.assertFalse(native_check(n,m,a)['raw_valid'])


class LifetimeChecks(unittest.TestCase):
    def fixture(self):
        a=dict(active=True,creation_100ns=7,cycles=5,user_100ns=1,kernel_100ns=0);return {(10,20):a},{(10,20):dict(a,cycles=6)}
    def test_retained_identity(self):self.assertTrue(same_lifetime(20,10,*self.fixture()))
    def test_reuse_rejected(self):
        a,b=self.fixture();b[(10,20)]['creation_100ns']=8;self.assertFalse(same_lifetime(20,10,a,b))
    def test_other_pid_not_substituted(self):self.assertFalse(same_lifetime(20,11,*self.fixture()))
    def test_exited_thread_rejected(self):
        a,b=self.fixture();b[(10,20)]['active']=False;self.assertFalse(same_lifetime(20,10,a,b))


if __name__=='__main__':unittest.main()
