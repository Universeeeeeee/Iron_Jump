"""Existing GUI archives on one clock axis; associations, not root attribution."""
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
from pathlib import Path
import statistics
import numpy as np
import zipfile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
FILETIME_EPOCH_NS=11644473600000000000


def utc_bounds(host_ns,anchor):
    # Use only the local anchor at this endpoint. QPC and UTC need not share
    # one immutable offset across an entire window (UTC can be slewed).
    lo=anchor['filetime_100ns']*100-FILETIME_EPOCH_NS-anchor['perf_after_ns']
    hi=anchor['filetime_100ns']*100-FILETIME_EPOCH_NS-anchor['perf_before_ns']
    assert lo<=hi
    return [host_ns+lo,host_ns+hi]


def prefix_equal(a,b):
    count=0
    for x,y in zip(a,b):
        if x!=y:break
        count+=1
    return count


if __name__=='__main__':
    groups=[('session_gui_comparison','plan02.json'),('session_startup_accounting','plan01.json'),
        ('label_call_identity','plan02.json'),('preview_bridge_delivery','plan01.json'),
        ('preview_native_sdk','plan01.json'),('preview_gil_ab','plan01.json')]
    rows=[];bindings={};coverage=[]
    for name,planname in groups:
        folder=ROOT/'experiments'/name;planpath=folder/planname;plan=read(planpath)
        archive=folder/'evidence01.zip' if (folder/'evidence01.zip').exists() else folder/'runs/evidence01.zip'
        bindings[str(archive.relative_to(ROOT))]=sha(archive);bindings[str(planpath.relative_to(ROOT))]=sha(planpath)
        with zipfile.ZipFile(archive) as z:
            manifest=json.loads(z.read('manifest01.json'));files=manifest.get('files',manifest)
            assert all(hashlib.sha256(z.read(n.replace('\\','/'))).hexdigest()==digest for n,digest in files.items())
            assert all(files[n]==v for n,v in plan['sources'].items())
            status=json.loads(z.read('runs/cohort01/status.json'));assert status['complete'] and not status['errors']
            for ordinal,case in enumerate(plan['cases'],1):
                prefix=f"runs/cohort01/{case['id']}/";capture=prefix+'capture/'
                record=json.loads(z.read(prefix+'record.json'));assert record['complete'] and record['target_returncode']==0 and not record['target_still_running']
                assert all(record['semantics'][k] for k in ('full_original_report','full_quality_runtime_state','raw_fields_exact'))
                work=json.loads(z.read(capture+'workload_final.json'));context=json.loads(z.read(capture+'gui_context.json'))
                actor=json.loads(z.read(capture+'client/actor/result.json'));report=json.loads(z.read(capture+'client/actor/report.json'))
                gui=json.loads(z.read(capture+'gui_result.json'));opens=work['rows']['model_open'];calls=work['rows']['adapter_calls']
                assert len(opens)==1 and opens[0]['error'] is None and calls and all(v['error'] is None for v in calls)
                assert all(v['shape']==[360,640,3] and v['dtype']=='uint8' for v in calls)
                touch=min(e['touch_sample'] for e in report['walking_summary']['event_publications'] if e['active'])
                with np.load(io.BytesIO(z.read(capture+'client/actor/raw_frames.npz'))) as raw:
                    index=int(np.searchsorted(raw['sample_indices'],touch));assert int(raw['sample_indices'][index])==touch
                    touch_receipt=int(raw['received_ns'][index])
                before=[v for v in calls if v['end_ns']<=touch_receipt]
                assert len(before)>=20
                median=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in before)
                state='slow' if median>=30 else 'fast' if median<=26 else 'intermediate'
                anchors=work['anchors'];start=utc_bounds(anchors[0]['perf_ns'],anchors[0]);end=utc_bounds(anchors[-1]['perf_ns'],anchors[-1])
                utc_elapsed=[end[0]-start[1],end[1]-start[0]]
                perf_elapsed=anchors[-1]['perf_ns']-anchors[0]['perf_ns']
                row=dict(cohort=name,case=case['id'],cohort_ordinal=ordinal,pid=work['pid'],backend=case['backend'],
                    boundary=case.get('boundary','bridge' if name in ('preview_bridge_delivery','preview_native_sdk') else 'original'),
                    sdk='real' if name in ('preview_native_sdk','preview_gil_ab') else 'simulated',
                    observation_start_perf_ns=anchors[0]['perf_ns'],observation_end_perf_ns=anchors[-1]['perf_ns'],
                    observation_start_utc_ns_bounds=start,observation_end_utc_ns_bounds=end,
                    UTC_elapsed_minus_perf_ns_bounds=[v-perf_elapsed for v in utc_elapsed],
                    observation_start_UTC=datetime.fromtimestamp(start[0]/1e9,timezone.utc).isoformat(),
                    observation_start_China=datetime.fromtimestamp(start[0]/1e9,timezone(timedelta(hours=8))).isoformat(),
                    open_wall_ms=(opens[0]['end_ns']-opens[0]['begin_ns'])/1e6,
                    first_base_call_wall_ms=(calls[0]['end_ns']-calls[0]['begin_ns'])/1e6,
                    precontact_base_calls=len(before),precontact_base_median_ms=median,exploratory_state=state,
                    precontact_first10_wall_ms=[(v['end_ns']-v['begin_ns'])/1e6 for v in calls[:10]],
                    model_calls=len(calls),video_frames=len(gui['video_frame_ids']),
                    session_id=context['session_id'],priority_class=context['priority_class'],qpa=context['qpa'],
                    process_power_policy=context['process'],thread_power_policy=context['thread'],
                    original_report_raw_state_exact=True,model_closed_in_tail=work['model_end_checks'])
                rows.append(row)
            coverage.append(dict(cohort=name,cases=len(plan['cases']),manifest_files_verified=len(files)))
    rows.sort(key=lambda v:v['observation_start_perf_ns'])
    for i,row in enumerate(rows):
        row['preceding_retained_window']=None if not i else dict(cohort=rows[i-1]['cohort'],case=rows[i-1]['case'],state=rows[i-1]['exploratory_state'])
        row['gap_between_observation_brackets_s']=None if not i else (row['observation_start_perf_ns']-rows[i-1]['observation_end_perf_ns'])/1e9
        # Retained observations omit other activities and do not prove idle gaps.
        assert not i or row['observation_start_perf_ns']>rows[i-1]['observation_end_perf_ns']
    result=dict(scope='Six existing GUI cohorts only. All windows retained; no new workload orintervention. Chronological state proxies, no causal/CPU/GIL shares.',
        classifier=dict(slow_base_median_at_least_ms=30,fast_at_most_ms=26,basis='Prior startup-accounting exploratory labels reused, not optimized on this timeline. First-touch actual receipt cutoff; no claim of identical selected model work.'),
        archives=coverage,rows=rows,
        findings=dict(total_windows=len(rows),slow=sum(r['exploratory_state']=='slow' for r in rows),fast=sum(r['exploratory_state']=='fast' for r in rows),
            same_recorded_session=len({r['session_id'] for r in rows})==1,
            same_recorded_priority=len({r['priority_class'] for r in rows})==1,
            slow_windows_not_first_in_their_cohort=[dict(cohort=r['cohort'],case=r['case']) for r in rows if r['exploratory_state']=='slow' and r['cohort_ordinal']!=1],
            fast_to_slow_across_retained_windows=[dict(cohort=r['cohort'],case=r['case'],gap_s=r['gap_between_observation_brackets_s']) for r in rows if r['exploratory_state']=='slow' and r['preceding_retained_window'] and r['preceding_retained_window']['state']=='fast']),
        limits=['A cohort ordinal is not the first application use since boot. Observation brackets are not process birth/death.',
            'Gaps contain unretained other work/preparation; no claim of idle time or reset by elapsed time.',
            'These cohorts differ in measurement, SDK and intervention. No pooled effect estimates orcross-cohort CPU subtraction.',
            'Same session/priority and successful policy getters do not prove unchanged hardware delivery.',
            'Model wall-time proxies do not distinguish calculation, GIL, memory, worker activity orCPU delivery.'],
        root_condition_confirmed=False,new_windows=False,bindings=dict(inputs=bindings,script_sha256=sha(Path(__file__))))
    with (HERE/'chronology01.json').open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(dict(findings=result['findings'],timeline=[{k:r[k] for k in ('observation_start_China','cohort','case','exploratory_state','precontact_base_median_ms','gap_between_observation_brackets_s')} for r in rows]),indent=2))
