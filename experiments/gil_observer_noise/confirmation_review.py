"""Review all fixed confirmation pairs, retaining the pilot and every outlier."""
import argparse
import math
from pathlib import Path
from scipy.stats import nct
from analyze import stage
from control03 import read,write
from noise_stats import acceptance,drift


def sensitivity(estimate):
    out={};n=estimate['independent_pairs'];df=estimate['df'];critical=estimate['critical_t']
    for key,m in estimate['metrics'].items():
        sd=m['sd_log_ratio']
        def power(effect):
            if sd==0:return 1.0 if effect else estimate['family_alpha']/estimate['family_size']
            nc=math.log1p(effect)*math.sqrt(n)/sd
            # Use t symmetry: this SciPy build can return NaN for the
            # tiny left CDF at large positive noncentrality. Never treat NaN as power.
            positive=float(nct.sf(critical,df,nc));negative=float(nct.sf(critical,df,-nc))
            if not math.isfinite(positive+negative):raise ArithmeticError('Noncentral-t tail failed')
            return min(1.0,positive+negative)
        lo,hi=0.0,1.0
        for _ in range(60):
            mid=(lo+hi)/2
            if power(mid)>=.8:hi=mid
            else:lo=mid
        out[key]=dict(power_for_positive_effect={str(x):power(x) for x in (.02,.03,.10)},minimum_positive_relative_effect_80pct=hi if power(1)>=.8 else None,limits='Noncentral-t sensitivity under the same parametric independent-pair assumptions; describes precision, not measured GUI/GIL effect.')
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=stage(a.raw,'confirmation_plan01.json','confirmation01');estimate=result['estimate'];result['acceptance']=acceptance(estimate)
    halfwidths={k:(math.log1p(m['simultaneous_ci_relative'][1])-math.log1p(m['simultaneous_ci_relative'][0]))/2 for k,m in estimate['metrics'].items()}
    result['precision']=dict(log_halfwidths=halfwidths,target=math.log1p(.01),all_at_or_below_target=all(v<=math.log1p(.01) for v in halfwidths.values()))
    by_mode={}
    for mode in ('off','on'):
        cases=[read(p) for p in sorted((a.raw/'confirmation01/run01').glob(f'pair*_{mode}/analysis.json'))];by_mode[mode]=drift(cases)
    result['drift_by_mode']=by_mode;result['sensitivity']=sensitivity(estimate)
    result['offline_3pct_equivalence_ready']=result['acceptance']['statistical_equivalence_pass'] and result['precision']['all_at_or_below_target'] and result['all_cadence_checks'] and not any(v['flag'] for v in by_mode.values())
    result['actual_load_disturbance_pass']=False;result['field_attribution_ready']=False;result['root_cause_or_fix_complete']=False
    result['limits']=['All24 fixed pairs retained, including first slow OFF; no trimming, normalization, re-sampling or extension.','AA vs confirmation has an explicit20ms phase change; AA supplies an approximate planning prior, not an exact phase-matched qualification.','Sparse samples do not yield GIL hold/wait shares. GUI/vision/SDK/USB concurrency and real pending are absent; field qualification remains false.']
    write(a.output,result)
    print({k:result[k] for k in ('acceptance','precision','offline_3pct_equivalence_ready','actual_load_disturbance_pass','field_attribution_ready')})
