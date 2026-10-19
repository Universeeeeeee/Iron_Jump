import unittest
from check import check


class Correctness(unittest.TestCase):
    def fixture(self):
        cases=[]
        callback=dict(tid=7,event_valid_before=True,event_valid_after=True,owned_before=False,owned_after=False,returned_None=True)
        for i in range(2):
            modes={}
            for name in ('golden','binding','bridge'):
                modes[name]=dict(pixels_sha256=str(i),changed_from_prefill=True,label_invalid_after_delete=True,style_invalid_after_delete=True)
                if name!='golden':modes[name].update(base_errors=[],callbacks=[dict(callback)],events_valid_after_render=[False])
            cases.append(dict(id=str(i),modes=modes,complete_bytes_equal=True))
        error=dict(raised=True,type='TypeError',message='fixture')
        injected=dict(style_calls=1,exception_observed=True,recovery_matches_golden=True,deleted=True,
            caught_at_base_call=1,caught_at_render=0,same_exception_instance=True,stderr_contains_sentinel=False)
        d=dict(errors=[],unexpected_Qt_messages=[],handler_restored=True,None_reference_check=dict(before=4,after=4),
            gui_tid=7,cases=cases,invalid_inputs=[dict(binding=dict(error),bridge=dict(error)) for _ in range(4)],
            injected_callbacks=[dict(injected),dict(injected)])
        return d,dict(cases=[dict(id='0'),dict(id='1')])

    def test_one_pixel_result_or_lifetime_mismatch_fails(self):
        d,p=self.fixture();d['cases'][0]['modes']['bridge']['pixels_sha256']='different'
        with self.assertRaises(AssertionError):check(d,p)
        d,p=self.fixture();d['cases'][0]['modes']['bridge']['events_valid_after_render']=[True]
        with self.assertRaises(AssertionError):check(d,p)

    def test_error_moved_from_call_to_stderr_or_not_injected_fails(self):
        for mutate in ('channel','missing'):
            d,p=self.fixture()
            if mutate=='channel':d['injected_callbacks'][1].update(caught_at_base_call=0,stderr_contains_sentinel=True)
            else:d['injected_callbacks'][1]['style_calls']=0
            with self.assertRaises(AssertionError):check(d,p)

    def test_success_is_not_a_performance_or_field_pass(self):
        d,p=self.fixture();q=check(d,p)
        self.assertTrue(q['correctness_control_pass'])
        self.assertFalse(q['performance_benefit_proven']);self.assertFalse(q['field_fix_verified'])
