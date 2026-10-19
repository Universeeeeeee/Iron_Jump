"""Recheck all four archived CPU controls; no new capture or causal shares."""
import hashlib
import itertools
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def validate_blocks(roi):
    blocks=roi['blocks'];assert blocks
    assert blocks[0]['raw_first']==roi['raw_first'] and blocks[-1]['raw_last']+1==roi['raw_after_last']
    assert roi['frames']==roi['raw_after_last']-roi['raw_first']
    assert blocks[0]['wall_begin_ns']==roi['wall_begin_ns']
    for i,b in enumerate(blocks):
        assert b['raw_last']>=b['raw_first'] and b['wall_end_ns']-b['wall_begin_ns']==b['wall_ns'] and b['thread_cpu_ns']>=0
        if i:assert blocks[i-1]['raw_last']+1==b['raw_first'] and blocks[i-1]['wall_end_ns']==b['wall_begin_ns']
    assert sum(b['thread_cpu_ns'] for b in blocks)<=roi['thread_cpu_ns']
    assert sum(b['wall_ns'] for b in blocks)<=roi['wall_ns']
    return dict(wall_tail_ns=roi['wall_ns']-sum(b['wall_ns'] for b in blocks),cpu_tail_ns=roi['thread_cpu_ns']-sum(b['thread_cpu_ns'] for b in blocks),
                negative_wall_minus_cpu_blocks=[i for i,b in enumerate(blocks) if b['wall_ns']<b['thread_cpu_ns']])

if __name__=='__main__':
    plan=read(HERE/'plan02.json');raw=ROOT/plan['raw'];manifest=read(raw/'manifest.json');assert sha(raw/'manifest.json')==plan['manifest_sha256']
    assert all(sha(raw/n.replace('\\','/'))==v for n,v in manifest.items());assert sha(Path(__file__))==plan['reviewer_sha256']
    base=raw/'cpu_delivery01';frozen=read(base/'plan01.json');assert all(sha(base/n)==v for n,v in frozen['sources'].items())
    stage=base/'diagnostic01/run01';status=read(stage/'result.json');assert status['capture_protocol_complete'] and not status['errors']
    cases={};rois={}
    for spec in frozen['cases']:
        name=spec['id'];folder=stage/name;roi=read(folder/'target/roi.json');analysis=read(folder/'analysis.json');record=read(folder/'record.json');complete=read(folder/'target/complete.json')
        assert spec['mode']==record['mode']=='off' and not record['errors'] and record['target_returncode']==0 and not record['target_still_running'] and not record['observer_still_running']
        assert analysis['case_pass'] and all(analysis['checks'].values()) and roi['blocks']==analysis['blocks']
        assert roi['wall_ns']==analysis['wall_ns'] and roi['thread_cpu_ns']==analysis['thread_cpu_ns']==analysis['os_cpu_span_ns']
        assert all(complete[k] is True for k in ('full_report_exact','quality_runtime_exact','event_audit_exact','timeline_exact','mirror_exact','raw_archive_exact','inputs_unchanged','all_458_sources_unchanged'))
        rois[name]=roi;cases[name]=dict(block_checks=validate_blocks(roi),wall_ms=roi['wall_ns']/1e6,cpu_ms=roi['thread_cpu_ns']/1e6,cycles=analysis['cycles'],frames=roi['frames'],report_sha256=complete['report_canonical_sha256'],
                                      blocks=[dict(raw_first=b['raw_first'],raw_last=b['raw_last'],wall_ms=b['wall_ns']/1e6,cpu_ms=b['thread_cpu_ns']/1e6) for b in roi['blocks']])
    assert len({x['report_sha256'] for x in cases.values()})==1
    comparisons=[]
    for a,b in itertools.combinations(cases,2):
        x,y=rois[a],rois[b];assert [(v['raw_first'],v['raw_last']) for v in x['blocks']]==[(v['raw_first'],v['raw_last']) for v in y['blocks']]
        comparisons.append(dict(cases=[a,b],wall_delta_ms=(y['wall_ns']-x['wall_ns'])/1e6,cpu_delta_ms=(y['thread_cpu_ns']-x['thread_cpu_ns'])/1e6,
                                per_block_cpu_delta_ms=[(v['thread_cpu_ns']-u['thread_cpu_ns'])/1e6 for u,v in zip(x['blocks'],y['blocks'])],
                                per_block_wall_delta_ms=[(v['wall_ns']-u['wall_ns'])/1e6 for u,v in zip(x['blocks'],y['blocks'])]))
    result=dict(cases=cases,all_six_descriptive_comparisons=comparisons,manifest_files_verified=len(manifest),
                evidence='All four original frozen cases retained, all seven input blocks aligned. CPU and wall changes span the full ROI; no GUI/vision/SDK pipeline was running in this synchronous target.',
                limits=['Comparisons are descriptive dependent contrasts of four runs, not six independent experimental pairs.','thread_time and GetThreadTimes share OS accounting; agreement is not an independent physical frequency/instruction measurement.','Negative block wall-minus-CPU values expose boundary/quantization limits; never clamp or label the residual as GIL/scheduler waiting.','Cycles are not instruction counts or delivered CPU frequency. Coarse placements do not describe the entire migration history.','Matching final outputs does not prove identical internal allocations, call counts or machine instructions.','This old diagnostic has GC/placement observer overhead; findings cannot quantify contributions to historical GUI backlog.'],
                next='Use a fixed whole-chain input/state with coarse original stage boundaries and separately verified call identity to distinguish work-count growth from execution cost. Preserve original algorithm, GC and scheduling settings; timing wrappers must be calibrated before quantitative attribution.',
                actual_load_disturbance_pass=False,primary_root_identified=False)
    with (HERE/'result01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:dict(wall_ms=v['wall_ms'],cpu_ms=v['cpu_ms'],block_checks=v['block_checks']) for k,v in cases.items()},indent=2))
