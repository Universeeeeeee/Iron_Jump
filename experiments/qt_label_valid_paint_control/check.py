"""Correctness gate only; no throughput, GIL share or field-fix acceptance."""


def check(data,plan):
    assert not data['errors'] and not data['unexpected_Qt_messages'] and data['handler_restored']
    assert data['None_reference_check']['before']==data['None_reference_check']['after']
    assert len(data['cases'])==len(plan['cases'])
    for expected,row in zip(plan['cases'],data['cases']):
        assert row['id']==expected['id']
        modes=row['modes'];assert set(modes)=={'golden','binding','bridge'}
        assert modes['golden']['pixels_sha256']==modes['binding']['pixels_sha256']==modes['bridge']['pixels_sha256']
        assert row['complete_bytes_equal'] and all(v['changed_from_prefill'] for v in modes.values())
        for name in ('binding','bridge'):
            v=modes[name];assert v['base_errors']==[] and len(v['callbacks'])==1
            callback=v['callbacks'][0]
            assert callback['tid']==data['gui_tid'] and callback['event_valid_before'] and callback['event_valid_after']
            assert callback['owned_before']==callback['owned_after'] and callback['returned_None']
        assert modes['binding']['events_valid_after_render']==modes['bridge']['events_valid_after_render']
        assert all(v['label_invalid_after_delete'] and v['style_invalid_after_delete'] for v in modes.values())
    assert data['cases'][0]['modes']['golden']['pixels_sha256']!=data['cases'][1]['modes']['golden']['pixels_sha256']
    assert len(data['invalid_inputs'])==4
    assert all(v['binding']==v['bridge'] and v['binding']['raised'] for v in data['invalid_inputs'])
    assert len(data['injected_callbacks'])==2
    observed=[]
    for row in data['injected_callbacks']:
        assert row['style_calls']==1 and row['exception_observed']
        assert row['recovery_matches_golden'] and row['deleted']
        observed.append({k:row[k] for k in ('caught_at_base_call','caught_at_render','same_exception_instance','stderr_contains_sentinel')})
    assert observed[0]==observed[1]
    return dict(correctness_control_pass=True,performance_benefit_proven=False,field_fix_verified=False)
