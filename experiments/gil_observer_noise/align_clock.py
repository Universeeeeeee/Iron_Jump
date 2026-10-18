"""Bound the mapping QPC -> existing host perf_counter_ns markers without target injection."""
import argparse
import json
from pathlib import Path


def mapping(anchors):
    if not anchors: raise ValueError('No anchors')
    frequency=anchors[0]['frequency']
    if any(a['frequency']!=frequency for a in anchors): raise ValueError('Frequency changed')
    if any('perf_before_ns' not in a or 'perf_after_ns' not in a for a in anchors):
        raise ValueError('Old one-sided perf clock is insufficient for bounded alignment')
    # Both QPC calls occur inside the perf-counter interval, allowing for GIL descheduling.
    lower=max(a['perf_before_ns']-a['qpc_after']*1000000000//frequency for a in anchors)
    upper=min(a['perf_after_ns']-a['qpc_before']*1000000000//frequency for a in anchors)
    if lower>upper: raise ValueError('Inconsistent QPC/perf clocks')
    if upper-lower>1000000: raise ValueError('Mapping uncertainty exceeds 1 ms')
    return dict(qpc_frequency=frequency,host_ns_offset_lower=lower,host_ns_offset_upper=upper,
                uncertainty_ns=upper-lower,formula='host_ns = qpc * 1e9 / frequency + offset; retain both bounds')


def main(record):
    anchors=[record['start'],record['end']]
    for group in ['before','after']:
        for thread in record['external_observation'][group]: anchors += [thread['start'],thread['end']]
    return mapping(anchors)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('record',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    result=main(json.loads(a.record.read_text()))
    with a.output.open('x') as stream:json.dump(result,stream,indent=2)
