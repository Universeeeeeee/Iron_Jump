"""Finite real-widget correctness; never performance or clinical acceptance."""


def check(data,plan):
    assert not data['errors'] and not data['Qt_messages'] and data['handler_restored']
    assert data['original_method_unchanged'] and data['AST_audit']['only_first_statement_changed'] and data['AST_audit']['remaining_body_AST_equal']
    assert len(data['cases'])==len(plan['cases'])
    for expected,row in zip(plan['cases'],data['cases']):
        assert row['id']==expected['id'] and row['full_pixels_equal']
        a,b=row['original'],row['bridge']
        assert a['pixels_sha256']==b['pixels_sha256'] and a['mappings']==b['mappings']
        for v in (a,b):
            assert v['widget_dpr']==1.25 and v['state_before']==v['state_after'] and not v['signals']
            assert v['event_tids'] and set(v['event_tids'])=={data['gui_tid']}
            assert v['deleted'] and v['filter_deleted'] and v['changed_from_prefill']
        assert a['events_valid_after_render']==b['events_valid_after_render']
        assert a['draw_calls']==b['draw_calls']
        if expected['pose']:assert a['draw_calls']['pose']==1
        if expected['angles']:assert a['draw_calls']['angle']==1
        if expected['interval']:assert a['draw_calls']['label']>=1
    by={r['id']:r for r in data['cases']}
    assert by['image_only']['original']['pixels_sha256']==by['low_quality']['original']['pixels_sha256']
    assert by['image_only']['original']['pixels_sha256']!=by['pose']['original']['pixels_sha256']
    assert by['pose']['original']['pixels_sha256']!=by['mirrored']['original']['pixels_sha256']
    assert len(data['faults'])==2
    fields=('caught_at_render','same_instance','stderr_contains_sentinel','recovery_matches_original')
    for v in data['faults']:assert v['fault_calls']==1 and v['observed'] and v['deleted'] and v['recovery_matches_original']
    assert {k:data['faults'][0][k] for k in fields}=={k:data['faults'][1][k] for k in fields}
    return dict(canvas_semantics_pass=True,performance_pass=False,field_fix_verified=False)
