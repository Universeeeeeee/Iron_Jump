"""Post-run frozen-window A/A evaluation; never imported by acquisition."""
import csv,hashlib,json,sys
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'single_usb_field'))
from verify_capture import verify,read
from analyze import window

def trial(item):
    p=HERE/'runs'/item['name'];integrity=verify(p);m=read(p/'measurement.json');cpu=read(p/'native_cpu.json')
    start=m['armed_ns']+3_000_000_000;end=m['armed_ns']+19_000_000_000
    points=sorted(m['queue_common']+m['queue_samples'],key=lambda v:v[0]);w=window(points,start,end)
    visual=[{'host_ns':m['armed_ns'],'visual':m['visual_start']}]+m['telemetry']+[{'host_ns':m['stop_request_ns'],'visual':m['visual_end']}]
    visual=[v for v in visual if start<=v['host_ns']<end];a,b=visual[0],visual[-1];elapsed=(b['host_ns']-a['host_ns'])/1e9
    preview=(b['visual']['renders']-a['visual']['renders'])/elapsed
    with (p/'camera.csv').open() as f:camera=list(csv.DictReader(f))
    record=read(p/'camera_record_start.json');origin=(record['before_ns']+record['after_ns'])/2
    times=[float(v['record_elapsed_seconds']) for v in camera if start<=origin+float(v['record_elapsed_seconds'])*1e9<end]
    camera_fps=(len(times)-1)/(times[-1]-times[0])
    seconds=(sum(cpu['clock_anchors'][1][k] for k in ('perf_before_ns','perf_after_ns'))-sum(cpu['clock_anchors'][0][k] for k in ('perf_before_ns','perf_after_ns')))/2e9
    thread_cpu={name:sum(cpu['end'][name][k]-cpu['start'][name][k] for k in ('user_100ns','kernel_100ns'))/1e7 for name in cpu['start']}
    trace=read(HERE/(item['name']+'_trace_validation.json')) if item['trace'] else None
    valid=integrity['integrity_passed'] and integrity['formal_usable_contact_fraction']<=.01
    return {'name':item['name'],'mode':item['mode'],'trace':item['trace'],'pair':item['pair'],'valid_empty_capture':valid,'integrity':integrity,'primary_3_to_19_host_s':w,'preview_fps':preview,'preview_observed_s':elapsed,'camera_record_fps':camera_fps,'camera_clock_scope':'Record-start perf bracket midpoint; CSV record elapsed, no camera/device drift correction.','native_cpu_seconds':thread_cpu,'native_cpu_snapshot_wall_s':seconds,'trace_validation':trace,'formal_visual':{k:m['visual_end'][k]-m['visual_start'][k] for k in m['visual_start']}}

def main():
    plan=read(HERE/'plan.json');assert read(HERE/'batch_complete.json')['completed']==12
    trials=[trial(v) for v in plan['trials']];pairs=[]
    for pair in range(1,7):
        off=next(v for v in trials if v['pair']==pair and not v['trace']);on=next(v for v in trials if v['pair']==pair and v['trace'])
        fps=on['primary_3_to_19_host_s']['consumer_fps']-off['primary_3_to_19_host_s']['consumer_fps']
        age=on['primary_3_to_19_host_s']['oldest_pending_ms']['p95']-off['primary_3_to_19_host_s']['oldest_pending_ms']['p95']
        preview=on['preview_fps']/off['preview_fps'];camera=on['camera_record_fps']/off['camera_record_fps']
        cpu=(on['native_cpu_seconds']['consumer']/on['native_cpu_snapshot_wall_s'])/(off['native_cpu_seconds']['consumer']/off['native_cpu_snapshot_wall_s'])
        checks={'captures_valid':off['valid_empty_capture'] and on['valid_empty_capture'],'consumer_fps_delta_abs_le20':abs(fps)<=20,'head_p95_increase_le20ms':age<=20,'preview_ratio_0.9_to_1.1':.9<=preview<=1.1,'camera_ratio_0.95_to_1.05':.95<=camera<=1.05,'consumer_cpu_increase_le10pct':cpu<=1.1,'trace_events_and_losses_valid':bool(on['trace_validation'] and on['trace_validation'].get('passed'))}
        pairs.append({'pair':pair,'mode':off['mode'],'consumer_fps_ON_minus_OFF':fps,'head_p95_ON_minus_OFF_ms':age,'preview_ON_div_OFF':preview,'camera_ON_div_OFF':camera,'consumer_native_cpu_fraction_ON_div_OFF':cpu,'checks':checks,'passed':all(checks.values())})
    output={'scope':plan['scope'],'frozen_plan_sha256':hashlib.sha256((HERE/'plan.json').read_bytes()).hexdigest(),'all_six_pairs_passed':all(v['passed'] for v in pairs),'pairs':pairs,'trials':trials,'limits':['No human or dense contact tracing calibration; observer retention/SDK logging overhead remains uncalibrated.','Only two native CPU boundary snapshots; approximate whole-20s CPU, separately from primary 3..19s window.','1000Hz input-capped consumer rate is not spare capacity or an optimization benefit.','No field ETW capture exists; no CPU-exclusive, GIL or GC root-cause attribution.']}
    (HERE/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (HERE/'pairs.csv').open('w',newline='') as f:
        rows=[{k:v for k,v in p.items() if k!='checks'} for p in pairs];w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps({'passed':output['all_six_pairs_passed'],'pairs':pairs},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
