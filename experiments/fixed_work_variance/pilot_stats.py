"""Descriptive four-pair pilot; old3%/1% acceptance is never inferred from OFF only."""
import math

def describe(pairs):
    import statistics as standard
    from scipy.stats import t
    n=len(pairs);assert n==4,'Fixed pilot is exactly four independent fresh-process pairs'
    names=('wall_ns','cpu_ns','cycles');output={}
    for name in names:
        values=[(a[name],b[name]) for a,b in pairs]
        if any(x<=0 or y<=0 for x,y in values):
            output[name]=dict(available=False,reason='Nonpositive delta retained; no epsilon or replacement');continue
        ratios=[math.log(y/x) for x,y in values];mean=standard.mean(ratios);sd=standard.stdev(ratios)
        half=float(t.ppf(1-.05/(2*len(names)),n-1))*sd/math.sqrt(n)
        output[name]=dict(available=True,independent_pairs=n,log_ratio_sd=sd,geometric_relative_change=math.expm1(mean),
                          simultaneous_t_interval_relative=[math.expm1(mean-half),math.expm1(mean+half)],log_half_width=half,
                          all_raw_relative_changes=[y/x-1 for x,y in values],raw_abs_15pct_checks=[abs(y/x-1)<=.15 for x,y in values])
    available=[x['log_ratio_sd'] for x in output.values() if x['available']]
    planning=None
    if len(available)==len(names):
        sd=max(available);options=[]
        for count in range(8,25):
            half=float(t.ppf(1-.05/(2*len(names)),count-1))*sd/math.sqrt(count)
            options.append(dict(pairs=count,predicted_log_half_width=half,meets_1pct_planning_target=half<=math.log(1.01)))
        selected=next((x for x in options if x['meets_1pct_planning_target']),options[-1])
        planning=dict(method='Once-only SD planning from this pilot, max endpoint SD,8..24 future pairs. Not a guarantee of variance stationarity or permission to extend this pilot.',selected=selected,all_options=options)
    return dict(endpoints=output,planning=planning,independent_pairs=n,actual_load_disturbance_pass=False,ON_started=False,
                limits='Bonferroni Student-t log-ratio intervals for3 endpoints assume independent stationary approximately normal pair log ratios. Pilot is descriptive; common observer cost and dynamic GUI applicability remain unknown.')
