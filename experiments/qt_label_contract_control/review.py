"""Separate the observed API contract from incomplete process-exit telemetry."""
import hashlib
import json
from pathlib import Path
import zipfile
from check import check

HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    plan=read(HERE/'plan01.json');raw=read(HERE/'result01.json');target=read(HERE/'target01.json')
    assert raw['plan_sha256']==sha(HERE/'plan01.json')
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
    assert plan['process_budget']==1 and plan['retry_budget']==0 and not plan['performance_AB']
    contract=check(raw)
    assert not raw['errors'] and raw['passed']
    post=read(HERE/'post01.json')
    assert post['frozen_sources_unchanged'] and post['existing_modules_unchanged'] and post['oracle_unchanged']
    assert not post['old_pid_current_records'] and set(post['locks'])=={'active.lock','launch.lock'}
    assert target['retained_process_handle_wait_confirmed_exit']
    native=read(HERE/'exitcode_control02.status.json')
    assert native['confirmed_exit'] and native['observation_complete'] and native['native_query_success']
    assert native['native_exit_code']==native['managed_exit_code']==7
    support=read(HERE/'exitcode_control_binding02.json')
    assert support['launch02_sha256']==sha(HERE/'launch02.ps1') and support['exit7_source_sha256']==sha(HERE/'exit7.py')
    transport=read(HERE/'transport01.json');archive=HERE/'runs/evidence01.zip'
    assert sha(archive)==transport['sha256']
    with zipfile.ZipFile(archive) as z:
        m=json.loads(z.read('manifest01.json'))
        assert all(hashlib.sha256(z.read(n)).hexdigest()==v for n,v in m['files'].items())
        assert len(m['files'])==transport['manifest_files']
        assert all(n+'/' in z.namelist() for n in m['locks'])
        assert all(m['files'][n]==v for n,v in plan['sources'].items())
        assert m['files']['MessageOracle.dll']==plan['dll_sha256']
        for name in ('result01.json','launch02.ps1','exit7.py'):
            assert m['files'][name]==sha(HERE/name)
    phases={p:[r['gil'] for r in raw['rows'] if r['phase']==p] for p in (1,2)}
    exit_confirmed=isinstance(target['exit_code'],int)
    result=dict(contract_data_pass=contract['contract_control_pass'],native_callback_GIL_values=phases,
        raw_controller_pass_field_scope='API-contract checker only, not full execution-observation acceptance.',
        original_target_confirmed_gone=True,original_exit_code=target['exit_code'],original_exit_code_observed=exit_confirmed,
        overall_control_execution_acceptance_pass=contract['contract_control_pass'] and exit_confirmed and target['exit_code']==0,
        missing_original_evidence=[] if exit_confirmed else ['Retained child exit-code read was null. Original control stays incomplete; no Qt rerun.'],
        corrected_launcher_independent_ExitProcess7_control_pass=True,
        limits=['Native message callbacks occur inside deliberate invalid-paint calls, not inside the real image scaling/latch workload.',
            'Five sampled callback positions do not prove continuous ownership over an entire paint call.',
            'The direct call is a negative control, not a production-safe replacement or an optimization candidate.',
            'No pixels, real widget instance, model/report equivalence, performance benefit or GIL contribution is measured.',
            'This does not upgrade old stack/3%/1% failures, the original missing exit code, or any field attribution gate.'],
        root_cause_or_fix_complete=False,field_attribution_ready=False,
        bindings={p.name:sha(p) for p in (Path(__file__),HERE/'plan01.json',HERE/'result01.json',HERE/'target01.json',
            HERE/'post01.json',HERE/'transport01.json',HERE/'launch_binding01.json',HERE/'exitcode_control02.status.json',
            HERE/'exitcode_control_binding02.json',HERE/'preflight_transport_failure01.json',HERE/'exitcode_control_failure01.json',
            HERE/'archive_transfer_failure01.json')})
    with (HERE/'review01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
