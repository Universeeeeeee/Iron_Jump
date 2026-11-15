"""Prespecified state proxies and spacing-qualification boundaries."""
import statistics
from spacing import busy


def state(result,rules):
    prep=(result['preparation']['end_ns']-result['preparation']['begin_ns'])/1e6
    calls=result['model']['calls']
    median=statistics.median((v['end_ns']-v['begin_ns'])/1e6 for v in calls)
    label='slow' if prep>=rules['slow_prepare_ms_min'] and median>=rules['slow_model_ms_min'] else 'fast' if prep<=rules['fast_prepare_ms_max'] and median<=rules['fast_model_ms_max'] else 'intermediate'
    return dict(label=label,prepare_wall_ms=prep,prepare_cpu_ms=result['preparation']['thread_cpu_ns']/1e6,
                consumer_wall_ms=(result['consumer']['end_ns']-result['consumer']['begin_ns'])/1e6,
                consumer_cpu_ms=result['consumer']['thread_cpu_ns']/1e6,model_call_median_ms=median)


def spacing_quality(record,rules):
    requested=record['requested_gap_seconds'];actual=(record['child_launch_before_ns']-record['previous_exit_observed_ns'])/1e9
    assert actual>=requested
    intervals=[busy(a,b) for a,b in zip(record['system_samples'],record['system_samples'][1:])]
    long=requested==rules['long_gap_seconds']
    power=[r['ac'] for r in record['system_samples']]
    samples=record['system_samples']
    bounded=all(0<=v['end_ns']-v['begin_ns']<=50_000_000 for v in samples)
    bounded=bounded and all(0<b['begin_ns']-a['begin_ns']<=6_000_000_000 for a,b in zip(samples,samples[1:]))
    return dict(actual_gap_seconds=actual,launch_lateness_seconds=actual-requested,
        spacing_pass=0<=actual-requested<=rules['maximum_launch_lateness_seconds'],
        system_busy_median_percent=statistics.median(intervals) if intervals else None,
        system_busy_max_percent=max(intervals) if intervals else None,
        long_gap_quiet_and_AC=(bounded and len(intervals)>=rules['min_long_intervals'] and statistics.median(intervals)<=rules['long_system_busy_median_percent_max'] and max(intervals)<=rules['long_system_busy_max_percent_max'] and set(power)=={rules['required_AC']}) if long else None,
        system_read_max_ns=max((r['end_ns']-r['begin_ns'] for r in record['system_samples']),default=0))
