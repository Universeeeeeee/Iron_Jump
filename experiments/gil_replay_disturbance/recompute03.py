"""Recompute the failed and post-repair cohorts without another capture or changed gate."""
import argparse
import json
from pathlib import Path
from control import read,sha
from verify import case_result,pair_result

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main(a):
    raw=a.raw;manifest=read(raw/'manifest03.json');assert all(sha(raw/n)==h for n,h in manifest.items())
    plan=read(raw/'plan03.json');original=read(raw/'plan01.json')
    assert all(sha(raw/n)==sha(HERE/n)==h for n,h in plan['sources'].items()) and all(sha(raw/n)==sha(HERE/n)==h for n,h in original['sources'].items())
    assert plan['relative_limit']==original['relative_limit']==.15 and plan['raw_first']==original['raw_first']==42237 and plan['raw_after_last']==original['raw_after_last']==49061 and sha(raw/'observer.exe')==plan['observer_sha256']==original['observer_sha256']
    cases={};rows_seen=0
    for i,order in enumerate(plan['orders'],1):
        for mode in order:
            case=raw/f'cohort03/run01/pair{i}_{mode}';record=read(case/'record.json');rows=[json.loads(l) for l in (case/'samples.jsonl').read_text().splitlines()] if mode=='on' else []
            result=case_result(record,read(case/'target/roi.json'),read(case/'target/complete.json'),rows,plan,ROOT)
            assert result==read(case/'analysis.json');cases[f'pair{i}_{mode}']=result;rows_seen+=sum(r['kind']=='sample' for r in rows)
    pairs=[dict(pair=i,**pair_result(cases[f'pair{i}_off'],cases[f'pair{i}_on'],plan)) for i in range(1,4)]
    frozen=read(raw/'cohort03/run01/result.json');assert frozen['pairs']==pairs and not frozen['errors'] and frozen['offline_contact_chain_perturbation_pass']==all(p['offline_contact_chain_pair_pass'] for p in pairs)
    first=read(raw/'run01/result.json');second=read(raw/'completion02/result.json')
    assert first['errors'] and second['errors'] and not (raw/'run01/pair2_off/target/complete.json').exists() and not (raw/'run01/pair3_off').exists() and not (raw/'run01/pair3_on').exists()
    exceeded=[dict(pair=p['pair'],**b,limit=.15) for p in pairs for b in p['block_changes'] if abs(b['wall_change'])>.15]
    summary=dict(scope='Two separate preserved cohorts, not pooled. Initial cohort failed operationally; independent post-repair cohort completed and failed its unchanged block perturbation gate.',archive_manifest_files=len(manifest),all_hashes_verified=True,same_final_observer_sha256=plan['observer_sha256'],original_failed_plan_sha256=sha(raw/'plan01.json'),post_repair_plan_sha256=sha(raw/'plan03.json'),initial_analysis_failure_preserved=True,initial_file_handoff_failure_preserved=True,initial_pair2_off_terminal_reason='No terminal complete record; after-counter missing; cannot be treated as a valid calibration case. No matching process remains at post-audit.',post_repair_cases={n:dict(case_pass=v['case_pass'],wall_ms=v['wall_ns']/1e6,thread_cpu_ms=v['thread_cpu_ns']/1e6,cycles=v['cycles'],samples_inside_roi=v['samples_fully_inside_roi'],clock_uncertainty_ns=v['clock']['uncertainty_ns']) for n,v in cases.items()},post_repair_pairs=pairs,exceeded_blocks=exceeded,all_6_post_repair_cases_valid=all(v['case_pass'] for v in cases.values()),post_repair_samples=rows_seen,offline_contact_chain_perturbation_pass=frozen['offline_contact_chain_perturbation_pass'],original_and_new_failed_locks_retained=True,actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_or_fix_complete=False,limits=['No GUI paint/event loop, vision callbacks, USB input queue/pending or real SDK child in this workload. Consumer-only original chain cannot qualify full actual load.','Raw trace stream checks do not turn StackWalk termination into PDB-proven closure or provide function attribution.','Do not average away the failing fixed block or use a passed partial pair to replace either failed cohort. No capture after the predeclared six-case cohort.'])
    with a.output.open('x') as f:json.dump(summary,f,indent=2)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('post_repair_cases','post_repair_pairs','limits')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
