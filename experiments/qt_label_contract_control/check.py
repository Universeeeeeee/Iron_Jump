"""Synthetic API-contract checks; never a performance or field acceptance gate."""


def check(data):
    assert data['handler_restored'] and data['same_exact_QLabel_native_export']
    assert data['source_and_modules_match_plan'] and data['rows']
    phases = {p:[r for r in data['rows'] if r['phase'] == p] for p in (1,2)}
    assert sum(map(len, phases.values())) == len(data['rows'])
    assert phases[1] and len(phases[1]) == len(phases[2])
    assert all(r['tid'] == data['gui_tid'] and r['message_type'] == 1 for r in data['rows'])
    for phase, rows in phases.items():
        begin, end = data['call_qpc'][str(phase)]
        assert all(begin <= r['qpc'] <= end and r['gil'] in (0,1) for r in rows)
    assert [r['message_type'] for r in phases[1]] == [r['message_type'] for r in phases[2]]
    assert all(r['gil'] == 1 for r in phases[1])
    assert any(r['gil'] == 0 for r in phases[2])
    return dict(contract_control_pass=True, wrapper_native_warning_GIL_held=True,
        direct_native_call_has_GIL_free_warning=True, field_owner_or_root_proven=False,
        scope='Expected invalid-paint warnings only. Does not execute or qualify the real image-scale/latch workload.')
