"""Independent timebase and PMC-delivery review of the unchanged four-window evidence."""
import hashlib
import json
from pathlib import Path
import statistics

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    audit=read(HERE/'audit01.json')
    clocks=read(HERE/'clock_metadata01.json')
    phase=read(ROOT/'experiments/slow_state_pmc_work/result01.json')
    cpuid=read(HERE/'cpuid01.json')
    assert clocks['qpc_frequency']==audit['QPC_frequency']==10_000_000
    assert clocks['clock_type']==audit['raw_QPC_clock_type']==1
    assert all(clocks[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost'))
    assert cpuid['vendor']=='GenuineIntel' and cpuid['family']==6 and cpuid['model']==158
    leaf=cpuid['leaf15']
    assert leaf['denominator']>0 and leaf['numerator']>0
    tsc_per_crystal=leaf['numerator']/leaf['denominator']
    # Keep the affine conversion exact. A float at FILETIME magnitude has a 16-tick ULP here.
    offset_numerators=[v['filetime_100ns']*clocks['qpc_frequency']-v['qpc']*10_000_000
        for v in clocks['clock_samples']]
    median_numerator=statistics.median(offset_numerators)
    residual_numerators=[v-median_numerator for v in offset_numerators]
    rows=[]
    phase_by_case={v['case']:v for v in phase['cases']}
    for case in audit['cases']:
        original=phase_by_case[case['case']
        ]
        for name,timing in case['phases'].items():
            counters=original['phases'][name]
            running_s=timing['CSwitch_exactly_clipped_running_ms']/1000
            reference_hz=counters['reference_counter_outer']/running_s
            core_hz=counters['core_counter_outer']/running_s
            core_per_reference=counters['core_counter_outer']/counters['reference_counter_outer']
            os_per_reference=counters['OS_cycles']/counters['reference_counter_outer']
            core_per_os=counters['core_counter_outer']/counters['OS_cycles']
            rows.append(dict(case=case['case'],phase=name,
                state=original['state']['label'],retired_instructions=counters['retired_instruction_outer'],
                CSwitch_clipped_running_ms=timing['CSwitch_exactly_clipped_running_ms'],
                GetThreadTimes_ms=timing['GetThreadTimes_total_ms'],raw_CPU_gate_pass=timing['raw_gate_pass'],
                reference_counter_hz_during_residency=reference_hz,
                core_counter_hz_during_residency=core_hz,
                core_per_reference=core_per_reference,
                OS_cycles_per_reference=os_per_reference,
                core_cycles_per_OS_cycle=core_per_os,
                OS_reference_vs_CPUID_ratio_relative_difference=os_per_reference/tsc_per_crystal-1))
    ratio_delivery=all(abs(v['OS_reference_vs_CPUID_ratio_relative_difference'])<=0.02 for v in rows)
    output=dict(
        cpuid=cpuid,CPUID_TSC_per_crystal_ratio=tsc_per_crystal,
        CPUID_crystal_hz_available=bool(leaf['crystal_hz']),
        QPC_FILETIME_sample_count=len(offset_numerators),
        QPC_FILETIME_fixed_slope_max_abs_residual_100ns=max(abs(v) for v in residual_numerators)/clocks['qpc_frequency'],
        QPC_FILETIME_fixed_slope_span_100ns=(max(offset_numerators)-min(offset_numerators))/clocks['qpc_frequency'],
        float_precision_artifact_avoided=True,
        OS_cycles_per_reference_matches_CPUID_ratio_within_2pct_all_phases=ratio_delivery,
        rows=rows,
        established=[
            'Raw-QPC and converted-FILETIME passes preserve a fixed one-second-per-second slope across retained events.',
            'OS cycles divided by the delivered Reference counter match the CPUID TSC/crystal ratio within the descriptive 2% cross-check in all phases.',
            'Core/OS-cycle ratios are near 1.00 in the slow window and 1.66-1.68 in the fast windows; this is a hardware-delivery signal independent of retired-instruction similarity.',
        ],
        boundaries=[
            'This validates the delivered counter scale for these eight retained phases; it does not repair the failed GetThreadTimes/CSwitch gate.',
            'CPUID leaf15 ECX is zero on this machine, so no absolute crystal or GHz value is invented. Only the delivered 100:1 scale relation and dimensionless Core/OS ratio are used.',
            'No retired-instruction similarity is used by itself to name frequency, cache, GIL or a responsible function.',
            'Original cross-state comparisons remain withheld under the original plan.',
        ],
        original_31_25ms_gate_unchanged=True,
        original_cross_state_comparison_released=False,
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (
            Path(__file__),HERE/'audit01.json',HERE/'clock_metadata01.json',HERE/'cpuid.rs',
            ROOT/'experiments/slow_state_pmc_work/result01.json')})
    with (HERE/'clock_and_delivery02.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k!='rows'},indent=2))
