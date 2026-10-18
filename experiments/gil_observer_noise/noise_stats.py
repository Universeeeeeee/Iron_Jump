"""Pair-level log-ratio uncertainty; blocks do not create extra replicates."""
import math
import statistics
from scipy.stats import t, spearmanr

METRICS=('wall_ns','thread_cpu_ns','cycles')


def values(case):
    return {**{k:case[k] for k in METRICS},**{f'block_{b["raw_first"]}':b['wall_ns'] for b in case['blocks']}}


def contrast(pairs,alpha=.05):
    if len(pairs)<2:raise ValueError('At least2 independent fresh process pairs required')
    a0,b0=map(values,pairs[0]);keys=tuple(a0)
    if any(tuple(values(a))!=keys or tuple(values(b))!=keys for a,b in pairs):raise ValueError('Metric/block identity mismatch')
    family=len(keys);n=len(pairs);critical=float(t.ppf(1-alpha/(2*family),n-1));result={}
    for key in keys:
        ratios=[]
        for a,b in pairs:
            x,y=values(a)[key],values(b)[key]
            if x<=0 or y<=0:raise ValueError('Nonpositive timing/counter metric')
            ratios.append(math.log(y/x))
        mean=statistics.mean(ratios);sd=statistics.stdev(ratios);half=critical*sd/math.sqrt(n)
        result[key]=dict(n=n,mean_log_ratio=mean,sd_log_ratio=sd,geometric_relative_change=math.expm1(mean),simultaneous_ci_relative=[math.expm1(mean-half),math.expm1(mean+half)],raw_relative_changes=[math.expm1(x) for x in ratios],absolute_change_max=max(abs(math.expm1(x)) for x in ratios))
    return dict(metrics=result,independent_pairs=n,df=n-1,family_size=family,family_alpha=alpha,critical_t=critical,method='Two-sided Student t on whole-pair log ratios, Bonferroni family interval. No outlier removal; block metrics are correlated endpoints, not independent replicates. Requires adequately stationary independent pair errors; small pilot is not a distribution-free guarantee.')


def precision_plan(off_aa,on_aa,minimum=8,maximum=24,halfwidth=.01):
    keys=tuple(off_aa['metrics'])
    if tuple(on_aa['metrics'])!=keys:raise ValueError('A/A endpoint mismatch')
    sd={k:math.sqrt((off_aa['metrics'][k]['sd_log_ratio']**2+on_aa['metrics'][k]['sd_log_ratio']**2)/2) for k in keys}
    threshold=math.log1p(halfwidth);required=None
    for n in range(minimum,maximum+1):
        critical=float(t.ppf(1-.05/(2*len(keys)),n-1))
        if all(critical*s/math.sqrt(n)<=threshold for s in sd.values()):required=n;break
    return dict(chosen_pairs=required or maximum,predicted_precision_sufficient=required is not None,minimum=minimum,maximum=maximum,target_simultaneous_log_halfwidth=threshold,pooled_AA_predicted_sd=sd,rule='Freeze once from both completed A/A pilots, then one fixed OFF/ON cohort. Cap does not imply sufficient precision; no optional stopping or success-driven extra pairs.')


def acceptance(estimate,equivalence=.03,legacy_hard_limit=.15):
    all_ci=all(-equivalence<=m['simultaneous_ci_relative'][0] and m['simultaneous_ci_relative'][1]<=equivalence for m in estimate['metrics'].values())
    hard=all(m['absolute_change_max']<=legacy_hard_limit for m in estimate['metrics'].values())
    return dict(equivalence_limit=equivalence,all_simultaneous_intervals_inside=all_ci,every_original_trial_inside_legacy_hard_limit=hard,statistical_equivalence_pass=all_ci and hard,limits='This is a new3% family-equivalence requirement plus the retained15% per-trial hard bound; does not rewrite earlier failed gates or qualify GUI/SDK/field load.')


def drift(cases):
    v=[c['wall_ns'] for c in cases];rho,p=spearmanr(list(range(len(v))),v)
    return dict(n=len(v),rank_rho=float(rho) if math.isfinite(rho) else None,pvalue=float(p) if math.isfinite(p) else None,flag=bool(math.isfinite(rho) and abs(rho)>=.7 and p<.05),wall_range_relative=max(v)/min(v)-1,limits='Screen for monotone drift; absence of a flag does not prove stationarity. Do not post-hoc correct timing or infer CPU frequency from cycles.')
