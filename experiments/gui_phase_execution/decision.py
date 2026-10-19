"""Symptom feasibility decision; never overwrites failed fixed-work mechanism gate."""
import math
import statistics

def decide(pairs):
    if len(pairs)!=4:raise ValueError('Exactly four pairs required')
    all_cases=[x for pair in pairs for x in pair]
    if not all(x['qualified'] for x in all_cases):return dict(advance=False,reason='unqualified_window')
    if any(x['scheduled_max_ms']<=0 for x in all_cases):raise ValueError('Invalid latency')
    severe=sum(a['observed_queue_lower']>=1000 and a['max_latency_ms']>=1000 for a,b in pairs)
    changes=[b['scheduled_max_ms']/a['scheduled_max_ms'] for a,b in pairs]
    gain=1-math.exp(statistics.mean(math.log(x) for x in changes))
    gates=dict(at_least_three_severe_defaults=severe>=3,every_pair_improves=all(x<1 for x in changes),geometric_gain_at_least_20pct=gain>=.20,
               candidate_max_latency_at_most_250ms=all(b['scheduled_max_ms']<=250 for a,b in pairs),candidate_queue_upper_at_most_250=all(b['queue_upper']<=250 for a,b in pairs),
               input_lateness_at_most_150ms=all(x['input_lateness_ms']<=150 for x in all_cases))
    return dict(advance=all(gates.values()),gates=gates,severe_defaults=severe,geometric_scheduled_latency_reduction=gain,
                prior_fixed_work_joint_gate_pass=False,field_fix_verified=False)
