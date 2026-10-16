"""Read-only historical reconstruction; exact queue observations, censored timings."""
import csv,hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'ground_backlog_measurement'
sys.path.insert(0,str(SOURCE))
from semantics import verify,read
TRIALS=[('scout_hardware_walk_connected','walk1'),('repeat_hardware_walk_2','walk2'),('repeat_hardware_walk_3','walk3'),('scout_hardware_run_connected','run1'),('repeat_hardware_run_2','run2'),('repeat_hardware_run_3','run3')]

def stats(a):
    return {'p50':float(np.median(a)),'p95':float(np.percentile(a,95)),'max':float(max(a))}
def write_csv(path,rows):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def prepare(folder):
    m,s,report,receipts,active=verify(folder)
    a=np.array(m['arrivals'],dtype=np.int64);n0=int(a[0,2]);arm=m['armed_ns']
    assert np.all(np.diff(a[:,0])>=0) and np.all(np.diff(a[:,1])>=0)
    assert np.all(a[:,0]>=a[:,1]) and np.array_equal(a[:,0],receipts)
    assert np.array_equal(a[:,2],np.arange(n0,n0+len(a)))
    q=sorted(m['queue_common']+m['queue_samples'],key=lambda r:r[0])
    t=np.array([r[0] for r in q],dtype=np.int64)
    E=np.array([r[5]-n0+1 for r in q]);C=np.array([r[1]-n0+1 for r in q]);Q=np.array([r[3] for r in q])
    S=np.searchsorted(a[:,1],t,side='right');A=np.searchsorted(a[:,0],t,side='right')
    assert np.all(np.diff(E)>=0) and np.all(np.diff(C)>=0)
    assert np.all(S>=A) and np.all(A>=E) and np.all(E>=C)
    assert np.all(A-E<=1) and np.all(E-C>=Q)
    assert np.array_equal(S-C,(S-A)+(A-E)+(E-C))
    assert np.array_equal(E-C-Q,np.array([r[8] for r in q]))
    assert E[-1]==C[-1]==len(a)
    # DirectConnection returns only after on_frame enqueues. Last frame is
    # bounded by a locked witness; no interpolation of real event timestamps.
    i=np.arange(1,len(a)+1)
    ew=np.searchsorted(E,i,side='left');cw=np.searchsorted(C,i,side='left')
    enq_upper=np.minimum(np.r_[a[1:,0],t[-1]],t[ew])
    c_upper=t[cw];c_lower=np.r_[a[0,0],t][cw]
    assert np.all(enq_upper>=a[:,0]) and np.all(c_upper>=enq_upper)
    assert np.all(c_upper>=c_lower)
    frame_rows=({'sample':int(n),'planned_ns':int(d),'prepared_ns':int(h),'enqueue_lower_ns':int(h),'enqueue_upper_ns':int(eu),'batch_ack_lower_ns':int(cl),'batch_ack_upper_ns':int(cu)} for (h,d,n),eu,cl,cu in zip(a,enq_upper,c_lower,c_upper))
    write_csv(HERE/'frames'/(folder.name+'.csv'),list(frame_rows))
    rows=[{'host_ns':int(v),'relative_s':(int(v)-arm)/1e9,'S_planned':int(ss),'A_prepared':int(aa),'E_enqueued':int(ee),'C_batch_ack':int(cc),'upstream_not_prepared':int(ss-aa),'prepared_not_enqueued':int(aa-ee),'enqueued_not_batch_ack':int(ee-cc),'pending_exact':int(qq),'popped_or_inflight':int(ee-cc-qq),'phase':r[9],'batch_first':r[10],'batch_last':r[11],'batch_size':r[12]} for v,ss,aa,ee,cc,qq,r in zip(t,S,A,E,C,Q,q)]
    write_csv(HERE/'snapshots'/(folder.name+'.csv'),rows)
    return m,s,a,q,t,S,A,E,C,Q,enq_upper,rows

def window(start,end,a,q,t,S,A,E,C,Q,arm):
    mask=(t>=start)&(t<end);ii=np.flatnonzero(mask);first,last=ii[0],ii[-1];dt=(t[last]-t[first])/1e9
    emitted=(a[:,0]>=start)&(a[:,0]<end)
    point=int(ii[np.argmax((S-C)[mask])]);r=q[point]
    p=[r for r in q if start<=r[0]<end and r[9]=='batch']
    return {'requested_host_window_s':[(start-arm)/1e9,(end-arm)/1e9],'observed_window_s':[(int(t[first])-arm)/1e9,(int(t[last])-arm)/1e9],'snapshot_count':len(ii),'planned_fps':float((S[last]-S[first])/dt),'prepared_fps':float((A[last]-A[first])/dt),'enqueued_fps':float((E[last]-E[first])/dt),'batch_ack_fps':float((C[last]-C[first])/dt),'source_lateness_ms':stats((a[emitted,0]-a[emitted,1])/1e6),'max_upstream_not_prepared':int(max((S-A)[mask])),'max_pending_exact':int(max(Q[mask])),'max_enqueued_not_batch_ack':int(max((E-C)[mask])),'largest_plan_to_ack_debt_snapshot':{'relative_s':(int(t[point])-arm)/1e9,'upstream_not_prepared':int(S[point]-A[point]),'prepared_not_enqueued':int(A[point]-E[point]),'enqueued_not_batch_ack':int(E[point]-C[point]),'pending_exact':int(Q[point]),'completed_sample':r[1],'latest_enqueued_sample':r[5]},'batch_phase_observations':len(p),'snapshot_max_gap_ms':float(max(np.diff(t[mask]))/1e6)}

def gaps(times,arm,label,threshold_ms,anchor_uncertainty_ms=0):
    out=[]
    for i in np.flatnonzero(np.diff(times)>threshold_ms*1e6):
        out.append({'stream':label,'start_s':(int(times[i])-arm)/1e9,'end_s':(int(times[i+1])-arm)/1e9,'gap_ms':float((times[i+1]-times[i])/1e6),'anchor_uncertainty_ms':anchor_uncertainty_ms})
    return out

def main():
    (HERE/'frames').mkdir(exist_ok=True);(HERE/'snapshots').mkdir(exist_ok=True)
    results=[];all_events=[];camera_events=[];manifest={};plots=[];topology=[]
    for name,short in TRIALS:
        folder=SOURCE/'runs'/name
        for f in folder.iterdir():
            if f.is_file() and f.suffix!='.mjpg':manifest[str(f.relative_to(SOURCE))]={'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
        m,s,a,q,t,S,A,E,C,Q,enq_upper,rows=prepare(folder);arm=m['armed_ns']
        due=dict(zip(a[:,2].tolist(),a[:,1].tolist()));empty_group=next(g for g in s['groups'] if g['phase']=='empty')
        empty=window(due[empty_group['start']],due[empty_group['end']],a,q,t,S,A,E,C,Q,arm)
        mask=(s['data']['sample_indices']>=empty_group['start'])&(s['data']['sample_indices']<empty_group['end'])
        bits=s['data']['bits'][mask].copy();bits[:,s['bad']]=0
        empty['raw_after_bad_mask']={'frames':len(bits),'frames_with_any_usable_bit':int(np.count_nonzero(bits.any(axis=1))),'max_usable_bits':int(bits.sum(axis=1).max())}

        whole=window(arm,int(t[-1])+1,a,q,t,S,A,E,C,Q,arm)
        with np.load(folder/'native_usb_frames.npz') as z:usb=z['received_ns'].copy()
        cam=list(csv.DictReader((folder/'native_camera.csv').open()));elapsed=np.array([float(v['record_elapsed_seconds']) for v in cam])
        checked_ns=int(a[a[:,2]==m['checked'],0][0]);lo=checked_ns;hi=arm;mid=(lo+hi)//2
        cam_t=mid+np.rint(elapsed*1e9).astype(np.int64);uncertainty=(hi-lo)/2e6
        assert len(cam)==m['native']['writer']['frames_written']
        assert sum(int(v['length']) for v in cam)==m['native']['writer']['bytes_written']
        camera_bounds={'record_start_relative_host_s':[(lo-arm)/1e9,0.],'alignment_midpoint_uncertainty_ms':uncertainty,'CSV_is_pre_Python_callback':True,'no_exact_record_start_timestamp':True}
        ps=np.array([r[0] for r in m['queue_samples']],dtype=np.int64)
        for i in np.flatnonzero(np.diff(elapsed)>.05):
            camera_events.append({'name':name,'short':short,'native_elapsed_start_s':float(elapsed[i]),'native_elapsed_end_s':float(elapsed[i+1]),'native_wall_gap_ms':float((elapsed[i+1]-elapsed[i])*1000),'media_sample_gap_ms':(float(cam[i+1]['sample_time'])-float(cam[i]['sample_time']))*1000,'capture_frame_index_start':int(cam[i]['capture_frame_index']),'capture_frame_index_end':int(cam[i+1]['capture_frame_index']),'host_start_lower_s':(lo-arm)/1e9+float(elapsed[i]),'host_start_upper_s':float(elapsed[i])})
        ack_ns=int(t[np.flatnonzero(C==len(a))[0]])
        stopped_ns=next(v[0] for v in m['native']['hardware']['states'] if v[1]=='disconnected')
        assert stopped_ns>ack_ns
        topology.append({'name':name,'source_frames_prepared_and_signal_emissions':len(a),'real_USB_frames_and_signal_emissions':len(usb),'source_frames_retained_payload_bytes':int(len(a)*(s['data']['bits'].shape[1]+s['data']['wire'].shape[1]+s['data']['valid_bits'].shape[1])),'USB_frames_retained_payload_bytes':int(len(usb)*1632),'retained_payload_bytes_excludes_Python_object_overhead':True,'first_all_batch_ack_witness_s':(ack_ns-arm)/1e9,'last_source_frame_prepared_s':(int(a[-1,0])-arm)/1e9,'first_all_enqueued_witness_s':(int(t[np.flatnonzero(E==len(a))[0]])-arm)/1e9,'USB_disconnect_s':(stopped_ns-arm)/1e9,'USB_NPZ_JSON_save_starts_after_disconnect':True,'USB_save_after_all_primary_ack':True})
        events=gaps(a[:,0],arm,'source_preparation',50)+gaps(usb,arm,'USB_Python_assembly',50)+gaps(cam_t,arm,'camera_native_pre_callback_approx',50,uncertainty)+gaps(ps,arm,'P_sampler_observation',200)
        for r in events:r.update(name=name,short=short,period='pre_arm' if r['end_s']<=0 else 'post_all_ack' if r['start_s']>=(ack_ns-arm)/1e9 else 'active_or_boundary')
        all_events.extend(events)
        formal_points=[r for r in m['queue_samples'] if arm<=r[0]<=t[-1]]
        phase_counts={ph:sum(r[9]==ph for r in formal_points) for ph in ('empty','batch','pending','handoff')}
        repeats=[]
        for prev,cur in zip(formal_points,formal_points[1:]):
            if prev[9]==cur[9]=='batch' and prev[10:]==cur[10:]:
                repeats.append({'start_s':(prev[0]-arm)/1e9,'end_s':(cur[0]-arm)/1e9,'observed_same_batch_span_ms':(cur[0]-prev[0])/1e6,'batch_first':cur[10],'batch_last':cur[11],'batch_size':cur[12]})
        focus=window(arm+7000000000,arm+14000000000,a,q,t,S,A,E,C,Q,arm) if short=='run2' else None
        result={'name':name,'short':short,'initial_empty_by_planned_time':empty,'whole_formal_observed':whole,'focus_7_14s':focus,'sampled_consumer_state_counts':phase_counts,'same_active_batch_across_sampler_points':repeats,'camera_alignment':camera_bounds,'snapshot_prepared_minus_enqueued_max':int(max(A-E)),'source_to_enqueue_upper_bound_ms':stats((enq_upper-a[:,0])/1e6),'semantic_exact':True}
        results.append(result);plots.append((short,arm,a,t,S,A,E,C,Q,events))
    (HERE/'summary.json').write_text(json.dumps(results,indent=2)+'\n')
    (HERE/'input_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (HERE/'topology_counts.json').write_text(json.dumps(topology,indent=2)+'\n')
    write_csv(HERE/'native_camera_gaps.csv',camera_events)
    write_csv(HERE/'gaps.csv',sorted(all_events,key=lambda r:(r['name'],r['start_s'],r['stream'])))
    plot(plots)
    print(json.dumps([{k:r[k] for k in ('short','snapshot_prepared_minus_enqueued_max','sampled_consumer_state_counts')} for r in results],indent=2))

def plot(data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(3,2,figsize=(13,10),layout='constrained')
    for (short,arm,a,t,S,A,E,C,Q,events),ax in zip(data,[axes[i,j] for j in range(2) for i in range(3)]):
        x=(t-arm)/1e9;mask=x>=0
        ax.plot(x[mask],(S-A)[mask],color='#d47908',label='Scheduled, not prepared')
        ax.plot(x[mask],(E-C)[mask],color='#1766a5',label='Enqueued, batch not acknowledged')
        ax.plot(x[mask],Q[mask],color='#278548',ls=':',label='Actual pending deque')
        ax.set(title=short,xlabel='Seconds after arm',ylabel='Frames');ax.grid(alpha=.2)
    axes[0,0].legend(fontsize=8);fig.suptitle('Historical backlog decomposition at locked snapshots (not CPU time)')
    fig.savefig(HERE/'overview.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(3,2,figsize=(14,10),layout='constrained')
    for col,key in enumerate(('walk1','run2')):
        short,arm,a,t,S,A,E,C,Q,events=next(d for d in data if d[0]==key);x=(t-arm)/1e9
        limits=(0,21) if col==0 else (7,14)
        mask=(x>=limits[0])&(x<=limits[1]);ax=axes[0,col]
        for col_time,label,color in ((1,'Planned','#999999'),(0,'Prepared','#d47908')):
            xx=(a[:,col_time]-arm)/1e9;chosen=(xx>=limits[0])&(xx<=limits[1]);yy=np.arange(1,len(a)+1)-3501
            ax.step(xx[chosen],yy[chosen],where='post',label=label,color=color,lw=1.2)
        for y,label,color in ((E,'Enqueued witness','#278548'),(C,'Batch-ack witness','#1766a5')):ax.plot(x[mask],y[mask]-3501,label=label,color=color,lw=1,ls=':',marker='.',markersize=2)
        ax.set(title=key,ylabel='Formal frames');ax.legend(fontsize=8);ax.set_xlim(*limits)
        ax=axes[1,col];ax.plot(x[mask],(S-A)[mask],label='Upstream not prepared',color='#d47908');ax.plot(x[mask],(E-C)[mask],label='Enqueued not batch acknowledged',color='#1766a5');ax.plot(x[mask],Q[mask],label='Exact pending',ls=':',color='#278548');ax.set(ylabel='Frames');ax.legend(fontsize=8);ax.set_xlim(*limits)
        ax=axes[2,col];labels=['source_preparation','USB_Python_assembly','camera_native_pre_callback_approx','P_sampler_observation']
        for r in events:
            if r['end_s']<limits[0] or r['start_s']>limits[1]:continue
            y=labels.index(r['stream']);ax.plot([r['start_s'],r['end_s']],[y,y],lw=5,solid_capstyle='butt',color=['#d47908','#7058a3','#278548','#777777'][y])
        ax.set_yticks(range(4),['Source gaps >50ms','USB assembly gaps >50ms','Native camera gaps >50ms*','P sample gaps >200ms']);ax.set(xlabel='Seconds after arm',ylim=(-.5,3.5));ax.set_xlim(*limits)
        for ax in axes[:,col]:ax.grid(alpha=.2)
    fig.suptitle('Two anomalies: actual observations and intervals without observations\n*Camera offset uncertainty: walk1 +/-116.75ms, run2 +/-5.97ms; bars do not identify CPU/GIL ownership',fontsize=12)
    fig.savefig(HERE/'anomalies.png',dpi=160);plt.close(fig)

if __name__=='__main__':main()
