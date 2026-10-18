"""Bound deque peaks between every preserved FIFO witness, without interpolation."""
import hashlib
import json
from pathlib import Path


def bound_deque(rows,first,last):
    if not rows or first>last:raise ValueError('Missing source/observations')
    if any(a[0]>b[0] for a,b in zip(rows,rows[1:])):raise ValueError('Observations out of order')
    previous_e=previous_d=first-1;upper=0
    for stamp,e,p in rows:
        d=e-p
        if not first-1<=previous_e<=e<=last or not first-1<=previous_d<=d<=e or p<0:raise ValueError('Not a contiguous frame-only FIFO prefix')
        # Within (previous observation, this one), E<=this E and D>=previous D.
        upper=max(upper,e-previous_d);previous_e,previous_d=e,d
    if previous_e!=last or previous_d!=last:raise ValueError('No final empty witness; tail peak unbounded here')
    return dict(combined_observed_deque_peak_lower_bound=max(p for _,_,p in rows),continuous_deque_peak_upper_bound=upper,observations=len(rows),first_observed_host_ns=rows[0][0],last_observed_host_ns=rows[-1][0])


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();root=Path(__file__).resolve().parents[2]
    read=lambda path:json.loads(path.read_text(encoding='utf-8-sig'))
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    cohorts=[('prior','gil_gui_calibration01','off_aa01'),('repeat','gil_gui_restart_repeat01','restart_repeat01')]
    captures=[];manifests={}
    for label,name,stage in cohorts:
        raw=root/'experiments/native_stack_capture/runs'/name/'evidence01';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());manifests[label]=sha(raw/'manifest.json')
        base=raw/'experiments/gil_gui_calibration/runs'/stage
        captures.extend((label+'/'+case.name,case/'capture') for case in sorted(base.glob('pair*')))
    raw=root/'experiments/gil_workload_observation/runs/evidence02';manifest=read(raw/'manifest.json');assert all(sha(raw/n)==v for n,v in manifest.items());manifests['metadata_failed02']=sha(raw/'manifest.json')
    captures.append(('metadata_failed02/off_a',raw/'runs/observation02/off_a/capture'))
    cases={}
    import numpy as np
    for label,folder in captures:
        m=read(folder/'measurement.json');common=m['queue_common'];sampled=m['queue_samples']
        with np.load(folder/'raw_frames.npz') as source:
            indices=source['sample_indices'];first=int(indices[0]);last=int(indices[-1]);assert np.array_equal(indices,np.arange(first,last+1))
        rows=sorted([[r[0],r[5],r[3]] for r in common+sampled]);result=bound_deque(rows,first,last)
        result.update(common_witness_peak=max(r[3] for r in common),periodic_probe_peak=max(r[3] for r in sampled),measurement_sha256=sha(folder/'measurement.json'))
        cases[label]=result
    result=dict(cases=cases,source_manifest_sha256=manifests,
                proof='Frame-only FIFO starts empty. D=E-P. Between consecutive observations i,j, E(t)<=E_j and D(t)>=D_i, so P(t)<=E_j-D_i. Initial interval uses D_start=first_sample-1. Final observed E=D=last plus finite EOF bounds the tail. No interpolation.',
                assumptions=['Only the frozen contiguous-file Source is covered; it emits frames without issue entries. This does not automatically apply to live USB/issue queues.',
                             'E/P witnesses are locked and dequeue/enqueue prefixes are monotone. Queue size P excludes already popped/inflight frames.',
                             'Observed maxima are lower bounds on the actual peak. Combined upper bound is conservative; neither point family alone is the continuous maximum.',
                             'Current failed02 metadata acceptance remains failed. These are bounds for the instrumented runs, not zero-observer counterfactuals or CPU/GIL attribution.'],
                actual_load_disturbance_pass=False,field_attribution_ready=False,primary_root_identified=False)
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps({k:{n:v[n] for n in ('common_witness_peak','periodic_probe_peak','combined_observed_deque_peak_lower_bound','continuous_deque_peak_upper_bound')} for k,v in cases.items()},indent=2))
