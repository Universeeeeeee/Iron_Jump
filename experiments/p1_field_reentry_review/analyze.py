"""Recompute queue/contact-to-paint facts from four retained real single-USB Walk runs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('field_analysis',ROOT/'experiments/single_usb_field/analyze.py')
field=importlib.util.module_from_spec(spec);spec.loader.exec_module(field)

if __name__=='__main__':
    onsite=read(HERE/'onsite_observations01.json');rows=[]
    for folder in sorted(p for p in (HERE/'runs').iterdir() if p.is_dir()):
        m=read(folder/'measurement.json');report=read(folder/'report.json');state=read(folder/'state.json')
        acquisition=read(folder/'acquisition.json');controller=read(folder/'controller_result.json')
        with np.load(folder/'raw_frames.npz') as z:
            raw={k:z[k].copy() for k in z.files}
        samples=raw['sample_indices'];received=raw['received_ns'];bits=raw['bits'].copy()
        assert len(samples)==len(received)==len(bits)==len(acquisition['frames'])
        assert 0<m['raw_total']<=len(samples)
        assert np.all(np.diff(samples)==1) and np.all(np.diff(received)>=0)
        assert np.all(raw['dropped_frames_before']==0) and not acquisition['issues']
        assert controller['valid_capture'] and controller['terminated_after_child_cleanup']
        assert not controller['trace_owned_remaining'] and not controller['errors']
        assert not m['errors'] and not m['SDK_errors'] and m['queue_final'][3]==m['queue_final'][7]==0
        bad=state['quality']['preflight']['bad_indices'];bits[:,bad]=0
        formal=(received>=m['armed_ns'])&(received<m['stop_request_ns'])
        contact=formal&np.any(bits>0,axis=1)
        points=sorted(m['queue_common']+m['queue_samples']+[m['queue_final']],key=lambda v:v[0])
        formal_points=[v for v in points if m['armed_ns']<=v[0]<m['stop_request_ns']]
        initial=field.window(points,m['armed_ns'],m['armed_ns']+5_000_000_000)
        contact_window=None
        if contact.any():
            first=int(received[np.flatnonzero(contact)[0]]);last=int(received[np.flatnonzero(contact)[-1]])+1_000_000
            contact_window=field.window(points,first,last)
        lookup={int(sample):i for i,sample in enumerate(samples)};paint={int(k):v for k,v in m['paints'].items()}
        pubs=report['walking_summary']['event_publications'];timings=[]
        for event in pubs:
            cid=event.get('contact_id');touch=event.get('touch_sample')
            if event.get('active') and cid in paint and touch in lookup:
                timings.append(dict(contact_id=cid,touch_sample=touch,
                    receipt_to_paint_ms=(paint[cid]-int(received[lookup[touch]]))/1e6))
        formal_received=received[formal];formal_samples=samples[formal]
        actual_rate=(formal_samples[-1]-formal_samples[0]) / ((formal_received[-1]-formal_received[0])/1e9)
        oldest=[(v[0]-v[4])/1e6 for v in formal_points if v[4] is not None]
        completed=[(v[0]-v[2])/1e6 for v in formal_points]
        max_paint=max(v['receipt_to_paint_ms'] for v in timings)
        row=dict(case=folder.name,source_sha256={p.name:sha(p) for p in folder.iterdir() if p.is_file()},
            onsite=onsite[folder.name],controller_child_returncode=controller['child_returncode'],
            raw_frames_with_preparation=len(samples),formal_archive_frames=m['raw_total'],
            formal_frames=int(formal.sum()),actual_receipt_rate_fps=actual_rate,
            max_receipt_gap_ms=float(np.diff(formal_received).max()/1e6),initial_empty=initial,contact_window=contact_window,
            observed_pending_max=max(v[3] for v in formal_points),observed_oldest_pending_max_ms=max(oldest,default=0),
            completed_receipt_age_max_ms=max(completed),active_publications=sum(bool(v.get('active')) for v in pubs),
            active_publications_painted=len(timings),algorithm_touch_count=report['touch_count'],algorithm_lift_count=report['lift_count'],
            receipt_to_paint=timings,receipt_to_paint_max_ms=max_paint,receipt_to_paint_p95_ms=float(np.percentile([v['receipt_to_paint_ms'] for v in timings],95)),
            severe_real_backlog=actual_rate>=990 and (max(v[3] for v in formal_points)>=1000 or max_paint>=1000),
            field_integrity_pass=True)
        rows.append(row)
    out=dict(cases=rows,
        conclusions=[
            'All four retained runs deliver approximately1000fps into the host after USB assembly; severe delay is not required by low input rate.',
            'At least one real single-USB run has host-side FIFO and contact-to-paint delay above1s; later runs can be fast without production code changes.',
            'Onsite perceived delay is retained independently and may disagree with sparse queue observations; neither source is silently rewritten.',
            'These original-only runs establish the field symptom range, not a candidate A/B or CPU/GIL contribution.'
        ],
        P0_CPU_gate_used_for_P1_metrics=False,
        next_experiment=dict(
            candidate='Combined camera/video plus MediaPipe process boundary, not model-only isolation.',
            prerequisite='First pass delivery/semantic equivalence on saved input: exact selected frames/pixels/model outputs/pose decisions/SDK commands andfinal report.',
            field_design='Order-balanced fresh-system blocks. Record original andcandidate under matched Core/OS delivery bands; severe original required before a repair claim. Do not pair a slow original with a naturally recovered candidate.',
            endpoints=['actual receipt rate','consumer fps','continuous FIFO upper bound','oldest pending age','receipt contact-to-paint','planned contact-to-paint','input lateness','all active publications painted'],
            absolute_candidate_limits={'continuous_FIFO_frames':250,'max_planned_contact_to_paint_ms':250,'max_input_lateness_ms':150},
            semantic_gates=['raw wire/bits/validity/counters','quality/runtime/audit/timeline/mirror','complete report','actual video/model/SDK work','human step/first-foot kept separate'],
            CPU_attribution_gate='Historical31.25ms failure remains. Any new CPU mechanism capture must include DPC/ISR,CSwitch,PMC andnative boundaries; no percentages otherwise.'),
        goal_complete=False,
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),HERE/'onsite_observations01.json',ROOT/'experiments/single_usb_field/analyze.py')})
    with (HERE/'result01.json').open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
