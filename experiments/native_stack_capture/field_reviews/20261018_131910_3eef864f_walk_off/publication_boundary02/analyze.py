"""Use exact filtered-output -> outer-input mapping before joining completion witnesses."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def bracket(points,sample):
    j=next(i for i,row in enumerate(points) if row[1]>=sample)
    assert j>0 and points[j-1][1]<sample<=points[j][1]
    return points[j-1],points[j]


def analyze(raw,mapping,prior):
    capture=raw/'formal/capture';measurement=read(capture/'measurement.json');report=read(capture/'report.json');checks=read(mapping/'checks.json')
    assert all(checks[k] for k in ('full_report_exact','quality_runtime_exact','event_audit_exact','unmasked_timeline_exact','mirror_history_exact','raw_archive_exact','all_458_sources_unchanged','input_files_unchanged'))
    assert all(sha(capture/n)==v for n,v in checks['input_sha256'].items())
    values=np.load(mapping/'output_map.npy');assert np.all(np.diff(values[:,1])==1) and np.all(np.diff(values[:,0])>=0)
    assert len(values)==checks['output_map_count']==measurement['raw_retained']
    outer_by_output=dict(zip(map(int,values[:,1]),map(int,values[:,0])))
    replay_publications=read(mapping/'publications.json');pubs=[e for e in report['walking_summary']['event_publications'] if e['active']]
    points=sorted(measurement['queue_common']+[measurement['queue_final']],key=lambda r:r[0]);assert all(p[9]!='batch' for p in points)
    with np.load(capture/'raw_frames.npz') as z:samples,receipts=z['sample_indices'].copy(),z['received_ns'].copy()
    def receipt(sample):
        i=int(np.searchsorted(samples,sample));assert samples[i]==sample;return int(receipts[i])
    result=[];old={e['contact_id']:e for e in prior['footprints']}
    for pub in pubs:
        replay=next(p for p in replay_publications if p['event']['contact_id']==pub['contact_id']);output=pub['published_sample'];outer=outer_by_output[output]
        assert replay['event']['published_sample']==replay['processor_sample']==output and replay['outer_raw_sample']==outer and replay['phase']=='input'
        before,after=bracket(points,outer);availability=receipt(outer);touch=receipt(pub['touch_sample']);paint=measurement['paints'][str(pub['contact_id'])]
        lower=max(before[0],availability);upper=after[0];assert lower<=upper and lower<=paint
        row=dict(contact_id=pub['contact_id'],touch_sample=pub['touch_sample'],processor_publication_sample=output,outer_raw_that_delivers_publication_sample=outer,filter_forwarding_samples=outer-output,completion_before=before,completion_after=after,publication_host_bounds_ns=[lower,upper],
            touch_receipt_to_paint_ms=(paint-touch)/1e6,touch_to_processor_sample_receipt_ms=(receipt(output)-touch)/1e6,additional_raw_forwarding_receipt_ms=(availability-receipt(output))/1e6,
            touch_to_required_outer_receipt_ms=(availability-touch)/1e6,required_outer_receipt_to_publication_bounds_ms=[(lower-availability)/1e6,(upper-availability)/1e6],
            publication_to_paint_bounds_ms=[max(0,(paint-upper)/1e6),(paint-lower)/1e6],required_outer_receipt_to_paint_ms=(paint-availability)/1e6,
            old_upper_bound_changed=round((after[0]-measurement['armed_ns'])/1e9,9)!=round(old[pub['contact_id']]['publication_processing_bracket_formal_s'][1],9))
        assert abs(row['touch_receipt_to_paint_ms']-old[pub['contact_id']]['receipt_to_paint_ms'])<1e-9
        result.append(row)
    return dict(case=prior['case'],input_sha256=checks['input_sha256'],mapping_sha256=sha(mapping/'output_map.npy'),checks_sha256=sha(mapping/'checks.json'),prior_review_sha256=sha(PRIOR_PATH),correction='published_sample is a filtered Processor index, not its outer raw consume call. Prior review01 publication bounds are superseded here; original receipt-to-paint, raw continuity, backlog and failed protocol are unchanged.',footprints=result,changed_completion_brackets=[r['contact_id'] for r in result if r['old_upper_bound_changed']],all_11_forwarding_lags_samples=sorted({r['filter_forwarding_samples'] for r in result}),actual_load_disturbance_pass=False,field_attribution_ready=False,root_cause_complete=False,limits=['Exact original-chain semantic replay gives an index mapping only, never field execution timestamps. Completion times still come only from consumer queue_common/queue_final.','Availability is an observed receipt boundary, not exact algorithm confirmation latency; it includes shape confirmation, filter lookahead and upstream reading/assembly timing.','The remaining host delay is queue/processing/dispatch, not exclusive CPU, GIL waiting or a particular function.','Do not sum independent upper bounds; the intervals describe one publication instant.','Earlier report and failed owner stream remain preserved and failed.'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--mapping',type=Path,required=True);p.add_argument('--prior',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();PRIOR_PATH=a.prior
    result=analyze(a.raw,a.mapping,read(a.prior))
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(changed=result['changed_completion_brackets'],last_two=result['footprints'][-2:]),indent=2))
