"""Independent delivered-artifact checks and unfinished-work age accounting."""
import hashlib
import json
from pathlib import Path
import statistics

import numpy as np

HERE=Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    native=HERE/'native_windows'
    for ledger in (read(native/'native_v2_delivery.json'),read(native/'gui_v3_connection.json')['deliveries']):
        for row in ledger:
            expected=row.get('archive_sha256',row.get('sha256'))
            path=native/(row['experiment']+('.tar.gz'))
            assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,path
    folder=native/'E5v3_GUI'
    matrix=read(folder/'gui_pairs.json')
    assert matrix['complete'] and matrix['all_semantics_exact']
    reference_raw=None;reference_state=None
    results=[]
    for pair in matrix['pairs']:
        for arm in ('baseline','candidate'):
            item=pair[arm];actor_folder=folder/'runs'/item['name']/'client/actor'
            actor=read(actor_folder/'result.json')
            acquisition=read(actor_folder/'acquisition.json')
            assert not acquisition['issues']
            with np.load(actor_folder/'raw_frames.npz') as z:
                raw={k:z[k] for k in z.files}
            indices=raw['sample_indices']
            assert np.array_equal(indices,np.arange(int(indices[0]),int(indices[-1])+1))
            assert not raw['dropped_frames_before'].any()
            assert len(acquisition['frames'])==len(indices)
            assert len(np.unique(raw['stream_ids']))==1
            assert np.array_equal(raw['bits'],1-np.unpackbits(raw['wire'],axis=1,bitorder='little'))
            assert not any(f['quality_flags'] for f in acquisition['frames'])
            optical={k:v for k,v in raw.items() if k!='received_ns'}
            if reference_raw is None:reference_raw=optical
            for k in optical:assert np.array_equal(optical[k],reference_raw[k]),(item['name'],k)
            receipts={int(n):int(t) for n,t in zip(indices,raw['received_ns'])}
            state=read(actor_folder/'state.json');report=read(actor_folder/'report.json')
            branches=[report['report_config_snapshot']['device'],
                      report['report_config_snapshot']['beam_quality']['preflight'],
                      state['quality']['preflight']]
            checked=branches[0]['checked_sample_index']
            for branch in branches:
                assert branch['checked_monotonic_ns']==receipts[checked]
                del branch['checked_monotonic_ns']
            current=[report,state]
            if reference_state is None:reference_state=current
            assert reference_state==current,item['name']
            rows=sorted(actor['queue_common']+actor['queue_samples']+[actor['queue_final']],key=lambda x:x[0])
            completed=enqueued=int(indices[0])-1;bound=0;ages=[];live=[]
            touches=[e['touch_sample'] for e in item['events']]
            active_begin=min(touches);active_end=min(max(touches)+1200,int(indices[-1]))
            for row in rows:
                stamp,c,pending,e=int(row[0]),int(row[1]),int(row[3]),int(row[5])
                assert completed<=c<=e and enqueued<=e<=indices[-1]
                assert row[7]==e-c and row[8]==e-c-pending>=0
                bound=max(bound,e-completed);completed=c;enqueued=e
                if e>c:
                    # Include the popped/inflight oldest unfinished sample.
                    age=(stamp-receipts[c+1])/1e6
                else:age=0.0
                assert age>=0
                if stamp<=raw['received_ns'][-1] and e>checked:
                    ages.append(age)
                    if active_begin<=c<=active_end:live.append((e/1000,age))
            assert completed==enqueued==indices[-1]
            assert bound==item['unfinished_upper_bound']
            slope=float(np.polyfit([x[0] for x in live],[x[1] for x in live],1)[0]) if len(live)>2 else None
            results.append({'pair':pair['pair'],'arm':arm,'name':item['name'],
                'raw_frames':len(indices),'formal_report_frames':report['report_config_snapshot']['raw_buffer']['total_received_frames'],
                'unfinished_upper_bound':bound,'oldest_unfinished_age_live_p99_ms':float(np.percentile(ages,99)),
                'oldest_unfinished_age_live_max_ms':max(ages),
                'active_age_slope_ms_per_device_second':slope,'slope_points':len(live),
                'active_interval_samples':[active_begin,active_end],
                'scope':'Age sampled at batch/common/probe boundaries; includes inflight. No continuous-age maximum claim.'})
    candidates=[r for r in results if r['arm']=='candidate']
    slopes=[r['active_age_slope_ms_per_device_second'] for r in candidates]
    slope_gate=all(x is not None and x<=10 for x in slopes) and statistics.median(slopes)<=5
    output={'delivered_archives_sha_verified':True,'raw_full_streams_equal':True,
        'complete_reports_quality_runtime_events_timeline_equal':True,
        'host_clock_normalisation_verified_against_raw_receipts':True,
        'unfinished_bound_independently_reconstructed':True,'candidate_short_window_age_slope_gate':slope_gate,
        'candidate_age_slope_median':statistics.median(slopes),'runs':results,
        'limits':['One recorded walking input, repeated four pairs.','No physical capture, SDK or pose inference.',
                  'GUI is offscreen Qt paint completion, not display presentation.',
                  'Candidate performance gates do not imply stable latency improvement.']}
    (HERE/'E5_GUI_audit.json').write_text(json.dumps(output,indent=2))
    print(json.dumps({k:v for k,v in output.items() if k!='runs'},indent=2))


if __name__=='__main__':main()
