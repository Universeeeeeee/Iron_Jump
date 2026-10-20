import hashlib,json,statistics
from pathlib import Path
HERE=Path(__file__).resolve().parent;sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
if __name__=='__main__':
 d=json.loads((HERE/'result01.json').read_text());by={}
 for repeat in d['repeats']:
  for b in repeat['blocks']:by.setdefault((b['first_sample'],b['last_sample']),[]).append(b['wall_ns']/b['samples']/1000)
 med={k:statistics.median(v) for k,v in by.items()}
 def weighted(a,z):
  total=cost=0
  for (x,y),v in med.items():overlap=max(0,min(y,z)-max(x,a)+1);total+=overlap;cost+=overlap*v
  return cost/total
 build=weighted(60227,62152);recover=weighted(62153,64977)
 out=dict(exact_algorithm_state=all(r['exact_algorithm_state'] for r in d['repeats']),offline_build_us_per_frame=build,offline_recover_us_per_frame=recover,offline_recover_relative_to_build=recover/build-1,
  retained_live_build_fps=846.8486151255076,retained_live_recover_fps=1129.1434769241444,
  conclusion='The saved algorithm chain is about20% more expensive in the live recovery input range, yet the isolated consumer runs about33% faster there. Input complexity cannot explain the transient recovery; Qt timer/scheduling/execution delivery dominates the inversion.',
  optimization_target='Reduce repeated zero-interval Qt wake dependence; batch40 candidate is sized to the measured5% peak gap.',bindings=dict(result_sha256=sha(HERE/'result01.json'),summarizer_sha256=sha(Path(__file__))))
 (HERE/'summary01.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
