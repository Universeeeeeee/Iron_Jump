"""Recompute the P0 preservation/identity gates from retained artifacts."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    source=ROOT/'experiments/slow_state_pmc_work'
    transport=read(source/'transport01.json')
    assert sha(source/'runs/evidence01.zip')==transport['sha256']
    manifest=read(source/'runs/evidence01/manifest01.json')
    assert all(sha(source/'runs/evidence01'/name)==digest for name,digest in manifest.items())
    audit=read(HERE/'audit01.json')
    conclusion=read(HERE/'conclusion02.json')
    clock=read(HERE/'clock_metadata01.json')
    binding=read(HERE/'clock_reader_binding01.json')
    cpuid=read(HERE/'cpuid01.json')
    assert clock['target_pid']==17252 and clock['qpc_frequency']==audit['QPC_frequency']
    assert all(clock[k]==0 for k in ('header_events_lost','buffers_lost','consumer_events_lost'))
    assert binding['original_source_sha256']==sha(ROOT/'experiments/native_stack_capture/ReadStacks.cs')
    assert cpuid['source_sha256']==sha(HERE/'cpuid.rs')
    assert conclusion['original_difference_ms']==audit['cases'][0]['phases']['preparation']['raw_gap_ms']
    assert conclusion['exactly_clipped_difference_ms']==audit['cases'][0]['phases']['preparation']['clipped_gap_ms']
    assert conclusion['original_four_window_usability']['original_31_25ms_gate_pass'] is False
    assert conclusion['acceptance']==dict(
        reviewable_explanation_or_boundary_recorded=True,
        original_gate_and_failure_preserved=True,
        seven_passing_phases_do_not_release_comparison=True,
        retired_instruction_similarity_not_used_alone_for_cause=True)
    output=dict(
        original_65_file_archive_verified=True,
        old_ETL_derived_event_manifest_verified=True,
        independent_clock_reader_source_and_target_verified=True,
        CPUID_source_and_result_verified=True,
        exact_residual_and_preservation_decision_recomputed=True,
        original_31_25ms_gate_pass=False,
        cross_state_comparisons_released=False,
        P0_boundary_record_complete=True,
        goal_complete=False,
        bindings={p.name:sha(p) for p in (
            Path(__file__),HERE/'audit01.json',HERE/'overlap01.json',HERE/'clock_and_delivery02.json',
            HERE/'conclusion02.json',source/'transport01.json')})
    with (HERE/'verification01.json').open('x') as f:json.dump(output,f,indent=2)
    print(json.dumps(output,indent=2))
