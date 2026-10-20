"""P0 decision: preserve the failed gate and state exactly what remains usable."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    audit=read(HERE/'audit01.json')
    overlap=read(HERE/'overlap01.json')
    clock=read(HERE/'clock_and_delivery02.json')
    interrupt=read(ROOT/'experiments/interrupt_scope_control/scope_audit01.json')
    slow=next(v for v in audit['cases'] if v['case']=='service01')['phases']['preparation']
    assert abs(slow['raw_gap_ms']-83.6124)<1e-6
    assert abs(slow['clipped_gap_ms']-83.5967)<1e-6
    assert not slow['raw_gate_pass'] and not slow['clipped_gate_pass_for_diagnostic_only']
    assert not overlap['any_double_counted_residency']
    assert clock['QPC_FILETIME_fixed_slope_max_abs_residual_100ns']<=20
    assert interrupt['old_83ms_gap_explained'] is False
    tick_ms=15.625
    output=dict(
        P0_review_complete=True,
        original_difference_ms=slow['raw_gap_ms'],
        exactly_clipped_difference_ms=slow['clipped_gap_ms'],
        boundary_overhang_ms=slow['outer_edge_ms'],
        GetThreadTimes_total_ms=slow['GetThreadTimes_total_ms'],
        GetThreadTimes_in_15_625ms_ticks=slow['GetThreadTimes_total_ms']/tick_ms,
        CSwitch_clipped_in_15_625ms_ticks=slow['CSwitch_exactly_clipped_running_ms']/tick_ms,
        QPC_FILETIME_max_residual_us=clock['QPC_FILETIME_fixed_slope_max_abs_residual_100ns']/10,
        explained_components=dict(
            CSwitch_boundary_overhang_ms=slow['outer_edge_ms'],
            simultaneous_cross_CPU_double_count_ms=0.0,
            lifecycle_or_TID_reuse=False,
            timebase_drift_at_83ms_scale=False),
        unresolved_residual_ms=slow['clipped_gap_ms'],
        mechanism_status=dict(
            established=[
                'CSwitch residency and GetThreadTimes are different accounting scopes in this evidence; exact marker clipping does not reconcile them.',
                'GetThreadTimes and Python thread_time are the same Windows accounting family and both expose 15.625ms quantization here.',
                'Later DPC/ISR control validates event structure but exposes coarse independent endpoint counters.',
                'Old ETL lacks DPC/ISR events, so historical interrupt overlap is not reconstructible.',
                'Dimensionless Core/OS-cycle delivery is about1.00 in slow phases and1.66-1.68 in fast phases, with OS/Reference matching CPUID100:1.',
            ],
            reasonable_hypotheses=[
                'Unrecorded ISR/DPC occupancy may contribute because it can occur while a thread remains current.',
                'Statistical/quantized Windows thread-time accounting and other kernel accounting-scope differences may contribute.',
            ],
            not_established=[
                'The fraction of the83.5967ms caused by interrupts, timer quantization oranother kernel mechanism.',
                'A unique power, thermal, cache, GIL orfunction-level cause.',
                'An absolute GHz value; CPUID did not publish the crystal frequency on this machine.',
            ]),
        original_four_window_usability=dict(
            input_output_model_and_report_identity=True,
            PID_TID_lifecycle_and_phase_boundaries=True,
            raw_PMC_and_OS_cycle_values_descriptive_only=True,
            independent_hardware_delivery_signal=True,
            frozen_cross_state_quantitative_attribution=False,
            CPU_GIL_cache_frequency_contribution_percentages=False,
            original_31_25ms_gate_pass=False),
        acceptance=dict(
            reviewable_explanation_or_boundary_recorded=True,
            original_gate_and_failure_preserved=True,
            seven_passing_phases_do_not_release_comparison=True,
            retired_instruction_similarity_not_used_alone_for_cause=True),
        P1_transition=dict(
            allowed_scope='Proceed with real 1000Hz queue-age, consumer-throughput andcontact-to-paint metrics that do not require the failed CPU-share attribution.',
            required_if_CPU_mechanism_is_remeasured='One finite actual-load capture with DPC/ISR plus CSwitch/PMC/native boundaries andpredeclared gates; never rewrite the old result.',
            synthetic_controls_are_not_field_fix=True),
        goal_complete=False,
        bindings={str(p.relative_to(ROOT)):sha(p) for p in (
            Path(__file__),HERE/'audit01.json',HERE/'overlap01.json',HERE/'clock_and_delivery02.json',
            ROOT/'experiments/interrupt_scope_control/scope_audit01.json')})
    with (HERE/'conclusion02.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output,indent=2))
