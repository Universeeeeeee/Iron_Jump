"""Align retained queue build/recovery phases with model calls; no new workload."""
import hashlib,json,statistics
from pathlib import Path
HERE=Path(__file__).resolve().parent
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'));sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def phases(name):
 q=read(HERE/'evidence'/f'{name}_actor.json')['queue_common'];w=read(HERE/'evidence'/f'{name}_workload_final.json');start=next(r for r in q if r[5]>=60188);peak=max(q,key=lambda r:r[3]);end=next(r for r in q if r[5]>=64957);out={}
 spans=[('build',start,peak)]+([] if peak[0]>=end[0] else [('recover',peak,end)])
 for label,a,b in spans:
  duration=(b[0]-a[0])/1e9;service=(b[1]-a[1])/duration;rows=[x['record'] for x in w['rows']['inferences'] if a[0]/1e9<=x['record']['inference_start_s']<b[0]/1e9];cost=[(x['inference_end_s']-x['inference_start_s'])*1000 for x in rows]
  out[label]=dict(duration_s=duration,consumer_effective_fps=service,pending=[a[3],b[3]],model_calls=len(cost),model_wall_ms_median=None if not cost else statistics.median(cost),model_wall_ms_mean=None if not cost else statistics.mean(cost))
 if 'recover' not in out:out['recover']=None
 return out
if __name__=='__main__':
 cases={n:phases(n) for n in ('cold01_process','isolated01')}
 result=dict(cases=cases,conclusion='Model-call wall time does not order consumer capacity across these retained windows. Consumer/GUI process separation is the stronger actionable boundary, while exact causal share remains confounded.',
  evidence=['cold visual-process window has relatively faster model calls but severe consumer capacity','isolated-consumer window has slower model calls yet recovers above1000fps'],
  limits=['Cross-window execution state and input timing are not randomized.','No GIL/Qt/CPU contribution percentage or responsible function.'],
  bindings={n:sha(HERE/'evidence'/n) for n in ('cold01_process_actor.json','cold01_process_workload_final.json','isolated01_actor.json','isolated01_workload_final.json')})
 (HERE/'phase_alignment01.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
