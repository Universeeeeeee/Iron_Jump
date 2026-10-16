"""Exploratory dense-window audit; preserves the frozen broad-window classification."""
import json
from pathlib import Path
import numpy as np
from analyze import read,window
HERE=Path(__file__).resolve().parent

def summarize(folder):
    m=read(folder/'measurement.json');a=read(folder/'analysis.json');dense=read(folder/'dense_diagnostic.json');s=read(folder/'state.json')
    with np.load(folder/'raw_frames.npz') as z:sample=z['sample_indices'];received=z['received_ns']
    with np.load(folder/'raw_archive.npz') as z:ticks=np.rint(z['device_timestamps']*1000).astype(np.int64);bits=z['bits']
    idx=np.searchsorted(sample,ticks);host=received[idx];formal=(host>=m['armed_ns'])&(host<m['stop_request_ns']);origin=int(ticks[np.flatnonzero(formal)[0]])
    points=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0]);bins=[]
    for b in a['device_contact_bins']:
        mask=formal&((ticks-origin)//1000==b['device_second']);t=host[mask];n=ticks[mask];delta=(t-t[0])/1e6-(n-n[0])
        bins.append({**b,'first_receipt_relative_s':float((t[0]-m['armed_ns'])/1e9),'last_receipt_relative_s':float((t[-1]-m['armed_ns'])/1e9),'max_interreceipt_gap_ms':float(np.max(np.diff(t))/1e6) if len(t)>1 else None,'arrival_clock_offset_span_ms':float(np.ptp(delta)),'queue_window':window(points,int(t[0]),int(t[-1])+1)})
    end=m['armed_ns']+int(dense['blocks'][-1]['end_host_relative_s']*1e9)
    witness=next((r for r in points if end<=r[0]<m['stop_request_ns'] and r[3]==r[7]==0),None)
    return {'name':folder.name,'scope':'Post hoc audit of predeclared density bins. Not a changed prespecified acceptance result. Arrival offsets use application receipt timestamps, not wire timestamps.','frozen_broad_window_gate':a['sustained_shortage_reproduced'],'dense_blocks':dense['blocks'],'density_bin_metrics':bins,'dense_end_first_observed_empty_witness_ms':None if witness is None else (witness[0]-end)/1e6,'recovery_scope':'First sampled pending=unfinished=0 after dense-bin end; not physical last-step recovery. Late beam-64 pulses make original any-contact recovery a different quantity.','initial_empty':a['windows']['initial_empty'],'whole':a['windows']['whole_formal'],'paint_latency':a['footprint_receipt_to_paint_ms'],'actual_pose_coverage_all_contact_intervals':a['contact_pose_present_in_each_observed_interval'],'formal_visual':a['visual_formal']}

if __name__=='__main__':
    value=[summarize(HERE/'runs'/n) for n in ('field_walk_02','field_run_01')]
    (HERE/'phase_metrics.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{k:v for k,v in r.items() if k not in ('density_bin_metrics','whole','initial_empty','dense_blocks')} for r in value],ensure_ascii=False,indent=2))
