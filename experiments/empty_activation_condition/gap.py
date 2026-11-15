"""One fixed inter-block quiet interval; no active target or hardware/power setter."""
import json
from pathlib import Path
import statistics
import sys
from spacing import SystemReader,gap,busy
HERE=Path(__file__).resolve().parent
if __name__=='__main__':
    p=json.loads((HERE/'plan01.json').read_text());exit_ns=int(sys.argv[1])
    r=gap(exit_ns,p['inter_block_gap_seconds'],SystemReader(),lambda v:print(json.dumps(v),flush=True))
    samples=r['system_samples'];loads=[busy(a,b) for a,b in zip(samples,samples[1:])]
    timing=(r['wait_finished_ns']-r['deadline_ns'])/1e9
    bounded=all(0<=v['end_ns']-v['begin_ns']<=50000000 for v in samples) and all(0<b['begin_ns']-a['begin_ns']<=6000000000 for a,b in zip(samples,samples[1:]))
    q=dict(readiness_lateness_seconds=timing,readiness_pass=0<=timing<=2,
        quiet_and_AC=bounded and len(loads)>=50 and statistics.median(loads)<=15 and max(loads)<=50 and {v['ac'] for v in samples}=={1},
        system_busy_median_percent=statistics.median(loads),system_busy_max_percent=max(loads),
        scope='Controller gap readiness/quiet observation only. Actual next target startup time is recorded separately, not asserted identical tothis marker.')
    with (HERE/'runs/inter_block_gap01.json').open('x') as f:json.dump(dict(record=r,quality=q),f,indent=2)
    assert q['readiness_pass'] and q['quiet_and_AC']
