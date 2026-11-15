"""Fixed state coverage/sequence rule; no optional extension or percent attribution."""
def decide(labels,quality):
    expected={'b1_baseline':'slow','b1_after_sham':'slow','b1_after_interactive':'fast',
              'b2_baseline':'slow','b2_after_interactive':'fast','b2_after_sham':'fast'}
    covered=labels.get('b1_baseline')=='slow' and labels.get('b2_baseline')=='slow'
    supported=quality and covered and labels==expected
    return dict(two_slow_baselines_observed=covered,activation_condition_supported=supported,
        conclusion='Repeated predeclared activation-associated recovery pattern observed in the fixed fixture.' if supported else 'The predeclared two-block activation pattern is not established; retain all states, no extension.',
        limitations=['Two ordered blocks do not identify a unique OS/hardware mechanism.','Five-minute gap is observed, not an assumed reset; baseline must actually be slow.',
            'Empty launch contains common scheduler/PowerShell/Python overhead; no claim ofzeroCPU.','No oldCPU/GIL/disturbance gate is upgraded.'])
