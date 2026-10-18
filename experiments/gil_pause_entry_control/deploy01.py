"""Deploy one fresh synthetic control directory and freeze before any target starts."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/ground_throughput_diagnosis'));import windows as w
REMOTE='E:/OptoJump/IronJump-gil-pause-control-20261019-01'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


if __name__=='__main__':
    shutil.copyfile(ROOT/'experiments/gil_waiter_control/resolve_raw.py',HERE/'resolve_raw.py')
    paths=[p for p in HERE.iterdir() if p.suffix in ('.py','.c','.cmd')]
    with zipfile.ZipFile(HERE/'source01.zip','x',zipfile.ZIP_DEFLATED) as z:
        for p in paths:z.write(p,p.name)
    archive_sha=sha(HERE/'source01.zip')
    w.ssh(f"if(Test-Path '{REMOTE}'){{throw 'Existing control directory'}};New-Item -ItemType Directory '{REMOTE}'|Out-Null")
    w.transfer(HERE/'source01.zip',f'{w.HOST}:{REMOTE}/source01.zip')
    result=w.ssh(f"if((Get-FileHash '{REMOTE}/source01.zip').Hash.ToLower() -ne '{archive_sha}'){{throw 'Source archive mismatch'}};& D:/conda/python.exe -m zipfile -e '{REMOTE}/source01.zip' '{REMOTE}';if($LASTEXITCODE){{throw 'Extract failed'}};Set-Location '{REMOTE}';& cmd /c build.cmd *> build.log;if($LASTEXITCODE){{Get-Content build.log;throw 'Build failed'}};@{{dll_sha=(Get-FileHash PauseOracle.dll).Hash.ToLower();pdb_sha=(Get-FileHash PauseOracle.pdb).Hash.ToLower();python_sha=(Get-FileHash D:/conda/python311.dll).Hash.ToLower();dbghelp_sha=(Get-FileHash C:/Windows/System32/dbghelp.dll).Hash.ToLower();observer_sha=(Get-FileHash E:/OptoJump/IronJump-gil-observer-noise-20261018-01/observer.exe).Hash.ToLower()}}|ConvertTo-Json -Compress",timeout=60)
    built=json.loads(result)
    with (HERE/'build01.json').open('x') as f:json.dump(built,f,indent=2)
    old=json.loads((ROOT/'experiments/gil_waiter_control/plan01.json').read_text())
    assert built['observer_sha']==old['observer_sha256'] and built['python_sha']==old['python_dll_sha256'] and built['dbghelp_sha']==old['dbghelp_sha256']
    plan=dict(scope='One no-request baseline, one explicit external early-owner-pause counterexample. Does not reproduce internal NtSuspendProcess ordering or certify natural application waiting.',
              cases=['baseline01','early_owner_pause01'],count_per_case=1,period_ms=250,
              observer_path='E:/OptoJump/IronJump-gil-observer-noise-20261018-01/observer.exe',observer_sha256=built['observer_sha'],
              oracle_dll_sha256=built['dll_sha'],oracle_pdb_sha256=built['pdb_sha'],python_dll_sha256=built['python_sha'],dbghelp_sha256=built['dbghelp_sha'],
              native_helpers=old['native_helpers'],symbol_search_path=old['symbol_search_path'],
              sources={p.name:sha(p) for p in paths},source_archive_sha256=archive_sha,
              original_waiter_plan_sha256=sha(ROOT/'experiments/gil_waiter_control/plan01.json'),
              original_gui_analysis_sha256=sha(ROOT/'experiments/gil_gui_analysis/analysis_summary01.json'),
              checks=['Both native stacks close to independently matched thread roots; requested context IP retained.',
                      'Native requested/acquired/gate markers are zero before intervention; holder identity stable.',
                      'Owner-only pause actually delivered: five owner-heartbeat readings equal, independent native heartbeat progresses; SuspendThread previous0 and ResumeThread previous1.',
                      'Adversarial request begins only after owner suspension; closed native take_gil acquisition chain occurs before owner resume; request acquires after cleanup.',
                      'Baseline has no GIL request/acquisition chain and completes through native skip gate.',
                      'All source/binary identities, lifecycle counters, clean exits and locks confirmed. No retry or altered old acceptance gates.'],
              actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False)
    with (HERE/'plan01.json').open('x') as f:json.dump(plan,f,indent=2)
    w.transfer(HERE/'plan01.json',f'{w.HOST}:{REMOTE}/plan01.json')
    print(json.dumps(dict(remote=REMOTE,plan_sha256=sha(HERE/'plan01.json'),build=built),indent=2))
